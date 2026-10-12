"""The Faustus copilot in Mercator's Hoard: the stdlib relay, the launcher in the pages, the manifest and the off switch."""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from contextlib import closing
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import mercator
import mercator_copilot
from support import running_server

ROOT = Path(mercator.__file__).resolve().parent

try:  # the vendored Hoard Link gets the copilot modules when it is synced from the shared library
    from hoard_link import copilot as shared  # noqa: F401
    from hoard_link.copilot_launcher import LAUNCHER_JS  # noqa: F401
    HAVE_COPILOT = True
except ImportError:
    HAVE_COPILOT = False


class FakeFaustus:
    """Just enough of Faustus: capabilities, the panel script, an echo, a held SSE stream and an error."""

    def __init__(self) -> None:
        self.received: list[dict] = []
        self.release = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, body, kind="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/hoard-copilot/capabilities":
                    self._send(200, json.dumps({"contract_version": "1.0"}).encode())
                elif self.path == "/api/hoard-copilot/panel.js":
                    self._send(200, b"export const panel = 1;", "application/javascript")
                elif self.path == "/api/chat/boom":
                    self._send(500, json.dumps({"error": "upstream broke"}).encode())
                else:
                    self._send(404, b"{}")

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                outer.received.append({"path": self.path, "body": body, "authorization": self.headers.get("Authorization"),
                                       "content_type": self.headers.get("Content-Type"),
                                       "client_version": self.headers.get("X-Faustus-Client-Version")})
                if self.path == "/api/chat/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b"data: one\n\n")
                    self.wfile.flush()
                    outer.release.wait(10)
                    self.wfile.write(b"data: two\n\n")
                else:
                    self._send(200, body, self.headers.get("Content-Type", "application/json"))

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def stop(self) -> None:
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def call(port, method, path, body=None, headers=None):
    with closing(HTTPConnection("127.0.0.1", port, timeout=10)) as conn:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()


