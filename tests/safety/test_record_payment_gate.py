"""Phase D2 — record_payment tool: HIGH-TRUST, approval-gated (ARCH-ENG-084).

record_payment books a verified payment against an opportunity. Invariants:
- refuses unless invoked through the dispatcher (mutation capability).
- refuses a non-positive amount (the agent never invents a payout).
- refuses without an approved approval_id (HIGH-TRUST gate).
- refuses a PENDING/DENIED approval.
- with an APPROVED approval + a wired lifecycle tracker, it records via the
  evidence-gated mark_paid_verified (never fabricating amount/evidence).
"""
import sys
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import agents.safety.handlers as H
from agents.safety.approval import (
    ApprovalStatus, ApprovalItem, HumanApprovalQueue,
)
from agents.safety.calling import _DISPATCH_CAPABILITY


class _StubState:
    def __init__(self):
        self.work_status = "PAID"


class _StubTracker:
    def __init__(self):
        self.calls = []

    def mark_paid_verified(self, opp_id, *, amount=0.0, evidence=None):
        self.calls.append((opp_id, amount, evidence))
        return _StubState()


def _enqueue_and_approve(queue, *, approve=True, amount=10.0) -> str:
    """Enqueue a scoped PAYMENT approval (ARCH-ENG-129) and optionally approve.

    ARCH-ENG-129: the approval must name the tool AND the amount. Before the
    scope binding, `enqueue_payment("pay", "record a payment")` recorded no
    amount and `record_payment` accepted any figure the caller passed — a
    human-approved $5 approval booked $1,000,000 (reproduced by execution).
    The amount is now part of what the operator authorizes.
    """
    item = queue.enqueue_payment("pay", "record a payment", amount=amount)
    if approve:
        queue.approve(item.id, notes="ok")
    return item.id


class TestRecordPaymentGate(unittest.TestCase):
    def setUp(self):
        self.tracker = _StubTracker()
        H.set_lifecycle_tracker(self.tracker)
        self.queue = HumanApprovalQueue.instance()

    def tearDown(self):
        H.set_lifecycle_tracker(None)

    def _call(self, args):
        return H._tool_record_payment(args, authorization=_DISPATCH_CAPABILITY)

    def test_requires_dispatcher_capability(self):
        out = H._tool_record_payment(
            {"opportunity_id": "o1", "amount": 10, "approval_id": "x"},
            authorization=None)
        self.assertIn("Authorization required", out)
        self.assertEqual(self.tracker.calls, [])

    def test_rejects_nonpositive_amount(self):
        aid = _enqueue_and_approve(self.queue)
        out = self._call({"opportunity_id": "o1", "amount": 0, "approval_id": aid})
        self.assertIn("positive", out)
        self.assertEqual(self.tracker.calls, [])

    def test_rejects_missing_approval_id(self):
        out = self._call({"opportunity_id": "o1", "amount": 10})
        self.assertIn("approval_id", out)
        self.assertEqual(self.tracker.calls, [])

    def test_rejects_pending_approval(self):
        aid = _enqueue_and_approve(self.queue, approve=False)
        out = self._call({"opportunity_id": "o1", "amount": 10, "approval_id": aid})
        self.assertIn("not approved", out)
        self.assertEqual(self.tracker.calls, [])

    def test_records_behind_approved_approval(self):
        """An APPROVED approval books the payment, but ONLY with L3 evidence.

        ARCH-ENG-121: this test previously passed a bare ``evidence_ref`` and
        asserted the hand-written ``{\"verified\": True}`` dict reached the
        tracker — i.e. it asserted the bypass. The dict carried no ``status``
        and no ``verification_level``, so ``_is_verified_evidence`` took its
        legacy ``if not status: return bool(ev.get(\"verified\"))`` branch and
        booked the agent-asserted amount as VERIFIED revenue. An approval
        authorizes an ACTION, not an AMOUNT or a VERIFICATION, so the caller
        must now supply evidence that independently meets the L3 floor.

        ARCH-ENG-129: the approval also names the amount. $25.00 is what the
        operator approved, so $25.00 is the only figure this approval can book.
        """
        from agents.evidence.evidence import (
            Evidence, EvidenceStatus, VerificationLevel,
        )

        aid = _enqueue_and_approve(self.queue, amount=25.0)
        evidence = Evidence(
            source="ethereum",
            evidence_type="transaction_receipt",
            subject_type="payment",
            subject_id="o1",
            amount=25.0,
            status=EvidenceStatus.VERIFIED,
            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
            source_reference="ev-1",
        )
        out = self._call({"opportunity_id": "o1", "amount": 25.0,
                          "evidence_ref": "ev-1", "approval_id": aid,
                          "evidence": evidence})
        self.assertIn("PAID", out)
        self.assertEqual(len(self.tracker.calls), 1)
        opp_id, amount, passed = self.tracker.calls[0]
        self.assertEqual(opp_id, "o1")
        self.assertAlmostEqual(amount, 25.0)
        # The caller's real Evidence is passed through untouched.
        self.assertIs(passed, evidence)

    def test_refuses_bare_evidence_ref_without_l3_evidence(self):
        """ARCH-ENG-121: a bare evidence_ref is an assertion, not evidence.

        The old behaviour booked this as verified revenue. The approval still
        authorizes the action, but nothing here verifies the amount.
        """
        aid = _enqueue_and_approve(self.queue, amount=25.0)
        out = self._call({"opportunity_id": "o1", "amount": 25.0,
                          "evidence_ref": "ev-1", "approval_id": aid})
        self.assertIn("L3", out)
        self.assertEqual(self.tracker.calls, [])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
