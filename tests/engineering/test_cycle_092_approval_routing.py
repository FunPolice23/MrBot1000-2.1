"""Cycle 092 — human-approval routing integrity (two GUI surfaces, one approval).

Two defects, both in the path from "a human clicked Approve" to "the
irreversible action ran":

DEFECT 1 — ``main.py:_execute_approved_action`` had no idempotency guard. A
decided queue item stays APPROVED forever and TWO surfaces route the same
decision to that handler (``ApprovalPanel`` emits ``item_decided``;
``SafetyTab._route_decision`` calls the handler directly), so ONE human
approval ran the irreversible action once per signal emission. Reproduced:
1 approval -> 2 executions of ``run_command``, queue still 1 item / 0 pending.
Contrast: ``PlatformSubmitter.submit_if_approved`` already refuses to send
twice, so the SUBMISSION path needed no second guard.

DEFECT 2 — ``gui/tabs/safety_tools_tab.py`` silently dropped the Approve click
for any approval the SafetyGuard did not itself enqueue. ``SafetyGuard.approve()``
only knows its own ``_owned`` ids, and ``_refresh_approvals`` listed only
``guard.get_pending_approvals()``, so items the chat dispatcher and the Big
Brain enqueue straight into ``HumanApprovalQueue`` were invisible AND
unactionable there. Reproduced: queue.pending()==2, table rows==0, and
``_on_approve`` left the item 'pending' with no log and no error.

TESTING APPROACH
``main.py`` constructs a QApplication-dependent class, so it cannot be
instantiated in a unit test; the handler is exercised by binding the REAL
unbound methods onto a minimal shim host (``MainWindow._execute_approved_action
.__get__(shim)``), which is exactly how the desktop wires them and needs no
QApplication. ``safety_tools_tab.py`` is a real QWidget: tests/conftest.py
already guarantees exactly one session-wide offscreen QApplication for every
test module, so ``SafetyTab`` is constructed for real (the established pattern
in tests/gui/) rather than mocking the widget.

``agents.safety.dispatch.execute_tool`` is monkeypatched to a counter: no
irreversible command is ever run by these tests, they only count calls.
"""
from __future__ import annotations

import pytest

from agents.safety import dispatch
from agents.safety.approval import (
    ApprovalItem,
    ApprovalKind,
    ApprovalStatus,
    HumanApprovalQueue,
)
from agents.safety.guard import SafetyAction, SafetyGuard


# ── helpers ─────────────────────────────────────────────────────────────────

class _Signal:
    """Stands in for a Qt signal's ``emit`` so handlers can run headless."""

    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class _HandlerHost:
    """Minimal host for the REAL MainWindow approval handlers.

    Only the attributes those handlers touch are provided, so the production
    code under test is the real thing while ``MainWindow.__init__`` (which
    starts manager threads and a QApplication) is never entered.
    """

    def __init__(self, queue):
        self.approval_queue = queue
        self.log_signal = _Signal()
        self._executed_approval_ids = set()
        self._earning_tab = None
        import main
        self._execute_approved_action = (
            main.MainWindow._execute_approved_action.__get__(self))
        self._on_approval_decided = (
            main.MainWindow._on_approval_decided.__get__(self))
        self._execute_approved_submission = (
            main.MainWindow._execute_approved_submission.__get__(self))

    def _refresh_approval_alert(self):  # GUI-only; not under test here
        pass


@pytest.fixture
def queue():
    """A fresh, isolated approval queue per test (singleton is process-wide)."""
    HumanApprovalQueue.reset_singleton()
    q = HumanApprovalQueue.instance()
    yield q
    HumanApprovalQueue.reset_singleton()


@pytest.fixture
def executed_tools(monkeypatch):
    """Count ``execute_tool`` calls instead of running any irreversible tool."""
    calls = []

    def fake_execute_tool(tool, arguments, approved=False):
        calls.append({"tool": tool, "arguments": arguments,
                      "approved": approved})
        return f"ran {tool}"

    monkeypatch.setattr(dispatch, "execute_tool", fake_execute_tool)
    return calls


