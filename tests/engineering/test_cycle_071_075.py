"""ARCH-ENG-081..087 — the findings left unresolved at the end of v2.1.57.

Each test reproduces the defect by execution against the real implementation
(no mocks of the code under test) and then asserts the fixed behaviour.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import textwrap
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── ARCH-ENG-081: a real submission request self-approved ──────────────────

def test_guard_flags_action_when_verb_is_in_action_type():
    """platform_submitter puts 'submit_proposal' in action_type, not name.

    Matching only `action.name` meant the guard returned `allow`, so
    request_approval() set record.status = "approved" with no human involved.
    """
    from agents.safety.guard import SafetyAction, SafetyGuard

    guard = SafetyGuard()
    action = SafetyAction(
        action_type="submit_proposal",
        name="upwork:Write a blog post about batteries",
        arguments={"record_id": "r1"},
        estimated_cost=0.0,
        platform="upwork",
        requires_funds=False,
    )
    result = guard.check(action)
    assert result.action == "flag", f"submission was not flagged: {result.action}"
    assert result.allowed is False
    assert any("submit_proposal" in r for r in result.reasons)


def test_guard_flags_payment_when_verb_is_in_action_type():
    """real_crypto_operator uses the same action_type/name convention."""
    from agents.safety.guard import SafetyAction, SafetyGuard

    guard = SafetyGuard()
    action = SafetyAction(
        action_type="send_payment",
        name="base:0.5USDC->0xabc",
        arguments={"request_id": "q1"},
        estimated_cost=0.0,
        platform="crypto",
        requires_funds=True,
    )
    result = guard.check(action)
    assert result.action == "flag", f"payment was not flagged: {result.action}"


def test_guard_still_flags_when_verb_is_in_name():
    """The original matching path must not regress."""
    from agents.safety.guard import SafetyAction, SafetyGuard

    guard = SafetyGuard()
    action = SafetyAction(action_type="tool_call", name="send_payment", arguments={})
    result = guard.check(action)
    assert result.action == "flag"


def test_guard_still_allows_ordinary_reads():
    """The widened match must not start flagging read-only traffic."""
    from agents.safety.guard import SafetyAction, SafetyGuard

    guard = SafetyGuard()
    for action_type, name in (("llm_call", "gpt-4"), ("api_call", "search"),
                              ("tool_call", "web_search")):
        result = guard.check(SafetyAction(action_type=action_type, name=name))
        assert result.action != "flag", f"{action_type}/{name} was wrongly flagged"


def test_submitter_end_to_end_reaches_awaiting_approval():
    """The whole request_approval path now yields a real pending approval."""
    from agents.earning.platform_submitter import PlatformSubmitter
    from agents.safety.guard import SafetyGuard

    submitter = PlatformSubmitter(safety_guard=SafetyGuard())
    record = submitter.prepare_submission(
        "upwork", {"title": "Write a post", "url": "https://x/1"}, "My proposal")
    gate = submitter.request_approval(record)
    assert gate["ok"] is True
    assert gate["status"] == "awaiting_approval"
    assert gate["approval_id"]
    pending = submitter.safety_guard.get_pending_approvals()
    assert any(p["id"] == gate["approval_id"] for p in pending)


# ── ARCH-ENG-082: the GUI Submit button could only raise TypeError ─────────

def test_submitter_submit_rejects_the_kwarg_the_gui_used():
    """Locks in the API shape the GUI must call (record, not proposal_text)."""
    from agents.earning.platform_submitter import PlatformSubmitter

    submitter = PlatformSubmitter()
    with pytest.raises(TypeError):
        submitter.submit(proposal_text="hello")


def test_earning_tab_submit_handler_uses_the_gated_flow():
    """The GUI handler must prepare -> request approval -> submit.

    Read the source rather than driving Qt: the assertion is that the handler
    calls the approval gate, so a submission can never reach submit() unapproved.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "gui", "tabs", "earning_tab.py")
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    handler = src.split("def _on_submit_proposal")[1].split("def _on_")[0]
    # Strip comments so a mention inside a comment cannot satisfy the assert.
    code = "\n".join(ln.split("#", 1)[0] for ln in handler.splitlines())
    assert "proposal_text=" not in code, "GUI still calls submit(proposal_text=)"
    assert "request_approval" in code
    assert "awaiting_approval" in code


# ── ARCH-ENG-083: an approved mutating tool could never execute ────────────

