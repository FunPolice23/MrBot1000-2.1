"""agents/approval_queue.py — Human-approval queue for submissions, payments, and gates."""
from __future__ import annotations

import time
import os
import sys
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from agents.core.notifications import NotificationService, NotifLevel

# Env override for the persisted queue location. Tests point this at a
# throwaway file (the same isolation pattern as MRBOT_ENV_PATH / conftest.py).
_APPROVAL_LOG_ENV = "MRBOT_APPROVAL_QUEUE_PATH"

# Upper bound on the persisted approval history. It caps DECIDED history only:
# PENDING items and decisions made in the current process are never evicted
# (see _maybe_persist), so the file can exceed this bound while live work is
# outstanding. Restored DECIDED items are history, not authorization — see
# find_by_id().
_MAX_RETAINED_ITEMS = 200


def default_log_path() -> str:
    """Resolve where the approval queue is persisted. "" means in-memory only.

    Convention follows the rest of the app's agent state: ``~/.mrbot1000``
    holds reputation.json, wallets.json, opportunities.db, submissions/ and
    microtasks/ (opportunity_portfolio.py, reputation.py, wallet.py,
    platform_submitter.py). It is derived from the user's home directory, never
    a hardcoded absolute path, and never inside the source tree (which may be
    read-only, and which a re-clone would silently replace).

    A test run must be structurally incapable of writing the operator's LIVE
    queue — several existing tests call ``HumanApprovalQueue.instance()`` and
    then ``clear_all()``, which would otherwise persist an empty list over real
    pending approvals. Same rule as app/environment.py's ``.env`` write
    refusal: under pytest the queue stays in memory unless a test opts in by
    setting MRBOT_APPROVAL_QUEUE_PATH.
    """
    override = (os.environ.get(_APPROVAL_LOG_ENV) or "").strip()
    if override:
        return override
    if "pytest" in sys.modules:
        return ""
    return os.path.join(os.path.expanduser("~"), ".mrbot1000", "approvals.json")


class ApprovalKind(str, Enum):
    SUBMISSION = "submission"      # freelance/microtask platform submit
    PAYMENT = "payment"            # crypto or fiat payout
    GATE = "gate"                  # human_gates.py gate clearance
    ACTION = "action"              # any other irreversible action


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    DEFERRED = "deferred"


@dataclass
class ApprovalItem:
    """A single pending approval item in the queue."""
    id: str = ""
    kind: ApprovalKind = ApprovalKind.ACTION
    title: str = ""
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_by: str = ""         # agent / system component
    requested_at: float = 0.0
    decided_at: float = 0.0
    decided_by: str = ""
    notes: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            import uuid
            self.id = uuid.uuid4().hex
        if self.requested_at == 0.0:
            self.requested_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "description": self.description,
            "details": self.details,
            "status": self.status.value,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "notes": self.notes,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ApprovalItem":
        return cls(
            id=d.get("id", ""),
            kind=ApprovalKind(d.get("kind", ApprovalKind.ACTION.value)),
            title=d.get("title", ""),
            description=d.get("description", ""),
            details=d.get("details", {}),
            status=ApprovalStatus(d.get("status", ApprovalStatus.PENDING.value)),
            requested_by=d.get("requested_by", ""),
            requested_at=d.get("requested_at", time.time()),
            decided_at=d.get("decided_at", 0.0),
            decided_by=d.get("decided_by", ""),
            notes=d.get("notes", ""),
            payload=d.get("payload", {}),
        )


