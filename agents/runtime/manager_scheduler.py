"""Qt-independent manager cadence and heartbeat scheduling policies."""

from __future__ import annotations

import os


def adaptive_sleep(error_streak: int, pending_work: bool) -> float:
    """Return a bounded poll delay based on work and recent failures."""
    limit = int(os.getenv("STREAM_ERROR_STREAK_LIMIT", "5"))
    fast = float(os.getenv("STREAM_FAST_POLL", "0.3"))
    idle = float(os.getenv("STREAM_IDLE_POLL", "1.0"))
    cap = float(os.getenv("STREAM_MAX_BACKOFF", "10.0"))
    if error_streak >= limit:
        return min(
            cap,
            fast * (2 ** min(error_streak - limit, 5)),
        )
    return fast if pending_work else idle


def heartbeat_due(
    *,
    now: float,
    last_heartbeat: float,
    idle_cooldown: float,
) -> bool:
    """Return whether the next autonomous heartbeat should run."""
    return (now - last_heartbeat) >= idle_cooldown


__all__ = ["adaptive_sleep", "heartbeat_due"]
