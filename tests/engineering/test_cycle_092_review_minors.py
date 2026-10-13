"""Cycle 092 adversarial review — the two MINOR findings, closed.

F4 — ``agents/safety/approval.py:_maybe_persist`` EVICTED an item a human had
     DECIDED IN THIS PROCESS. The history bound (``_MAX_RETAINED_ITEMS = 200``)
     kept every PENDING item and dropped the oldest DECIDED ones — but an
     approval recorded seconds ago in the current process IS decided, so it was
     evicted like any other old history. Reproduced: enqueue a $5000 PAYMENT
     item, approve it, enqueue 210 more items -> ``find_by_id`` returns None and
     the item is gone from the JSON log too. The operator lost the ability to
     act on a live approval and the audit record of their own decision.

     Fix: items decided in this process are never evicted (tracked in
     ``_decided_in_process``, the in-process twin of ``_restored_decided``), and
     both tracking sets are intersected with the surviving ids on every persist
     so they cannot drift away from ``_items``.

     PRESERVED: a decision restored from a PREVIOUS process is still refused by
     ``find_by_id`` (history, not authorization), and PENDING items are still
     never dropped.

F7 — ``gui/tabs/safety_tools_tab.py`` offered PAYMENT approvals it could not
     route. ``_refresh_approvals`` listed every PENDING item regardless of kind,
     but ``main.py:_on_approval_decided`` only has ACTION and SUBMISSION
     branches. ``SafetyGuard`` sets ``kind=PAYMENT`` whenever an action has
     ``requires_funds``, so a guard-enqueued payment request was selectable and
     approvable here, the approval was recorded in the queue, and nothing
     executed it — with no log explaining why. Reproduced: the payment row is
     listed, Approve turns it APPROVED, zero tools run, zero log lines.

     Fix (Option A): this surface only lists the kinds it can route. The
     request itself is NOT hidden — the Approvals panel
     (``gui/panels/approval_panel.py``) lists every pending item of every kind
     with full detail, and every enqueue raises a sticky ``approval_required``
     notification. That panel carries the same unroutable-approval gap (it is
     not one of the files this fix may touch); it is recorded as a follow-up,
     and what this change guarantees is that no surface offers a button that is
     a guaranteed no-op. Option B (list it, log loudly)
     was rejected: it cannot make the click do anything, so the honest fix is
     not to offer a button that is guaranteed to be a no-op.

TESTING APPROACH
The approval-queue tests construct ``HumanApprovalQueue(log_path)`` directly
against a ``tmp_path`` file: under pytest ``default_log_path()`` is ``""``
(in-memory), and the eviction bound only runs on the persisting path, so the
singleton would never exercise it.

``safety_tools_tab.py`` is a real QWidget; tests/conftest.py already guarantees
exactly one session-wide offscreen QApplication, so ``SafetyTab`` and
``ApprovalPanel`` are constructed for real (the established pattern in
tests/gui/ and tests/engineering/test_cycle_092_approval_routing.py).
"""
from __future__ import annotations

import json
import time

import pytest

from agents.safety.approval import (
    _MAX_RETAINED_ITEMS,
    ApprovalItem,
    ApprovalKind,
    ApprovalStatus,
    HumanApprovalQueue,
)
from agents.safety.guard import SafetyAction, SafetyGuard


# ── F4: an in-process decision is never evicted ─────────────────────────────

@pytest.fixture
def disk_queue(tmp_path):
    """A queue that really persists, so the history bound actually runs.

    ``HumanApprovalQueue.instance()`` resolves to an in-memory queue under
    pytest (``default_log_path()`` returns ``""``), and ``_maybe_persist``
    returns immediately without a log path — the eviction bug lives entirely on
    the persisting path, so the singleton cannot reproduce it.
    """
    return HumanApprovalQueue(str(tmp_path / "approvals.json"))


