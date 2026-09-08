"""Per-provider circuit breaker for LLM calls (v2.0.34y, Section D4).

Problem (D4 audit): `base_worker.llm` retries every provider up to 3 times in
the outer attempt loop. A dead/flaky cloud provider therefore burns 3 serial
attempts (each with its own timeout/latency) before the loop falls through to
the next provider — wasted time AND wasted spend on billable APIs.

Fix: a tiny per-provider circuit breaker, open after ``LLM_CB_FAILURES``
(default 3) consecutive failures, that SKIPS the provider for the rest of the
current call and for ``LLM_CB_COOLDOWN`` seconds (default 60) across calls.
A single success resets it (half-open -> closed). This is fail-fast failover,
not a permanent ban: the provider is re-tried once the cooldown lapses.

State is an in-process module-level singleton (one breaker per process). It is
intentionally NOT persisted: a restart starts clean, and a flaky-but-recovering
provider should be given a fresh chance. No network, no DB, no drift.
"""

from __future__ import annotations

import os
import time
from typing import Dict


def _enabled() -> bool:
    return os.getenv("LLM_CB_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def _failure_threshold() -> int:
    try:
        return max(1, int(os.getenv("LLM_CB_FAILURES", "3")))
    except ValueError:
        return 3


def _cooldown_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("LLM_CB_COOLDOWN", "60")))
    except ValueError:
        return 60.0


class _ProviderState:
    __slots__ = ("consecutive_failures", "open_until")

    def __init__(self):
        self.consecutive_failures = 0
        self.open_until = 0.0  # epoch seconds; 0 == closed


class ProviderCircuitBreaker:
    """Tracks consecutive failures per provider and opens the circuit past a threshold."""

    def __init__(self):
        self._states: Dict[str, _ProviderState] = {}

    def is_open(self, name: str) -> bool:
        """True if the provider should be skipped right now (circuit open)."""
        if not _enabled():
            return False
        st = self._states.get(name)
        if st is None:
            return False
        if st.open_until and time.time() < st.open_until:
            return True
        # Cooldown elapsed -> half-open: allow one trial, reset counts.
        if st.open_until and time.time() >= st.open_until:
            st.consecutive_failures = 0
            st.open_until = 0.0
        return False

    def record_failure(self, name: str) -> None:
        if not _enabled():
            return
        st = self._states.get(name)
        if st is None:
            st = _ProviderState()
            self._states[name] = st
        st.consecutive_failures += 1
        if st.consecutive_failures >= _failure_threshold():
            st.open_until = time.time() + _cooldown_seconds()

    def record_success(self, name: str) -> None:
        # Any success closes the circuit (and forgets prior failures).
        st = self._states.get(name)
        if st is not None:
            st.consecutive_failures = 0
            st.open_until = 0.0

    def reset(self, name: str) -> None:
        self._states.pop(name, None)

    def snapshot(self) -> Dict[str, dict]:
        """Debug/observability view of current breaker state."""
        out = {}
        now = time.time()
        for name, st in self._states.items():
            out[name] = {
                "consecutive_failures": st.consecutive_failures,
                "open": bool(st.open_until and now < st.open_until),
                "open_for_s": max(0.0, st.open_until - now) if st.open_until else 0.0,
            }
        return out


_breaker = ProviderCircuitBreaker()


def get_breaker() -> ProviderCircuitBreaker:
    """Shared, process-wide circuit breaker for `llm()`."""
    return _breaker
