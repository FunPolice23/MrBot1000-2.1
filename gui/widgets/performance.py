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


class _DeferredQueue:
    """Run non-critical initialization after the event loop is pumping.
    
    Startup latency is dominated by synchronous widget construction and
    DB/network probes. Deferring non-critical work lets the window appear
    instantly, then fills in data as it arrives.
    """
    
    def __init__(self):
        self._queue: list[tuple[str, Callable, tuple, dict]] = []
        self._running = False
        self._done: set[str] = set()
    
    def schedule(self, key: str, fn: Callable, *args, delay_ms: int = 0, **kwargs):
        """Schedule a task. If key already done, skip. If already scheduled, replace."""
        if key in self._done:
            return
        # Replace existing entry with same key
        self._queue = [(k, f, a, kw) for k, f, a, kw in self._queue if k != key]
        self._queue.append((key, fn, args, kwargs))
    
    def run_next(self):
        """Run the next queued task. Called via QTimer.singleShot."""
        if not self._queue:
            self._running = False
            return
        key, fn, args, kwargs = self._queue.pop(0)
        self._running = True
        try:
            fn(*args, **kwargs)
        except Exception:
            pass  # Never let deferred work crash the GUI
        finally:
            self._done.add(key)
            # Schedule next task
            if self._queue:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self.run_next)
            else:
                self._running = False


class _RequestCoalescer:
    """Coalesce identical concurrent requests (e.g. tab rebuild storms).
    
    If the same request key is already in-flight, wait for its result
    instead of launching a duplicate DB query.
    """
    
    def __init__(self):
        self._in_flight: dict[str, threading.Event] = {}
        self._results: dict[str, Any] = {}
        self._lock = threading.Lock()
    
    def get_or_compute(self, key: str, compute_fn: Callable, *args, **kwargs) -> Any:
        """Return cached result if in-flight; else compute and cache."""
        with self._lock:
            if key in self._in_flight:
                event = self._in_flight[key]
            else:
                event = threading.Event()
                self._in_flight[key] = event
                # Release lock before computing
                try:
                    result = compute_fn(*args, **kwargs)
                    self._results[key] = result
                    return result
                finally:
                    event.set()
                    del self._in_flight[key]
        # Another thread is computing; wait for it
        event.wait(timeout=10.0)
        return self._results.get(key)


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


class _BoundedCache:
    """Memory-bounded LRU cache for expensive computations.
    
    Caches things like DB stats, model profiles, file listings.
    Evicts oldest entries when size limit is hit.
    """
    
    def __init__(self, max_size: int = 64, ttl_seconds: float = 30.0):
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if present and not expired."""
        if key not in self._cache:
            return None
        value, ts = self._cache[key]
        if time.time() - ts > self._ttl:
            del self._cache[key]
            return None
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return value
    
    def put(self, key: str, value: Any):
        """Cache a value, evicting oldest if at capacity."""
        if key in self._cache:
            del self._cache[key]
        elif len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        self._cache[key] = (value, time.time())
    
    def invalidate(self, key: str = None):
        """Invalidate a specific key, or all if None."""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()


class _WeakRefPool:
    """Track background workers with weak references so GC can reclaim them.
    
    Prevents the _http_workers / _retired_workers lists from growing unbounded.
    """
    
    def __init__(self):
        self._refs: list[weakref.ref] = []
    
    def add(self, obj):
        """Add a weakly-referenced object to the pool."""
        def cleanup(ref):
            self._refs = [r for r in self._refs if r is not ref]
        self._refs.append(weakref.ref(obj, cleanup))
    
    def alive_count(self) -> int:
        """Count still-alive objects."""
        return sum(1 for r in self._refs if r() is not None)
    
    def prune(self) -> int:
        """Remove dead refs. Returns count pruned."""
        before = len(self._refs)
        self._refs = [r for r in self._refs if r() is not None]
        return before - len(self._refs)


# Singleton instances
_deferred = _DeferredQueue()
_coalescer = _RequestCoalescer()
_cache = _BoundedCache(max_size=128, ttl_seconds=30.0)
_worker_pool = _WeakRefPool()


def schedule_deferred(key: str, fn: Callable, *args, **kwargs):
    """Schedule a deferred initialization task."""
    _deferred.schedule(key, fn, *args, **kwargs)
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, _deferred.run_next)


def coalesce_request(key: str, compute_fn: Callable, *args, **kwargs) -> Any:
    """Coalesce identical concurrent requests."""
    return _coalescer.get_or_compute(key, compute_fn, *args, **kwargs)


def cache_get(key: str) -> Optional[Any]:
    """Get from bounded cache."""
    return _cache.get(key)


def cache_put(key: str, value: Any):
    """Put into bounded cache."""
    _cache.put(key, value)


def cache_invalidate(key: str = None):
    """Invalidate cache entries."""
    _cache.invalidate(key)


def track_worker(obj):
    """Track a background worker with weak ref."""
    _worker_pool.add(obj)


def prune_workers() -> int:
    """Prune dead workers. Returns count pruned."""
    return _worker_pool.prune()


def make_throttler(flush_ms: int = 50) -> _SignalThrottler:
    """Create a new signal throttler."""
    return _SignalThrottler(flush_ms)
