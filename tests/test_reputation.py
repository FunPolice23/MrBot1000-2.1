"""Reputation must distinguish recorded work from verified earnings."""

import tempfile
import unittest

from agents.reputation import ReputationTracker, WorkRecord


def _record(task_id, platform, payout, verified=False, costs=0.0):
    return WorkRecord(
        task_id=task_id,
        platform=platform,
        title=task_id,
        description="",
        category="test",
        status="completed",
        payout=payout,
        costs=costs,
        verified=verified,
    )


class TestReputationVerification(unittest.TestCase):
    def test_unverified_completion_is_not_verified_earnings(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker = ReputationTracker(f"{folder}/reputation.json")
            tracker.record_work(_record("unverified", "platform", 500.0))
            metrics = tracker.get_overall_metrics()

        self.assertEqual(metrics["recorded_earnings"], 500.0)
        self.assertEqual(metrics["verified_earnings"], 0.0)
        self.assertEqual(metrics["unverified_completed_records"], 1)

    def test_verified_platform_metrics_are_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker = ReputationTracker(f"{folder}/reputation.json")
            tracker.record_work(_record("unverified", "platform", 500.0))
            tracker.record_work(_record("verified", "platform", 25.0, verified=True))
            platform = tracker.get_platform_metrics("platform")

        self.assertEqual(platform.total_earnings, 525.0)
        self.assertEqual(platform.verified_earnings, 25.0)

    def test_unverified_platform_does_not_win_verified_ranking(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker = ReputationTracker(f"{folder}/reputation.json")
            tracker.record_work(_record("unverified", "unverified-platform", 1000.0))
            tracker.record_work(_record("verified", "verified-platform", 10.0, verified=True))

        self.assertEqual(tracker.get_portfolio()["top_platform"], "verified-platform")


if __name__ == "__main__":
    unittest.main()