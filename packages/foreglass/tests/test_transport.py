"""The real HttpsTransport against a local TLS test server (offline; nothing leaves 127.0.0.1).

Shows that a real http.client exchange behaves as PublicClient assumes: a 3xx comes back
unfollowed, a premature close is an incomplete response, and the size cap, the total
deadline and the read timeout hold. The throwaway test CA is trusted only by the context
injected here; the default context refuses it.
"""

import http.server
import ssl
import threading
import time
import unittest
from pathlib import Path

from comuvia import RefusalError

from foreglass import HttpsTransport, PublicClient

TLS = Path(__file__).resolve().parent / "tls"
LEDGER_PATH = "/verification-explorer/ledger.json"


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # the body ends when the connection closes unless Content-Length says otherwise

    def log_message(self, *args):
        pass

    def do_GET(self):
        behaviour = self.server.behaviour
        self.server.requests.append((self.path, dict(self.headers)))
        if behaviour == "ok":
            body = b'{"ok": true}\r\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif behaviour == "redirect":
            self.send_response(302)
            self.send_header("Location", f"https://localhost:{self.server.server_port}/elsewhere.json")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif behaviour == "short":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"x" * 500)
            self.wfile.flush()
        elif behaviour == "big_declared":
            self.send_response(200)
            self.send_header("Content-Length", str(2 * 1024 * 1024))
            self.end_headers()
        elif behaviour == "big_streamed":
            self.send_response(200)
            self.end_headers()
            for _ in range(32):
                self.wfile.write(b"y" * 65536)
        elif behaviour == "drip":
            self.send_response(200)
            self.send_header("Content-Length", "20")
            self.end_headers()
            for _ in range(20):
                self.wfile.write(b"z")
                self.wfile.flush()
                time.sleep(0.15)
        elif behaviour == "stall":
            self.send_response(200)
            self.send_header("Content-Length", "10")
            self.end_headers()
            self.wfile.flush()
            time.sleep(2.0)


class LocalTlsServer:
    def __enter__(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.behaviour, self.server.requests = "ok", []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(TLS / "test-server.pem", TLS / "test-server-key.pem")
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def trusted_transport():
    return HttpsTransport(context=ssl.create_default_context(cafile=str(TLS / "test-ca.pem")))


def client(server, **options):
    options.setdefault("transport", trusted_transport())
    options.setdefault("sleep", lambda seconds: None)
    return PublicClient(origin=f"https://localhost:{server.port}", allowed_hosts=["localhost"],
                        allowed_ports=[server.port], **options)


def codes(action):
    try:
        action()
    except RefusalError as error:
        return error.codes
    raise AssertionError("not refused")


class RealTransport(unittest.TestCase):
    def test_complete_response_is_read_exactly(self):
        with LocalTlsServer() as server:
            artifact = client(server).fetch("ledger")
            self.assertEqual((artifact.status, artifact.data), (200, b'{"ok": true}\r\n'))
            path, headers = server.server.requests[0]
            self.assertEqual(path, LEDGER_PATH)
            self.assertEqual(headers.get("Accept-Encoding"), "identity")
            self.assertNotIn("Cookie", headers)

    def test_redirect_is_returned_not_followed(self):
        with LocalTlsServer() as server:
            server.server.behaviour = "redirect"
            response = trusted_transport().request(
                f"https://localhost:{server.port}{LEDGER_PATH}", headers={}, connect_timeout=5, read_timeout=5)
            try:
                self.assertEqual(response.status, 302)
                self.assertTrue(response.headers["location"].endswith("/elsewhere.json"))
            finally:
                response.close()
            self.assertEqual(len(server.server.requests), 1)

    def test_premature_close_is_an_incomplete_response(self):
        with LocalTlsServer() as server:
            server.server.behaviour = "short"
            reader = client(server, max_retries=1)
            self.assertEqual(codes(lambda: reader.fetch("ledger")), {"incomplete_response"})
            self.assertEqual(len(server.server.requests), 2)

    def test_size_cap_holds_declared_and_streamed(self):
        with LocalTlsServer() as server:
            server.server.behaviour = "big_declared"
            self.assertEqual(codes(lambda: client(server, max_bytes=1024 * 1024).fetch("ledger")), {"response_too_large"})
            server.server.behaviour = "big_streamed"
            self.assertEqual(codes(lambda: client(server, max_bytes=1024 * 1024).fetch("ledger")), {"response_too_large"})

    def test_total_deadline_and_read_timeout_hold(self):
        with LocalTlsServer() as server:
            server.server.behaviour = "drip"
            started = time.monotonic()
            self.assertEqual(codes(lambda: client(server, total_timeout=0.6).fetch("ledger")), {"deadline_exceeded"})
            self.assertLess(time.monotonic() - started, 2.5)
            server.server.behaviour = "stall"
            self.assertEqual(codes(lambda: client(server, read_timeout=0.5, max_retries=0).fetch("ledger")), {"network_error"})

    def test_default_context_refuses_the_untrusted_test_certificate(self):
        with LocalTlsServer() as server:
            reader = client(server, transport=HttpsTransport(), max_retries=0)
            self.assertEqual(codes(lambda: reader.fetch("ledger")), {"network_error"})

    def test_port_allow_list_is_explicit(self):
        with LocalTlsServer() as server:
            with self.assertRaises(RefusalError) as caught:
                PublicClient(origin=f"https://localhost:{server.port}", allowed_hosts=["localhost"])
            self.assertEqual(caught.exception.codes, {"host_not_allowed"})


if __name__ == "__main__":
    unittest.main()
