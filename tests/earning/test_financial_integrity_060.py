"""ARCH-ENG-060..069 — financial-integrity regression tests.

Every defect below was reproduced by execution BEFORE the fix and is asserted
resolved after. They share one theme: the earning/evidence pipeline had several
places where an UNVERIFIED claim could become verified revenue, or where a
rejected state-machine transition silently moved the stage anyway.

  060  `_stage_verify` fail-open: an exception (or a lifecycle returning None)
       left `verified=True`, so a DB error booked a $4000 payout as a win and
       fed `outcome_state="paid", revenue=4000` into the learning ledgers.
  061  `_ALLOWED_TRANSITIONS` was decorative — the invalid branch still called
       `_append`, which unconditionally overwrote `current_stage`.
  062  Every `paid` branch bypassed the state machine via a direct `_append`,
       so `discovered` -> `paid` skipped every predecessor stage and a `failed`
       opportunity could be resurrected to `paid`.
  064  `verified_revenue_usd`/`unverified_payouts` read `ev.get("verified")`,
       a key `Evidence.to_dict()` never emits — inverting trust so a real L5
       on-chain payout counted as $0 and a hand-written `{"verified": True}`
       dict booked its full expected_usd.
  065  `evidence_policy.reconcile` used a DENY-list of four manual methods, so
       `method="heuristic"` / `method="whatever"` escalated to VERIFIED@L4.
       `reconcile_evidence` also booked the CLAIMED amount, not the settled one.
  067  Expense vocabulary mismatch: `payment_*` evidence types were never
       recognised, so `realized_expense` was always 0.0.
  068  `mark_final_outcome` zeroed nothing: an unverified $5000 "paid" was
       recorded as a successful $5000 revenue event in the learning priors.
  069  `pending_revenue` compared against the lowercase "unverified" while
       `EvidenceStatus.UNVERIFIED.value` is uppercase — always 0.0.
"""

import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.evidence.evidence import (
    Evidence,
    EvidenceStatus,
    VerificationLevel,
)
from agents.evidence.evidence_policy import is_transition_eligible, reconcile
from agents.evidence.evidence_store import EvidenceStore
from agents.earning.economic_accounting import EconomicAccounting
from agents.earning.opportunity_lifecycle import OpportunityLifecycleTracker
from agents.services.autonomous_loop import AutonomousResult
from app.database import AgentDB


def _payment_evidence(subject_id, amount=4000.0, level=VerificationLevel.L3_EXTERNAL_SOURCE,
                      method="authenticated_api", etype="payment_gross", status=EvidenceStatus.VERIFIED):
    return Evidence.create(
        source="system", evidence_type=etype, subject_type="opportunity",
        subject_id=subject_id, external_id=f"ext-{subject_id}", amount=amount,
        currency="usd", verification_method=method, verification_level=level,
        status=status, provenance={"producer": "payment_provider"})


def _eligible_chain(subject_id, amount=4000.0):
    """A full SUBMITTED->PAID chain: submission + completion + payment.

    `_stage_verify` only reaches the lifecycle call when `is_transition_eligible`
    is satisfied, so a payment record alone is not enough to exercise it.
    """
    return [
        Evidence.create(source="platform", evidence_type="platform_submission",
                        subject_type="opportunity", subject_id=subject_id,
                        amount=0.0, currency="usd", verification_method="authenticated_api",
                        verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
                        status=EvidenceStatus.VERIFIED),
        Evidence.create(source="platform", evidence_type="completion_confirmation",
                        subject_type="opportunity", subject_id=subject_id,
                        amount=0.0, currency="usd", verification_method="authenticated_api",
                        verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
                        status=EvidenceStatus.VERIFIED),
        _payment_evidence(subject_id, amount=amount),
    ]


