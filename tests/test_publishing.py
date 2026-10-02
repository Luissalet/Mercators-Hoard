import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

os.environ["HOARD_EVENTS"] = "0"

import agent_tools
import cults_catalog
import mercator
import mercator_family
import post_csv
import publishing

SALES_COLUMNS = {"date": "date", "product": "product", "amount": "amount", "currency": "currency", "id": "id"}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        for name, value in (("DATA", self.data), ("DB", self.data / "mercator.sqlite3")):
            patcher = patch.object(mercator, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.events = []
        patcher = patch.object(mercator_family, "emit", lambda kind, data=None: self.events.append((kind, data or {})) or True)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(mercator_family, "link_ref", lambda *args, **kw: self.events.append(("ref", args)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.token_file = mercator_family.configure(self.data)
        mercator.database()
        self.addCleanup(mercator.close_databases)

    def call(self, name, **args):
        return agent_tools.call_tool(name, args)

    def kinds(self):
        return [kind for kind, _ in self.events if kind != "ref"]


class PostsTests(Base):
    def test_create_edit_and_validation(self):
        made = self.call("post_upsert", platform="instagram_reel", title="Pikachu", caption="Hola", hashtags="#Pokemon, #3dprint #pokemon")
        post = made["post"]
        self.assertTrue(made["created"])
        self.assertEqual(post["hashtags"], ["Pokemon", "3dprint"])
        self.assertEqual(post["text"], "Hola\n\n#Pokemon #3dprint")
        self.assertEqual(post["status"], "idea")
        edited = self.call("post_upsert", post_id=post["id"], caption="Otro texto")["post"]
        self.assertEqual((edited["title"], edited["caption"], edited["hashtags"]), ("Pikachu", "Otro texto", ["Pokemon", "3dprint"]))
        for bad in ({"platform": "myspace", "title": "x"}, {"title": "x"}, {"platform": "x"},
                    {"platform": "x", "title": "x", "status": "scheduled"}, {"platform": "x", "title": "x", "scheduled_at": "mañana"},
                    {"platform": "x", "title": "x", "color": "red"}, {"post_id": 999, "title": "x"}):
            with self.assertRaises(ValueError, msg=bad):
                self.call("post_upsert", **bad)

    def test_schedule_and_publish_emit_events_once(self):
        post = self.call("post_upsert", platform="tiktok", title="Reel")["post"]
        self.call("post_schedule", post_id=post["id"], scheduled_at="2026-10-05T18:30")
        self.call("post_schedule", post_id=post["id"], scheduled_at="2026-10-06T18:30")
        published = self.call("post_publish", post_id=post["id"], url="https://example.com/v/1")["post"]
        self.assertEqual(published["status"], "published")
        self.assertTrue(published["published_at"])
        self.call("post_publish", post_id=post["id"], url="https://example.com/v/1")
        self.assertEqual(self.kinds(), ["mercator.post.scheduled", "mercator.post.published"])
        scheduled = [d for k, d in self.events if k == "mercator.post.scheduled"][0]
        self.assertEqual((scheduled["post_id"], scheduled["scheduled_at"]), (post["id"], "2026-10-05T18:30:00"))
        self.assertNotIn("caption", scheduled)

    def test_date_only_and_listing_filters(self):
        a = self.call("post_upsert", platform="youtube", title="Largo", status="scheduled", scheduled_at="2026-10-05")["post"]
        self.call("post_upsert", platform="x", title="Corto", status="draft")
        self.assertEqual(a["scheduled_at"], "2026-10-05")
        self.assertEqual(self.call("posts_list", status="scheduled")["total"], 1)
        self.assertEqual(self.call("posts_list", platform="x")["posts"][0]["title"], "Corto")
        self.assertEqual(self.call("posts_list", q="larg")["total"], 1)
        self.assertEqual(self.call("posts_list", **{"from": "2026-10-01", "to": "2026-10-31"})["total"], 1)
        with self.assertRaises(ValueError):
            self.call("posts_list", status="bogus")

    def test_media_ref_links_the_other_app_record(self):
        self.call("post_upsert", platform="instagram_reel", title="R", media_ref="hoard://lumiere/render/7")
        refs = [a for k, a in self.events if k == "ref"]
        self.assertEqual(refs[0][:3], ("hoard://mercator/post/1", "hoard://lumiere/render/7", "publishes"))
        self.call("post_upsert", platform="instagram_reel", title="Path", media_ref="C:/videos/a.mp4")
        self.assertEqual(len([1 for k, _ in self.events if k == "ref"]), 1)

    def test_draft_from_media_is_idempotent_and_uses_default_platform(self):
        first = self.call("post_draft_from_media", media_ref="hoard://lumiere/render/12", title="Clip")
        again = self.call("post_draft_from_media", media_ref="hoard://lumiere/render/12", title="Clip otra vez")
        self.assertTrue(first["created"])
        self.assertFalse(again["created"])
        self.assertEqual(again["post_id"], first["post_id"])
        self.assertEqual((first["post"]["status"], first["post"]["platform"]), ("draft", "instagram_reel"))
        self.assertEqual(self.kinds(), ["mercator.post.drafted"])
        other = self.call("post_draft_from_media", media_ref="hoard://prospero/production/3", title="Videoclip", platform="youtube")
        self.assertEqual(other["post"]["platform"], "youtube")
        with self.assertRaises(ValueError):
            self.call("post_draft_from_media", media_ref="", title="x")

    def test_unknown_tool_and_arguments(self):
        with self.assertRaises(KeyError):
            agent_tools.call_tool("nope", {})
        with self.assertRaises(ValueError):
            self.call("posts_list", surprise=1)
        with self.assertRaises(ValueError):
            agent_tools.call_tool("post_get", {})

    def test_agenda_lists_only_scheduled_posts_in_range(self):
        self.call("post_upsert", platform="tiktok", title="En rango", status="scheduled", scheduled_at="2026-10-05T18:30")
        self.call("post_upsert", platform="tiktok", title="Fuera", status="scheduled", scheduled_at="2026-12-05T18:30")
        self.call("post_upsert", platform="tiktok", title="Borrador", status="draft", scheduled_at="2026-10-06T18:30")
        with mercator.reading() as conn:
            items = publishing.agenda_items(conn, date(2026, 10, 1), date(2026, 10, 31), "http://127.0.0.1:5195")
        self.assertEqual([i["title"] for i in items], ["Publicar: En rango (TikTok)"])
        self.assertEqual((items[0]["kind"], items[0]["id"]), ("publish", "mercator:publish:1"))
        answer = mercator_family.agenda(mercator.agenda_provider, "2026-10-01", "2026-10-31")
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["items"][0]["start"], "2026-10-05T18:30:00")
        self.assertFalse(answer["items"][0]["all_day"])

    def test_overdue_scheduled_post_is_high_priority(self):
        past = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        self.call("post_upsert", platform="x", title="Tarde", status="scheduled", scheduled_at=past)
        with mercator.reading() as conn:
            items = publishing.agenda_items(conn, date.today() - timedelta(days=7), date.today(), "http://x")
        self.assertEqual(items[0]["priority"], "high")


class MetricsTests(Base):
    def publish(self, title, when, views, platform="instagram_reel", **extra):
        post = self.call("post_upsert", platform=platform, title=title, status="published", published_at=when)["post"]
        if views is not None:
            self.call("post_metrics_add", post_id=post["id"], views=views, **extra)
        return post

    def test_metrics_validation_and_latest_snapshot(self):
        post = self.publish("A", "2026-09-14T18:00", None)
        for bad in ({}, {"views": -1}, {"views": "x"}, {"views": 1, "ts": "ayer"}, {"revenue": "abc"}, {"revenue": "1", "currency": "EURO"}):
            with self.assertRaises(ValueError, msg=bad):
                self.call("post_metrics_add", post_id=post["id"], **bad)
        self.call("post_metrics_add", post_id=post["id"], views=100, likes=5, ts="2026-09-15T10:00:00+00:00")
        self.call("post_metrics_add", post_id=post["id"], views=900, likes=40, revenue="12,50", currency="usd", ts="2026-09-20T10:00:00+00:00")
        self.call("post_metrics_add", post_id=post["id"], views=400, ts="2026-09-16T10:00:00+00:00")   # older than the 20th
        got = self.call("post_get", post_id=post["id"])["post"]
        self.assertEqual(got["metrics_latest"]["views"], 900)
        self.assertEqual((got["metrics_latest"]["revenue"], got["metrics_latest"]["currency"]), ("12.50", "USD"))
        self.assertEqual([m["views"] for m in got["metrics"]], [100, 400, 900])

    def test_stats_totals_per_platform_and_currency(self):
        self.publish("A", "2026-09-14T18:00", 1000, likes=100, revenue="10", currency="EUR")
        self.publish("B", "2026-09-15T18:00", 500, likes=50, revenue="5", currency="USD")
        self.publish("C", "2026-09-16T18:00", 250, platform="youtube")
        stats = self.call("posts_stats")
        reel = [p for p in stats["by_platform"] if p["platform"] == "instagram_reel"][0]
        self.assertEqual((reel["views"], reel["likes"], reel["posts"]), (1500, 150, 2))
        self.assertEqual(reel["revenue"], [{"currency": "EUR", "amount": "10"}, {"currency": "USD", "amount": "5"}])
        self.assertEqual(reel["engagement"], 0.1)
        self.assertEqual(stats["top_posts"][0]["title"], "A")
        self.assertEqual(self.call("posts_stats", platform="youtube")["posts"], 1)

    def test_best_hours_average_views_by_weekday_and_hour(self):
        # 2026-09-14 is a Monday, 2026-09-15 a Tuesday.
        self.publish("a", "2026-09-14T18:00", 1000)
        self.publish("b", "2026-09-21T18:30", 3000)   # Monday 18:xx
        self.publish("c", "2026-09-15T09:00", 100)
        self.publish("d", "2026-09-16", 700)           # date only: counts for the weekday, not for an hour
        draft = self.call("post_upsert", platform="x", title="no", status="draft")["post"]
        self.call("post_metrics_add", post_id=draft["id"], views=99999)
        hours = self.call("posts_stats")["best_hours"]
        self.assertEqual(hours["sample"], 4)
        monday = [w for w in hours["by_weekday"] if w["weekday"] == 0][0]
        self.assertEqual((monday["posts"], monday["avg_views"]), (2, 2000.0))
        self.assertEqual([h["hour"] for h in hours["by_hour"]], [9, 18])
        self.assertEqual(hours["by_hour"][1]["avg_views"], 2000.0)
        self.assertEqual(hours["top_slots"][0]["weekday"], 0)
        self.assertEqual(hours["note"], "few_posts")

    def test_best_hours_empty(self):
        hours = self.call("posts_stats")["best_hours"]
        self.assertEqual((hours["sample"], hours["by_hour"], hours["top_slots"]), (0, [], []))


YT = ("Content,Video title,Video publish time,Duration,Views,Watch time (hours),Estimated revenue (USD),Impressions\n"
      "Total,,,,9999,10,3.00,5\n"
      'abc123,Pikachu timelapse,"Sep 14, 2026",120,"1.250",12.5,1.20,4000\n'
      "zzz999,Nuevo vídeo,2026-09-30,300,80,3.1,0.40,800\n")
IG = ("Post ID,Description,Publish time,Permalink,Views,Reach,Likes,Comments,Shares,Saves\n"
      "111,Reel Eevee,2026-09-20 18:45,https://instagram.com/reel/AAA/,5000,4000,300,20,10,40\n")
TT = ("Video title,Video link,Post time,Total views,Total likes,Total comments,Total shares,Total bookmarks\n"
      "Reel TikTok,https://tiktok.com/@x/video/1,2026-09-21,900,90,9,3,12\n")


class CsvTests(Base):
    def test_presets_are_recognised_by_column_names(self):
        self.assertEqual(post_csv.preview(YT)["preset"], "youtube_studio")
        self.assertEqual(post_csv.preview(IG)["preset"], "instagram")
        self.assertEqual(post_csv.preview(TT)["preset"], "tiktok")
        self.assertEqual(post_csv.preview("a,b\n1,2\n")["preset"], "generic")
        mapping = post_csv.preview(YT)["mapping"]
        self.assertEqual((mapping["external_id"], mapping["title"], mapping["views"], mapping["published_at"]),
                         ("Content", "Video title", "Views", "Video publish time"))
        self.assertEqual(mapping["revenue"], "Estimated revenue (USD)")
        self.assertEqual(mapping["currency_default"], "USD")
        ig = post_csv.preview(IG)["mapping"]
        self.assertEqual((ig["url"], ig["caption"], ig["saves"]), ("Permalink", "Description", "Saves"))

    def test_spanish_headers_and_semicolons(self):
        text = "Contenido;Título del vídeo;Hora de publicación del vídeo;Visualizaciones;Me gusta\nq1;Mi vídeo;5 sept 2026;1.234;50\n"
        preview = post_csv.preview(text)
        self.assertEqual((preview["preset"], preview["delimiter"]), ("youtube_studio", ";"))
        with mercator.session() as conn:
            result = post_csv.import_rows(conn, text, "youtube", preview["mapping"])
        self.assertEqual((result["created"], result["snapshots"]), (1, 1))
        post = self.call("posts_list")["posts"][0]
        self.assertEqual((post["published_at"], post["metrics_latest"]["views"], post["external_id"]), ("2026-09-05", 1234, "q1"))

    def run_import(self, text, platform):
        with mercator.session() as conn:
            return post_csv.import_rows(conn, text, platform, post_csv.preview(text, platform)["mapping"])

    def test_youtube_import_creates_posts_skips_total_and_is_idempotent(self):
        first = self.run_import(YT, "youtube")
        self.assertEqual((first["rows"], first["created"], first["snapshots"], first["skipped"]), (3, 2, 2, []))
        posts = {p["title"]: p for p in self.call("posts_list")["posts"]}
        pika = posts["Pikachu timelapse"]
        self.assertEqual((pika["status"], pika["published_at"], pika["metrics_latest"]["views"]), ("published", "2026-09-14", 1250))
        self.assertEqual((pika["metrics_latest"]["revenue"], pika["metrics_latest"]["currency"]), ("1.20", "USD"))
        second = self.run_import(YT, "youtube")
        self.assertEqual((second["created"], second["snapshots"], second["unchanged"]), (0, 0, 2))
        changed = YT.replace('"1.250"', '"2.000"')
        third = self.run_import(changed, "youtube")
        self.assertEqual((third["snapshots"], third["unchanged"]), (1, 1))
        self.assertEqual(self.call("post_get", post_id=pika["id"])["post"]["metrics_latest"]["views"], 2000)
        self.assertEqual(len(self.call("post_get", post_id=pika["id"])["post"]["metrics"]), 2)

    def test_import_matches_an_existing_post_by_title_or_url(self):
        mine = self.call("post_upsert", platform="instagram_reel", title="Reel Eevee")["post"]
        self.run_import(IG, "instagram_reel")
        posts = self.call("posts_list")["posts"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["id"], mine["id"])
        self.assertEqual((posts[0]["url"], posts[0]["metrics_latest"]["saves"], posts[0]["metrics_latest"]["shares"]),
                         ("https://instagram.com/reel/AAA/", 40, 10))
        # a second platform's rows never touch posts of another platform
        self.run_import(TT, "tiktok")
        self.assertEqual(len(self.call("posts_list")["posts"]), 2)
        self.assertEqual(self.call("posts_list", platform="tiktok")["posts"][0]["metrics_latest"]["views"], 900)

    def test_bad_input_is_reported(self):
        with mercator.session() as conn:
            for text, platform, mapping in (("", "youtube", {}), (YT, "myspace", {"title": "Video title"}), (YT, "youtube", {}),
                                            (YT, "youtube", {"title": "Nope"}), (YT, "youtube", "x")):
                with self.assertRaises(ValueError, msg=(platform, mapping)):
                    post_csv.import_rows(conn, text, platform, mapping)
            result = post_csv.import_rows(conn, "Video title,Views\nA,abc\n,5\n", "youtube", {"title": "Video title", "views": "Views"})
        self.assertEqual(result["created"], 1)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertTrue(result["warnings"])


class SalesBatchTests(Base):
    CSV = "id,date,product,amount,currency\nA,2026-09-28,Model A,12.50,EUR\nB,2026-09-28,Model B,9.00,USD\n"

    def test_import_creates_a_batch_with_event_and_lines(self):
        result = mercator.import_sales_batch(self.CSV, SALES_COLUMNS)
        self.assertEqual((result["rows"], result["added"], result["duplicates"]), (2, 2, 0))
        self.assertEqual(self.kinds(), ["mercator.sales.imported"])
        event = self.events[0][1]
        self.assertEqual((event["batch"], event["added"]), (result["batch"], 2))
        batch = self.call("sales_batch_get", batch=result["batch"])
        self.assertEqual(batch["count"], 2)
        self.assertEqual([l["line"] for l in batch["lines"]], [1, 2])
        self.assertEqual((batch["lines"][0]["product"], batch["lines"][0]["amount"], batch["lines"][0]["currency"]), ("Model A", "12.50", "EUR"))
        self.assertEqual(batch["by_currency"], [{"currency": "EUR", "income": "12.50"}, {"currency": "USD", "income": "9.00"}])

    def test_reimport_adds_nothing_and_emits_nothing(self):
        mercator.import_sales_batch(self.CSV, SALES_COLUMNS)
        self.events.clear()
        again = mercator.import_sales_batch(self.CSV, SALES_COLUMNS)
        self.assertEqual(again["added"], 0)
        self.assertEqual(self.events, [])
        self.assertEqual(self.call("sales_batch_get", batch=again["batch"])["count"], 0)

    def test_new_rows_of_a_second_file_form_their_own_batch(self):
        first = mercator.import_sales_batch(self.CSV, SALES_COLUMNS)
        second = mercator.import_sales_batch(self.CSV + "C,2026-09-29,Model C,3.00,EUR\n", SALES_COLUMNS)
        self.assertNotEqual(first["batch"], second["batch"])
        lines = self.call("sales_batch_get", batch=second["batch"])["lines"]
        self.assertEqual([l["product"] for l in lines], ["Model C"])
        self.assertEqual(self.call("sales_batch_get", batch=first["batch"])["count"], 2)

    def test_legacy_function_keeps_its_three_counters_and_unknown_batch_is_an_error(self):
        self.assertEqual(mercator.import_sales(self.CSV, SALES_COLUMNS), {"rows": 2, "added": 2, "duplicates": 0})
        with self.assertRaises(ValueError):
            self.call("sales_batch_get", batch="imp-nope")

    def test_store_created_before_batches_is_migrated(self):
        old = self.data / "old"
        old.mkdir()
        db = old / "mercator.sqlite3"
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.executescript("CREATE TABLE sales (fingerprint TEXT PRIMARY KEY, sold_at TEXT NOT NULL, product TEXT NOT NULL, "
                               "amount TEXT NOT NULL, currency TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'cults-csv');"
                               "CREATE TABLE sales_imports (imported_at TEXT NOT NULL, file_hash TEXT NOT NULL, rows INTEGER NOT NULL, added INTEGER NOT NULL);"
                               "INSERT INTO sales VALUES ('f1','2026-01-01','Old','1.00','EUR','cults-csv');")
        with patch.object(mercator, "DATA", old), patch.object(mercator, "DB", db):
            mercator.database()
            result = mercator.import_sales_batch(self.CSV, SALES_COLUMNS)
            self.assertEqual(result["added"], 2)
            self.assertEqual(mercator.summary()["sales_count"], 3)


class CatalogTests(Base):
    LISTINGS = [{"ref": "vulcan:folder:1:Contornos/Pikachu", "kind": "folder", "title": "Pikachu outline", "description": "A" * 50,
                 "tags": ["pokemon", "outline"], "price": "4.99", "currency": "EUR", "folder": "Contornos/Pikachu",
                 "model_ids": [3, 4], "status": "approved", "updated_at": "2026-10-01T10:00:00"},
                {"ref": "vulcan:model:9", "kind": "model", "title": "Solo en Vulcan", "description": "", "tags": [], "price": None,
                 "folder": "Otros/Solo", "model_ids": [9]},
                {"ref": "", "title": "sin ref"}, "no es un dict"]

    def test_catalog_from_vulcan_upserts_and_merges_into_the_catalogue(self):
        root = self.data / "products"
        (root / "Pikachu").mkdir(parents=True)
        (root / "Pikachu" / "cults3d.json").write_text(json.dumps({"title": "Pikachu", "tags": ["a"]}), encoding="utf-8")
        answer = {"ok": True, "result": {"ok": True, "listings": self.LISTINGS}}
        with patch.object(mercator_family, "call", return_value=answer) as called, \
                patch.object(mercator, "secrets", return_value={"MERCATOR_PRODUCTS_DIR": str(root)}):
            first = self.call("catalog_from_vulcan")
            self.assertEqual((first["received"], first["added"], first["skipped"]), (4, 2, 2))
            again = self.call("catalog_from_vulcan", folder="Contornos")
            self.assertEqual((again["added"], again["updated"], again["unchanged"]), (0, 0, 2))
            self.assertEqual(called.call_args_list[0].args[:2], ("vulcan", "listings_export_catalog"))
            self.assertEqual(called.call_args_list[1].args[2], {"folder": "Contornos"})
            catalog = mercator.products()
            items = {item["id"]: item for item in catalog["items"]}
            self.assertEqual(sorted(items), ["Pikachu", "Solo"])
            self.assertEqual(items["Pikachu"]["catalog"]["price"], "4.99")
            self.assertEqual(items["Pikachu"]["tags"], 1)           # the folder scan still wins for folders on disk
            self.assertFalse(items["Solo"]["has_listing"])
            self.assertEqual(mercator.catalog_query(query="solo")["items"][0]["id"], "Solo")
            changed = [dict(self.LISTINGS[0], title="Pikachu v2")]
            called.return_value = {"ok": True, "result": {"ok": True, "listings": changed}}
            self.assertEqual(self.call("catalog_from_vulcan")["updated"], 1)

    def test_vulcan_not_running_or_bad_answer(self):
        with patch.object(mercator_family, "call", return_value={"ok": False, "error": "hub not reachable"}):
            result = self.call("catalog_from_vulcan")
        self.assertFalse(result["ok"])
        self.assertIn("Vulcan", result["error"])
        for payload in ({"ok": False, "error": "boom"}, {"nothing": 1}, "text"):
            with patch.object(mercator_family, "call", return_value={"ok": True, "result": payload}):
                self.assertFalse(self.call("catalog_from_vulcan")["ok"])
        self.assertEqual(mercator.products()["state"], "needs_access") if not Path.home().joinpath("Desktop").exists() else None

    def test_catalogue_store_is_read_only_when_missing(self):
        self.assertEqual(cults_catalog.list_items(self.data / "absent.sqlite3"), [])


class CaptionTests(Base):
    def test_suggestions_come_from_a_resident_model_or_fail_clearly(self):
        post = self.call("post_upsert", platform="x", title="Pikachu en 3D", notes="Impreso en PLA")["post"]
        seen = {}

        def fake(system, user):
            seen["system"], seen["user"] = system, user
            return "1. Primera opción\n2) Segunda\n3. Tercera\n4. Cuarta"
        with patch.object(agent_tools, "llm", fake):
            result = self.call("post_caption_suggest", post_id=post["id"])
        self.assertEqual(result["suggestions"], ["Primera opción", "Segunda", "Tercera"])
        self.assertIn("280", seen["system"])
        self.assertIn("Impreso en PLA", seen["user"])
        with patch.object(agent_tools, "llm", lambda s, u: None):
            self.assertFalse(self.call("post_caption_suggest", title="x")["ok"])
        with self.assertRaises(ValueError):
            self.call("post_caption_suggest")


class ContractTests(Base):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), mercator.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.token = Path(self.token_file).read_text().strip()

    def http(self, method, path, body=None, token=None, headers=None):
        with closing(HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)) as conn:
            head = {"Host": "127.0.0.1", **(headers or {})}
            if token:
                head["Authorization"] = "Bearer " + token
            data = json.dumps(body).encode() if body is not None else None
            if data:
                head["Content-Type"] = "application/json"
            conn.request(method, path, data, head)
            response = conn.getresponse()
            raw = response.read()
            return response.status, raw, dict(response.getheaders())

    def json(self, *args, **kwargs):
        status, raw, _ = self.http(*args, **kwargs)
        return status, json.loads(raw)

    def test_health_block_and_tools_list(self):
        status, health = self.json("GET", "/api/health")
        self.assertEqual((status, health["service"], health["hoard_link"]["app"]), (200, "mercator-hoard", "mercator"))
        status, tools = self.json("GET", "/api/agent/tools")
        names = {t["name"] for t in tools["tools"]}
        self.assertEqual(status, 200)
        for needed in ("posts_list", "post_get", "post_upsert", "post_schedule", "post_publish", "post_metrics_add", "posts_stats",
                       "post_draft_from_media", "sales_batch_get", "catalog_from_vulcan", "mercator_catalog", "mercator_sales"):
            self.assertIn(needed, names)

    def test_agent_call_needs_the_token_and_maps_errors(self):
        self.assertEqual(self.http("POST", "/api/agent/call", {"name": "posts_list"})[0], 401)
        self.assertEqual(self.http("POST", "/api/agent/call", {"name": "posts_list"}, token="wrong")[0], 401)
        status, body = self.json("POST", "/api/agent/call", {"name": "post_draft_from_media", "arguments": {"media_ref": "hoard://lumiere/render/1", "title": "T"}},
                                 token=self.token)
        self.assertEqual((status, body["created"]), (200, True))
        status, body = self.json("POST", "/api/agent/call", {"name": "no_such_tool", "arguments": {}}, token=self.token)
        self.assertEqual(status, 404)
        self.assertIn("Unknown tool", body["error"])
        status, body = self.json("POST", "/api/agent/call", {"name": "post_get", "arguments": {"post_id": 99}}, token=self.token)
        self.assertEqual(status, 400)
        self.assertIn("No existe", body["error"])
        # the hub's call shape also carries "tool" and "caller"
        status, body = self.json("POST", "/api/agent/call", {"tool": "posts_list", "name": "posts_list", "arguments": {}, "caller": "hub"}, token=self.token)
        self.assertEqual((status, body["total"]), (200, 1))

    def test_agenda_route(self):
        self.call("post_upsert", platform="x", title="Mañana", status="scheduled", scheduled_at="2026-10-05T09:00")
        self.assertEqual(self.http("GET", "/api/family/agenda")[0], 401)
        status, body = self.json("GET", "/api/family/agenda?from=2026-10-01&to=2026-10-31&sphere=personal", token=self.token)
        self.assertEqual((status, body["ok"], len(body["items"])), (200, True, 1))
        self.assertEqual(body["items"][0]["kind"], "publish")

    def test_ui_flow_over_http_emits_events(self):
        status, made = self.json("POST", "/api/posts", {"platform": "youtube", "title": "Vídeo", "status": "scheduled", "scheduled_at": "2026-10-05T18:00"})
        self.assertEqual(status, 200)
        pid = made["post"]["id"]
        self.assertEqual(self.json("POST", "/api/posts/metrics", {"post_id": pid, "views": "10"})[0], 200)
        status, listed = self.json("GET", "/api/posts?status=scheduled")
        self.assertEqual(listed["posts"][0]["metrics_latest"]["views"], 10)
        self.assertEqual(self.json("GET", "/api/posts/stats")[1]["posts"], 1)
        self.assertEqual(self.json("GET", f"/api/posts/{pid}")[1]["post"]["metrics"][0]["views"], 10)
        self.assertEqual(self.json("POST", "/api/posts", {"platform": "nope", "title": "x"})[0], 400)
        self.assertEqual(self.json("POST", "/api/posts/delete", {"post_id": pid})[0], 200)
        self.assertEqual(self.json("GET", f"/api/posts/{pid}")[0], 400)
        self.assertIn("mercator.post.scheduled", self.kinds())

    def test_csv_routes(self):
        status, preview = self.json("POST", "/api/posts/import/preview", {"csv": YT, "platform": "youtube"})
        self.assertEqual((status, preview["preset"]), (200, "youtube_studio"))
        status, result = self.json("POST", "/api/posts/import", {"csv": YT, "platform": "youtube", "mapping": preview["mapping"]})
        self.assertEqual((status, result["created"]), (200, 2))
        self.assertEqual(self.json("POST", "/api/posts/import", {"csv": YT, "platform": "youtube", "mapping": {}})[0], 400)

    def test_sales_import_route_returns_the_batch(self):
        status, result = self.json("POST", "/api/sales/import", {"csv": SalesBatchTests.CSV, "columns": SALES_COLUMNS})
        self.assertEqual(status, 200)
        self.assertTrue(result["batch"].startswith("imp-"))
        self.assertEqual(self.kinds(), ["mercator.sales.imported"])

    def test_media_is_served_with_ranges_and_only_for_media_files(self):
        picture = self.data / "clip.mp4"
        picture.write_bytes(bytes(range(200)))
        text = self.data / "secret.txt"
        text.write_text("no")
        a = self.call("post_upsert", platform="instagram_reel", title="v", media_ref=str(picture))["post"]
        b = self.call("post_upsert", platform="instagram_reel", title="t", media_ref=str(text))["post"]
        c = self.call("post_upsert", platform="instagram_reel", title="h", media_ref="hoard://lumiere/render/1")["post"]
        status, raw, headers = self.http("GET", f"/api/posts/{a['id']}/media")
        self.assertEqual((status, len(raw), headers["Content-Type"]), (200, 200, "video/mp4"))
        status, raw, headers = self.http("GET", f"/api/posts/{a['id']}/media", headers={"Range": "bytes=10-19"})
        self.assertEqual((status, raw, headers["Content-Range"]), (206, bytes(range(10, 20)), "bytes 10-19/200"))
        status, raw, _ = self.http("GET", f"/api/posts/{a['id']}/media", headers={"Range": "bytes=-5"})
        self.assertEqual((status, raw), (206, bytes(range(195, 200))))
        self.assertEqual(self.http("GET", f"/api/posts/{a['id']}/media", headers={"Range": "bytes=500-600"})[0], 416)
        self.assertEqual(self.http("GET", f"/api/posts/{b['id']}/media")[0], 404)
        self.assertEqual(self.http("GET", f"/api/posts/{c['id']}/media")[0], 404)

    def test_pages_are_served_and_foreign_hosts_refused(self):
        for path, marker in (("/publicacion", b"Publicaci"), ("/publicacion.js", b"openEditor"), ("/publicacion.css", b".cal-grid")):
            status, raw, _ = self.http("GET", path)
            self.assertEqual(status, 200)
            self.assertIn(marker, raw)
        self.assertEqual(self.http("POST", "/api/agent/call", {"name": "posts_list"}, token=self.token, headers={"Host": "evil.example"})[0], 403)


