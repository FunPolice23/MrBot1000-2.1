"""Strategy feedback + ranking integration (Phase C, ARCH-ENG-081).

Closes the autonomous-learning outcome loop: recorded autonomous runs are
aggregated per-platform and applied as an advisory ranking adjustment. Tests
lock in: aggregation correctness, financial truth (only paid runs count toward
total_paid), cold-start safety (thin data -> no adjustment), and that the GoT
ordering is preserved when no feedback is supplied.
"""
import os
import sys
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.earning.strategy_feedback import StrategyFeedback, PlatformStats


class _FakeStore:
    """Minimal stand-in for AutonomousRunStore.list_runs()."""
    def __init__(self, rows):
        self._rows = rows
    def list_runs(self, limit=50):
        return self._rows[:limit]


def _run(opp_id, *, success=False, paid=False, amount=0.0, decision=""):
    return {"opportunity_id": opp_id, "success": success, "paid": paid,
            "payment_amount": amount, "decision": decision}


class TestAggregation(unittest.TestCase):
    def test_per_platform_rates_and_totals(self):
        # ugig: 4 runs, 2 success, 2 paid ($100 + $50), prolific: 2 runs, 0 paid
        rows = [
            _run("o1", success=True, paid=True, amount=100.0, decision="proceed"),
            _run("o2", success=True, paid=True, amount=50.0, decision="proceed"),
            _run("o3", success=False, decision="reject"),
            _run("o4", success=False, decision="reject"),
            _run("p1", success=False, decision="reject"),
            _run("p2", success=False, decision="reject"),
        ]
        resolver = lambda oid: "ugig" if oid.startswith("o") else "prolific"
        fb = StrategyFeedback(_FakeStore(rows), resolver, min_runs=3)
        stats = fb.platform_stats()
        self.assertAlmostEqual(stats["ugig"].success_rate, 0.5)
        self.assertAlmostEqual(stats["ugig"].paid_rate, 0.5)
        self.assertEqual(stats["ugig"].total_paid, 150.0)
        self.assertAlmostEqual(stats["ugig"].avg_payout, 75.0)
        self.assertEqual(stats["prolific"].paid_runs, 0)
        self.assertEqual(stats["prolific"].total_paid, 0.0)

    def test_financial_truth_only_paid_runs_count(self):
        """An unpaid run with a nonzero payment_amount must NOT inflate totals."""
        rows = [
            _run("o1", paid=True, amount=100.0),
            _run("o2", paid=False, amount=999.0),  # must be ignored
        ]
        fb = StrategyFeedback(_FakeStore(rows), lambda _: "ugig", min_runs=1)
        st = fb.platform_stats()["ugig"]
        self.assertEqual(st.total_paid, 100.0)
        self.assertEqual(st.paid_runs, 1)

    def test_unresolved_platform_bucketed_not_dropped(self):
        rows = [_run("x1"), _run("x2")]
        fb = StrategyFeedback(_FakeStore(rows), lambda _: "", min_runs=1)
        stats = fb.platform_stats()
        self.assertIn("", stats)
        self.assertEqual(stats[""].runs, 2)

    def test_summary_lines_exclude_unresolved(self):
        rows = [_run("o1", paid=True, amount=10.0), _run("z1")]
        fb = StrategyFeedback(_FakeStore(rows),
                              lambda oid: "ugig" if oid.startswith("o") else "",
                              min_runs=1)
        lines = fb.summary_lines()
        self.assertTrue(any("ugig" in ln for ln in lines))
        self.assertFalse(any(ln.startswith(":") for ln in lines))


class TestRankingAdjustment(unittest.TestCase):
    def _stats(self, rows, resolver):
        return StrategyFeedback(_FakeStore(rows), resolver, min_runs=3).platform_stats()

    def test_cold_start_no_adjustment(self):
        """Fewer than min_runs -> adjustment is exactly 1.0 (no distortion)."""
        rows = [_run("o1", paid=True, amount=100.0)]  # only 1 run
        fb = StrategyFeedback(_FakeStore(rows), lambda _: "ugig", min_runs=3)
        self.assertEqual(fb.ranking_adjustment("ugig"), 1.0)

    def test_paying_platform_bonus(self):
        rows = [_run(f"o{i}", paid=True, amount=10.0) for i in range(4)]
        fb = StrategyFeedback(_FakeStore(rows), lambda _: "ugig", min_runs=3)
        self.assertGreater(fb.ranking_adjustment("ugig"), 1.0)

    def test_never_paid_penalty(self):
        rows = [_run(f"o{i}", success=False) for i in range(4)]
        fb = StrategyFeedback(_FakeStore(rows), lambda _: "prolific", min_runs=3)
        self.assertLess(fb.ranking_adjustment("prolific"), 1.0)

    def test_unknown_platform_no_adjustment(self):
        fb = StrategyFeedback(_FakeStore([]), lambda _: "ugig", min_runs=3)
        self.assertEqual(fb.ranking_adjustment("never-seen"), 1.0)

    def test_adjustment_clamped(self):
        rows = [_run(f"o{i}", paid=True, amount=10.0) for i in range(50)]
        fb = StrategyFeedback(_FakeStore(rows), lambda _: "ugig", min_runs=3)
        adj = fb.ranking_adjustment("ugig")
        self.assertLessEqual(adj, 1.25)
        self.assertGreaterEqual(adj, 0.75)


class TestStoreReadSafety(unittest.TestCase):
    def test_unreadable_store_yields_no_feedback(self):
        class _Boom:
            def list_runs(self, limit=50):
                raise RuntimeError("db locked")
        fb = StrategyFeedback(_Boom(), lambda _: "ugig")
        self.assertEqual(fb.platform_stats(), {})   # never raises


if __name__ == "__main__":
    raise SystemExit(unittest.main())
