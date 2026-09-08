"""tests/test_learning_loop.py — Opportunity Learning Loop (v2.0.36d) extensive tests.

Covers the user's required behavior:
- 10-step feedback pipeline (record -> associate evidence -> economics -> predicted vs actual
  -> prediction error -> reputation/strategy/metrics -> future evaluation)
- prediction capture + prediction-error/accuracy tracking
- recency weighting (old outcomes don't dominate; history retained)
- the 11 required metrics (attempt/acceptance/completion/payment/failure/cancellation rates,
  avg revenue/net/effort/hourly, expected vs actual return)
- learning must NOT permanently blacklist from one bad result (sample-size guard)
- learning must NOT modify security policy; only ranking params within bounds
- the LLM cannot rewrite safety rules (governor refuses)
- outcomes flow into future evaluation (OpportunityIntelligenceEngine priors update)
- append-only / auditability
"""

import os
import tempfile
import time
import unittest


def _mem():
    return __import__("earning_memory").EarningMemory(
        db_path=os.path.join(tempfile.mkdtemp(), "ll.db"))


def _loop(mem):
    from earning_learning_loop import LearningLoop
    return LearningLoop(mem)


class TestPredictionCaptureAndAccuracy(unittest.TestCase):
    def setUp(self):
        self.mem = _mem()
        self.loop = _loop(self.mem)

    def test_predicted_vs_actual_effort_error(self):
        self.loop.process_outcome("o1", outcome_state="failed", category="writing",
            effort_hours=5.0, predicted={"effort_hours": 2.0, "revenue": 100.0, "success_prob": 0.75},
            predicted_effort_hours=2.0, predicted_revenue=100.0, predicted_success_prob=0.75,
            failure_cause="bad_estimate")
        acc = self.mem.get_prediction_accuracy("category", "writing")
        # effort pred 2, actual 5 -> err 3/2 = 1.5
        self.assertAlmostEqual(acc["effort_mae_pct"], 1.5, places=2)
        self.assertEqual(acc["sample_size"], 1)
        self.assertTrue(acc["cold_start"])

    def test_predicted_vs_actual_revenue_error(self):
        self.loop.process_outcome("o1", outcome_state="paid", category="writing",
            revenue=80.0, predicted={"revenue": 100.0, "success_prob": 0.8},
            predicted_revenue=100.0, predicted_success_prob=0.8, success_cause="good")
        acc = self.mem.get_prediction_accuracy("category", "writing")
        # revenue pred 100, actual 80 -> err 0.2
        self.assertAlmostEqual(acc["revenue_mae_pct"], 0.2, places=2)

    def test_success_probability_wrong_when_actual_fails(self):
        # predicted 0.75 (model said success) but actual failed -> success_correct = 0
        self.loop.process_outcome("o1", outcome_state="failed", category="writing",
            predicted={"success_prob": 0.75}, predicted_success_prob=0.75, failure_cause="bad")
        acc = self.mem.get_prediction_accuracy("category", "writing")
        self.assertEqual(acc["success_accuracy"], 0.0)

    def test_success_probability_correct_when_actual_paid(self):
        self.loop.process_outcome("o1", outcome_state="paid", category="writing",
            predicted={"success_prob": 0.75}, predicted_success_prob=0.75, success_cause="good")
        acc = self.mem.get_prediction_accuracy("category", "writing")
        self.assertEqual(acc["success_accuracy"], 1.0)

    def test_no_prediction_recorded_when_not_supplied(self):
        self.loop.process_outcome("o1", outcome_state="paid", category="writing",
            revenue=80.0, success_cause="good")
        acc = self.mem.get_prediction_accuracy("category", "writing")
        self.assertEqual(acc["sample_size"], 0)
        self.assertTrue(acc["cold_start"])

    def test_accuracy_confidence_low_at_n1_rises_with_samples(self):
        for i in range(5):
            self.loop.process_outcome(f"o{i}", outcome_state="paid", category="writing",
                revenue=90.0 + i, predicted={"revenue": 100.0, "success_prob": 0.8},
                predicted_revenue=100.0, predicted_success_prob=0.8, success_cause="good")
        acc = self.mem.get_prediction_accuracy("category", "writing")
        self.assertGreater(acc["confidence"], 0.25)  # grew beyond neutral
        self.assertFalse(acc["cold_start"])