def _enqueue_action(queue, tool, arguments, requested_by="dialogue"):
    return queue.enqueue(ApprovalItem(
        kind=ApprovalKind.ACTION,
        title=f"Chat tool request: {tool}",
        description=f"The chat requested {tool}.",
        requested_by=requested_by,
        details={"tool": tool, "arguments": arguments},
        payload={"tool": tool, "arguments": arguments},
    ))


# ── DEFECT 1: one approval must execute an irreversible action at most once ──

def test_one_approval_executes_irreversible_action_once(queue, executed_tools):
    """The reproduction: two surfaces deliver the same approval -> ONE run.

    ``ApprovalPanel`` emits ``item_decided`` and ``SafetyTab._route_decision``
    calls the handler; both land in ``_on_approval_decided``.
    """
    host = _HandlerHost(queue)
    item = _enqueue_action(queue, "run_command", {"command": "echo SENT"})
    assert queue.approve(item.id) is True

    host._on_approval_decided(item.id, ApprovalStatus.APPROVED, "panel")
    host._on_approval_decided(item.id, ApprovalStatus.APPROVED, "safety tab")

    assert len(executed_tools) == 1, (
        "one human approval executed the irreversible action "
        f"{len(executed_tools)} times")
    assert executed_tools[0]["tool"] == "run_command"


def test_duplicate_decision_is_logged_for_the_operator(queue, executed_tools):
    """A re-emission must not look like a silently dead click."""
    host = _HandlerHost(queue)
    item = _enqueue_action(queue, "run_command", {"command": "echo SENT"})
    queue.approve(item.id)

    host._on_approval_decided(item.id, ApprovalStatus.APPROVED, "panel")
    first_log_count = len(host.log_signal.messages)
    host._on_approval_decided(item.id, ApprovalStatus.APPROVED, "safety tab")

    assert len(executed_tools) == 1
    new_messages = host.log_signal.messages[first_log_count:]
    assert any("already executed" in m and item.id in m for m in new_messages), (
        f"operator got no explanation for the no-op click: {new_messages}")


def test_second_distinct_approval_still_executes(queue, executed_tools):
    """The guard is per approval id — it must not suppress a NEW approval."""
    host = _HandlerHost(queue)
    first = _enqueue_action(queue, "run_command", {"command": "echo ONE"})
    second = _enqueue_action(queue, "run_command", {"command": "echo TWO"})
    queue.approve(first.id)
    queue.approve(second.id)

    host._on_approval_decided(first.id, ApprovalStatus.APPROVED, "panel")
    host._on_approval_decided(second.id, ApprovalStatus.APPROVED, "panel")
    # And a re-emission of each is still refused.
    host._on_approval_decided(first.id, ApprovalStatus.APPROVED, "safety tab")
    host._on_approval_decided(second.id, ApprovalStatus.APPROVED, "safety tab")

    assert len(executed_tools) == 2
    assert {c["arguments"]["command"] for c in executed_tools} == {
        "echo ONE", "echo TWO"}


def test_rejected_or_pending_item_never_executes(queue, executed_tools):
    """The guard must not weaken the queue re-read: nothing runs unless the
    queue itself records APPROVED, and a forged signal argument is ignored."""
    host = _HandlerHost(queue)
    item = _enqueue_action(queue, "run_command", {"command": "echo SENT"})

    # PENDING item, but the signal argument claims APPROVED.
    host._on_approval_decided(item.id, ApprovalStatus.APPROVED, "forged")
    assert executed_tools == []

    # Genuinely denied: still nothing runs.
    queue.deny(item.id)
    host._on_approval_decided(item.id, ApprovalStatus.APPROVED, "forged")
    assert executed_tools == []


def test_unknown_approval_id_is_ignored(queue, executed_tools):
    host = _HandlerHost(queue)
    host._on_approval_decided("no-such-id", ApprovalStatus.APPROVED, "x")
    assert executed_tools == []


