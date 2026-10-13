import os
import unittest
import time
from types import SimpleNamespace
from unittest.mock import patch

from agents.services.autonomous_loop import AutonomousLoop


class TestAutonomyLimits(unittest.TestCase):
    def test_concurrency_limit_blocks_second_run(self):
        with patch.dict(os.environ, {"MRBOT_AUTONOMY_MAX_CONCURRENT": "1"}):
            loop = AutonomousLoop(SimpleNamespace())
        self.assertTrue(loop._run_slots.acquire(blocking=False))
        try:
            result = loop.run(SimpleNamespace(id="opp-limit"))
            self.assertEqual(result.decision, "blocked")
            self.assertIn("concurrency", result.decision_reason)
        finally:
            loop._run_slots.release()

    def test_cancelled_run_is_terminal_failure(self):
        loop = AutonomousLoop(SimpleNamespace())
        loop.cancel("opp-cancel")
        result = loop.run(SimpleNamespace(id="opp-cancel"))
        self.assertEqual(result.decision, "failed")
        self.assertIn("cancelled", result.decision_reason.lower())

    def test_run_duration_limit_is_enforced_between_stages(self):
        with patch.dict(os.environ, {"MRBOT_AUTONOMY_MAX_RUN_SECONDS": "0.001"}):
            loop = AutonomousLoop(SimpleNamespace())
        original = loop._stage_discovered

        def slow_stage(*args):
            original(*args)
            # Windows' time.monotonic() has ~15.6 ms granularity, so a 10 ms
            # sleep sometimes reads back as 0 elapsed and the limit check
            # passes — the test then failed on the NEXT unrelated stage. Sleep
            # past at least one full tick so the measurement is deterministic.
            time.sleep(0.05)

        loop._stage_discovered = slow_stage
        result = loop.run(SimpleNamespace(id="opp-timeout"))
        self.assertEqual(result.decision, "failed")
        self.assertIn("exceeded", result.decision_reason.lower())

    def test_portfolio_less_pipeline_does_not_crash_prioritize(self):
        # v2.1.55 (ARCH-ENG-058): _stage_prioritize called
        # self.portfolio.load_all() unguarded. Every other portfolio stage
        # checks `is not None`; this one turned a portfolio-less pipeline into
        # a generic "Loop error: 'NoneType' object has no attribute
        # 'load_all'" and aborted the run. Drive a full run with a pipeline
        # that has no portfolio at all.
        loop = AutonomousLoop(SimpleNamespace())
        result = loop.run(SimpleNamespace(id="opp-no-portfolio"))
        stage_names = [s.stage for s in result.stages]
        self.assertIn("prioritize", stage_names)
        self.assertNotIn("load_all", " ".join(result.errors))


if __name__ == "__main__":
    unittest.main()