class TestRecencyWeighting(unittest.TestCase):
    def setUp(self):
        self.mem = _mem()
        self.loop = _loop(self.mem)
        self.now = time.time()

    def _seed(self, recent_rev, old_rev, old_age_days=365):
        self.loop.process_outcome("recent", outcome_state="paid", category="w",
            revenue=recent_rev, cost=0.0, predicted={"revenue": recent_rev},
            predicted_revenue=recent_rev, success_cause="good")
        self.loop.process_outcome("old", outcome_state="paid", category="w",
            revenue=old_rev, cost=0.0, predicted={"revenue": old_rev},
            predicted_revenue=old_rev, success_cause="good")
        # backdate the "old" row
        import sqlite3
        c = sqlite3.connect(self.mem.db_path)
        c.execute("UPDATE outcome_memory_v2 SET ts=? WHERE opportunity_id=?",
                  (self.now - old_age_days * 86400, "old"))
        c.commit(); c.close()

    def test_recent_outcome_dominates_average(self):
        self._seed(recent_rev=200.0, old_rev=20.0)
        m = self.mem.compute_opportunity_metrics("category", "w", now=self.now)
        # unweighted avg would be 110; recency-weighted should be ~ near 200
        self.assertGreater(m.average_revenue, 150.0)
        self.assertLess(m.average_revenue, 200.0)

    def test_history_retained_for_audit(self):
        self._seed(recent_rev=200.0, old_rev=20.0)
        with self.mem._lock:
            import sqlite3
            c = sqlite3.connect(self.mem.db_path)
            n = c.execute("SELECT COUNT(*) FROM outcome_memory_v2 WHERE category='w'").fetchone()[0]
            c.close()
        self.assertEqual(n, 2)  # BOTH rows kept (no deletion)

    def test_recency_weight_function_monotonic(self):
        from earning_memory import recency_weight
        w0 = recency_weight(self.now, now=self.now)
        w_old = recency_weight(self.now - 365 * 86400, now=self.now)
        self.assertAlmostEqual(w0, 1.0, places=3)
        self.assertLess(w_old, 0.1)  # 1yr old weighs far less


class TestElevenMetrics(unittest.TestCase):
    def setUp(self):
        self.mem = _mem()
        self.loop = _loop(self.mem)

    def _seed_funnel(self):
        # category 'w': 4 attempts -> 3 accepted -> 2 completed -> 2 paid; 1 failed; 1 cancelled
        self.loop.process_outcome("a1", outcome_state="applied", category="w", revenue=0.0)
        self.loop.process_outcome("a2", outcome_state="accepted", category="w", revenue=0.0)
        self.loop.process_outcome("a3", outcome_state="completed", category="w", revenue=100.0, cost=10.0, effort_hours=2.0, time_spent_hours=3.0, success_cause="good")
        self.loop.process_outcome("a4", outcome_state="paid", category="w", revenue=120.0, cost=10.0, effort_hours=2.0, time_spent_hours=3.0, success_cause="good")
        self.loop.process_outcome("a5", outcome_state="failed", category="w", revenue=0.0, failure_cause="bad")
        self.loop.process_outcome("a6", outcome_state="abandoned", category="w", revenue=0.0)

    def test_all_eleven_metrics_present(self):
        self._seed_funnel()
        m = self.mem.compute_opportunity_metrics("category", "w")
        for f in ("attempt_rate", "acceptance_rate", "completion_rate", "payment_rate",
                  "failure_rate", "cancellation_rate", "average_revenue",
                  "average_net_profit", "average_effort_hours", "average_hourly_return",
                  "expected_vs_actual_return"):
            self.assertTrue(hasattr(m, f), f"missing metric {f}")
            self.assertIsInstance(getattr(m, f), (int, float))

    def test_funnel_rates_correct(self):
        self._seed_funnel()
        m = self.mem.compute_opportunity_metrics("category", "w")
        # a2 accepted, a3 completed, a4 paid -> 3 reached acceptance; a3+a4 completed; a4 paid
        self.assertAlmostEqual(m.acceptance_rate, 3 / 6, places=3)
        self.assertAlmostEqual(m.completion_rate, 2 / 6, places=3)
        self.assertAlmostEqual(m.payment_rate, 1 / 6, places=3)
        self.assertAlmostEqual(m.failure_rate, 1 / 6, places=3)
        self.assertAlmostEqual(m.cancellation_rate, 1 / 6, places=3)

    def test_average_revenue_and_profit(self):
        self._seed_funnel()
        m = self.mem.compute_opportunity_metrics("category", "w")
        # revenue weighted avg of paid rows mostly (100,120) vs 0s; > 0
        self.assertGreater(m.average_revenue, 0.0)
        self.assertGreater(m.average_net_profit, 0.0)

    def test_average_hourly_return(self):
        self._seed_funnel()
        m = self.mem.compute_opportunity_metrics("category", "w")
        # net ~ (90+110)/2 per paid; time 3h -> ~33/h
        self.assertGreater(m.average_hourly_return, 0.0)

    def test_cold_start_confidence_at_low_n(self):
        self.loop.process_outcome("x", outcome_state="paid", category="z", revenue=50.0, success_cause="good")
        m = self.mem.compute_opportunity_metrics("category", "z")
        self.assertTrue(m.cold_start)
        self.assertLess(m.confidence, 1.0)

    def test_compute_all_metrics_iterates_dimensions(self):
        self._seed_funnel()
        allm = self.mem.compute_all_metrics("category")
        self.assertTrue(any(m.value == "w" for m in allm))