def test_submission_path_is_consumed_once_by_the_submitter(queue):
    """``PlatformSubmitter.submit_if_approved`` already refuses to send twice,
    so ``_execute_approved_submission`` must NOT need a second ledger.

    Driven through the real request_approval -> human approve -> submit path so
    the queue re-read inside the submitter is exercised for real.
    """
    from agents.earning.platform_submitter import PlatformSubmitter

    guard = SafetyGuard()
    submitter = PlatformSubmitter(safety_guard=guard)
    sent = []

    class _Adapter:
        def submit_proposal(self, payload, confirmed_by_human=False):
            sent.append(payload)
            return {"ok": True}

    submitter.register_platform("fake", _Adapter())
    record = submitter.prepare_submission(
        "fake", {"url": "http://example.test/1", "title": "T"}, "proposal")
    requested = submitter.request_approval(record)
    assert requested["ok"] is True and requested["approval_id"], (
        "the submission was never queued for human approval")
    assert queue.approve(record.approval_id) is True

    first = submitter.submit_if_approved(record)
    second = submitter.submit_if_approved(record)

    assert first["ok"] is True
    assert second["ok"] is False and "already executed" in second["error"]
    assert len(sent) == 1, "one approval sent the submission twice"


# ── DEFECT 2: the human's decision on the Safety & Tools tab is never dropped ──

@pytest.fixture
def safety_tab(queue):
    """A real SafetyTab (conftest guarantees the offscreen QApplication)."""
    from gui.tabs.safety_tools_tab import SafetyTab
    tab = SafetyTab()
    tab.approval_queue = queue
    tab.refresh_timer.stop()
    yield tab


def _select_row(tab, approval_id):
    for row in range(tab.approvals_table.rowCount()):
        if tab.approvals_table.item(row, 0).text() == approval_id:
            tab.approvals_table.setCurrentCell(row, 0)
            return True
    return False


def test_refresh_lists_every_pending_item_not_only_guard_owned(
        safety_tab, queue):
    """The reproduction: dispatch-origin items were invisible in the table."""
    guard = SafetyGuard()
    # A guard-owned request (a high-trust action).
    guard.check(SafetyAction(
        action_type="submit_proposal", name="submit_proposal",
        arguments={}, requires_funds=False, estimated_cost=0.0))
    # Two items enqueued straight into the queue by chat dispatch.
    dispatch_ids = [
        _enqueue_action(queue, "run_command", {"command": "echo A"}).id,
        _enqueue_action(queue, "file_write", {"path": "x.txt"}).id,
    ]

    safety_tab.safety_guard = guard
    safety_tab.refresh()
    listed = [safety_tab.approvals_table.item(r, 0).text()
              for r in range(safety_tab.approvals_table.rowCount())]

    assert len(listed) == len(queue.pending()), (
        f"table showed {listed} but the queue holds {len(queue.pending())} "
        "pending item(s)")
    for approval_id in dispatch_ids:
        assert approval_id in listed, (
            f"dispatch-origin approval {approval_id} is not listed, so the "
            "operator cannot see or select it")


def test_guard_owned_and_dispatch_items_are_both_selectable(safety_tab, queue):
    """The id column must carry the real queue id for the approve path."""
    guard = SafetyGuard()
    guard.check(SafetyAction(
        action_type="submit_proposal", name="submit_proposal",
        arguments={}, requires_funds=False, estimated_cost=0.0))
    dispatch_id = _enqueue_action(
        queue, "run_command", {"command": "echo A"}).id

    safety_tab.safety_guard = guard
    safety_tab.refresh()
    ids = {safety_tab.approvals_table.item(r, 0).text()
           for r in range(safety_tab.approvals_table.rowCount())}
    assert dispatch_id in ids
    assert any(queue.find_by_id(i) is not None for i in ids), (
        "a listed id does not resolve in the queue, so approving it would "
        "be a no-op")