@unittest.skipUnless(HAVE_COPILOT, "the vendored hoard_link has no copilot modules yet")
class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.faustus = FakeFaustus()
        self.addCleanup(self.faustus.stop)
        self.copilot = mercator_copilot.Copilot.create(self.temp.name, faustus_urls=[self.faustus.url], token="secret")
        patcher = patch.object(mercator, "COPILOT", self.copilot)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_info_names_this_app_and_a_stable_data_space(self):
        with running_server() as port:
            status, _, body = call(port, "GET", "/api/copilot/info")
            info = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual((info["app_id"], info["app_name"]), ("mercator", "Mercator's Hoard"))
            self.assertEqual(info["panel_url"], "/api/copilot/panel.js")
            self.assertTrue(info["data_space_id"])
            again = mercator_copilot.Copilot.create(self.temp.name, faustus_urls=[self.faustus.url], token="")
            self.assertEqual(again.space_id, info["data_space_id"])  # stored in copilot-space-id: it survives restarts

    def test_panel_and_launcher_are_served(self):
        with running_server() as port:
            status, headers, body = call(port, "GET", "/api/copilot/panel.js")
            self.assertEqual((status, body), (200, b"export const panel = 1;"))
            self.assertIn("javascript", headers["Content-Type"])
            status, headers, body = call(port, "GET", "/api/copilot/launcher.js")
            self.assertEqual(status, 200)
            self.assertIn("javascript", headers["Content-Type"])
            self.assertIn(b"faustus-chat", body)
            self.assertEqual(call(port, "GET", "/api/copilot/nope")[0], 404)

    def test_proxy_forces_this_app_into_the_context_and_keeps_the_token_on_the_server(self):
        envelope = {"path": "/api/chat/echo", "method": "POST", "headers": {"X-Faustus-Client-Version": "9", "Cookie": "x"},
                    "body": {"message": "hi", "context": {"origin": {"app_id": "someone-else", "keep": 1}, "view": {"page": "p"}}}}
        with running_server() as port:
            status, _, body = call(port, "POST", "/api/copilot/proxy", json.dumps(envelope), {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        sent = self.faustus.received[-1]
        context = json.loads(sent["body"])["context"]
        self.assertEqual(context["origin"]["app_id"], "mercator")
        self.assertEqual(context["origin"]["data_space_id"], self.copilot.space_id)
        self.assertEqual(context["origin"]["keep"], 1)
        self.assertEqual(context["view"], {"page": "p"})
        self.assertEqual((sent["authorization"], sent["client_version"]), ("Bearer secret", "9"))
        self.assertEqual(json.loads(body)["context"]["origin"]["app_id"], "mercator")

    def test_proxy_rewrites_the_context_part_of_a_multipart_upload_and_keeps_the_file(self):
        boundary = "XX"
        parts = (f'--{boundary}\r\nContent-Disposition: form-data; name="context"\r\n\r\n{json.dumps({"origin": {"app_id": "x"}})}\r\n'
                 f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.bin"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
        payload = parts + bytes(range(256)) + f"\r\n--{boundary}--\r\n".encode()
        envelope = {"path": "/api/chat/upload", "method": "POST", "raw_body": base64.b64encode(payload).decode(),
                    "content_type": f"multipart/form-data; boundary={boundary}"}
        with running_server() as port:
            self.assertEqual(call(port, "POST", "/api/copilot/proxy", json.dumps(envelope))[0], 200)
        sent = self.faustus.received[-1]["body"]
        self.assertIn(b'"app_id": "mercator"', sent)
        self.assertNotIn(b'"app_id": "x"', sent)
        self.assertIn(bytes(range(256)), sent)

    def test_proxy_refuses_what_is_not_a_copilot_operation(self):
        with running_server() as port:
            for path in ("/api/other", "//evil.example/api/chat/x", "api/chat/x", 7, None):
                status, _, _ = call(port, "POST", "/api/copilot/proxy", json.dumps({"path": path}))
                self.assertEqual(status, 400, path)
            self.assertEqual(call(port, "POST", "/api/copilot/proxy", "not json")[0], 400)
            self.assertEqual(call(port, "POST", "/api/copilot/proxy", json.dumps([1]))[0], 400)
        self.assertEqual(self.faustus.received, [])

    def test_upstream_errors_pass_through(self):
        with running_server() as port:
            envelope = {"path": "/api/chat/boom", "method": "GET"}
            status, _, body = call(port, "POST", "/api/copilot/proxy", json.dumps(envelope))
        self.assertEqual((status, json.loads(body)), (500, {"error": "upstream broke"}))

    def test_a_stream_reaches_the_browser_before_it_ends(self):
        envelope = {"path": "/api/chat/stream", "method": "POST", "body": {"message": "hi"}}
        with running_server() as port, closing(HTTPConnection("127.0.0.1", port, timeout=10)) as conn:
            conn.request("POST", "/api/copilot/proxy", body=json.dumps(envelope))
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn("text/event-stream", response.getheader("Content-Type"))
            self.assertEqual(response.readline(), b"data: one\n")  # arrives while Faustus is still holding the stream
            self.faustus.release.set()
            self.assertIn(b"data: two", response.read())

    def test_without_faustus_the_relay_answers_503(self):
        down = mercator_copilot.Copilot.create(self.temp.name, faustus_urls=["http://127.0.0.1:9"], token="")
        with patch.object(mercator, "COPILOT", down), running_server() as port:
            self.assertEqual(call(port, "GET", "/api/copilot/info")[0], 503)
            self.assertEqual(call(port, "GET", "/api/copilot/panel.js")[0], 503)
            self.assertEqual(call(port, "POST", "/api/copilot/proxy", json.dumps({"path": "/api/chat/x"}))[0], 503)
            self.assertEqual(call(port, "GET", "/api/health")[0], 200)  # the app itself never depends on Faustus

    def test_the_relay_obeys_the_request_guard(self):
        with running_server() as port:
            status, _, _ = call(port, "GET", "/api/copilot/info", headers={"Host": "evil.example"})
            self.assertEqual(status, 403)
            status, _, _ = call(port, "POST", "/api/copilot/proxy", json.dumps({"path": "/api/chat/x"}),
                                {"Origin": "https://evil.example"})
            self.assertEqual(status, 403)

    def test_html_pages_carry_the_launcher_and_only_they_may_use_inline_styles(self):
        with running_server() as port:
            for path in ("/", "/publicacion"):
                status, headers, body = call(port, "GET", path)
                self.assertEqual(status, 200)
                self.assertIn(b'<script type="module" src="/api/copilot/launcher.js"></script></body>', body)
                self.assertIn("style-src 'self' 'unsafe-inline'", headers["Content-Security-Policy"])
                self.assertIn("script-src 'self';", headers["Content-Security-Policy"] + ";")
                self.assertIn(b'<script src="/copilot.js" defer></script>', body)
            for path in ("/app.js", "/api/health", "/copilot.js"):
                status, headers, body = call(port, "GET", path)
                self.assertEqual(status, 200)
                self.assertNotIn(b"launcher.js", body)
                self.assertIn("style-src 'self';", headers["Content-Security-Policy"])


@unittest.skipUnless(HAVE_COPILOT, "the vendored hoard_link has no copilot modules yet")
class OffSwitchTests(unittest.TestCase):
    def test_hoard_copilot_0_turns_the_panel_off(self):
        with tempfile.TemporaryDirectory() as data, patch.dict("os.environ", {"HOARD_COPILOT": "0"}):
            self.assertIsNone(mercator_copilot.Copilot.create(data, faustus_urls=["http://127.0.0.1:9"], token=""))

    def test_without_the_relay_the_pages_are_untouched_and_the_routes_do_not_exist(self):
        with patch.object(mercator, "COPILOT", None), running_server() as port:
            status, headers, body = call(port, "GET", "/")
            self.assertEqual(status, 200)
            self.assertNotIn(b"launcher.js", body)
            self.assertIn("style-src 'self';", headers["Content-Security-Policy"])
            self.assertEqual(call(port, "GET", "/api/copilot/info")[0], 404)
            self.assertEqual(call(port, "POST", "/api/copilot/proxy", "{}")[0], 404)


class ManifestAndScriptTests(unittest.TestCase):
    def test_the_manifest_declares_the_copilot_context(self):
        manifest = json.loads((ROOT / "faustus-plugin.json").read_text("utf-8"))
        copilot = manifest["x-family"]["copilot"]
        self.assertEqual((copilot["provider"], copilot["contract"], copilot["panel"]), ("faustus", "1.0", "/api/copilot/panel.js"))
        self.assertTrue({"tracked_project", "crm_deal", "post", "editor"} <= set(copilot["context"]))
        self.assertTrue(manifest["x-family"]["agenda"])  # what was there stays

    @unittest.skipUnless(shutil.which("node"), "node is needed to run the page script tests")
    def test_the_page_context_builder(self):
        result = subprocess.run(["node", "--test", str(ROOT / "tests" / "copilot_context.test.js")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
