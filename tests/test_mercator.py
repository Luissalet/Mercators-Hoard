import tempfile
import json
import os
import threading
import unittest
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import mercator
import mercator_family
from support import HAVE_MCP, bridge_calls, dump, running_server


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        data = Path(self.temp.name)
        patcher_data = patch.object(mercator, "DATA", data)
        patcher_db = patch.object(mercator, "DB", data / "mercator.sqlite3")
        patcher_data.start(); patcher_db.start()
        self.addCleanup(patcher_data.stop); self.addCleanup(patcher_db.stop)
        mercator.database()
        self.addCleanup(mercator.close_databases)

    def test_sales_import_is_idempotent_and_uses_decimal_comma(self):
        source = "sale,date,product,income,currency\nA,28/09/2026,Model A,12,50,EUR\n"
        # Quoted decimal comma as in a real CSV export.
        source = source.replace("12,50", '"12,50"')
        columns = {"id": "sale", "date": "date", "product": "product",
                   "amount": "income", "currency": "currency"}
        first = mercator.import_sales(source, columns)
        second = mercator.import_sales(source, columns)
        self.assertEqual(first, {"rows": 1, "added": 1, "duplicates": 0})
        self.assertEqual(second["added"], 0)
        sale = mercator.summary()["sales"][0]
        self.assertEqual((sale["sold_at"], sale["amount"]), ("2026-09-28", "12.50"))

    def test_semicolon_csv_preserves_two_identical_sales_without_ids(self):
        source = "fecha;producto;importe\n28/09/2026;Modelo A;12,50\n28/09/2026;Modelo A;12,50\n"
        columns = {"date": "fecha", "product": "producto", "amount": "importe"}
        self.assertEqual(mercator.import_sales(source, columns)["added"], 2)
        self.assertEqual(mercator.import_sales(source, columns)["added"], 0)
        self.assertEqual(mercator.summary()["sales_count"], 2)

    def test_supabase_never_treats_public_key_as_admin_access(self):
        config = {"env": Path(self.temp.name) / "public.env",
                  "public_env": Path(self.temp.name) / "public.env"}
        config["env"].write_text("EXPO_PUBLIC_SUPABASE_URL=https://example.supabase.co\n"
                                 "EXPO_PUBLIC_SUPABASE_ANON_KEY=public\n", encoding="utf-8")
        conn = mercator.database()
        with patch.object(mercator, "secrets", return_value={}):
            mercator.supabase_users(conn, "bookhoard", config)
        self.assertEqual(mercator.summary()["statuses"][0]["state"], "needs_access")
        self.assertEqual(mercator.summary()["metrics"], [])

    def test_supabase_timeout_marks_source_unavailable(self):
        config = {"env": Path(self.temp.name) / "server.env"}
        config["env"].write_text("SUPABASE_URL=https://example.supabase.co\n"
                                 "SUPABASE_SERVICE_ROLE_KEY=private\n", encoding="utf-8")
        conn = mercator.database()
        with patch.object(mercator, "request_json", side_effect=TimeoutError()):
            mercator.supabase_users(conn, "watchhoard", config)
        self.assertEqual(mercator.summary()["statuses"][0]["state"], "error")
        self.assertEqual(mercator.summary()["metrics"], [])

    def test_cloudflare_rejects_unexpected_multiple_aggregates(self):
        conn = mercator.database()
        with patch.object(mercator, "secrets", return_value={
            "CLOUDFLARE_API_TOKEN": "x", "CLOUDFLARE_ACCOUNT_ID": "account",
        }), patch.object(mercator, "request_json", return_value={
            "data": {"viewer": {"accounts": [{"workersInvocationsAdaptive":
                                                [{"sum": {"requests": 1}}] * 2}]}}
        }):
            mercator.cloudflare_worker(conn, "watchhoard", {"worker": "watchhoard"})
        self.assertEqual(mercator.summary()["statuses"][0]["state"], "error")
        self.assertEqual(mercator.summary()["metrics"], [])

    def test_local_server_rejects_foreign_host_and_origin(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), mercator.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for host, origin, expected in (("evil.example", None, 403),
                                       ("127.0.0.1", "https://evil.example", 403),
                                       ("127.0.0.1", None, 200)):
            with closing(HTTPConnection("127.0.0.1", server.server_port, timeout=3)) as conn:
                headers = {"Host": host}
                if origin:
                    headers["Origin"] = origin
                conn.request("GET", "/api/health", headers=headers)
                response = conn.getresponse()
                response.read()
                self.assertEqual(response.status, expected)

    def test_catalog_and_sales_queries_are_paged_and_currency_separated(self):
        root = Path(self.temp.name) / "products"
        root.mkdir()
        for name, tags in (("Tagged", ["pokemon", "figure"]), ("Untagged", [])):
            folder = root / name
            folder.mkdir()
            (folder / "cults3d.json").write_text(json.dumps({"title": name, "tags": tags}), encoding="utf-8")
        (root / "Pending").mkdir()
        with patch.object(mercator, "secrets", return_value={"MERCATOR_PRODUCTS_DIR": str(root)}):
            self.assertEqual(mercator.catalog_query(untagged=True)["items"][0]["id"], "Untagged")
            self.assertEqual(mercator.catalog_query(missing=True)["items"][0]["id"], "Pending")
            self.assertEqual(mercator.catalog_query(offset=1, limit=1)["total"], 3)
        mercator.import_sales("date,product,amount,currency\n2026-09-28,Tagged,12.50,EUR\n2026-09-28,Tagged,9.00,USD\n",
                              {"date": "date", "product": "product", "amount": "amount", "currency": "currency"})
        result = mercator.sales_query("Tagged", limit=1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["sales"]), 1)
        self.assertEqual(result["by_currency"], [{"currency": "EUR", "income": "12.50"}, {"currency": "USD", "income": "9.00"}])

    def test_catalog_http_uses_native_filters_and_pages_without_changing_listings(self):
        from urllib.parse import urlencode
        root = Path(self.temp.name) / 'catalog-http'
        root.mkdir()
        for name, content in [('A-zero', '{"title":"Mismo ñ","tags":[]}'),
                              ('B-bad-tags', '{"title":"Mismo ñ","tags":"wrong"}'),
                              ('C-malformed', '{'), ('D-nonobject', '[]')]:
            folder = root / name
            folder.mkdir()
            (folder / 'cults3d.json').write_text(content, encoding='utf8')
        (root / 'E-missing').mkdir()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('cults3d.json')}
        with patch.object(mercator, 'secrets', return_value={'MERCATOR_PRODUCTS_DIR': str(root)}), running_server() as port:
            for args in [{'untagged': True}, {'missing': True}, {'untagged': True, 'missing': True},
                         {'query': 'MISMO Ñ', 'offset': 1, 'limit': 1}]:
                native = mercator.catalog_query(**args)
                query = urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in args.items()})
                with closing(HTTPConnection('127.0.0.1', port, timeout=3)) as conn:
                    conn.request('GET', '/api/catalog?' + query)
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read()), native)
            self.assertEqual([r['id'] for r in mercator.catalog_query(untagged=True)['items']], ['A-zero', 'B-bad-tags'])
            self.assertEqual([r['id'] for r in mercator.catalog_query(missing=True)['items']], ['B-bad-tags', 'C-malformed', 'D-nonobject', 'E-missing'])
            with closing(HTTPConnection('127.0.0.1', port, timeout=3)) as conn:
                conn.request('GET', '/api/catalog?untagged=perhaps')
                response = conn.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
        with patch.object(mercator, 'secrets', return_value={'MERCATOR_PRODUCTS_DIR': str(root / 'not-here')}):
            self.assertEqual(mercator.catalog_query()['state'], 'needs_access')
        with patch.object(mercator, 'secrets', return_value={'MERCATOR_PRODUCTS_DIR': str(root)}):
            self.assertEqual(mercator.catalog_query(query='not found')['state'], 'ok')

    @unittest.skipUnless(HAVE_MCP, "the stdio bridge needs the mcp package")
    def test_mcp_stdio_reads_isolated_catalog_without_modifying_it(self):
        root = Path(self.temp.name) / "products"
        folder = root / "Modelo á"
        folder.mkdir(parents=True)
        listing = folder / "cults3d.json"
        listing.write_text(json.dumps({"title": "Modelo á", "tags": []}), encoding="utf-8")
        before = listing.read_bytes()
        mercator_family.configure(self.temp.name)
        with patch.dict(os.environ, {"MERCATOR_PRODUCTS_DIR": str(root)}), running_server() as port:
            answer = bridge_calls(port, self.temp.name, [("mercator_catalog", {"untagged": True}), ("mercator_sales", {})])
        tools = answer["tools"]
        self.assertEqual(dump(tools[0])["annotations"]["readOnlyHint"], True)
        self.assertIn("cuáles", tools[0].description)
        catalog = json.loads(answer["results"][0].content[0].text)
        self.assertEqual((catalog["items"][0]["tags"], catalog["items"][0]["id"]), (0, "Modelo á"))
        self.assertEqual(json.loads(answer["results"][1].content[0].text)["total"], 0)
        self.assertEqual(listing.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
