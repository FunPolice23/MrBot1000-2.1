"""agents/notifications.py — Notification service: Windows toast + in-app panel."""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("mrbot.notifications")

# Levels map to severity; CRITICAL and APPROVAL_REQUIRED are high-priority.
class NotifLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    APPROVAL_REQUIRED = "approval_required"   # human gate triggered
    CRITICAL = "critical"                      # safety / credit critical


@dataclass
class Notif:
    """A single notification event."""
    id: str = ""
    title: str = ""
    message: str = ""
    level: str = NotifLevel.INFO.value
    sticky: bool = False            # keep in panel until dismissed
    source: str = ""                # e.g. "heartbeat", "earning", "safety"
    ts: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            import uuid
            self.id = uuid.uuid4().hex
        if self.ts == 0.0:
            self.ts = time.time()


class NotificationService:
    """Central notification hub.

    - In-app list kept in a thread-safe queue; GUI polls or listens.
    - High-priority notifications attempt a Windows toast when a running
      QApplication is available; that path is best-effort and non-fatal.
    """

    _instance: Optional["NotificationService"] = None
    lock = threading.Lock()

    def __init__(self):
        self._queue: "queue.Queue[Notif]" = queue.Queue()
        self._history: List[Notif] = []
        self.max_history = 200
        self._listeners: List[Callable[[Notif], None]] = []
        self._toast_available = False

    # ── Singleton ──────────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "NotificationService":
        with cls.lock:
            if cls._instance is None:
                cls._instance = cls.__new__(cls)
                cls._instance.__init__()
            return cls._instance

    @classmethod
    def reset_singleton(cls):
        with cls.lock:
            cls._instance = None

    # ── Push ───────────────────────────────────────────────────────────────────

    def push(self, title: str, message: str, level: str = NotifLevel.INFO.value,
             sticky: bool = False, source: str = "", payload: Dict[str, Any] = None) -> Notif:
        note = Notif(
            title=title,
            message=message,
            level=level,
            sticky=sticky,
            source=source,
            payload=payload or {},
        )
        self._enqueue(note)
        # Notify listeners synchronously
        for cb in list(self._listeners):
            try:
                cb(note)
            except Exception:
                pass
        return note

    def _enqueue(self, note: Notif):
        try:
            self._queue.put_nowait(note)
        except queue.Full:
            pass
        self._history.append(note)
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]

    # ── History / queue ───────────────────────────────────────────────────────

    def history(self, limit: int = 100) -> List[Notif]:
        return list(self._history[-limit:])

    def recent(self, level: Optional[str] = None, limit: int = 50) -> List[Notif]:
        items = self._history
        if level:
            items = [n for n in items if n.level == level]
        return items[-limit:]

    def pending(self) -> List[Notif]:
        """Return items that have not been acknowledged/dismissed."""
        # For now, all sticky items are 'pending' in-app.
        return [n for n in self._history if n.sticky]

    def dismiss(self, note_id: str) -> bool:
        """Remove a sticky note from history."""
        for i, n in enumerate(self._history):
            if n.id == note_id:
                self._history.pop(i)
                return True
        return False

    # ── Listeners ─────────────────────────────────────────────────────────────

    def subscribe(self, cb: Callable[[Notif], None]):
        self._listeners.append(cb)

    def unsubscribe(self, cb: Callable[[Notif], None]):
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

    # ── Windows toast (best-effort) ───────────────────────────────────────────

    def try_toast(self, note: Notif):
        """Attempt a system toast; non-fatal if unavailable."""
        if not self._toast_available:
            return
        try:
            self._send_toast(note)
        except Exception:
            logger.debug("toast send failed", exc_info=True)

    def _send_toast(self, note: Notif):
        # Windows 10/11 toast via win10toast if available; else fallback.
        try:
            import win10toast
            toaster = win10toast.ToastNotifier()
            toaster.show_toast(
                note.title,
                note.message,
                icon_path=None,
                duration=5,
                threaded=False,
            )
        except Exception as e:
            logger.warning("win10toast unavailable: %s", e)

    def detect_toast_support(self):
        """Check once whether win10toast is importable."""
        try:
            import win10toast  # noqa: F401
            self._toast_available = True
        except Exception:
            self._toast_available = False

    # ── Convenience helpers ───────────────────────────────────────────────────

    def info(self, title: str, message: str, **kw):
        return self.push(title, message, NotifLevel.INFO.value, **kw)

    def success(self, title: str, message: str, **kw):
        return self.push(title, message, NotifLevel.SUCCESS.value, **kw)

    def warning(self, title: str, message: str, **kw):
        return self.push(title, message, NotifLevel.WARNING.value, **kw)

    def error(self, title: str, message: str, **kw):
        return self.push(title, message, NotifLevel.ERROR.value, **kw)

    def approval_required(self, title: str, message: str, **kw):
        kw.setdefault("sticky", True)
        n = self.push(title, message, NotifLevel.APPROVAL_REQUIRED.value, **kw)
        self.try_toast(n)
        return n

    def critical(self, title: str, message: str, **kw):
        kw.setdefault("sticky", True)
        n = self.push(title, message, NotifLevel.CRITICAL.value, **kw)
        self.try_toast(n)
        return n


def notify(title: str, message: str, level: str = NotifLevel.INFO.value, **kw):
    """Module-level convenience; uses singleton."""
    return NotificationService.instance().push(title, message, level, **kw)


__all__ = [
    "NotificationService",
    "notify",
    "Notif",
    "NotifLevel",
]
