"""Runtime service helpers formerly provided by the library hub."""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class TaskQueue:
    """
    Priority task queue with deduplication (ignores exact duplicate tasks).

    Priority: 0 = highest, 10 = lowest.

    Usage::

        tq = TaskQueue()
        tq.put("fix bug in proposer.py", priority=0)
        tq.put("run heartbeat", priority=5)
        task, prio = tq.get()
    """

    def __init__(self):
        self._q: List[Tuple[int, float, str]] = []  # (priority, ts, task)
        self._seen: set = set()
        self._lock = threading.Lock()

    def put(self, task: str, priority: int = 5):
        with self._lock:
            key = hashlib.md5(task.encode()).hexdigest()
            if key in self._seen:
                return
            self._seen.add(key)
            import bisect
            bisect.insort(self._q, (priority, time.time(), task))

    def get(self, block: bool = True, timeout: float = 1.0) -> Tuple[str, int]:
        deadline = time.time() + timeout
        while True:
            with self._lock:
                if self._q:
                    prio, _, task = self._q.pop(0)
                    return task, prio
            if not block or time.time() > deadline:
                raise queue.Empty
            time.sleep(0.05)

    def __len__(self):
        with self._lock:
            return len(self._q)

    def clear(self):
        with self._lock:
            self._q.clear()
            self._seen.clear()


# ─────────────────────────────────────────────────────────────────────────────
#  AgentLogger  — structured event logger
# ─────────────────────────────────────────────────────────────────────────────
class AgentLogger:
    """
    Thin structured logger.  Writes to an AgentDB if provided, otherwise
    buffers in memory and prints to stdout.

    Usage::

        logger = AgentLogger(db=my_db, source="AnalystWorker")
        logger.info("Scan complete")
        logger.error("LLM timed out")
        logger.event("file_read", {"path": "agents/foo.py", "size": 1234})
    """

    def __init__(self, db=None, source: str = "Agent",
                 signal=None, max_buffer: int = 500):
        self.db = db
        self.source = source
        self.signal = signal          # optional Qt Signal(str)
        self._buffer: deque = deque(maxlen=max_buffer)

    def _emit(self, level: str, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}][{level}][{self.source}] {text}"
        self._buffer.append(entry)
        if self.signal:
            try:
                self.signal.emit(entry)
            except Exception:
                pass
        if self.db:
            try:
                self.db.log_thought(self.source, f"[{level}] {text}")
            except Exception:
                pass

    def info(self, text: str):   self._emit("INFO",  text)
    def warn(self, text: str):   self._emit("WARN",  text)
    def error(self, text: str):  self._emit("ERROR", text)
    def debug(self, text: str):  self._emit("DEBUG", text)

    def event(self, name: str, data: Dict = None):
        payload = json.dumps(data or {}, default=str)
        self._emit("EVENT", f"{name} {payload}")

    def recent(self, n: int = 20) -> List[str]:
        return list(self._buffer)[-n:]


# ─────────────────────────────────────────────────────────────────────────────
#  FileWatcher  — polling-based change detector
# ─────────────────────────────────────────────────────────────────────────────
class FileWatcher:
    """
    Watch a set of files/directories for changes via mtime polling.

    Usage::

        watcher = FileWatcher(interval=5.0)
        watcher.watch("/path/to/folder")
        changed = watcher.check()   # returns list of changed paths
    """

    def __init__(self, interval: float = 5.0):
        self._interval = interval
        self._mtimes: Dict[str, float] = {}
        self._paths: List[str] = []
        self._last_check = 0.0

    def watch(self, path: str):
        if path not in self._paths:
            self._paths.append(path)

    def check(self) -> List[str]:
        now = time.time()
        if now - self._last_check < self._interval:
            return []
        self._last_check = now
        changed = []
        for p_str in self._paths:
            p = Path(p_str)
            if p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file():
                        self._check_file(str(f), changed)
            elif p.is_file():
                self._check_file(p_str, changed)
        return changed

    def _check_file(self, path: str, changed: List[str]):
        try:
            mtime = Path(path).stat().st_mtime
            if path not in self._mtimes or self._mtimes[path] != mtime:
                if path in self._mtimes:
                    changed.append(path)
                self._mtimes[path] = mtime
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
#  EmbeddingCache  — keyword-based dedup / similarity cache
# ─────────────────────────────────────────────────────────────────────────────
class EmbeddingCache:
    """
    Simple keyword-based cache to avoid repeating very similar LLM calls.

    Uses Jaccard similarity on word sets — no external ML dependency.

    Usage::

        cache = EmbeddingCache(similarity_threshold=0.8, max_size=200)
        hit = cache.get("how do I fix proposer.py errors?")
        if hit is None:
            result = llm(...)
            cache.put("how do I fix proposer.py errors?", result)
    """

    def __init__(self, similarity_threshold: float = 0.8, max_size: int = 200):
        self._threshold = similarity_threshold
        self._max_size = max_size
        self._entries: List[Tuple[frozenset, str, str]] = []  # (words, key, value)
        self._lock = threading.Lock()

    @staticmethod
    def _tokenize(text: str) -> frozenset:
        return frozenset(re.findall(r"\b\w+\b", text.lower()))

    def get(self, query: str) -> Optional[str]:
        q_words = self._tokenize(query)
        with self._lock:
            for words, _key, value in self._entries:
                inter = len(q_words & words)
                union = len(q_words | words)
                if union > 0 and inter / union >= self._threshold:
                    return value
        return None

    def put(self, key: str, value: str):
        words = self._tokenize(key)
        with self._lock:
            self._entries.append((words, key, value))
            if len(self._entries) > self._max_size:
                self._entries.pop(0)

    def clear(self):
        with self._lock:
            self._entries.clear()

    def __len__(self):
        return len(self._entries)


# ─────────────────────────────────────────────────────────────────────────────
#  Convenience helpers
# ─────────────────────────────────────────────────────────────────────────────


__all__=["TaskQueue", "AgentLogger", "FileWatcher", "EmbeddingCache"]
