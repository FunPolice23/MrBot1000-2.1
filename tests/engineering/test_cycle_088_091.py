"""ARCH-ENG-088..091 — the findings left unresolved at the end of v2.1.61.

Each test reproduces the defect by execution against the real implementation
(no mocks of the code under test) and then asserts the fixed behaviour.

* 088 — SafetyGuard kept a private pending list, so a flagged submission
        appeared nowhere the operator could approve it.
* 089 — nothing ever called RecursionDetectorLayer.pop(), so a long-lived
        guard refused every later action as a recursion loop.
* 090 — execute_tool refused documented aliases after the human approved
        them: the gate resolved the alias, the handler table did not.
* 091 — an approved submission was terminal: queued, approved, never sent.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.safety.policy import PROJECT_ROOT


def _submission_action(record_id: str = "r1", name: str = "upwork:Write a post"):
    from agents.safety.guard import SafetyAction
    return SafetyAction(
        action_type="submit_proposal",
        name=name,
        arguments={"record_id": record_id},
        estimated_cost=0.0,
        platform="upwork",
        requires_funds=False,
    )


@pytest.fixture
def clean_queue():
    """A HumanApprovalQueue with no leftover items, restored after the test.

    Restores by direct list assignment, NOT by re-enqueueing: enqueue()
    unconditionally resets status to PENDING, so re-enqueueing would resurrect
    every previously-decided item as a pending approval — erasing recorded
    human decisions and leaking phantom approvals into unrelated tests.
    """
    from agents.safety.approval import HumanApprovalQueue
    queue = HumanApprovalQueue.instance()
    saved = list(queue._items)
    queue.clear_all()
    try:
        yield queue
    finally:
        queue.clear_all()
        queue._items.extend(saved)


# ── ARCH-ENG-088: one queue, visible to the operator ─────────────────────

def test_flagged_action_reaches_the_operator_visible_queue(clean_queue):
    """The Approvals panel reads HumanApprovalQueue, not the guard's list.

    Reproduced before the fix: guard pending == 1, queue pending == 0, so the
    operator saw "No pending approvals" for a submission awaiting their
    decision.
    """
    from agents.safety.guard import SafetyGuard

    guard = SafetyGuard()
    result = guard.check(_submission_action())
    assert result.action == "flag"

    queue_pending = clean_queue.pending()
    assert len(queue_pending) == 1, "flagged action never reached HumanApprovalQueue"
    assert queue_pending[0].id == guard.get_pending_approvals()[0]["id"]
    assert queue_pending[0].kind.value == "submission"


def test_queued_submission_carries_the_record_id(clean_queue):
    """Without the record id the approval cannot be routed back to a submit."""
    from agents.safety.guard import SafetyGuard

    SafetyGuard().check(_submission_action(record_id="rec-42"))
    item = clean_queue.pending()[0]
    assert item.details["arguments"]["record_id"] == "rec-42"
    assert item.details["action_type"] == "submit_proposal"


def test_payment_is_queued_as_a_payment(clean_queue):
    """A fund-moving action must not be filed as a generic ACTION."""
    from agents.safety.guard import SafetyAction, SafetyGuard

    SafetyGuard().check(SafetyAction(
        action_type="send_payment",
        name="base:0.5USDC->0xabc",
        arguments={"request_id": "q1"},
        requires_funds=True,
        platform="crypto",
    ))
    assert clean_queue.pending()[0].kind.value == "payment"


def test_decision_in_queue_is_visible_to_the_guard(clean_queue):
    """Approving in the GUI must retire the guard's copy of the request."""
    from agents.safety.approval import ApprovalStatus
    from agents.safety.guard import SafetyGuard

    guard = SafetyGuard()
    guard.check(_submission_action())
    approval_id = guard.get_pending_approvals()[0]["id"]

    assert clean_queue.approve(approval_id) is True
    assert guard.get_pending_approvals() == [], "guard still reports a decided item"