class ToolCatalogueTests(unittest.TestCase):
    def test_first_lines_fit_the_tool_index_and_read_only_tools_say_so(self):
        for tool in agent_tools.tool_catalog():
            first = tool["description"].split("\n", 1)[0]
            self.assertLessEqual(len(first), 110, (tool["name"], len(first)))
            self.assertIn("readOnlyHint", tool["annotations"])
            self.assertGreater(len(tool["description"]), len(first), tool["name"])
        read_only = {t["name"] for t in agent_tools.tool_catalog() if t["annotations"]["readOnlyHint"]}
        self.assertTrue({"posts_list", "post_get", "posts_stats", "sales_batch_get", "mercator_catalog", "mercator_sales"} <= read_only)
        self.assertFalse({"post_upsert", "post_publish", "post_schedule", "post_metrics_add", "catalog_from_vulcan"} & read_only)

    def test_stdio_bridge_lists_and_runs_the_new_tools(self):
        with tempfile.TemporaryDirectory() as data:
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "post_upsert", "arguments": {"platform": "x", "title": "Hola"}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "posts_list", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "post_get", "arguments": {"post_id": 77}}},
            ]
            script = Path(mercator.__file__).with_name("mcp_server.py")
            child = subprocess.run([sys.executable, str(script)], input="".join(json.dumps(r) + "\n" for r in requests), text=True,
                                   encoding="utf-8", capture_output=True, timeout=20,
                                   env={**os.environ, "MERCATOR_DATA_DIR": data, "HOARD_EVENTS": "0"})
            self.assertEqual(child.returncode, 0, child.stderr)
            replies = [json.loads(line) for line in child.stdout.splitlines()]
            self.assertIn("post_draft_from_media", {t["name"] for t in replies[0]["result"]["tools"]})
            self.assertEqual(json.loads(replies[2]["result"]["content"][0]["text"])["posts"][0]["title"], "Hola")
            self.assertTrue(replies[3]["result"]["isError"])