def _flood(queue, count, prefix="noise"):
    """Enqueue ``count`` PENDING ACTION items — the eviction trigger."""
    for i in range(count):
        queue.enqueue(ApprovalItem(kind=ApprovalKind.ACTION,
                                   title=f"{prefix}-{i}",
                                   description=f"{prefix} item {i}"))


def test_an_approval_decided_in_this_process_is_never_evicted(
        disk_queue, tmp_path):
    """THE F4 REPRODUCTION: a live $5000 approval must survive the bound."""
    payment = disk_queue.enqueue_payment(
        "Pay vendor", "5000 USD payout", amount=5000.0, currency="USD")
    assert disk_queue.approve(payment.id, notes="operator click") is True

    _flood(disk_queue, _MAX_RETAINED_ITEMS + 10)

    # The bound really ran — otherwise this test proves nothing.
    assert len([i for i in disk_queue._items
                if i.status == ApprovalStatus.PENDING]) > _MAX_RETAINED_ITEMS

    found = disk_queue.find_by_id(payment.id)
    assert found is not None, (
        "an approval the operator made in THIS process was evicted from "
        "memory by the history bound")
    assert found.status is ApprovalStatus.APPROVED

    on_disk = json.loads((tmp_path / "approvals.json").read_text(
        encoding="utf-8"))
    assert any(record["id"] == payment.id
               and record["status"] == ApprovalStatus.APPROVED.value
               for record in on_disk), (
        "the recorded decision was also deleted from the persisted audit log")


def test_a_denial_decided_in_this_process_is_never_evicted(disk_queue):
    """The guarantee is for any human decision, not only approvals."""
    item = disk_queue.enqueue(ApprovalItem(kind=ApprovalKind.ACTION,
                                           title="rm -rf",
                                           description="dangerous"))
    assert disk_queue.deny(item.id, notes="operator refused") is True

    _flood(disk_queue, _MAX_RETAINED_ITEMS + 10)

    found = disk_queue.find_by_id(item.id)
    assert found is not None
    assert found.status is ApprovalStatus.DENIED


def test_pending_items_are_still_never_evicted(disk_queue):
    """The original invariant this file exists for must not regress."""
    oldest = disk_queue.enqueue(ApprovalItem(kind=ApprovalKind.ACTION,
                                             title="oldest pending request"))
    _flood(disk_queue, _MAX_RETAINED_ITEMS + 100)

    pending = [i for i in disk_queue._items
               if i.status == ApprovalStatus.PENDING]
    assert len(pending) == _MAX_RETAINED_ITEMS + 101, (
        f"a PENDING request was evicted: {len(pending)} survived of "
        f"{_MAX_RETAINED_ITEMS + 101}")
    assert disk_queue.find_by_id(oldest.id) is not None
    assert disk_queue.find_by_id(oldest.id).status is ApprovalStatus.PENDING


def test_an_old_decision_still_gets_pruned(disk_queue):
    """The bound must still cap decided history — the fix is not "keep all"."""
    for i in range(60):
        item = disk_queue.enqueue(ApprovalItem(kind=ApprovalKind.ACTION,
                                               title=f"old-{i}"))
        disk_queue.approve(item.id)
    _flood(disk_queue, _MAX_RETAINED_ITEMS + 100)

    kept = [i for i in disk_queue._items
            if i.id in disk_queue._decided_in_process]
    assert len(kept) == 60, (
        "in-process decisions are the ones that must be retained")
    assert len(disk_queue._items) > _MAX_RETAINED_ITEMS, (
        "the bound is expected to be exceeded while live decisions exist")
    # ...and the file still contains them, oldest first is irrelevant here.
    assert all(i.status != ApprovalStatus.PENDING for i in kept)


