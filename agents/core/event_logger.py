"""agents/event_logger.py — Unified structured event logger (Phase 6).

Ties together:
- Evidence store (provenance proofs, payout records)
- Comms (task execution, approval outcomes)
- Safety events (cost cap, recursion, tool firewall, human gate)
- Heartbeat ticks (tier, credits, tasks executed)
- LLM spend events
- System lifecycle events (agent start/stop, model switch)

All events land in one rotating JSONL log + in-memory index, queryable by
the desktop GUI (timestamp, level, source, event_type, free-text search).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mrbot.event_logger")


# ── Event types ─────────────────────────────────────────────────────────────

class EventLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"


class EventType(str, Enum):
    """High-level category for filtering in the GUI."""
    INFO = "info"
    EARNING = "earning"
    APPROVAL = "approval"
    SAFETY = "safety"
    LLM_SPEND = "llm_spend"
    SYSTEM = "system"
    HEARTBEAT = "heartbeat"
    EVIDENCE = "evidence"
    COMMUNICATION = "communication"
    NOTIFICATION = "notification"


@dataclass
class Event:
    """A single structured event in the unified log."""
    id: str = ""
    ts: float = 0.0
    level: str = EventLevel.INFO.value
    event_type: str = EventType.INFO.value
    source: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    session_id: str = ""
    tags: List[str] = field(default_factory=list)
    prev_hash: str = ""  # Hash-chained ledger: hash of previous event
    hash: str = ""       # Hash of this event (sha256 of content + prev_hash)

    def __post_init__(self):
        if self.id == "":
            self.id = uuid.uuid4().hex
        if self.ts == 0.0:
            self.ts = time.time()
        if self.session_id == "":
            self.session_id = os.environ.get("MRBOT_SESSION", "default")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "level": self.level,
            "event_type": self.event_type,
            "source": self.source,
            "message": self.message,
            "details": self.details,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "tags": self.tags,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Event":
        return cls(
            id=d.get("id", ""),
            ts=d.get("ts", time.time()),
            level=d.get("level", EventLevel.INFO.value),
            event_type=d.get("event_type", EventType.INFO.value),
            source=d.get("source", ""),
            message=d.get("message", ""),
            details=d.get("details", {}),
            correlation_id=d.get("correlation_id", ""),
            session_id=d.get("session_id", ""),
            tags=d.get("tags", []) or [],
            prev_hash=d.get("prev_hash", ""),
            hash=d.get("hash", ""),
        )

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of this event's content chained to prev_hash."""
        import hashlib
        content = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256((content + self.prev_hash).encode()).hexdigest()

    @property
    def iso_ts(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc).isoformat()


# ── Logger ───────────────────────────────────────────────────────────────────

