"""tests/test_self_audit.py — Self-Audit & Continuous-Improvement Layer (v2.0.36j-T4)."""

import os
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional

from agents.self_audit import (
    AuditCategory, Severity, AuditFinding, AuditReport, SelfAuditEngine,
)


class FakeMemory:
    """Memory backed by a real temp SQLite DB so audit queries work."""
    def __init__(self, db_path: str, portfolio=None, wallet_manager=None):
        self.db_path = db_path
        self.portfolio = portfolio
        self.wallet_manager = wallet_manager

    def get_platform_reputation(self, platform: str) -> Optional[Dict]:
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT success_count, failed_count, scam_count, avg_revenue, total_attempts, last_attempt "
            "FROM reputation_memory WHERE platform=?",
            (platform,)
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

    def get_prediction_accuracy(self, dim: str = "global", value: str = "global") -> Dict:
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT effort_err_pct, revenue_err_pct, success_correct "
            "FROM prediction_accuracy WHERE dim=? AND dim_value=?",
            (dim, value),
        ).fetchall()
        conn.close()
        n = len(rows)
        if n == 0:
            return {"sample_size": 0, "revenue_error_pct": 0.0, "revenue_error": 0.0}
        return {
            "sample_size": n,
            "revenue_error_pct": sum(r[1] for r in rows) / n,
            "revenue_error": sum(r[1] for r in rows) / n,
        }

    def compute_all_metrics(self, dim: str = "category") -> List[Any]:
        """Compute simple metrics directly from outcome_memory_v2."""
        import sqlite3
        col_map = {"category": "category", "platform": "platform", "task_type": "task_type"}
        if dim not in col_map:
            return []
        conn = sqlite3.connect(self.db_path)
        vals = [r[0] for r in conn.execute(
            f"SELECT DISTINCT {col_map[dim]} FROM outcome_memory_v2 WHERE {col_map[dim]} <> ''"
        ).fetchall()]

        results = []
        for v in vals:
            rows = conn.execute(
                f"SELECT outcome_state, revenue, net_profit, effort_hours, time_spent_hours, ts "
                f"FROM outcome_memory_v2 WHERE {col_map[dim]} = ?",
                (v,)
            ).fetchall()
            n = len(rows)
            if n == 0:
                continue
            ACCEPTED = {"accepted", "completed", "submitted", "paid"}
            PAID = {"paid"}
            accepted = sum(1 for r in rows if r[0] in ACCEPTED)
            paid = sum(1 for r in rows if r[0] in PAID)
            total_rev = sum(r[1] or 0 for r in rows)
            total_net = sum(r[2] or 0 for r in rows)
            total_eff = sum(r[3] or 0 for r in rows)
            total_time = sum(r[4] or 0 for r in rows)
            last_active = max((r[5] for r in rows if r[5]), default=0)

            # Simple mock metric object
            m = type("M", (), {
                "value": v,
                "sample_size": n,
                "acceptance_rate": accepted / n,
                "payment_rate": paid / n,
                "average_revenue": total_rev / n,
                "average_net_profit": total_net / n,
                "average_effort_hours": total_eff / n,
                "average_hourly_return": total_net / total_time if total_time > 0 else 0.0,
                "expected_vs_actual_return": 1.0,
                "last_active": last_active,
            })()
            results.append(m)
        conn.close()
        return results

    def get_successful_patterns(self, pattern_type: str, min_confidence: float = 0.0) -> List[Dict]:
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT pattern_value, success_count, total_attempts FROM pattern_memory "
            "WHERE pattern_type=? AND success_count > 0",
            (pattern_type,)
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            total = r[2] if r[2] else 0
            rate = r[1] / total if total > 0 else 0.0
            result.append({"pattern_value": r[0], "success_rate": rate, "total": total})
        return result


class FakePortfolio:
    def __init__(self, entries=None):
        self._entries = entries or []

    def load_all(self):
        return self._entries


class FakeEntry:
    def __init__(self, opportunity_id, work_status_val):
        self.opportunity_id = opportunity_id
        self.work_status = type("WS", (), {"value": work_status_val})()


