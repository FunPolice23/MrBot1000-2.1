import unittest

from agents.runtime.performance import PerformanceTelemetry


class TestPerformanceTelemetry(unittest.TestCase):
    def test_snapshot_is_provider_independent(self):
        telemetry = PerformanceTelemetry()
        telemetry.record_prompt(120, tokens=30)
        telemetry.record_model_call(100, first_token_latency_ms=25)
        telemetry.record_model_call(50, ok=False)
        telemetry.record_gui_update(3)
        telemetry.mark_startup_complete()

        snapshot = telemetry.snapshot()
        self.assertIsNotNone(snapshot["startup_ms"])
        self.assertEqual(snapshot["model_calls"], 2)
        self.assertEqual(snapshot["model_errors"], 1)
        self.assertEqual(snapshot["prompt_chars"], 120)
        self.assertEqual(snapshot["prompt_tokens"], 30)
        self.assertEqual(snapshot["gui_updates"], 3)
        self.assertEqual(snapshot["avg_model_latency_ms"], 75.0)
        self.assertEqual(snapshot["avg_first_token_latency_ms"], 25.0)

    def test_negative_values_do_not_corrupt_counters(self):
        telemetry = PerformanceTelemetry()
        telemetry.record_prompt(-1, tokens=-2)
        telemetry.record_gui_update(-3)
        snapshot = telemetry.snapshot()
        self.assertEqual(snapshot["prompt_chars"], 0)
        self.assertEqual(snapshot["prompt_tokens"], 0)
        self.assertEqual(snapshot["gui_updates"], 0)


if __name__ == "__main__":
    unittest.main()
