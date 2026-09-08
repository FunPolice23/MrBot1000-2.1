"""tests/test_opportunity_portfolio.py — Opportunity Portfolio & Work Queue (v2.0.36h)."""

import os
import tempfile
import time
import unittest
from dataclasses import asdict

from agents.opportunity_portfolio import (
    PortfolioEntry,
    WorkStatus,
    OpportunityPortfolio,
    IllegalTransitionError,
    QueuePolicy,
    CapacityConfig,
    WorkQueue,
    resolve_next_action,
    apply_next,
)
from agents.opportunity_models import Opportunity


def _sample_entry(opportunity_id="opp-1", work_status=WorkStatus.NEW, **overrides):
    now = time.time()
    data = dict(
        opportunity_id=opportunity_id,
        opportunity_ref={"title": "Python automation", "source": "upwork"},
        work_status=work_status,
        priority=0.5,
        expected_value=100.0,
        expected_hourly_value=25.0,
        deadline=now + 86400 * 3,
        confidence=0.6,
        risk=0.3,
        effort=4.0,
        next_action="",
        waiting_reason="",
        evidence_status="none",
        payment_status="unpaid",
        blocked_reason="",
        platform="upwork",
        category="coding",
        task_type="automation",
        skill_fit=0.7,
        policy_score=0.0,
        added_at=now,
        updated_at=now,
        policy_version="v1",
    )
    data.update(overrides)
    return PortfolioEntry(**data)


class TestPersistenceAndRecovery(unittest.TestCase):
    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "portfolio.db")

    def test_add_get_list(self):
        p = OpportunityPortfolio(db_path=self.db_path)
        e = _sample_entry()
        p.add(e)
        got = p.get("opp-1")
        self.assertIsNotNone(got)
        self.assertEqual(got.opportunity_id, "opp-1")
        self.assertEqual(got.work_status, WorkStatus.NEW)
        new_entries = p.list_work(WorkStatus.NEW)
        self.assertEqual(len(new_entries), 1)
        self.assertEqual(new_entries[0].opportunity_id, "opp-1")

    def test_transition_updates_status_and_timestamp(self):
        p = OpportunityPortfolio(db_path=self.db_path)
        e = _sample_entry()
        p.add(e)
        old_ts = e.updated_at
        time.sleep(0.01)
        p.transition_work_status("opp-1", WorkStatus.EVALUATING)
        got = p.get("opp-1")
        self.assertEqual(got.work_status, WorkStatus.EVALUATING)
        self.assertGreater(got.updated_at, old_ts)

    def test_restart_recovery(self):
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(_sample_entry("opp-1", WorkStatus.NEW))
        p.add(_sample_entry("opp-2", WorkStatus.READY))
        p.add(_sample_entry("opp-3", WorkStatus.IN_PROGRESS))
        counts_before = p.count_by_status()
        # Close (drop reference) and reopen SAME db_path
        del p
        p2 = OpportunityPortfolio(db_path=self.db_path)
        all_entries = p2.list_all()
        self.assertEqual(len(all_entries), 3)
        by_id = {e.opportunity_id: e for e in all_entries}
        self.assertEqual(by_id["opp-1"].work_status, WorkStatus.NEW)
        self.assertEqual(by_id["opp-2"].work_status, WorkStatus.READY)
        self.assertEqual(by_id["opp-3"].work_status, WorkStatus.IN_PROGRESS)
        self.assertEqual(p2.count_by_status(), counts_before)

    def test_remove(self):
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(_sample_entry())
        self.assertIsNotNone(p.get("opp-1"))
        p.remove("opp-1")
        self.assertIsNone(p.get("opp-1"))
        self.assertEqual(p.list_all(), [])