def test_guard_cannot_approve_twice(clean_queue):
    """A second approve() must not re-run the same irreversible action."""
    from agents.safety.approval import ApprovalStatus
    from agents.safety.guard import SafetyGuard

    guard = SafetyGuard()
    guard.check(_submission_action())
    approval_id = guard.get_pending_approvals()[0]["id"]

    assert guard.approve(approval_id) is True
    assert guard.approve(approval_id) is False
    assert clean_queue.find_by_id(approval_id).status == ApprovalStatus.APPROVED


def test_guard_reject_propagates_to_the_queue(clean_queue):
    from agents.safety.approval import ApprovalStatus
    from agents.safety.guard import SafetyGuard

    guard = SafetyGuard()
    guard.check(_submission_action())
    approval_id = guard.get_pending_approvals()[0]["id"]

    assert guard.reject(approval_id) is True
    assert clean_queue.find_by_id(approval_id).status == ApprovalStatus.DENIED
    assert guard.get_pending_approvals() == []


def test_pending_approvals_property_still_works(clean_queue):
    """The attribute existed as a list; callers must not break on the change."""
    from agents.safety.guard import SafetyGuard

    guard = SafetyGuard()
    layer = guard.get_layer("human_approval")
    assert layer.pending_approvals == []
    guard.check(_submission_action())
    assert len(layer.pending_approvals) == 1


# ── ARCH-ENG-089: the recursion stack must balance ───────────────────────

def test_many_sequential_actions_are_not_a_recursion_loop():
    """Reproduced: the 11th distinct submission returned
    block / "Call depth exceeded: 10/10". Depth models NESTING; sequential
    independent actions are not nesting.
    """
    from agents.safety.guard import SafetyGuard

    guard = SafetyGuard()
    for i in range(40):
        result = guard.check(_submission_action(
            record_id=f"r{i}", name=f"upwork:Job {i}"))
        assert result.action == "flag", (
            f"action {i} was refused as {result.action}: {result.reasons}")


def test_recursion_stack_is_empty_after_a_check():
    """check() must leave the detector balanced, or depth only ever grows."""
    from agents.safety.guard import RecursionDetectorLayer, SafetyGuard

    guard = SafetyGuard()
    guard.check(_submission_action())
    layer = guard.get_layer("recursion_detector")
    assert isinstance(layer, RecursionDetectorLayer)
    assert layer._call_stack == [], "call stack leaked across checks"


def test_genuine_nesting_is_still_detected():
    """The detector must keep working for the case it exists for."""
    from agents.safety.guard import RecursionDetectorLayer, SafetyResult

    layer = RecursionDetectorLayer({"max_depth": 3})
    for i in range(3):
        layer.check(_submission_action(record_id=f"n{i}", name=f"nested:{i}"))
    blocked = layer.check(_submission_action(record_id="n4", name="nested:4"))
    assert isinstance(blocked, SafetyResult)
    assert blocked.action == "block"
    assert "depth" in blocked.reasons[0].lower()


def test_repeated_identical_calls_are_still_detected():
    """The repeat rule must survive the depth pop.

    Repeats are TEMPORAL (the same action over and over in sequence), depth is
    NESTED. Coupling them to one stack made the naive pop-bracket silently
    disable loop detection, so this asserts the sequential case explicitly.
    """
    from agents.safety.guard import SafetyGuard

    guard = SafetyGuard()
    blocked = None
    for _ in range(6):
        blocked = guard.check(_submission_action(name="loop:same"))
        if blocked is not None and blocked.action == "block":
            break
    assert blocked is not None, "a repeated identical action was never blocked"
    assert blocked.action == "block"
    assert "Repeated calls" in blocked.reasons[0]


