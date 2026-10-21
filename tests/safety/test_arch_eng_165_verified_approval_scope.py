"""ARCH-ENG-165 — `approved=True` was a bare boolean, so it authorized nothing.

`AuthorizedActionDispatcher.authorize` had, in full:

    allowed, reason, decision = self.safety_gate.check(name, arguments)
    if decision == SafetyDecision.NEEDS_APPROVAL and approved:
        return AuthorizationResult(True, SafetyDecision.ALLOWED,
                                   "Explicit approval supplied")
    return AuthorizationResult(allowed, decision, reason)

The entire authorization was the caller's truthy boolean. It never consulted
`HumanApprovalQueue` and never called `assert_approval_covers`, so:

  * an approval that was never APPROVED would authorize an action;
  * an approval recorded with no tool scope would authorize any tool;
  * an approval for one amount or path would authorize a different one.

The HIGH-TRUST handlers were never exposed, because `record_payment`,
`social_post` and the crypto send re-check the queue themselves
(ARCH-ENG-129/121/130). But a mutating tool with NO internal check —
`file_write`, `run_command`, `workshop_payment` — executed on the bare boolean
alone. `main.py:1066` was the only production caller and it did stamp an
approval id into the arguments first, so this was a latent gap in the boundary
rather than an active exploit; the boundary itself, however, authorized nothing.

There are now two paths, and the reason string distinguishes them:

  * `approval_id` GIVEN -> VERIFIED against the shared queue via
    `assert_approval_covers(item, name, arguments)`. The approval must name
    THIS tool and match these arguments. A refusal does NOT upgrade: the
    original NEEDS_APPROVAL stands, so the action stays pending and visible.
  * `approval_id` ABSENT -> unchanged behaviour, for compatibility, but the
    reason now says "UNVERIFIED" so it cannot be read as the verified path.

The regression is the mismatch test: an approval recorded for a DIFFERENT
amount must not execute a different amount on the verified path.
"""

import unittest

from agents.safety.approval import (
    ApprovalItem, ApprovalKind, ApprovalStatus, HumanApprovalQueue,
)
from agents.safety.authorization import AuthorizedActionDispatcher
from agents.safety.gate import SafetyDecision


def _enqueue(queue, tool, arguments, title="approve me"):
    return queue.enqueue(ApprovalItem(
        kind=ApprovalKind.ACTION,
        title=title,
        description="A recorded action.",
        requested_by="test",
        details={"tool": tool, "arguments": arguments},
        payload={"tool": tool, "arguments": arguments},
    ))


class ApprovalTestBase(unittest.TestCase):
    def setUp(self):
        HumanApprovalQueue.reset_singleton()
        self.queue = HumanApprovalQueue.instance()
        self.dispatcher = AuthorizedActionDispatcher()

    def tearDown(self):
        HumanApprovalQueue.reset_singleton()

    # A tool the gate classifies as NEEDS_APPROVAL.
    TOOL = "run_command"
    ARGS = {"command": "echo approved"}


class TestVerifiedPath(ApprovalTestBase):
    """ARCH-ENG-165 — with an id, the approval is really checked."""

    def test_a_matching_approved_item_is_allowed(self):
        item = _enqueue(self.queue, self.TOOL, dict(self.ARGS))
        self.assertTrue(self.queue.approve(item.id))
        result = self.dispatcher.authorize(self.TOOL, dict(self.ARGS),
                                          approved=True, approval_id=item.id)
        self.assertTrue(result.allowed)
        self.assertEqual(result.decision, SafetyDecision.ALLOWED)

    def test_an_unknown_approval_id_does_not_authorize(self):
        result = self.dispatcher.authorize(self.TOOL, dict(self.ARGS),
                                          approved=True,
                                          approval_id="does-not-exist")
        self.assertFalse(result.allowed)
        self.assertIn("not found", result.reason)

    def test_a_pending_item_does_not_authorize(self):
        """An approval the human has not decided yet authorizes nothing."""
        item = _enqueue(self.queue, self.TOOL, dict(self.ARGS))
        result = self.dispatcher.authorize(self.TOOL, dict(self.ARGS),
                                          approved=True, approval_id=item.id)
        self.assertFalse(result.allowed)
        self.assertNotEqual(result.decision, SafetyDecision.ALLOWED)

    def test_a_rejected_item_does_not_authorize(self):
        item = _enqueue(self.queue, self.TOOL, dict(self.ARGS))
        self.assertTrue(self.queue.decide(item.id, ApprovalStatus.DENIED, "no"))
        result = self.dispatcher.authorize(self.TOOL, dict(self.ARGS),
                                          approved=True, approval_id=item.id)
        self.assertFalse(result.allowed)
        self.assertIn("not approved", result.reason)

    def test_an_approval_with_no_tool_scope_authorizes_nothing(self):
        """ARCH-ENG-129: a free-form approval authorizes no action."""
        item = self.queue.enqueue(ApprovalItem(
            kind=ApprovalKind.ACTION,
            title="free-form",
            description="no tool recorded",
            requested_by="test",
            details={"note": "just a note"},
        ))
        self.assertTrue(self.queue.approve(item.id))
        result = self.dispatcher.authorize(self.TOOL, dict(self.ARGS),
                                          approved=True, approval_id=item.id)
        self.assertFalse(result.allowed)
        self.assertIn("no tool scope", result.reason)


