"""End-to-end checks of the installed package: Fixture A, Fixture B and a correction.

Each scenario runs through the Python API and through the command line
(``python -m comuvia``). Stores live in temporary directories; nothing is fetched.
"""

import base64
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import comuvia
from comuvia import RecordStore, check_selector, evaluate, evaluation_records, reference_to, reproduce

VECTORS = Path(__file__).resolve().parent / "vectors"
IDENTITY = json.loads((VECTORS / "identity.json").read_text(encoding="utf-8"))
RECORDS = IDENTITY["records"]
SOURCES = {k: base64.b64decode(v) for k, v in IDENTITY["sources_base64"].items()}
FIXTURE_A = ["res-harbor-weekly-e42-transcript", "asr-harbor-weekly-e42-ilsley-freight", "int-ilsley-freight-analyst-1"]
FIXTURE_B = [
    "q-port-calder-teu-2027-01", "fc-lantern-port-calder-teu-2027-01",
    "res-port-calder-bulletin-2027-01-first", "out-port-calder-teu-2027-01",
]
EVALUATED = {"evaluated_at": "2027-02-17T00:00:00Z", "recorded_by": "evaluator:example-evaluator", "recorded_at": "2027-02-17T00:00:00Z"}


def cli(*args):
    """Run the installed CLI; return (exit code, parsed JSON output)."""
    result = subprocess.run([sys.executable, "-I", "-m", "comuvia", "--json", *args], capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout) if result.stdout.strip() else None


def walk(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}/{index}")
    else:
        yield path, value


class Scenario(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, body):
        path = self.root / f"{body['id']}.r{body['revision']}.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return str(path)


class FixtureA(Scenario):
    def test_api(self):
        store_path = self.root / "store"
        RecordStore.create(store_path)
        with RecordStore(store_path, writer=True) as store:
            for record_id in FIXTURE_A:
                self.assertTrue(store.append(RECORDS[record_id]).appended)
        report = evaluate(RecordStore(store_path).records())
        self.assertEqual(report.counts["candidates"], 2)
        self.assertEqual(report.counts["excluded"], 2)
        self.assertEqual((report.counts["eligible"], report.counts["scored"], report.counts["unresolved"]), (0, 0, 0))
        reasons = {r.record["id"]: list(r.reasons) for r in report.results}
        self.assertEqual(reasons["asr-harbor-weekly-e42-ilsley-freight"],
                         ["no_declared_probability", "conditional_scenario", "no_pinned_question"])
        self.assertEqual(reasons["int-ilsley-freight-analyst-1"], ["not_a_forecast", "conditional_scenario"])
        for path, value in walk(report.as_json()):
            if "probability" in path or path.endswith("/loss"):
                self.assertNotEqual(value, 0.85, path)

    def test_selector(self):
        assertion = RECORDS["asr-harbor-weekly-e42-ilsley-freight"]
        snapshot = RECORDS["res-harbor-weekly-e42-transcript"]
        transcript = SOURCES["res-harbor-weekly-e42-transcript"]
        check = check_selector(assertion, transcript, snapshot=snapshot)
        self.assertEqual((check.result, check.checked), ("match", ("quote", "text_quote", "text_position")))
        paraphrase = copy.deepcopy(assertion)
        paraphrase["quote"]["exact"] = "Freight problems may get worse next winter if the canal shuts."
        paraphrase["selector"]["text_quote"] = {"unknown": "paraphrase_has_no_exact_text"}
        paraphrase["selector"]["text_position"] = {"unknown": "paraphrase_has_no_exact_text"}
        self.assertEqual(comuvia.validate(paraphrase), [])
        check = check_selector(paraphrase, transcript)
        self.assertEqual(check.result, "mismatch")
        self.assertEqual([i.code for i in check.issues], ["quote_mismatch"])
        paraphrase["quote"]["verbatim"] = False
        self.assertEqual(check_selector(paraphrase, transcript).result, "unavailable")
        self.assertEqual(check_selector(assertion, None).result, "unavailable")
        self.assertEqual(check_selector(assertion, transcript.replace(b"\n", b"\r\n"), snapshot=snapshot).result, "mismatch")

    def test_cli(self):
        store = str(self.root / "store")
        self.assertEqual(cli("store", "init", store)[0], 0)
        code, _ = cli("store", "append", store, *[self.write(RECORDS[i]) for i in FIXTURE_A])
        self.assertEqual(code, 0)
        code, report = cli("evaluate", "--store", store)
        self.assertEqual(code, 0)
        self.assertEqual(report["counts"]["excluded"], 2)
        self.assertIsNone(report["aggregate"])
        transcript = self.root / "transcript.txt"
        transcript.write_bytes(SOURCES["res-harbor-weekly-e42-transcript"])
        code, result = cli("verify", self.write(RECORDS["asr-harbor-weekly-e42-ilsley-freight"]),
                           "--content", str(transcript), "--store", store)
        self.assertEqual((code, result["selector"]["result"]), (0, "match"))
        self.assertEqual(result["references"], [{"pointer": "/resource", "result": "match"}])


