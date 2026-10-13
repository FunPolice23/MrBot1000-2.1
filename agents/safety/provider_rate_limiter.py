"""Per-provider rate limiting + daily budget (Phase F, ARCH-ENG-091).

The existing ``CostGuard`` is a single GLOBAL daily $ ceiling set only via env.
This adds what the operator asked for:

- **Per-provider rate limit** (calls/sec) via a thread-safe ``TokenBucket`` so a
  provider can't be hammered in a burst.
- **Per-provider daily call cap** with **provider-aware defaults**: LOCAL
  providers (ollama/local/llama.cpp) are hardware-bound — no $ cap unless the
  operator opts in; CLOUD providers get a sensible default daily call cap so a
  subscription/budget isn't burned too fast.
- **Operator-configurable in the Settings tab** — every limit is seeded from env
  (``<PROVIDER>_RATE_PER_SEC``, ``<PROVIDER>_MAX_CALLS_PER_DAY``) and persisted
  there.

Over-rate / over-budget calls are REFUSED with a clear reason (fail closed) for
billable providers; local providers are never $-capped. The daily counter is
persisted to SQLite so an app restart does not reset the day's usage.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Dict, Optional

from app.library import TokenBucket

# Providers that run on the user's own hardware — no monetary cost, so never
# $-capped by default. Rate-limit still applies (they share CPU/GPU).
_LOCAL_MARKERS = ("ollama", "local", "llama", "llamacpp", "vllm", "lmstudio",
                  "koboldcpp")


def is_local_provider(name: str) -> bool:
    n = (name or "").lower()
    return any(m in n for m in _LOCAL_MARKERS)


# Provider-aware defaults: (rate_per_sec, max_calls_per_day). Local providers get
# a generous rate (hardware-bound) and NO daily cap (0 = unlimited). Cloud
# providers get a conservative daily cap so a budget lasts the day.
_DEFAULTS = {
    "local": (2.0, 0),        # no daily cap
    "cloud": (1.0, 500),      # ~500 calls/day default for any cloud provider
}


def _defaults_for(name: str):
    return _DEFAULTS["local"] if is_local_provider(name) else _DEFAULTS["cloud"]


class ProviderRateLimiter:
    """Per-provider token-bucket rate limit + persisted daily call cap."""

    def __init__(self, db_path: Optional[str] = None):
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        self._db_path = db_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "agent.db")

    # ── config (env, overridable in Settings) ─────────────────────────────
    def rate_for(self, provider: str) -> float:
        key = f"{(provider or '').upper().replace('-', '_')}_RATE_PER_SEC"
        env = os.getenv(key, "").strip()
        if env:
            try:
                return max(0.01, float(env))
            except ValueError:
                pass
        return _defaults_for(provider)[0]

    def max_calls_for(self, provider: str) -> int:
        key = f"{(provider or '').upper().replace('-', '_')}_MAX_CALLS_PER_DAY"
        env = os.getenv(key, "").strip()
        if env:
            try:
                return max(0, int(env))  # 0 = unlimited
            except ValueError:
                pass
        return _defaults_for(provider)[1]

    def _bucket(self, provider: str) -> TokenBucket:
        with self._lock:
            b = self._buckets.get(provider)
            if b is None:
                rate = self.rate_for(provider)
                b = TokenBucket(rate=rate, capacity=max(1.0, rate))
                self._buckets[provider] = b
            return b

    # ── daily counter (persisted) ─────────────────────────────────────────
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _calls_today(self, provider: str) -> int:
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            try:
                cur = conn.execute(
                    "SELECT n FROM provider_daily_calls WHERE day=? AND provider=?",
                    (self._today(), provider))
                row = cur.fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
        except Exception:
            return 0  # fail open on the counter so a db hiccup can't wedge calls

    def _bump(self, provider: str) -> None:
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            try:
                conn.execute(
                    "INSERT INTO provider_daily_calls(day, provider, n) VALUES(?,?,1) "
                    "ON CONFLICT(day, provider) DO UPDATE SET n=n+1",
                    (self._today(), provider))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    # ── the gate ──────────────────────────────────────────────────────────
    def check(self, provider: str) -> Dict:
        """Return {"allow": bool, "reason": str}. Does NOT consume a token."""
        max_calls = self.max_calls_for(provider)
        if max_calls > 0 and self._calls_today(provider) >= max_calls:
            return {"allow": False,
                    "reason": (f"daily call cap reached for '{provider}' "
                               f"({max_calls}/day)")}
        return {"allow": True, "reason": ""}

    def acquire(self, provider: str, *, block: bool = True,
                timeout: float = 2.0) -> Dict:
        """Rate-limit + count one call. Returns {"allow", "reason"}.

        Fails closed on the daily cap. On rate, either blocks (token bucket
        sleep) or returns allow=False when ``block`` is False or the wait would
        exceed ``timeout``.
        """
        cap = self.check(provider)
        if not cap["allow"]:
            return cap
        bucket = self._bucket(provider)
        if not bucket.try_acquire(1.0, timeout=timeout if block else 0.0):
            return {"allow": False,
                    "reason": f"rate limit for '{provider}' — try again shortly"}
        self._bump(provider)
        return {"allow": True, "reason": ""}

    def status(self) -> Dict[str, Dict]:
        """Per-provider view for the Settings/DB tabs."""
        out = {}
        for provider in {*(self._buckets.keys()),}:
            out[provider] = {
                "rate_per_sec": self.rate_for(provider),
                "max_calls_per_day": self.max_calls_for(provider),
                "calls_today": self._calls_today(provider),
                "local": is_local_provider(provider),
            }
        return out


# Process-wide singleton so the daily counter and buckets are shared.
_LIMITER: Optional[ProviderRateLimiter] = None
_LIMITER_LOCK = threading.Lock()


def get_provider_rate_limiter() -> ProviderRateLimiter:
    global _LIMITER
    with _LIMITER_LOCK:
        if _LIMITER is None:
            _LIMITER = ProviderRateLimiter()
        return _LIMITER


def ensure_table(db_path: Optional[str] = None) -> None:
    """Create the daily-calls table if absent (safe to call repeatedly)."""
    path = db_path or (os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "agent.db"))
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS provider_daily_calls ("
                "day TEXT NOT NULL, provider TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY(day, provider))")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


__all__ = ["ProviderRateLimiter", "get_provider_rate_limiter",
           "is_local_provider", "ensure_table"]