class HumanApprovalQueue:
    """In-memory human-approval queue for the desktop app.

    Items enter as PENDING and stay until a human Approves, Denies, or
    Defers them. The queue drives both the in-app approval panel and
    the notification service (approval_required notifications).
    """

    _instance: Optional["HumanApprovalQueue"] = None
    _lock = None  # lazily created per-class; shared across instances

    def __init__(self, log_path: Optional[str] = None):
        self._items: List[ApprovalItem] = []
        # "" means "in memory only" (the value default_log_path() returns under
        # pytest); normalize it to None so `if self._log_path:` guards elsewhere
        # in this class all mean the same thing.
        self._log_path = log_path or None
        self._notif = NotificationService.instance()
        self.on_change: Optional[Callable[[ApprovalItem], None]] = None  # Phase 6
        # Ids of items that were DECIDED in a previous process and restored from
        # disk. See find_by_id() for why these are history, not authorization.
        self._restored_decided: set[str] = set()
        # Ids of items a human decided IN THIS PROCESS. The eviction bound in
        # _maybe_persist() must never drop one: a decision recorded seconds ago
        # is a live authorization the operator is still acting on, plus the
        # audit record of it — not history that may be pruned.
        self._decided_in_process: set[str] = set()
        if log_path:
            self._load()

    @classmethod
    def _get_lock(cls):
        import threading as _t
        if cls._lock is None:
            cls._lock = _t.Lock()
        return cls._lock

    @classmethod
    def instance(cls) -> "HumanApprovalQueue":
        with cls._get_lock():
            if cls._instance is None:
                # The queue is the app's ONLY record of a human decision, so the
                # singleton must resolve a real path. Calling __init__() with no
                # argument left log_path=None: _maybe_persist() returned
                # immediately and _load() never ran, so every pending approval
                # was silently discarded on exit and an operator who restarted
                # found an empty Approvals tab with no record anything had been
                # requested. default_log_path() is "" (in-memory) under pytest
                # so a test run can never overwrite the live queue.
                cls._instance = cls(default_log_path())
            return cls._instance

    @classmethod
    def reset_singleton(cls):
        with cls._get_lock():
            cls._instance = None

    # ── Enqueue ────────────────────────────────────────────────────────────────

    def enqueue(self, item: ApprovalItem) -> ApprovalItem:
        """Add a pending approval item and fire a notification."""
        with self._get_lock():
            existing_ids = {i.id for i in self._items}
            if not item.id or item.id in existing_ids:
                import uuid
                item.id = uuid.uuid4().hex
            item.status = ApprovalStatus.PENDING
            self._items.append(item)
            self._maybe_persist()
        self._notif.approval_required(
            title=f"Approval needed: {item.title}",
            message=item.description,
            source="approval_queue",
            sticky=True,
            payload={"approval_id": item.id, "kind": item.kind.value},
        )
        # Phase 6: fire on_change callback (e.g. to update GUI panels)
        if self.on_change:
            try:
                self.on_change(item)
            except Exception:
                pass
        return item

    def enqueue_submission(self, title: str, description: str,
                           requested_by: str = "system",
                           details: Dict[str, Any] = None,
                           payload: Dict[str, Any] = None) -> ApprovalItem:
        item = ApprovalItem(
            kind=ApprovalKind.SUBMISSION,
            title=title,
            description=description,
            requested_by=requested_by,
            details=details or {},
            payload=payload or {},
        )
        return self.enqueue(item)

    def enqueue_payment(self, title: str, description: str,
                        amount: float = 0.0, currency: str = "",
                        requested_by: str = "system",
                        details: Dict[str, Any] = None,
                        payload: Dict[str, Any] = None) -> ApprovalItem:
        """Queue a PAYMENT approval for ``record_payment``.

        ARCH-ENG-129: the approved AMOUNT is part of the approval's scope. An
        operator who reviews "pay $5.00" has authorized $5.00 and nothing else,
        so the amount travels in ``details["arguments"]`` alongside the tool
        name and is enforced by ``assert_approval_covers``. Passing no amount
        records no authorized amount, and the HIGH-TRUST tool then refuses any
        positive one — fail-closed, because an approval that never stated a
        figure cannot authorize booking one.
        """
        scope_args: Dict[str, Any] = {"amount": float(amount or 0.0)}
        if currency:
            scope_args["currency"] = currency
        item = ApprovalItem(
            kind=ApprovalKind.PAYMENT,
            title=title,
            description=description,
            requested_by=requested_by,
            # Scope always lives in `details`: `approval_scope` reads `payload`
            # first and falls back to `details`, and a caller-supplied payload
            # is preserved verbatim (it may carry redaction-sensitive fields
            # that other consumers assert on).
            details={"tool": "record_payment", "arguments": scope_args,
                     "amount": amount, "currency": currency,
                     **(details or {})},
            payload=payload if payload is not None else {
                "tool": "record_payment", "arguments": scope_args},
        )
        return self.enqueue(item)

    def enqueue_gate(self, title: str, description: str,
                     gate_type: str = "",
                     requested_by: str = "human_gates",
                     details: Dict[str, Any] = None,
                     payload: Dict[str, Any] = None) -> ApprovalItem:
        item = ApprovalItem(
            kind=ApprovalKind.GATE,
            title=title,
            description=description,
            requested_by=requested_by,
            details={"gate_type": gate_type, **(details or {})},
            payload=payload or {},
        )
        return self.enqueue(item)

    # ── Decisions ──────────────────────────────────────────────────────────────

    def decide(self, item_id: str, decision: ApprovalStatus,
               decided_by: str = "human", notes: str = "") -> bool:
        """Approve / deny / defer a pending item.

        Returns True if the item existed and was pending.

        ARCH-ENG-166: the `_find` + status check ran BEFORE the lock was
        acquired, so two threads (a GUI decision and the safety guard's
        decision thread) could both observe PENDING and both proceed to decide
        the same irreversible action. The whole check-then-act is now inside
        one critical section, so an approval is decided exactly once.
        """
        with self._get_lock():
            item = self._find(item_id)
            if item is None or item.status != ApprovalStatus.PENDING:
                return False
            item.status = decision
            item.decided_at = time.time()
            item.decided_by = decided_by
            item.notes = notes
            # A decision made in THIS process is live authorization and must
            # survive the history bound; see _maybe_persist().
            self._decided_in_process.add(item.id)
            self._maybe_persist()
        # Notify the outcome
        if decision == ApprovalStatus.APPROVED:
            self._notif.success(
                title=f"Approved: {item.title}",
                message=f"Human approved: {notes or item.description}",
                source="approval_queue",
            )
        elif decision == ApprovalStatus.DENIED:
            self._notif.warning(
                title=f"Denied: {item.title}",
                message=f"Human denied: {notes or item.description}",
                source="approval_queue",
            )
        else:
            self._notif.info(
                title=f"Deferred: {item.title}",
                message=f"Deferred by {decided_by}: {notes or item.description}",
                source="approval_queue",
            )
        # Phase 6: fire on_change so GUI panels refresh on any decision.
        if self.on_change:
            try:
                self.on_change(item)
            except Exception:
                pass
        return True

    def deny(self, item_id: str, notes: str = "") -> bool:
        return self.decide(item_id, ApprovalStatus.DENIED, notes=notes)

    def defer(self, item_id: str, notes: str = "") -> bool:
        return self.decide(item_id, ApprovalStatus.DEFERRED, notes=notes)

    def approve(self, item_id: str, notes: str = "") -> bool:
        return self.decide(item_id, ApprovalStatus.APPROVED, notes=notes)

    # ── Queries ────────────────────────────────────────────────────────────────

    def pending(self) -> List[ApprovalItem]:
        with self._get_lock():
            return [i for i in self._items if i.status == ApprovalStatus.PENDING]

    def all(self) -> List[ApprovalItem]:
        with self._get_lock():
            return list(self._items)

    # ARCH-ENG-166: `find_by_id` is the lookup every irreversible-action
    # consumer uses to confirm a human decision (platform_submitter,
    # live_trading, code_patch_service, SafetyGuard). It took NO lock while a
    # single shared queue instance was mutated from GUI threads, the safety
    # guard's decision thread, and every worker that enqueues — and `_items` is
    # also TRUNCATED by the history bound, so a concurrent reader could observe
    # a list mid-mutation. A torn read here is a financial-integrity bug. The
    # lock is now taken across the lookup AND the restored-decided test, so the
    # two cannot be evaluated against different states.

    def find_by_id(self, item_id: str) -> Optional[ApprovalItem]:
        """Look up an item by id, refusing decisions restored from a prior run.

        This is the lookup every execution consumer uses to confirm a human
        decision (platform_submitter.execute_approved, live_trading._is_approved,
        code_patch_service._is_approved, SafetyGuard._decide_in_shared_queue).
        Returning None for an id decided in a previous process makes those
        consumers fail CLOSED — "cannot confirm a human decision" — so a restart
        can never turn a stale approval into a live one and run an irreversible
        action against content the human no longer sees. A PENDING item restored
        from disk is returned normally: it authorizes nothing until a human
        decides it in this process. ``all()`` still exposes the full history.
        """
        with self._get_lock():
            item = self._find(item_id)
            if item is None:
                return None
            if item.id in self._restored_decided:
                return None
            return item

    def items_for_kind(self, kind: ApprovalKind) -> List[ApprovalItem]:
        with self._get_lock():
            return [i for i in self._items
                    if i.kind == kind and i.status == ApprovalStatus.PENDING]

    def pending_count(self) -> int:
        return len(self.pending())

    def clear_all(self):
        """Remove all items (e.g. on app exit or reset)."""
        with self._get_lock():
            self._items.clear()
            self._restored_decided.clear()
            self._decided_in_process.clear()
            self._maybe_persist()

    # ── Persistence (best-effort JSON) ─────────────────────────────────────────

    def _maybe_persist(self):
        if not self._log_path:
            return
        try:
            import json
            os.makedirs(os.path.dirname(self._log_path) or ".", exist_ok=True)
            # Bound the history: this file is rewritten in full on every change,
            # so an unbounded queue would grow the write cost forever. Two
            # classes of item are NEVER evicted:
            #
            #   * PENDING items — losing one is the defect this file exists to
            #     fix: a request nobody can see is a request nobody can approve.
            #   * items a human DECIDED IN THIS PROCESS — approving a $5000
            #     payment and then enqueueing 210 more items used to delete that
            #     approval from memory AND from disk, destroying both the live
            #     authorization and the audit record of a human decision. A
            #     decision is not history the moment it is made; it is history
            #     only once the process that made it has exited (at which point
            #     _restored_decided already refuses to honour it).
            #
            # The bound therefore caps the decided HISTORY only, oldest first.
            keep = list(self._items)
            if len(keep) > _MAX_RETAINED_ITEMS:
                live = [i for i in keep
                        if i.status == ApprovalStatus.PENDING
                        or i.id in self._decided_in_process]
                history = [i for i in keep
                           if i.status != ApprovalStatus.PENDING
                           and i.id not in self._decided_in_process]
                history.sort(key=lambda i: i.decided_at or i.requested_at)
                slots = max(0, _MAX_RETAINED_ITEMS - len(live))
                keep = live + history[-slots:] if slots else list(live)
                self._items = sorted(keep, key=lambda i: i.requested_at)
            # The tracking sets must not drift from the list they describe: an
            # id whose item is gone is neither "restored decided" nor "decided
            # in process" for anything (find_by_id already returns None for a
            # missing item). This intersection is the ONLY removal path besides
            # clear_all(), so without it both sets would grow monotonically for
            # the life of the process while _items stayed bounded.
            retained = {i.id for i in self._items}
            self._restored_decided &= retained
            self._decided_in_process &= retained
            # ARCH-ENG-265 (AM-02): write atomically, then replace. The old
            # `open(..., "w")` + json.dump truncated the log first, so a crash
            # mid-write left _load() with nothing to restore -- and the failure
            # was swallowed by `except Exception: pass`. This file IS the
            # human-decision record; losing it silently is not best-effort.
            tmp_path = self._log_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(
                    [i.to_dict() for i in self._items],
                    f, indent=2,
                )
            os.replace(tmp_path, self._log_path)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Approval-queue persistence failed (%s). Human decisions made "
                "in this process are held in memory only and will not survive "
                "a restart.", exc)

    def _load(self):
        """Restore persisted items from the JSON log (best-effort).

        Restore uses ``ApprovalItem.from_dict`` and appends directly to
        ``self._items`` — it NEVER calls ``enqueue()``. ``enqueue()``
        unconditionally resets ``item.status = ApprovalStatus.PENDING``, so a
        re-enqueueing restore would resurrect every already-DENIED or
        already-APPROVED item as a fresh pending request, erasing the recorded
        human decision and manufacturing approvals nobody gave. (A prior cycle
        fixed exactly this in a test fixture; it must not come back here.)

        STALE-APPROVAL SAFETY. A decision recorded in a previous process is
        history, not a live authorization, and a restart must never by itself
        make an irreversible action runnable against content that may have
        changed since the human looked at it (a submission whose copy was
        rewritten, a payment approved days ago, a live order). So restored
        DECIDED ids are recorded in ``self._restored_decided`` and
        ``find_by_id()`` — the single lookup every execution consumer uses
        (platform_submitter.execute_approved, live_trading._is_approved,
        code_patch_service._is_approved) — refuses them. Those consumers fail
        CLOSED on a missing id ("cannot confirm a human decision"), so nothing
        executes on a stale approval. Restored PENDING items are returned
        normally: they authorize nothing until a human decides them in THIS
        process, which is the re-validation we want. The full history stays in
        ``all()`` so the operator can still see what was decided and re-request
        it deliberately.
        """
        if not self._log_path:
            return
        try:
            import json
            if not os.path.exists(self._log_path):
                return
            with open(self._log_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, list):
                return
            self._restored_decided = set()
            restored: List[ApprovalItem] = []
            for d in raw:
                if not isinstance(d, dict):
                    continue
                try:
                    item = ApprovalItem.from_dict(d)
                except Exception:
                    continue  # one malformed record must not drop the rest
                if item.status != ApprovalStatus.PENDING:
                    self._restored_decided.add(item.id)
                restored.append(item)
            self._items = restored
        except Exception:
            # A corrupt or unreadable log must not crash startup, and must not
            # be overwritten before it is read: keep _items empty but leave the
            # file in place so the operator can inspect it.
            pass

    def _find(self, item_id: str) -> Optional[ApprovalItem]:
        for i in self._items:
            if i.id == item_id:
                return i
        return None