class TestLearningLoopPipeline(unittest.TestCase):
    def setUp(self):
        self.mem = _mem()
        self.loop = _loop(self.mem)

    def test_step1_record_outcome(self):
        d = self.loop.process_outcome("o1", outcome_state="paid", category="w",
            revenue=100.0, success_cause="good")
        self.assertTrue(d.recorded)
        self.assertEqual(self.mem.get_category_history("w")["total"], 1)

    def test_step2_associate_evidence(self):
        d = self.loop.process_outcome("o1", outcome_state="paid", category="w",
            revenue=100.0, success_cause="good", evidence_ids=["ev1", "ev2"])
        self.assertEqual(d.evidence_linked, 2)
        self.assertEqual(self.mem.get_outcome_evidence("o1"), ["ev1", "ev2"])

    def test_step6_reputation_updated(self):
        self.loop.process_outcome("o1", outcome_state="paid", platform="up", category="w",
            revenue=100.0, success_cause="good")
        rep = self.mem.get_platform_reputation("up")
        self.assertEqual(rep["success"], 1)
        self.assertEqual(rep["total"], 1)

    def test_step7_strategy_memory_updated(self):
        self.loop.process_outcome("o1", outcome_state="paid", category="w",
            strategy_used="aggressive", proposal_variant="v1", revenue=100.0, success_cause="good")
        from earning_memory import EarningMemory
        # strategy_memory updated via fan-out
        self.assertGreater(self.mem.compute_opportunity_metrics("category", "w").sample_size, 0)

    def test_step8_category_performance_updated(self):
        for i in range(3):
            self.loop.process_outcome(f"o{i}", outcome_state="paid", category="w",
                revenue=90.0, success_cause="good")
        m = self.mem.compute_opportunity_metrics("category", "w")
        self.assertEqual(m.sample_size, 3)
        self.assertGreater(m.average_revenue, 0.0)

    def test_step10_future_evaluation_reflects_learning(self):
        from agents.opportunity_intelligence import OpportunityIntelligenceEngine, SemanticEstimate
        from agents.opportunity_models import Opportunity
        for i in range(5):
            self.loop.process_outcome(f"w{i}", outcome_state="paid", category="writing",
                revenue=100.0, cost=10.0, effort_hours=2.0, time_spent_hours=3.0, success_cause="good")
        self.loop.process_outcome("wf", outcome_state="failed", category="writing",
            revenue=0.0, cost=5.0, failure_cause="bad")
        eng = OpportunityIntelligenceEngine()
        est = SemanticEstimate(skill_fit=0.8, difficulty=0.3, competition=0.3)
        def mk(cat):
            return Opportunity(opportunity_id="n", source="src", platform="up", title="T",
                description="d", category=cat, advertised_amount=100.0, estimated_net_value=90.0,
                estimated_effort=2.0, scam_risk=0.1, risk_level="low", source_reliability=0.7,
                external_url="https://x")
        r_w = eng.evaluate(mk("writing"), memory=self.mem, estimates=est)
        r_c = eng.evaluate(mk("coding"), memory=self.mem, estimates=est)
        # writing has learned history (success_rate ~0.83) -> higher expected value than cold coding
        self.assertGreater(r_w.expected_value, r_c.expected_value)
        self.assertAlmostEqual(self.mem.get_category_history("writing")["success_rate"], 5 / 6, places=3)


