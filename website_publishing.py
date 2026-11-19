"""Persistent loopback publications and their private form inbox."""

from __future__ import annotations

import hashlib
import http.client
import json
import ntpath
import os
import re
import runpy
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from hoard_link import _hubclient, guard
from hoard_link.atomic import write_json_atomic

HOST = "127.0.0.1"
MAX_FILES = 10_000
MAX_BYTES = 512 * 1024 * 1024
MAX_FORM = 16 * 1024
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
INBOX = """
    CREATE TABLE IF NOT EXISTS submissions (
        reference TEXT PRIMARY KEY, fields TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""
DESTINATIONS = ("local_hub", "public_https_proxy", "public_static_host")


class PublicationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _linked(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _package_path(raw: str) -> Path:
    parts = raw.replace("\\", "/").split("/")
    if any(
        part in ("", ".", "..")
        or part.endswith((".", " "))
        or re.search(r'[:<>|?*"\x00-\x1f]', part)
        or (ntpath.isreserved(part) if hasattr(ntpath, "isreserved") else PureWindowsPath(part).is_reserved())
        for part in parts
    ):
        raise PublicationError("invalid_package", "The package contains an invalid path.")
    return Path(*parts)


def _write_package(source: Path, target: Path) -> str:
    digest = hashlib.sha256()
    total = count = 0
    names: set[str] = set()

    def copy(name, size, open_file):
        nonlocal total, count
        path = _package_path(name)
        key = path.as_posix().casefold()
        total += size
        count += 1
        if key in names or total > MAX_BYTES or count > MAX_FILES:
            raise PublicationError("invalid_package", "The package has duplicate paths or exceeds its size limit.")
        names.add(key)
        dest = target / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open_file() as stream, dest.open("xb") as output:
            shutil.copyfileobj(stream, output)
        if dest.stat().st_size != size:
            raise PublicationError("invalid_package", "A source file changed while copying the package.")

    try:
        if source.is_dir():
            def raise_walk_error(exc):
                raise exc

            for folder, directories, files in os.walk(source, followlinks=False, onerror=raise_walk_error):
                for name in directories + files:
                    candidate = Path(folder) / name
                    if _linked(candidate):
                        raise PublicationError("invalid_package", "The package contains a symbolic link or junction.")
                for name in files:
                    member = Path(folder) / name
                    info = member.stat()
                    if not stat.S_ISREG(info.st_mode):
                        raise PublicationError("invalid_package", "The package contains a special file.")
                    copy(member.relative_to(source).as_posix(), info.st_size, partial(member.open, "rb"))
        else:
            with zipfile.ZipFile(source) as archive:
                for member in archive.infolist():
                    _package_path(member.filename.rstrip("/"))
                    mode = stat.S_IFMT(member.external_attr >> 16)
                    if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or member.flag_bits & 1:
                        raise PublicationError("invalid_package", "ZIP links, special files and encrypted entries are unsupported.")
                    if not member.is_dir():
                        copy(member.filename, member.file_size, partial(archive.open, member))
    except (OSError, zipfile.BadZipFile, NotImplementedError) as exc:
        raise PublicationError("invalid_package", "The website package could not be copied.") from exc

    for member in sorted(path for path in target.rglob("*") if path.is_file()):
        name = member.relative_to(target).as_posix().encode("utf-8")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        with member.open("rb") as handle:
            digest.update(hashlib.file_digest(handle, "sha256").digest())
    return digest.hexdigest()


def _hub_startup(enable=False) -> dict:
    url = _hubclient.hub_url()
    try:
        parts = urlsplit(url)
        valid = (parts.scheme == "http" and parts.hostname in (HOST, "localhost", "::1")
                 and parts.path in ("", "/") and not (parts.username or parts.password or parts.query or parts.fragment))
    except ValueError:
        valid = False
    if not valid:
        return {"state": "unavailable"}
    status, result = _hubclient.fetch(url + "/api/keep-alive?quick=1", timeout=2)
    if status != 200 or not isinstance(result, dict) or not isinstance(result.get("apps"), list):
        return {"state": "unavailable"}
    row = next((row for row in result["apps"] if isinstance(row, dict) and row.get("id") == "mercator"), None)
    if enable and row is None:
        if not _hubclient.hub_up(url):
            return {"state": "unavailable"}
        status, changed = _hubclient.fetch(url + "/api/keep-alive", {"app": "mercator", "keep": True}, timeout=2)
        if status == 200 and isinstance(changed, dict) and changed.get("ok"):
            row = {}
        else:
            return {"state": "unavailable"}
    if row is None:
        return {"state": "disabled"}
    if result.get("disabled_by_env") or row.get("refusal") or row.get("placement") or row.get("manually_stopped"):
        return {"state": "paused"}
    return {"state": "enabled"}


class Publisher:
    """The Mercator listener owns the registry and the site processes."""

    def __init__(self, data: Path):
        self.root = data.resolve() / "websites"
        self.registry = self.root / "sites.json"
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen] = {}
        try:
            payload = json.loads(self.registry.read_text(encoding="utf-8"))
            fields = {"title", "port", "revision", "public", "server", "source", "active"}
            self._loaded = payload if isinstance(payload, dict) and all(
                isinstance(site, dict) and fields <= site.keys() for site in payload.values()
            ) else None
        except FileNotFoundError:
            self._loaded = {}
        except (OSError, ValueError):
            self._loaded = None

    @property
    def _sites(self):
        if self._loaded is None:
            raise PublicationError("invalid_registry", "The website registry is unreadable. Its contents were preserved.")
        return self._loaded

    def _site_dir(self, slug):
        return self.root / slug

    def _bundle(self, slug, site):
        return self._site_dir(slug) / "versions" / site["revision"]

    def _db(self, slug):
        return self._site_dir(slug) / "forms.sqlite3"

    def _save(self, slug, site):
        sites = {**self._sites, slug: site}
        write_json_atomic(self.registry, sites)
        self._loaded = sites

    def _running(self, slug):
        process = self._processes.get(slug)
        return process is not None and process.poll() is None

    def _stop(self, slug):
        process = self._processes.pop(slug, None)
        if process is None:
            return
        process.stdin.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _start(self, slug, site):
        bundle = self._bundle(slug, site)
        if not bundle.is_dir():
            raise PublicationError("start_failed", "The published package is missing.")
        port = site["port"]
        with socket.socket() as reservation:
            if sys.platform == "win32":
                reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                reservation.bind((HOST, port))
            except OSError as exc:
                raise PublicationError("start_failed", "The website port is already in use.") from exc

        with (self._site_dir(slug) / "server.log").open("ab") as log:
            python = Path(sys.executable)
            if python.name.lower() == "pythonw.exe":
                python = python.with_name("python.exe")
            runtime = [str(python), "-u", str(Path(__file__).resolve()), str(port), str(self._db(slug)),
                       site["public"], site["server"]]
            # The handed-off server gets its own environment, without service or account credentials.
            keys = {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATH", "TEMP", "TMP", "LANG"}
            env = {key: value for key, value in os.environ.items() if key.upper() in keys}
            process = subprocess.Popen(runtime, cwd=bundle, stdin=subprocess.PIPE, stdout=log, stderr=log,
                                       env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._processes[slug] = process
        deadline = time.monotonic() + 5
        while process.poll() is None and time.monotonic() < deadline:
            with closing(http.client.HTTPConnection(HOST, port, timeout=0.3)) as connection:
                try:
                    connection.request("GET", "/")
                    if connection.getresponse().status == 200 and process.poll() is None:
                        return
                except (OSError, http.client.HTTPException):
                    pass
            time.sleep(0.075)
        self._stop(slug)
        raise PublicationError("start_failed", "The website did not answer at its local address. See the site server.log.")

    def restore(self):
        with self._lock:
            if self._loaded is None:
                return
            for slug, site in self._sites.items():
                if site["active"] and not self._running(slug):
                    self._stop(slug)
                    try:
                        self._start(slug, site)
                    except (PublicationError, OSError):
                        continue

    def close(self):
        with self._lock:
            for slug in list(self._processes):
                self._stop(slug)

    def _change(self, slug, site, before):
        self._stop(slug)
        try:
            if site["active"]:
                self._start(slug, site)
            self._save(slug, site)
        except (PublicationError, OSError):
            self._stop(slug)
            if before and before["active"]:
                try:
                    self._start(slug, before)
                except (PublicationError, OSError):
                    pass  # persisted intent still points to the previous version; restore will retry it
            raise

    def _free_port(self):
        reserved = {site["port"] for site in self._sites.values()}
        for _ in range(20):
            with socket.socket() as listener:
                listener.bind((HOST, 0))
                port = listener.getsockname()[1]
            if port not in reserved:
                return port
        raise PublicationError("start_failed", "No free local port could be assigned to this website.")

    def _snapshot(self, slug, source, server):
        versions = self._site_dir(slug) / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="import-", dir=versions) as work:
            staging = Path(work) / "package"
            staging.mkdir()
            revision = _write_package(source, staging)
            package = staging
            children = list(staging.iterdir())
            if len(children) == 1 and children[0].is_dir() and children[0].name != "public":
                package = children[0]
            public = "public" if (package / "public" / "index.html").is_file() else "."
            if not (package / public / "index.html").is_file():
                raise PublicationError("missing_index", "The package needs index.html at its root or in public/.")
            if server and (not (package / server).is_file() or public == "."):
                raise PublicationError("invalid_server", "A Python server needs its entry file and public/index.html.")
            version = versions / revision
            if not version.exists():
                package.rename(version)
        return revision, public

    @staticmethod
    def _validate_slug(slug):
        if not isinstance(slug, str) or len(slug) > 64 or not SLUG.fullmatch(slug):
            raise PublicationError("invalid_slug", "Use lowercase letters, numbers and single hyphens for the website ID.")
        _package_path(slug)

    @staticmethod
    def _view(slug, site, running):
        return {"slug": slug, "title": site["title"], "revision": site["revision"],
                "url": f"http://{HOST}:{site['port']}/", "active": site["active"],
                "state": "live" if running else "unavailable" if site["active"] else "unpublished",
                "server": site["server"], "source": site["source"], "undo_token": site.get("undo_token")}

    def publish(self, slug, source, title=None, server="", start_with_hub=True):
        self._validate_slug(slug)
        if not isinstance(source, str) or not Path(source).is_absolute():
            raise PublicationError("invalid_source", "Enter an absolute local path to a folder or ZIP.")
        original = Path(source)
        if not original.exists() or _linked(original):
            raise PublicationError("invalid_source", "The source path does not exist or is a link.")
        original = original.resolve()
        if (original == self.root or original in self.root.parents or self.root in original.parents
                or not (original.is_dir() or (original.is_file() and original.suffix.lower() == ".zip"))):
            raise PublicationError("invalid_source", "Choose a folder or ZIP outside the publication store.")
        if not isinstance(server, str):
            raise PublicationError("invalid_server", "Enter the relative path to a Python entry file.")
        if server:
            if PurePosixPath(server).suffix != ".py":
                raise PublicationError("invalid_server", "Enter the relative path to a Python entry file.")
            server = _package_path(server).as_posix()
        if title is None:
            title = slug
        if not isinstance(title, str) or not 0 < len(title.strip()) <= 120 or not isinstance(start_with_hub, bool):
            raise PublicationError("invalid_options", "Enter a title up to 120 characters and a valid startup option.")
        with self._lock:
            before = self._sites.get(slug)
            revision, public = self._snapshot(slug, original, server)
            port = before["port"] if before else self._free_port()
            site = {"title": title.strip(), "port": port, "revision": revision, "public": public,
                    "server": server, "source": str(original), "active": True}
            stable = ("title", "port", "revision", "public", "server", "source", "active")
            if before and all(before[key] == site[key] for key in stable):
                if not self._running(slug):
                    self._stop(slug)
                    self._start(slug, before)
                current = before
            else:
                current = {**site, "undo_token": uuid4().hex, "previous": (
                    {key: before[key] for key in stable} if before else {**site, "active": False}
                )}
                self._change(slug, current, before)
            result = {"ok": True, "site": self._view(slug, current, True), "undo_token": current.get("undo_token")}
        result["hub_startup"] = _hub_startup(enable=start_with_hub)
        return result

    def unpublish(self, slug):
        self._validate_slug(slug)
        with self._lock:
            before = self._get(slug)
            if not before["active"]:
                return {"ok": True, "site": self._view(slug, before, False), "undo_token": before.get("undo_token")}
            previous = {key: value for key, value in before.items() if key not in ("undo_token", "previous")}
            site = {**previous, "active": False, "undo_token": uuid4().hex, "previous": previous}
            self._change(slug, site, before)
            return {"ok": True, "site": self._view(slug, site, False), "undo_token": site["undo_token"]}

    def undo(self, slug, undo_token):
        self._validate_slug(slug)
        with self._lock:
            before = self._get(slug)
            if not undo_token or before.get("undo_token") != undo_token:
                raise PublicationError("stale_undo", "This undo no longer applies to the current website state.")
            site = before["previous"]
            self._change(slug, site, before)
            return {"ok": True, "site": self._view(slug, site, self._running(slug))}

    def _get(self, slug):
        if slug not in self._sites:
            raise PublicationError("unknown_site", "No website has that ID.")
        return self._sites[slug]

    def status(self, slug=None):
        if slug is not None:
            self._validate_slug(slug)
        with self._lock:
            sites = [(slug, self._get(slug))] if slug is not None else sorted(self._sites.items())
            views = [self._view(key, site, self._running(key)) for key, site in sites]
        return {"ok": True, "sites": views, "hub_startup": _hub_startup(), "destinations": list(DESTINATIONS)}

    def submissions(self, slug, limit=25, offset=0):
        self._validate_slug(slug)
        if (type(limit) is not int or type(offset) is not int or not 1 <= limit <= 100 or not 0 <= offset <= 2**31 - 1):
            raise PublicationError("invalid_pagination", "Use a limit from 1 to 100 and a non-negative offset.")
        with self._lock:
            self._get(slug)
        path = self._db(slug)
        items = []
        if path.is_file():
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                db.row_factory = sqlite3.Row
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
                sources = []
                if "submissions" in tables:
                    sources.append("SELECT reference, created_at, fields FROM submissions")
                if "commissions" in tables:
                    fields = {r[1] for r in db.execute("PRAGMA table_info(commissions)")}
                    if {"reference", "created_at", "name", "email", "category", "details"} <= fields:
                        sources.append("SELECT reference, created_at, json_object('name', name, 'email', email, "
                                       "'category', category, 'details', details) AS fields FROM commissions")
                if sources:
                    sql = " UNION ALL ".join(sources) + " ORDER BY created_at DESC, reference DESC LIMIT ? OFFSET ?"
                    items = [{"reference": row["reference"], "created_at": row["created_at"],
                              "fields": json.loads(row["fields"])} for row in db.execute(sql, (limit + 1, offset))]
        return {"ok": True, "slug": slug, "submissions": items[:limit],
                "next_offset": offset + limit if len(items) > limit else None}


class StaticWebsite(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory, database, **kwargs):
        self.database = database
        super().__init__(*args, directory=directory, **kwargs)

    def _allowed(self):
        headers = {name.lower(): value for name, value in self.headers.items()}
        return guard.check_request("GET", headers, self.server.server_port, strict_ports=True) is None

    def log_request(self, code="-", size="-"):
        print(f"{self.command} {code}")  # avoid logging form fields or query strings

    def list_directory(self, path):
        self.send_error(404)
        return None

    def send_head(self):
        if not self._allowed():
            self.send_error(403)
            return None
        path = unquote(urlsplit(self.path).path)
        if any(part.startswith(".") or part.endswith((" ", ".")) or ":" in part for part in path.replace("\\", "/").split("/") if part):
            self.send_error(404)
            return None
        if Path(path).suffix.lower() in {".py", ".db", ".sqlite", ".sqlite3", ".pem", ".key"}:
            self.send_error(404)
            return None
        return super().send_head()

    def _reply(self, code, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/forms":
            return self._reply(404, {"error": "not_found"})
        port = self.server.server_port
        content_type = self.headers.get_content_type()
        if not self._allowed() or self.headers.get("Origin") != f"http://{HOST}:{port}":
            return self._reply(403, {"error": "origin"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_FORM:
                return self._reply(413, {"error": "size"})
            raw = self.rfile.read(length).decode("utf-8")
            if content_type == "application/json":
                fields = json.loads(raw)
            elif content_type == "application/x-www-form-urlencoded":
                fields = {key: ", ".join(values) for key, values in parse_qs(raw, max_num_fields=30).items()}
            else:
                return self._reply(415, {"error": "content_type"})
            if (not isinstance(fields, dict) or not 1 <= len(fields) <= 30
                    or any(not re.fullmatch(r"[\w-]{1,64}", key) or not isinstance(value, str) or len(value) > 4000
                           for key, value in fields.items())):
                return self._reply(400, {"error": "fields"})
        except (UnicodeError, ValueError):
            return self._reply(400, {"error": "fields"})
        reference = "WEB-" + uuid4().hex[:12].upper()
        try:
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute(INBOX)
                db.execute("INSERT INTO submissions (reference, fields) VALUES (?, ?)",
                           (reference, json.dumps(fields, ensure_ascii=False)))
        except sqlite3.Error:
            return self._reply(503, {"error": "storage"})
        return self._reply(201, {"reference": reference})


def _website_worker():
    port, database, public, server = sys.argv[1:]
    # Closing this pipe also stops the site if the owning Mercator is killed.
    def watch_owner():
        sys.stdin.buffer.read()
        os._exit(0)

    threading.Thread(target=watch_owner, daemon=True).start()
    if server:
        path = Path(server).resolve()
        sys.path.insert(0, str(path.parent))
        sys.argv = [str(path), "--port", port, "--db", database]
        runpy.run_path(str(path), run_name="__main__")
    else:
        handler = partial(StaticWebsite, directory=public, database=database)
        with ThreadingHTTPServer((HOST, int(port)), handler) as httpd:
            httpd.serve_forever()


if __name__ == "__main__":
    _website_worker()
