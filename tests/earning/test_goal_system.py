"""tests/test_goal_system.py — Unit tests for GoalTracker SQLite persistence.

ARCH-ENG-244 updated for the LIVE wiring: the unguarded `add_earnings` is
gone (BF-02 — add_evidence's verified-guard is the only credit path), and
process_event reads the production earning-event contract
(event_type="earning", details.revenue/action/platform — BF-03's real
stream, not the invented vocabulary).
"""
import tempfile
import os
import unittest

from agents.earning.goal_system import (
    GoalTracker, Goal, GoalStatus, GoalPath, EvidenceRow,
)


class TestGoalTrackerCRUD(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.tracker = GoalTracker(db_path=self.db)

    def tearDown(self):
        try:
            os.unlink(self.db)
        except PermissionError:
            pass

    def test_create_and_get(self):
        g = Goal(id="g1", title="Test Goal", target_usd=100.0, path=GoalPath.FREELANCE.value)
        self.tracker.create(g)
        got = self.tracker.get("g1")
        self.assertIsNotNone(got)
        self.assertEqual(got.title, "Test Goal")
        self.assertEqual(got.target_usd, 100.0)
        self.assertEqual(got.path, GoalPath.FREELANCE.value)

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.tracker.get("nonexistent"))

    def test_list_active(self):
        g1 = Goal(id="g1", title="Active Goal", target_usd=50.0, path=GoalPath.FREELANCE.value)
        g2 = Goal(id="g2", title="Completed Goal", target_usd=30.0, path=GoalPath.MICROTASK.value)
        self.tracker.create(g1)
        self.tracker.create(g2)
        active = self.tracker.list_active()
        self.assertEqual(len(active), 2)

    def test_list_all(self):
        g1 = Goal(id="g1", title="Goal 1", target_usd=10.0)
        g2 = Goal(id="g2", title="Goal 2", target_usd=20.0)
        self.tracker.create(g1)
        self.tracker.create(g2)
        all_goals = self.tracker.list_all()
        self.assertEqual(len(all_goals), 2)

    def test_update(self):
        g = Goal(id="g1", title="Original", target_usd=100.0)
        self.tracker.create(g)
        g.title = "Updated"
        self.tracker.update(g)
        got = self.tracker.get("g1")
        self.assertEqual(got.title, "Updated")

    def test_delete(self):
        g = Goal(id="g1", title="To Delete", target_usd=10.0)
        self.tracker.create(g)
        self.tracker.delete("g1")
        self.assertIsNone(self.tracker.get("g1"))
        self.assertEqual(self.tracker.list_active(), [])