def _make_db(db_path, platforms=None, strategies=None, outcomes=None):
    """Create a minimal DB with required tables and optional data."""
    import sqlite3
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
            predicted_effort REAL DEFAULT 0,
            actual_effort REAL DEFAULT 0,
            predicted_revenue REAL DEFAULT 0,
            actual_revenue REAL DEFAULT 0,
            predicted_success_prob REAL DEFAULT 0,
            actual_success INTEGER DEFAULT 0,
            effort_err_pct REAL DEFAULT 0,
            revenue_err_pct REAL DEFAULT 0,
            success_correct INTEGER DEFAULT 0,
            ts REAL
        );
        CREATE TABLE IF NOT EXISTS outcome_memory_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opportunity_id TEXT NOT NULL,
            outcome_state TEXT NOT NULL,
            platform TEXT,
            category TEXT,
            task_type TEXT,
            revenue REAL DEFAULT 0,
            cost REAL DEFAULT 0,
            net_profit REAL DEFAULT 0,
            effort_hours REAL DEFAULT 0,
            time_spent_hours REAL DEFAULT 0,
            strategy_used TEXT,
            proposal_variant TEXT,
            model_used TEXT,
            human_intervention BOOLEAN DEFAULT 0,
            automation_level REAL DEFAULT 0,
            reason TEXT,
            evidence TEXT,
            failure_cause TEXT,
            success_cause TEXT,
            disputed BOOLEAN DEFAULT 0,
            ts REAL
        );
        CREATE TABLE IF NOT EXISTS search_strategy (
            strategy_id TEXT PRIMARY KEY,
            origin TEXT, query TEXT, normalized_query TEXT,
            platform TEXT, category TEXT, task_type TEXT, source TEXT,
            used_count INTEGER, result_count INTEGER, useful_result_count INTEGER,
            duplicate_count INTEGER, accepted INTEGER, completed INTEGER,
            paid INTEGER, net_revenue REAL, effort_sum REAL, reward_sum REAL,
            last_used REAL, created_at REAL
        );
        CREATE TABLE IF NOT EXISTS pattern_memory (
            pattern_type TEXT,
            pattern_key TEXT,
            pattern_value TEXT,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            total_attempts INTEGER DEFAULT 0,
            success_cause TEXT,
            failure_cause TEXT,
            confidence REAL DEFAULT 0,
            last_seen REAL
        );
    """)
    for platform, data in (platforms or {}).items():
        conn.execute(
            "INSERT OR REPLACE INTO reputation_memory (platform, success_count, failed_count, total_attempts, last_attempt) VALUES (?, ?, ?, ?, ?)",
            (platform, data.get("success", 0), data.get("failed", 0), data.get("total", 0), data.get("last_attempt", time.time())),
        )
    for strat in (strategies or []):
        conn.execute(
            "INSERT OR REPLACE INTO search_strategy (strategy_id, used_count, result_count, useful_result_count, completed, paid, net_revenue, duplicate_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (strat["strategy_id"], strat.get("used_count", 0), strat.get("result_count", 0),
             strat.get("useful_result_count", 0), strat.get("completed", 0), strat.get("paid", 0),
             strat.get("net_revenue", 0.0), strat.get("duplicate_count", 0)),
        )
    for outcome in (outcomes or []):
        conn.execute(
            "INSERT INTO outcome_memory_v2 (opportunity_id, outcome_state, category, task_type, revenue, cost, effort_hours, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (outcome["opportunity_id"], outcome["outcome_state"], outcome.get("category", ""),
             outcome.get("task_type", ""), outcome.get("revenue", 0), outcome.get("cost", 0),
             outcome.get("effort_hours", 0), outcome.get("ts", time.time())),
        )
    conn.commit()
    conn.close()


class TestSelfAuditEngine(unittest.TestCase):

    def test_no_findings_on_empty_memory(self):
        """Empty memory should produce no findings."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path)
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        self.assertEqual(len(report.findings), 0)

    def test_detects_poor_platform(self):
        """Platform with 0% acceptance should be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path, platforms={"BadPlatform": {"success": 0, "failed": 10, "total": 10}})
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        poor = report.by_category(AuditCategory.POOR_PLATFORMS)
        self.assertGreater(len(poor), 0)
        self.assertIn("BadPlatform", poor[0].observation)

    def test_detects_repeated_failures(self):
        """Platform with >= 70% failure rate should be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path, platforms={"FailPlatform": {"success": 1, "failed": 9, "total": 10}})
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        failures = report.by_category(AuditCategory.REPEATED_FAILURES)
        self.assertGreater(len(failures), 0)

    def test_detects_prediction_error(self):
        """Large revenue prediction error should be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path)
        import sqlite3
        conn = sqlite3.connect(db_path)
        for i in range(3):
            conn.execute(
                "INSERT INTO prediction_accuracy (opportunity_id, dim, dim_value, effort_err_pct, revenue_err_pct, success_correct) VALUES (?, ?, ?, ?, ?, ?)",
                (f"pred-{i}", "global", "global", 0.3, 0.8, 1),
            )
        conn.commit()
        conn.close()
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        pred = report.by_category(AuditCategory.PREDICTION_ERRORS)
        self.assertGreater(len(pred), 0)

    def test_detects_bad_strategy(self):
        """Strategy with usefulness < 0.2 should be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path, strategies=[
            {"strategy_id": "bad-strat", "used_count": 5, "result_count": 50,
             "useful_result_count": 2, "completed": 1, "paid": 0, "net_revenue": 0.0, "duplicate_count": 10},
        ])
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        bad = report.by_category(AuditCategory.BAD_STRATEGIES)
        self.assertGreater(len(bad), 0)
        self.assertIn("bad-strat", bad[0].observation)

    def test_detects_poor_category(self):
        """Category with < 10% acceptance should be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path, outcomes=[
            {"opportunity_id": "o1", "outcome_state": "rejected", "category": "BadCat", "ts": time.time()},
            {"opportunity_id": "o2", "outcome_state": "rejected", "category": "BadCat", "ts": time.time()},
            {"opportunity_id": "o3", "outcome_state": "rejected", "category": "BadCat", "ts": time.time()},
            {"opportunity_id": "o4", "outcome_state": "rejected", "category": "BadCat", "ts": time.time()},
            {"opportunity_id": "o5", "outcome_state": "rejected", "category": "BadCat", "ts": time.time()},
        ])
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        poor = report.by_category(AuditCategory.POOR_CATEGORIES)
        self.assertGreater(len(poor), 0)

    def test_detects_poor_task_type(self):
        """Task type with good acceptance but poor hourly return should be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path, outcomes=[
            {"opportunity_id": "o1", "outcome_state": "paid", "task_type": "BadTask", "revenue": 10, "cost": 2, "effort_hours": 5, "ts": time.time()},
            {"opportunity_id": "o2", "outcome_state": "paid", "task_type": "BadTask", "revenue": 15, "cost": 2, "effort_hours": 6, "ts": time.time()},
            {"opportunity_id": "o3", "outcome_state": "paid", "task_type": "BadTask", "revenue": 12, "cost": 2, "effort_hours": 4, "ts": time.time()},
            {"opportunity_id": "o4", "outcome_state": "paid", "task_type": "BadTask", "revenue": 8, "cost": 2, "effort_hours": 5, "ts": time.time()},
            {"opportunity_id": "o5", "outcome_state": "rejected", "task_type": "BadTask", "ts": time.time()},
        ])
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        poor = report.by_category(AuditCategory.POOR_TASK_TYPES)
        self.assertGreater(len(poor), 0)

    def test_detects_low_performing_variant(self):
        """Proposal variant with < 15% acceptance should be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path)
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO pattern_memory (pattern_type, pattern_value, success_count, total_attempts) VALUES (?, ?, ?, ?)",
            ("proposal_variant", "variantA", 1, 10),
        )
        conn.commit()
        conn.close()
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        low = report.by_category(AuditCategory.LOW_PERFORMING_VARIANTS)
        self.assertGreater(len(low), 0)

    def test_detects_human_intervention(self):
        """High rate of AWAITING_APPROVAL should be flagged."""
        entries = [FakeEntry(f"opp-{i}", "awaiting_approval") for i in range(5)]
        entries += [FakeEntry(f"opp-{i+5}", "in_progress") for i in range(2)]
        portfolio = FakePortfolio(entries)
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path)
        mem = FakeMemory(db_path=db_path, portfolio=portfolio)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        human = report.by_category(AuditCategory.HUMAN_INTERVENTION)
        self.assertGreater(len(human), 0)

    def test_detects_execution_failures(self):
        """Blocked/failed entries should be flagged."""
        entries = [
            FakeEntry("opp-1", "blocked"),
            FakeEntry("opp-2", "failed"),
            FakeEntry("opp-3", "rejected"),
        ]
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path)
        mem = FakeMemory(db_path=db_path, portfolio=FakePortfolio(entries))
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        fail = report.by_category(AuditCategory.EXECUTION_FAILURES)
        self.assertGreater(len(fail), 0)

    def test_detects_stale_providers(self):
        """Provider with no activity in 60 days should be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path, platforms={
            "StalePlatform": {"success": 1, "failed": 0, "total": 1, "last_attempt": time.time() - (60 * 86400)}
        })
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem, config={"stale_days": 30})
        report = engine.run_audit()
        stale = report.by_category(AuditCategory.STALE_PROVIDERS)
        self.assertGreater(len(stale), 0)

    def test_detects_stale_categories(self):
        """Category with no recent activity should be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path, outcomes=[
            {"opportunity_id": f"o{i}", "outcome_state": "paid", "category": "StaleCat",
             "revenue": 100, "cost": 0, "effort_hours": 2, "ts": time.time() - (60 * 86400)}
            for i in range(5)
        ])
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem, config={"stale_days": 30})
        report = engine.run_audit()
        stale = report.by_category(AuditCategory.STALE_CATEGORIES)
        self.assertGreater(len(stale), 0)

    def test_detects_security_problems(self):
        """Wallet validation failures should be flagged."""
        class FakeWallet:
            failed_operations = [{"description": "Invalid signature"}]
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path)
        mem = FakeMemory(db_path=db_path, wallet_manager=FakeWallet())
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        sec = report.by_category(AuditCategory.SECURITY_PROBLEMS)
        self.assertGreater(len(sec), 0)

    def test_no_findings_below_threshold(self):
        """Platforms with acceptable performance should not be flagged."""
        db_path = os.path.join(tempfile.mkdtemp(), "test.db")
        _make_db(db_path, platforms={"GoodPlatform": {"success": 8, "failed": 2, "total": 10}})
        mem = FakeMemory(db_path=db_path)
        engine = SelfAuditEngine(mem)
        report = engine.run_audit()
        self.assertEqual(len(report.by_category(AuditCategory.POOR_PLATFORMS)), 0)
        self.assertEqual(len(report.by_category(AuditCategory.REPEATED_FAILURES)), 0)


class TestAuditReport(unittest.TestCase):
    def test_to_dict(self):
        finding = AuditFinding(
            category=AuditCategory.POOR_PLATFORMS, severity=Severity.HIGH,
            observation="test", evidence={"a": 1}, confidence=0.8,
            recommended_change="change", expected_benefit="benefit", expected_risk="risk",
            affected_components=["comp"], test_requirements=["test"],
        )
        report = AuditReport(findings=[finding])
        d = report.to_dict()
        self.assertEqual(d["total_findings"], 1)
        self.assertEqual(d["high_count"], 1)

    def test_by_category(self):
        f1 = AuditFinding(category=AuditCategory.POOR_PLATFORMS, severity=Severity.HIGH,
                          observation="a", evidence={}, confidence=0.5,
                          recommended_change="c", expected_benefit="b", expected_risk="r",
                          affected_components=[], test_requirements=[])
        f2 = AuditFinding(category=AuditCategory.BAD_STRATEGIES, severity=Severity.MEDIUM,
                          observation="b", evidence={}, confidence=0.5,
                          recommended_change="c", expected_benefit="b", expected_risk="r",
                          affected_components=[], test_requirements=[])
        report = AuditReport(findings=[f1, f2])
        self.assertEqual(len(report.by_category(AuditCategory.POOR_PLATFORMS)), 1)
        self.assertEqual(len(report.by_category(AuditCategory.BAD_STRATEGIES)), 1)


if __name__ == "__main__":
    unittest.main()
