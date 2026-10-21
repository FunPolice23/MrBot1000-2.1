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
    # A *-cloud provider is remote/billable even when its name shares a token
    # with a local one (llama-cloud, localstack-cloud): the "cloud" marker wins
    # over any local substring, so it cannot escape the budget/rate cap.
    if "cloud" in n:
        return False
    if "brain" in n:
        return True
    if n.startswith("local") or "ollama" in n:
        return True
    try:
        from agents.runtime.provider_keys import LOCAL_PROVIDERS
        # Spelling-robust: lm-studio / lmstudio / "lm studio" are the same
        # on-machine provider; normalise hyphens/spaces before the set check.
        # ARCH-ENG-145: the DOT is squashed too. `llama.cpp` — the display name
        # `ProviderManager._detect_llamacpp` puts on ProviderInfo.name — squashed
        # to "llama.cpp" and missed the set's "llamacpp", so the project's own
        # primary local brain was classified CLOUD: it took the billable tier
        # (1.0/sec, 500 calls/day) and became $-skippable by CostGuard, the exact
        # inversion the class docstring warns about. Confirmed failing on clean
        # HEAD by tests/safety/test_provider_rate_limiter.py::test_local_providers.
        # Safe: no cloud vendor name squashes into a LOCAL_PROVIDERS entry (the
        # "cloud" marker above still wins first for llama-cloud/localstack-cloud).
        squashed = (n.replace("-", "").replace("_", "")
                     .replace(" ", "").replace(".", ""))
        if n in LOCAL_PROVIDERS or squashed in LOCAL_PROVIDERS:
            return True
    except Exception:
        pass
    return False


def estimate_call_cost(provider: str, model: str,
                       prompt_tokens: int = 0, completion_tokens: int = 0) -> float:
    """Real USD cost of one LLM call, or 0.0 for local/free providers.

    A roster (BrainSlot) can point a brain slot at a *cloud* provider, so a
    brain adapter's resolved provider is not always the local llama.cpp. The
    brain adapters must record the real cost of a cloud-backed call — not a
    hardcoded 0.0 — or that call never counts against the daily budget,
    CostGuard never trips, and the cloud brain is never skipped/`$`-capped:
    the exact net-negative-earning path the budget exists to prevent. Local
    brains stay 0.0 (free). Unknown/cloud model pricing also yields 0.0 (we
    never fabricate a cost), which the caller may treat as a fail-open.
    """
    if is_local_provider(provider):
        return 0.0
    try:
        from app.provider_models import _price_for
        inn, out = _price_for(model or "")
    except Exception:
        inn = out = None
    if inn is None and out is None:
        return 0.0
    return ((prompt_tokens or 0) / 1_000_000) * (inn or 0.0) + \
           ((completion_tokens or 0) / 1_000_000) * (out or 0.0)


def enforcement_skip_decision(provider: str, db) -> tuple[bool, str]:
    """Whether a call to `provider` should be SKIPPED for budget reasons, keyed
    on the provider NAME — never on whether a cost was recorded.

    Returns (skip, reason). Local/free providers are never skipped. A billable
    (cloud) provider is skipped when the daily $-budget is exceeded.

    Design note (the unpriced-model tension): an UNPRICED cloud model records
    0.0 cost (estimate_call_cost never fabricates), so the $-budget alone cannot
    catch it — it would bill real money invisibly. The $-budget therefore only
    caps PRICED models. The caller MUST also apply the per-provider call-count
    cap (provider_rate_limiter), which keys on the SAME name-based billable
    classification (is_local_provider), so unpriced cloud models are still
    capped by call-count. Priced -> capped by $; unpriced -> capped by
    call-count; local -> free. Wire BOTH at the brain-adapter entry, keyed on
    the resolved provider (_cfg.provider), or unpriced cloud models escape both.
    """
    if is_local_provider(provider):
        return False, ""
    try:
        guard = CostGuard.from_env()
        if guard.should_skip(db, provider):
            # ARCH-ENG-243 (BD-01): a trip is a typed safety event (the
            # Insights panel counts blocked `safety:warning` events as its
            # "Safety incidents" KPI). Guarded: the decision is emitted
            # AFTER it is made and telemetry must never alter it.
            try:
                from agents.core.event_logger import StructuredEventLogger
                StructuredEventLogger.instance().safety_event(
                    gate_type="cost_guard", blocked=True,
                    description=(f"daily budget exceeded for billable "
                                 f"provider '{provider}'"))
            except Exception:
                pass
            return True, f"daily budget exceeded for billable provider '{provider}'"
    except Exception:
        pass
    return False, ""


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
