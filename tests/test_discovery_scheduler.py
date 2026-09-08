"""tests/test_discovery_scheduler.py — Dynamic Discovery Scheduler (v2.0.36f).

Covers the user's required behavior:
- self-driving discovery (no manual "find me jobs"): select_tasks/tick produce work.
- respects platform rate limits (throttle hooks), source cooldowns (interval), resource
  constraints (max_tasks_per_tick), model availability, working hours, freshness, dedup
  (engine), source reliability, error backoff.
- dynamic decisions from history: winner -> shorter interval + higher priority; loser -> reduced.
- exploration/exploitation balance: exploration floor maintained; known winners not fully exploited.
- multi-origin strategy generation (SKILL, HISTORICAL_CATEGORY, USER_PREFERENCE, EMERGING,
  PAST_SUCCESS_TERM, PLATFORM_TERM, EXPLORATION) + optional LLM suggester (fails safe).
- provenance: each discovered opp tagged with strategy:<id>; strategy outcomes learned.
- LLM NEVER performs an external action (only the injected validated discover_fn is called).
"""

import os
import tempfile
import time
import unittest
from typing import Dict, List

from agents.discovery_scheduler import (
    DiscoveryScheduler, SchedulerConfig, DiscoveryTask, SourceState,
)
from agents.discovery_strategies import (
    SearchStrategyGenerator, SearchStrategy, ORIGIN_SKILL, ORIGIN_EMERGING,
    ORIGIN_PAST_SUCCESS_TERM, ORIGIN_PLATFORM_TERM, ORIGIN_EXPLORATION,
)
from agents.opportunity_models import Opportunity


class _Mem:
    """Minimal memory stub implementing the reads/writes the scheduler uses."""
    def __init__(self):
        self.rep = {}
        self.cat = {}
        self.ok_terms = []
        self.bad_terms = []
        self.strategy_outcomes = []
        self.search_strategies = []

    def get_platform_reputation(self, src):
        return self.rep.get(src, {"success": 0, "total": 0, "avg_revenue": 0.0})

    def get_category_history(self, c):
        return self.cat.get(c, {"success": 0, "failed": 0, "total": 0,
                                 "success_rate": 0.0, "avg_revenue": 0.0, "confidence": 0.0})

    def get_successful_search_terms(self, n):
        return self.ok_terms[:n]

    def get_failed_search_terms(self, n):
        return self.bad_terms[:n]

    def compute_all_metrics(self, dim):
        return []

    def record_strategy_outcome(self, sid, success, reward=0.0):
        self.strategy_outcomes.append((sid, success, reward))

    def record_search_strategy(self, sid, origin, query, cats, source):
        self.search_strategies.append((sid, origin, query, cats, source))


def _opp(title, source="web", cat="other", prov=""):
    return Opportunity(opportunity_id=f"o_{title}", source=source, platform=source,
                       title=title, description="", category=cat,
                       external_url=f"https://x/{title}", provenance=prov)


class TestStrategyGeneration(unittest.TestCase):
    def test_all_origins_present(self):
        g = SearchStrategyGenerator()
        strs = g.generate(known_skills=["python"], successful_categories=["coding"],
                          preferences=["design"], successful_terms=["django"],
                          failed_terms=["spam"], sources=["upwork", "web"])
        origins = {s.origin for s in strs}
        for o in (ORIGIN_SKILL, ORIGIN_EMERGING, ORIGIN_PAST_SUCCESS_TERM,
                  ORIGIN_PLATFORM_TERM, ORIGIN_EXPLORATION):
            self.assertIn(o, origins)

    def test_failed_terms_excluded(self):
        g = SearchStrategyGenerator()
        strs = g.generate(failed_terms=["spammy query"], sources=["web"])
        self.assertFalse(any("spammy query" in s.query for s in strs))

    def test_llm_suggester_fails_safe(self):
        g = SearchStrategyGenerator()
        g.set_suggester(lambda ctx: (_ for _ in ()).throw(RuntimeError("llm down")))
        strs = g.generate(known_skills=["python"])  # must not raise
        self.assertTrue(isinstance(strs, list))

    def test_llm_suggestions_folded(self):
        g = SearchStrategyGenerator()
        g.set_suggester(lambda ctx: ["llm idea one", "llm idea two"])
        strs = g.generate(known_skills=["python"])
        self.assertTrue(any("llm idea" in s.query for s in strs))


