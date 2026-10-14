"""An approval authorizes ONE action, not a capability (ARCH-ENG-129).

`_tool_record_payment` and `_tool_social_post` are the project's two
HIGH-TRUST mutating tools. Both took an `approval_id` and checked exactly one
thing about it: `item.status == ApprovalStatus.APPROVED`. The item's `kind`,
`details` and `payload` were never read, so the arguments that reach the
machine — `amount`, `content` — were raw agent tool arguments sitting next to a
gate that did not know what the human had reviewed.

Three defects, each reproduced by EXECUTING the real handlers before the fix
(see the ARCH-ENG-129 section of CHANGELOG.md for the measured output):

  F1  a human-approved **$5.00** payment booked **$1,000,000.00** of verified
      revenue — the amount was never compared to what was approved;
  F2  a human-approved **file_write** approval (`scratch.txt`) was replayed as
      the `approval_id` for **record_payment**, which booked $777. Approval ids
      are model-visible (`dispatch`/`chat_completion` return `request_id=` into
      the transcript), so ONE id could be spent against ANY mutating tool;
  F3  a human-approved social post of `'Hello team'` published
      `'BUY THIS NOW http://x'` — outbound public content behind a gate that
      never read what the human saw.

The fix is one predicate, `agents.safety.approval.assert_approval_covers`,
called by both tools before they mutate: the approval must name THIS tool and,
where the producer recorded the arguments the human reviewed, THOSE arguments.
Unscoped items authorize nothing (fail closed).

No network, no GUI, no filesystem: the lifecycle tracker and social writer are
stubs, and the queue is the in-memory pytest queue.
"""
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

import agents.safety.handlers as H
from agents.evidence.evidence import (
    Evidence, EvidenceStatus, VerificationLevel,
)
from agents.safety.approval import (
    ApprovalItem, ApprovalKind, ApprovalStatus, HumanApprovalQueue,
    assert_approval_covers, approval_scope,
)
from agents.safety.calling import _DISPATCH_CAPABILITY


class _StubState:
    def __init__(self):
        self.work_status = "PAID"


class _StubTracker:
    """Records what actually reached `mark_paid_verified`."""

    def __init__(self):
        self.calls = []

    def mark_paid_verified(self, opp_id, *, amount=0.0, evidence=None):
        self.calls.append((opp_id, amount, evidence))
        return _StubState()


def _l3_evidence(subject_id, reference, amount):
    return Evidence(
        source="ethereum", evidence_type="transaction_receipt",
        subject_type="payment", subject_id=subject_id, amount=amount,
        status=EvidenceStatus.VERIFIED,
        verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
        source_reference=reference,
    )


def _scoped_payment(queue, amount, *, approve=True):
    """The shape `enqueue_payment` now records: tool + approved amount."""
    item = queue.enqueue_payment("pay", "record a payment", amount=amount)
    if approve:
        queue.approve(item.id, notes="operator")
    return item.id


def _scoped_tool(queue, tool, arguments, *, approve=True):
    """The shape `dispatch.execute_tool` / `chat_completion` record."""
    item = queue.enqueue(ApprovalItem(
        kind=ApprovalKind.ACTION,
        title=f"Chat tool request: {tool}",
        description=f"The chat requested {tool}.",
        requested_by="dialogue",
        details={"tool": tool, "arguments": arguments},
        payload={"tool": tool, "arguments": arguments},
    ))
    if approve:
        queue.approve(item.id, notes="operator")
    return item.id