class FakeLifecycle:
    """Minimal lifecycle stub that exposes _ALLOWED_TRANSITIONS and mark_final_outcome."""
    _ALLOWED_TRANSITIONS = {
        "discovered": {"researched", "queued", "failed"},
        "researched": {"queued", "failed"},
        "queued": {"applied", "rejected", "failed"},
        "applied": {"in_progress", "rejected", "failed"},
        "in_progress": {"submitted", "failed"},
        "submitted": {"paid", "failed"},
        "paid": set(),
        "failed": set(),
        "rejected": set(),
    }

    def __init__(self):
        self.states = {}

    def get_state(self, opportunity_id):
        return {"current_stage": self.states.get(opportunity_id, "discovered")}

    def mark_final_outcome(self, opportunity_id, *, outcome_state, **kwargs):
        current = self.states.get(opportunity_id, "discovered")
        allowed = self._ALLOWED_TRANSITIONS.get(current, set())
        if outcome_state not in allowed:
            raise ValueError(f"Invalid lifecycle transition: {current} → {outcome_state}")
        self.states[opportunity_id] = outcome_state

    def mark_paid_verified(self, opportunity_id, amount=0.0):
        self.mark_final_outcome(opportunity_id, outcome_state="paid")

    def mark_failed(self, opportunity_id, note=""):
        self.mark_final_outcome(opportunity_id, outcome_state="failed")

    def mark_rejected(self, opportunity_id, reason=""):
        self.mark_final_outcome(opportunity_id, outcome_state="rejected")


class TestWorkStatusMachine(unittest.TestCase):
    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "portfolio.db")

    def test_valid_transition_allowed(self):
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(_sample_entry())
        p.transition_work_status("opp-1", WorkStatus.EVALUATING)
        self.assertEqual(p.get("opp-1").work_status, WorkStatus.EVALUATING)

    def test_invalid_transition_rejected(self):
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(_sample_entry())
        with self.assertRaises(IllegalTransitionError):
            p.transition_work_status("opp-1", WorkStatus.PAID)

    def test_lifecycle_authoritative(self):
        """Lifecycle is still authority: an illegal lifecycle transition is rejected."""
        lifecycle = FakeLifecycle()
        lifecycle.states["opp-1"] = "discovered"
        p = OpportunityPortfolio(db_path=self.db_path, lifecycle=lifecycle)
        p.add(_sample_entry(work_status=WorkStatus.NEW))
        # NEW→IN_PROGRESS implies discovered→in_progress which lifecycle disallows
        with self.assertRaises(IllegalTransitionError):
            p.transition_work_status("opp-1", WorkStatus.IN_PROGRESS)
        # WorkStatus must NOT have changed (atomicity: lifecycle rejected, so no change)
        self.assertEqual(p.get("opp-1").work_status, WorkStatus.NEW)

    def test_blocked_preserves_lifecycle_stage(self):
        lifecycle = FakeLifecycle()
        lifecycle.states["opp-1"] = "in_progress"
        p = OpportunityPortfolio(db_path=self.db_path, lifecycle=lifecycle)
        p.add(_sample_entry(work_status=WorkStatus.IN_PROGRESS))
        p.transition_work_status("opp-1", WorkStatus.BLOCKED)
        self.assertEqual(p.get("opp-1").work_status, WorkStatus.BLOCKED)
        # lifecycle stage must NOT have changed (__preserve__)
        self.assertEqual(lifecycle.states["opp-1"], "in_progress")

    def test_terminal_states_immutable(self):
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(_sample_entry(work_status=WorkStatus.PAID))
        with self.assertRaises(IllegalTransitionError):
            p.transition_work_status("opp-1", WorkStatus.READY)
        self.assertEqual(p.get("opp-1").work_status, WorkStatus.PAID)

    def test_full_valid_chain(self):
        """A full NEW→PAY path works through the chain."""
        lifecycle = FakeLifecycle()
        lifecycle.states["opp-1"] = "discovered"
        p = OpportunityPortfolio(db_path=self.db_path, lifecycle=lifecycle)
        p.add(_sample_entry(work_status=WorkStatus.NEW))
        chain = [
            (WorkStatus.EVALUATING, "researched"),
            (WorkStatus.QUALIFIED, "queued"),
            (WorkStatus.READY, "queued"),
            (WorkStatus.IN_PROGRESS, "in_progress"),
        ]
        for ws, lc_stage in chain:
            p.transition_work_status("opp-1", ws)
            self.assertEqual(p.get("opp-1").work_status, ws)
        self.assertEqual(lifecycle.states["opp-1"], "in_progress")


