"""tests/test_earning_memory_au.py — Earning/Opportunity Learning Memory expansion (v2.0.35).

Covers the user's required scenario set:
- 10 distinct memory types (write + read)
- outcome states (all 14) + unknown-state rejection
- structured failure causes (16) — never just "failure"
- structured success causes (WHY it succeeded)
- analytics answering the 12 questions (confidence + sample size)
- cold-start safety (neutral prior, low confidence, no overlearning from n=1)
- outcomes flow into future decisions (OpportunityIntelligenceEngine reads the memory)
"""

import os
import tempfile
import unittest

from earning_memory import (
    EarningMemory, OUTCOME_STATES, FAILURE_CAUSES, SUCCESS_CAUSES, MIN_SAMPLES,
)
from agents.opportunity_intelligence import OpportunityIntelligenceEngine, EvaluationConfig
from agents.opportunity_models import Opportunity


class _MemoryTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.mktemp(suffix=".db", prefix="emau-")
        self.mem = EarningMemory(db_path=self.tmp_db)

    def tearDown(self):
        if os.path.exists(self.tmp_db):
            os.unlink(self.tmp_db)

    def _opp(self, category="writing", task_type="article", platform="Upwork",
             amount=100.0, net=90.0, effort=2.0, opp_id="o1", ext="http://x/1"):
        return Opportunity(
            opportunity_id=opp_id, source="test", platform=platform,
            title="Gig", description="Do the thing", category=category,
            task_type=task_type, advertised_amount=amount,
            estimated_net_value=net, estimated_effort=effort,
            currency="USD", external_url=ext,
        )


class TestMemoryTypesAndEnums(_MemoryTestBase):
    def test_outcome_states_all_accepted(self):
        for st in OUTCOME_STATES:
            rid = self.mem.record_outcome_v2("o_" + st, st, category="c", platform="p")
            self.assertIsNotNone(rid, f"state {st} should be accepted")

    def test_unknown_outcome_state_rejected(self):
        self.assertIsNone(self.mem.record_outcome_v2("oX", "not_a_real_state"))
        # nothing recorded
        self.assertEqual(self.mem._category_net_hourly(), [])

    def test_failure_cause_structured(self):
        self.mem.record_outcome_v2("o1", "failed", platform="Upwork", category="writing",
                                   failure_cause="low_payment", cost=5.0)
        # failure_memory should carry the structured cause, not bare "failure"
        with self.mem._lock:
            import sqlite3
            conn = sqlite3.connect(self.mem.db_path)
            row = conn.execute("SELECT cause FROM failure_memory").fetchone()
            conn.close()
        self.assertEqual(row[0], "low_payment")

    def test_failure_cause_unknown_ignored(self):
        self.mem.record_outcome_v2("o1", "failed", failure_cause="bogus_cause")
        with self.mem._lock:
            import sqlite3
            conn = sqlite3.connect(self.mem.db_path)
            n = conn.execute("SELECT COUNT(*) FROM failure_memory").fetchone()[0]
            conn.close()
        self.assertEqual(n, 0)

    def test_success_cause_structured(self):
        self.mem.record_outcome_v2("o1", "accepted", platform="Upwork", category="writing",
                                   success_cause="good_skill_fit", revenue=100.0)
        with self.mem._lock:
            import sqlite3
            conn = sqlite3.connect(self.mem.db_path)
            row = conn.execute("SELECT cause FROM success_memory").fetchone()
            conn.close()
        self.assertEqual(row[0], "good_skill_fit")

    def test_all_failure_causes_enumerable(self):
        self.assertEqual(len(FAILURE_CAUSES), 16)
        for c in FAILURE_CAUSES:
            # each is a valid cause with no crash on store
            self.mem.record_outcome_v2("o_" + c, "failed", failure_cause=c)

    def test_all_success_causes_enumerable(self):
        self.assertEqual(len(SUCCESS_CAUSES), 12)
        for c in SUCCESS_CAUSES:
            self.mem.record_outcome_v2("o_" + c, "accepted", success_cause=c, revenue=10.0)

    def test_opportunity_timeline_records_events(self):
        self.mem.record_opportunity_event("o1", "discovered", "found on Upwork")
        self.mem.record_opportunity_event("o1", "submitted")
        with self.mem._lock:
            import sqlite3
            conn = sqlite3.connect(self.mem.db_path)
            rows = conn.execute(
                "SELECT stage FROM opportunity_timeline WHERE opportunity_id='o1' ORDER BY id").fetchall()
            conn.close()
        self.assertEqual([r[0] for r in rows], ["discovered", "submitted"])

    def test_record_outcome_fans_out(self):
        self.mem.record_outcome_v2("o1", "accepted", platform="Upwork", category="writing",
                                   task_type="article", revenue=100.0, cost=10.0,
                                   strategy_used="templateA", proposal_variant="v1",
                                   success_cause="good_skill_fit")
        # strategy memory
        with self.mem._lock:
            import sqlite3
            conn = sqlite3.connect(self.mem.db_path)
            strat = conn.execute("SELECT success_count FROM strategy_memory").fetchone()
            src = conn.execute("SELECT accepted, paid FROM source_memory").fetchone()
            conn.close()
        self.assertEqual(strat[0], 1)
        self.assertEqual(src[0], 1)  # accepted counted