class PublishingUnitTests(unittest.TestCase):
    def test_normalisers(self):
        self.assertEqual(publishing.norm_when("2026-10-05T18:30"), "2026-10-05T18:30:00")
        self.assertEqual(publishing.norm_when("2026-10-05 18:30"), "2026-10-05T18:30:00")
        self.assertEqual(publishing.norm_when("05/10/2026 18:30"), "2026-10-05T18:30:00")
        self.assertEqual(publishing.norm_when("2026-10-05"), "2026-10-05")
        self.assertIsNone(publishing.norm_when(""))
        with self.assertRaises(ValueError):
            publishing.norm_when("2026-13-45")
        self.assertEqual(publishing.norm_ts("2026-09-15T10:00:00+02:00"), "2026-09-15T08:00:00+00:00")
        self.assertEqual(publishing.norm_hashtags(["#a", "A", " b c ", ""]), ["a", "bc"])
        self.assertEqual(post_csv.parse_count("1.234"), 1234)
        self.assertEqual(post_csv.parse_count("1,234"), 1234)
        self.assertEqual(post_csv.parse_count("12"), 12)
        self.assertIsNone(post_csv.parse_count("12.5"))
        self.assertEqual(post_csv.parse_when("5 sept 2026"), "2026-09-05")
        self.assertEqual(post_csv.parse_when("Sep 14, 2026"), "2026-09-14")


if __name__ == "__main__":
    unittest.main()
