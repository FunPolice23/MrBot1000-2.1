import unittest

from agents.earning.economic_policy import (
    DecisionAction,
    DecisionPolicy,
    EconomicPrediction,
    evaluate_prediction,
)


class TestEconomicPrediction(unittest.TestCase):
    def test_expected_net_value_keeps_costs_and_waiting_time_separate(self):
        prediction = EconomicPrediction(
            opportunity_id="op-1",
            payout_amount=100.0,
            probability_of_success=0.8,
            probability_of_payment=0.9,
            startup_cost=2.0,
            model_cost=3.0,
            api_cost=1.0,
            transaction_fees=4.0,
            expected_failure_cost=5.0,
            expected_rework_cost=6.0,
            active_work_hours=1.0,
            research_hours=0.5,
            human_hours=0.25,
            expected_rework_hours=0.25,
            elapsed_wait_hours=48.0,
            time_to_payment_hours=72.0,
        )
        self.assertAlmostEqual(prediction.expected_net_value, 51.0)
        self.assertAlmostEqual(prediction.productive_hours, 2.0)
        self.assertAlmostEqual(prediction.expected_hourly_return, 25.5)
        self.assertEqual(prediction.elapsed_wait_hours, 48.0)

    def test_invalid_probability_is_rejected(self):
        with self.assertRaises(ValueError):
            EconomicPrediction(
                opportunity_id="op-1",
                probability_of_success=1.1,
            )


class TestDecisionPolicy(unittest.TestCase):
    def setUp(self):
        self.prediction = EconomicPrediction(
            opportunity_id="op-1",
            payout_amount=100.0,
            probability_of_success=0.8,
            probability_of_payment=0.9,
            active_work_hours=2.0,
            confidence=0.8,
            freshness_timestamp=100.0,
        )

    def test_selects_when_policy_gates_pass(self):
        result = evaluate_prediction(
            self.prediction,
            DecisionPolicy(
                policy_version="policy-2",
                minimum_expected_net_value=50.0,
                minimum_risk_adjusted_hourly_return=20.0,
            ),
            now=120.0,
        )
        self.assertEqual(result.action, DecisionAction.SELECT)
        self.assertEqual(result.policy_version, "policy-2")

    def test_defers_when_economic_threshold_fails(self):
        result = evaluate_prediction(
            self.prediction,
            DecisionPolicy(minimum_expected_net_value=90.0),
            now=120.0,
        )
        self.assertEqual(result.action, DecisionAction.DEFER)
        self.assertIn("expected_net_value_below_policy", result.reasons)

    def test_requests_research_for_low_confidence_only(self):
        prediction = EconomicPrediction(
            opportunity_id="op-2",
            payout_amount=100.0,
            probability_of_success=0.8,
            probability_of_payment=0.9,
            active_work_hours=2.0,
            confidence=0.2,
            freshness_timestamp=100.0,
        )
        result = evaluate_prediction(
            prediction,
            DecisionPolicy(minimum_confidence=0.5),
            now=120.0,
        )
        self.assertEqual(result.action, DecisionAction.RESEARCH_MORE)

    def test_rejects_stale_or_unsafe_prediction(self):
        result = evaluate_prediction(
            self.prediction,
            DecisionPolicy(
                maximum_prediction_age_seconds=10.0,
                maximum_risk_penalty=0.1,
            ),
            now=120.0,
            gates={"legality": False},
        )
        self.assertEqual(result.action, DecisionAction.REJECT)
        self.assertIn("prediction_stale", result.reasons)
        self.assertIn("legality_gate_failed", result.reasons)

    def test_rejects_insufficient_autonomy(self):
        result = evaluate_prediction(
            self.prediction,
            DecisionPolicy(required_autonomy_level=2),
            now=120.0,
            available_autonomy_level=1,
        )
        self.assertEqual(result.action, DecisionAction.REJECT)
        self.assertIn("autonomy_level_below_policy", result.reasons)


if __name__ == "__main__":
    unittest.main()