class TestAnalyticsAndColdStart(_MemoryTestBase):
    def _seed(self, n_accept, n_fail, category="writing", platform="Upwork"):
        for i in range(n_accept):
            self.mem.record_outcome_v2(f"a{i}", "accepted", platform=platform,
                                       category=category, task_type="article",
                                       revenue=100.0, cost=10.0, time_spent_hours=2.0,
                                       strategy_used="tpl", proposal_variant="v1",
                                       success_cause="good_skill_fit")
        for i in range(n_fail):
            self.mem.record_outcome_v2(f"f{i}", "failed", platform=platform,
                                       category=category, task_type="article",
                                       cost=5.0, strategy_used="tpl", proposal_variant="v1",
                                       failure_cause="low_payment")

    def test_confidence_low_at_n1(self):
        self.mem.record_outcome_v2("o1", "accepted", category="writing", success_cause="good_skill_fit")
        summ = self.mem.category_outcome_summary("writing")
        self.assertTrue(summ["cold_start"])
        self.assertLess(summ["confidence"], 1.0)
        self.assertEqual(summ["sample_size"], 1)

    def test_cold_start_neutral_when_empty(self):
        summ = self.mem.category_outcome_summary("nonexistent")
        self.assertTrue(summ["cold_start"])
        self.assertEqual(summ["sample_size"], 0)

    def test_confidence_rises_after_min_samples(self):
        self._seed(MIN_SAMPLES + 2, 0)
        summ = self.mem.category_outcome_summary("writing")
        self.assertFalse(summ["cold_start"])
        self.assertGreaterEqual(summ["confidence"], 0.25)

    def test_most_reliable_platforms(self):
        self._seed(3, 0, platform="Upwork")
        self._seed(0, 4, platform="Flaky")
        rel = self.mem.most_reliable_platforms()
        platforms = [r["platform"] for r in rel]
        self.assertIn("Upwork", platforms)
        # Upwork (success_rate 1.0) must outrank Flaky (success_rate 0.0) in desc order
        self.assertLess(platforms.index("Upwork"), platforms.index("Flaky"))

    def test_platforms_poor_acceptance(self):
        self._seed(0, 5, platform="Flaky")
        poor = self.mem.platforms_poor_acceptance()
        self.assertEqual(poor[0]["platform"], "Flaky")
        self.assertLess(poor[0]["success_rate"], 0.5)

    def test_best_performing_task_types(self):
        self.mem.record_outcome_v2("a", "accepted", category="writing", task_type="article", success_cause="good_skill_fit")
        res = self.mem.best_performing_task_types()
        self.assertEqual(res[0]["task_type"], "article")
        self.assertEqual(res[0]["value"], 1.0)

    def test_net_hourly_category(self):
        self.mem.record_outcome_v2("a", "accepted", category="writing", revenue=100.0,
                                   cost=10.0, time_spent_hours=2.0, net_profit=90.0,
                                   success_cause="good_skill_fit")
        self.mem.record_outcome_v2("b", "failed", category="writing", cost=50.0,
                                   time_spent_hours=10.0, net_profit=-50.0,
                                   failure_cause="low_payment")
        hi = self.mem.highest_net_hourly_categories()
        self.assertEqual(hi[0]["category"], "writing")
        self.assertGreater(hi[0]["value"], 0.0)

    def test_best_proposal_templates(self):
        self.mem.record_outcome_v2("a", "accepted", proposal_variant="v1", category="c", success_cause="good_skill_fit")
        self.mem.record_outcome_v2("b", "failed", proposal_variant="v2", category="c", failure_cause="low_payment")
        best = self.mem.best_proposal_templates()
        self.assertEqual(best[0]["proposal_variant"], "v1")

    def test_recurring_failure_causes(self):
        for i in range(3):
            self.mem.record_outcome_v2(f"f{i}", "failed", category="c", failure_cause="deadline_failure")
        self.mem.record_outcome_v2("f4", "failed", category="c", failure_cause="low_payment")
        rc = self.mem.recurring_failure_causes()
        self.assertEqual(rc[0]["cause"], "deadline_failure")
        self.assertEqual(rc[0]["count"], 3)

    def test_reusable_and_avoid_strategies(self):
        # Use two DISTINCT strategies so ordering is meaningful.
        for i in range(5):
            self.mem.record_outcome_v2(f"a{i}", "accepted", category="c", platform="Upwork",
                                       strategy_used="good", proposal_variant="v1",
                                       success_cause="good_skill_fit", revenue=100.0, cost=5.0)
        for i in range(4):
            self.mem.record_outcome_v2(f"b{i}", "failed", category="c2", platform="Flaky",
                                       strategy_used="bad", proposal_variant="v1",
                                       failure_cause="low_payment", cost=5.0)
        reuse = self.mem.reusable_success_strategies()
        strategies = [r["strategy"] for r in reuse]
        self.assertIn("good", strategies)
        self.assertIn("bad", strategies)
        # 'good' (5/5) must outrank 'bad' (0/4)
        self.assertLess(strategies.index("good"), strategies.index("bad"))
        self.assertGreater(reuse[0]["value"], reuse[-1]["value"])
        avoid = self.mem.strategies_to_avoid()
        self.assertTrue(len(avoid) >= 1)

    def test_profitable_but_often_fail(self):
        for i in range(4):
            self.mem.record_outcome_v2(f"f{i}", "failed", category="trap", failure_cause="low_payment", revenue=0.0)
        for i in range(4):
            self.mem.record_outcome_v2(f"a{i}", "accepted", category="trap", revenue=200.0, success_cause="good_skill_fit")
        pbf = self.mem.profitable_but_often_fail()
        self.assertEqual(pbf[0]["category"], "trap")

    def test_task_types_high_completion(self):
        self.mem.record_outcome_v2("a", "completed", category="c", task_type="quick")
        self.mem.record_outcome_v2("b", "failed", category="c", task_type="slow")
        hc = self.mem.task_types_high_completion()
        self.assertEqual(hc[0]["task_type"], "quick")