# ── Approval scope binding (ARCH-ENG-129) ────────────────────────────────────
#
# An approval authorizes ONE action, not a capability. Before ARCH-ENG-129 the
# only thing a HIGH-TRUST tool checked was `item.status == APPROVED` — the
# item's `kind`, `details` and `payload` were never read. Reproduced on the
# real code by executing it:
#
#   * a human-approved **$5.00** payment approval booked **$1,000,000.00** of
#     verified revenue, because `amount` was a raw tool argument;
#   * a human-approved **file_write** approval (path `scratch.txt`) was
#     replayed as the `approval_id` for **record_payment**, which then booked
#     $777 — approval ids are model-visible, so one id could be spent against
#     any mutating tool;
#   * a human-approved social post of `'Hello team'` published
#     `'BUY THIS NOW <link>'`, because `content` was a raw tool argument.
#
# The fix is a single predicate every HIGH-TRUST tool calls before it mutates:
# the approval must name THIS tool and, where the human saw arguments, THOSE
# arguments. Fail-closed: an item that records no scope at all authorizes
# nothing.


def approval_scope(item: "ApprovalItem") -> Dict[str, Any]:
    """The (tool, arguments) pair the human actually approved, or {} if none.

    Producers record scope in two shapes, both accepted:
      * ``details``/``payload`` with ``tool`` + ``arguments`` keys — used by
        ``dispatch.execute_tool``, ``chat_completion`` and ``big_brain``;
      * ``enqueue_payment`` / ``enqueue_gate`` / ``enqueue_submission`` and
        the registration/safety-guard producers, which record only free-form
        ``details``. Those carry NO tool name and therefore authorize nothing
        under ``assert_approval_covers`` (see below).
    """
    for source in (getattr(item, "payload", None), getattr(item, "details", None)):
        if isinstance(source, dict):
            tool = source.get("tool")
            args = source.get("arguments")
            if isinstance(tool, str) and tool.strip():
                return {"tool": tool.strip(),
                        "arguments": args if isinstance(args, dict) else {}}
    return {}


