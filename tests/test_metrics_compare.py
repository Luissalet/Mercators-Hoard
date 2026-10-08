"""Saved snapshot comparisons: cumulative endpoints, never a daily activity sum."""
from test_publishing import Base
from support import HAVE_MCP, bridge_calls, dump, running_server
import unittest
import agent_tools


class CompareTests(Base):
    def setUp(self):
        super().setUp()
        self.post = self.call("post_upsert", platform="youtube", title="Demo")["post"]["id"]

    def add(self, ts, **values):
        return self.call("post_metrics_add", post_id=self.post, ts=ts, **values)["metrics"]

    def compare(self, start="2026-10-01T10:00:00Z", end="2026-10-02T10:00:00Z"):
        return self.call("post_metrics_compare", post_id=self.post, from_ts=start, to_ts=end)

    def test_endpoints_offsets_exact_money_and_read_only(self):
        a = self.add("2026-10-01T10:00:00Z", views=100, revenue="10,10", currency="EUR")
        self.add("2026-10-01T12:00:00Z", views=180, revenue="11,20", currency="EUR")
        b = self.add("2026-10-02T10:00:00Z", views=250, revenue="12,50", currency="EUR")
        self.add("2026-10-03T10:00:00Z", views=999)
        before = self.call("post_get", post_id=self.post)
        got = self.compare("2026-10-01T12:00:00+02:00")
        self.assertEqual([got[k]["id"] for k in ("before_snapshot", "after_snapshot")], [a["id"], b["id"]])
        self.assertEqual(got["metrics"]["views"]["delta"], 150)
        self.assertEqual(got["metrics"]["views"]["percent_change"], 150)
        self.assertEqual(got["revenue"]["delta"], "2.40")
        self.assertEqual(got, self.compare())
        self.assertEqual(before, self.call("post_get", post_id=self.post))
        self.assertEqual(self.kinds(), [])

    def test_negative_correction_and_tie_uses_last_inserted(self):
        self.add("2026-10-01T10:00:00Z", views=100)
        self.add("2026-10-02T10:00:00Z", views=150)
        last = self.add("2026-10-02T10:00:00Z", views=80)
        got = self.compare()
        self.assertEqual(got["after_snapshot"]["id"], last["id"])
        self.assertEqual((got["metrics"]["views"]["delta"], got["metrics"]["views"]["percent_change"]), (-20, -20))

    def test_sparse_rows_are_not_backfilled_and_currency_not_mixed(self):
        self.add("2026-10-01T10:00:00Z", views=100, likes=8, revenue="1", currency="EUR")
        self.add("2026-10-02T10:00:00Z", likes=12, revenue="2", currency="USD")
        got = self.compare()
        self.assertIsNone(got["metrics"]["views"]["delta"])
        self.assertIsNone(got["metrics"]["views"]["after"])
        self.assertEqual(got["metrics"]["likes"]["delta"], 4)
        self.assertEqual(got["revenue"]["reason"], "currency_mismatch")
        self.assertIsNone(got["revenue"]["delta"])

    def test_absent_baseline_zero_and_same_snapshot(self):
        empty = self.compare()
        self.assertIsNone(empty["before_snapshot"])
        self.assertIsNone(empty["after_snapshot"])
        self.add("2026-10-01T10:00:00Z", views=0)
        self.add("2026-10-02T10:00:00Z", views=50)
        missing = self.compare("2026-09-30T10:00:00Z")
        self.assertIsNone(missing["before_snapshot"])
        self.assertIsNone(missing["metrics"]["views"]["delta"])
        got = self.compare()["metrics"]["views"]
        self.assertEqual(got["delta"], 50)
        self.assertEqual(got["reason"], "zero_baseline")
        self.assertIsNone(got["percent_change"])
        same = self.compare("2026-10-02T11:00:00Z", "2026-10-02T12:00:00Z")
        self.assertEqual(same["before_snapshot"], same["after_snapshot"])
        self.assertEqual(same["metrics"]["views"]["delta"], 0)

    def test_errors_and_catalog(self):
        for args in ({"from_ts": "yesterday", "to_ts": "2026-10-02"},
                     {"from_ts": "2026-10-03T00:00:00Z", "to_ts": "2026-10-02T00:00:00Z"},
                     {"from_ts": "", "to_ts": "2026-10-02T00:00:00Z"}):
            with self.assertRaises(ValueError):
                self.call("post_metrics_compare", post_id=self.post, **args)
        with self.assertRaises(ValueError):
            self.call("post_metrics_compare", post_id=999, from_ts="2026-10-01", to_ts="2026-10-02")
        tool = next(t for t in agent_tools.tool_catalog() if t["name"] == "post_metrics_compare")
        self.assertTrue(tool["annotations"]["readOnlyHint"])

    @unittest.skipUnless(HAVE_MCP, "mcp package unavailable")
    def test_real_mcp_transport(self):
        self.add("2026-10-01T10:00:00Z", views=100)
        self.add("2026-10-02T10:00:00Z", views=130)
        args = {"post_id": self.post, "from_ts": "2026-10-01T10:00:00Z", "to_ts": "2026-10-02T10:00:00Z"}
        with running_server() as port:
            result = bridge_calls(port, self.data, [("post_metrics_compare", args)])
        import json
        answer = dump(result["results"][0])
        self.assertFalse(answer.get("isError"))
        value = json.loads(answer["content"][0]["text"])
        self.assertEqual(value["metrics"]["views"]["delta"], 30)