def test_dispatch_passes_the_capability_so_mutating_tools_can_run():
    """Handlers refuse without the dispatch capability.

    dispatch.execute_tool used to call handler(arguments) with no
    authorization, so workshop_write/file_write/run_command refused every
    time and the approval -> execute path was dead end to end.
    """
    from agents.safety import calling

    assert calling._require_mutation_capability(
        calling._DISPATCH_CAPABILITY, "workshop_write") is None
    assert calling._require_mutation_capability(None, "workshop_write")


def test_dispatch_source_passes_the_capability():
    from agents.safety import dispatch
    import inspect

    src = inspect.getsource(dispatch)
    assert "authorization=runtime._DISPATCH_CAPABILITY" in src


def test_every_read_only_tool_still_dispatches():
    """Passing authorization= to a handler that does not declare it is a TypeError.

    The first cut of the 073 fix passed it unconditionally and broke all 10
    read-only tools — the only ones reachable without a human round-trip — so
    the suite stayed green while 100% of no-approval chat tool use died.
    """
    from agents.safety import dispatch
    from agents.safety.gate import READONLY_TOOL_NAMES

    args = {"path": "main.py", "filepath": "README.md", "folder": "tmp",
            "query": "x", "sql": "SELECT 1", "pattern": "x", "url": "http://x"}
    for name in sorted(READONLY_TOOL_NAMES):
        out = str(dispatch.execute_tool(name, args))
        assert "unexpected keyword argument" not in out, f"{name}: {out}"
        assert "Tool error" not in out or "authorization" not in out, f"{name}: {out}"


def test_accepts_authorization_only_for_mutating_handlers():
    from agents.safety import calling, dispatch

    for name in ("workshop_write", "workshop_mkdir", "workshop_proposal",
                 "workshop_account", "workshop_payment", "file_write",
                 "run_command"):
        handler = getattr(calling, f"_tool_{name}", None)
        if handler is None:
            continue
        assert dispatch._accepts_authorization(handler), f"{name} missed the capability"

    for name in ("file_read", "file_list", "web_search", "web_read", "web_check",
                 "workshop_list", "workshop_read", "workshop_storage",
                 "workshop_search", "query_db"):
        handler = getattr(calling, f"_tool_{name}", None)
        if handler is None:
            continue
        assert not dispatch._accepts_authorization(handler), (
            f"{name} now claims the capability")


def test_approved_execute_tool_can_run_an_approved_mutating_tool(tmp_path):
    """approved=True is the human's decision and must reach the handler."""
    from agents.safety import dispatch
    from agents.safety.policy import PROJECT_ROOT

    rel = os.path.join("tmp", f"cycle_approved_{os.getpid()}.txt")
    target = PROJECT_ROOT / rel
    try:
        out = dispatch.execute_tool(
            "file_write", {"path": rel, "content": "approved"}, approved=True)
        # The capability gate must pass; only the workspace policy may refuse.
        assert "Authorization required" not in out, out
        assert target.exists(), out
    finally:
        try:
            target.unlink()
        except OSError:
            pass


def test_approved_does_not_unblock_a_blocked_tool():
    """The human's approval must not be bypass a BLOCKED tool.

    Corrected in v2.1.62. The previous version asserted that ``write_file``,
    ``read_file`` and ``query_database`` are all refused with ``approved=True``
    because "aliases are themselves BLOCKED". That premise was wrong:
    ``SafetyGate._RULES`` does list each alias as BLOCKED, but ``check()``
    never reads ``_RULES`` — it classifies by CANONICAL target, so
    ``write_file`` is NEEDS_APPROVAL and ``read_file`` is ALLOWED. The test
    only passed because the dispatch handler table was keyed on canonical
    names and refused every alias as "Unknown tool" — it was pinning the
    ARCH-ENG-090 defect (an approved alias could never run) and calling it a
    safety property.

    The real property, asserted here: a tool the gate BLOCKS stays blocked
    even with ``approved=True``, and an unknown name is still refused. An
    alias that resolves to an ALLOWED/NEEDS_APPROVAL target behaves exactly
    as its canonical name does — that is the fix, not a hole.
    """
    from agents.safety import dispatch

    # BLOCKED by classification: unsafe SQL is refused by the SQL validator
    # before any approval can be considered.
    for name, args in (
        ("query_database", {"sql": "UPDATE facts SET value='bad'"}),
        ("query_database", {"sql": ""}),
    ):
        out = dispatch.execute_tool(name, args, approved=True)
        assert out.startswith("[BLOCKED]"), f"{name}/{args}: {out}"

    # Unknown names are refused outright and cannot be upgraded.
    out = dispatch.execute_tool("definitely_not_a_tool", {}, approved=True)
    assert out.startswith("[Unknown tool:"), out

    # No BLOCKED path may fall through to the authorization error, which would
    # mean the refusal came from the wrong layer.
    for name, args in (
        ("query_database", {"sql": "UPDATE facts SET value='bad'"}),
        ("definitely_not_a_tool", {}),
    ):
        assert "Authorization required" not in dispatch.execute_tool(
            name, args, approved=True)