def assert_approval_covers(item: "ApprovalItem", tool: str,
                           arguments: Dict[str, Any]) -> Optional[str]:
    """None when `item` authorizes exactly `tool(**arguments)`; else a refusal.

    The approval must have been recorded as an APPROVED decision for THIS tool.
    When the producer recorded the arguments the human reviewed, those
    arguments must match the call — a different amount, a different path or
    different content is a DIFFERENT action and needs its own approval.

    Numbers compare with a small tolerance (JSON round-trips `25.0` as `25`),
    everything else compares exactly. Keys the approval did not record are not
    policed: producers legitimately record a subset (e.g. ``big_brain`` adds a
    ``reason``), and an unrecorded key cannot have been shown to the human, so
    requiring it would make the tool unusable.
    """
    if item is None:
        return "approval not found"
    if item.status != ApprovalStatus.APPROVED:
        return (f"approval {item.id} is {item.status.value}, not approved")
    scope = approval_scope(item)
    recorded_tool = scope.get("tool", "")
    if not recorded_tool:
        return (
            f"approval {item.id} records no tool scope, so it authorizes no "
            f"action; {tool} was not executed"
        )
    if recorded_tool != tool:
        return (
            f"approval {item.id} authorizes {recorded_tool!r}, not {tool!r}; "
            f"{tool} was not executed"
        )
    recorded_args = scope.get("arguments") or {}
    for key, want in recorded_args.items():
        # `approval_id` is the handle by which the caller REFERS to this
        # approval, not an argument the human reviewed as part of the action.
        # It is also re-stamped by ``main._execute_approved_action`` with the
        # id the operator actually approved, so comparing it would refuse
        # every honest call. The binding it provides is redundant: the tool
        # name and the reviewed arguments are what identify the action.
        if key == "approval_id":
            continue
        got = (arguments or {}).get(key)
        if not _approval_args_match(want, got):
            return (
                f"approval {item.id} authorized {tool} with {key}="
                f"{want!r}, but the call passed {got!r}; {tool} was not "
                f"executed (an approval authorizes one action, not a "
                f"capability)"
            )
    return None


