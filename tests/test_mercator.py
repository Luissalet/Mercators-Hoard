import tempfile
import threading
import unittest
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import mercator


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        data = Path(self.temp.name)
        patcher_data = patch.object(mercator, "DATA", data)
        patcher_db = patch.object(mercator, "DB", data / "mercator.sqlite3")
        patcher_data.start(); patcher_db.start()
        self.addCleanup(patcher_data.stop); self.addCleanup(patcher_db.stop)
        mercator.db().close()

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
        with closing(mercator.db()) as conn, conn, patch.object(mercator, "secrets", return_value={}):
            mercator.supabase_users(conn, "bookhoard", config)
        self.assertEqual(mercator.summary()["statuses"][0]["state"], "needs_access")
        self.assertEqual(mercator.summary()["metrics"], [])

    def test_supabase_timeout_marks_source_unavailable(self):
        config = {"env": Path(self.temp.name) / "server.env"}
        config["env"].write_text("SUPABASE_URL=https://example.supabase.co\n"
                                 "SUPABASE_SERVICE_ROLE_KEY=private\n", encoding="utf-8")
        with closing(mercator.db()) as conn, conn, patch.object(mercator, "request_json", side_effect=TimeoutError()):
            mercator.supabase_users(conn, "watchhoard", config)
        self.assertEqual(mercator.summary()["statuses"][0]["state"], "error")
        self.assertEqual(mercator.summary()["metrics"], [])

    def test_cloudflare_rejects_unexpected_multiple_aggregates(self):
        with closing(mercator.db()) as conn, conn, patch.object(mercator, "secrets", return_value={
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


if __name__ == "__main__":
    unittest.main()