class _StoreStub:
    """Minimal EvidenceStore surface the lifecycle uses."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def record(self, ev):
        self.items.append(ev)
        return ev

    def get(self, evidence_id):
        for ev in self.items:
            if getattr(ev, "id", None) == evidence_id:
                return ev
        return None

    def for_subject(self, subject_type, subject_id):
        return [e for e in self.items
                if e.subject_type == subject_type and e.subject_id == subject_id]


def _tracker(store=None):
    """A tracker that never touches disk."""
    t = OpportunityLifecycleTracker.__new__(OpportunityLifecycleTracker)
    t._evidence_store = store
    t._states = {}
    t._history = []
    t._callback = None
    t._learning_loop = None
    t._outcome_callback = None
    t._state_path = None
    return t


def _real_store():
    """A real EvidenceStore backed by a throwaway sqlite DB."""
    tmpdir = tempfile.mkdtemp(prefix="arch_eng_060_")
    return EvidenceStore(AgentDB(os.path.join(tmpdir, "evidence.db")))


class TestStageVerifyFailsClosed(unittest.TestCase):
    """ARCH-ENG-060 — an exception during paid-verification is NOT a payout."""

    def _loop(self):
        from agents.services.autonomous_loop import AutonomousLoop
        loop = AutonomousLoop.__new__(AutonomousLoop)
        loop.evidence_store = None
        loop.lifecycle = None
        return loop

    def test_lifecycle_exception_leaves_paid_false(self):
        loop = self._loop()

        class _BoomLifecycle:
            def mark_paid_verified(self, *a, **kw):
                raise RuntimeError("database is locked")

        loop.lifecycle = _BoomLifecycle()

        class _Store:
            def for_subject(self, *a, **kw):
                return _eligible_chain("opp-boom")

        loop.evidence_store = _Store()

        result = AutonomousResult(opportunity_id="opp-boom")
        opp = type("Opp", (), {"id": "opp-boom", "opportunity_id": "opp-boom"})()
        loop._stage_verify(result, opp, facts=opp)

        self.assertFalse(result.paid,
                         "a lifecycle DB error must not be read as a verified payout")
        self.assertTrue(any("paid-verification failed" in e for e in result.errors),
                        f"the error must be surfaced, got {result.errors}")

    def test_lifecycle_returning_none_leaves_paid_false(self):
        loop = self._loop()

        class _NoneLifecycle:
            def mark_paid_verified(self, *a, **kw):
                return None

        loop.lifecycle = _NoneLifecycle()

        class _Store:
            def for_subject(self, *a, **kw):
                return _eligible_chain("opp-none")

        loop.evidence_store = _Store()

        result = AutonomousResult(opportunity_id="opp-none")
        opp = type("Opp", (), {"id": "opp-none", "opportunity_id": "opp-none"})()
        loop._stage_verify(result, opp, facts=opp)

        self.assertFalse(result.paid,
                         "getattr default 'paid' previously turned None into a win")


class TestRejectedTransitionDoesNotMoveStage(unittest.TestCase):
    """ARCH-ENG-061 — the allowed-transition table must actually gate."""

    def test_in_progress_cannot_go_back_to_queued(self):
        t = _tracker()
        t.mark_queued("o1", score=0.9)
        t.mark_applied("o1")
        t.mark_in_progress("o1")
        t.mark_queued("o1", score=0.9)
        st = t.get_state("o1")
        self.assertEqual(st["current_stage"], "in_progress")
        self.assertTrue(st["last_transition_error"])
        self.assertFalse(st["history"][-1]["transition_ok"])

    def test_paid_opportunity_cannot_be_demoted_to_failed(self):
        t = _tracker()
        t.mark_queued("o2", score=0.9)
        t.mark_applied("o2")
        t.mark_in_progress("o2")
        t.mark_submitted("o2")
        t.mark_paid_verified("o2", amount=100.0,
                             evidence=_payment_evidence("o2", 100.0))
        self.assertEqual(t.get_state("o2")["status"], "paid")

        t.mark_failed("o2", note="after paid")
        st = t.get_state("o2")
        self.assertEqual(st["current_stage"], "paid",
                         "a revenue-booked opportunity must not be demoted")
        self.assertEqual(st["status"], "paid")

    def test_failed_opportunity_is_not_resurrected_to_paid(self):
        t = _tracker()
        t.mark_failed("o3", note="dead")
        t.mark_paid_verified("o3", amount=500.0,
                             evidence=_payment_evidence("o3", 500.0))
        st = t.get_state("o3")
        self.assertNotEqual(st["status"], "paid")
        self.assertNotEqual(st["current_stage"], "paid")

    def test_completed_is_not_reachable_from_discovered(self):
        """`completed` IS a legal terminal stage from `discovered` (an abandoned
        opportunity), but it must be reached THROUGH the machine, and it must not
        then be promotable to `paid`."""
        t = _tracker()
        t.mark_final_outcome("o4", outcome_state="completed", revenue=0.0)
        st = t.get_state("o4")
        self.assertEqual(st["current_stage"], "completed")
        self.assertEqual(st["status"], "completed")
        self.assertTrue(st["history"][-1]["transition_ok"],
                        "a legal terminal move must be recorded as ok")
        # A completed opportunity is terminal: no route to paid.
        self.assertEqual(t._route_to("completed", "paid"), [])


class TestPaidMustPassThroughStateMachine(unittest.TestCase):
    """ARCH-ENG-062 — no direct `_append(state, 'paid')` bypass."""

    def test_l5_onchain_payout_routes_through_claimed(self):
        t = _tracker()
        ev = _payment_evidence("o5", 7777.0, level=VerificationLevel.L5_CRYPTOGRAPHIC,
                               method="blockchain_balance_delta", etype="balance_delta")
        t.mark_paid_verified("o5", amount=7777.0, evidence=ev)
        st = t.get_state("o5")
        stages = [h["stage"] for h in st["history"]]
        self.assertEqual(st["status"], "paid")
        self.assertIn("claimed", stages,
                      "the crypto route must pass through an explicit stage, "
                      f"got history {stages}")

    def test_payout_reaches_paid_from_every_live_stage(self):
        """ARCH-ENG-062 regression: a verified payout must not be BLOCKED because
        the opportunity happens to sit at `applied` or `in_progress`. The first cut
        of this fix hardcoded a single `claimed` waypoint and refused a real $750
        payout on an in-progress opportunity."""
        for start_stage, setup in (
            ("discovered", lambda t, o: None),
            ("researched", lambda t, o: t.mark_researched(o)),
            ("queued", lambda t, o: (t.mark_researched(o), t.mark_queued(o, 0.9))),
            ("applied", lambda t, o: (t.mark_researched(o), t.mark_queued(o, 0.9),
                                      t.mark_applied(o))),
            ("in_progress", lambda t, o: (t.mark_researched(o), t.mark_queued(o, 0.9),
                                          t.mark_applied(o), t.mark_in_progress(o))),
        ):
            with self.subTest(start_stage=start_stage):
                oid = f"live-{start_stage}"
                t = _tracker()
                setup(t, oid)
                self.assertEqual(t.get_state(oid)["current_stage"], start_stage)
                t.mark_paid_verified(oid, amount=750.0,
                                     evidence=_payment_evidence(oid, 750.0))
                st = t.get_state(oid)
                self.assertEqual(st["status"], "paid",
                                 f"a verified $750 payout must reach paid from {start_stage}")
                self.assertEqual(st["current_stage"], "paid")
                self.assertAlmostEqual(st["last_amount"], 750.0, places=2)

    def test_terminal_stages_can_never_reach_paid(self):
        for terminal in ("failed", "rejected", "paid", "completed"):
            self.assertEqual(_tracker()._route_to(terminal, "paid"), [],
                             f"{terminal} is terminal and must not route to paid")

    def test_freelance_route_still_reaches_paid_from_submitted(self):
        t = _tracker()
        t.mark_queued("o6", score=0.9)
        t.mark_applied("o6")
        t.mark_in_progress("o6")
        t.mark_submitted("o6")
        t.mark_paid_verified("o6", amount=120.0,
                             evidence=_payment_evidence("o6", 120.0))
        self.assertEqual(t.get_state("o6")["current_stage"], "paid")


class TestReconcileMethodAllowList(unittest.TestCase):
    """ARCH-ENG-065 — only independent methods may escalate to VERIFIED."""

    def _unverified(self):
        return Evidence.create(
            source="operator", evidence_type="payment_gross",
            subject_type="opportunity", subject_id="r1", amount=25.0, currency="usd",
            verification_method="manual_attestation",
            verification_level=VerificationLevel.L1_SELF_REPORTED,
            status=EvidenceStatus.UNVERIFIED)

    def test_arbitrary_method_cannot_escalate(self):
        for method in ("heuristic", "whatever", "", "operator_says_so"):
            ev = reconcile(self._unverified(), "operator", method=method)
            self.assertFalse(ev.status.is_affirmative,
                             f"method={method!r} must NOT reach an affirmative status")

    def test_independent_method_still_escalates(self):
        ev = reconcile(self._unverified(), "operator", method="external_reconciliation")
        self.assertTrue(ev.status.is_affirmative)
        self.assertGreaterEqual(int(ev.verification_level),
                                int(VerificationLevel.L3_EXTERNAL_SOURCE))


class TestReconcileBooksSettledAmount(unittest.TestCase):
    """ARCH-ENG-065 — book the reconciled amount, not the operator's claim."""

    def test_reconciled_amount_wins_over_claim(self):
        store = _real_store()
        t = OpportunityLifecycleTracker(evidence_store=store)
        t.mark_queued("o7", score=0.9)
        t.mark_applied("o7")
        t.mark_in_progress("o7")
        t.mark_submitted("o7", amount=5000.0)

        # A submission + completion record so SUBMITTED->PAID is reachable, plus the
        # operator's $5000 claim...
        store.record(Evidence.create(
            source="platform", evidence_type="platform_submission",
            subject_type="opportunity", subject_id="o7", amount=0.0, currency="usd",
            verification_method="authenticated_api",
            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
            status=EvidenceStatus.VERIFIED))
        store.record(Evidence.create(
            source="platform", evidence_type="completion_confirmation",
            subject_type="opportunity", subject_id="o7", amount=0.0, currency="usd",
            verification_method="authenticated_api",
            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
            status=EvidenceStatus.VERIFIED))
        store.record(_payment_evidence("o7", 5000.0))

        # ...settled externally for $25.
        settled = Evidence.create(
            source="bank", evidence_type="payment_gross", subject_type="opportunity",
            subject_id="o7", amount=25.0, currency="usd",
            verification_method="manual_attestation",
            verification_level=VerificationLevel.L1_SELF_REPORTED,
            status=EvidenceStatus.UNVERIFIED)
        store.record(settled)

        t.reconcile_evidence("o7", settled.id, reconciler="operator",
                             method="external_reconciliation")

        st = t.get_state("o7")
        self.assertEqual(st["status"], "paid")
        self.assertAlmostEqual(st["last_amount"], 25.0, places=2,
                               msg="a $5000 claim settled for $25 must book $25")

        profile = EconomicAccounting(store).get_profile("o7")
        self.assertAlmostEqual(st["last_amount"], 25.0, places=2)
        self.assertNotAlmostEqual(profile.verified_revenue, 5000.0, places=2,
                                  msg="the $5000 claim must not be booked as verified")