def test_sequential_loop_is_blocked_but_distinct_work_is_not():
    """The two rules must not bleed into each other.

    Same name over and over -> repeat block. Distinct names in sequence ->
    must all pass (that was ARCH-ENG-089: refused as "Call depth exceeded").
    """
    from agents.safety.guard import SafetyGuard

    looping = SafetyGuard()
    loop_block = None
    for _ in range(6):
        result = looping.check(_submission_action(name="loop:same"))
        if result.action == "block":
            loop_block = result
            break
    assert loop_block is not None, "sequential loop was not detected"

    distinct = SafetyGuard()
    for i in range(40):
        result = distinct.check(_submission_action(
            record_id=f"r{i}", name=f"upwork:Job {i}"))
        assert result.action == "flag", (
            f"distinct action {i} refused as {result.action}: {result.reasons}")


# ── ARCH-ENG-090: an approved alias must run ─────────────────────────────

def test_approved_alias_executes(clean_queue):
    """Reproduced: execute_tool("write_file", ..., approved=True) returned
    "[Unknown tool: write_file]" — the operator approved an action that could
    never run, while the identical file_write call succeeded.
    """
    from agents.safety.dispatch import execute_tool

    # The path must be inside the project workspace (resolve_project_path
    # confines every tool write); tmp_path is outside it and would be refused
    # for a reason unrelated to this defect.
    rel = os.path.join("tmp", "test_alias_approved.txt")
    target = os.path.join(PROJECT_ROOT, rel)
    try:
        queued = execute_tool("write_file", {"path": rel, "content": "hi"})
        assert "PENDING APPROVAL" in queued

        pending = clean_queue.pending()
        assert len(pending) == 1
        assert clean_queue.approve(pending[0].id) is True

        result = execute_tool("write_file", {"path": rel, "content": "hi"},
                              approved=True)
        assert "Unknown tool" not in result, f"approved alias still refused: {result}"
        assert os.path.exists(target), f"approved alias did not run: {result}"
        with open(target, "r", encoding="utf-8") as fh:
            assert fh.read() == "hi"
    finally:
        if os.path.exists(target):
            os.remove(target)


def test_unapproved_alias_still_does_not_execute(clean_queue):
    """The fix must not turn the alias into an approval bypass."""
    from agents.safety.dispatch import execute_tool

    rel = os.path.join("tmp", "test_alias_unapproved.txt")
    target = os.path.join(PROJECT_ROOT, rel)
    try:
        result = execute_tool("write_file", {"path": rel, "content": "hi"})
        assert "PENDING APPROVAL" in result
        assert not os.path.exists(target)
    finally:
        if os.path.exists(target):
            os.remove(target)


def test_read_only_alias_resolves(clean_queue):
    """read_file / query_database are BLOCKED-by-classification aliases; the
    gate's own verdict must be what the operator sees, not a handler miss.
    """
    from agents.safety.dispatch import execute_tool

    # query_database -> query_db is classified READONLY, so it runs directly.
    result = execute_tool("query_database", {"sql": "SELECT 1"})
    assert "Unknown tool" not in result, f"read-only alias refused: {result}"


def test_truly_unknown_tool_is_still_refused():
    """Canonicalisation must not widen the accepted name set."""
    from agents.safety.dispatch import execute_tool

    assert "Unknown tool" in execute_tool("totally_made_up_tool", {})


# ── ARCH-ENG-091: an approved submission must be sent ────────────────────

def _prepared_record(submitter, record_id_url="https://x/1"):
    record = submitter.prepare_submission(
        "upwork", {"title": "Write a post", "url": record_id_url}, "My proposal")
    gate = submitter.request_approval(record)
    assert gate["status"] == "awaiting_approval"
    assert gate["approval_id"]
    return record


def test_approved_submission_is_actually_submitted(clean_queue, tmp_path):
    """Reproduced: request_approval queued the request and nothing ever read
    the decision back, so an approved submission was never sent.
    """
    from agents.earning.platform_submitter import PlatformSubmitter
    from agents.safety.guard import SafetyGuard

    submitter = PlatformSubmitter(
        safety_guard=SafetyGuard(), evidence_dir=str(tmp_path))
    record = _prepared_record(submitter)

    before = submitter.submit_if_approved(record)
    assert before["status"] == "awaiting_approval"
    assert record.status != "submitted", "sent before the human decided"

    assert clean_queue.approve(record.approval_id) is True
    after = submitter.submit_if_approved(record)
    assert after["ok"] is True, after
    assert after["status"] == "submitted"
    assert record.status == "submitted"