class TestGoalTrackerEvidence(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.tracker = GoalTracker(db_path=self.db)
        self.goal = Goal(id="g1", title="Test", target_usd=100.0)
        self.tracker.create(self.goal)

    def tearDown(self):
        try:
            os.unlink(self.db)
        except PermissionError:
            pass

    def test_add_evidence_verified_updates_current_usd(self):
        e = EvidenceRow(goal_id="g1", type="payment_received", amount_usd=25.0, verified=True)
        self.tracker.add_evidence("g1", e)
        g = self.tracker.get("g1")
        self.assertEqual(g.current_usd, 25.0)

    def test_add_evidence_unverified_does_not_update(self):
        e = EvidenceRow(goal_id="g1", type="proposal_sent", amount_usd=25.0, verified=False)
        self.tracker.add_evidence("g1", e)
        g = self.tracker.get("g1")
        self.assertEqual(g.current_usd, 0.0)

    def test_list_evidence(self):
        e1 = EvidenceRow(goal_id="g1", type="payment_received", amount_usd=10.0, verified=True)
        e2 = EvidenceRow(goal_id="g1", type="proposal_sent", amount_usd=0.0, verified=False)
        self.tracker.add_evidence("g1", e1)
        self.tracker.add_evidence("g1", e2)
        ev = self.tracker.list_evidence("g1")
        self.assertEqual(len(ev), 2)


class TestGoalTrackerProgress(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.tracker = GoalTracker(db_path=self.db)
        self.goal = Goal(id="g1", title="Test", target_usd=100.0, path=GoalPath.FREELANCE.value)
        self.tracker.create(self.goal)

    def tearDown(self):
        try:
            os.unlink(self.db)
        except PermissionError:
            pass

    def test_the_unguarded_credit_path_is_gone(self):
        """ARCH-ENG-244 (BF-02): add_earnings claimed "verified" in its
        docstring while crediting a bare SQL increment; the single credit
        path is now add_evidence's verified-guard."""
        self.assertFalse(hasattr(self.tracker, "add_earnings"))

    def test_check_completion_partial_stays_active(self):
        # Credits flow only through add_evidence's verified-guard now.
        self.tracker.add_evidence(
            "g1", EvidenceRow(type="payment_received", amount_usd=50.0,
                              verified=True))
        self.tracker.check_completion("g1")
        g = self.tracker.get("g1")
        self.assertEqual(g.status, GoalStatus.ACTIVE.value)

    def test_check_completion_complete(self):
        self.tracker.add_evidence(
            "g1", EvidenceRow(type="payment_received", amount_usd=100.0,
                              verified=True))
        self.tracker.check_completion("g1")
        g = self.tracker.get("g1")
        self.assertEqual(g.status, GoalStatus.COMPLETED.value)
        self.assertIsNotNone(g.completed_at)

    def test_summary(self):
        g1 = Goal(id="s1", title="Goal 1", target_usd=100.0, path=GoalPath.FREELANCE.value)
        g2 = Goal(id="s2", title="Goal 2", target_usd=50.0, path=GoalPath.MICROTASK.value)
        self.tracker.create(g1)
        self.tracker.create(g2)
        self.tracker.add_evidence(
            "s1", EvidenceRow(type="payment_received", amount_usd=50.0,
                              verified=True))
        s = self.tracker.summary()
        self.assertEqual(s["total_goals"], 3)
        self.assertEqual(s["active_goals"], 3)
        self.assertEqual(s["completed_goals"], 0)
        self.assertEqual(s["total_earned"], 50.0)
        self.assertEqual(s["total_target"], 250.0)
        self.assertAlmostEqual(s["overall_progress"], 20.0, delta=0.1)


class TestGoalTrackerEvents(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.tracker = GoalTracker(db_path=self.db)

    def tearDown(self):
        try:
            os.unlink(self.db)
        except PermissionError:
            pass

    def _earning_event(self, *, action="finalized:paid", revenue=30.0,
                       platform="upwork", success=True, goal_id=None,
                       tags=None):
        """A REAL post-ARCH-ENG-243 earning event, exactly as the pipeline
        emits it (revenue = the lifecycle's verified-effective value)."""
        from types import SimpleNamespace
        details = {"action": action, "revenue": revenue, "cost": 0.02,
                   "platform": platform, "success": success}
        if goal_id is not None:
            details["goal_id"] = goal_id
        return SimpleNamespace(
            event_type="earning", source="llm_cost",
            details=details, tags=tags or ["earning", action])

    def test_process_event_goal_bound_paid_credits(self):
        g = Goal(id="g1", title="Test", target_usd=100.0)
        self.tracker.create(g)

        self.tracker.process_event(
            self._earning_event(goal_id="g1", revenue=30.0))
        got = self.tracker.get("g1")
        self.assertEqual(got.current_usd, 30.0,
                         "a VERIFIED paid finalize credits its bound goal")
        rows = self.tracker.list_evidence("g1")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].verified)
        self.assertEqual(rows[0].amount_usd, 30.0)

    def test_process_event_goal_bound_nonpaid_records_but_does_not_credit(self):
        """A non-paid effective state is RECORDED as evidence and never
        moves money — verified=False rows cannot pass the guard."""
        g = Goal(id="g1", title="Test", target_usd=100.0)
        self.tracker.create(g)

        self.tracker.process_event(
            self._earning_event(goal_id="g1", action="finalized:completed",
                                revenue=25.0))
        got = self.tracker.get("g1")
        self.assertEqual(got.current_usd, 0.0)
        rows = self.tracker.list_evidence("g1")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].verified)

    def test_process_event_verified_down_payment_cannot_credit(self):
        """The lifecycle wrote revenue 0 for a payment it could not verify;
        a paid-state event with revenue 0 cannot credit a cent."""
        g = Goal(id="g1", title="Test", target_usd=100.0)
        self.tracker.create(g)

        self.tracker.process_event(
            self._earning_event(goal_id="g1", revenue=0.0))
        got = self.tracker.get("g1")
        self.assertEqual(got.current_usd, 0.0)

    def test_process_event_platform_binding_credits_declared_goal(self):
        """Operator-declared binding: the goal's metadata.platforms names
        the platforms whose VERIFIED payouts count toward it."""
        g = Goal(id="g1", title="Test", target_usd=100.0,
                 metadata={"platforms": ["Upwork"]})
        self.tracker.create(g)

        self.tracker.process_event(
            self._earning_event(revenue=40.0, platform="upwork"))
        got = self.tracker.get("g1")
        self.assertEqual(got.current_usd, 40.0,
                         "platform match is case-insensitive")

    def test_process_event_without_binding_never_credits(self):
        """No explicit and no declared binding: the tracker does NOT guess
        what an unbound amount belongs to (the removed auto-match did)."""
        g = Goal(id="g1", title="Test", target_usd=100.0,
                 path=GoalPath.FREELANCE.value)  # a path alone is not a claim
        self.tracker.create(g)

        self.tracker.process_event(
            self._earning_event(revenue=25.0, platform="upwork"))
        got = self.tracker.get("g1")
        self.assertEqual(got.current_usd, 0.0)
        self.assertEqual(self.tracker.list_evidence("g1"), [])

    def test_process_event_wrong_platform_does_not_credit(self):
        g = Goal(id="g1", title="Test", target_usd=100.0,
                 metadata={"platforms": ["prolific"]})
        self.tracker.create(g)

        self.tracker.process_event(
            self._earning_event(revenue=25.0, platform="upwork"))
        self.assertEqual(self.tracker.get("g1").current_usd, 0.0)

    def test_process_event_inactive_goal_is_not_credited(self):
        g = Goal(id="g1", title="Test", target_usd=100.0,
                 status=GoalStatus.PAUSED.value,
                 metadata={"platforms": ["upwork"]})
        self.tracker.create(g)

        self.tracker.process_event(
            self._earning_event(revenue=25.0, platform="upwork"))
        self.assertEqual(self.tracker.get("g1").current_usd, 0.0,
                         "list_active() excludes paused goals")

    def test_process_event_unknown_ignored(self):
        # Should not raise
        class FakeEvent:
            event_type = "unknown.event"
            source = ""
            details = {}
            tags = []

        self.tracker.process_event(FakeEvent())
        # No goals created, no errors
        self.assertEqual(self.tracker.summary()["total_goals"], 0)


