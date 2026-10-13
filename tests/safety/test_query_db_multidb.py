"""Phase D1 — query_db multi-DB read access (ARCH-ENG-083).

Agents could previously only read agent.db; the earning tabs' data
(opportunities/outcomes), portfolio, autonomous runs, and learning memory were
unreachable. query_db now accepts an allowlisted `db` store name resolved via
the canonical STORE_AUTHORITIES contract. Invariants:
- known store names resolve to the right file; default is agent.db (back-compat).
- unknown / path-traversal names are REJECTED (never an arbitrary path).
- queries remain SELECT-only (read-only enforcement unchanged).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

from agents.safety.handlers import _resolve_db_path, _tool_query_db


class TestResolveDbPath(unittest.TestCase):
    def test_known_stores_resolve(self):
        self.assertTrue(_resolve_db_path("agent").endswith("agent.db"))
        self.assertTrue(_resolve_db_path("earning").endswith("earning.db"))
        self.assertTrue(_resolve_db_path("memory").endswith("earning_memory.db"))
        self.assertTrue(_resolve_db_path("portfolio").endswith("opportunity_portfolio.db"))
        self.assertTrue(_resolve_db_path("autonomous_runs").endswith("autonomous_runs.db"))

    def test_default_is_agent_db(self):
        self.assertTrue(_resolve_db_path("").endswith("agent.db"))
        self.assertTrue(_resolve_db_path(None).endswith("agent.db"))

    def test_unknown_and_traversal_rejected(self):
        for bad in ("etc/passwd", "../../secret", "notastore", "agent.db"):
            with self.assertRaises(ValueError):
                _resolve_db_path(bad)


class TestQueryDbTool(unittest.TestCase):
    def test_reads_named_store(self):
        # earning.db exists in the repo; a SELECT must not error on resolution.
        out = _tool_query_db({"sql": "SELECT name FROM sqlite_master WHERE type='table' LIMIT 3",
                              "db": "earning"})
        self.assertNotIn("Query error", out)
        self.assertNotIn("unknown db", out)

    def test_unknown_db_reported_not_crashed(self):
        out = _tool_query_db({"sql": "SELECT 1", "db": "notastore"})
        self.assertIn("unknown db", out)

    def test_write_still_refused(self):
        out = _tool_query_db({"sql": "DELETE FROM opportunities", "db": "earning"})
        self.assertIn("read-only", out.lower())

    def test_default_db_back_compat(self):
        # No db arg -> agent.db (unchanged behavior).
        out = _tool_query_db({"sql": "SELECT count(*) FROM thoughts"})
        self.assertNotIn("unknown db", out)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