def test_denied_submission_is_never_sent(clean_queue, tmp_path):
    from agents.earning.platform_submitter import PlatformSubmitter
    from agents.safety.guard import SafetyGuard

    submitter = PlatformSubmitter(
        safety_guard=SafetyGuard(), evidence_dir=str(tmp_path))
    record = _prepared_record(submitter, record_id_url="https://x/2")

    assert clean_queue.deny(record.approval_id) is True
    result = submitter.submit_if_approved(record)
    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert record.status != "submitted"


def test_deferred_submission_is_never_sent(clean_queue, tmp_path):
    """Defer is a decision, and it is not an approval."""
    from agents.earning.platform_submitter import PlatformSubmitter
    from agents.safety.guard import SafetyGuard

    submitter = PlatformSubmitter(
        safety_guard=SafetyGuard(), evidence_dir=str(tmp_path))
    record = _prepared_record(submitter, record_id_url="https://x/3")

    assert clean_queue.defer(record.approval_id) is True
    result = submitter.submit_if_approved(record)
    assert result["ok"] is False
    assert record.status != "submitted"


def test_submission_without_a_queued_approval_is_refused(clean_queue, tmp_path):
    """Fail closed: no queue entry means no provable human decision."""
    from agents.earning.platform_submitter import PlatformSubmitter

    submitter = PlatformSubmitter(evidence_dir=str(tmp_path))
    record = submitter.prepare_submission(
        "upwork", {"title": "T", "url": "https://x/4"}, "P")
    result = submitter.submit_if_approved(record)
    assert result["ok"] is False
    assert record.status != "submitted"


def test_submit_still_refuses_an_unapproved_record(tmp_path):
    """The pre-existing gate must not be weakened by the new entry point."""
    from agents.earning.platform_submitter import PlatformSubmitter

    submitter = PlatformSubmitter(evidence_dir=str(tmp_path))
    record = submitter.prepare_submission(
        "upwork", {"title": "T", "url": "https://x/5"}, "P")
    result = submitter.submit(record)
    assert result["ok"] is False
    assert "Not approved" in result["error"]


def test_earning_tab_injects_a_real_guard():
    """The guard-injection consequence recorded at the end of v2.1.61.

    gui/tabs/earning_tab.py built PlatformSubmitter() with no guard, so
    request_approval failed CLOSED and Submit always reported "no safety guard
    configured" — the feature was unusable.

    Parsed with AST rather than substring-matched: a plain `"PlatformSubmitter()"
    not in src` check also matches this defect's own explanatory comment, so it
    would fail on a correct fix and pass on a badly-commented one.
    """
    import ast

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "gui", "tabs", "earning_tab.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    constructions = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "PlatformSubmitter":
            continue
        kwargs = {kw.arg for kw in node.keywords}
        constructions.append((bool(node.args), "safety_guard" in kwargs))

    assert constructions, "Earning tab no longer constructs a PlatformSubmitter"
    assert all(guard for _positional, guard in constructions), (
        f"an unguarded PlatformSubmitter() is still constructed: {constructions}")


# ── Review-pass findings (v2.1.62) ───────────────────────────────────────

class _RecordingAdapter:
    """A real platform adapter, so submit() takes the live-adapter branch."""

    def __init__(self):
        self.calls = 0

    def submit_proposal(self, payload, confirmed_by_human=False):
        self.calls += 1
        return {"ok": True, "external_id": self.calls}


