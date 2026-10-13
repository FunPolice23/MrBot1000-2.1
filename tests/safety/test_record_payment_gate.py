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

sys.path.insert(0, r"D:\MrBot1000_2.0")

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


def _enqueue_and_approve(queue, *, approve=True) -> str:
    item = queue.enqueue_payment("pay", "record a payment")
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
        aid = _enqueue_and_approve(self.queue, approve=True)
        out = self._call({"opportunity_id": "o1", "amount": 25.0,
                          "evidence_ref": "ev-1", "approval_id": aid})
        self.assertIn("PAID", out)
        self.assertEqual(len(self.tracker.calls), 1)
        opp_id, amount, evidence = self.tracker.calls[0]
        self.assertEqual(opp_id, "o1")
        self.assertAlmostEqual(amount, 25.0)
        self.assertEqual(evidence["verified"], True)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