class TestSchedulerDecisions(unittest.TestCase):
    def setUp(self):
        self.mem = _Mem()
        self.mem.rep = {
            "upwork": {"success": 9, "total": 10, "avg_revenue": 120.0},
            "fiverr": {"success": 1, "total": 10, "avg_revenue": 0.0},
        }
        self.now = time.time()
        self.sched = DiscoveryScheduler(memory=self.mem, generator=SearchStrategyGenerator(),
                                        config=SchedulerConfig())

    def test_winner_shorter_interval_higher_priority(self):
        self.sched.select_tasks(["upwork", "fiverr"], now=self.now)
        self.assertLess(self.sched._state("upwork").interval, self.sched._state("fiverr").interval)
        self.assertGreater(self.sched._state("upwork").priority, self.sched._state("fiverr").priority)

    def test_tasks_generated(self):
        tasks = self.sched.select_tasks(["upwork", "fiverr", "web"], now=self.now)
        self.assertTrue(len(tasks) > 0)

    def test_exploration_floor_present(self):
        tasks = self.sched.select_tasks(["upwork", "fiverr", "web"], now=self.now)
        self.assertGreaterEqual(sum(1 for t in tasks if t.is_exploration), 1)

    def test_not_pure_exploitation(self):
        # With profitable winners, we must still emit exploration tasks.
        tasks = self.sched.select_tasks(["upwork", "fiverr"], now=self.now)
        self.assertTrue(any(t.is_exploration for t in tasks))

    def test_error_backoff_suspends(self):
        for _ in range(3):
            self.sched.record_outcome("web", "sX", error=True, now=self.now)
        self.assertTrue(self.sched._state("web").suspended_until > self.now)
        self.assertFalse(self.sched._can_run("web", self.now))

    def test_one_bad_result_does_not_permanently_kill(self):
        for _ in range(3):
            self.sched.record_outcome("web", "sX", error=True, now=self.now)
        self.sched.record_outcome("web", "sX", success=True, now=self.now)
        self.assertLessEqual(self.sched._state("web").suspended_until, self.now)
        # after cooldown passes, it can run again
        self.sched._state("web").last_run = self.now - self.sched._state("web").interval - 5
        self.assertTrue(self.sched._can_run("web", self.now))

    def test_working_hours_skip(self):
        sched = DiscoveryScheduler(memory=self.mem, generator=SearchStrategyGenerator(),
                                   config=SchedulerConfig(working_hours=(9, 17)))
        import datetime
        off = time.mktime(datetime.datetime(2026, 1, 1, 3, 0).timetuple())
        self.assertEqual(len(sched.select_tasks(["upwork"], now=off)), 0)

    def test_freshness_skips_recent_category(self):
        self.sched.mark_searched("coding", now=self.now)
        tasks = self.sched.select_tasks(["upwork", "fiverr", "web"], now=self.now)
        self.assertEqual(sum(1 for t in tasks if t.category == "coding"), 0)

    def test_model_unavailable_uses_curated_exploration(self):
        sched = DiscoveryScheduler(memory=self.mem, generator=SearchStrategyGenerator(),
                                   config=SchedulerConfig(model_available=False))
        tasks = sched.select_tasks(["web"], now=self.now)
        for t in tasks:
            if t.is_exploration:
                self.assertIn(t.strategy.origin, (ORIGIN_EMERGING, ORIGIN_EXPLORATION, ORIGIN_PLATFORM_TERM))

    def test_resource_constraint_max_tasks(self):
        sched = DiscoveryScheduler(memory=self.mem, generator=SearchStrategyGenerator(),
                                   config=SchedulerConfig(max_tasks_per_tick=5))
        tasks = sched.select_tasks(["upwork", "fiverr", "web", "social", "defi", "airdrop"],
                                   now=self.now)
        self.assertLessEqual(len(tasks), 5)


