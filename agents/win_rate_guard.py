"""agents/win_rate_guard.py — Auto-decline platforms below a win-rate threshold (A5).

Closes the feedback loop: once the bot has enough outcome history for a platform, it
stops wasting proposals (and LLM $) on platforms that consistently lose. Guards
cold-start: a platform with fewer than `min_samples` attempts is never declined
(insufficient data).

Pure + testable (no worker/network needed). Mirrors agents.cost_guard.py's shape.
"""

import os
from typing import Optional


class WinRateGuard:
    """Decline a platform when its win-rate is below `decline_below` AND it has at
    least `min_samples` attempts. decline_below is a fraction (0..1)."""

    def __init__(self, decline_below: float = 0.2, min_samples: int = 5):
        try:
            self.decline_below = float(decline_below if decline_below is not None else 0.2)
        except (TypeError, ValueError):
            self.decline_below = 0.2
        try:
            self.min_samples = int(min_samples if min_samples is not None else 5)
        except (TypeError, ValueError):
            self.min_samples = 5

    @classmethod
    def from_env(cls, env_key: str = "WINRATE_DECLINE_BELOW") -> "WinRateGuard":
        """Read `decline_below` from an env value expressed as a PERCENT (e.g. "20")."""
        raw = os.getenv(env_key, "")
        try:
            pct = float(raw)
        except (TypeError, ValueError):
            pct = 20.0
        return cls(decline_below=pct / 100.0)

    @staticmethod
    def _rate_and_total(reputation: dict) -> tuple:
        """Return (success_rate, total) from a reputation dict, tolerating shapes."""
        if not isinstance(reputation, dict):
            return 0.0, 0
        # EarningMemory.get_platform_reputation exposes success_rate + total.
        rate = reputation.get("success_rate")
        total = reputation.get("total")
        if rate is None or total is None:
            # Fallback: compute from raw counts.
            s = int(reputation.get("success", 0) or 0)
            f = int(reputation.get("failed", 0) or 0)
            total = int(total or (s + f))
            rate = (s / total) if total else 0.0
        try:
            return float(rate), int(total)
        except (TypeError, ValueError):
            return 0.0, 0

    def should_decline(self, reputation: dict) -> bool:
        """True iff the platform has enough samples AND its win-rate is below threshold."""
        rate, total = self._rate_and_total(reputation)
        if total < self.min_samples:
            return False  # cold-start: not enough data to judge
        return rate < self.decline_below

    def status(self, reputation: dict) -> dict:
        rate, total = self._rate_and_total(reputation)
        return {
            "success_rate": round(rate, 4),
            "total": total,
            "decline_below": self.decline_below,
            "min_samples": self.min_samples,
            "should_decline": self.should_decline(reputation),
            "insufficient_data": total < self.min_samples,
        }