class StructuredEventLogger:
    """Unified event logger with rotating JSONL + in-memory index."""

    _instance: Optional["StructuredEventLogger"] = None
    _lock = None

    def __init__(
        self,
        log_dir: Optional[str] = None,
        max_file_mb: int = 20,
        max_files: int = 5,
        max_in_memory: int = 2000,
    ):
        self.log_dir = log_dir or os.path.join(
            os.environ.get("LOCALAPPDATA", "."), "MrBot1000", "logs"
        )
        self.max_file_mb = max_file_mb
        self.max_files = max_files
        self.max_in_memory = max_in_memory
        self._events: List[Event] = []
        self._index: Dict[str, List[int]] = defaultdict(list)  # event_type -> [idx]
        self._level_index: Dict[str, List[int]] = defaultdict(list)
        self._source_index: Dict[str, List[int]] = defaultdict(list)
        self._free_text_index: Dict[str, List[int]] = defaultdict(list)
        self._current_file: Optional[str] = None
        self._file_size: int = 0
        self._next_rotation_check: float = 0.0
        self.on_log: Optional[Callable[[Event], None]] = None  # Phase 6 bridge
        self._event_callbacks: List[Callable[[Event], None]] = []  # Phase 6 goal tracker
        self._ensure_dir()

    # ── Singleton ────────────────────────────────────────────────────────────

    @classmethod
    def _get_lock(cls):
        import threading as _t
        if cls._lock is None:
            cls._lock = _t.Lock()
        return cls._lock

    @classmethod
    def instance(cls) -> "StructuredEventLogger":
        with cls._get_lock():
            if cls._instance is None:
                cls._instance = cls.__new__(cls)
                cls._instance.__init__()
            return cls._instance

    @classmethod
    def reset_singleton(cls):
        with cls._get_lock():
            cls._instance = None

    # ── Event callbacks (Phase 6: goal tracker) ─────────────────────────────

    def add_event_callback(self, callback: Callable[[Event], None]):
        """Register a callback to be called on every logged event."""
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)

    def remove_event_callback(self, callback: Callable[[Event], None]):
        """Remove a previously registered callback."""
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)

    # ── Directory setup ──────────────────────────────────────────────────────

    def _ensure_dir(self):
        os.makedirs(self.log_dir, exist_ok=True)

    # ── Log file selection ────────────────────────────────────────────────────

    def _current_log_path(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"events-{today}.jsonl")

    def _should_rotate(self, event_size: int) -> bool:
        path = self._current_log_path()
        if not os.path.isfile(path):
            return False
        total = os.path.getsize(path) + event_size
        return total > self.max_file_mb * 1024 * 1024

    def _rotate(self):
        """Close current file and start a fresh one."""
        self._current_file = None
        self._file_size = 0
        self._next_rotation_check = 0.0
        self._prune_old_files()

    def _prune_old_files(self):
        """Keep only the most recent max_files log files."""
        try:
            files = sorted(
                f for f in os.listdir(self.log_dir)
                if f.startswith("events-") and f.endswith(".jsonl")
            )
            while len(files) > self.max_files:
                oldest = files.pop(0)
                try:
                    os.remove(os.path.join(self.log_dir, oldest))
                except Exception:
                    pass
        except Exception:
            pass

    # ── Indexing ─────────────────────────────────────────────────────────────

    def _index_event(self, idx: int, ev: Event):
        self._index[ev.event_type].append(idx)
        self._level_index[ev.level].append(idx)
        self._source_index[ev.source].append(idx)
        text = f"{ev.message} {ev.event_type} {ev.source} {' '.join(ev.tags)}"
        for word in text.lower().split():
            if len(word) >= 3:
                self._free_text_index[word].append(idx)

    # ── Public API ────────────────────────────────────────────────────────────

    def log(self, event: Event) -> Event:
        """Log an event. Hash-chains it to the previous event for tamper
        evidence."""
        # Hash chain: set prev_hash from last event's hash
        if self._events:
            event.prev_hash = self._events[-1].hash
            event.hash = event.compute_hash()
        else:
            event.prev_hash = ""
            event.hash = event.compute_hash()

        self._maybe_rotate(len(json.dumps(event.to_dict(), default=str)))
        self._write_event(event)
        idx = len(self._events)
        self._events.append(event)
        self._index_event(idx, event)
        self._prune_in_memory()
        # Phase 6: fire callback for alerting engine
        if self.on_log:
            try:
                self.on_log(event)
            except Exception as e:
                logger.warning("event_logger.on_log callback failed: %s", e)
        # Phase 6: fire event callbacks (goal tracker, etc.)
        for cb in self._event_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.warning("event_logger._event_callback failed: %s", e)
        return event

    def _write_event(self, event: Event):
        path = self._current_log_path()
        try:
            # Use default=str to handle non-serializable objects gracefully
            event_json = json.dumps(event.to_dict(), default=str)
            with open(path, "a", encoding="utf-8") as f:
                f.write(event_json + "\n")
            self._file_size += len(event_json) + 1
        except Exception as e:
            logger.warning("event_logger write failed: %s", e)
            # Try to log the error without the problematic details
            try:
                safe_dict = event.to_dict()
                safe_dict["details"] = {k: str(v) for k, v in safe_dict.get("details", {}).items()}
                event_json = json.dumps(safe_dict, default=str)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(event_json + "\n")
            except Exception:
                pass

    def _maybe_rotate(self, event_size: int):
        if self._should_rotate(event_size):
            self._rotate()

    def _prune_in_memory(self):
        if len(self._events) > self.max_in_memory:
            excess = len(self._events) - self.max_in_memory
            removed = self._events[:excess]
            self._events = self._events[excess:]
            # Rebuild indexes from scratch (simpler than incremental removal)
            self._index.clear()
            self._level_index.clear()
            self._source_index.clear()
            self._free_text_index.clear()
            for i, ev in enumerate(self._events):
                self._index_event(i, ev)

    # ── Queries ──────────────────────────────────────────────────────────────

    def query(
        self,
        event_type: Optional[str] = None,
        level: Optional[str] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> List[Event]:
        """Query the in-memory event log."""
        candidates = set(range(len(self._events)))

        if event_type:
            candidates &= set(self._index.get(event_type, []))
        if level:
            candidates &= set(self._level_index.get(level, []))
        if source:
            candidates &= set(self._source_index.get(source, []))
        if search:
            words = search.lower().split()
            if words:
                idx_sets = [self._free_text_index.get(w, []) for w in words]
                candidates &= set(idx_sets[0]) if idx_sets else set()
                for s in idx_sets[1:]:
                    candidates &= s

        results = []
        for idx in sorted(candidates, reverse=True):
            ev = self._events[idx]
            if since is not None and ev.ts < since:
                continue
            if until is not None and ev.ts > until:
                continue
            results.append(ev)
            if len(results) >= limit:
                break

        return results[offset: offset + limit]

    def recent(
        self,
        event_type: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 50,
    ) -> List[Event]:
        """Recent events, newest first."""
        all_ev = self._events[-limit * 3:] if len(self._events) > limit * 3 else self._events
        filtered = all_ev
        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        if level:
            filtered = [e for e in filtered if e.level == level]
        return filtered[-limit:][::-1]

    def count_by_type(self) -> Dict[str, int]:
        counts = defaultdict(int)
        for ev in self._events:
            counts[ev.event_type] += 1
        return dict(counts)

    def last_event_of_type(self, event_type: str) -> Optional[Event]:
        for ev in reversed(self._events):
            if ev.event_type == event_type:
                return ev
        return None

    def clear_in_memory(self):
        """Free in-memory events (logged events in JSONL are preserved)."""
        self._events.clear()
        self._index.clear()
        self._level_index.clear()
        self._source_index.clear()
        self._free_text_index.clear()

    # ── Convenience helpers ──────────────────────────────────────────────────

    def info(self, event_type: str, message: str, source: str = "",
             details: Dict[str, Any] = None, tags: List[str] = None, **kw):
        ev = Event(
            event_type=event_type,
            level=EventLevel.INFO.value,
            message=message,
            source=source,
            details=details or {},
            tags=tags or [],
            **kw,
        )
        return self.log(ev)

    def warning(self, event_type: str, message: str, source: str = "",
                details: Dict[str, Any] = None, tags: List[str] = None, **kw):
        ev = Event(
            event_type=event_type,
            level=EventLevel.WARNING.value,
            message=message,
            source=source,
            details=details or {},
            tags=tags or [],
            **kw,
        )
        return self.log(ev)

    def error(self, event_type: str, message: str, source: str = "",
              details: Dict[str, Any] = None, tags: List[str] = None, **kw):
        ev = Event(
            event_type=event_type,
            level=EventLevel.ERROR.value,
            message=message,
            source=source,
            details=details or {},
            tags=tags or [],
            **kw,
        )
        return self.log(ev)

    def critical(self, event_type: str, message: str, source: str = "",
                 details: Dict[str, Any] = None, tags: List[str] = None, **kw):
        ev = Event(
            event_type=event_type,
            level=EventLevel.CRITICAL.value,
            message=message,
            source=source,
            details=details or {},
            tags=tags or [],
            **kw,
        )
        return self.log(ev)

    # ── Domain-specific helpers ──────────────────────────────────────────────

    def earning_event(self, action: str, revenue: float = 0.0,
                      cost: float = 0.0, platform: str = "",
                      success: bool = False, **kw):
        return self.log(Event(
            event_type=EventType.EARNING.value,
            level=EventLevel.INFO.value,
            message=f"earning:{action}",
            source="earning",
            details={"action": action, "revenue": revenue, "cost": cost,
                     "platform": platform, "success": success},
            tags=["earning", action, platform] if platform else ["earning", action],
            **kw,
        ))

    def safety_event(self, gate_type: str, blocked: bool,
                     description: str = "", **kw):
        return self.log(Event(
            event_type=EventType.SAFETY.value,
            level=EventLevel.WARNING.value if blocked else EventLevel.INFO.value,
            message=f"safety:{gate_type}:{'blocked' if blocked else 'passed'}",
            source="safety",
            details={"gate_type": gate_type, "blocked": blocked,
                     "description": description},
            tags=["safety", gate_type],
            **kw,
        ))

    def llm_spend_event(self, model: str, provider: str, tokens: int,
                        est_usd: float, **kw):
        return self.log(Event(
            event_type=EventType.LLM_SPEND.value,
            level=EventLevel.DEBUG.value,
            message=f"llm_spend:{model}:{provider}",
            source="llm_cost",
            details={"model": model, "provider": provider,
                     "tokens": tokens, "est_usd": est_usd},
            tags=["llm_spend", model],
            **kw,
        ))

    def heartbeat_event(self, tier: str, credits: float,
                        tasks_run: int, errors: int, **kw):
        return self.log(Event(
            event_type=EventType.HEARTBEAT.value,
            level=EventLevel.INFO.value,
            message=f"heartbeat:tier={tier}",
            source="heartbeat",
            details={"tier": tier, "credits": credits,
                     "tasks_run": tasks_run, "errors": errors},
            tags=["heartbeat", tier],
            **kw,
        ))


# ── Module-level convenience ─────────────────────────────────────────────────

def log_event(event_type: str, message: str, level: str = EventLevel.INFO.value,
              source: str = "", **kw) -> Event:
    return StructuredEventLogger.instance().log(Event(
        event_type=event_type, level=level, message=message, source=source, **kw
    ))


__all__ = [
    "StructuredEventLogger",
    "Event",
    "EventLevel",
    "EventType",
    "log_event",
]