class TestQueueAndPolicy(unittest.TestCase):
    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "portfolio.db")
        self.policy = QueuePolicy()
        self.capacity = CapacityConfig(
            max_active_tasks=2,
            max_pending_applications=3,
            max_simultaneous=5,
            max_high_risk=1,
            max_financial_exposure=500.0,
        )

    def _make_entry(self, opportunity_id, work_status=WorkStatus.READY, **overrides):
        return _sample_entry(opportunity_id=opportunity_id, work_status=work_status, **overrides)

    def test_prioritizes_high_ehv_low_risk_over_low_ehv_high_risk(self):
        """User's example: high-EV-hourly + high-confidence + low-risk + good-skill-fit + near-deadline
        outranks low-EV + high-effort + high-risk."""
        now = time.time()
        p = OpportunityPortfolio(db_path=self.db_path)
        # Winner: high EV/h, high confidence, low risk, good skill fit, near deadline
        winner = self._make_entry("winner", WorkStatus.READY,
                                  expected_hourly_value=80.0, confidence=0.9, risk=0.1,
                                  skill_fit=0.9, effort=2.0, deadline=now + 3600,
                                  expected_value=200.0)
        # Loser: low EV/h, low confidence, high risk, poor skill fit, far deadline
        loser = self._make_entry("loser", WorkStatus.READY,
                                 expected_hourly_value=5.0, confidence=0.2, risk=0.8,
                                 skill_fit=0.2, effort=20.0, deadline=now + 86400 * 30,
                                 expected_value=50.0)
        p.add(winner)
        p.add(loser)
        q = WorkQueue(p, self.policy, self.capacity)
        ordered = q.prioritized(now)
        self.assertEqual(ordered[0].opportunity_id, "winner")
        self.assertEqual(ordered[1].opportunity_id, "loser")

    def test_capacity_limits_active_tasks(self):
        """With max_active_tasks=2 and 5 READY opps, select_next returns ≤ 2."""
        now = time.time()
        p = OpportunityPortfolio(db_path=self.db_path)
        for i in range(5):
            p.add(self._make_entry(f"opp-{i}", WorkStatus.READY,
                                   expected_hourly_value=50.0 - i))
        q = WorkQueue(p, self.policy, self.capacity)
        selected = q.select_next(now)
        # max_active_tasks=2 → only 2 selected
        self.assertLessEqual(len(selected), 2)

    def test_high_risk_limit(self):
        """With max_high_risk=1, a 2nd high-risk opp is skipped."""
        now = time.time()
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(self._make_entry("safe-1", WorkStatus.READY, risk=0.2, expected_hourly_value=30.0))
        p.add(self._make_entry("high-1", WorkStatus.READY, risk=0.9, expected_hourly_value=40.0))
        p.add(self._make_entry("high-2", WorkStatus.READY, risk=0.95, expected_hourly_value=35.0))
        q = WorkQueue(p, self.policy, self.capacity)
        selected = q.select_next(now)
        high_risk_selected = [e for e in selected if e.risk > 0.7]
        self.assertLessEqual(len(high_risk_selected), 1)

    def test_financial_exposure_limit(self):
        """Entries pushing exposure over max are skipped."""
        now = time.time()
        p = OpportunityPortfolio(db_path=self.db_path)
        # max_financial_exposure=500; big-1 already in progress (400 exposure)
        p.add(self._make_entry("big-1", WorkStatus.IN_PROGRESS, expected_value=400.0,
                               expected_hourly_value=50.0))
        q = WorkQueue(p, self.policy, self.capacity)
        # big-2 would push exposure to 800 > 500 → should exceed
        counts = q._current_counts(now)
        reason = q.would_exceed_capacity(
            self._make_entry("big-2", WorkStatus.IN_PROGRESS, expected_value=400.0), counts)
        self.assertIsNotNone(reason)
        self.assertIn("financial_exposure", reason)

    def test_custom_scorer_plugged(self):
        """Inject a custom scorer; queue respects it (formula NOT hardcoded)."""
        now = time.time()
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(self._make_entry("a", WorkStatus.READY, expected_value=100.0))
        p.add(self._make_entry("b", WorkStatus.READY, expected_value=50.0))
        # Custom scorer: prioritize by expected_value only (reverses default order)
        custom_policy = QueuePolicy(scorer=lambda e, n: e.expected_value)
        q = WorkQueue(p, custom_policy, self.capacity)
        ordered = q.prioritized(now)
        self.assertEqual(ordered[0].opportunity_id, "a")
        self.assertEqual(ordered[1].opportunity_id, "b")

    def test_configurable_weights_change_order(self):
        """Flipping weights changes ranking."""
        now = time.time()
        p = OpportunityPortfolio(db_path=self.db_path)
        # Entry A: high EV/h but high risk
        p.add(self._make_entry("A", WorkStatus.READY, expected_hourly_value=100.0, risk=0.8,
                               confidence=0.5))
        # Entry B: low EV/h but low risk
        p.add(self._make_entry("B", WorkStatus.READY, expected_hourly_value=20.0, risk=0.1,
                               confidence=0.5))
        # Default weights: risk weight is -0.8, so B should win
        q1 = WorkQueue(p, QueuePolicy(), self.capacity)
        o1 = q1.prioritized(now)
        # Flip: make risk weight positive (risk is good) → A should win
        q2 = WorkQueue(p, QueuePolicy(w_risk=0.8), self.capacity)
        o2 = q2.prioritized(now)
        self.assertNotEqual(o1[0].opportunity_id, o2[0].opportunity_id)

    def test_no_deadline_lowers_urgency(self):
        now = time.time()
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(self._make_entry("no-deadline", WorkStatus.READY, deadline=0,
                               expected_hourly_value=50.0))
        p.add(self._make_entry("far-deadline", WorkStatus.READY, deadline=now + 86400 * 20,
                               expected_hourly_value=50.0))
        p.add(self._make_entry("near-deadline", WorkStatus.READY, deadline=now + 3600,
                               expected_hourly_value=50.0))
        q = WorkQueue(p, self.policy, self.capacity)
        ordered = q.prioritized(now)
        # near-deadline should be first, no-deadline and far-deadline lower
        self.assertEqual(ordered[0].opportunity_id, "near-deadline")

    def test_summary(self):
        now = time.time()
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(self._make_entry("a", WorkStatus.IN_PROGRESS, expected_value=100.0))
        p.add(self._make_entry("b", WorkStatus.READY, expected_value=50.0))
        p.add(self._make_entry("c", WorkStatus.PAID, expected_value=200.0))
        q = WorkQueue(p, self.policy, self.capacity)
        s = q.summary(now)
        self.assertEqual(s["active_tasks"], 1)
        self.assertEqual(s["pending_applications"], 1)
        self.assertEqual(s["financial_exposure"], 100.0)
        self.assertEqual(s["remaining_active"], 1)  # max 2 - 1 = 1


