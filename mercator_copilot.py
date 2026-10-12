"""Mercator's Faustus copilot relay: the four ``/api/copilot/*`` routes for a standard-library HTTP server.

The shared relay in ``hoard_link.copilot`` is built on FastAPI; Mercator serves with ``http.server``, so this module
carries the same behaviour with ``http.client`` (same routes, same allow-list, same origin rewrite, SSE streamed
without buffering) and reuses the shared pieces that are plain Python: the launcher script, the multipart context
rewrite and the launcher injection.

The panel, the conversation, the model and the tools live in Faustus. The app keeps no chat loop and no history, and the
Faustus token stays on the server. When the vendored ``hoard_link`` does not have the copilot modules yet, ``create``
returns ``None`` and the app simply runs without the panel.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import urllib.request
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

APP_ID = "mercator"
APP_NAME = "Mercator's Hoard"
MAX_PROXY_BODY = 64_000_000  # chat uploads (images, documents) are larger than the dashboard's own 5 MB limit
ALLOWED_PREFIXES = ("/api/hoard-copilot/", "/api/chat/", "/api/session/", "/api/sessions/")
ALLOWED_ROUTES = ("/api/chat_stream", "/api/session", "/api/sessions")
FORWARDED_RESPONSE = ("content-type", "x-odysseus-run-id", "x-faustus-idempotent-replay", "x-faustus-api-version")
FORWARDED_REQUEST = ("x-faustus-client-version", "x-odysseus-run-id")


class Unavailable(Exception):
    """Faustus did not answer on any configured endpoint."""


class Copilot:
    def __init__(self, data_dir: Path | str, *, faustus_urls: list[str], token: str, launcher_js: str, shared: Any,
                 app_id: str = APP_ID, app_name: str = APP_NAME) -> None:
        self.app_id, self.app_name = app_id, app_name
        self.urls = [url.rstrip("/") for url in faustus_urls if url]
        self.headers = {"Authorization": "Bearer " + token} if token else {}
        self.launcher = launcher_js.encode("utf-8")
        self.shared = shared
        space_file = Path(data_dir) / "copilot-space-id"
        space_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with space_file.open("x", encoding="utf-8") as handle:
                handle.write(str(uuid.uuid4()))
        except FileExistsError:
            pass
        self.space_id = space_file.read_text(encoding="utf-8").strip()
        self._selected: str | None = None
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # -- creation -------------------------------------------------------------------------------------------------

    @classmethod
    def create(cls, data_dir: Path | str, *, faustus_urls: list[str] | None = None, token: str | None = None,
               config_path: str | None = None) -> "Copilot | None":
        """The relay for this app, or ``None`` when ``HOARD_COPILOT=0`` or the vendored Hoard Link has no copilot yet."""
        if os.environ.get("HOARD_COPILOT") == "0":
            return None
        try:
            from hoard_link import copilot as shared
            from hoard_link.config import LinkConfig
            from hoard_link.copilot_launcher import LAUNCHER_JS
        except ImportError:
            return None
        if faustus_urls is None or token is None:
            link = LinkConfig.load(path=config_path, app=APP_ID)
            env_url = os.environ.get("MERCATOR_FAUSTUS_URL") or os.environ.get("HOARD_FAUSTUS_URL")
            if faustus_urls is None:
                faustus_urls = [env_url] if env_url else list(link.faustus_urls)
            if token is None:
                token = link.faustus_token
        return cls(data_dir, faustus_urls=faustus_urls, token=token or "", launcher_js=LAUNCHER_JS, shared=shared)

    # -- the HTML pages ---------------------------------------------------------------------------------------------

    def inject(self, html: bytes) -> bytes:
        """The page with the launcher script before ``</body>``."""
        return self.shared.inject_launcher(html)

    # -- Faustus --------------------------------------------------------------------------------------------------

    def locate(self) -> str:
        if self._selected:
            return self._selected
        for base in self.urls:
            try:
                request = urllib.request.Request(base + "/api/hoard-copilot/capabilities", headers=self.headers)
                with self._opener.open(request, timeout=3) as response:
                    if response.status == 200 and json.load(response).get("contract_version"):
                        self._selected = base
                        return base
            except (OSError, ValueError):
                continue
        raise Unavailable("Faustus copilot is unavailable on the configured endpoints")

    def _open(self, path: str, method: str, body: bytes | None, content_type: str, extra: dict[str, str]):
        base = self.locate()
        parts = urlsplit(base)
        connect = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        connection = connect(parts.hostname, parts.port, timeout=900)
        headers = {**self.headers, **extra}
        if body is not None:
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(body))
        try:
            connection.request(method, parts.path.rstrip("/") + path, body=body, headers=headers)
            return connection, connection.getresponse()
        except (OSError, http.client.HTTPException, ValueError) as exc:
            connection.close()
            self._selected = None
            raise Unavailable("Faustus copilot connection failed") from exc

    def _stream(self, handler, path: str, method: str = "GET", body: bytes | None = None,
                content_type: str = "application/json", extra: dict[str, str] | None = None) -> None:
        """Answer ``handler`` with Faustus's response, chunk by chunk (the server speaks HTTP/1.0: closing ends the body)."""
        try:
            connection, response = self._open(path, method, body, content_type, extra or {})
        except Unavailable as exc:
            self._json(handler, 503, {"error": str(exc)})
            return
        try:
            handler.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() in FORWARDED_RESPONSE:
                    handler.send_header(name, value)
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.end_headers()
            read = getattr(response, "read1", None) or response.read
            while True:
                chunk = read(8192)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                handler.wfile.flush()
        except (OSError, http.client.HTTPException):
            pass  # the browser left (closed the panel) or Faustus dropped the stream
        finally:
            connection.close()

    @staticmethod
    def _json(handler, code: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    # -- routes ---------------------------------------------------------------------------------------------------

    def handle(self, handler, method: str, path: str) -> bool:
        """Serve ``/api/copilot/*`` for ``handler`` (a request handler whose guard already passed). False: not ours."""
        if method == "GET" and path == "/api/copilot/info":
            try:
                base = self.locate()
            except Unavailable as exc:
                self._json(handler, 503, {"error": str(exc)})
                return True
            self._json(handler, 200, {"app_id": self.app_id, "app_name": self.app_name, "data_space_id": self.space_id,
                                      "panel_url": "/api/copilot/panel.js", "server": "/", "tool_server_id": self.app_id,
                                      "settings_url": base + "/studio/settings"})
            return True
        if method == "GET" and path == "/api/copilot/panel.js":
            self._stream(handler, "/api/hoard-copilot/panel.js")
            return True
        if method == "GET" and path == "/api/copilot/launcher.js":
            handler.send_response(200)
            handler.send_header("Content-Type", "application/javascript; charset=utf-8")
            handler.send_header("Content-Length", str(len(self.launcher)))
            handler.send_header("Cache-Control", "no-cache")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.end_headers()
            handler.wfile.write(self.launcher)
            return True
        if method == "POST" and path == "/api/copilot/proxy":
            self._proxy(handler)
            return True
        return False

    def _proxy(self, handler) -> None:
        try:
            length = int(handler.headers.get("Content-Length", "0") or 0)
            if length < 0 or length > MAX_PROXY_BODY:
                self._json(handler, 413, {"error": "Copilot request too large"})
                return
            envelope = json.loads(handler.rfile.read(length) or b"{}")
            if not isinstance(envelope, dict):
                raise ValueError("envelope")
            path = envelope.get("path", "")
            if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
                raise ValueError("path")
            route = urlsplit(path).path
            if not (route.startswith(ALLOWED_PREFIXES) or route in ALLOWED_ROUTES):
                raise ValueError("Unknown copilot operation")
            origin = {"app_id": self.app_id, "data_space_id": self.space_id}
            body = None
            if "raw_body" in envelope:
                body = base64.b64decode(envelope["raw_body"], validate=True)
                body = self.shared.multipart_context(body, envelope.get("content_type", ""), origin)
            elif "body" in envelope:
                payload = envelope["body"]
                if isinstance(payload, dict):
                    for field in ("context", "hoard_context"):
                        if isinstance(payload.get(field), dict):
                            payload[field]["origin"] = {**payload[field].get("origin", {}), **origin}
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            extra = {name: value for name, value in (envelope.get("headers") or {}).items()
                     if isinstance(name, str) and name.lower() in FORWARDED_REQUEST}
            method = str(envelope.get("method", "GET")).upper()
            content_type = envelope.get("content_type", "application/json")
        except (ValueError, TypeError, AttributeError):
            self._json(handler, 400, {"error": "Invalid copilot transport request"})
            return
        self._stream(handler, path, method, body, content_type, extra)