def test_approved_submission_is_not_sent_twice(clean_queue, tmp_path):
    """An irreversible submission must not be re-executable.

    The queue keeps a decided item APPROVED forever, so a second call to the
    new public entry point re-ran the submission. Reproduced: two calls with a
    real adapter registered produced two external submissions.
    """
    from agents.earning.platform_submitter import PlatformSubmitter
    from agents.safety.guard import SafetyGuard

    submitter = PlatformSubmitter(
        safety_guard=SafetyGuard(), evidence_dir=str(tmp_path))
    adapter = _RecordingAdapter()
    submitter.register_platform("upwork", adapter)

    record = _prepared_record(submitter)
    assert clean_queue.approve(record.approval_id) is True

    first = submitter.submit_if_approved(record)
    assert first["ok"] is True, first
    assert adapter.calls == 1

    second = submitter.submit_if_approved(record)
    assert second["ok"] is False, "the same submission was sent twice"
    assert adapter.calls == 1, "adapter was invoked again"


def test_real_adapter_submission_is_sent_once_after_approval(clean_queue, tmp_path):
    """The live-adapter branch must actually reach the adapter, exactly once."""
    from agents.earning.platform_submitter import PlatformSubmitter
    from agents.safety.guard import SafetyGuard

    submitter = PlatformSubmitter(
        safety_guard=SafetyGuard(), evidence_dir=str(tmp_path))
    adapter = _RecordingAdapter()
    submitter.register_platform("upwork", adapter)

    record = _prepared_record(submitter)
    # Before approval the adapter must not be touched.
    pending = submitter.submit_if_approved(record)
    assert pending["status"] == "awaiting_approval"
    assert adapter.calls == 0

    assert clean_queue.approve(record.approval_id) is True
    result = submitter.submit_if_approved(record)
    assert result["ok"] is True, result
    assert adapter.calls == 1
    assert record.status == "submitted"


def test_failed_queue_decision_does_not_mark_the_record_approved(clean_queue):
    """approve() must not report success when the queue did not record it.

    The first cut set the local record to 'approved' (and fired the then-live
    approval callback) before checking the queue result, so a caller that
    ignored the return value would treat a failed write as a human approval.

    ARCH-ENG-259 (AE-03): the callback seam this test used to instrument was
    itself dead -- `HumanApprovalQueue` owns the DECISION now, and the setter
    was never called by production code. The seam is gone; the guarantee is
    unchanged and is asserted where the state lives (the return value and the
    owned record), not through a callback that no longer exists.
    """
    from agents.safety.guard import SafetyGuard

    guard = SafetyGuard()
    guard.check(_submission_action())
    approval_id = guard.get_pending_approvals()[0]["id"]

    # Remove the mirrored item so the queue write cannot succeed.
    clean_queue.clear_all()

    assert guard.approve(approval_id) is False
    # The record must still be pending, not approved.
    assert guard.get_layer("human_approval")._owned[approval_id]["status"] == "pending"


def test_owned_map_is_bounded_on_a_long_lived_guard(clean_queue):
    """A process-lifetime guard must not accumulate DECIDED records forever.

    The Safety & Tools tab polls get_pending() on a timer, so an unbounded
    _owned map of decided requests would be walked on every refresh.

    Only decided records are pruned. PENDING ones are deliberately retained —
    each is an approval request a human has not answered, and dropping one
    would lose the request — so this asserts the bound on decided volume.
    """
    from agents.safety.guard import SafetyGuard

    guard = SafetyGuard({"human_approval": {"owned_max": 8}})
    layer = guard.get_layer("human_approval")
    assert layer._owned_max == 8

    ids = []
    for i in range(40):
        guard.check(_submission_action(record_id=f"r{i}", name=f"upwork:Job {i}"))
        ids.append(layer.pending_approvals[-1]["id"])
        # Decide each one so it becomes prunable.
        clean_queue.approve(ids[-1])

    # Reading pending retires the decided records and prunes them.
    guard.get_pending_approvals()
    assert len(layer._owned) <= 8, (
        f"_owned grew to {len(layer._owned)} decided entries on a bounded guard")

    # A live, unanswered request is never pruned away.
    guard.check(_submission_action(record_id="live", name="upwork:Live"))
    assert layer.get_pending(), "a pending request was pruned"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