class TestNextAction(unittest.TestCase):
    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "portfolio.db")

    def test_resolve_next_action_each_status(self):
        """Every status maps to a sensible action/reason."""
        for ws in WorkStatus:
            entry = _sample_entry(opportunity_id="x", work_status=ws)
            action, reason = resolve_next_action(entry)
            self.assertIsInstance(action, str)
            self.assertIsInstance(reason, str)
            self.assertTrue(len(action) > 0)
        # Spot-check a few
        self.assertEqual(resolve_next_action(_sample_entry(work_status=WorkStatus.NEW))[0], "evaluate")
        self.assertEqual(resolve_next_action(_sample_entry(work_status=WorkStatus.READY))[0], "begin_work")
        self.assertEqual(resolve_next_action(_sample_entry(work_status=WorkStatus.PAID))[0], "none")

    def test_blocked_entry_action_reflects_reason(self):
        entry = _sample_entry(work_status=WorkStatus.BLOCKED, blocked_reason="waiting on docs")
        action, reason = resolve_next_action(entry)
        self.assertEqual(action, "unblock_or_abandon")
        self.assertEqual(reason, "waiting on docs")

    def test_waiting_external_action_reflects_reason(self):
        entry = _sample_entry(work_status=WorkStatus.WAITING_EXTERNAL,
                              waiting_reason="awaiting client feedback")
        action, reason = resolve_next_action(entry)
        self.assertEqual(action, "follow_up")
        self.assertEqual(reason, "awaiting client feedback")

    def test_apply_next_advances_through_chain(self):
        """apply_next walks NEW → EVALUATING → QUALIFIED → RECOMMENDED → READY → IN_PROGRESS."""
        lifecycle = FakeLifecycle()
        lifecycle.states["opp-1"] = "discovered"
        p = OpportunityPortfolio(db_path=self.db_path, lifecycle=lifecycle)
        entry = _sample_entry(work_status=WorkStatus.NEW)
        p.add(entry)
        now = time.time()
        for expected in [WorkStatus.EVALUATING, WorkStatus.QUALIFIED, WorkStatus.RECOMMENDED,
                         WorkStatus.READY, WorkStatus.IN_PROGRESS]:
            entry = apply_next(p, p.get("opp-1"), now)
            self.assertEqual(entry.work_status, expected)

    def test_apply_next_terminal_noop(self):
        p = OpportunityPortfolio(db_path=self.db_path)
        p.add(_sample_entry(work_status=WorkStatus.PAID))
        entry = apply_next(p, p.get("opp-1"), time.time())
        self.assertEqual(entry.work_status, WorkStatus.PAID)