def _approval_args_match(want: Any, got: Any) -> bool:
    """Compare an approved argument value against the value being executed."""
    if isinstance(want, bool) or isinstance(got, bool):
        return want is got
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return abs(float(want) - float(got)) <= 1e-6
    if isinstance(want, dict) and isinstance(got, dict):
        return all(k in got and _approval_args_match(v, got[k])
                   for k, v in want.items())
    if isinstance(want, (list, tuple)) and isinstance(got, (list, tuple)):
        return (len(want) == len(got)
                and all(_approval_args_match(a, b) for a, b in zip(want, got)))
    return want == got


# ── module-level convenience ───────────────────────────────────────────────────

def enqueue_approval(kind: ApprovalKind, title: str, description: str,
                      requested_by: str = "system", **kw) -> ApprovalItem:
    q = HumanApprovalQueue.instance()
    if kind == ApprovalKind.SUBMISSION:
        return q.enqueue_submission(title, description, requested_by, **kw)
    if kind == ApprovalKind.PAYMENT:
        return q.enqueue_payment(title, description, requested_by=requested_by, **kw)
    if kind == ApprovalKind.GATE:
        return q.enqueue_gate(title, description, requested_by=requested_by, **kw)
    return q.enqueue(ApprovalItem(kind=kind, title=title, description=description,
                                   requested_by=requested_by, **kw))


__all__ = [
    "ApprovalKind",
    "ApprovalStatus",
    "ApprovalItem",
    "HumanApprovalQueue",
    "enqueue_approval",
    "approval_scope",
    "assert_approval_covers",
]
