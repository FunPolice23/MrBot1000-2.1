"""
comms.py — Structured internal message/event protocol for MrBot1000.

This is the communication backbone introduced by the Chat↔Main communication
redesign (see COMMS_REDESIGN.md). It replaces ad-hoc string queues, positional
Qt signal tuples, and the JSON-file SharedContext mirror with a single, typed,
thread-safe message bus.

Design goals (from the redesign spec):
  - Every message carries message_id, correlation_id, source, destination,
    message_type, timestamp, priority, payload, status, parent_message_id.
  - Asynchronous, correlation-id tracked, thread-safe, observable.
  - Cancellation (via CancellationToken), retry bookkeeping, failure reporting.
  - Queue isolation is preserved by the caller (Manager/Summarizer keep their
    own threads + queues); the bus is the routing/observability layer.
  - NO circular Chat↔Main loops: the bus rejects a request that would replay an
    already-seen (source, destination) edge for a correlation_id (cycle detect),
    and rejects any request whose destination == source.

The bus is PURE PYTHON (no Qt dependency) so the protocol and all 11 acceptance
tests are verifiable without a running QApplication. GUI/thread delivery uses a
thin Qt bridge (see main.py / QtEventBridge) that subscribes to this bus.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ─────────────────────────────────────────────────────────────────────────────
#  Message taxonomy
# ─────────────────────────────────────────────────────────────────────────────

class MessageType(str, Enum):
    """All message/event types flowing through the bus."""
    USER_REQUEST       = "USER_REQUEST"
    TASK_REQUEST       = "TASK_REQUEST"
    TASK_RESULT        = "TASK_RESULT"
    MODEL_REQUEST      = "MODEL_REQUEST"
    MODEL_RESULT       = "MODEL_RESULT"
    STATE_UPDATE       = "STATE_UPDATE"
    OPPORTUNITY_UPDATE = "OPPORTUNITY_UPDATE"
    EVIDENCE_UPDATE    = "EVIDENCE_UPDATE"
    MEMORY_QUERY       = "MEMORY_QUERY"
    MEMORY_RESULT      = "MEMORY_RESULT"
    APPROVAL_REQUIRED  = "APPROVAL_REQUIRED"
    APPROVAL_RESULT    = "APPROVAL_RESULT"
    # v2.1 dual-brain collaboration protocol
    PLAN_REQUEST       = "PLAN_REQUEST"
    PLAN_RESULT        = "PLAN_RESULT"
    RESEARCH_REQUEST   = "RESEARCH_REQUEST"
    RESEARCH_RESULT    = "RESEARCH_RESULT"
    REVIEW_REQUEST     = "REVIEW_REQUEST"
    REVIEW_RESULT      = "REVIEW_RESULT"
    EXECUTION_REQUEST  = "EXECUTION_REQUEST"
    EXECUTION_RESULT   = "EXECUTION_RESULT"
    AUTONOMOUS_RUN_UPDATE = "AUTONOMOUS_RUN_UPDATE"
    ERROR              = "ERROR"
    NOTIFICATION       = "NOTIFICATION"


class MessageStatus(str, Enum):
    PENDING   = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    DONE      = "DONE"
    FAILED    = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT   = "TIMEOUT"


# Request types can trigger a (re)action by the destination; these are the ones
# the loop-prevention / dedup logic applies to.
REQUEST_TYPES: Set[MessageType] = {
    MessageType.USER_REQUEST,
    MessageType.TASK_REQUEST,
    MessageType.MODEL_REQUEST,
    MessageType.MEMORY_QUERY,
    MessageType.APPROVAL_REQUIRED,
    MessageType.PLAN_REQUEST,
    MessageType.RESEARCH_REQUEST,
    MessageType.REVIEW_REQUEST,
    MessageType.EXECUTION_REQUEST,
}

# Result/event types are terminal broadcasts (no loop risk, no dedup).
RESULT_TYPES: Set[MessageType] = {
    MessageType.TASK_RESULT,
    MessageType.MODEL_RESULT,
    MessageType.MEMORY_RESULT,
    MessageType.APPROVAL_RESULT,
    MessageType.STATE_UPDATE,
    MessageType.OPPORTUNITY_UPDATE,
    MessageType.EVIDENCE_UPDATE,
    MessageType.PLAN_RESULT,
    MessageType.RESEARCH_RESULT,
    MessageType.REVIEW_RESULT,
    MessageType.EXECUTION_RESULT,
    MessageType.AUTONOMOUS_RUN_UPDATE,
    MessageType.NOTIFICATION,
    MessageType.ERROR,
}


class CancelledError(Exception):
    """Raised inside a long-running handler when its token is cancelled."""
    def __init__(self, reason: Optional[str] = None):
        super().__init__(reason or "operation cancelled")
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
#  Message envelope
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Message:
    """Structured internal message.

    Every field from the redesign spec is present:
      message_id, correlation_id, source, destination, message_type,
      timestamp, priority, payload, status, parent_message_id.
    """
    message_type: MessageType
    source: str
    destination: str
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    priority: int = 5
    payload: Dict[str, Any] = field(default_factory=dict)
    status: MessageStatus = MessageStatus.PENDING
    error: Optional[str] = None
    timeout: Optional[float] = None

    def __post_init__(self) -> None:
        if self.correlation_id is None:
            self.correlation_id = self.message_id

    # ── convenience accessors ──────────────────────────────────────────────
    def text(self) -> str:
        return self.payload.get("text", "") if isinstance(self.payload, dict) else ""

    def set_text(self, value: str) -> "Message":
        self.payload["text"] = value
        return self

    def derive(self, mtype: MessageType, source: Optional[str] = None,
               destination: Optional[str] = None, **extra: Any) -> "Message":
        """Create a child message that correlates back to this one."""
        return Message(
            message_type=mtype,
            source=source if source is not None else self.destination,
            destination=destination if destination is not None else self.source,
            correlation_id=self.correlation_id,
            parent_message_id=self.message_id,
            priority=self.priority,
            payload={**self.payload, **extra},
        )

    def as_error(self, err: str) -> "Message":
        return self.derive(MessageType.ERROR, source=self.destination,
                           destination=self.source, error=err)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "parent_message_id": self.parent_message_id,
            "source": self.source,
            "destination": self.destination,
            "message_type": self.message_type.value,
            "timestamp": self.timestamp,
            "priority": self.priority,
            "payload": self.payload,
            "status": self.status.value,
            "error": self.error,
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Message":
        return cls(
            message_type=MessageType(d["message_type"]),
            source=d["source"],
            destination=d["destination"],
            message_id=d.get("message_id") or uuid.uuid4().hex,
            correlation_id=d.get("correlation_id"),
            parent_message_id=d.get("parent_message_id"),
            timestamp=d.get("timestamp", time.time()),
            priority=d.get("priority", 5),
            payload=d.get("payload", {}) or {},
            status=MessageStatus(d.get("status", "PENDING")),
            error=d.get("error"),
            timeout=d.get("timeout"),
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Cancellation token
# ─────────────────────────────────────────────────────────────────────────────

class CancellationToken:
    """Cooperative cancellation primitive for long-running bus handlers."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self.reason: Optional[str] = None

    def cancel(self, reason: Optional[str] = None) -> None:
        with self._lock:
            self.reason = reason
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledError(self.reason)

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._event.wait(timeout)


