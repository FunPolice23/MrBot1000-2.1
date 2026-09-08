"""tests/test_search_strategy_memory.py — Search Strategy Memory (v2.0.36g).

Covers the user's required behavior:
- tracks query, normalized_query, platform, category, task_type, source, result_count,
  useful_result_count, duplicate rate, acceptance/completion/payment rates, net revenue,
  avg effort, timestamp, search strategy identifier.
- learns that semantically related searches can have very DIFFERENT economic outcomes
  (the 3 example strategies).
- does NOT optimize for number of results: a high-volume/useless strategy ranks below a
  low-volume/profitable one.
- optimizes for useful, legitimate, profitable opportunities (composite usefulness reward;
  duplicates penalized).
- exploration preserved: novel searches are NOT permanently suppressed (cold-start neutral
  prior; explore_search_strategies() surfaces them).
- search-strategy outcomes are recorded and available to the discovery scheduler
  (get_successful_search_terms / explore_search_strategies / top_search_strategies(by=usefulness)).
"""

import os
import tempfile
import unittest
from typing import Dict

from earning_memory import EarningMemory


def _run(m: EarningMemory, sid, origin, q, src, plat, catt, tt, res):
    """Simulate 3 discovery runs so strategies exit cold-start (used_count >= MIN_SAMPLES)."""
    for _ in range(3):
        m.record_search_strategy(sid, origin, q, [catt], src, platform=plat,
                                 category=catt, task_type=tt)
    m.record_strategy_result(sid, **res)


class TestSchemaAndTracking(unittest.TestCase):
    def setUp(self):
        self.m = EarningMemory(db_path=os.path.join(tempfile.mkdtemp(), "ss.db"))

    def test_all_tracked_fields(self):
        self.m.record_search_strategy("A", "HISTORICAL_CATEGORY", "Python automation freelance",
                                      ["coding"], "upwork", platform="upwork", category="coding",
                                      task_type="automation")
        self.m.record_strategy_result("A", result_count=10, useful_result_count=4,
                                      duplicate_count=2, accepted=3, completed=2, paid=2,
                                      net_revenue=120.0, effort_hours=5.0)
        s = self.m.get_search_strategy_stats("A")
        self.assertEqual(s["query"], "Python automation freelance")
        self.assertEqual(s["normalized_query"], "python automation")  # stopwords stripped
        self.assertEqual(s["platform"], "upwork")
        self.assertEqual(s["category"], "coding")
        self.assertEqual(s["task_type"], "automation")
        self.assertEqual(s["source"], "upwork")
        self.assertEqual(s["result_count"], 10)
        self.assertEqual(s["useful_result_count"], 4)
        self.assertEqual(s["duplicate_count"], 2)
        self.assertEqual(s["accepted"], 3)
        self.assertEqual(s["completed"], 2)
        self.assertEqual(s["paid"], 2)
        self.assertAlmostEqual(s["net_revenue"], 120.0)
        self.assertAlmostEqual(s["avg_effort"], 2.5)  # 5.0 / 2 completed
        self.assertAlmostEqual(s["duplicate_rate"], 0.2)
        self.assertAlmostEqual(s["acceptance_rate"], 0.3)
        self.assertAlmostEqual(s["completion_rate"], 0.2)
        self.assertAlmostEqual(s["payment_rate"], 1.0)  # paid/completed = 2/2
        self.assertGreater(s["last_used"], 0.0)


class TestSemanticallyRelatedDifferentOutcomes(unittest.TestCase):
    def setUp(self):
        self.m = EarningMemory(db_path=os.path.join(tempfile.mkdtemp(), "ss.db"))

    def test_three_example_strategies(self):
        # Strategy A: high volume, almost no useful, many duplicates.
        _run(self.m, "A", "PAST_SUCCESS_TERM", "Python automation freelance", "upwork", "upwork",
             "coding", "automation",
             dict(result_count=50, useful_result_count=1, duplicate_count=40,
                   accepted=0, completed=0, paid=0, net_revenue=0.0))
        # Strategy B: few results but useful + paid.
        _run(self.m, "B", "EXPLORATION", "Python data cleanup paid task", "upwork", "upwork",
             "data", "cleanup",
             dict(result_count=5, useful_result_count=4, duplicate_count=0,
                   accepted=3, completed=2, paid=2, net_revenue=200.0, effort_hours=4.0))
        # Strategy C: profitable contract work.
        _run(self.m, "C", "HISTORICAL_CATEGORY", "CSV data processing contract", "upwork", "upwork",
             "data", "processing",
             dict(result_count=8, useful_result_count=6, duplicate_count=0,
                   accepted=4, completed=3, paid=3, net_revenue=320.0, effort_hours=6.0))

        sA = self.m.get_search_strategy_stats("A")
        sB = self.m.get_search_strategy_stats("B")
        sC = self.m.get_search_strategy_stats("C")
        # A has the MOST results but the LEAST usefulness (penalized for dup + no profit).
        self.assertGreater(sA["result_count"], sB["result_count"])
        self.assertLess(sA["usefulness"], sB["usefulness"])
        self.assertLess(sA["usefulness"], sC["usefulness"])
        # B and C (profitable) outrank A despite A's larger volume.
        top = self.m.top_search_strategies(5)
        ids = [t["strategy_id"] for t in top]
        self.assertIn("A", ids)
        # A must NOT be the top strategy (volume != usefulness).
        self.assertNotEqual(ids[0], "A")