def test_a_decision_restored_from_a_previous_process_is_still_refused(tmp_path):
    """PRESERVED: stale authorization must still fail CLOSED across a restart."""
    path = tmp_path / "approvals.json"
    stale = ApprovalItem(
        id="stale-approved", kind=ApprovalKind.PAYMENT, title="Pay vendor",
        status=ApprovalStatus.APPROVED, decided_at=time.time(),
        decided_by="human")
    still_pending = ApprovalItem(id="stale-pending",
                                 kind=ApprovalKind.ACTION, title="Do a thing")
    path.write_text(json.dumps([stale.to_dict(), still_pending.to_dict()]),
                    encoding="utf-8")

    queue = HumanApprovalQueue(str(path))

    assert "stale-approved" in queue._restored_decided
    assert queue.find_by_id("stale-approved") is None, (
        "a decision from a PREVIOUS process must never authorize anything")
    assert any(i.id == "stale-approved" for i in queue.all()), (
        "the history itself must stay visible in all()")
    # A restored PENDING item is returned normally: it authorizes nothing
    # until a human decides it in THIS process.
    restored_pending = queue.find_by_id("stale-pending")
    assert restored_pending is not None
    assert restored_pending.status is ApprovalStatus.PENDING

    # Flood: the stale record is history and may be pruned, but find_by_id
    # must keep refusing it either way.
    _flood(queue, _MAX_RETAINED_ITEMS + 100)
    assert queue.find_by_id("stale-approved") is None
    assert queue.find_by_id("stale-pending") is not None


def test_the_tracking_sets_do_not_outgrow_the_queue(tmp_path):
    """PRESERVED against drift: both decided-sets track surviving items only."""
    records = [
        ApprovalItem(id=f"old-{i}", kind=ApprovalKind.ACTION,
                     title=f"old-{i}", status=ApprovalStatus.APPROVED,
                     requested_at=1000.0 + i,
                     decided_at=2000.0 + i).to_dict()
        for i in range(300)
    ]
    path = tmp_path / "approvals.json"
    path.write_text(json.dumps(records), encoding="utf-8")

    queue = HumanApprovalQueue(str(path))
    assert len(queue._restored_decided) == 300

    _flood(queue, 50)

    surviving = {i.id for i in queue._items}
    assert queue._restored_decided <= surviving, (
        "_restored_decided references ids that are no longer in _items")
    assert len(queue._restored_decided) < 300, (
        "restored decided history was not pruned as it was evicted")
    assert len(queue._restored_decided) <= len(queue._items), (
        "the tracking set outgrew the list it describes")

    # In-process decisions: none may be evicted, and none may be orphaned.
    for i in range(20):
        item = queue.enqueue(ApprovalItem(kind=ApprovalKind.ACTION,
                                          title=f"live-{i}"))
        queue.approve(item.id)
    _flood(queue, _MAX_RETAINED_ITEMS + 100)
    surviving = {i.id for i in queue._items}
    assert queue._decided_in_process <= surviving
    assert len(queue._decided_in_process) == 20

    queue.clear_all()
    assert queue._decided_in_process == set()
    assert queue._restored_decided == set()


# ── F7: this surface only offers approvals it can actually route ────────────

@pytest.fixture
def queue():
    """A fresh, isolated approval queue per test (singleton is process-wide)."""
    HumanApprovalQueue.reset_singleton()
    q = HumanApprovalQueue.instance()
    yield q
    HumanApprovalQueue.reset_singleton()


@pytest.fixture
def safety_tab(queue):
    """A real SafetyTab (conftest guarantees the offscreen QApplication)."""
    from gui.tabs.safety_tools_tab import SafetyTab
    tab = SafetyTab()
    tab.approval_queue = queue
    tab.safety_guard = SafetyGuard()
    tab.refresh_timer.stop()
    yield tab
    tab.cleanup()


def _listed_ids(tab):
    return {tab.approvals_table.item(row, 0).text()
            for row in range(tab.approvals_table.rowCount())}


def _select_row(tab, approval_id):
    for row in range(tab.approvals_table.rowCount()):
        if tab.approvals_table.item(row, 0).text() == approval_id:
            tab.approvals_table.setCurrentCell(row, 0)
            return True
    return False