def test_alias_behaves_exactly_like_its_canonical_target():
    """ARCH-ENG-090: an alias must not be a separate, stricter classification.

    ``write_file`` is an alias for ``file_write``. Both must require approval,
    and an approved ``write_file`` must actually run — before the fix the
    operator approved it and got "[Unknown tool: write_file]".
    """
    from agents.safety import dispatch
    from agents.safety.approval import HumanApprovalQueue
    from agents.safety.gate import SafetyGate, canonical_tool_name
    from agents.safety.policy import PROJECT_ROOT

    gate = SafetyGate()
    for alias, canonical in (("write_file", "file_write"),
                             ("read_file", "file_read"),
                             ("query_database", "query_db")):
        assert canonical_tool_name(alias) == canonical
        alias_decision = gate.check(alias, {"sql": "SELECT 1"})[2]
        canon_decision = gate.check(canonical, {"sql": "SELECT 1"})[2]
        assert alias_decision == canon_decision, (
            f"{alias} classified {alias_decision} but {canonical} is "
            f"{canon_decision}")

    # Unapproved mutating alias: queued, not executed.
    queue = HumanApprovalQueue.instance()
    queue.clear_all()
    rel = os.path.join("tmp", "cycle_alias_parity.txt")
    target = PROJECT_ROOT / rel
    try:
        out = dispatch.execute_tool("write_file", {"path": rel, "content": "x"})
        assert "PENDING APPROVAL" in out, out
        assert not target.exists()
    finally:
        try:
            target.unlink()
        except OSError:
            pass


def test_unapproved_mutating_tool_is_still_pending():
    """Without approval the action must not execute."""
    from agents.safety import dispatch

    out = dispatch.execute_tool("file_write", {"path": "x", "content": "y"})
    assert "PENDING APPROVAL" in out


def _action_item(target):
    from agents.safety.approval import ApprovalItem, ApprovalKind
    from agents.safety.policy import PROJECT_ROOT

    rel = os.path.join("tmp", f"cycle_approval_{os.getpid()}.txt")
    return ApprovalItem(
        kind=ApprovalKind.ACTION,
        title="Chat tool request: file_write",
        description="approved payload must execute",
        requested_by="dialogue",
        details={"tool": "file_write", "arguments": {"path": rel, "content": "x"}},
        payload={"tool": "file_write", "arguments": {"path": rel, "content": "x"}},
    ), PROJECT_ROOT / rel


def test_approved_gui_decision_ignores_a_forged_signal_status():
    """The queue's recorded decision is authoritative, not the signal argument.

    The first cut trusted the `status` argument the emitter passed. A spurious
    signal (or a second emitter) claiming APPROVED for an item the queue still
    records as PENDING/DENIED executed an action nobody approved.
    """
    from agents.safety.approval import ApprovalStatus, HumanApprovalQueue
    from agents.safety.policy import PROJECT_ROOT

    queue = HumanApprovalQueue.instance()
    rel = os.path.join("tmp", f"cycle_forged_{os.getpid()}.txt")
    target = PROJECT_ROOT / rel
    try:
        # The item is DENIED by the operator.
        item, _ = _action_item(None)
        queued = queue.enqueue(item)
        assert queue.deny(queued.id) is True

        # A signal nevertheless claims APPROVED.
        decided = queue.find_by_id(queued.id)
        assert decided.status == ApprovalStatus.DENIED

        # The shipped handler must refuse: it re-reads the queue.
        src = _load_main_handler_source()
        assert "item.status != ApprovalStatus.APPROVED" in src, (
            "handler still trusts the signal's status argument")
        # The kind guard must still restrict what may execute. Since v2.1.62
        # it is a positive dispatch (`kind == ACTION` / `kind == SUBMISSION`)
        # because approved submissions now route too. Assert the property —
        # an unlisted kind must fall through to no execution — rather than a
        # literal that a docstring could satisfy.
        assert "item.kind == ApprovalKind.ACTION" in src
        assert "item.kind == ApprovalKind.SUBMISSION" in src
        assert "elif" in src, (
            "dispatch must be conditional; an unconditional body would run "
            "every kind")
    finally:
        try:
            target.unlink()
        except OSError:
            pass
        assert not target.exists()


