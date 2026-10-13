"""Phase D1 — query_db multi-DB read access (ARCH-ENG-083).

Agents could previously only read agent.db; the earning tabs' data
(opportunities/outcomes), portfolio, autonomous runs, and learning memory were
unreachable. query_db now accepts an allowlisted `db` store name resolved via
the canonical STORE_AUTHORITIES contract. Invariants:
- known store names resolve to the right file; default is agent.db (back-compat).
- unknown / path-traversal names are REJECTED (never an arbitrary path).
- queries remain SELECT-only (read-only enforcement unchanged).

These tests build their OWN store files in a temp dir and point
`agents.safety.handlers.PROJECT_ROOT` at it. Every `*.db` is gitignored
(runtime state), so a fresh clone has no `earning.db` — and `_tool_query_db`
checks `os.path.exists` BEFORE the SQL validator. Depending on the repo's live
DB therefore made `test_write_still_refused` fail in a clone while passing
in-tree: it got "[Database not found: earning.db]" instead of "read-only",
so the invariant it exists to prove was never exercised. That is exactly the
class of environment-dependent test ARCH-ENG-111/112 fixed.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class _StoreRootTestCase(unittest.TestCase):
    """Base: a temp PROJECT_ROOT holding real (empty) store DBs.

    Patching `agents.safety.handlers.PROJECT_ROOT` (the name `_resolve_db_path`
    actually reads) makes the DBs exist without touching operator state and
    without depending on gitignored runtime files.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name
        for fname in ("agent.db", "earning.db", "earning_memory.db",
                      "opportunity_portfolio.db", "autonomous_runs.db"):
            conn = sqlite3.connect(os.path.join(root, fname))
            conn.execute("CREATE TABLE IF NOT EXISTS opportunities (id INTEGER)")
            conn.commit()
            conn.close()
        patcher = mock.patch("agents.safety.handlers.PROJECT_ROOT", Path(root))
        patcher.start()
        self.addCleanup(patcher.stop)


class TestQueryDbTool(_StoreRootTestCase):
    def test_reads_named_store(self):
        # earning.db exists (built by the base class); a SELECT must not error.
        out = _tool_query_db({"sql": "SELECT name FROM sqlite_master WHERE type='table' LIMIT 3",
                              "db": "earning"})
        self.assertNotIn("Query error", out)
        self.assertNotIn("unknown db", out)
        self.assertNotIn("not found", out.lower())

    def test_unknown_db_reported_not_crashed(self):
        out = _tool_query_db({"sql": "SELECT 1", "db": "notastore"})
        self.assertIn("unknown db", out)

    def test_write_still_refused(self):
        """The read-only gate must refuse a write, whatever the store.

        Asserts on the SQL validator's own wording, so the test cannot pass
        because the DB happened to be missing.
        """
        out = _tool_query_db({"sql": "DELETE FROM opportunities", "db": "earning"})
        self.assertIn("read-only", out.lower())
        self.assertNotIn("not found", out.lower(),
                         "the store must exist for this test to prove the gate")

    def test_default_db_back_compat(self):
        # No db arg -> agent.db (unchanged behavior).
        out = _tool_query_db({"sql": "SELECT count(*) FROM sqlite_master"})
        self.assertNotIn("unknown db", out)
        self.assertNotIn("not found", out.lower())


class TestMissingStoreIsReportedNotCrashed(unittest.TestCase):
    """A gitignored store legitimately absent must be reported, not crash."""

    def test_absent_store_reports_not_found(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch("agents.safety.handlers.PROJECT_ROOT", Path(root)):
                out = _tool_query_db({"sql": "SELECT 1", "db": "earning"})
        self.assertIn("not found", out.lower())
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