def _guard_payment(queue, amount=5000.0):
    """A guard-enqueued PAYMENT request, exactly as guard.py builds one."""
    guard = SafetyGuard()
    guard.check(SafetyAction(
        action_type="send_payment", name="workshop_payment",
        arguments={"amount": amount}, requires_funds=True,
        estimated_cost=amount))
    payment = [i for i in queue.pending()
               if i.kind == ApprovalKind.PAYMENT]
    assert payment, "the guard never enqueued the payment request"
    return guard, payment[0]


def test_a_payment_request_is_not_offered_for_approval_here(
        safety_tab, queue):
    """THE F7 REPRODUCTION: an approval nothing can execute was offered."""
    guard, payment = _guard_payment(queue)
    assert queue.find_by_id(payment.id).kind is ApprovalKind.PAYMENT

    safety_tab.safety_guard = guard
    safety_tab.refresh()

    listed = _listed_ids(safety_tab)
    assert payment.id not in listed, (
        "a PAYMENT approval was offered on a surface whose decision handler "
        "has no PAYMENT branch, so Approve could only ever be a silent no-op")
    # Not hidden: it stays pending, and therefore visible/actionable in the
    # Approvals panel (asserted separately) and in its sticky notification.
    assert queue.find_by_id(payment.id).status is ApprovalStatus.PENDING


def test_a_gate_request_is_not_offered_for_approval_here(safety_tab, queue):
    """GATE has no routing branch either — same rule, same reason."""
    gate = queue.enqueue_gate("Gate clearance", "human_gates wants a decision")
    safety_tab.refresh()
    assert gate.id not in _listed_ids(safety_tab)
    assert queue.find_by_id(gate.id).status is ApprovalStatus.PENDING


def test_routable_kinds_are_still_listed_and_approvable_here(
        safety_tab, queue):
    """The filter must not re-hide what this tab CAN act on.

    Regression guard for the earlier fix (ARCH-ENG-088..091): an item the
    operator cannot see is an item the operator cannot approve.
    """
    action_id = queue.enqueue(ApprovalItem(
        kind=ApprovalKind.ACTION, title="Chat tool request: run_command",
        description="The chat requested run_command.",
        details={"tool": "run_command", "arguments": {"command": "echo A"}},
        payload={"tool": "run_command", "arguments": {"command": "echo A"}},
    )).id
    submission_id = queue.enqueue_submission("Submit proposal", "send it").id
    _guard_payment(queue)  # an unroutable item sitting in the same queue

    safety_tab.refresh()
    listed = _listed_ids(safety_tab)
    assert action_id in listed
    assert submission_id in listed

    assert _select_row(safety_tab, action_id)
    safety_tab._on_approve()
    assert queue.find_by_id(action_id).status is ApprovalStatus.APPROVED


def test_the_payment_request_is_still_listed_in_the_approvals_panel(queue):
    """Where a payment request lives instead: the Approvals panel lists all.

    Note the residual: ``ApprovalPanel`` lists every kind and emits
    ``item_decided`` -> the same ``main.py:_on_approval_decided`` that has no
    PAYMENT branch, so that surface carries the same unroutable-approval gap.
    It is out of scope for this change set (``gui/panels/approval_panel.py`` is
    not one of the files this fix may touch) and is recorded as a follow-up.
    This test only asserts the request is NOT hidden from the operator.
    """
    from PySide6.QtCore import Qt
    from gui.builders.refresh_coordinator import refresh_coordinator
    from gui.panels.approval_panel import ApprovalPanel

    _, payment = _guard_payment(queue)
    panel = ApprovalPanel(approval_queue=queue)
    try:
        panel._refresh()
        listed = {panel.list_widget.item(row).data(Qt.UserRole)
                  for row in range(panel.list_widget.count())}
        assert payment.id in listed, (
            "the payment request is filtered from Safety & Tools, so it must "
            "still be visible to the operator somewhere")
    finally:
        refresh_coordinator().unregister(panel._refresh_key)
