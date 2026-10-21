"""Provider-independent process and model performance telemetry."""

from __future__ import annotations

import os
import threading
import time
import tracemalloc
from typing import Any


_PROCESS_START = time.perf_counter()

# ARCH-ENG-221: ALLOCATION TRACING IS NOW OPT-IN.
#
# This used to call `tracemalloc.start()` at MODULE IMPORT, unconditionally and
# forever. `agents/runtime/__init__.py` re-exports from this module, so merely
# importing anything under `agents.runtime` -- including `device_registry`, which
# `_hardware_line()` touches on every chat turn -- switched allocation tracing on
# for the entire process lifetime.
#
# The cost is not small and it is not local. tracemalloc records every
# `PyObject` allocation and free in its own hash table, which typically slows an
# allocation-bound workload by 2-4x and grows that table without bound. This
# application streams tokens, rebuilds prompts and f-strings, and churns tens of
# thousands of `QTableWidgetItem` objects per minute across six or more threads
# on a 6-core CPU. It was paying that tax continuously to serve ONE diagnostic --
# `snapshot()`'s current/peak memory figures.
# The diagnostic is still available: set MRBOT_TRACE_MEMORY=1. It is a debugging
# aid, not something to leave running in normal operation.
_TRACE_MEMORY = os.environ.get("MRBOT_TRACE_MEMORY", "").strip().lower() in (
    "1", "true", "yes", "on")
if _TRACE_MEMORY:
    tracemalloc.start(1)


class PerformanceTelemetry:
    """Thread-safe counters and timings for runtime diagnostics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._startup_ms: float | None = None
        self._model_calls = 0
        self._model_errors = 0
        self._retries = 0
        self._model_latency_ms = 0.0
        self._first_token_latency_ms = 0.0
        self._first_token_samples = 0
        self._prompt_chars = 0
        self._prompt_tokens = 0
        self._gui_updates = 0

    def mark_startup_complete(self) -> float:
        duration_ms = (time.perf_counter() - _PROCESS_START) * 1000
        with self._lock:
            self._startup_ms = duration_ms
        return duration_ms

    def record_prompt(self, chars: int, tokens: int = 0) -> None:
        with self._lock:
            self._prompt_chars += max(0, int(chars))
            self._prompt_tokens += max(0, int(tokens))

    def record_model_call(
        self,
        latency_ms: float,
        *,
        first_token_latency_ms: float | None = None,
        ok: bool = True,
    ) -> None:
        with self._lock:
            self._model_calls += 1
            self._model_latency_ms += max(0.0, float(latency_ms))
            if not ok:
                self._model_errors += 1
            if first_token_latency_ms is not None:
                self._first_token_latency_ms += max(0.0, float(first_token_latency_ms))
                self._first_token_samples += 1

    def record_retry(self, count: int = 1) -> None:
        with self._lock:
            self._retries += max(0, int(count))

    def record_gui_update(self, count: int = 1) -> None:
        with self._lock:
            self._gui_updates += max(0, int(count))

    def snapshot(self) -> dict[str, Any]:
        # ARCH-ENG-221: report whether these are real. `get_traced_memory()`
        # returns (0, 0) when tracing was never started, which would otherwise
        # read as "this process is using no memory" -- a false claim in a
        # diagnostic panel, which is the exact failure mode this codebase
        # keeps producing.
        if _TRACE_MEMORY:
            current, peak = tracemalloc.get_traced_memory()
            mem_traced = True
        else:
            current = peak = 0
            mem_traced = False
        wall_ms = max(1.0, (time.perf_counter() - _PROCESS_START) * 1000)
        cpu_ms = time.process_time() * 1000
        with self._lock:
            calls = self._model_calls
            first_samples = self._first_token_samples
            return {
                "startup_ms": round(self._startup_ms, 1) if self._startup_ms is not None else None,
                "model_calls": calls,
                "model_errors": self._model_errors,
                "retries": self._retries,
                # ARCH-ENG-221: explicitly False when tracing is off, so the
                # panel cannot present a 0-byte reading as a real measurement.
                "memory_traced": mem_traced,
                "model_error_rate": round(self._model_errors / calls, 4) if calls else 0.0,
                "avg_model_latency_ms": round(self._model_latency_ms / calls, 1) if calls else 0.0,
                "avg_first_token_latency_ms": (
                    round(self._first_token_latency_ms / first_samples, 1)
                    if first_samples else 0.0
                ),
                "prompt_chars": self._prompt_chars,
                "prompt_tokens": self._prompt_tokens,
                "gui_updates": self._gui_updates,
                "process_cpu_ms": round(cpu_ms, 1),
                "process_cpu_ratio": round(cpu_ms / wall_ms, 4),
                "python_memory_current_bytes": current,
                "python_memory_peak_bytes": peak,
            }


telemetry = PerformanceTelemetry()

__all__ = ["PerformanceTelemetry", "telemetry"]
