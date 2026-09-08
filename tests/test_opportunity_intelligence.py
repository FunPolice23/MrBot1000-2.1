"""tests/test_opportunity_intelligence.py — Opportunity Intelligence Engine.

Covers the 24-factor expected-value model, neutral-prior cold-start, deterministic
combination (LLM provides estimates only), structured explainable verdicts, and the
required scenarios: cold-start, strong history, poor history, missing data,
high-risk, highly profitable, all six verdict classes.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.opportunity_models import Opportunity
from agents.opportunity_intelligence import (
    OpportunityIntelligenceEngine, SemanticEstimate, EvaluationConfig, EvaluationResult,
)
from earning_memory import EarningMemory


def _opp(**kw):
    base = dict(opportunity_id="o1", source="src", platform="Upwork",
                title="T", description="d", category="coding",
                advertised_amount=100.0, estimated_net_value=90.0,
                estimated_effort=5.0, scam_risk=0.1, risk_level="low",
                source_reliability=0.7, external_url="https://x.com/j/1")
    base.update(kw)
    return Opportunity(**base)


class TestFactorModel(unittest.TestCase):
    def setUp(self):
        self.engine = OpportunityIntelligenceEngine()

    def test_expected_value_formula(self):
        # Highly profitable, low-risk, high skill fit.
        o = _opp(advertised_amount=500.0, estimated_net_value=450.0, estimated_effort=10.0,
                 scam_risk=0.05, risk_level="low", source_reliability=0.9)
        est = SemanticEstimate(skill_fit=0.9, difficulty=0.3, competition=0.3)
        r = self.engine.evaluate(o, estimates=est)
        # EV must equal P(success)*P(payment)*net - cost - penalty (cost 0 at default).
        expected = r.p_success * r.p_payment * r.expected_net_revenue - r.risk_penalty
        self.assertAlmostEqual(r.expected_value, expected, places=3)
        self.assertGreater(r.expected_value, 0)

    def test_expected_hourly_value(self):
        o = _opp(estimated_net_value=200.0, estimated_effort=4.0, scam_risk=0.0,
                 risk_level="low", source_reliability=0.9)
        r = self.engine.evaluate(o, estimates=SemanticEstimate(skill_fit=0.8, difficulty=0.2))
        self.assertGreater(r.expected_hourly_value, 0)
        self.assertAlmostEqual(r.expected_hourly_value, r.expected_value / 4.0, places=2)

    def test_p_success_is_acceptance_times_completion(self):
        o = _opp()
        r = self.engine.evaluate(o, estimates=SemanticEstimate(skill_fit=0.7, difficulty=0.4))
        self.assertAlmostEqual(r.p_success, r.p_acceptance * r.p_completion, places=6)

    def test_structured_reasons_present(self):
        r = self.engine.evaluate(_opp(), estimates=SemanticEstimate(skill_fit=0.8, difficulty=0.3))
        for k in ("skill_fit", "task_difficulty", "payment", "platform_history", "scam_risk",
                  "confidence", "verdict_rationale"):
            self.assertIn(k, r.reasons)
        # Not just a score — reasons explain WHY.
        self.assertIsInstance(r.reasons["skill_fit"], str)

    def test_configurable_policy(self):
        # Raising the attractive threshold changes the verdict, not the model.
        cfg = EvaluationConfig(attractive_ev=1000.0)
        e = OpportunityIntelligenceEngine(cfg)
        o = _opp(advertised_amount=500.0, estimated_net_value=450.0)
        r = e.evaluate(o, estimates=SemanticEstimate(skill_fit=0.9, difficulty=0.2))
        self.assertEqual(r.verdict, "marginal")  # EV below the raised bar


class TestColdStart(unittest.TestCase):
    def setUp(self):
        self.engine = OpportunityIntelligenceEngine()

    def test_neutral_prior_used_without_memory(self):
        e = OpportunityIntelligenceEngine()
        o = _opp()
        r = e.evaluate(o, estimates=SemanticEstimate(skill_fit=0.8, difficulty=0.3))
        # No memory -> cold_start flagged, neutral-prior probabilities (~0.5 region).
        self.assertTrue(r.cold_start)
        self.assertLessEqual(r.confidence, EvaluationConfig().neutral_confidence + 1e-6)
        # Neutral prior still yields a computable, non-zero probability.
        self.assertGreater(r.p_success, 0.0)
        self.assertLessEqual(r.p_success, 1.0)

    def test_cold_start_does_not_reject_category(self):
        # A profitable-but-unknown category is not "blocked"/"poor" purely for cold-start.
        o = _opp(category="brand_new_cat", advertised_amount=400.0, estimated_net_value=380.0,
                 estimated_effort=8.0, scam_risk=0.05, risk_level="low", source_reliability=0.8)
        r = self.engine.evaluate(o, estimates=SemanticEstimate(skill_fit=0.9, difficulty=0.2))
        self.assertTrue(r.cold_start)
        self.assertIn(r.verdict, ("attractive", "marginal"))  # not blocked/poor for lack of data

    def test_confidence_low_at_cold_start(self):
        r = self.engine.evaluate(_opp())
        self.assertLess(r.confidence, 0.4)


class TestWithMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mem = EarningMemory(db_path=os.path.join(self.tmp, "m.db"))
        self.engine = OpportunityIntelligenceEngine()

    def _seed(self, platform=None, category=None, task_type=None, wins=0, losses=0, rev=0.0):
        for _ in range(wins):
            if platform: self.mem.update_reputation(platform, True, rev)
            if category: self.mem.record_category_outcome(category, True, rev)
            if task_type: self.mem.record_task_type_outcome(task_type, True, rev)
        for _ in range(losses):
            if platform: self.mem.update_reputation(platform, False)
            if category: self.mem.record_category_outcome(category, False, 0.0)
            if task_type: self.mem.record_task_type_outcome(task_type, False, 0.0)

    def test_strong_history_boosts_verdict(self):
        # Strong platform + category + task-type history (above min samples).
        self._seed(platform="Upwork", category="coding", task_type="python",
                   wins=10, rev=120.0)
        o = _opp(platform="Upwork", category="coding", task_type="python",
                 advertised_amount=200.0, estimated_net_value=180.0, estimated_effort=6.0,
                 scam_risk=0.05, risk_level="low", source_reliability=0.85)
        r = self.engine.evaluate(o, memory=self.mem,
                                 estimates=SemanticEstimate(skill_fit=0.9, difficulty=0.3))
        self.assertFalse(r.cold_start)
        self.assertGreater(r.confidence, EvaluationConfig().neutral_confidence)
        self.assertIn(r.verdict, ("attractive", "marginal"))

    def test_poor_history_lowers_success_prob(self):
        # Mostly losses -> low historical success rate -> lower p_success than neutral.
        self._seed(platform="Flaky", category="writing", task_type="blog",
                   wins=1, losses=9, rev=10.0)
        o = _opp(platform="Flaky", category="writing", task_type="blog",
                 advertised_amount=200.0, estimated_net_value=180.0, estimated_effort=6.0,
                 scam_risk=0.1, risk_level="low", source_reliability=0.5)
        r = self.engine.evaluate(o, memory=self.mem,
                                 estimates=SemanticEstimate(skill_fit=0.8, difficulty=0.3))
        # Historical success rate ~0.1 -> blended success pulled down -> p_success below neutral.
        self.assertLess(r.p_success, 0.5)
        self.assertIn(r.verdict, ("poor", "marginal"))

    def test_history_helpers_zero_at_start(self):
        self.assertEqual(self.mem.get_category_history("coding")["total"], 0)
        self.assertEqual(self.mem.get_task_type_history("python")["total"], 0)


class TestVerdictClasses(unittest.TestCase):
    def setUp(self):
        self.engine = OpportunityIntelligenceEngine()

    def test_attractive_profitable(self):
        o = _opp(advertised_amount=1000.0, estimated_net_value=900.0, estimated_effort=10.0,
                 scam_risk=0.02, risk_level="low", source_reliability=0.95)
        r = self.engine.evaluate(o, estimates=SemanticEstimate(skill_fit=0.95, difficulty=0.2))
        self.assertEqual(r.verdict, "attractive")

    def test_marginal(self):
        o = _opp(advertised_amount=50.0, estimated_net_value=40.0, estimated_effort=8.0,
                 scam_risk=0.1, risk_level="low", source_reliability=0.6)
        r = self.engine.evaluate(o, estimates=SemanticEstimate(skill_fit=0.5, difficulty=0.5))
        self.assertIn(r.verdict, ("marginal", "poor"))

    def test_poor_low_value(self):
        o = _opp(advertised_amount=10.0, estimated_net_value=5.0, estimated_effort=20.0,
                 scam_risk=0.1, risk_level="low", source_reliability=0.5)
        r = self.engine.evaluate(o, estimates=SemanticEstimate(skill_fit=0.3, difficulty=0.8))
        self.assertIn(r.verdict, ("poor", "marginal"))

    def test_unsafe_high_scam(self):
        o = _opp(advertised_amount=5000.0, estimated_net_value=5000.0,
                 scam_risk=0.95, risk_level="high", source_reliability=0.1)
        r = self.engine.evaluate(o, estimates=SemanticEstimate(skill_fit=0.9))
        self.assertEqual(r.verdict, "unsafe")

    def test_unsafe_high_risk_level(self):
        o = _opp(risk_level="high", scam_risk=0.1, source_reliability=0.8,
                 advertised_amount=200.0, estimated_net_value=180.0)
        r = self.engine.evaluate(o, estimates=SemanticEstimate(skill_fit=0.8))
        self.assertEqual(r.verdict, "unsafe")

    def test_insufficient_information_missing_data(self):
        # Valid listing (has url) but no payment/effort info -> insufficient_information.
        o = _opp(advertised_amount=0.0, estimated_net_value=0.0, estimated_effort=0.0,
                 external_url="https://x.com/j/2")
        r = self.engine.evaluate(o)
        self.assertEqual(r.verdict, "insufficient_information")

    def test_blocked_structurally_invalid(self):
        # No title/desc/external ref -> blocked (hard structural failure).
        o = Opportunity(opportunity_id="b", source="s", platform="P", title="",
                        description="", category="writing", advertised_amount=0.0)
        r = self.engine.evaluate(o)
        self.assertEqual(r.verdict, "blocked")


class TestLLMNotAuthoritative(unittest.TestCase):
    def setUp(self):
        self.engine = OpportunityIntelligenceEngine()

    def test_llm_estimate_never_directly_sets_verdict(self):
        e = OpportunityIntelligenceEngine()
        # An LLM claiming sky-high skill fit on a scammy opp must NOT override unsafe.
        o = _opp(scam_risk=0.99, risk_level="high", source_reliability=0.05,
                 advertised_amount=9999.0, estimated_net_value=9999.0)
        r = e.evaluate(o, estimates=SemanticEstimate(skill_fit=1.0, difficulty=0.0,
                                                     payment_reliability=1.0))
        self.assertEqual(r.verdict, "unsafe")  # deterministic policy wins

    def test_missing_llm_estimate_uses_neutral_defaults(self):
        # No SemanticEstimate at all -> engine still returns a valid result (neutral priors).
        r = self.engine.evaluate(_opp())
        self.assertIsInstance(r, EvaluationResult)
        self.assertIn(r.verdict, ("attractive", "marginal", "poor"))


class TestScenariosSummary(unittest.TestCase):
    """The 7 explicitly-required scenarios, named for auditability."""

    def setUp(self):
        self.engine = OpportunityIntelligenceEngine()

    def test_1_cold_start(self):
        self.assertTrue(self.engine.evaluate(_opp()).cold_start)

    def test_2_strong_history(self):
        import tempfile
        mem = EarningMemory(db_path=tempfile.mktemp(suffix=".db"))
        for _ in range(8):
            mem.update_reputation("Upwork", True, 100.0)
            mem.record_category_outcome("coding", True, 100.0)
            mem.record_task_type_outcome("python", True, 100.0)
        o = _opp(platform="Upwork", category="coding", task_type="python",
                 advertised_amount=300.0, estimated_net_value=280.0, estimated_effort=5.0,
                 scam_risk=0.05, risk_level="low", source_reliability=0.9)
        r = self.engine.evaluate(o, memory=mem,
                                 estimates=SemanticEstimate(skill_fit=0.9, difficulty=0.3))
        self.assertFalse(r.cold_start)
        self.assertIn(r.verdict, ("attractive", "marginal"))

    def test_3_poor_history(self):
        import tempfile
        mem = EarningMemory(db_path=tempfile.mktemp(suffix=".db"))
        for _ in range(8):
            mem.update_reputation("Flaky", False)
            mem.record_category_outcome("writing", False, 0.0)
        o = _opp(platform="Flaky", category="writing", advertised_amount=200.0,
                 estimated_net_value=180.0, estimated_effort=6.0, scam_risk=0.1,
                 risk_level="low", source_reliability=0.5)
        r = self.engine.evaluate(o, memory=mem, estimates=SemanticEstimate(skill_fit=0.8))
        self.assertLess(r.p_success, 0.5)

    def test_4_missing_data(self):
        o = _opp(advertised_amount=0.0, estimated_net_value=0.0, estimated_effort=0.0,
                 external_url="https://x.com/j/3")
        self.assertEqual(self.engine.evaluate(o).verdict, "insufficient_information")

    def test_5_high_risk(self):
        o = _opp(scam_risk=0.95, risk_level="high", source_reliability=0.1)
        self.assertEqual(self.engine.evaluate(o).verdict, "unsafe")

    def test_6_highly_profitable(self):
        o = _opp(advertised_amount=2000.0, estimated_net_value=1800.0, estimated_effort=12.0,
                 scam_risk=0.02, risk_level="low", source_reliability=0.95)
        r = self.engine.evaluate(o, estimates=SemanticEstimate(skill_fit=0.95, difficulty=0.2))
        self.assertEqual(r.verdict, "attractive")
        self.assertGreater(r.expected_value, 0)


class TestPipelineWiring(unittest.TestCase):
    """Integration: EarningPipeline.evaluate() attaches the intelligence verdict."""

    def test_evaluate_attaches_intelligence(self):
        import tempfile
        from earning_pipeline import EarningPipeline

        tmp = tempfile.mkdtemp()
        pipe = EarningPipeline(db_path=os.path.join(tmp, "p.db"),
                               memory_path=os.path.join(tmp, "m.db"),
                               log_fn=lambda *a, **k: None)
        # Build a legacy Opportunity with LLM-style scores already set.
        from earning_pipeline import Opportunity as LegacyOpp
        o = LegacyOpp(id="w1", source="upwork", type="coding", title="Python gig",
                      description="do python", platform="Upwork",
                      payment_type="usd", payment_amount=300.0,
                      payment_currency="USD", estimated_usd_value=280.0,
                      risk_level="low", url="https://up.work/j/w1", status="new")
        o.skill_match = 0.9
        o.effort_score = 0.3
        o.scam_prob = 0.05
        outs = pipe.evaluate([o])
        self.assertEqual(len(outs), 1)
        attached = getattr(outs[0], "intelligence", None)
        self.assertIsNotNone(attached)
        self.assertEqual(attached.opportunity_id, "w1")
        # Verdict is a member of the defined set.
        self.assertIn(attached.verdict, {"attractive", "marginal", "poor",
                                         "unsafe", "insufficient_information", "blocked"})
        # Reasons explain WHY (not just a number).
        self.assertIn("confidence", attached.reasons)


if __name__ == "__main__":
    unittest.main()
