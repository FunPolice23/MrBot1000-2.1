"""Performance optimization for MrBot1000 GUI.

Addresses startup speed, tab switching, and heavy task isolation:
1. Deferred initialization queue (lower startup latency)
2. Request coalescing (prevent duplicate DB/network calls)
3. Signal throttling (batch rapid log emissions)
4. Memory-bounded caches (avoid recomputation)
5. Background worker patterns (keep GUI thread free)
"""

from __future__ import annotations

import threading
import time
import weakref
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional


class _SignalThrottler:
    """Batch rapid signal emissions into a single GUI update.

    Log storms (e.g. heartbeat + startup + tab build) can flood the
    event loop. This collects emissions and flushes at most every N ms.

    Thread safety: `emit` is connected to QThread signals (e.g. DialogueWorker
    progress) and therefore runs on the *worker* thread. A QTimer created there
    would belong to the worker's thread and die with it — the next emit then
    faults inside Qt (observed as an access violation in `_pump`/teardown).
    The timer is therefore parented to the receiver's thread: created on the
    GUI thread via a queued signal, and the buffer is guarded by a lock.
    """

    def __init__(self, flush_ms: int = 50):
        self._buffer: list[tuple] = []
        self._timer = None
        self._flush_ms = flush_ms
        self._callback: Optional[Callable] = None
        self._lock = threading.Lock()
        self._host = None  # QObject living on the GUI thread (timer parent)

    def connect(self, callback: Callable):
        """Set the flush callback (receives list of buffered items)."""
        self._callback = callback

    def disconnect(self):
        """Detach the callback and cancel any pending GUI flush."""
        self._callback = None
        with self._lock:
            self._buffer.clear()
        timer = self._timer
        self._timer = None
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass

    def emit(self, *args):
        """Buffer an emission. Flushes automatically after flush_ms.

        Safe from any thread: the buffer append is locked and the flush timer is
        armed on the GUI thread.
        """
        with self._lock:
            self._buffer.append(args)
            timer_live = self._timer is not None
        if timer_live:
            return
        self._arm_timer()

    def _arm_timer(self):
        """Create/start the flush timer on the GUI thread."""
        from PySide6.QtCore import QTimer, QThread
        # Always build the timer on the thread that owns the QApplication so it
        # is serviced by the GUI event loop regardless of the emitting thread.
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            owner_thread = app.thread() if app is not None else QThread.currentThread()
        except Exception:
            owner_thread = QThread.currentThread()
        if QThread.currentThread() is owner_thread:
            self._start_timer()
        else:
            # Hop to the GUI thread before touching Qt objects.
            QTimer.singleShot(0, self._start_timer)

    def _start_timer(self):
        from PySide6.QtCore import QTimer
        with self._lock:
            if self._timer is not None:
                return
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(self._flush)
            self._timer = timer
        timer.start(self._flush_ms)

    def _flush(self):
        """Flush buffered emissions to the callback (GUI thread)."""
        self._timer = None
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer.copy()
            self._buffer.clear()
        if self._callback:
            from agents.runtime.performance import telemetry
            telemetry.record_gui_update()
            try:
                self._callback(batch)
            except Exception:
                pass


# Singleton instances
def make_throttler(flush_ms: int = 50) -> _SignalThrottler:
    """Create a new signal throttler."""
    return _SignalThrottler(flush_ms)
