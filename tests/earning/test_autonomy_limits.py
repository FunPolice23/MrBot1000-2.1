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
            time.sleep(0.01)

        loop._stage_discovered = slow_stage
        result = loop.run(SimpleNamespace(id="opp-timeout"))
        self.assertEqual(result.decision, "failed")
        self.assertIn("exceeded", result.decision_reason.lower())


if __name__ == "__main__":
    unittest.main()