class TestProvenanceAndLearning(unittest.TestCase):
    def setUp(self):
        self.mem = _Mem()
        self.now = time.time()
        self.sched = DiscoveryScheduler(memory=self.mem, generator=SearchStrategyGenerator(),
                                        config=SchedulerConfig())

    def test_tick_tags_provenance_and_records_strategy(self):
        # Injected VALIDATED provider interface (not the LLM).
        def discover_fn(source_name, strategy):
            return [_opp("job1", source=source_name, cat="coding")]

        stats = self.sched.tick(discover_fn, sources=["web"], now=self.now)
        self.assertGreaterEqual(stats["opportunities"], 1)
        # strategy usage recorded to memory (learning link)
        self.assertTrue(len(self.mem.search_strategies) >= 1)

    def test_run_task_tags_strategy_provenance(self):
        strat = SearchStrategy(strategy_id="s_test", origin=ORIGIN_SKILL, query="python",
                                categories=["coding"], source="web")
        task = DiscoveryTask(source="web", strategy=strat, category="coding",
                             priority=1.0, is_exploration=False, reason="t")
        opps, err = self.sched.run_task(task, lambda s, st: [_opp("j", source="web", cat="coding")],
                                        now=self.now)
        self.assertEqual(err, "")
        self.assertIn("strategy:s_test", opps[0].provenance)
        self.assertEqual(opps[0].category, "coding")

    def test_run_task_isolates_source_error(self):
        strat = SearchStrategy(strategy_id="s_err", origin=ORIGIN_SKILL, query="x", source="web")
        task = DiscoveryTask(source="web", strategy=strat, category="", priority=1.0,
                             is_exploration=True, reason="t")
        opps, err = self.sched.run_task(task, lambda s, st: (_ for _ in ()).throw(RuntimeError("boom")),
                                        now=self.now)
        self.assertEqual(opps, [])
        self.assertTrue(err)  # error isolated, not raised
        self.assertTrue(self.sched._state("web").suspended_until > self.now)  # backoff engaged

    def test_llm_never_called_in_tick(self):
        # The discover_fn is the only external entry; prove the LLM path is not touched.
        calls = {"n": 0}
        def discover_fn(source_name, strategy):
            calls["n"] += 1
            return [_opp("j", source=source_name)]
        self.sched.tick(discover_fn, sources=["web"], now=self.now)
        self.assertGreater(calls["n"], 0)  # validated interface called
        # No LLM object is referenced by the scheduler at all.
        self.assertIsNone(self.sched.generator._suggester)


class TestHistoryDrivenBoosts(unittest.TestCase):
    def setUp(self):
        self.mem = _Mem()
        # upwork: reliable + profitable -> should be prioritized / searched more often.
        self.mem.rep = {"upwork": {"success": 9, "total": 10, "avg_revenue": 120.0}}
        # A recently-profitable category should be boosted for exploration.
        self.mem.cat = {"ai_training_data": {"success": 5, "failed": 1, "total": 6,
                                             "success_rate": 0.83, "avg_revenue": 90.0,
                                             "confidence": 0.9}}
        self.now = time.time()
        self.sched = DiscoveryScheduler(memory=self.mem, generator=SearchStrategyGenerator(),
                                        config=SchedulerConfig())

    def test_recently_profitable_category_boosted(self):
        # The profitable category should appear among selected task categories.
        tasks = self.sched.select_tasks(["upwork", "web"], now=self.now)
        cats = {t.category for t in tasks}
        self.assertIn("ai_training_data", cats)

    def test_low_yield_high_listing_source_reduced(self):
        # fiverr: many listings, almost no success -> interval grows, priority drops.
        self.mem.rep = {"fiverr": {"success": 1, "total": 10, "avg_revenue": 0.0}}
        sched = DiscoveryScheduler(memory=self.mem, generator=SearchStrategyGenerator(),
                                   config=SchedulerConfig())
        sched.select_tasks(["fiverr", "web"], now=self.now)
        self.assertGreater(sched._state("fiverr").interval, 1800.0)  # beyond base
        self.assertLess(sched._state("fiverr").priority, 0.6)

    def test_profitable_source_priority_high(self):
        tasks = self.sched.select_tasks(["upwork", "web"], now=self.now)
        up_tasks = [t for t in tasks if t.source == "upwork"]
        self.assertTrue(up_tasks)
        # upwork tasks should carry a high priority (reliable + profitable).
        self.assertGreater(max(t.priority for t in up_tasks), 1.5)

    def test_exploration_maintained_with_winners(self):
        # Even with a known winner, exploration tasks must still be emitted (balance).
        tasks = self.sched.select_tasks(["upwork", "web"], now=self.now)
        self.assertTrue(any(t.is_exploration for t in tasks))


class TestSchedulerStatePersistence(unittest.TestCase):
    def test_source_state_defaults(self):
        st = SourceState(name="web")
        self.assertEqual(st.error_count, 0)
        self.assertFalse(st.is_suspended(time.time()))

    def test_backoff_grows_exponentially(self):
        st = SourceState(name="web")
        st.error_count = 0
        b0 = st.backoff_seconds()
        st.error_count = 3
        b3 = st.backoff_seconds()
        self.assertGreater(b3, b0)


if __name__ == "__main__":
    unittest.main()