class TestNotOptimizingForVolume(unittest.TestCase):
    def setUp(self):
        self.m = EarningMemory(db_path=os.path.join(tempfile.mkdtemp(), "ss.db"))

    def test_volume_useless_ranks_below_low_volume_profitable(self):
        _run(self.m, "BIG", "EXPLORATION", "free stuff list", "web", "web", "other", "misc",
             dict(result_count=100, useful_result_count=0, duplicate_count=90,
                   accepted=0, completed=0, paid=0, net_revenue=0.0))
        _run(self.m, "SMALL", "HISTORICAL_CATEGORY", "python api integration contract", "upwork",
             "upwork", "coding", "integration",
             dict(result_count=3, useful_result_count=3, accepted=2, completed=2, paid=2,
                   net_revenue=400.0, effort_hours=3.0))
        top = self.m.top_search_strategies(5)
        ids = [t["strategy_id"] for t in top]
        self.assertEqual(ids[0], "SMALL")
        self.assertLess(ids.index("BIG"), len(ids))  # present but not first


class TestExplorationPreserved(unittest.TestCase):
    def setUp(self):
        self.m = EarningMemory(db_path=os.path.join(tempfile.mkdtemp(), "ss.db"))

    def test_novel_strategy_not_suppressed(self):
        # A novel strategy recorded once should get a neutral prior (not negative).
        self.m.record_search_strategy("NOVEL", "EXPLORATION", "novel ai labeling gig", ["ai"],
                                      "web", platform="web", category="ai")
        s = self.m.get_search_strategy_stats("NOVEL")
        self.assertTrue(s["cold_start"])
        self.assertEqual(s["usefulness"], 0.5)  # neutral prior, not suppressed
        # explore_search_strategies surfaces it for the scheduler.
        exp = self.m.explore_search_strategies(10)
        self.assertTrue(any(t["strategy_id"] == "NOVEL" for t in exp))

    def test_failed_terms_require_min_samples_cold_start_safe(self):
        # A novel (low-sample) strategy with 0 useful is NOT flagged as 'failed'
        # (so it keeps getting a chance).
        self.m.record_search_strategy("NEW1", "EMERGING", "experimental search", ["x"], "web")
        self.assertEqual(self.m.get_failed_search_terms(10), [])
        # A well-sampled strategy with 0 useful IS flagged as failed.
        for _ in range(3):
            self.m.record_search_strategy("OLD0", "EMERGING", "dead end query", ["x"], "web")
        self.m.record_strategy_result("OLD0",
            result_count=20, useful_result_count=0, duplicate_count=5)
        self.assertIn("dead end query", self.m.get_failed_search_terms(10))


class TestSchedulerAvailability(unittest.TestCase):
    def setUp(self):
        self.m = EarningMemory(db_path=os.path.join(tempfile.mkdtemp(), "ss.db"))

    def test_successful_terms_ranked_by_usefulness(self):
        _run(self.m, "A", "HISTORICAL_CATEGORY", "big but useless query", "web", "web", "other",
             "misc", dict(result_count=80, useful_result_count=1, net_revenue=0.0))
        _run(self.m, "B", "HISTORICAL_CATEGORY", "small profitable query", "upwork", "upwork",
             "coding", "dev", dict(result_count=4, useful_result_count=4, accepted=3,
             completed=3, paid=3, net_revenue=300.0))
        terms = self.m.get_successful_search_terms(5)
        # The profitable one ranks first even though A has far more results.
        self.assertEqual(terms[0], "small profitable query")

    def test_top_by_usefulness_default(self):
        _run(self.m, "A", "EXPLORATION", "alpha", "web", "web", "other", "misc",
             dict(result_count=10, useful_result_count=2, net_revenue=10.0))
        _run(self.m, "B", "EXPLORATION", "beta", "web", "web", "other", "misc",
             dict(result_count=10, useful_result_count=9, accepted=5, completed=5, paid=5,
                   net_revenue=500.0))
        top = self.m.top_search_strategies(5, by="usefulness")
        self.assertEqual(top[0]["strategy_id"], "B")

    def test_normalize_groups_related_queries(self):
        from earning_memory import _normalize_query
        self.assertEqual(_normalize_query("Python   automation freelance!!"),
                         "python automation")
        self.assertEqual(_normalize_query("CSV Data Processing Contract"),
                         "csv data processing contract")


class TestMigration(unittest.TestCase):
    def test_old_schema_gets_new_columns(self):
        # Simulate a pre-v2.0.36g DB (only old columns) and ensure it migrates cleanly.
        import sqlite3
        db = os.path.join(tempfile.mkdtemp(), "old.db")
        c = sqlite3.connect(db)
        c.executescript(
            "CREATE TABLE search_strategy (strategy_id TEXT PRIMARY KEY, origin TEXT, "
            "query TEXT, categories TEXT, source TEXT, used_count INTEGER DEFAULT 0, "
            "success_count INTEGER DEFAULT 0, reward_sum REAL DEFAULT 0, last_used REAL, "
            "created_at REAL);")
        c.commit(); c.close()
        m = EarningMemory(db_path=db)
        m.record_search_strategy("X", "SKILL", "python", ["coding"], "web",
                                 platform="web", category="coding")
        m.record_strategy_result("X", result_count=3, useful_result_count=2, paid=1,
                                 net_revenue=90.0)
        s = m.get_search_strategy_stats("X")
        self.assertEqual(s["query"], "python")
        self.assertEqual(s["useful_result_count"], 2)
        self.assertEqual(s["paid"], 1)
        self.assertGreater(s["usefulness"], 0.0)


if __name__ == "__main__":
    unittest.main()
