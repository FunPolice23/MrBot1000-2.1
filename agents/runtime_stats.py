# MrBot1000/agents/runtime_stats.py — autonomous-loop telemetry (Section E G5).
"""
Lightweight, thread-safe telemetry for the manager heartbeat loop. Extracted from
manager.py (v2.0.34ah, Section E part B) into its own reusable module.

Tracks cycle timing, error streak, and throughput so the GUI can show a "Stream
Health" readout and the loop can adapt its cadence (back off after errors, poll
faster when work is pending). No I/O; safe to call from the manager thread and
read from the GUI thread.
"""
import os
import time
import threading


class RuntimeStats:
    def __init__(self):
        self._lock = threading.Lock()
        self.cycles = 0
        self.jobs_processed = 0
        self.chats_handled = 0
        self.tasks_handled = 0
        self.errors = 0
        self.error_streak = 0
        self.last_cycle_ms = 0.0
        self.started_at = time.time()
        self.last_error_ts = 0.0
        self.last_success_ts = 0.0

    def record_cycle(self, ms: float, *, ok: bool = True, kind: str = "heartbeat"):
        with self._lock:
            self.cycles += 1
            self.last_cycle_ms = ms
            if kind == "job":
                self.jobs_processed += 1
            elif kind == "chat":
                self.chats_handled += 1
            elif kind == "task":
                self.tasks_handled += 1
            if ok:
                self.error_streak = 0
                self.last_success_ts = time.time()
            else:
                self.errors += 1
                self.error_streak += 1
                self.last_error_ts = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            uptime = max(1.0, now - self.started_at)
            total_work = self.jobs_processed + self.chats_handled + self.tasks_handled
            return {
                "cycles": self.cycles,
                "jobs_processed": self.jobs_processed,
                "chats_handled": self.chats_handled,
                "tasks_handled": self.tasks_handled,
                "errors": self.errors,
                "error_streak": self.error_streak,
                "last_cycle_ms": round(self.last_cycle_ms, 1),
                "uptime_s": round(uptime, 1),
                "throughput_per_min": round(total_work / (uptime / 60.0), 2),
                "healthy": self.error_streak < int(os.getenv("STREAM_ERROR_STREAK_LIMIT", "5")),
                "last_error_ago_s": round(now - self.last_error_ts, 1),
                "last_success_ago_s": round(now - self.last_success_ts, 1),
            }