class TestVerifiedRevenueReadsRealEvidence(unittest.TestCase):
    """ARCH-ENG-064 — trust must not be inverted."""

    def test_genuine_l5_payout_counts_as_verified(self):
        t = _tracker()
        ev = _payment_evidence("o8", 480.0, level=VerificationLevel.L5_CRYPTOGRAPHIC,
                               method="blockchain_balance_delta", etype="balance_delta")
        t.mark_queued("o8", score=0.9)
        t.mark_applied("o8")
        t.mark_in_progress("o8")
        t.mark_submitted("o8")
        t.mark_paid_verified("o8", amount=480.0, evidence=ev)

        self.assertAlmostEqual(t.verified_revenue_usd(), 480.0, places=2,
                               msg="a cryptographic payout must count as revenue")
        self.assertEqual(t.unverified_payouts(), [])

    def test_self_reported_dict_without_status_is_not_trusted_by_default(self):
        t = _tracker()
        st = t._ensure("o9")
        st.status = "paid"
        st.last_amount = 9999.0
        st.verification = {"expected_usd": 9999}
        self.assertEqual(t.verified_revenue_usd(), 0.0,
                         "a dict with no status/level must not book revenue")
        self.assertIn("o9", t.unverified_payouts())

    def test_low_level_evidence_is_not_verified_revenue(self):
        t = _tracker()
        st = t._ensure("o10")
        st.status = "paid"
        st.last_amount = 250.0
        st.verification = {"status": "VERIFIED", "verification_level": 1}
        self.assertEqual(t.verified_revenue_usd(), 0.0,
                         "an L1 attestation must not enter hard verified revenue")


