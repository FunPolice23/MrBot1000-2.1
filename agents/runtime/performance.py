"""Provider-independent process and model performance telemetry."""

from __future__ import annotations

import threading
import time
import tracemalloc
from typing import Any


_PROCESS_START = time.perf_counter()
tracemalloc.start()


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
        current, peak = tracemalloc.get_traced_memory()
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
