"""Record store behavior: single writer, refusals, idempotence, crash/tamper reports, no rewrite path."""

import base64
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import comuvia
from comuvia import RecordStore, RefusalError, record_digest, reference_to

VECTORS = Path(__file__).resolve().parent / "vectors"
RECORDS = json.loads((VECTORS / "identity.json").read_text(encoding="utf-8"))["records"]
QUESTION = RECORDS["q-port-calder-teu-2027-01"]
FORECAST = RECORDS["fc-lantern-port-calder-teu-2027-01"]

CYCLES = 300

HOLDER = """
import os, sys
from comuvia import RecordStore
store = RecordStore(sys.argv[1], writer=True)
if sys.argv[2] == "torn":
    # Simulate dying mid-append: a body renamed into records/ but its index line torn.
    import json
    from comuvia import canonicalize, record_digest
    body = json.loads(sys.argv[3])
    name = record_digest(body).removeprefix("sha256:") + ".json"
    open(os.path.join(sys.argv[1], "records", name), "wb").write(canonicalize(body))
    open(os.path.join(sys.argv[1], "index.jsonl"), "ab").write(b'{"digest":"sha256:')
    os._exit(0)
print("locked", os.getpid(), flush=True)
sys.stdin.readline()
if sys.argv[2] == "hold":
    store.close()
"""

