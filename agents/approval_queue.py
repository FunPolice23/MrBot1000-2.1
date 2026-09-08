"""agents/approval_queue.py — Human-approval queue for submissions, payments, and gates."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from agents.notifications import NotificationService, NotifLevel


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
        self._log_path = log_path
        self._notif = NotificationService.instance()
        self.on_change: Optional[Callable[[ApprovalItem], None]] = None  # Phase 6
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
                cls._instance = cls.__new__(cls)
                cls._instance.__init__()
            return cls._instance

    @classmethod
    def reset_singleton(cls):
        with cls._get_lock():
            cls._instance = None

    # ── Enqueue ────────────────────────────────────────────────────────────────

    def enqueue(self, item: ApprovalItem) -> ApprovalItem:
        """Add a pending approval item and fire a notification."""
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
        item = ApprovalItem(
            kind=ApprovalKind.PAYMENT,
            title=title,
            description=description,
            requested_by=requested_by,
            details={"amount": amount, "currency": currency, **(details or {})},
            payload=payload or {},
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
        """
        item = self._find(item_id)
        if item is None or item.status != ApprovalStatus.PENDING:
            return False
        item.status = decision
        item.decided_at = time.time()
        item.decided_by = decided_by
        item.notes = notes
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
        return True

    def deny(self, item_id: str, notes: str = "") -> bool:
        return self.decide(item_id, ApprovalStatus.DENIED, notes=notes)

    def defer(self, item_id: str, notes: str = "") -> bool:
        return self.decide(item_id, ApprovalStatus.DEFERRED, notes=notes)

    def approve(self, item_id: str, notes: str = "") -> bool:
        return self.decide(item_id, ApprovalStatus.APPROVED, notes=notes)

    # ── Queries ────────────────────────────────────────────────────────────────

    def pending(self) -> List[ApprovalItem]:
        return [i for i in self._items if i.status == ApprovalStatus.PENDING]

    def all(self) -> List[ApprovalItem]:
        return list(self._items)

    def find_by_id(self, item_id: str) -> Optional[ApprovalItem]:
        return self._find(item_id)

    def items_for_kind(self, kind: ApprovalKind) -> List[ApprovalItem]:
        return [i for i in self._items if i.kind == kind and i.status == ApprovalStatus.PENDING]

    def pending_count(self) -> int:
        return len(self.pending())

    def clear_all(self):
        """Remove all items (e.g. on app exit or reset)."""
        self._items.clear()
        self._maybe_persist()

    # ── Persistence (best-effort JSON) ─────────────────────────────────────────

    def _maybe_persist(self):
        if not self._log_path:
            return
        try:
            import json
            os = __import__("os")
            os.makedirs(os.path.dirname(self._log_path) or ".", exist_ok=True)
            with open(self._log_path, "w", encoding="utf-8") as f:
                json.dump(
                    [i.to_dict() for i in self._items],
                    f, indent=2,
                )
        except Exception:
            pass  # persistence is best-effort

    def _find(self, item_id: str) -> Optional[ApprovalItem]:
        for i in self._items:
            if i.id == item_id:
                return i
        return None


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
]
