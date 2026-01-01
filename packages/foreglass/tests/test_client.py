"""Reader transport rules, with an injected transport. These tests never touch the network."""

import json
import subprocess
import sys
import unittest

from comuvia import RefusalError

import foreglass
from foreglass import PublicClient
from foreglass.client import USER_AGENT

LEDGER_URL = "https://foreglass.ai/verification-explorer/ledger.json"


class FakeResponse:
    def __init__(self, status, headers=None, chunks=(), read_error=None):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._chunks = list(chunks)
        self._read_error = read_error
        self.closed = False

    def read(self, size):
        if self._read_error:
            raise self._read_error
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        self.closed = True


class FakeTransport:
    """Replays a scripted list of responses or exceptions and records every request."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def request(self, url, *, headers, connect_timeout, read_timeout):
        self.requests.append({"url": url, "headers": dict(headers), "connect": connect_timeout, "read": read_timeout})
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def ok(body=b"{}", **headers):
    return FakeResponse(200, {"Content-Type": "application/json", **headers}, [body])


def client(script, **options):
    sleeps = []
    transport = FakeTransport(script)
    options.setdefault("sleep", sleeps.append)
    options.setdefault("clock", lambda: 1_790_000_000.0)
    return PublicClient(transport=transport, **options), transport, sleeps


def codes(action):
    try:
        action()
    except RefusalError as error:
        return error.codes
    raise AssertionError("not refused")


class ReaderRules(unittest.TestCase):
    def test_import_and_construction_make_no_request(self):
        probe = (
            "import sys\n"
            "events = []\n"
            "sys.addaudithook(lambda e, a: events.append(e) if e.startswith(('socket.', 'urllib.', 'http.')) else None)\n"
            "import foreglass\n"
            "client = foreglass.PublicClient()\n"
            "client.url_for('ledger')\n"
            "foreglass.capabilities()\n"
            "print(len(events))\n"
        )
        result = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=60)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "0"), result.stderr)

    def test_www_redirect_to_apex_is_followed_and_bytes_are_exact(self):
        body = b'{\r\n  "a": 1\r\n}\r\n'
        reader, transport, _ = client([
            FakeResponse(308, {"Location": LEDGER_URL}),
            ok(body),
        ], origin="https://www.foreglass.ai")
        artifact = reader.fetch("ledger")
        self.assertEqual(artifact.data, body)
        self.assertEqual((artifact.request_url, artifact.final_url), ("https://www.foreglass.ai/verification-explorer/ledger.json", LEDGER_URL))
        self.assertEqual((artifact.status, artifact.content_type, artifact.data_origin), (200, "application/json", "observed"))
        headers = transport.requests[0]["headers"]
        self.assertEqual(headers["User-Agent"], USER_AGENT)
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertFalse({"Cookie", "Authorization"} & set(headers))

    def test_redirect_rules(self):
        off_list = client([FakeResponse(302, {"Location": "https://example.org/x.json"})])[0]
        self.assertEqual(codes(lambda: off_list.fetch("ledger")), {"redirect_off_origin"})
        downgrade = client([FakeResponse(301, {"Location": "http://foreglass.ai/x.json"})])[0]
        self.assertEqual(codes(lambda: downgrade.fetch("ledger")), {"insecure_redirect"})
        hops = [FakeResponse(307, {"Location": LEDGER_URL}) for _ in range(4)] + [ok()]
        too_many, transport, _ = client(hops)
        self.assertEqual(codes(lambda: too_many.fetch("ledger")), {"too_many_redirects"})
        self.assertEqual(len(transport.requests), 4)
        three = client([FakeResponse(307, {"Location": LEDGER_URL}) for _ in range(3)] + [ok()])[0]
        self.assertEqual(three.fetch("ledger").status, 200)

    def test_plain_http_and_off_list_origins_are_refused(self):
        self.assertEqual(codes(lambda: PublicClient(origin="http://foreglass.ai")), {"insecure_url"})
        self.assertEqual(codes(lambda: PublicClient(origin="https://example.org")), {"host_not_allowed"})
        custom = PublicClient(origin="https://mirror.example.org", allowed_hosts=["mirror.example.org"], transport=FakeTransport([ok()]))
        self.assertEqual(custom.fetch("ledger").final_url, "https://mirror.example.org/verification-explorer/ledger.json")
        self.assertEqual(codes(lambda: PublicClient().url_for("anything")), {"unknown_artifact"})

    def test_size_cap_refuses_mid_stream_and_by_declared_length(self):
        streamed, _, _ = client([FakeResponse(200, {}, [b"x" * 600, b"y" * 600])], max_bytes=1000)
        self.assertEqual(codes(lambda: streamed.fetch("ledger")), {"response_too_large"})
        declared, _, _ = client([FakeResponse(200, {"Content-Length": "5000"}, [b"x"])], max_bytes=1000)
        self.assertEqual(codes(lambda: declared.fetch("ledger")), {"response_too_large"})
        encoded, _, _ = client([FakeResponse(200, {"Content-Encoding": "gzip"}, [b"x"])])
        self.assertEqual(codes(lambda: encoded.fetch("ledger")), {"unsupported_content_encoding"})

    def test_timeouts_retries_and_backoff(self):
        reader, transport, sleeps = client([TimeoutError("read timed out"), OSError("reset"), ok()],
                                           connect_timeout=2.5, read_timeout=7.0)
        self.assertEqual(reader.fetch("ledger").status, 200)
        self.assertEqual([(r["connect"], r["read"]) for r in transport.requests], [(2.5, 7.0)] * 3)
        self.assertEqual(sleeps, [1.0, 2.0])
        failing, transport, sleeps = client([FakeResponse(503), FakeResponse(502), FakeResponse(500), ok()])
        self.assertEqual(codes(lambda: failing.fetch("ledger")), {"http_status"})
        self.assertEqual(len(transport.requests), 3)  # one try plus max_retries=2
        down, transport, _ = client([TimeoutError(), TimeoutError(), TimeoutError()])
        self.assertEqual(codes(lambda: down.fetch("ledger")), {"network_error"})
        self.assertEqual(len(transport.requests), 3)

    def test_short_body_against_content_length_is_incomplete(self):
        short = lambda: FakeResponse(200, {"Content-Length": "1000"}, [b"x" * 500])
        reader, transport, sleeps = client([short(), short(), short()])
        self.assertEqual(codes(lambda: reader.fetch("ledger_ots")), {"incomplete_response"})
        self.assertEqual((len(transport.requests), sleeps), (3, [1.0, 2.0]))
        recovered, _, _ = client([short(), FakeResponse(200, {"Content-Length": "1000"}, [b"x" * 600, b"y" * 400])])
        self.assertEqual(recovered.fetch("ledger_ots").byte_length, 1000)
        longer, _, _ = client([FakeResponse(200, {"Content-Length": "10"}, [b"x" * 20])] * 3)
        self.assertEqual(codes(lambda: longer.fetch("ledger_ots")), {"incomplete_response"})

    def test_protocol_error_during_read_is_a_network_error(self):
        import http.client

        broken = lambda: FakeResponse(200, {}, read_error=http.client.IncompleteRead(b"partial", 100))
        reader, transport, _ = client([broken(), broken(), broken()])
        self.assertEqual(codes(lambda: reader.fetch("fragility_latest")), {"network_error"})
        self.assertEqual(len(transport.requests), 3)

    def test_failed_fetch_leaves_the_accepted_snapshot_unchanged(self):
        import tempfile
        from pathlib import Path

        from foreglass import SnapshotArchive

        ledger = b'{"_schema": "foreglass.verification-ledger/v1", "counts": {"included": 0}, "lanes": []}'
        with tempfile.TemporaryDirectory() as tmp:
            archive = SnapshotArchive.create(Path(tmp) / "archive")
            good, _, _ = client([ok(ledger, **{"Content-Length": str(len(ledger))})])
            accepted = archive.intake(good.fetch_bundle(["ledger"]))
            self.assertTrue(accepted.accepted)
            short = lambda: FakeResponse(200, {"Content-Length": "1000"}, [b"x" * 500])
            bad, _, _ = client([short(), short(), short()])
            self.assertEqual(codes(lambda: bad.fetch_bundle(["ledger"])), {"incomplete_response"})
            self.assertEqual(archive.accepted().snapshot_id, accepted.snapshot_id)

    def test_total_deadline_bounds_a_slow_drip(self):
        ticks = iter([0.0, 0.0, 1.0, 50.0, 200.0, 400.0])
        drip = FakeResponse(200, {}, [b"a", b"b", b"c", b"d"])
        reader, _, _ = client([drip], total_timeout=100.0, monotonic=lambda: next(ticks))
        self.assertEqual(codes(lambda: reader.fetch("ledger")), {"deadline_exceeded"})

    def test_retry_after_is_honoured_up_to_the_cap(self):
        reader, _, sleeps = client([FakeResponse(429, {"Retry-After": "5"}), FakeResponse(429, {"Retry-After": "3600"}), ok()],
                                   retry_after_cap=30.0)
        reader.fetch("ledger")
        self.assertEqual(sleeps, [5.0, 30.0])

    def test_client_errors_are_not_retried(self):
        reader, transport, sleeps = client([FakeResponse(404), ok()])
        self.assertEqual(codes(lambda: reader.fetch("ledger")), {"http_status"})
        self.assertEqual((len(transport.requests), sleeps), (1, []))

    def test_archive_files_are_named_by_the_index_and_verified(self):
        body = b"archived ledger bytes"
        import hashlib
        entry = {"file": "2026-09-20.json", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "ots": "2026-09-20.json.ots"}
        reader, transport, _ = client([ok(body)])
        artifact = reader.fetch_archive_file(entry)
        self.assertEqual(transport.requests[0]["url"], "https://foreglass.ai/verification-explorer/ledger-archive/2026-09-20.json")
        self.assertEqual(artifact.declared_sha256, "sha256:" + entry["sha256"])
        wrong = client([ok(b"different bytes")])[0]
        self.assertEqual(codes(lambda: wrong.fetch_archive_file(entry)), {"digest_mismatch"})
        for name in ("../ledger.json", "a/b.json", "", None):
            self.assertEqual(codes(lambda: reader.fetch_archive_file({**entry, "file": name})), {"invalid_archive_entry"})

    def test_capabilities_are_truthful(self):
        caps = foreglass.capabilities()
        self.assertEqual(set(caps["unsupported"]) >= {"custom_execution", "mcp", "submission", "outcome_normalization"}, True)
        public = {name for name in dir(PublicClient) if not name.startswith("_")}
        self.assertEqual(public, {"fetch", "fetch_archive_file", "fetch_bundle", "url_for"})
        for name in dir(foreglass):
            self.assertFalse(any(word in name.lower() for word in ("submit", "upload", "execute", "mcp")), name)
        json.dumps(caps)


if __name__ == "__main__":
    unittest.main()
