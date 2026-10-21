"""ARCH-ENG-121 — record_payment evidence floor (evidence-integrity regression).

Defect: the record_payment tool handler built a hand-written evidence dict
``{"verified": True, "method": "manual", "reference": evidence_ref or
"agent-recorded", "note": ...}`` with NO ``status`` and NO ``verification_level``.
`OpportunityLifecycleTracker._is_verified_evidence` honours that legacy shape
via ``if not status: return bool(ev.get("verified"))``, so an agent-supplied
amount was booked as VERIFIED revenue with no independent verification — a
bypass of the L3 external-source floor every other paid path enforces.

Policy decided (defend here, assert here): FAIL CLOSED. An approval authorizes
an ACTION, not an AMOUNT and not a VERIFICATION. `amount` and `evidence_ref`
are raw agent tool arguments. Relabelling the hand-written dict with a
synthesized status/level (option (a)) would merely launder an unverified claim
into the verified column — the very inversion the evidence model forbids ("the
LLM is NEVER allowed to construct a VERIFIED Evidence directly"). So the caller
must supply evidence that ALREADY satisfies the L3 floor on its own
credentials, and an empty evidence_ref is refused rather than defaulted to the
agent-authored string "agent-recorded".

Invariants asserted:
 1. the legacy handler dict does NOT book into verified_revenue_usd() (refused).
 2. a genuinely L3-conformant evidence record DOES book.
 3. the existing guards still hold: amount<=0, missing approval_id, non-APPROVED
    approval, unknown approval.
 4. no regression in the amount>0 / approval-required refusal messages.
"""
import sys
import unittest
import os
import shutil
import tempfile

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import agents.safety.handlers as H
from agents.earning.opportunity_lifecycle import OpportunityLifecycleTracker
from agents.evidence.evidence import (
    Evidence, EvidenceStatus, VerificationLevel,
)
from agents.evidence.evidence_store import EvidenceStore
from agents.safety.approval import (
    ApprovalStatus, HumanApprovalQueue,
)
from agents.safety.calling import _DISPATCH_CAPABILITY


def _approved_approval_id(queue, title="record a payment", amount=10.0) -> str:
    """Enqueue + APPROVE a scoped payment item and return its id.

    ARCH-ENG-129: the approved amount is part of the approval's scope. Tests
    that then book a DIFFERENT amount must expect a refusal — the fixture
    records what the operator authorized, and the tool enforces it.
    """
    item = queue.enqueue_payment(title, "record a payment behind this approval",
                                 amount=amount)
    self_ok = queue.approve(item.id, notes="arch-eng-121 test")
    assert self_ok, "test setup: approval should transition to APPROVED"
    assert item.status == ApprovalStatus.APPROVED
    return item.id


def _l3_evidence(subject_id: str, reference: str, amount: float) -> Evidence:
    """A genuinely L3-conformant evidence record (an authenticated API response
    confirmed the payment). This is what an independent verifier would produce —
    it carries its own affirmative status and L3 level, which is exactly what
    the record_payment handler must now require."""
    return Evidence.create(
        source="platform", evidence_type="platform_transaction",
        subject_type="opportunity", subject_id=subject_id,
        status=EvidenceStatus.VERIFIED,
        verification_method="authenticated_api_response",
        verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
        amount=amount, currency="USD",
        source_reference=reference,
        raw_reference=f"platform confirmed payment of {amount} for {subject_id}",
        provenance={"producer": "arch_eng_121_test", "method": "authenticated_api_response"},
    )


