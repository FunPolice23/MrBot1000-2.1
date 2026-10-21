"""ARCH-ENG-155 — the autonomous loop's economics stage could not reject anything.

`_stage_check_economics` computed `estimated_hourly` and then discarded it: it
appended a StageResult with status COMPLETED and returned NOTHING, whatever the
economics were. `_run` called it as a bare statement, so the return value had
nowhere to go. Meanwhile `agents/earning/economic_policy.py` — a complete,
tested deterministic gate layer (net value, risk-adjusted hourly return,
staleness, confidence, risk penalty, payment delay, productive hours, autonomy
level, and the legality/capability/identity/evidence gates) — was imported by
NOTHING in production: a repo-wide grep for an import of `economic_policy`
outside tests/ returned 0 hits, so those gates ran only in their own unit tests.

OBSERVED pre-fix, by execution: an opportunity with advertised_amount=5,
estimated_net_value=-500, estimated_effort=200 produced
`estimated_hourly: -2.5` and status `completed`, and the loop went on to plan,
execute and submit work that loses money on every axis.

These tests fail with the stage reverted to the COMPLETED-always form and pass
with the gate wired.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from agents.earning.economic_policy import (
    DecisionAction,
    DecisionPolicy,
    EconomicPrediction,
    SETTINGS_KEY,
    evaluate_prediction,
    load_policy,
)
from agents.services.autonomous_loop import AutonomousLoop, StageStatus

# Import the production doubles rather than re-declaring them, so these tests
# exercise the SAME opportunity shape the loop's own suite uses. (A test double
# that disagrees with the caller's bug is exactly how ARCH-ENG-147 shipped
# green: `FakeTaskExecutor.run(task)` mirrored the wrong method name.)
from tests.earning.test_autonomous_loop import FakeOpp, FakePipeline


class IsolatedSettingsMixin:
    """Point the policy loader at a throwaway settings file.

    Mirrors the `MRBOT_DEVICE_SETTINGS_PATH` convention used by
    `device_registry`: without this the loader reads the operator's LIVE
    settings.json, so a test could pass locally and fail on a fresh clone.
    """

    def setUp(self) -> None:
        super().setUp()
        self._path = os.path.join(
            tempfile.gettempdir(), f"mrbot_155_{os.getpid()}_{id(self)}.json")
        with open(self._path, "w", encoding="utf-8") as f:
            f.write("{}")
        self._prev = os.environ.get("MRBOT_DEVICE_SETTINGS_PATH")
        os.environ["MRBOT_DEVICE_SETTINGS_PATH"] = self._path

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("MRBOT_DEVICE_SETTINGS_PATH", None)
        else:
            os.environ["MRBOT_DEVICE_SETTINGS_PATH"] = self._prev
        try:
            os.unlink(self._path)
        except OSError:
            pass
        super().tearDown()

    def _write_settings(self, block: dict) -> None:
        import json
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump({SETTINGS_KEY: block}, f)


class TestEconomicPolicyGate(IsolatedSettingsMixin, unittest.TestCase):
    """The loop must refuse work the deterministic policy declines."""

    def _run(self, opp):
        pipeline = FakePipeline()
        loop = AutonomousLoop(pipeline=pipeline)
        return loop.run(opp), loop

    def test_negative_net_value_opportunity_never_reaches_execute(self):
        """The exact opportunity that used to sail through to execute."""
        result, _ = self._run(
            FakeOpp(advertised_amount=5, estimated_net_value=-500,
                    estimated_effort=200))
        self.assertEqual(result.decision, "reject")
        self.assertNotIn("execute", [s.stage for s in result.stages])
        self.assertFalse(result.success)

    def test_reject_reason_names_the_policy_verdict(self):
        """A reject must say WHY, not just that it happened."""
        result, _ = self._run(
            FakeOpp(advertised_amount=5, estimated_net_value=-500,
                    estimated_effort=200))
        self.assertIn("expected_net_value_below_policy", result.decision_reason)

    def test_stage_status_is_failed_not_completed_when_declined(self):
        pipeline = FakePipeline()
        loop = AutonomousLoop(pipeline=pipeline)
        from agents.evidence.provenance import FactStore
        from types import SimpleNamespace
        result = SimpleNamespace(stages=[], errors=[])
        loop._stage_check_economics(
            result, FakeOpp(advertised_amount=5, estimated_net_value=-500,
                            estimated_effort=200), FactStore("opp-x"))
        self.assertEqual(result.stages[-1].status, StageStatus.FAILED)
        self.assertEqual(result.stages[-1].data["policy_action"], "defer")

    def test_profitable_opportunity_still_passes_the_gate(self):
        """The gate must not reject everything — a good opp must proceed."""
        pipeline = FakePipeline()
        loop = AutonomousLoop(pipeline=pipeline)
        from agents.evidence.provenance import FactStore
        from types import SimpleNamespace
        result = SimpleNamespace(stages=[], errors=[])
        loop._stage_check_economics(
            result, FakeOpp(advertised_amount=500, estimated_net_value=400,
                            estimated_effort=2, risk_level="low"),
            FactStore("opp-good"))
        self.assertEqual(result.stages[-1].status, StageStatus.COMPLETED)
        self.assertEqual(result.stages[-1].data["policy_action"], "select")

    def test_policy_net_value_reproduces_the_opportunity_estimate(self):
        """The policy must decide on the estimate the loop already trusts.

        `EconomicPrediction.expected_net_value` is DERIVED from payout and
        probabilities. If those were left at their 0.0 defaults the derived
        value would be -startup_cost regardless of the opportunity's own
        estimate, so every opportunity would be declined for the wrong reason
        (this is exactly the shape of bug this test caught mid-implementation).
        """
        pipeline = FakePipeline()
        loop = AutonomousLoop(pipeline=pipeline)
        from agents.evidence.provenance import FactStore
        from types import SimpleNamespace
        result = SimpleNamespace(stages=[], errors=[])
        loop._stage_check_economics(
            result, FakeOpp(advertised_amount=5, estimated_net_value=-500,
                            estimated_effort=200), FactStore("opp-x"))
        self.assertAlmostEqual(
            result.stages[-1].data["policy_expected_net_value"], -500.0)

    def test_policy_error_fails_open_and_never_halts_the_loop(self):
        """A policy that cannot be evaluated must not stop the autonomous loop.

        The genuine fail-open path is a prediction the policy layer REJECTS,
        not a broken settings file: `load_policy` never raises (corrupt
        settings fall back to defaults, which still decline this opportunity —
        verified by `test_corrupt_settings_still_declines`). Here the
        opportunity carries an illegal value that
        `EconomicPrediction.__post_init__` refuses, so the gate cannot be
        computed at all and the stage must keep the pre-existing COMPLETED
        behaviour rather than block on an error it invented.
        """
        pipeline = FakePipeline()
        loop = AutonomousLoop(pipeline=pipeline)
        from agents.evidence.provenance import FactStore
        from types import SimpleNamespace
        result = SimpleNamespace(stages=[], errors=[])
        # confidence > 1.0 is illegal for EconomicPrediction -> raises -> caught.
        # FakeOpp tolerates arbitrary attributes via __getattr__ but takes no
        # extra kwargs, so the illegal value is set on the instance.
        bad = FakeOpp(advertised_amount=5, estimated_net_value=-500,
                      estimated_effort=200)
        bad.confidence = 5.0
        loop._stage_check_economics(result, bad, FactStore("opp-x"))
        self.assertEqual(result.stages[-1].status, StageStatus.COMPLETED)
        self.assertTrue(
            any("Economic policy error" in e for e in result.errors),
            "the swallowed error must still be visible on the result")

    def test_corrupt_settings_still_declines(self):
        """Corrupt settings must NOT disable the gate.

        `load_policy` swallows a parse failure and returns the DEFAULTS, so a
        broken settings.json degrades to the shipped thresholds rather than
        switching the gate off — the opportunity is still evaluated.
        """
        pipeline = FakePipeline()
        loop = AutonomousLoop(pipeline=pipeline)
        from agents.evidence.provenance import FactStore
        from types import SimpleNamespace
        with open(self._path, "w", encoding="utf-8") as f:
            f.write("{not json")
        result = SimpleNamespace(stages=[], errors=[])
        loop._stage_check_economics(
            result, FakeOpp(advertised_amount=5, estimated_net_value=-500,
                            estimated_effort=200), FactStore("opp-x"))
        self.assertEqual(result.stages[-1].status, StageStatus.FAILED)


class TestPolicyLoading(IsolatedSettingsMixin, unittest.TestCase):
    """`load_policy` must read settings.json safely and never raise."""

    def test_absent_settings_yields_defaults(self):
        policy = load_policy()
        self.assertEqual(policy.minimum_expected_net_value,
                         DecisionPolicy().minimum_expected_net_value)

    def test_settings_threshold_is_applied(self):
        self._write_settings({"minimum_expected_net_value": 25.0})
        self.assertEqual(load_policy().minimum_expected_net_value, 25.0)

    def test_out_of_range_setting_falls_back_to_default(self):
        """A bad value must not invert a gate — it must keep the default."""
        self._write_settings({"minimum_confidence": 5.0})  # > 1.0, illegal
        self.assertEqual(
            load_policy().minimum_confidence, DecisionPolicy().minimum_confidence)

    def test_non_numeric_setting_is_ignored(self):
        self._write_settings({"minimum_expected_net_value": "lots"})
        self.assertEqual(
            load_policy().minimum_expected_net_value,
            DecisionPolicy().minimum_expected_net_value)

    def test_boolean_is_not_treated_as_a_number(self):
        """bool is a subclass of int in Python; True must not become 1.0."""
        self._write_settings({"minimum_expected_net_value": True})
        self.assertEqual(
            load_policy().minimum_expected_net_value,
            DecisionPolicy().minimum_expected_net_value)

    def test_corrupt_settings_yields_defaults_without_raising(self):
        with open(self._path, "w", encoding="utf-8") as f:
            f.write("{{{")
        self.assertIsInstance(load_policy(), DecisionPolicy)

    def test_missing_file_yields_defaults_without_raising(self):
        os.unlink(self._path)
        self.assertIsInstance(load_policy(), DecisionPolicy)

    def test_unknown_key_is_not_silently_accepted(self):
        """A typo'd threshold must not configure a field that does not exist."""
        self._write_settings({"minimum_expectd_net_value": 25.0})
        # It is ignored, so the default holds — the typo cannot change behaviour.
        self.assertEqual(
            load_policy().minimum_expected_net_value,
            DecisionPolicy().minimum_expected_net_value)

    def test_operator_threshold_actually_changes_the_verdict(self):
        """End-to-end: a threshold set in settings.json changes the decision."""
        self._write_settings({"minimum_risk_adjusted_hourly_return": 500.0})
        policy = load_policy()
        prediction = EconomicPrediction(
            opportunity_id="o", payout_amount=100.0,
            probability_of_success=1.0, probability_of_payment=1.0,
            startup_cost=10.0, active_work_hours=2.0)
        result = evaluate_prediction(prediction, policy)
        self.assertEqual(result.action, DecisionAction.DEFER)


if __name__ == "__main__":
    unittest.main()