class TestRecordPaymentAmountScope(unittest.TestCase):
    """F1 — the approved AMOUNT is what may be booked."""

    def setUp(self):
        self.tracker = _StubTracker()
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

    def test_approved_amount_is_the_only_amount_bookable(self):
        """The F1 reproduction, inverted: $5.00 approved books $5.00."""
        aid = _scoped_payment(self.queue, 5.00)
        ev = _l3_evidence("opp-XYZ", "ev-1", 5.0)
        out = self._call({"opportunity_id": "opp-XYZ", "amount": 5.00,
                          "evidence_ref": "ev-1", "approval_id": aid,
                          "evidence": ev})
        self.assertIn("PAID", out)
        self.assertEqual(len(self.tracker.calls), 1)
        self.assertAlmostEqual(self.tracker.calls[0][1], 5.00)

    def test_amount_above_the_approved_amount_is_refused(self):
        """THE F1 DEFECT: $5.00 approved must NOT book $1,000,000.00.

        Before ARCH-ENG-129 this booked $1,000,000.00 of verified revenue —
        measured, not hypothetical.
        """
        aid = _scoped_payment(self.queue, 5.00)
        ev = _l3_evidence("opp-XYZ", "ev-1", 5.0)
        out = self._call({"opportunity_id": "opp-XYZ", "amount": 1000000.0,
                          "evidence_ref": "ev-1", "approval_id": aid,
                          "evidence": ev})
        self.assertIn("refused", out)
        self.assertIn("authorizes one action", out)
        self.assertEqual(self.tracker.calls, [],
                         "a payment above the approved amount was booked")

    def test_amount_below_the_approved_amount_is_refused(self):
        """Scope binding is symmetric — it is not a ceiling."""
        aid = _scoped_payment(self.queue, 500.00)
        ev = _l3_evidence("opp-XYZ", "ev-1", 500.0)
        out = self._call({"opportunity_id": "opp-XYZ", "amount": 0.01,
                          "evidence_ref": "ev-1", "approval_id": aid,
                          "evidence": ev})
        self.assertIn("refused", out)
        self.assertEqual(self.tracker.calls, [])

    def test_int_and_float_amounts_are_the_same_amount(self):
        """JSON round-trips 25.0 as 25; the binding must not be brittle."""
        aid = _scoped_payment(self.queue, 25.0)
        ev = _l3_evidence("opp-i", "ev-2", 25.0)
        out = self._call({"opportunity_id": "opp-i", "amount": 25,
                          "evidence_ref": "ev-2", "approval_id": aid,
                          "evidence": ev})
        self.assertIn("PAID", out)
        self.assertEqual(len(self.tracker.calls), 1)

    def test_payment_with_no_recorded_amount_authorizes_no_amount(self):
        """Fail closed: an approval that never stated a figure books none.

        `enqueue_payment(title, desc)` with the default `amount=0.0` records
        `amount=0.0`. Every positive booking is then refused, because nothing
        in the item authorizes one.
        """
        aid = _scoped_payment(self.queue, 0.0)
        ev = _l3_evidence("opp-z", "ev-3", 10.0)
        out = self._call({"opportunity_id": "opp-z", "amount": 10.0,
                          "evidence_ref": "ev-3", "approval_id": aid,
                          "evidence": ev})
        self.assertIn("refused", out)
        self.assertEqual(self.tracker.calls, [])