# ─────────────────────────────────────────────────────────────────────────────
#  Event bus
# ─────────────────────────────────────────────────────────────────────────────

Handler = Callable[[Message], None]


class EventBus:
    """
    Thread-safe, typed, observable message router.

    - Subscribers register by handler, message_type, destination, or source.
    - publish() performs loop-prevention (cycle + self-loop) and dedup of
      already-delivered request message_ids.
    - Cancellation tokens are tracked per message_id / correlation_id.
    - All delivery is synchronous within publish(); callers that need async
      delivery push onto their own thread queue inside the handler.
    """

    _instance: Optional["EventBus"] = None

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: List[Handler] = []
        self._by_type: Dict[MessageType, List[Handler]] = {}
        self._by_dest: Dict[str, List[Handler]] = {}
        self._by_source: Dict[str, List[Handler]] = {}
        # message_id -> Message (currently/last seen in flight)
        self._inflight: Dict[str, Message] = {}
        # message_id -> delivery count (for dedup of request types)
        self._delivered: Dict[str, int] = {}
        # correlation_id -> set of (source, destination) edges already traversed
        self._edges: Dict[str, Set[Tuple[str, str]]] = {}
        # message_id -> CancellationToken
        self._tokens: Dict[str, CancellationToken] = {}
        # correlation_id -> CancellationToken
        self._tokens_by_corr: Dict[str, CancellationToken] = {}
        self.max_loop_depth = 6
        # observability counters
        self.loop_violations = 0
        self.dedup_drops = 0
        self.total_published = 0

    # ── singleton ──────────────────────────────────────────────────────────
    @classmethod
    def instance(cls) -> "EventBus":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> "EventBus":
        """Replace the singleton with a fresh one (used by tests)."""
        cls._instance = cls()
        return cls._instance

    # ── subscription ───────────────────────────────────────────────────────
    def subscribe(self, handler: Handler) -> None:
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)

    def unsubscribe(self, handler: Handler) -> None:
        with self._lock:
            if handler in self._handlers:
                self._handlers.remove(handler)
            for lst in (self._by_type, self._by_dest, self._by_source):
                for lst2 in lst.values():
                    if handler in lst2:
                        lst2.remove(handler)

    def subscribe_type(self, mtype: MessageType, handler: Handler) -> None:
        with self._lock:
            self._by_type.setdefault(mtype, [])
            if handler not in self._by_type[mtype]:
                self._by_type[mtype].append(handler)

    def subscribe_destination(self, dest: str, handler: Handler) -> None:
        with self._lock:
            self._by_dest.setdefault(dest, [])
            if handler not in self._by_dest[dest]:
                self._by_dest[dest].append(handler)

    def subscribe_source(self, src: str, handler: Handler) -> None:
        with self._lock:
            self._by_source.setdefault(src, [])
            if handler not in self._by_source[src]:
                self._by_source[src].append(handler)

    # ── helpers ─────────────────────────────────────────────────────────────
    def _depth(self, msg: Message) -> int:
        """Walk the parent chain via _inflight to compute correlation depth."""
        seen = set()
        depth = 0
        cur = msg.parent_message_id
        while cur and cur not in seen:
            seen.add(cur)
            depth += 1
            parent = self._inflight.get(cur)
            if parent is None:
                break
            cur = parent.parent_message_id
        return depth

    def get_token(self, correlation_id: str) -> CancellationToken:
        with self._lock:
            tok = self._tokens_by_corr.get(correlation_id)
            if tok is None:
                tok = CancellationToken()
                self._tokens_by_corr[correlation_id] = tok
            return tok

    # ── publish ─────────────────────────────────────────────────────────────
    def publish(self, msg: Message, token: Optional[CancellationToken] = None) -> bool:
        """
        Route a message to all matching subscribers.

        Returns True if delivered (or accepted), False if rejected by loop
        prevention / dedup. On rejection the message status is set to FAILED
        with an explanatory error and an ERROR message is emitted.
        """
        with self._lock:
            self.total_published += 1

            # 1) Loop prevention — self-loop (A -> A).
            if msg.message_type in REQUEST_TYPES and msg.destination == msg.source:
                self.loop_violations += 1
                msg.status = MessageStatus.FAILED
                msg.error = "self-loop rejected (destination == source)"
                self._emit_error(msg)
                return False

            # 2) Loop prevention — ping-pong / cycle for REQUEST types.
            #    Reject if this request would route back to a node that already
            #    *initiated* a request in this correlation chain (i.e. a node
            #    that previously appeared as a source). This structurally forbids
            #    Chat↔Manager request loops without blocking legitimate
            #    RESULT/event messages returning to the originator.
            if msg.message_type in REQUEST_TYPES:
                prior_sources = self._prior_sources(msg)
                if msg.destination in prior_sources:
                    self.loop_violations += 1
                    msg.status = MessageStatus.FAILED
                    msg.error = f"circular route rejected (back to prior source {msg.destination!r})"
                    self._emit_error(msg)
                    return False
                edges = self._edges.setdefault(msg.correlation_id or msg.message_id, set())
                edge = (msg.source, msg.destination)
                if edge in edges:
                    self.loop_violations += 1
                    msg.status = MessageStatus.FAILED
                    msg.error = "circular route rejected (edge replay)"
                    self._emit_error(msg)
                    return False

            # 3) Dedup — same request message_id delivered more than once.
            if msg.message_type in REQUEST_TYPES and msg.message_id in self._delivered:
                self.dedup_drops += 1
                msg.status = MessageStatus.FAILED
                msg.error = "duplicate message_id dropped"
                self._emit_error(msg)
                return False

            # accept
            self._inflight[msg.message_id] = msg
            self._delivered[msg.message_id] = self._delivered.get(msg.message_id, 0) + 1
            edges = self._edges.setdefault(msg.correlation_id or msg.message_id, set())
            edges.add((msg.source, msg.destination))
            if token is not None:
                self._tokens[msg.message_id] = token
                self._tokens_by_corr[msg.correlation_id or msg.message_id] = token
            msg.status = MessageStatus.IN_FLIGHT

        # deliver outside the lock to avoid deadlocks from re-entrant publish
        self._deliver(msg)
        return True

    def _prior_sources(self, msg: Message) -> set:
        """Walk the parent chain for this correlation and collect every node
        that has *initiated* a request (appeared as a source). Used by loop
        prevention to reject pings back to an originator."""
        sources = set()
        seen = set()
        cur = msg
        while cur is not None and cur.message_id not in seen:
            seen.add(cur.message_id)
            sources.add(cur.source)
            pid = cur.parent_message_id
            cur = self._inflight.get(pid) if pid else None
            if cur is None and pid is not None:
                # parent may have been delivered already; best-effort only
                break
        return sources

    def _emit_error(self, original: Message) -> None:
        err = original.derive(MessageType.ERROR, source=original.destination,
                              destination=original.source, error=original.error or "rejected")
        err.status = MessageStatus.FAILED
        with self._lock:
            self._inflight[err.message_id] = err
            self._delivered[err.message_id] = 1
        try:
            self._deliver(err)
        except Exception:
            pass

    def _deliver(self, msg: Message) -> None:
        with self._lock:
            handlers = set(self._handlers)
            handlers |= set(self._by_type.get(msg.message_type, []))
            handlers |= set(self._by_dest.get(msg.destination, []))
            handlers |= set(self._by_source.get(msg.source, []))
            handlers = list(handlers)
        for h in handlers:
            try:
                h(msg)
            except Exception:
                # a misbehaving handler must never break delivery to others
                pass

    # ── cancellation ────────────────────────────────────────────────────────
    def cancel(self, message_id_or_correlation: str,
               reason: Optional[str] = None) -> bool:
        """Cancel by message_id or correlation_id. Returns True if a token was found."""
        with self._lock:
            tok = self._tokens.get(message_id_or_correlation) \
                or self._tokens_by_corr.get(message_id_or_correlation)
            # also try to find by correlation if it was a message_id we don't have
            if tok is None:
                msg = self._inflight.get(message_id_or_correlation)
                if msg is not None:
                    tok = self._tokens_by_corr.get(msg.correlation_id)
            if tok is None:
                return False
            tok.cancel(reason)
            # mark any in-flight message(s) for this correlation as CANCELLED
            for mid, m in list(self._inflight.items()):
                if mid == message_id_or_correlation or \
                        m.correlation_id == message_id_or_correlation:
                    m.status = MessageStatus.CANCELLED
            return True

    # ── convenience factories ───────────────────────────────────────────────
    def request(self, source: str, destination: str, mtype: MessageType,
                payload: Optional[Dict[str, Any]] = None,
                parent: Optional[Message] = None,
                priority: int = 5,
                token: Optional[CancellationToken] = None) -> Message:
        msg = Message(
            message_type=mtype,
            source=source,
            destination=destination,
            payload=payload or {},
            priority=priority,
            parent_message_id=parent.message_id if parent is not None else None,
            correlation_id=parent.correlation_id if parent is not None else None,
        )
        self.publish(msg, token=token)
        return msg

    def publish_error(self, correlation_id: str, source: str, destination: str,
                      error: str) -> Message:
        msg = Message(
            message_type=MessageType.ERROR,
            source=source,
            destination=destination,
            correlation_id=correlation_id,
            payload={"error": error},
            status=MessageStatus.FAILED,
        )
        self.publish(msg)
        return msg

    # ── observability / reset ───────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_published": self.total_published,
                "loop_violations": self.loop_violations,
                "dedup_drops": self.dedup_drops,
                "inflight": len(self._inflight),
                "tokens": len(self._tokens),
            }

    def reset(self) -> None:
        with self._lock:
            self._handlers.clear()
            self._by_type.clear()
            self._by_dest.clear()
            self._by_source.clear()
            self._inflight.clear()
            self._delivered.clear()
            self._edges.clear()
            self._tokens.clear()
            self._tokens_by_corr.clear()
            self.loop_violations = 0
            self.dedup_drops = 0
            self.total_published = 0


# ── Qt delivery bridge ────────────────────────────────────────────────────
# The bus is pure Python; GUI widgets live on the Qt thread. This optional
# bridge subscribes to the bus and re-emits a Qt Signal so widgets receive
# messages on the GUI thread (QueuedConnection) without ever touching model
# internals. Import-guarded so comms.py stays Qt-free for the test suite.
try:
    from PySide6.QtCore import QObject, Signal as QtSignal

    class QtEventBridge(QObject):
        """Re-emits every bus Message as a Qt signal on the GUI thread."""
        message = QtSignal(object)

        def __init__(self, bus: "EventBus | None" = None, parent=None):
            super().__init__(parent)
            self._bus = bus or EventBus.instance()
            self._bus.subscribe(self._on_bus)

        def _on_bus(self, msg: Message) -> None:
            self.message.emit(msg)
except Exception:  # pragma: no cover - Qt optional
    QtEventBridge = None  # type: ignore


# Backwards-friendly aliases used by some call sites / docs.
BusMessage = Message
MESSAGE_TYPES = list(MessageType)

