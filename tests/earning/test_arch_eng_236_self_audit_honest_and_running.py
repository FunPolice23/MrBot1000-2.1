"""ARCH-ENG-236 / AJ-01 + AJ-02 -- the self-audit engine must be reachable AND
honest about its data basis.

The findings
------------
AJ-01 (high): `SelfAuditEngine` was constructed exactly once
(`earning_pipeline.py:181`) and the attribute was never read again.
`run_audit()` -- the engine's only public entry point -- had no production
caller; all fourteen `_audit_*` methods were reachable only from it, hence dead
by transitivity. 15 methods, ~460 lines, zero reachable entry.

AJ-02 (high, restated by 11s): the empty outcome tables are ARCH-ENG-158
*succeeding* (fail-closed on unverified payments), the designed resting state.
A self-audit layer that ran anyway would return zero findings and read as a
clean bill of health -- converting a visible gap into invisible assurance.
The load-bearing requirement: the audit must permanently distinguish
"insufficient data" from "no problems".

The fix (both halves, in the 11r-prescribed order)
---------------------------------------------------
1. Every `_audit_*` now declares the data basis it actually saw
   (`AuditReport.basis`, by category value: rows examined, or 1 when a gated
   in-memory/on-disk source was present). A category with no basis or zero
   rows is INSUFFICIENT; `AuditReport.conclusion()` refuses to claim a clean
   bill while any audit is data-starved, and run-level guards record engine
   errors instead of letting audits fail silently clean.
2. `EarningPipeline.run_full_cycle` calls `run_self_audit()` once per live
   cycle and logs the honest conclusion (the `[SelfAudit]` line) -- the
   missing last hop.

A tree-specific honesty note: `agents/IMPROVEMENTS.md` does not exist, so the
`documentation_drift` audit's source is absent and its basis is never
declared -- meaning a fully-populated database still reads as
"INSUFFICIENT DATA (1 of 14)". That is the discipline working, not a defect:
the absence of a source is recorded, never papered over.

Vacuity probe (2026-10-19): against the pre-fix tree, the conclusion/basis
assertions fail (no such fields exist to be wrong), and the [SelfAudit] log
line never appears because run_full_cycle never called the engine.
"""

import os
import shutil
import sqlite3
import tempfile
import time
import types
import unittest
from typing import Any, Dict, List, Optional

from agents.services.self_audit import AuditCategory, SelfAuditEngine
from app.earning_pipeline import EarningPipeline


class FakeMemory:
    """Same fixture contract as tests/earning/test_self_audit.py."""

    def __init__(self, db_path: str, portfolio=None, wallet_manager=None):
        self.db_path = db_path
        self.portfolio = portfolio
        self.wallet_manager = wallet_manager

    def get_platform_reputation(self, platform: str) -> Optional[Dict]:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT success_count, failed_count, scam_count, avg_revenue, "
            "total_attempts, last_attempt FROM reputation_memory "
            "WHERE platform=?", (platform,)
        ).fetchone()
        conn.close()
        if row:
            total = row[4]
            return {
                "platform": platform, "success": row[0], "failed": row[1],
                "scam": row[2], "avg_revenue": row[3], "total": total,
                "success_rate": row[0] / total if total else 0.0,
                "last_attempt": row[5],
            }
        return None

    def get_prediction_accuracy(self, dim: str = "global",
                                value: str = "global") -> Dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT effort_err_pct, revenue_err_pct, success_correct "
            "FROM prediction_accuracy WHERE dim=? AND dim_value=?",
            (dim, value),
        ).fetchall()
        conn.close()
        n = len(rows)
        if n == 0:
            return {"sample_size": 0, "revenue_error_pct": 0.0,
                    "revenue_error": 0.0}
        return {
            "sample_size": n,
            "revenue_error_pct": sum(r[1] for r in rows) / n,
            "revenue_error": sum(r[1] for r in rows) / n,
        }

    def compute_all_metrics(self, dim: str = "category") -> List[Any]:
        col_map = {"category": "category", "platform": "platform",
                   "task_type": "task_type"}
        if dim not in col_map:
            return []
        conn = sqlite3.connect(self.db_path)
        vals = [r[0] for r in conn.execute(
            f"SELECT DISTINCT {col_map[dim]} FROM outcome_memory_v2 "
            f"WHERE {col_map[dim]} <> ''").fetchall()]
        results = []
        for v in vals:
            rows = conn.execute(
                "SELECT outcome_state, revenue, net_profit, effort_hours, "
                f"time_spent_hours, ts FROM outcome_memory_v2 "
                f"WHERE {col_map[dim]} = ?", (v,)).fetchall()
            n = len(rows)
            if n == 0:
                continue
            ACCEPTED = {"accepted", "completed", "submitted", "paid"}
            accepted = sum(1 for r in rows if r[0] in ACCEPTED)
            m = types.SimpleNamespace(
                value=v,
                sample_size=n,
                acceptance_rate=accepted / n,
                payment_rate=0.0,
                average_revenue=sum(r[1] or 0 for r in rows) / n,
                average_net_profit=sum(r[2] or 0 for r in rows) / n,
                average_effort_hours=sum(r[3] or 0 for r in rows) / n,
                average_hourly_return=(
                    sum(r[2] or 0 for r in rows) /
                    max(sum(r[4] or 0 for r in rows), 0.01)),
                expected_vs_actual_return=1.0,
                last_active=max((r[5] for r in rows if r[5]), default=0),
            )
            results.append(m)
        conn.close()
        return results

    def get_successful_patterns(self, pattern_type: str,
                                min_confidence: float = 0.0) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT pattern_value, success_count, total_attempts FROM "
            "pattern_memory WHERE pattern_type=? AND success_count > 0",
            (pattern_type,)
        ).fetchall()
        conn.close()
        return [
            {"pattern_value": r[0],
             "success_rate": r[1] / r[2] if r[2] else 0.0, "total": r[2]}
            for r in rows
        ]


