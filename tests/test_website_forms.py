import hashlib
import json
import urllib.request
import zipfile
from unittest.mock import patch

import pytest

import website_forms
import website_publishing
from website_publishing import PublicationError, Publisher


@pytest.fixture
def publisher(tmp_path, monkeypatch):
    monkeypatch.setattr(website_publishing, "_hub_startup", lambda **kwargs: {"state": "disabled"})
    app = Publisher(tmp_path / "data")
    yield app
    app.close()


@pytest.fixture
def static_site(tmp_path, publisher):
    source = tmp_path / "site"
    source.mkdir()
    (source / "index.html").write_text("<h1>Form</h1>", encoding="utf-8")
    (source / "website.json").write_text(json.dumps({"version": 1, "form": STATIC_FORM}), encoding="utf-8")
    return publisher.publish("demo", str(source))["site"]


STATIC_FORM = {"path": "/api/forms", "schema": "submissions",
               "fields": {"name": "Synthetic form check", "email": "test@example.invalid"},
               "marker_field": "name"}


def test_static_form_verifies_receipt_and_undo_targets_one_submission(publisher, static_site):
    url = static_site["url"]
    status, normal = website_forms._hubclient.fetch(url + "api/forms", {"name": "Ordinary entry"},
                                                    headers={"Origin": url.rstrip("/")})
    assert status == 201
    first = publisher.form_check(url)
    second = publisher.form_check(url)
    assert first["verdict"] == second["verdict"] == "pass"
    receipt = first["submission"]
    assert receipt["test"] and receipt["reference"] == first["checks"][0]["response_reference"]
    assert {r["reference"]: r["test"] for r in publisher.submissions("demo")["submissions"]} == {
        normal["reference"]: False, receipt["reference"]: True, second["submission"]["reference"]: True,
    }
    assert publisher.form_check_undo(**first["undo"]["arguments"])["deleted"] == 1
    assert publisher.form_check_undo(**first["undo"]["arguments"])["deleted"] == 0
    assert {r["reference"] for r in publisher.submissions("demo")["submissions"]} == {
        normal["reference"], second["submission"]["reference"],
    }


def test_bad_response_keeps_test_record_reversible(publisher, static_site):
    fetch = website_forms._hubclient.fetch

    def incorrect_reference(*args, **kwargs):
        status, _ = fetch(*args, **kwargs)
        return status, {"reference": "OTHER"}

    with patch.object(website_forms._hubclient, "fetch", incorrect_reference):
        report = publisher.form_check(static_site["url"])
    assert report["verdict"] == "fail"
    assert report["submission"]["test"]
    assert report["checks"][0]["stored_references"] != ["OTHER"]
    assert publisher.form_check_undo(**report["undo"]["arguments"])["deleted"] == 1


@pytest.mark.parametrize("url", ["https://example.invalid", "http://127.0.0.1:1", "http://user@127.0.0.1:42"])
def test_form_check_uses_only_a_managed_site(publisher, url):
    with pytest.raises(PublicationError):
        publisher.form_check(url)


def test_static_site_without_form_contract_has_no_form_verdict(publisher, tmp_path):
    source = tmp_path / "site"
    source.mkdir()
    (source / "index.html").write_text("<h1>Page with no form</h1>", encoding="utf-8")
    site = publisher.publish("demo", str(source))["site"]
    with pytest.raises(PublicationError) as missing:
        publisher.form_check(site["url"])
    assert missing.value.code == "missing_form_contract"


CONTRACT = {
    "version": 1,
    "server": {"entry": "server.py", "origin": "argument", "readiness": "/ready"},
    "form": {"path": "/submit", "schema": "submissions", "fields": {"message": "Synthetic"},
             "marker_field": "message"},
}

SERVER = """
import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--db", required=True)
parser.add_argument("--origin", required=True)
args = parser.parse_args()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/ready" else 404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/submit" or self.headers["Origin"] != args.origin:
            self.send_error(400)
            return
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        with sqlite3.connect(args.db) as db:
            db.execute("CREATE TABLE IF NOT EXISTS submissions (reference, created_at, fields)")
            db.execute("INSERT INTO submissions VALUES (?, CURRENT_TIMESTAMP, ?)", ("DEMO", raw.decode()))
        self.send_response(201)
        self.end_headers()
        self.wfile.write(b'{"reference":"DEMO"}')

HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
"""


def test_zip_contract_pins_source_checks_startup_and_preserves_provenance(publisher, tmp_path):
    archive = tmp_path / "site.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("site/public/index.html", "<h1>Form</h1>")
        zipped.writestr("site/server.py", SERVER)
        zipped.writestr("site/website.json", json.dumps(CONTRACT))
    provenance = {"order_id": 1, "package": {"id": 4, "revision": 2}}
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    published = publisher.publish("bundled", str(archive), source_sha256=digest, provenance=provenance)
    site = published["site"]
    assert site["provenance"] == provenance
    assert site["server"] == "server.py"
    with urllib.request.urlopen(site["url"] + "ready", timeout=3) as response:
        assert response.status == 200
    report = publisher.form_check(site["url"])
    assert report["verdict"] == "pass"
    assert report["submission"]["reference"] == "DEMO"
    assert publisher.form_check_undo(**report["undo"]["arguments"])["deleted"] == 1
    with pytest.raises(PublicationError) as mismatch:
        publisher.publish("bundled", str(archive), source_sha256="0" * 64)
    assert mismatch.value.code == "source_changed"
    assert publisher.status("bundled")["sites"][0] == site


@pytest.mark.parametrize("bad_route", ["https://example.invalid/form", "//example.invalid/form", "/../form"])
def test_contract_rejects_nonlocal_form_routes(tmp_path, publisher, bad_route):
    source = tmp_path / "site"
    source.mkdir()
    (source / "index.html").write_text("<h1>Form</h1>", encoding="utf-8")
    form = {**STATIC_FORM, "path": bad_route}
    (source / "website.json").write_text(json.dumps({"version": 1, "form": form}), encoding="utf-8")
    with pytest.raises(PublicationError) as invalid:
        publisher.publish("demo", str(source))
    assert invalid.value.code == "invalid_contract"