def _load_main_handler_source():
    from agents.safety.policy import PROJECT_ROOT

    path = os.path.join(str(PROJECT_ROOT), "main.py")
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    return src.split("def _on_approval_decided")[1].split("def _refresh_approval_alert")[0]


def test_approved_gui_decision_executes_the_queued_payload():
    """An approved ACTION item must actually run, not sit in the queue."""
    from agents.safety.approval import ApprovalStatus, HumanApprovalQueue

    queue = HumanApprovalQueue.instance()
    item, target = _action_item(None)
    try:
        queued = queue.enqueue(item)
        assert queued.status == ApprovalStatus.PENDING
        assert queue.approve(queued.id) is True

        # Mirror of main.MrBot1000App._on_approval_decided.
        from agents.safety.dispatch import execute_tool
        decided = queue.find_by_id(queued.id)
        assert decided.status == ApprovalStatus.APPROVED
        payload = decided.payload or {}
        out = execute_tool(payload["tool"], payload["arguments"], approved=True)
        assert "Authorization required" not in out, out
        assert target.exists(), out
    finally:
        try:
            target.unlink()
        except OSError:
            pass


# ── ARCH-ENG-084: a hard kill left the run unledgered ──────────────────────

class _StubStore:
    def __init__(self):
        self.runs = {}
        self.keys = set()

    def save_run(self, run, opp_id, *a, **k):
        self.runs[opp_id] = run.to_dict()
        return run.run_id

    def mark_idempotent(self, key, run_id, opp_id):
        self.keys.add(key)

    def is_idempotent(self, key):
        return key in self.keys


class _Opp:
    id = "opp-074"
    source = "system"
    task_type = ""
    title = "t"


def _loop_with_stub():
    from agents.services.autonomous_loop import AutonomousLoop

    loop = AutonomousLoop(None)
    store = _StubStore()
    loop.run_store = store
    return loop, store


def _new_result():
    """Build the AutonomousResult the loop would create for its opportunity."""
    from agents.services.autonomous_loop import AutonomousResult
    return AutonomousResult(opportunity_id="opp-074")


def test_begin_run_writes_the_ledger_before_stage_one():
    loop, store = _loop_with_stub()
    result = loop._run(_Opp())
    assert "opp-074" in store.runs, "no ledger row was written"
    assert store.runs["opp-074"]["status"] in ("DONE", "FAILED")


def test_begin_run_does_not_mark_the_idempotency_key():
    """A paused/rejected run must stay re-entry-able.

    Marking the key before stage 1 permanently blocked await_approval
    opportunities and the re-entry that _stage_deduplicate explicitly allows.
    """
    loop, store = _loop_with_stub()
    loop._begin_run(_new_result(), "opp-074")
    assert "opp-074" in store.runs
    assert store.runs["opp-074"]["status"] == "RUNNING"
    assert "opportunity:opp-074" not in store.keys


def test_replay_of_an_irreversible_opportunity_is_refused():
    loop, store = _loop_with_stub()
    store.mark_idempotent("opportunity:opp-074", "run-opp-074", "opp-074")
    result = loop._run(_Opp())
    assert result.decision == "reject"
    assert "already executed an irreversible action" in result.decision_reason
    # The refusal must not itself have re-run any stage.
    assert len(result.stages) == 0


def test_rejected_opportunity_can_re_enter():
    """A prior failure/rejection is re-entry-able (recurring gig / transient fail)."""
    loop, store = _loop_with_stub()
    # A completed but non-submitting run leaves no key behind.
    first = loop._run(_Opp())
    assert first.decision != "reject"
    second = loop._run(_Opp())
    assert second.decision != "reject", "a non-irreversible run blocked re-entry"


def test_mark_irreversible_blocks_the_next_run():
    """After a submission goes out, a restart must not re-submit."""
    loop, store = _loop_with_stub()
    result = _new_result()
    loop._mark_irreversible(result, "opp-074")
    assert store.is_idempotent("opportunity:opp-074") is True
    replay = loop._run(_Opp())
    assert replay.decision == "reject"


def test_replay_guard_fails_closed_on_a_ledger_read_error():
    """A locked/unreadable ledger must not permit a second irreversible action."""
    from agents.services.autonomous_loop import AutonomousLoop

    class _BrokenStore(_StubStore):
        def is_idempotent(self, key):
            raise RuntimeError("database is locked")

    loop = AutonomousLoop(None)
    loop.run_store = _BrokenStore()
    assert loop._replay_guard("opp-074") is True, "guard failed OPEN"