# A separate reader process running `comuvia store verify` in a loop until told to stop.
VERIFY_LOOP = """
import contextlib, io, os, sys
from comuvia.cli import main
store, stop = sys.argv[1], sys.argv[2]
runs = 0
while not os.path.exists(stop):
    with contextlib.redirect_stdout(io.StringIO()):
        main(["store", "verify", store, "--json"])
    runs += 1
print(runs)
"""


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "store"
        RecordStore.create(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def codes(self, action):
        with self.assertRaises(RefusalError) as caught:
            action()
        return caught.exception.codes

    def holder(self, mode):
        process = subprocess.Popen([sys.executable, "-I", "-c", HOLDER, str(self.path), mode],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        word, pid = process.stdout.readline().split()
        self.assertEqual(word, "locked")
        return process, pid

    def test_second_writer_in_another_process_is_refused_naming_the_holder(self):
        process, pid = self.holder("hold")
        try:
            with self.assertRaises(RefusalError) as caught:
                RecordStore(self.path, writer=True)
            self.assertEqual(caught.exception.codes, {"store_locked"})
            self.assertIn(f"pid={pid},", str(caught.exception.issues[0].message))
            self.assertIn(f"pid={pid},", RecordStore(self.path).verify().lock_holder)
            self.assertEqual(len(RecordStore(self.path).entries()), 0)  # readers need no lock
        finally:
            process.communicate("release" + chr(10), timeout=30)
        self.assertIsNone(RecordStore(self.path).verify().lock_holder)  # details blanked on close
        with RecordStore(self.path, writer=True) as store:
            store.append(QUESTION)
        self.assertTrue((self.path / "writer.lock").exists())  # the lock file is persistent

    def test_killed_writer_releases_the_lock(self):
        process, pid = self.holder("kill")
        process.kill()
        process.wait(timeout=30)
        self.assertIn(f"pid={pid},", RecordStore(self.path).verify().lock_holder)  # stale text, not a lock
        with RecordStore(self.path, writer=True) as store:
            store.append(QUESTION)

    def test_writer_dying_mid_append_leaves_guarded_residue(self):
        subprocess.run([sys.executable, "-I", "-c", HOLDER, str(self.path), "torn", json.dumps(QUESTION)],
                       check=True, capture_output=True, timeout=60)
        report = RecordStore(self.path).verify()
        self.assertLessEqual({"torn_index_line", "orphan_body"}, {i.code for i in report.issues})
        with RecordStore(self.path, writer=True) as store:  # the dead writer's OS lock is gone
            self.assertEqual(self.codes(lambda: store.append(QUESTION)), {"index_torn"})
            store.truncate_torn_tail()
            self.assertTrue(store.append(QUESTION).appended)
        self.assertTrue(RecordStore(self.path).verify().ok)

    def writer_cycles(self):
        """Open and close a writer CYCLES times (appending every 50th); return (close errors, refusals)."""
        close_errors, refusals, previous = [], [], None
        for cycle in range(CYCLES):
            try:
                store = RecordStore(self.path, writer=True)
            except RefusalError as error:
                refusals.append((cycle, sorted(error.codes)))
                continue
            if cycle % 50 == 0:
                body = copy.deepcopy(QUESTION)
                body.update(revision=cycle // 50 + 1, predecessor=None if previous is None else reference_to(previous))
                store.append(body)
                previous = body
            try:
                store.close()
            except OSError as error:
                close_errors.append((cycle, repr(error)))
        return close_errors, refusals

    def test_stress_reader_thread_never_disturbs_the_writer(self):
        import threading

        stop, reader_errors, reads = threading.Event(), [], [0]

        def reader():
            while not stop.is_set():
                try:
                    RecordStore(self.path).verify()
                    reads[0] += 1
                except Exception as error:  # noqa: BLE001 - any reader failure is a finding
                    reader_errors.append(repr(error))

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            close_errors, refusals = self.writer_cycles()
        finally:
            stop.set()
            thread.join(timeout=60)
        self.assertEqual(close_errors, [])
        self.assertEqual(refusals, [])
        self.assertEqual(reader_errors, [])
        self.assertGreater(reads[0], 0)
        with RecordStore(self.path, writer=True):
            pass
        self.assertTrue(RecordStore(self.path).verify().ok)

    def test_stress_reader_process_running_cli_verify(self):
        stop = Path(self.tmp.name) / "stop"
        reader = subprocess.Popen([sys.executable, "-I", "-c", VERIFY_LOOP, str(self.path), str(stop)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            close_errors, refusals = self.writer_cycles()
        finally:
            stop.write_text("stop")
            output, errors = reader.communicate(timeout=120)
        self.assertEqual(reader.returncode, 0, errors)
        self.assertGreater(int(output.strip()), 0)
        self.assertEqual(close_errors, [])
        self.assertEqual(refusals, [])
        with RecordStore(self.path, writer=True):
            pass
        self.assertTrue(RecordStore(self.path).verify().ok)

    def test_second_writer_in_same_process_is_refused(self):
        with RecordStore(self.path, writer=True):
            self.assertEqual(self.codes(lambda: RecordStore(self.path, writer=True)), {"store_locked"})

    def test_append_refusals_and_idempotence(self):
        with RecordStore(self.path, writer=True) as store:
            self.assertEqual(self.codes(lambda: store.append(FORECAST)), {"unresolved_reference"})
            first = store.append(QUESTION)
            self.assertTrue(first.appended)
            again = store.append(copy.deepcopy(QUESTION))
            self.assertEqual((again.appended, again.sequence), (False, first.sequence))
            self.assertEqual(len(store.entries()), 1)
            conflicting = copy.deepcopy(QUESTION)
            conflicting["text"] += " (edited)"
            self.assertEqual(self.codes(lambda: store.append(conflicting)), {"revision_conflict"})
            wrong_link = copy.deepcopy(FORECAST)
            wrong_link["question"]["digest"] = "sha256:" + "0" * 64
            self.assertEqual(self.codes(lambda: store.append(wrong_link)), {"reference_digest_mismatch"})
            invalid = copy.deepcopy(FORECAST)
            invalid["output"]["probability"] = 1.2
            self.assertEqual(self.codes(lambda: store.append(invalid)), {"out_of_range"})
            skipped = copy.deepcopy(QUESTION)
            skipped.update(revision=3, predecessor={**reference_to(QUESTION), "revision": 2})
            self.assertEqual(self.codes(lambda: store.append(skipped)), {"unresolved_reference"})
            self.assertTrue(store.append(FORECAST).appended)
        self.assertEqual(self.codes(lambda: RecordStore(self.path).append(QUESTION)), {"read_only_store"})
        self.assertTrue(RecordStore(self.path).verify().ok)

    def test_no_public_rewrite_path(self):
        names = {n for n in dir(RecordStore) if not n.startswith("_")}
        for forbidden in ("update", "delete", "remove", "replace", "put", "overwrite", "set", "rewrite", "edit"):
            self.assertFalse({n for n in names if forbidden in n}, forbidden)
        self.assertEqual(names, {
            "append", "close", "create", "entries", "get", "get_by_digest",
            "is_writer", "latest", "records", "truncate_torn_tail", "verify",
        })

    def test_verify_reports_crash_and_tamper_by_name(self):
        with RecordStore(self.path, writer=True) as store:
            store.append(QUESTION)
            store.append(FORECAST)
        self.assertTrue(RecordStore(self.path).verify().ok)
        index = self.path / "index.jsonl"
        with open(index, "ab") as handle:
            handle.write(b'{"digest":"sha256:')
        orphan = copy.deepcopy(QUESTION)
        orphan.update(revision=2, predecessor=reference_to(QUESTION))
        orphan_digest = record_digest(orphan).removeprefix("sha256:")
        (self.path / "records" / f"{orphan_digest}.json").write_bytes(comuvia.canonicalize(orphan))
        forecast_file = self.path / "records" / (record_digest(FORECAST).removeprefix("sha256:") + ".json")
        forecast_file.write_bytes(forecast_file.read_bytes().replace(b'"probability":0.7', b'"probability":0.8'))
        (self.path / "tmp" / "interrupted.tmp").write_bytes(b"partial")
        report = RecordStore(self.path).verify()
        codes = {i.code for i in report.issues}
        self.assertLessEqual({"torn_index_line", "orphan_body", "body_digest_mismatch", "leftover_temp_file"}, codes)
        self.assertFalse(report.ok)
        self.assertIn("checkpoint", report.detection_limit)
        self.assertEqual(self.codes(lambda: RecordStore(self.path).get_by_digest(record_digest(FORECAST))),
                         {"body_digest_mismatch"})
        with RecordStore(self.path, writer=True) as store:
            self.assertEqual(self.codes(lambda: store.append(orphan)), {"index_torn"})
            self.assertEqual(store.truncate_torn_tail(), len(b'{"digest":"sha256:'))
            self.assertTrue(store.append(orphan).appended)  # the orphan body is simply re-indexed
        codes = {i.code for i in RecordStore(self.path).verify().issues}
        self.assertNotIn("torn_index_line", codes)
        self.assertNotIn("orphan_body", codes)

    def test_verify_reports_missing_body_and_duplicate_entry(self):
        with RecordStore(self.path, writer=True) as store:
            store.append(QUESTION)
        index = self.path / "index.jsonl"
        line = index.read_bytes()
        index.write_bytes(line + line.replace(b'"sequence":1', b'"sequence":2'))
        codes = {i.code for i in RecordStore(self.path).verify().issues}
        self.assertIn("duplicate_index_entry", codes)
        os.remove(self.path / "records" / (record_digest(QUESTION).removeprefix("sha256:") + ".json"))
        self.assertIn("missing_body", {i.code for i in RecordStore(self.path).verify().issues})

    def test_digest_text_cannot_name_a_path_outside_records(self):
        (self.path.parent / "x.json").write_text("{}")
        for digest in ("sha256:../x", "sha256:../../x", "../x", "sha256:" + "A" * 64):
            self.assertEqual(self.codes(lambda: RecordStore(self.path).get_by_digest(digest)), {"malformed_digest"})
        with open(self.path / "index.jsonl", "ab") as index:
            index.write(comuvia.canonicalize({"sequence": 1, "record_type": "question", "id": "q", "revision": 1,
                                              "digest": "sha256:../x"}) + bytes([10]))
        self.assertIn("index_entry_invalid", {i.code for i in RecordStore(self.path).verify().issues})

    def test_create_and_open_refusals(self):
        self.assertEqual(self.codes(lambda: RecordStore.create(self.path)), {"store_exists"})
        self.assertEqual(self.codes(lambda: RecordStore(Path(self.tmp.name))), {"not_a_store"})


if __name__ == "__main__":
    unittest.main()
