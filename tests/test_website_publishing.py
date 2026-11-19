import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ["HOARD_EVENTS"] = "0"

import website_publishing
from website_publishing import PublicationError, Publisher


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def _post_form(url, fields):
    body = json.dumps(fields).encode("utf-8")
    origin = url.rstrip("/")
    request = urllib.request.Request(url + "api/forms", data=body, method="POST", headers={
        "Content-Type": "application/json", "Origin": origin})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


class WebsitePublishingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.site = root / "site"
        self.site.mkdir()
        (self.site / "index.html").write_text("<h1>Version one</h1>", encoding="utf-8")
        (self.site / "style.css").write_text("h1{color:red}", encoding="utf-8")
        hub = patch.object(website_publishing, "_hub_startup", return_value={"state": "disabled"})
        hub.start()
        self.addCleanup(hub.stop)
        self.publisher = Publisher(root / "data")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.publisher.close)

    def test_publish_form_unpublish_and_undo_keep_the_address(self):
        published = self.publisher.publish("demo", str(self.site), title="Demo")
        url = published["site"]["url"]
        self.assertEqual(published["site"]["state"], "live")
        self.assertEqual(_get(url), (200, "<h1>Version one</h1>"))
        self.assertEqual(_get(url + "style.css")[0], 200)

        status, reply = _post_form(url, {"name": "Ana", "message": "Hola"})
        self.assertEqual(status, 201)
        inbox = self.publisher.submissions("demo")["submissions"]
        self.assertEqual([row["reference"] for row in inbox], [reply["reference"]])
        self.assertEqual(inbox[0]["fields"], {"name": "Ana", "message": "Hola"})

        down = self.publisher.unpublish("demo")
        self.assertEqual(down["site"]["state"], "unpublished")
        with self.assertRaises(urllib.error.URLError):
            _get(url)

        restored = self.publisher.undo("demo", down["undo_token"])
        self.assertEqual(restored["site"]["url"], url)
        self.assertEqual(_get(url)[1], "<h1>Version one</h1>")
        self.assertEqual(len(self.publisher.submissions("demo")["submissions"]), 1)
        with self.assertRaises(PublicationError):
            self.publisher.undo("demo", down["undo_token"])

    def test_update_and_undo_return_to_the_previous_version(self):
        first = self.publisher.publish("demo", str(self.site))
        url = first["site"]["url"]
        (self.site / "index.html").write_text("<h1>Version two</h1>", encoding="utf-8")
        second = self.publisher.publish("demo", str(self.site))
        self.assertEqual(second["site"]["url"], url)
        self.assertEqual(_get(url)[1], "<h1>Version two</h1>")
        self.publisher.undo("demo", second["undo_token"])
        self.assertEqual(_get(url)[1], "<h1>Version one</h1>")

    def test_zip_package_with_a_single_folder_is_served(self):
        archive = Path(self.tmp.name) / "site.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("site/index.html", "<p>zip</p>")
        published = self.publisher.publish("zipped", str(archive))
        self.assertEqual(_get(published["site"]["url"])[1], "<p>zip</p>")

    def test_rejects_bad_ids_relative_sources_and_missing_index(self):
        with self.assertRaises(PublicationError):
            self.publisher.publish("Bad ID", str(self.site))
        with self.assertRaises(PublicationError):
            self.publisher.publish("demo", "site")
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        (empty / "readme.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(PublicationError) as raised:
            self.publisher.publish("empty", str(empty))
        self.assertEqual(raised.exception.code, "missing_index")
        self.assertEqual(self.publisher.status()["sites"], [])

    def test_unreadable_registry_is_preserved(self):
        registry = Path(self.tmp.name) / "data" / "websites" / "sites.json"
        registry.parent.mkdir(parents=True)
        registry.write_text("{broken", encoding="utf-8")
        publisher = Publisher(Path(self.tmp.name) / "data")
        with self.assertRaises(PublicationError) as raised:
            publisher.status()
        self.assertEqual(raised.exception.code, "invalid_registry")
        publisher.restore()
        self.assertEqual(registry.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