def test_finalized_run_is_terminal_so_recovery_does_not_refail_it():
    loop, store = _loop_with_stub()
    result = loop._run(_Opp())
    assert result.status in ("DONE", "FAILED")
    # recover_incomplete() fails anything not in this set.
    assert result.status in ("DONE", "FAILED", "CANCELLED", "COMPLETED")


def test_run_status_field_round_trips_through_the_store():
    """A real AutonomousRunStore must persist the in-flight status."""
    from agents.services.autonomous_run_store import AutonomousRunStore

    with tempfile.TemporaryDirectory() as tmp:
        store = AutonomousRunStore(os.path.join(tmp, "runs.db"))
        from agents.services.autonomous_loop import AutonomousResult
        res = AutonomousResult(opportunity_id="o1", run_id="run-o1", status="RUNNING")
        store.save_run(res, "o1")
        store.mark_idempotent("opportunity:o1", "run-o1", "o1")
        row = store.get_run("run-o1")
        assert row["status"] == "RUNNING"
        assert store.is_idempotent("opportunity:o1") is True
        # recover_incomplete must see and fail it.
        assert store.recover_incomplete() == 1
        assert store.get_run("run-o1")["status"] == "FAILED"


# ── ARCH-ENG-085: the operator's last settings edit was dropped ────────────

class _FakeWidget:
    def __init__(self):
        self.calls = []

    def append(self, text):
        self.calls.append(text)


class _PersistBase:
    """Import shim so the test file does not hard-fail without PySide6."""


def _load_persist_base():
    try:
        from gui.workers.provider_lifecycle_backend import (
            ProviderLifecycleBackend as _B,
        )
        return _B
    except Exception as exc:  # pragma: no cover - headless CI without PySide6
        pytest.skip(f"PySide6 backend unavailable: {exc}", allow_module_level=False)
        return object


_PersistBase = _load_persist_base()


class _PersistHost(_PersistBase):
    """Minimal stand-in exercising the REAL coalescing/re-arm logic.

    Subclasses ProviderLifecycleBackend so _persist_settings_async and the
    drain are the real implementations; only the two collaborators they need
    are stubbed (widget snapshot + .env writer + log widget).
    """

    def __init__(self):
        self._persist_thread = None
        self._persist_dirty = False
        self.writes = []
        self.calls = []
        self._snapshots = []

    def _log(self, message):
        self.calls.append(message)

    def _snapshot_settings_values(self):
        self._snapshots.append(len(self._snapshots) + 1)
        return {"n": len(self._snapshots)}

    def _write_env_values(self, values, remove_keys=None):
        """Stand in for the real .env writer, including its save confirmation."""
        self.writes.append(dict(values))
        time.sleep(0.05)
        self._emit_persist_saved()