class TestExpenseVocabulary(unittest.TestCase):
    """ARCH-ENG-067 — `payment_*` expense evidence must be counted."""

    def test_payment_expenses_are_recognised(self):
        store = _real_store()
        store.record(_payment_evidence("o11", 1000.0))
        for etype, amount in (("payment_fee", 200.0), ("payment_gas", 50.0),
                              ("payment_llm_cost", 30.0)):
            store.record(Evidence.create(
                source="system", evidence_type=etype, subject_type="opportunity",
                subject_id="o11", amount=amount, currency="usd",
                verification_method="authenticated_api",
                verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
                status=EvidenceStatus.VERIFIED))

        p = EconomicAccounting(store).get_profile("o11")
        self.assertAlmostEqual(p.verified_revenue, 1000.0, places=2)
        self.assertAlmostEqual(p.realized_expense, 280.0, places=2,
                               msg=f"expenses were {p.realized_expense}")
        self.assertAlmostEqual(p.realized_net, 720.0, places=2)


class TestPendingRevenueBucket(unittest.TestCase):
    """ARCH-ENG-069 — UNVERIFIED money belongs in pending, not lost."""

    def test_unverified_payment_lands_in_pending(self):
        store = _real_store()
        store.record(_payment_evidence(
            "o12", 300.0, level=VerificationLevel.L1_SELF_REPORTED,
            method="manual_attestation", status=EvidenceStatus.UNVERIFIED))
        p = EconomicAccounting(store).get_profile("o12")
        self.assertAlmostEqual(p.pending_revenue, 300.0, places=2,
                               msg=f"pending was {p.pending_revenue}")
        self.assertAlmostEqual(p.verified_revenue, 0.0, places=2)


