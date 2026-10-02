"""What Mercator takes from the family library: money and dates, the shared store, the result cap, the token and the bridge."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

os.environ["HOARD_EVENTS"] = "0"

import agent_tools
import mercator
import mercator_family
import post_csv
import publishing
from support import HAVE_MCP, bridge_calls, dump, running_server

ROOT = Path(mercator.__file__).resolve().parent
COLUMNS = {"date": "date", "product": "product", "amount": "amount", "currency": "currency"}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        for name, value in (("DATA", self.data), ("DB", self.data / "mercator.sqlite3")):
            patcher = patch.object(mercator, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(mercator_family, "emit", lambda *a, **k: True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.token_file = mercator_family.configure(self.data)
        mercator.database()
        self.addCleanup(mercator.close_databases)

    def stored(self):
        with mercator.reading() as conn:
            return [(r["sold_at"], r["product"], r["amount"], r["currency"]) for r in conn.execute("SELECT * FROM sales ORDER BY rowid")]


class AmountTests(Base):
    def amounts(self, *cells, currency="EUR"):
        text = "date,product,amount,currency\n" + "".join(f'2026-09-28,P{i},"{c}",{currency}\n' for i, c in enumerate(cells))
        mercator.import_sales(text, COLUMNS)
        return [row[2] for row in self.stored()]

    def test_the_stored_text_keeps_the_digits_the_person_wrote(self):
        self.assertEqual(self.amounts("12", "12,50", "12.5", "1.234,56", "0,99", "-3"), ["12", "12.50", "12.5", "1234.56", "0.99", "-3"])

    def test_the_fingerprint_of_a_row_without_an_id_is_the_one_older_versions_stored(self):
        mercator.import_sales("date,product,amount,currency\n2026-09-28,Model,12,EUR\n", COLUMNS)
        legacy = hashlib.sha256("row:2026-09-28|Model|12|EUR|1".encode("utf-8")).hexdigest()
        with mercator.reading() as conn:
            self.assertEqual([r["fingerprint"] for r in conn.execute("SELECT fingerprint FROM sales")], [legacy])
        again = mercator.import_sales("date,product,amount,currency\n2026-09-28,Model,12,EUR\n", COLUMNS)
        self.assertEqual(again["added"], 0)

    def test_a_row_stored_by_an_older_version_is_not_counted_twice(self):
        legacy = hashlib.sha256("row:2026-09-28|Model|12.50|EUR|1".encode("utf-8")).hexdigest()
        with mercator.session() as conn:
            conn.execute("INSERT INTO sales(fingerprint,sold_at,product,amount,currency) VALUES (?,?,?,?,?)",
                         (legacy, "2026-09-28", "Model", "12.50", "EUR"))
        result = mercator.import_sales("date,product,amount,currency\n28/09/2026,Model,\"12,50\",EUR\n", COLUMNS)
        self.assertEqual((result["added"], result["duplicates"]), (0, 1))

    def test_a_lone_group_of_three_digits_is_thousands_unless_the_currency_writes_dots_as_decimals(self):
        self.assertEqual(self.amounts("1.234", "2,099"), ["1234", "2099"])

    def test_a_dollar_amount_with_a_dot_is_a_decimal(self):
        self.assertEqual(self.amounts("1.234", currency="USD"), ["1.234"])

    def test_the_column_decides_the_decimal_mark(self):
        self.assertEqual(self.amounts("1.234,5", "12,25", "1.500"), ["1234.5", "12.25", "1500"])

    def test_the_column_decides_the_decimal_mark_when_it_is_the_dot(self):
        self.assertEqual(self.amounts("1,234.5", "12.25", "1,500", "7"), ["1234.5", "12.25", "1500", "7"])

    def test_signs_symbols_and_spaces(self):
        self.assertEqual(self.amounts("(12.00)", "12,50 €", "$ 3.00", "1 299"), ["-12.00", "12.50", "3.00", "1299"])

    def test_a_cell_that_disagrees_with_its_column_is_read_on_its_own(self):
        self.assertEqual(self.amounts("12,50", "9.99"), ["12.50", "9.99"])

    def test_rubbish_is_refused(self):
        for bad in ("abc", "1,2,3x", "", "NaN"):
            with self.assertRaises(ValueError, msg=bad):
                mercator.import_sales(f"date,product,amount\n2026-09-28,P,\"{bad}\"\n", {"date": "date", "product": "product", "amount": "amount"})

    def test_publishing_revenue_uses_the_same_reader(self):
        self.assertEqual(publishing._money("12,50"), "12.50")
        self.assertEqual(publishing._money("12"), "12")
        self.assertEqual(publishing._money("1.234,5 €"), "1234.5")
        self.assertEqual(publishing._money("(3.00)"), "-3.00")
        self.assertIsNone(publishing._money(""))
        with self.assertRaises(ValueError):
            publishing._money("abc")
        self.assertEqual(publishing.parse_amount("12,50"), Decimal("12.50"))


class DateTests(unittest.TestCase):
    def test_forms_of_a_day(self):
        for text, day in (("2026-09-28", "2026-09-28"), ("2026-09-28 10:15:00", "2026-09-28"), ("2026-09-28T23:59:00Z", "2026-09-28"),
                          ("28/09/2026", "2026-09-28"), ("28-09-2026 10:15", "2026-09-28"), ("28.09.2026", "2026-09-28"),
                          ("12/25/2026", "2026-12-25"), ("5 sept 2026", "2026-09-05"), ("Sep 14, 2026", "2026-09-14"),
                          ("14 de septiembre de 2026", "2026-09-14"), ("March 3rd, 2026", "2026-03-03"), ("03/04/26", "2026-04-03")):
            self.assertEqual(publishing.day_of(text), day, text)

    def test_what_is_not_a_full_day_is_refused(self):
        for text in ("", "15/10", "15 oct", "2026-02-30", "31/02/2026", "ayer", None):
            self.assertIsNone(publishing.day_of(text), text)

    def test_csv_dates_are_read_with_the_same_rules(self):
        self.assertEqual(post_csv.parse_when("14 sept 2026"), "2026-09-14")
        self.assertEqual(post_csv.parse_when("Sep 14, 2026"), "2026-09-14")
        self.assertEqual(post_csv.parse_when("12/25/2026"), "2026-12-25")
        self.assertEqual(post_csv.parse_when("2026-09-14T10:00"), "2026-09-14T10:00:00")
        self.assertIsNone(post_csv.parse_when("soon"))

    def test_the_import_refuses_a_date_it_cannot_read(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(mercator, "DB", Path(folder) / "x.sqlite3"):
            try:
                with self.assertRaises(ValueError):
                    mercator.import_sales("date,product,amount\nsoon,P,1\n", {"date": "date", "product": "product", "amount": "amount"})
            finally:
                mercator.close_databases()


class StoreTests(Base):
    def test_the_store_is_shared_versioned_and_waits_for_a_busy_file(self):
        store = mercator.database()
        self.assertIs(store, mercator.database())
        self.assertEqual(store.schema_version, 2)
        self.assertEqual(store.scalar("PRAGMA journal_mode").lower(), "wal")
        self.assertEqual(store.scalar("PRAGMA busy_timeout"), 15000)

    def test_closing_removes_the_wal_files_and_the_store_opens_again(self):
        mercator.import_sales("date,product,amount\n2026-09-28,P,1\n", {"date": "date", "product": "product", "amount": "amount"})
        mercator.close_databases()
        self.assertEqual([p.name for p in self.data.glob("mercator.sqlite3-*")], [])
        self.assertEqual(mercator.summary()["sales_count"], 1)

    def test_a_failed_write_is_rolled_back_as_a_whole(self):
        with self.assertRaises(RuntimeError):
            with mercator.session() as conn:
                conn.execute("INSERT INTO sales(fingerprint,sold_at,product,amount,currency) VALUES ('f','2026-01-01','P','1','EUR')")
                raise RuntimeError("boom")
        self.assertEqual(self.stored(), [])

    def test_the_schema_is_the_one_the_dashboard_always_had(self):
        with mercator.reading() as conn:
            tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            batch_columns = {r["name"] for r in conn.execute("PRAGMA table_info(sales)")}
        self.assertTrue({"metrics", "source_status", "sales", "sales_imports", "posts", "post_metrics", "app_settings", "catalog_items",
                         "schema_version"} <= tables)
        self.assertIn("batch", batch_columns)

    def test_a_slow_provider_does_not_block_the_dashboard(self):
        release = threading.Event()
        entered = threading.Event()

        def slow(url, headers, body=None):
            entered.set()
            release.wait(20)
            raise TimeoutError()

        secrets = {"CLOUDFLARE_API_TOKEN": "x", "CLOUDFLARE_ACCOUNT_ID": "account"}
        with patch.object(mercator, "secrets", return_value=secrets), patch.object(mercator, "request_json", slow):
            worker = threading.Thread(target=mercator.refresh, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(10))
                started = time.monotonic()
                self.assertIn("statuses", mercator.summary())
                self.assertLess(time.monotonic() - started, 5, "the dashboard waited for the provider")
            finally:
                release.set()
                worker.join(30)


class AgentContractTests(Base):
    def post(self, port, body, token=True):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + Path(self.token_file).read_text(encoding="utf-8").strip()
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/agent/call", json.dumps(body), headers)
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    def test_errors_have_a_status_and_a_code(self):
        with running_server() as port:
            self.assertEqual(self.post(port, {"name": "post_get", "arguments": {"post_id": 1}}, token=False)[0], 401)
            status, body = self.post(port, {"name": "nope", "arguments": {}})
            self.assertEqual((status, body["code"], body["ok"]), (404, "unknown_tool", False))
            status, body = self.post(port, {"name": "post_get", "arguments": {}})
            self.assertEqual((status, body["code"]), (400, "invalid"))
            with patch.object(agent_tools, "call_tool", side_effect=sqlite3.OperationalError("disk I/O error")):
                status, body = self.post(port, {"name": "posts_list", "arguments": {}})
            self.assertEqual((status, body["code"]), (500, "internal"))
            self.assertIn("disk I/O error", body["error"])

    def test_an_assistant_answer_is_capped_and_the_web_page_is_not(self):
        with mercator.session() as conn:
            for number in range(60):
                publishing.upsert_post(conn, {"platform": "x", "title": f"Post {number}", "caption": "x" * 200 + "é", "notes": "n" * 400})
        capped = agent_tools.call_tool("posts_list", {"limit": 60})
        self.assertLessEqual(len(json.dumps(capped, ensure_ascii=False).encode("utf-8")), 20_000)
        self.assertIn("truncated", capped)
        self.assertEqual(capped["total"], 60)
        full = agent_tools.call_tool("posts_list", {"limit": 60}, cap=False)
        self.assertEqual(len(full["posts"]), 60)
        self.assertNotIn("truncated", full)

    def test_the_agenda_needs_the_token_and_lists_scheduled_posts(self):
        agent_tools.call_tool("post_upsert", {"platform": "x", "title": "Pronto", "status": "scheduled", "scheduled_at": "2026-10-05T18:30"})
        with running_server() as port:
            conn = HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/api/family/agenda?from=2026-10-01&to=2026-10-31")
            self.assertEqual(conn.getresponse().status, 401)
            conn.close()
            conn = HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/api/family/agenda?from=2026-10-01&to=2026-10-31",
                         headers={"Authorization": "bearer " + Path(self.token_file).read_text(encoding="utf-8").strip()})
            answer = json.loads(conn.getresponse().read())
            conn.close()
        self.assertEqual([i["title"] for i in answer["items"]], ["Publicar: Pronto (X)"])


class TokenTests(Base):
    def test_the_token_is_created_once_and_kept(self):
        first = Path(self.token_file).read_text(encoding="utf-8")
        self.assertGreaterEqual(len(first.strip()), 32)
        mercator_family.configure(self.data)
        self.assertEqual(Path(self.token_file).read_text(encoding="utf-8"), first)

    def test_a_missing_or_wrong_token_never_matches(self):
        token = Path(self.token_file).read_text(encoding="utf-8").strip()
        self.assertTrue(mercator_family.bearer_ok("Bearer " + token))
        self.assertTrue(mercator_family.bearer_ok("bearer  " + token))
        self.assertFalse(mercator_family.bearer_ok("Bearer " + token + "x"))
        self.assertFalse(mercator_family.bearer_ok("Bearer "))
        self.assertFalse(mercator_family.bearer_ok(""))
        Path(self.token_file).write_text("", encoding="utf-8")
        self.assertFalse(mercator_family.bearer_ok("Bearer "))


class GuardTests(Base):
    def status(self, port, method="GET", path="/api/health", headers=None, body=None):
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        response.read()
        conn.close()
        return response.status

    def test_the_family_guard_protects_the_dashboard(self):
        with running_server() as port:
            here = f"127.0.0.1:{port}"
            self.assertEqual(self.status(port, headers={"Host": here}), 200)
            self.assertEqual(self.status(port, headers={"Host": here, "Origin": f"http://{here}"}), 200)
            self.assertEqual(self.status(port, headers={"Host": "evil.example"}), 403)
            self.assertEqual(self.status(port, headers={"Host": "127.0.0.1:1"}), 403, "a Host naming another port is refused")
            self.assertEqual(self.status(port, headers={"Host": here, "Origin": "https://evil.example"}), 403)
            self.assertEqual(self.status(port, headers={"Host": here, "Origin": "http://127.0.0.1:1"}), 403)
            self.assertEqual(self.status(port, headers={"Host": here, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"}), 403)
            self.assertEqual(self.status(port, "POST", "/api/refresh", {"Host": here, "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin"}), 403,
                             "an HTML form post is refused")

    def test_a_listed_name_is_accepted(self):
        with running_server() as port, patch.dict(os.environ, {"MERCATOR_ALLOWED_HOSTS": "panel.lan"}):
            self.assertEqual(self.status(port, headers={"Host": "panel.lan"}), 200)
            self.assertEqual(self.status(port, headers={"Host": "other.lan"}), 403)


class NoHttpxTests(unittest.TestCase):
    def test_the_server_and_its_family_link_load_without_httpx(self):
        code = ("import sys; sys.modules['httpx'] = None\n"
                "import mercator, mercator_family, agent_tools, post_csv, publishing\n"
                "print(mercator_family.health_block()['version'])\n"
                "print(agent_tools.call_tool('mercator_sales', {})['total'])")
        with tempfile.TemporaryDirectory() as folder:
            out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60,
                                 env={**os.environ, "MERCATOR_DATA_DIR": folder, "HOARD_EVENTS": "0"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.split()[0], "0.8.0")

    def test_caption_suggestions_say_so_when_the_model_backend_is_missing(self):
        code = ("import sys; sys.modules['httpx'] = None\n"
                "import agent_tools\n"
                "print(agent_tools._default_llm('s', 'u'))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "None")


@unittest.skipUnless(HAVE_MCP, "the stdio bridge needs the mcp package")
class BridgeTests(Base):
    def test_the_bridge_is_the_family_catalogue_bridge_for_this_app(self):
        import mcp_server
        bridge = mcp_server.make_bridge()
        self.assertEqual((bridge.service, bridge.package, bridge.default_port), ("mercator-hoard", "mercator", 5195))
        self.assertEqual(bridge.root, ROOT)
        with patch.dict(os.environ, {"MERCATOR_DATA_DIR": ""}):
            self.assertEqual(bridge.data_dir, ROOT / "data")

    def test_every_tool_of_the_catalogue_is_served_and_errors_keep_their_text(self):
        names = [t["name"] for t in agent_tools.tool_catalog()]
        with running_server() as port:
            answer = bridge_calls(port, self.data, [("post_get", {"post_id": 999}), ("posts_stats", {})])
        self.assertEqual([t.name for t in answer["tools"]], names)
        self.assertTrue(dump(answer["results"][0])["isError"])
        self.assertIn("999", answer["results"][0].content[0].text)
        self.assertFalse(dump(answer["results"][1])["isError"])

    def test_without_a_server_the_bridge_exits_with_a_message_naming_what_to_open(self):
        with tempfile.TemporaryDirectory() as folder:
            out = subprocess.run([sys.executable, str(ROOT / "mcp_server.py")], cwd=ROOT, capture_output=True, text=True, timeout=60, input="",
                                 env={**os.environ, "MERCATOR_URL": "http://127.0.0.1:9", "MERCATOR_DATA_DIR": folder,
                                      "MERCATOR_BRIDGE_AUTOSTART": "0"})
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("Mercator's Hoard", out.stderr)


if __name__ == "__main__":
    unittest.main()