class TestPipelineSync(unittest.TestCase):
    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "portfolio.db")

    def _make_legacy(self, opp_id, title="Test opp"):
        """Use the pipeline's legacy Opportunity model (has .id)."""
        from earning_pipeline import Opportunity as LegacyOpp
        return LegacyOpp(
            id=opp_id,
            source="test",
            platform="upwork",
            type="coding",
            title=title,
            description="desc",
            payment_type="usd",
            payment_amount=200.0,
            url="https://example.com",
            status="new",
        )

    def test_evaluate_syncs_to_portfolio(self):
        """After evaluate(), portfolio has entries with policy fields from intelligence verdict."""
        from earning_pipeline import EarningPipeline
        pipe = EarningPipeline(
            db_path=os.path.join(tempfile.mkdtemp(), "p.db"),
            memory_path=os.path.join(tempfile.mkdtemp(), "m.db"))
        portfolio = OpportunityPortfolio(db_path=self.db_path)
        pipe.portfolio = portfolio
        opp = self._make_legacy("opp-x")
        pipe.evaluate([opp])
        entry = portfolio.get("opp-x")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.platform, "upwork")
        self.assertEqual(entry.category, "coding")
        self.assertEqual(entry.work_status, WorkStatus.EVALUATING)

    def test_pipeline_works_without_portfolio(self):
        """Back-compat: evaluate() runs with portfolio=None."""
        from earning_pipeline import EarningPipeline
        pipe = EarningPipeline(
            db_path=os.path.join(tempfile.mkdtemp(), "p.db"),
            memory_path=os.path.join(tempfile.mkdtemp(), "m.db"))
        pipe.portfolio = None
        opp = self._make_legacy("opp-y")
        result = pipe.evaluate([opp])
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