class TestMarkFinalOutcomeZeroesUnverifiedRevenue(unittest.TestCase):
    """ARCH-ENG-068 — a downgraded outcome must not keep its revenue."""

    def test_unverified_paid_records_no_revenue_to_learning(self):
        recorded = {}
        seen_by_callback = {}

        class _LearningLoop:
            def process_outcome(self, oid, **kw):
                recorded.update(kw)
                recorded["opportunity_id"] = oid
                return recorded

        t = OpportunityLifecycleTracker.__new__(OpportunityLifecycleTracker)
        t._evidence_store = None
        t._states = {}
        t._learning_loop = _LearningLoop()
        t._outcome_callback = lambda oid, state, **kw: seen_by_callback.update(
            {"state": state, **kw})
        t._callback = None
        t._state_path = None

        t.mark_final_outcome("o13", outcome_state="paid", revenue=5000.0)

        self.assertEqual(recorded.get("outcome_state"), "completed")
        self.assertEqual(recorded.get("revenue"), 0.0,
                         "an unverified claim must not be booked as $5000 of revenue")
        # The search-strategy callback must see the same downgraded revenue — it
        # feeds strategy priors that unlock auto-submission (ARCH-ENG-068 second half).
        self.assertEqual(seen_by_callback.get("state"), "completed")
        self.assertEqual(seen_by_callback.get("revenue"), 0.0,
                         "the strategy-outcome callback must also see zeroed revenue")

    def test_verified_paid_keeps_its_revenue(self):
        recorded = {}
        store = _real_store()

        class _LearningLoop:
            def process_outcome(self, oid, **kw):
                recorded.update(kw)
                return recorded

        t = OpportunityLifecycleTracker.__new__(OpportunityLifecycleTracker)
        t._evidence_store = store
        t._states = {}
        t._learning_loop = _LearningLoop()
        t._outcome_callback = None
        t._callback = None
        t._state_path = None

        oid = "o14"
        t.mark_queued(oid, score=0.9)
        t.mark_applied(oid)
        t.mark_in_progress(oid)
        t.mark_submitted(oid)
        # A complete SUBMITTED->PAID chain so the payout genuinely verifies.
        for etype in ("platform_submission", "completion_confirmation"):
            store.record(Evidence.create(
                source="platform", evidence_type=etype, subject_type="opportunity",
                subject_id=oid, amount=0.0, currency="usd",
                verification_method="authenticated_api",
                verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
                status=EvidenceStatus.VERIFIED))
        store.record(_payment_evidence(oid, 300.0))
        t.mark_paid_verified(oid, amount=300.0,
                             evidence=_payment_evidence(oid, 300.0))
        self.assertEqual(t.get_state(oid)["status"], "paid")

        t.mark_final_outcome(oid, outcome_state="paid", revenue=300.0)

        self.assertEqual(recorded.get("outcome_state"), "paid")
        self.assertAlmostEqual(recorded.get("revenue", 0.0), 300.0, places=2,
                               msg="a genuinely verified payout must keep its revenue")