class TestGoalModel(unittest.TestCase):
    def test_goal_progress_pct(self):
        g = Goal(id="g1", target_usd=100.0, current_usd=25.0)
        self.assertAlmostEqual(g.progress_pct, 25.0)

    def test_goal_progress_pct_zero_target(self):
        g = Goal(id="g1", target_usd=0.0, current_usd=0.0)
        self.assertEqual(g.progress_pct, 0.0)

    def test_goal_progress_pct_capped(self):
        g = Goal(id="g1", target_usd=100.0, current_usd=150.0)
        self.assertAlmostEqual(g.progress_pct, 100.0)

    def test_goal_to_dict_roundtrip(self):
        g = Goal(id="g1", title="Test", target_usd=50.0, path=GoalPath.CRYPTO.value,
                 status=GoalStatus.ACTIVE.value, budget_usd=10.0, tags=["test"])
        d = g.to_dict()
        g2 = Goal.from_dict(d)
        self.assertEqual(g2.id, g.id)
        self.assertEqual(g2.title, g.title)
        self.assertEqual(g2.target_usd, g.target_usd)
        self.assertEqual(g2.path, g.path)
        self.assertEqual(g2.status, g.status)
        self.assertEqual(g2.tags, g.tags)

    def test_evidence_to_dict_roundtrip(self):
        e = EvidenceRow(id="e1", goal_id="g1", type="payment_received", amount_usd=25.0,
                        source="upwork", verified=True)
        d = e.to_dict()
        e2 = EvidenceRow.from_dict(d)
        self.assertEqual(e2.id, e.id)
        self.assertEqual(e2.goal_id, e.goal_id)
        self.assertEqual(e2.amount_usd, e.amount_usd)
        self.assertEqual(e2.verified, e.verified)


if __name__ == "__main__":
    unittest.main()
