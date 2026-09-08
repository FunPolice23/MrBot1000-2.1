"""Platform rate-limiting (v2.0.34q, Section C1).

ToS / anti-ban safety: every outbound call to a platform (search, submit,
scrape) must stay under that platform's acceptable request rate. We use the
existing thread-safe ``TokenBucket`` (library.py) as a per-platform throttle.

Design notes:
- One ``TokenBucket`` per platform, keyed by a stable platform name.
- Default (rate, capacity) tuned conservatively (polite, burst-limited). All
  values are env-overridable via ``RATE_<PLATFORM>`` (calls/second; a float).
- A module-level singleton ``get_throttle()`` is shared by discovery AND
  submit so they draw from the same bucket per platform.
- ``acquire`` only sleeps when over budget; idle calls are instantaneous, so
  there is no meaningful perf cost in the no-traffic case.
- This is a politeness limiter, NOT a secret. Failures (429, network) still
  surface normally; the throttle never swallows errors (see C3 for 429
  backoff).
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Optional

from library import TokenBucket


# Conservative per-platform defaults: (rate_calls_per_sec, burst_capacity).
# A ban kills the stream, so we err toward slow.
DEFAULT_LIMITS: Dict[str, tuple] = {
    "upwork":   (0.2, 1.0),    # ~1 call / 5s, burst 1
    "fiverr":   (0.2, 1.0),    # ~1 call / 5s, burst 1
    "microtask": (1.0, 3.0),   # 1 call/s, burst 3
    "web":      (2.0, 5.0),    # 2 calls/s, burst 5
    "airdrop":  (0.5, 2.0),    # 1 call / 2s, burst 2
    "defi":     (0.5, 2.0),
    "social":   (1.0, 3.0),
}

# Source name used inside the pipeline discover loop -> the platform bucket.
# The pipeline `discover` source keys map onto these buckets.
SOURCE_TO_PLATFORM = {
    "social": "social",
    "upwork": "upwork",
    "fiverr": "fiverr",
    "airdrop": "airdrop",
    "defi": "defi",
    "microtask": "microtask",
    "content": "web",
    "dynamic": "web",
}


def _env_rate(platform: str) -> Optional[float]:
    """Read RATE_<PLATFORM> (calls/sec) from env, validating it's a sane float."""
    raw = os.getenv(f"RATE_{platform.upper()}", "").strip()
    if not raw:
        return None
    try:
        val = float(raw)
    except ValueError:
        return None
    if val <= 0 or val > 1000:
        # Outside a sane range -> ignore (don't let a typo cause a ban or a hang).
        return None
    return val


class PlatformThrottle:
    """Holds one TokenBucket per platform and acquires tokens before calls."""

    def __init__(self) -> None:
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def _bucket(self, platform: str) -> TokenBucket:
        platform = (platform or "web").lower()
        with self._lock:
            b = self._buckets.get(platform)
            if b is None:
                rate = _env_rate(platform)
                if rate is not None:
                    # Env override: rate from env, capacity = max(burst 1, rate*5)
                    # so a high rate still allows a small burst.
                    b = TokenBucket(rate=rate, capacity=max(1.0, rate * 5.0))
                else:
                    rate_def, cap_def = DEFAULT_LIMITS.get(
                        platform, (1.0, 3.0))
                    b = TokenBucket(rate=rate_def, capacity=cap_def)
                self._buckets[platform] = b
            return b

    def acquire(self, platform: str, tokens: float = 1.0) -> None:
        """Block until one token is available for ``platform``.

        ``platform`` may be a discover-source name (e.g. "upwork", "content");
        it is mapped to the canonical bucket via SOURCE_TO_PLATFORM.
        """
        canonical = SOURCE_TO_PLATFORM.get((platform or "").lower(),
                                           (platform or "web").lower())
        self._bucket(canonical).acquire(tokens)

    def reset(self) -> None:
        """Drop all buckets (used in tests / config reload)."""
        with self._lock:
            self._buckets.clear()


# Module-level singleton, lazily created (matches other agent singletons).
_THROTTLE: Optional[PlatformThrottle] = None
_THROTTLE_LOCK = threading.Lock()


def get_throttle() -> PlatformThrottle:
    global _THROTTLE
    if _THROTTLE is None:
        with _THROTTLE_LOCK:
            if _THROTTLE is None:
                _THROTTLE = PlatformThrottle()
    return _THROTTLE