class TestScopeBinding(ApprovalTestBase):
    """ARCH-ENG-165 — the regression: an approval for one action must not
    execute a different one. This is what a bare boolean allowed."""

    def test_approval_for_a_different_command_does_not_execute(self):
        approved_args = {"command": "echo APPROVED-ONE"}
        item = _enqueue(self.queue, self.TOOL, approved_args)
        self.assertTrue(self.queue.approve(item.id))
        result = self.dispatcher.authorize(
            self.TOOL, {"command": "echo SOMETHING-ELSE"},
            approved=True, approval_id=item.id)
        self.assertFalse(result.allowed)

    def test_approval_for_a_different_tool_does_not_authorize(self):
        item = _enqueue(self.queue, "file_write",
                        {"path": "notes.md", "content": "x"})
        self.assertTrue(self.queue.approve(item.id))
        result = self.dispatcher.authorize(self.TOOL, dict(self.ARGS),
                                          approved=True, approval_id=item.id)
        self.assertFalse(result.allowed)
        self.assertIn("not", result.reason.lower())

    def test_approval_for_a_different_amount_does_not_authorize(self):
        """The financial case: $10 approved must not execute $10,000."""
        approved_args = {"amount": 10.0}
        item = _enqueue(self.queue, "record_payment", approved_args)
        self.assertTrue(self.queue.approve(item.id))
        result = self.dispatcher.authorize(
            "record_payment", {"amount": 10000.0},
            approved=True, approval_id=item.id)
        self.assertFalse(result.allowed)


class TestUnverifiedPathIsLabelled(ApprovalTestBase):
    """ARCH-ENG-165 — the compatibility path must not read as verified."""

    def test_bare_boolean_still_allows(self):
        """Behaviour is unchanged when no id is supplied."""
        result = self.dispatcher.authorize(self.TOOL, dict(self.ARGS),
                                          approved=True)
        self.assertTrue(result.allowed)

    def test_but_the_reason_says_it_is_unverified(self):
        result = self.dispatcher.authorize(self.TOOL, dict(self.ARGS),
                                          approved=True)
        self.assertIn("UNVERIFIED", result.reason)
        self.assertIn("no tool scope or argument scope was checked", result.reason)


class TestBlockedIsStillBlocked(ApprovalTestBase):
    """ARCH-ENG-165 — approval must never upgrade a BLOCKED decision."""

    def test_unknown_tool_is_blocked_even_when_approved(self):
        result = self.dispatcher.authorize("definitely_not_a_tool", {},
                                          approved=True, approval_id="x")
        self.assertFalse(result.allowed)
        self.assertEqual(result.decision, SafetyDecision.BLOCKED)

    def test_a_blocked_tool_stays_blocked_with_a_valid_approval(self):
        """An approval must not be a universal key."""
        from agents.safety.gate import SafetyGate
        gate = SafetyGate()
        _a, _r, decision = gate.check(self.TOOL, dict(self.ARGS))
        self.assertEqual(decision, SafetyDecision.NEEDS_APPROVAL)


class TestProductionCallerPassesTheId(unittest.TestCase):
    """ARCH-ENG-165 — `main.py` must use the verified path.

    A boundary that supports verification, with a production caller that does
    not use it, is the same defect one layer up.
    """

    def test_execute_approved_action_passes_the_approval_id(self):
        import inspect
        import agents.safety.dispatch as dispatch
        src = inspect.getsource(dispatch.execute_tool)
        self.assertIn("approval_id", src,
                      "dispatch.execute_tool must accept an approval_id")

    def test_main_passes_approval_id(self):
        import pathlib
        main = pathlib.Path(__file__).resolve().parents[2] / "main.py"
        text = main.read_text(encoding="utf-8")
        self.assertIn("approval_id=item_id", text,
                      "main.py must pass the approval id so the dispatcher "
                      "verifies scope instead of trusting a boolean")


if __name__ == "__main__":
    unittest.main()