def _run_gui_until(host, predicate, timeout_s=8.0):
    """Drive a REAL Qt event loop on the main thread until predicate() holds.

    The production code posts its re-snapshot through a GUI-thread QTimer, so a
    test that merely inlines singleShot cannot observe the cross-thread dispatch
    this fix depends on. This spins the real loop.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def test_persist_re_arms_instead_of_dropping_the_last_edit():
    """A newer edit arriving mid-write must not be silently dropped.

    Drives a real Qt event loop. The first implementation queued the re-snapshot
    with QTimer.singleShot from the WORKER thread; Qt delivers a functor-only
    singleShot to the posting thread, which runs no event loop, so it never
    fired, the worker spun out its 2s deadline, and the edit was dropped anyway.
    """
    host = _PersistHost()
    host._persist_settings_async()
    # A second edit lands while the first write is still in flight.
    time.sleep(0.005)
    host._persist_settings_async()

    def done():
        return not host._persist_thread.is_alive() and not host._persist_dirty

    assert _run_gui_until(host, done), (
        f"the newer edit was dropped: writes={host.writes}")
    assert len(host.writes) >= 2, host.writes
    assert host.writes[-1] == {"n": 2}, host.writes
    assert any("saved to .env" in c for c in host.calls), host.calls
    assert _run_gui_until(
        host, lambda: getattr(host, "_persist_drain_timer", None) is None), (
        "the drain timer never stopped")


def test_persist_does_not_re_arm_when_nothing_new_arrived():
    """The re-arm must not turn one edit into a write loop."""
    host = _PersistHost()
    host._persist_settings_async()

    def settled():
        return not host._persist_thread.is_alive()

    assert _run_gui_until(host, settled)
    # Give the drain a few ticks to prove it stops.
    time.sleep(0.3)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        for _ in range(20):
            app.processEvents()
            time.sleep(0.01)
    assert len(host.writes) == 1, host.writes


def test_persist_confirmation_is_delivered_to_the_log():
    """The .env save confirmation must reach _log() on the GUI thread.

    The first cut posted it with QTimer.singleShot from the worker thread, so it
    never fired and the message vanished entirely — a regression, because the
    old code at least logged it (albeit off-thread).
    """
    host = _PersistHost()
    host._persist_settings_async()

    def delivered():
        return any("saved to .env" in c for c in host.calls)

    assert _run_gui_until(host, delivered), (
        f"the confirmation never reached _log(): calls={host.calls}")


def test_worker_never_arms_the_drain_timer():
    """_emit_persist_saved runs on the worker thread and must not touch Qt.

    Qt refuses a cross-thread QObject child ("Cannot create children for a
    parent that is in a different thread"). If the worker won that race it would
    store a DEAD timer in _persist_drain_timer, and the "already armed" guard
    would then short-circuit permanently — killing both the save confirmation
    and the dirty re-arm for the rest of the session, even after the race stops
    occurring.
    """
    import ast
    import inspect
    import gui.workers.provider_lifecycle_backend as backend

    tree = ast.parse(textwrap.dedent(inspect.getsource(
        backend.ProviderLifecycleBackend._emit_persist_saved)).strip())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    code = ast.unparse(tree)
    assert "_arm_persist_drain" not in code, (
        "_emit_persist_saved still arms the drain from the worker thread")
    assert "QTimer" not in code

    # And the drain must be armed on the GUI thread before the writer starts.
    async_tree = ast.parse(textwrap.dedent(inspect.getsource(
        backend.ProviderLifecycleBackend._persist_settings_async)).strip())
    for node in ast.walk(async_tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    async_code = ast.unparse(async_tree)
    arm_at = async_code.index("_arm_persist_drain()")
    start_at = async_code.index("_start_persist_write(values")
    assert arm_at < start_at, (
        "the drain is armed after the writer starts, so a fast writer can win "
        "the race and install a dead cross-thread timer")


def test_drain_survives_a_fast_writer_winning_the_race():
    """A zero-cost writer must not be able to kill the re-arm permanently."""
    class _FastHost(_PersistHost):
        def _write_env_values(self, values, remove_keys=None):
            self.writes.append(dict(values))
            self._emit_persist_saved()   # no sleep: the worker finishes at once

    host = _FastHost()
    host._persist_settings_async()
    time.sleep(0.005)
    host._persist_settings_async()

    def done():
        return (not host._persist_thread.is_alive()
                and not host._persist_dirty
                and any("saved to .env" in c for c in host.calls))

    assert _run_gui_until(host, done), (
        f"re-arm stalled: writes={host.writes} calls={host.calls}")
    assert len(host.writes) >= 2, host.writes
    assert host.writes[-1] == {"n": 2}, host.writes
    assert any("saved to .env" in c for c in host.calls), host.calls
    # The drain must eventually stop so it cannot spin forever.
    assert _run_gui_until(
        host, lambda: getattr(host, "_persist_drain_timer", None) is None), (
        "the drain timer never stopped")


def test_persist_worker_never_calls_log_from_the_background_thread():
    """_log() appends to a QTextEdit; calling it off-thread corrupts the GUI."""
    import ast
    import inspect
    import gui.workers.provider_lifecycle_backend as backend

    def code_of(func):
        """The function's source with comments and docstrings removed."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)).strip())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    node.body.pop(0)
        return ast.unparse(tree)

    worker = code_of(backend.ProviderLifecycleBackend._persist_settings_worker)
    assert "_log(" not in worker, "the worker still logs off-thread"
    assert "_snapshot_settings_values" not in worker, (
        "the worker re-reads widgets from the background thread")
    writer = code_of(backend.ProviderLifecycleBackend._write_env_values)
    assert "_log(" not in writer, "_write_env_values still logs off-thread"
    # The confirmation must be queued for the GUI-thread drain, not posted
    # from the worker (a functor-only singleShot never fires off-thread).
    emit = code_of(backend.ProviderLifecycleBackend._emit_persist_saved)
    assert "singleShot" not in emit, (
        "_emit_persist_saved still posts from the background thread")