class FixtureB(Scenario):
    def test_api_evaluate_append_reproduce_and_correct(self):
        store_path = self.root / "store"
        RecordStore.create(store_path)
        with RecordStore(store_path, writer=True) as store:
            for record_id in FIXTURE_B:
                store.append(RECORDS[record_id])
            records = store.records()
            report = evaluate(records)
            (result,) = report.results
            self.assertEqual((result.status, result.reasons), ("scored", ()))
            self.assertEqual(json.dumps(result.loss), "0.09000000000000002")
            (first_evaluation,) = evaluation_records(report, records, **EVALUATED)
            self.assertEqual(comuvia.validate(first_evaluation), [])
            store.append(first_evaluation)
            self.assertEqual(reproduce(first_evaluation, store.records()).result, "match")

            outcome_r1 = RECORDS["out-port-calder-teu-2027-01"]
            r1_path = store_path / "records" / (comuvia.record_digest(outcome_r1).removeprefix("sha256:") + ".json")
            r1_bytes = r1_path.read_bytes()
            correction = copy.deepcopy(outcome_r1)
            correction.update(revision=2, predecessor=reference_to(outcome_r1), resolved_value=0,
                              recorded_at="2027-02-20T10:00:00Z")
            store.append(correction)
            records = store.records()
            report = evaluate(records)
            (result,) = report.results
            self.assertEqual(json.dumps(result.loss), "0.48999999999999994")
            self.assertEqual(result.outcome["revision"], 2)
            for body in evaluation_records(report, records, **EVALUATED):
                store.append(body)
        self.assertEqual(r1_path.read_bytes(), r1_bytes)
        reader = RecordStore(store_path)
        self.assertEqual(reader.latest()[("outcome", "out-port-calder-teu-2027-01")]["revision"], 2)
        self.assertEqual(reader.get("outcome", "out-port-calder-teu-2027-01", 1), outcome_r1)
        evaluations = {b["id"]: b for b in reader.records() if b["record_type"] == "evaluation"}
        self.assertEqual(len(evaluations), 2)
        for body in evaluations.values():
            self.assertEqual(reproduce(body, reader.records()).result, "match", body["id"])
        self.assertEqual(json.dumps(evaluations[first_evaluation["id"]]["result"]["loss"]), "0.09000000000000002")
        self.assertTrue(reader.verify().ok)

    def test_reproduce_detects_a_changed_result(self):
        records = [RECORDS[i] for i in FIXTURE_B]
        (body,) = evaluation_records(evaluate(records), records, **EVALUATED)
        body["result"]["loss"] = 0.09
        self.assertEqual(reproduce(body, records).result, "mismatch")
        body["scoring_rule"] = {**body["scoring_rule"], "digest": "sha256:" + "0" * 64}
        self.assertEqual(reproduce(body, records).result, "unavailable")
        self.assertEqual(reproduce(evaluation_records(evaluate(records), records, **EVALUATED)[0], records[:1]).result, "unavailable")

    def test_cli(self):
        store = str(self.root / "store")
        cli("store", "init", store)
        code, appended = cli("store", "append", store, *[self.write(RECORDS[i]) for i in FIXTURE_B])
        self.assertEqual((code, len(appended["entries"])), (0, 4))
        code, report = cli("evaluate", "--store", store, "--append", "--evaluated-at", EVALUATED["evaluated_at"],
                           "--recorded-by", EVALUATED["recorded_by"], "--recorded-at", EVALUATED["recorded_at"])
        self.assertEqual(code, 0)
        self.assertEqual(json.dumps(report["results"][0]["loss"]), "0.09000000000000002")
        self.assertEqual(len(report["evaluation_records"]), 1)
        code, reproduced = cli("reproduce", "--store", store)
        self.assertEqual((code, [r["result"] for r in reproduced["results"]]), (0, ["match"]))
        code, verified = cli("store", "verify", store)
        self.assertEqual((code, verified["ok"], verified["entries"]), (0, True, 5))
        self.assertIn("checkpoint", verified["detection_limit"])
        code, _ = cli("evaluate", "--store", store, "--append")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