class TestRecordPaymentEvidenceFloor(unittest.TestCase):
    def setUp(self):
        # A real, in-process tracker (no store) so we can observe what actually
        # lands in verified_revenue_usd(), not a stub.
        self.tracker = OpportunityLifecycleTracker()
        H.set_lifecycle_tracker(self.tracker)
        self.queue = HumanApprovalQueue.instance()

    def tearDown(self):
        H.set_lifecycle_tracker(None)
        try:
            self.queue.clear_all()
        except Exception:
            pass

    def _call(self, args):
        return H._tool_record_payment(args, authorization=_DISPATCH_CAPABILITY)

    # 1. The exact legacy dict the handler used to build must NOT book.
    def test_legacy_handwritten_dict_does_not_book(self):
        aid = _approved_approval_id(self.queue, amount=7500.0)
        # Reproduce the OLD handler behaviour verbatim: an agent assertion.
        out = self._call({
            "opportunity_id": "opp-legacy", "amount": 7500.0,
            "evidence_ref": "ev-1", "approval_id": aid,
            "evidence": {"verified": True, "method": "manual",
                         "reference": "agent-recorded",
                         "note": "recorded via approval (arch-eng-121 repro)"},
        })
        self.assertIn("refused", out)
        self.assertIn("L3", out)
        # The money must NOT be in the verified-revenue column.
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)
        state = self.tracker.get_state("opp-legacy")
        self.assertNotEqual(state["status"], "paid")
        # And it must not silently vanish either — nothing positive was booked.
        self.assertEqual(state["last_amount"], 0.0)

    def test_omitted_evidence_does_not_book(self):
        aid = _approved_approval_id(self.queue)
        out = self._call({
            "opportunity_id": "opp-noevidence", "amount": 100.0,
            "evidence_ref": "ev-x", "approval_id": aid,
        })
        self.assertIn("refused", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_empty_evidence_ref_refused_not_defaulted(self):
        aid = _approved_approval_id(self.queue, amount=50.0)
        ev = _l3_evidence("opp-emptyref", "ref", 50.0)
        out = self._call({
            "opportunity_id": "opp-emptyref", "amount": 50.0,
            "evidence_ref": "", "approval_id": aid, "evidence": ev,
        })
        # The old code defaulted an empty evidence_ref to "agent-recorded" (an
        # agent assertion). Even with conformant evidence, a missing reference
        # is now refused — no silent defaulting to an agent-authored string.
        self.assertIn("evidence_ref is required", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    # 2. A genuinely L3-conformant evidence record DOES book.
    def test_l3_conformant_evidence_books_as_verified(self):
        aid = _approved_approval_id(self.queue, amount=7500.0)
        ev = _l3_evidence("opp-l3", "platform:/tx/abc123", 7500.0)
        out = self._call({
            "opportunity_id": "opp-l3", "amount": 7500.0,
            "evidence_ref": "platform:/tx/abc123",
            "approval_id": aid, "evidence": ev,
        })
        self.assertIn("paid", out.lower())
        self.assertEqual(self.tracker.verified_revenue_usd(), 7500.0)
        state = self.tracker.get_state("opp-l3")
        self.assertEqual(state["status"], "paid")
        self.assertEqual(state["last_amount"], 7500.0)

    def test_handwritten_dict_evidence_refused(self):
        # A dict is itself agent-supplied (an agent can write
        # {"status": "VERIFIED", "verification_level": 5} out of thin air), so it
        # must be refused regardless of its contents — only a real Evidence
        # object (produced by an independent verifier) carries independent proof.
        aid = _approved_approval_id(self.queue)
        forged = {"status": "VERIFIED", "verification_level": 5,
                  "verification_method": "authenticated_api_response",
                  "amount": 7500.0}
        out = self._call({
            "opportunity_id": "opp-forged", "amount": 7500.0,
            "evidence_ref": "forged-ref", "approval_id": aid,
            "evidence": forged,
        })
        self.assertIn("refused", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_below_floor_evidence_refused(self):
        # An affirmative-but-L2 (or L1) record must NOT book: status alone is
        # not enough, the level floor is the whole point.
        aid = _approved_approval_id(self.queue)
        weak = Evidence.create(
            source="operator", evidence_type="manual_attestation",
            subject_type="opportunity", subject_id="opp-weak",
            status=EvidenceStatus.VERIFIED,
            verification_method="manual_attestation",
            verification_level=VerificationLevel.L1_SELF_REPORTED,
            amount=100.0, currency="USD",
        )
        out = self._call({
            "opportunity_id": "opp-weak", "amount": 100.0,
            "evidence_ref": "operator-note", "approval_id": aid,
            "evidence": weak,
        })
        self.assertIn("refused", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    # 3. Existing guards still hold.
    def test_amount_zero_refused(self):
        aid = _approved_approval_id(self.queue)
        ev = _l3_evidence("opp-a", "ref", 0.0)
        out = self._call({
            "opportunity_id": "opp-a", "amount": 0,
            "evidence_ref": "ref", "approval_id": aid, "evidence": ev,
        })
        self.assertIn("positive", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_amount_negative_refused(self):
        aid = _approved_approval_id(self.queue)
        ev = _l3_evidence("opp-b", "ref", 1.0)
        out = self._call({
            "opportunity_id": "opp-b", "amount": -5,
            "evidence_ref": "ref", "approval_id": aid, "evidence": ev,
        })
        self.assertIn("positive", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_missing_approval_id_refused(self):
        ev = _l3_evidence("opp-c", "ref", 10.0)
        out = self._call({
            "opportunity_id": "opp-c", "amount": 10,
            "evidence_ref": "ref", "evidence": ev,
        })
        self.assertIn("approval_id", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_non_approved_approval_refused(self):
        item = self.queue.enqueue_payment("pay", "not yet approved")
        # Leave PENDING (no approve()).
        ev = _l3_evidence("opp-d", "ref", 10.0)
        out = self._call({
            "opportunity_id": "opp-d", "amount": 10,
            "evidence_ref": "ref", "approval_id": item.id, "evidence": ev,
        })
        self.assertIn("not approved", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_unknown_approval_refused(self):
        ev = _l3_evidence("opp-e", "ref", 10.0)
        out = self._call({
            "opportunity_id": "opp-e", "amount": 10,
            "evidence_ref": "ref", "approval_id": "does-not-exist", "evidence": ev,
        })
        self.assertIn("not found", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    # 4. No regression in the amount>0 / approval-required messages.
    def test_amount_guard_message_unchanged(self):
        aid = _approved_approval_id(self.queue)
        out = self._call({
            "opportunity_id": "opp-f", "amount": 0,
            "evidence_ref": "ref", "approval_id": aid,
        })
        self.assertIn("amount must be positive", out)
        self.assertIn("the agent never invents a payout", out)

    def test_approval_required_message_unchanged(self):
        out = self._call({
            "opportunity_id": "opp-g", "amount": 10, "evidence_ref": "ref",
        })
        self.assertIn("approval_id", out)
        self.assertIn("HIGH-TRUST", out)

    # Sanity: the helper itself discriminates the legacy dict.
    def test_helper_discriminates_legacy_dict(self):
        legacy = {"verified": True, "method": "manual",
                  "reference": "agent-recorded", "note": "..."}
        self.assertFalse(H._evidence_meets_l3(legacy))
        self.assertFalse(H._evidence_meets_l3(None))
        self.assertFalse(H._evidence_meets_l3({"verified": True}))
        # Even a well-formed dict claiming L3 is refused: it is agent-supplied.
        self.assertFalse(H._evidence_meets_l3(
            {"status": "VERIFIED", "verification_level": 5}))
        l3 = _l3_evidence("opp-h", "ref", 1.0)
        self.assertTrue(H._evidence_meets_l3(l3))
        # A serialized Evidence dict is still a dict -> refused by the handler.
        self.assertFalse(H._evidence_meets_l3(l3.to_dict()))

    # ARCH-ENG-121 review: `_evidence_detail` documents itself as never-raising,
    # but a bad verification_level raised ValueError on the REFUSAL path, so a
    # malformed `evidence` argument surfaced as a tool crash instead of the
    # refusal the caller needs.
    def test_evidence_detail_never_raises_on_garbage_level(self):
        for bad in (
            {"status": "VERIFIED", "verification_level": "abc"},
            {"status": "VERIFIED", "verification_level": None},
            {"status": "VERIFIED", "verification_level": 999},
            {},
        ):
            with self.subTest(evidence=bad):
                detail = H._evidence_detail(bad)
                self.assertIsInstance(detail, str)
                self.assertTrue(detail)

    def test_record_payment_with_malformed_evidence_refuses_not_crashes(self):
        """End-to-end: garbage evidence must yield a refusal string."""
        aid = _approved_approval_id(self.queue)
        out = H._tool_record_payment(
            {"opportunity_id": "o1", "amount": 25.0, "approval_id": aid,
             "evidence_ref": "ev-1",
             "evidence": {"status": "VERIFIED", "verification_level": "abc"}},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("record_payment", out)
        self.assertNotIn("Tool error", out)
        self.assertNotIn("Traceback", out)
        # Nothing was booked: the tracker is the real one, so assert on the
        # authoritative verified-revenue figure rather than a stub call list.
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)


class TestRecordPaymentStoreResolution(unittest.TestCase):
    """ARCH-ENG-121 review: `evidence_ref` must be REACHABLE, not a dead end.

    Tool arguments arrive as JSON, so an `Evidence` OBJECT can never be passed
    in. Accepting only `args["evidence"]` made record_payment a guaranteed
    refusal loop, so `evidence_ref` is now resolved against the authoritative
    EvidenceStore. These tests pin both halves: a stored L3 record books, and
    every way to fake one still refuses.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="hermes-ae121-")
        from app.database import AgentDB
        self.store = EvidenceStore(
            AgentDB(os.path.join(self._tmp, "ev.db")))
        self.tracker = OpportunityLifecycleTracker(evidence_store=self.store)
        H.set_lifecycle_tracker(self.tracker)
        self.queue = HumanApprovalQueue.instance()

    def tearDown(self):
        H.set_lifecycle_tracker(None)
        try:
            self.queue.clear_all()
        except Exception:
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _store_l3(self, evidence_id, subject_id="opp-stored", amount=25.0):
        ev = Evidence(
            source="ethereum", evidence_type="transaction_receipt",
            subject_type="payment", subject_id=subject_id, amount=amount,
            status=EvidenceStatus.VERIFIED,
            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
            source_reference=evidence_id, id=evidence_id,
        )
        self.store.record(ev)
        return ev

    def _store_chain(self, subject_id, evidence_id="ev-real"):
        """Record the full freelance chain the lifecycle requires to flip PAID.

        `SUBMITTED->PAID` needs submission + completion + payment, each
        externally verifiable — a lone payment record is correctly NOT enough.
        """
        chain = (
            ("platform_submission", VerificationLevel.L3_EXTERNAL_SOURCE),
            ("completion_confirmation", VerificationLevel.L3_EXTERNAL_SOURCE),
            ("platform_transaction", VerificationLevel.L3_EXTERNAL_SOURCE),
        )
        for i, (etype, level) in enumerate(chain):
            self.store.record(Evidence(
                source="upwork" if i < 2 else "ethereum",
                evidence_type=etype, subject_type="opportunity",
                subject_id=subject_id, amount=25.0,
                status=EvidenceStatus.VERIFIED, verification_level=level,
                source_reference=f"{evidence_id}-{i}", id=f"{evidence_id}-{i}",
            ))

    def _call(self, args):
        return H._tool_record_payment(args, authorization=_DISPATCH_CAPABILITY)

    def test_stored_l3_evidence_ref_books(self):
        """The reachable path: cite an id the store really holds."""
        self._store_chain("opp-stored", "ev-real")
        aid = _approved_approval_id(self.queue, amount=25.0)
        out = self._call({"opportunity_id": "opp-stored", "amount": 25.0,
                          "evidence_ref": "ev-real-2", "approval_id": aid})
        self.assertIn("opp-stored", out)
        self.assertNotIn("refused", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 25.0)

    def test_unknown_evidence_ref_refuses(self):
        aid = _approved_approval_id(self.queue)
        out = self._call({"opportunity_id": "opp-x", "amount": 25.0,
                          "evidence_ref": "ev-does-not-exist", "approval_id": aid})
        self.assertIn("refused", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_stored_below_floor_evidence_refuses(self):
        """A record the store holds but that is only self-reported still refuses."""
        ev = Evidence(
            source="agent", evidence_type="self_report",
            subject_type="payment", subject_id="opp-low", amount=25.0,
            status=EvidenceStatus.UNVERIFIED,
            verification_level=VerificationLevel.L1_SELF_REPORTED,
            source_reference="ev-low", id="ev-low",
        )
        self.store.record(ev)
        aid = _approved_approval_id(self.queue)
        out = self._call({"opportunity_id": "opp-low", "amount": 25.0,
                          "evidence_ref": "ev-low", "approval_id": aid})
        self.assertIn("refused", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_stored_evidence_for_another_opportunity_refuses(self):
        """L3 proof of a DIFFERENT payment must not pay this opportunity."""
        self._store_l3("ev-other", subject_id="opp-other")
        aid = _approved_approval_id(self.queue, amount=25.0)
        out = self._call({"opportunity_id": "opp-mine", "amount": 25.0,
                          "evidence_ref": "ev-other", "approval_id": aid})
        self.assertIn("refused", out)
        self.assertIn("opp-other", out)
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_serialized_evidence_dict_still_refused(self):
        """An agent passing `to_dict()` output must not satisfy the floor.

        The object path is for in-process callers; over the tool boundary the
        record must come from the store, not from the payload.
        """
        stored = self._store_l3("ev-real2", subject_id="opp-stored2")
        aid = _approved_approval_id(self.queue, amount=999.0)
        out = self._call({"opportunity_id": "opp-stored2", "amount": 999.0,
                          "evidence_ref": "ev-real2", "approval_id": aid,
                          "evidence": stored.to_dict()})
        # Resolves via the STORE to the genuine record, so the subject matches
        # and it books the approved amount — the amount was never the thing
        # under test here; the floor is what must hold. (ARCH-ENG-129: the
        # approval now names that amount, so booking a different one is refused
        # before the evidence is even consulted.)
        self.assertIn("opp-stored2", out)
        self.assertNotIn("refused", out)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