class TestTerminalStatusIsNotCommittedOnRefusal(unittest.TestCase):
    """ARCH-ENG-061 — a refused transition must not change `status` either."""

    def test_mark_rejected_cannot_demote_a_paid_opportunity(self):
        t = _tracker()
        t.mark_queued("o15", score=0.9)
        t.mark_applied("o15")
        t.mark_in_progress("o15")
        t.mark_submitted("o15")
        t.mark_paid_verified("o15", amount=100.0,
                             evidence=_payment_evidence("o15", 100.0))
        self.assertEqual(t.get_state("o15")["status"], "paid")

        t.mark_rejected("o15", reason="client backed out")

        st = t.get_state("o15")
        self.assertEqual(st["status"], "paid",
                         "a revenue-booked opportunity must not become rejected")
        self.assertEqual(st["current_stage"], "paid")

    def test_mark_final_outcome_generic_branch_only_commits_on_success(self):
        t = _tracker()
        t.mark_queued("o16", score=0.9)
        t.mark_applied("o16")
        t.mark_in_progress("o16")
        t.mark_submitted("o16")
        t.mark_paid_verified("o16", amount=100.0,
                             evidence=_payment_evidence("o16", 100.0))

        # 'abandoned' is not a legal successor of 'paid' — status must not flip.
        t.mark_final_outcome("o16", outcome_state="abandoned")

        self.assertEqual(t.get_state("o16")["status"], "paid")
        self.assertEqual(t.get_state("o16")["current_stage"], "paid")


if __name__ == "__main__":
    unittest.main()