class FakePortfolio:
    def __init__(self, entries=None):
        self._entries = entries or []

    def load_all(self):
        return self._entries


ALL_CATEGORIES = {cat.value for cat in AuditCategory}
# `agents/IMPROVEMENTS.md` does not exist on this tree (checked at fix time),
# so the documentation-drift audit is permanently source-gated.
DOCS_GATED_CATEGORIES = {"documentation_drift"}


def _make_db(db_path, platforms=None, strategies=None, outcomes=None,
             patterns=None, opportunity_ids=None):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reputation_memory (
            platform TEXT PRIMARY KEY,
            success_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            scam_count INTEGER DEFAULT 0,
            avg_revenue REAL DEFAULT 0,
            total_attempts INTEGER DEFAULT 0,
            last_attempt REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS prediction_accuracy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opportunity_id TEXT NOT NULL,
            dim TEXT NOT NULL,
            dim_value TEXT NOT NULL,
            effort_err_pct REAL DEFAULT 0,
            revenue_err_pct REAL DEFAULT 0,
            success_correct INTEGER DEFAULT 0,
            ts REAL
        );
        CREATE TABLE IF NOT EXISTS outcome_memory_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opportunity_id TEXT NOT NULL,
            outcome_state TEXT NOT NULL,
            platform TEXT, category TEXT, task_type TEXT,
            revenue REAL DEFAULT 0, cost REAL DEFAULT 0,
            net_profit REAL DEFAULT 0, effort_hours REAL DEFAULT 0,
            time_spent_hours REAL DEFAULT 0,
            ts REAL
        );
        CREATE TABLE IF NOT EXISTS search_strategy (
            strategy_id TEXT PRIMARY KEY,
            used_count INTEGER, result_count INTEGER,
            useful_result_count INTEGER, completed INTEGER,
            paid INTEGER, net_revenue REAL, duplicate_count INTEGER
        );
        CREATE TABLE IF NOT EXISTS pattern_memory (
            pattern_type TEXT, pattern_key TEXT, pattern_value TEXT,
            success_count INTEGER DEFAULT 0,
            total_attempts INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS opportunities (
            id TEXT PRIMARY KEY
        );
    """)
    for platform, data in (platforms or {}).items():
        conn.execute(
            "INSERT OR REPLACE INTO reputation_memory (platform, "
            "success_count, failed_count, total_attempts, last_attempt) "
            "VALUES (?, ?, ?, ?, ?)",
            (platform, data.get("success", 0), data.get("failed", 0),
             data.get("total", 0), data.get("last_attempt", time.time())),
        )
    for strat in (strategies or []):
        conn.execute(
            "INSERT OR REPLACE INTO search_strategy (strategy_id, used_count, "
            "result_count, useful_result_count, completed, paid, net_revenue, "
            "duplicate_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (strat["strategy_id"], strat.get("used_count", 0),
             strat.get("result_count", 0),
             strat.get("useful_result_count", 0),
             strat.get("completed", 0), strat.get("paid", 0),
             strat.get("net_revenue", 0.0),
             strat.get("duplicate_count", 0)),
        )
    for outcome in (outcomes or []):
        conn.execute(
            "INSERT INTO outcome_memory_v2 (opportunity_id, outcome_state, "
            "category, task_type, revenue, cost, net_profit, effort_hours, "
            "time_spent_hours, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (outcome["opportunity_id"], outcome["outcome_state"],
             outcome.get("category", ""), outcome.get("task_type", ""),
             outcome.get("revenue", 0), outcome.get("cost", 0),
             outcome.get("net_profit",
                         outcome.get("revenue", 0) - outcome.get("cost", 0)),
             outcome.get("effort_hours", 0),
             outcome.get("time_spent_hours", 0),
             outcome.get("ts", time.time())),
        )
    for pat in (patterns or []):
        conn.execute(
            "INSERT OR REPLACE INTO pattern_memory (pattern_type, "
            "pattern_value, pattern_key, success_count, total_attempts) "
            "VALUES (?, ?, ?, ?, ?)",
            (pat.get("pattern_type", "proposal_variant"),
             pat["pattern_value"], pat.get("pattern_key", ""),
             pat.get("success_count", 0), pat.get("total_attempts", 0)),
        )
    for oid in (opportunity_ids or []):
        conn.execute("INSERT OR REPLACE INTO opportunities (id) VALUES (?)", (oid,))
    conn.commit()
    conn.close()


def _stub_accounting():
    """WizardSleeve accounting: profiles exist and are all-pull hours-known."""
    def get_profile(opp_id):
        return types.SimpleNamespace(
            realized_expense=0.0, expected_value=1.0, expenses=[])
    return types.SimpleNamespace(get_profile=get_profile)


def _engine(db_path, portfolio=True, wallet=True, accounting=None, **kw):
    mem = FakeMemory(
        db_path,
        portfolio=FakePortfolio() if portfolio is True else portfolio,
        wallet_manager=(
            types.SimpleNamespace(failed_operations=[])
            if wallet is True else wallet),
    )
    return SelfAuditEngine(mem, accounting=accounting, **kw)


class TestAuditReportIsHonestAboutItsBasis(unittest.TestCase):
    """The ARCH-ENG-158 resting state must read as INSUFFICIENT DATA."""

    def test_empty_tables_never_claim_health(self):
        """Zero findings on empty outcome tables is 'insufficient', not clean."""
        db_path = os.path.join(tempfile.mkdtemp(), "empty.db")
        _make_db(db_path)
        report = _engine(db_path).run_audit()
        self.assertEqual(report.findings, [])
        self.assertFalse(
            report.data_complete,
            "every table-backed audit had zero rows; the report must not "
            "claim a complete basis")
        self.assertTrue(
            report.conclusion().startswith("INSUFFICIENT DATA"),
            f"conclusion was: {report.conclusion()!r}")
        d = report.to_dict()
        self.assertNotIn(
            "no problems found", d["conclusion"],
            "an empty audit trail must never be phrased as a clean bill")
        self.assertFalse(d["data_complete"])

    def test_every_source_backed_audit_declares_its_basis(self):
        """With the gated sources present, 13 of 14 categories publish basis.

        `documentation_drift` is source-gated on `agents/IMPROVEMENTS.md`,
        which does not exist on this tree -- its absence is recorded as
        insufficiency, never as "docs checked and clean".
        """
        db_path = os.path.join(tempfile.mkdtemp(), "declared.db")
        _make_db(db_path)
        report = _engine(db_path, accounting=_stub_accounting()).run_audit()
        missing = ALL_CATEGORIES - set(report.basis)
        self.assertEqual(
            missing, DOCS_GATED_CATEGORIES,
            f"{sorted(missing)} is source-gated by the missing IMPROVEMENTS.md, "
            "but every OTHER audit must declare a basis -- an audit without a "
            "declared basis is indistinguishable from silence")
        # The gated sources were injected, so these three are available even
        # on an empty database; basis 1 means "source available", not "rows".
        self.assertEqual(report.basis["human_intervention"], 1)
        self.assertEqual(report.basis["execution_failures"], 1)
        self.assertEqual(report.basis["security_problems"], 1)

    def test_missing_gated_source_is_recorded_not_assumed_clean(self):
        """A None portfolio / wallet makes those audits INSUFFICIENT."""
        db_path = os.path.join(tempfile.mkdtemp(), "nopf.db")
        _make_db(db_path)
        report = _engine(db_path, portfolio=None, wallet=None).run_audit()
        self.assertNotIn("human_intervention", report.basis)
        self.assertNotIn("execution_failures", report.basis)
        self.assertNotIn("security_problems", report.basis)
        self.assertIn("human_intervention", report.insufficient_audits)
        self.assertIn("execution_failures", report.insufficient_audits)
        self.assertIn("security_problems", report.insufficient_audits)

    def test_seeded_data_produces_findings_and_counts_the_basis(self):
        db_path = os.path.join(tempfile.mkdtemp(), "seeded.db")
        _make_db(
            db_path,
            platforms={"upwork": {"success": 0, "failed": 5, "total": 5}},
        )
        report = _engine(db_path).run_audit()
        cats = {f.category for f in report.findings}
        self.assertIn(AuditCategory.REPEATED_FAILURES, cats)
        self.assertGreater(report.basis["repeated_failures"], 0)

    def test_engine_error_is_recorded_not_silent(self):
        """An audit that raises is an error on the report, not clean silence."""
        db_path = os.path.join(tempfile.mkdtemp(), "boom.db")
        _make_db(db_path)
        engine = _engine(db_path)
        engine.memory.get_prediction_accuracy = None  # attribute call raises
        report = engine.run_audit()
        self.assertTrue(
            any(err.startswith("prediction_errors")
                for err in report.audit_errors),
            f"audit_errors was {report.audit_errors!r}")
        self.assertTrue(
            report.conclusion().startswith("audit errors"),
            f"conclusion was: {report.conclusion()!r}")

    def test_full_data_still_cannot_claim_health_while_one_audit_is_starved(self):
        """Populate every table-backed audit; the missing docs file STILL
        keeps the honest conclusion -- and that is the point (AJ-02)."""
        db_path = os.path.join(tempfile.mkdtemp(), "full.db")
        _make_db(
            db_path,
            platforms={"upwork": {"success": 4, "failed": 1, "total": 5}},
            strategies=[{"strategy_id": "s1", "used_count": 5,
                         "result_count": 4, "useful_result_count": 3,
                         "completed": 2, "paid": 1, "net_revenue": 40.0,
                         "duplicate_count": 0}],
            outcomes=[{"opportunity_id": f"o{i}", "outcome_state": "paid",
                       "category": "crypto", "task_type": "research",
                       "revenue": 10.0, "cost": 1.0, "effort_hours": 1.0}
                      for i in range(4)],
            patterns=[{"pattern_value": "polite", "success_count": 6,
                       "total_attempts": 8}],
            opportunity_ids=["o0"],
        )
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO prediction_accuracy (opportunity_id, dim, dim_value, "
            "revenue_err_pct) VALUES ('o0','global','global',0.1)")
        conn.commit()
        conn.close()
        report = _engine(db_path, accounting=_stub_accounting()).run_audit()
        # Every audit that CAN see data did see it: bases > 0 across the other
        # categories, zero runtime errors.
        self.assertEqual(report.audit_errors, [])
        self.assertFalse(
            report.data_complete,
            "the docs file is absent -- claiming complete coverage would be "
            "exactly the inversion AJ-02 forbids")
        self.assertEqual(
            report.insufficient_audits, sorted(DOCS_GATED_CATEGORIES),
            f"only the docs-gated audit may be starved; got "
            f"{report.insufficient_audits}")
        self.assertEqual(report.findings, [])
        self.assertTrue(
            report.conclusion().startswith("INSUFFICIENT DATA"),
            f"conclusion was: {report.conclusion()!r}")


class TestSelfAuditActuallyRuns(unittest.TestCase):
    """AJ-01: run_full_cycle is live from main.py, so the hook is live too."""

    def _pipeline(self):
        tmp = tempfile.mkdtemp()
        log_lines: List[str] = []
        pipeline = EarningPipeline(
            db_path=os.path.join(tmp, "ep.db"),
            memory_path=os.path.join(tmp, "mem.db"),
            log_fn=log_lines.append,
        )
        # Keep the integration test offline: an empty sources list would
        # otherwise mean "all nine discovery sources" (network) -- replace the
        # SCAN service only; run_full_cycle's own wiring is what is under test.
        pipeline.discovery_service = types.SimpleNamespace(
            discover=lambda **kwargs: [], last_stats=None)
        self.addCleanup(pipeline.close)
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        return pipeline, log_lines

    def test_run_full_cycle_logs_the_audit_conclusion(self):
        """The missing last hop: the cycle reaches the engine every time."""
        pipeline, log_lines = self._pipeline()
        pipeline.run_full_cycle(sources=[])
        audit_lines = [l for l in log_lines if l.startswith("[SelfAudit]")]
        self.assertTrue(
            audit_lines,
            "run_full_cycle never reached run_audit() -- AJ-01 unchanged")
        # Empty new pipeline: the resting state must be honest insufficiency,
        # never "no problems found".
        self.assertNotIn(
            "no problems found", "".join(audit_lines),
            "an empty-table audit must never read as a clean bill (AJ-02)")

    def test_run_self_audit_returns_the_report(self):
        pipeline, _ = self._pipeline()
        report = pipeline.run_self_audit()
        self.assertIsNotNone(report)
        self.assertIn(
            "INSUFFICIENT DATA", report.conclusion(),
            "fresh pipeline, outcome tables empty by ARCH-ENG-158 design")


if __name__ == "__main__":
    unittest.main()
