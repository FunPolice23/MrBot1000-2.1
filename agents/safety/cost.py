"""agents/cost_guard.py — Hard daily LLM spend cap (A4).

Problem closed by this module: nothing limited cloud LLM spend, so a cloud model
could burn arbitrary $/day and turn "earning" net-negative. `CostGuard` enforces a
daily $ ceiling and lets callers skip BILLABLE providers (falling back to the
free/local one) once the cap is hit.

Spend is ESTIMATED (chars/4 × pricing, see database.get_llm_cost_usd). The guard is a
safety ceiling, not an exact meter — it may trip slightly early/late vs real billing.
"""

import os
from typing import Optional


def is_local_provider(name: str) -> bool:
    """A provider is free/local (never skipped by the budget guard) iff it runs
    on the user's own hardware and bills nothing.

    Recognises, in addition to the legacy ``ollama``/``local*`` spellings:
      * the local dual-brain adapter names ``big-brain`` / ``small-brain``
        (any ``-brain`` adapter runs on-machine), and
      * the canonical on-machine set (``provider_keys.LOCAL_PROVIDERS``:
        llamacpp, ollama, lmstudio, vllm, koboldcpp).

    Misclassifying a local brain as billable inverts the guard's intent: when
    the daily cap is hit it would skip the FREE brain and fall back to a paid
    cloud provider — spending real money the budget exists to prevent.
    """
    n = (name or "").strip().lower()
    if not n:
        return False
    if "brain" in n:
        return True
    if n.startswith("local") or "ollama" in n:
        return True
    try:
        from agents.runtime.provider_keys import LOCAL_PROVIDERS
        # Spelling-robust: lm-studio / lmstudio / "lm studio" are the same
        # on-machine provider; normalise hyphens/spaces before the set check.
        squashed = n.replace("-", "").replace("_", "").replace(" ", "")
        if n in LOCAL_PROVIDERS or squashed in LOCAL_PROVIDERS:
            return True
    except Exception:
        pass
    return False


class CostGuard:
    """Daily LLM budget guard. budget_usd == 0 disables the guard (backward compat)."""

    def __init__(self, daily_budget_usd: float = 0.0):
        try:
            self.daily_budget_usd = float(daily_budget_usd or 0.0)
        except (TypeError, ValueError):
            self.daily_budget_usd = 0.0

    @classmethod
    def from_env(cls, env_key: str = "LLM_DAILY_BUDGET_USD") -> "CostGuard":
        return cls(float(os.getenv(env_key, "0") or 0.0))

    def daily_cost_usd(self, db) -> float:
        """Estimated spend in the last 24h, via database.get_llm_cost_usd(days=1)."""
        if db is None:
            return 0.0
        try:
            return float(db.get_llm_cost_usd(days=1) or 0.0)
        except Exception:
            return 0.0

    def is_exceeded(self, db) -> bool:
        """True iff a budget is set AND estimated daily spend >= budget."""
        if self.daily_budget_usd <= 0:
            return False
        return self.daily_cost_usd(db) >= self.daily_budget_usd

    def should_skip(self, db, provider_name: str) -> bool:
        """Skip a BILLABLE provider when the daily cap is exceeded.

        Local/free providers are NEVER skipped (they cost nothing). A budget of 0
        means the guard is disabled and nothing is skipped.
        """
        if self.daily_budget_usd <= 0:
            return False
        if is_local_provider(provider_name):
            return False
        return self.is_exceeded(db)

    def status(self, db) -> dict:
        spent = self.daily_cost_usd(db)
        budget = self.daily_budget_usd
        exceeded = bool(budget > 0 and spent >= budget)
        return {
            "budget_usd": budget,
            "spent_usd": round(spent, 4),
            "remaining_usd": (round(budget - spent, 4) if budget > 0 else None),
            "exceeded": exceeded,
            "disabled": budget <= 0,
        }