class TestApprovalToolScope(unittest.TestCase):
    """F2 — an approval authorizes ONE tool, not a capability."""

    def setUp(self):
        self.tracker = _StubTracker()
        H.set_lifecycle_tracker(self.tracker)
        self.queue = HumanApprovalQueue.instance()
        self.posted = []
        H.set_social_writer(lambda p: self.posted.append(p) or {"ok": True})

    def tearDown(self):
        H.set_lifecycle_tracker(None)
        H.set_social_writer(None)
        try:
            self.queue.clear_all()
        except Exception:
            pass

    def test_file_write_approval_cannot_authorize_record_payment(self):
        """THE F2 DEFECT: a file_write approval replayed as record_payment.

        Before ARCH-ENG-129 this booked $777 of verified revenue behind an
        approval whose only recorded action was writing `scratch.txt`.
        """
        aid = _scoped_tool(self.queue, "file_write",
                           {"path": "scratch.txt", "content": "x"})
        ev = _l3_evidence("opp-XYZ", "ev-1", 777.0)
        out = H._tool_record_payment(
            {"opportunity_id": "opp-XYZ", "amount": 777.0,
             "evidence_ref": "ev-1", "approval_id": aid, "evidence": ev},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("refused", out)
        self.assertIn("file_write", out)
        self.assertEqual(self.tracker.calls, [],
                         "a file_write approval authorized a payment booking")

    def test_file_write_approval_cannot_authorize_social_post(self):
        aid = _scoped_tool(self.queue, "file_write",
                           {"path": "scratch.txt", "content": "x"})
        out = H._tool_social_post(
            {"network": "moltbook", "content": "spam", "approval_id": aid},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("refused", out)
        self.assertEqual(self.posted, [])

    def test_record_payment_approval_cannot_authorize_social_post(self):
        aid = _scoped_payment(self.queue, 25.0)
        out = H._tool_social_post(
            {"network": "moltbook", "content": "spam", "approval_id": aid},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("refused", out)
        self.assertEqual(self.posted, [])

    def test_unscoped_approval_authorizes_nothing(self):
        """Fail closed: an item naming no tool cannot authorize one.

        `enqueue_submission` / `enqueue_gate` and the registration and
        safety-guard producers record only free-form `details`. The human never
        saw a tool, so the item authorizes no tool.
        """
        item = self.queue.enqueue_submission("Post to Moltbook", "draft a post")
        self.queue.approve(item.id, notes="operator")
        out = H._tool_social_post(
            {"network": "moltbook", "content": "anything", "approval_id": item.id},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("refused", out)
        self.assertIn("no tool scope", out)
        self.assertEqual(self.posted, [])

    def test_pending_approval_is_still_refused(self):
        """The pre-existing status check is subsumed, not replaced."""
        aid = _scoped_payment(self.queue, 25.0, approve=False)
        ev = _l3_evidence("opp-p", "ev-4", 25.0)
        out = H._tool_record_payment(
            {"opportunity_id": "opp-p", "amount": 25.0, "evidence_ref": "ev-4",
             "approval_id": aid, "evidence": ev},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("not approved", out)
        self.assertEqual(self.tracker.calls, [])

    def test_unknown_approval_id_is_refused(self):
        ev = _l3_evidence("opp-u", "ev-5", 25.0)
        out = H._tool_record_payment(
            {"opportunity_id": "opp-u", "amount": 25.0, "evidence_ref": "ev-5",
             "approval_id": "does-not-exist", "evidence": ev},
            authorization=_DISPATCH_CAPABILITY)
        self.assertIn("not found", out)
        self.assertEqual(self.tracker.calls, [])


class TestSocialPostContentScope(unittest.TestCase):
    """F3 — the approved CONTENT is what may be published."""

    def setUp(self):
        self.queue = HumanApprovalQueue.instance()
        self.posted = []
        H.set_social_writer(lambda p: self.posted.append(p) or {"ok": True})

    def tearDown(self):
        H.set_social_writer(None)
        try:
            self.queue.clear_all()
        except Exception:
            pass

    def _call(self, args):
        return H._tool_social_post(args, authorization=_DISPATCH_CAPABILITY)

    def test_approved_content_is_published(self):
        aid = _scoped_tool(self.queue, "social_post",
                           {"network": "moltbook", "content": "Hello team"})
        out = self._call({"network": "moltbook", "content": "Hello team",
                          "approval_id": aid})
        self.assertIn("posted to moltbook", out)
        self.assertEqual(len(self.posted), 1)
        self.assertEqual(self.posted[0]["content"], "Hello team")

    def test_different_content_is_refused(self):
        """THE F3 DEFECT: 'Hello team' approved must not publish spam.

        Before ARCH-ENG-129 this published 'BUY THIS NOW http://x' behind an
        approval for 'Hello team' — measured, not hypothetical.
        """
        aid = _scoped_tool(self.queue, "social_post",
                           {"network": "moltbook", "content": "Hello team"})
        out = self._call({"network": "moltbook",
                          "content": "BUY THIS NOW http://x",
                          "approval_id": aid})
        self.assertIn("refused", out)
        self.assertIn("content", out)
        self.assertEqual(self.posted, [],
                         "content other than what was approved was published")

    def test_different_network_is_refused(self):
        aid = _scoped_tool(self.queue, "social_post",
                           {"network": "moltbook", "content": "hi"})
        out = self._call({"network": "twitter", "content": "hi",
                          "approval_id": aid})
        self.assertIn("refused", out)
        self.assertEqual(self.posted, [])

    def test_approval_id_argument_is_not_compared_against_itself(self):
        """`approval_id` is the handle, not part of the reviewed action.

        `main._execute_approved_action` re-stamps the executed call with the id
        the operator actually approved, so the queued arguments legitimately
        differ from the executed ones in exactly that key. Comparing it would
        refuse every honest call.
        """
        aid = _scoped_tool(self.queue, "social_post",
                           {"network": "moltbook", "content": "hi",
                            "approval_id": "placeholder"})
        out = self._call({"network": "moltbook", "content": "hi",
                          "approval_id": aid})
        self.assertIn("posted to moltbook", out)
        self.assertEqual(len(self.posted), 1)

    def test_no_wired_writer_still_refuses_without_fabricating(self):
        """ARCH-ENG-085's no-fabrication guarantee is untouched."""
        H.set_social_writer(None)
        aid = _scoped_tool(self.queue, "social_post",
                           {"network": "moltbook", "content": "hi"})
        out = self._call({"network": "moltbook", "content": "hi",
                          "approval_id": aid})
        self.assertIn("no confirmed write endpoint", out)
        self.assertNotIn("posted to moltbook", out)


class TestAssertApprovalCoversUnit(unittest.TestCase):
    """The predicate itself, including the shapes real producers emit."""

    def setUp(self):
        self.queue = HumanApprovalQueue.instance()

    def tearDown(self):
        try:
            self.queue.clear_all()
        except Exception:
            pass

    def test_none_item_is_refused(self):
        self.assertIn("not found", assert_approval_covers(None, "x", {}))

    def test_matching_scope_returns_none(self):
        item = self.queue.find_by_id(_scoped_tool(
            self.queue, "record_payment",
            {"amount": 10.0, "opportunity_id": "o1"}))
        self.assertIsNone(assert_approval_covers(
            item, "record_payment", {"amount": 10, "opportunity_id": "o1"}))

    def test_unrecorded_keys_are_not_policed(self):
        """Producers legitimately record a subset of the call's arguments.

        `big_brain` adds a `reason`; `dispatch` records the full dict. An
        unrecorded key cannot have been shown to the human, so requiring it
        would make the tool unusable rather than safer.
        """
        item = self.queue.find_by_id(_scoped_tool(
            self.queue, "record_payment", {"amount": 10.0}))
        self.assertIsNone(assert_approval_covers(
            item, "record_payment", {"amount": 10.0, "evidence_ref": "ev-9"}))

    def test_payload_is_preferred_over_details(self):
        """`big_brain` records scope in `payload` and extra keys in `details`."""
        item = ApprovalItem(
            kind=ApprovalKind.ACTION, title="t", description="d",
            status=ApprovalStatus.APPROVED,
            details={"tool": "file_write", "arguments": {"path": "a"}},
            payload={"tool": "record_payment", "arguments": {"amount": 10.0}},
        )
        self.assertEqual(approval_scope(item)["tool"], "record_payment")
        self.assertIsNone(assert_approval_covers(
            item, "record_payment", {"amount": 10.0}))

    def test_nested_argument_values_are_compared(self):
        item = self.queue.find_by_id(_scoped_tool(
            self.queue, "some_tool",
            {"opts": {"qty": 3, "tags": ["a", "b"]}}))
        self.assertIsNone(assert_approval_covers(
            item, "some_tool", {"opts": {"qty": 3, "tags": ["a", "b"]}}))
        self.assertIn("authorizes one action", assert_approval_covers(
            item, "some_tool", {"opts": {"qty": 3, "tags": ["a", "c"]}}))

    def test_booleans_are_not_treated_as_numbers(self):
        """`True == 1` in Python; an approved flag must not match a quantity."""
        item = self.queue.find_by_id(_scoped_tool(
            self.queue, "some_tool", {"flag": True}))
        self.assertIsNone(assert_approval_covers(
            item, "some_tool", {"flag": True}))
        self.assertIn("authorizes one action", assert_approval_covers(
            item, "some_tool", {"flag": 1}))

    def test_status_is_checked_before_scope(self):
        item = self.queue.enqueue_payment("pay", "p", amount=10.0)
        refusal = assert_approval_covers(item, "record_payment", {"amount": 10.0})
        self.assertIn("not approved", refusal)
        self.queue.approve(item.id)
        self.assertIsNone(assert_approval_covers(
            item, "record_payment", {"amount": 10.0}))

    def test_denied_approval_is_refused(self):
        item = self.queue.enqueue_payment("pay", "p", amount=10.0)
        self.queue.deny(item.id, notes="no")
        self.assertIn("not approved", assert_approval_covers(
            item, "record_payment", {"amount": 10.0}))


class TestEnqueuePaymentRecordsScope(unittest.TestCase):
    """`enqueue_payment` must record what the operator is authorizing."""

    def setUp(self):
        self.queue = HumanApprovalQueue.instance()

    def tearDown(self):
        try:
            self.queue.clear_all()
        except Exception:
            pass

    def test_scope_names_the_tool_and_the_amount(self):
        item = self.queue.enqueue_payment("pay", "p", amount=42.5,
                                          currency="USD")
        scope = approval_scope(item)
        self.assertEqual(scope["tool"], "record_payment")
        self.assertEqual(scope["arguments"]["amount"], 42.5)
        self.assertEqual(scope["arguments"]["currency"], "USD")

    def test_kind_is_still_payment(self):
        item = self.queue.enqueue_payment("pay", "p", amount=1.0)
        self.assertIs(item.kind, ApprovalKind.PAYMENT)

    def test_caller_supplied_payload_is_preserved_verbatim(self):
        """A payload the caller passes is not rewritten (redaction contract)."""
        sensitive = {"bank_account": "****-1234", "amount": 1000.0}
        item = self.queue.enqueue_payment("pay", "p", amount=1000.0,
                                          payload=sensitive)
        self.assertEqual(item.payload, sensitive)
        # Scope still resolves — via `details`, which `approval_scope` falls
        # back to when `payload` carries no tool name.
        self.assertEqual(approval_scope(item)["tool"], "record_payment")

    def test_legacy_amount_and_currency_details_are_still_present(self):
        """Existing consumers read `details["amount"]` directly."""
        item = self.queue.enqueue_payment("pay", "p", amount=7.0,
                                          currency="usd")
        self.assertEqual(item.details["amount"], 7.0)
        self.assertEqual(item.details["currency"], "usd")


class TestApprovalIdStampedOnExecute(unittest.TestCase):
    """The approve→execute path must bind the call to the approved item.

    `main._execute_approved_action` reads `payload["tool"]` and
    `payload["arguments"]` and re-dispatches with `approved=True`. The model
    cannot know an approval id before the item exists, so the queued arguments
    carry no `approval_id` — and the HIGH-TRUST tools would then refuse a call
    a human genuinely approved. The id is stamped at execution time.
    """

    def test_stamp_makes_the_queued_arguments_executable(self):
        """Read the production stamp site, do not reimplement it."""
        import inspect

        import main as app_main
        src = inspect.getsource(app_main.MainWindow._execute_approved_action)
        self.assertIn('arguments["approval_id"] = item_id', src,
                      "the approved id is no longer stamped into the call")
        # The stamp must happen BEFORE dispatch, and on a copy.
        self.assertLess(src.index("dict(arguments)"),
                        src.index("execute_tool("))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