def test_approve_records_decision_when_guard_does_not_own_the_id(
        safety_tab, queue):
    """The reproduction: the click was silently dropped."""
    dispatch_id = _enqueue_action(
        queue, "run_command", {"command": "echo A"}).id
    safety_tab.safety_guard = SafetyGuard()
    safety_tab.refresh()

    assert _select_row(safety_tab, dispatch_id)
    safety_tab._on_approve()

    item = queue.find_by_id(dispatch_id)
    assert item is not None
    assert item.status == ApprovalStatus.APPROVED, (
        "the human's Approve click was dropped: the queue item is still "
        f"{item.status.value}")


def test_approve_routes_to_the_app_decision_handler(safety_tab, queue):
    """A recorded approval must reach ``_on_approval_decided``."""
    from PySide6.QtWidgets import QWidget

    dispatch_id = _enqueue_action(
        queue, "run_command", {"command": "echo A"}).id
    safety_tab.safety_guard = SafetyGuard()

    routed = []
    # parent() must be a QWidget; the handler attribute is what is read.
    parent = QWidget()
    parent._on_approval_decided = (
        lambda item_id, status, notes: routed.append((item_id, status, notes)))
    safety_tab.setParent(parent)

    safety_tab.refresh()
    assert _select_row(safety_tab, dispatch_id)
    safety_tab._on_approve()

    assert routed and routed[0][0] == dispatch_id
    assert routed[0][1] == ApprovalStatus.APPROVED


def test_guard_owned_approval_still_goes_through_the_guard(safety_tab, queue):
    """The guard remains the first choice — the queue is only the fallback."""
    guard = SafetyGuard()
    guard.check(SafetyAction(
        action_type="submit_proposal", name="submit_proposal",
        arguments={}, requires_funds=False, estimated_cost=0.0))
    guard_id = guard.get_pending_approvals()[0]["id"]

    safety_tab.safety_guard = guard
    safety_tab.refresh()
    assert _select_row(safety_tab, guard_id)
    safety_tab._on_approve()

    assert guard.get_pending_approvals() == []
    assert queue.find_by_id(guard_id).status == ApprovalStatus.APPROVED


def test_reject_records_decision_when_guard_does_not_own_the_id(
        safety_tab, queue):
    """A rejection must not be swallowed either."""
    dispatch_id = _enqueue_action(
        queue, "run_command", {"command": "echo A"}).id
    safety_tab.safety_guard = SafetyGuard()
    safety_tab.refresh()

    assert _select_row(safety_tab, dispatch_id)
    safety_tab._on_reject()

    item = queue.find_by_id(dispatch_id)
    assert item.status == ApprovalStatus.DENIED, (
        f"the human's Reject click was dropped: status is {item.status.value}")


def test_rejected_item_is_not_executed_by_the_decision_handler(
        safety_tab, queue, executed_tools):
    """Deny must stay authoritative even after a rejected item is listed."""
    dispatch_id = _enqueue_action(
        queue, "run_command", {"command": "echo A"}).id
    safety_tab.safety_guard = SafetyGuard()
    safety_tab.refresh()
    assert _select_row(safety_tab, dispatch_id)
    safety_tab._on_reject()

    host = _HandlerHost(queue)
    host._on_approval_decided(dispatch_id, ApprovalStatus.APPROVED, "forged")
    assert executed_tools == []


def test_missing_requested_at_does_not_break_the_table(safety_tab, queue):
    """A row without ``requested_at`` must blank the panel silently."""
    _enqueue_action(queue, "run_command", {"command": "echo A"})
    original = ApprovalItem.to_dict

    def without_requested_at(self):
        data = original(self)
        del data["requested_at"]
        return data

    ApprovalItem.to_dict = without_requested_at
    try:
        safety_tab.refresh()
    finally:
        ApprovalItem.to_dict = original

    assert safety_tab.approvals_table.rowCount() == 1