class TestOutcomesFlowIntoDecisions(_MemoryTestBase):
    """T5: recorded outcomes must change the engine's verdict/priors."""

    def test_cold_start_then_history_changes_engine(self):
        opp = self._opp(category="writing", task_type="article", platform="Upwork")
        eng = OpportunityIntelligenceEngine(EvaluationConfig())
        # 1) Cold start: no memory -> cold_start True, neutral prior
        r0 = eng.evaluate(opp, memory=self.mem)
        self.assertTrue(r0.cold_start)
        self.assertLess(r0.confidence, 0.3)

        # 2) Record several ACCEPTED outcomes in this category/platform
        for i in range(5):
            self.mem.record_outcome_v2(f"a{i}", "accepted", platform="Upwork",
                                       category="writing", task_type="article",
                                       revenue=120.0, cost=10.0, time_spent_hours=2.0,
                                       strategy_used="tpl", proposal_variant="v1",
                                       success_cause="good_skill_fit")
        r1 = eng.evaluate(opp, memory=self.mem)
        self.assertFalse(r1.cold_start)
        self.assertGreater(r1.reasons["historical_success_rate"], 0.9)
        self.assertGreater(r1.confidence, r0.confidence)

    def test_failures_lower_engine_ev(self):
        opp = self._opp(category="risky", task_type="article", platform="Upwork")
        eng = OpportunityIntelligenceEngine(EvaluationConfig())
        # Seed failures in this category
        for i in range(5):
            self.mem.record_outcome_v2(f"f{i}", "failed", platform="Upwork",
                                       category="risky", task_type="article",
                                       cost=10.0, strategy_used="tpl",
                                       failure_cause="low_payment")
        r = eng.evaluate(opp, memory=self.mem)
        self.assertFalse(r.cold_start)
        # Historical success rate should be ~0, dragging EV down vs a clean category
        self.assertLess(r.reasons["historical_success_rate"], 0.2)


if __name__ == "__main__":
    unittest.main()
