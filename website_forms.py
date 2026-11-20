"""Packaged form contracts and reversible synthetic submissions."""

from contextlib import closing
import json
import re
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4

from hoard_link import _hubclient


CONTRACT_FILE = "website.json"
TOKEN = re.compile(r"[a-f0-9]{32}")
TEST_MARK = re.compile(r" \[mercator-test:([a-f0-9]{32})\]$")
COMMISSION_FIELDS = {"name", "email", "category", "details"}
MARKER_TEMPLATE = " [mercator-test:{}]"
MARKER_SIZE = len(MARKER_TEMPLATE.format("0" * 32))


class PublicationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _route(path):
    return (isinstance(path, str) and re.fullmatch(r"/(?:[a-zA-Z0-9_.~-]+/)*[a-zA-Z0-9_.~-]*", path)
            and not any(part in (".", "..") for part in path.split("/")))


def read_contract(package):
    manifest = package / CONTRACT_FILE
    if not manifest.is_file():
        return None
    try:
        with manifest.open("rb") as stream:
            raw = stream.read(32769)
        if len(raw) > 32768:
            raise ValueError("contract too large")
        obj = json.loads(raw)
        if type(obj["version"]) is not int or obj["version"] != 1 or obj.keys() - {"version", "server", "form"}:
            raise ValueError("unknown contract")
        server = obj.get("server")
        if "server" in obj and (not isinstance(server, dict)
                                or server.keys() != {"entry", "origin", "readiness"}
                                or not isinstance(server["entry"], str) or not server["entry"]
                                or server["origin"] not in ("port", "argument") or not _route(server["readiness"])):
            raise ValueError("invalid server")
        if "form" in obj:
            form = obj["form"]
            if (not isinstance(form, dict) or form.keys() != {"path", "schema", "fields", "marker_field"}
                    or not _route(form["path"]) or form["schema"] not in ("submissions", "commissions")
                    or not isinstance(form["fields"], dict) or not 1 <= len(form["fields"]) <= 30
                    or not all(re.fullmatch(r"[\w-]{1,64}", key) and isinstance(value, str)
                               and value == value.strip() and 0 < len(value) <= 4000
                               for key, value in form["fields"].items())
                    or not isinstance(form["marker_field"], str) or form["marker_field"] not in form["fields"]
                    or len(form["fields"][form["marker_field"]]) + MARKER_SIZE > 4000
                    or (form["schema"] == "commissions" and form["fields"].keys() != COMMISSION_FIELDS)):
                raise ValueError("invalid form")
            if not server and (form["path"], form["schema"]) != ("/api/forms", "submissions"):
                raise ValueError("invalid static form")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PublicationError("invalid_contract", "Review the version, server and form in website.json.") from exc
    return obj


def inbox_sources(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
    sources = {}
    if "submissions" in tables:
        sources["submissions"] = "SELECT reference, created_at, fields FROM submissions"
    if "commissions" in tables:
        columns = {row[1] for row in db.execute("PRAGMA table_info(commissions)")}
        if COMMISSION_FIELDS | {"reference", "created_at"} <= columns:
            sources["commissions"] = (
                "SELECT reference, created_at, json_object('name', name, 'email', email, "
                "'category', category, 'details', details) AS fields FROM commissions"
            )
    return sources


def _test_tokens(fields):
    if not isinstance(fields, dict):
        return set()
    return {match[1] for value in fields.values() if isinstance(value, str) and (match := TEST_MARK.search(value))}


def inbox_item(row):
    fields = json.loads(row["fields"])
    return {"reference": row["reference"], "created_at": row["created_at"],
            "fields": fields, "test": bool(_test_tokens(fields))}


def _test_rows(db, source, token):
    return [inbox_item(row) for row in db.execute(
        f"SELECT * FROM ({source}) WHERE instr(fields, ?) > 0", (token,))
        if token in _test_tokens(json.loads(row["fields"]))]


def check_form(db_path, slug, url, contract):
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    token = uuid4().hex
    fields = dict(contract["fields"])
    fields[contract["marker_field"]] += MARKER_TEMPLATE.format(token)
    status, reply = _hubclient.fetch(origin + contract["path"], fields, headers={"Origin": origin}, timeout=6)
    reference = reply.get("reference") if isinstance(reply, dict) else None
    entries = []
    observed = True
    try:
        if db_path.is_file():
            with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                db.row_factory = sqlite3.Row
                source = inbox_sources(db).get(contract["schema"])
                if source:
                    entries = _test_rows(db, source, token)
    except (OSError, sqlite3.Error, ValueError):
        observed = False
    passed = (observed and status is not None and 200 <= status < 300 and isinstance(reference, str)
              and len(entries) == 1 and entries[0]["reference"] == reference
              and all(entries[0]["fields"].get(key) == value for key, value in fields.items()))
    if passed:
        verdict = "pass"
        reason = {"en": "The form returned the reference stored for the test submission.",
                  "es": "El formulario devolvió la referencia guardada para el envío de prueba."}
    elif status is None or not observed:
        verdict = "unmeasured"
        reason = {"en": "The form response or inbox could not be read.",
                  "es": "No se ha podido leer la respuesta del formulario o el buzón."}
    else:
        verdict = "fail"
        reason = {"en": "The response and inbox did not confirm the same submission.",
                  "es": "La respuesta y el buzón no han confirmado el mismo envío."}
    check = {"id": "form-submission", "verdict": verdict, "reason": reason, "http_status": status,
             "response_reference": reference, "stored_references": [entry["reference"] for entry in entries]}
    return {"ok": True, "slug": slug, "url": url, "profile": "web-form", "verdict": verdict,
            "reason": reason, "checks": [check], "submission": entries[0] if len(entries) == 1 else None,
            "undo": {"tool": "website_form_check_undo", "arguments": {"slug": slug, "undo_token": token}}}


def undo_check(path, token):
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise PublicationError("invalid_undo", "Use the undo token returned by a form check.")
    deleted = 0
    if path.is_file():
        with closing(sqlite3.connect(path)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            for table, source in inbox_sources(db).items():
                for row in _test_rows(db, source, token):
                    deleted += db.execute(f"DELETE FROM {table} WHERE reference = ?", (row["reference"],)).rowcount
    return {"ok": True, "deleted": deleted}