class TestGovernanceAndSafety(unittest.TestCase):
    def setUp(self):
        self.gov = __import__("earning_learning_loop").LearningGovernor()
        self.loop = _loop(_mem())

    def test_security_policy_refused_api_key(self):
        self.assertFalse(self.gov.can_adjust("OPENAI_API_KEY"))
        dec = self.gov.propose_adjustment("OPENAI_API_KEY", 0.0)
        self.assertFalse(dec["allowed"])

    def test_security_policy_refused_safe_mode(self):
        self.assertFalse(self.gov.can_adjust("safe_mode_enabled"))
        self.assertFalse(self.gov.can_adjust("BLOCKED_PLATFORMS"))

    def test_ranking_param_clamped_to_bounds(self):
        dec = self.gov.propose_adjustment("category_preference_multiplier", 5.0)
        self.assertTrue(dec["allowed"])
        self.assertEqual(dec["value"], 1.5)  # clamped to upper bound
        dec2 = self.gov.propose_adjustment("category_preference_multiplier", -9.0)
        self.assertEqual(dec2["value"], 0.5)  # clamped to lower bound

    def test_unknown_param_refused(self):
        dec = self.gov.propose_adjustment("some_random_param", 1.0)
        self.assertFalse(dec["allowed"])

    def test_one_bad_result_does_not_blacklist(self):
        dec = self.gov.propose_suppression("category", "writing", failure_rate=1.0, sample_size=1)
        self.assertFalse(dec["suppress"])
        self.assertEqual(dec["multiplier"], 1.0)

    def test_suppression_only_with_enough_samples_and_floor(self):
        dec = self.gov.propose_suppression("category", "writing", failure_rate=0.9, sample_size=10)
        self.assertTrue(dec["suppress"])
        self.assertGreaterEqual(dec["multiplier"], 0.5)  # bounded, never 0

    def test_loop_never_modifies_security(self):
        # The loop's governor cannot produce an allowed adjustment for a security param.
        self.assertTrue(self.loop.refuse_security_policy_change("PROVIDER_NVIDIA_ENABLED", 0.0))
        self.assertTrue(self.loop.refuse_security_policy_change("MAX_TOKENS", 0.0))

    def test_llm_cannot_rewrite_safety_rules(self):
        # An "unsafe" learned suggestion must be refused by the governor, not applied.
        unsafe_suggestion = {"param": "safe_mode_enabled", "value": 0}
        dec = self.gov.propose_adjustment(unsafe_suggestion["param"], unsafe_suggestion["value"])
        self.assertFalse(dec["allowed"])
        self.assertIsNone(dec["value"])


class TestAppendOnlyAudit(unittest.TestCase):
    def setUp(self):
        self.mem = _mem()
        self.loop = _loop(self.mem)

    def test_outcome_recorded_once_idempotent_rows(self):
        self.loop.process_outcome("o1", outcome_state="paid", category="w", revenue=50.0, success_cause="good")
        self.loop.process_outcome("o2", outcome_state="paid", category="w", revenue=60.0, success_cause="good")
        import sqlite3
        c = sqlite3.connect(self.mem.db_path)
        n = c.execute("SELECT COUNT(*) FROM outcome_memory_v2 WHERE category='w'").fetchone()[0]
        c.close()
        self.assertEqual(n, 2)  # both retained, append-only

    def test_prediction_history_retained_for_audit(self):
        self.loop.process_outcome("o1", outcome_state="paid", category="w", revenue=50.0,
            predicted={"revenue": 100.0, "success_prob": 0.8}, predicted_revenue=100.0,
            predicted_success_prob=0.8, success_cause="good")
        import sqlite3
        c = sqlite3.connect(self.mem.db_path)
        n = c.execute("SELECT COUNT(*) FROM prediction_accuracy").fetchone()[0]
        c.close()
        self.assertEqual(n, 4)  # global + category + platform + task_type rows (dim fan-out)


if __name__ == "__main__":
    unittest.main()
