"""Strategy feedback — close the autonomous-learning outcome loop (Phase C).

The autonomous loop records every run to `AutonomousRunStore` (success, paid,
payment_amount, decision), but nothing ever read those outcomes back — ranking
and discovery ran blind. This module aggregates recorded runs into per-platform
statistics so ranking can be informed by what has ACTUALLY paid, not just by
estimated value.

Design:
- **Read-only** over the run store; never mutates recorded outcomes.
- **Decoupled join**: the caller supplies a `platform_resolver(opportunity_id)
  -> platform` (in the app, `OpportunityPortfolio.get(id).platform`), so this
  module does not assume the two DBs are co-located and stays unit-testable.
- **Financial truth**: `total_paid`/`avg_payout` are summed ONLY over runs where
  `paid` is true and `payment_amount` is the recorded amount — never inferred,
  never estimated.
- **Cold-start safe**: `platform_stats` reports `runs`; callers apply a ranking
  adjustment only when `runs >= min_runs` (see `ranking_adjustment`). Thin data
  never distorts ranking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class PlatformStats:
    """Aggregated outcome statistics for one platform."""
    platform: str
    runs: int = 0
    successes: int = 0          # decision proceeded to a successful outcome
    paid_runs: int = 0          # runs that actually paid
    total_paid: float = 0.0     # sum of payment_amount over paid runs only
    decisions: Dict[str, int] = field(default_factory=dict)  # decision -> count

    @property
    def success_rate(self) -> float:
        return self.successes / self.runs if self.runs else 0.0

    @property
    def paid_rate(self) -> float:
        return self.paid_runs / self.runs if self.runs else 0.0

    @property
    def avg_payout(self) -> float:
        return self.total_paid / self.paid_runs if self.paid_runs else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "runs": self.runs,
            "successes": self.successes,
            "paid_runs": self.paid_runs,
            "success_rate": round(self.success_rate, 4),
            "paid_rate": round(self.paid_rate, 4),
            "total_paid": round(self.total_paid, 2),
            "avg_payout": round(self.avg_payout, 2),
            "decisions": dict(self.decisions),
        }


# Ranking adjustment knobs (advisory only — never auto-approves/submits).
_PAYING_BONUS = 1.15       # platform with a real paid history
_NEVER_PAID_PENALTY = 0.85  # platform with runs but zero payments
_MAX_ADJUST = 1.25          # clamp ceiling
_MIN_ADJUST = 0.75          # clamp floor


class StrategyFeedback:
    """Aggregate autonomous-run outcomes into per-platform statistics."""

    def __init__(self, run_store: Any,
                 platform_resolver: Optional[Callable[[str], str]] = None,
                 *, min_runs: int = 3):
        self._store = run_store
        self._resolve = platform_resolver or (lambda _opp_id: "")
        self.min_runs = max(1, int(min_runs))

    # ── aggregation ─────────────────────────────────────────────────────────
    def platform_stats(self, limit: int = 500) -> Dict[str, PlatformStats]:
        """Aggregate recent runs into {platform: PlatformStats}.

        Runs whose platform cannot be resolved are bucketed under "" and
        reported separately (never silently dropped, never inflating a real
        platform).
        """
        runs = self._recent_runs(limit)
        by_platform: Dict[str, PlatformStats] = {}
        for run in runs:
            opp_id = run.get("opportunity_id", "") or ""
            platform = (self._resolve(opp_id) or "").strip().lower()
            stats = by_platform.setdefault(platform, PlatformStats(platform=platform))
            stats.runs += 1
            if run.get("success"):
                stats.successes += 1
            if run.get("paid"):
                stats.paid_runs += 1
                # Financial truth: only real recorded payment amounts.
                try:
                    stats.total_paid += float(run.get("payment_amount") or 0.0)
                except (TypeError, ValueError):
                    pass
            decision = (run.get("decision") or "").strip()
            if decision:
                stats.decisions[decision] = stats.decisions.get(decision, 0) + 1
        return by_platform

    def _recent_runs(self, limit: int) -> List[Dict[str, Any]]:
        """Read recent runs from the store, tolerating either list_runs() or a
        raw connection. Never raises — an unreadable store yields no feedback."""
        try:
            lister = getattr(self._store, "list_runs", None)
            if callable(lister):
                rows = lister(limit=limit)
                return [r for r in (rows or []) if isinstance(r, dict)]
        except Exception:
            return []
        return []

    # ── ranking signal (advisory) ─────────────────────────────────────────────
    def ranking_adjustment(self, platform: str,
                           stats: Optional[Dict[str, PlatformStats]] = None) -> float:
        """Multiplier for a platform's rank, in [_MIN_ADJUST, _MAX_ADJUST].

        - Cold start (< min_runs for this platform) -> 1.0 (no adjustment).
        - Has paid history -> _PAYING_BONUS.
        - Has runs but never paid -> _NEVER_PAID_PENALTY.
        Advisory only: it reweights ranking, never approves or submits.
        """
        key = (platform or "").strip().lower()
        if not key:
            return 1.0
        stats = stats if stats is not None else self.platform_stats()
        st = stats.get(key)
        if st is None or st.runs < self.min_runs:
            return 1.0
        if st.paid_runs > 0:
            return _PAYING_BONUS
        return _NEVER_PAID_PENALTY

    def summary_lines(self, stats: Optional[Dict[str, PlatformStats]] = None
                      ) -> List[str]:
        """Human-readable per-platform summary for the Autonomous-Learning tab."""
        stats = stats if stats is not None else self.platform_stats()
        lines: List[str] = []
        for platform in sorted(k for k in stats if k):
            st = stats[platform]
            lines.append(
                f"{platform}: {st.runs} runs, {st.success_rate:.0%} success, "
                f"{st.paid_rate:.0%} paid, ${st.total_paid:.2f} total "
                f"(${st.avg_payout:.2f} avg over {st.paid_runs} paid)"
            )
        return lines
