"""Deterministic intelligence evaluation for earning opportunities."""

from __future__ import annotations

from typing import Any, Callable, Optional

from agents.earning.opportunity_adapters import legacy_to_canonical
from agents.earning.opportunity_intelligence import (
    OpportunityIntelligenceEngine,
    SemanticEstimate,
)


def evaluate_intelligence(
    opportunity: Any,
    *,
    memory: Any,
    engine: Optional[OpportunityIntelligenceEngine] = None,
    log_fn: Callable[[str], None],
) -> Any:
    """Attach and return the policy-backed intelligence result.

    Model-facing fields are semantic estimates only. The intelligence engine
    remains the authority for the deterministic verdict.
    """
    try:
        canonical = legacy_to_canonical(opportunity)
        # ARCH-ENG-124: the LLM's `effort` axis is a SCORE (0..1 after the
        # v2.1.95 normalization in evaluation.py), not a duration. It used to be
        # passed straight into `effort_hours`, so a 0.1 score became "0.1 hours"
        # and the engine divided expected value by it: measured end-to-end on a
        # $2,500 GitHub bounty, effort_score=0.1 produced
        # `expected_hourly_value = $1,403.09/h` and verdict "attractive". That
        # number reached `got.OpportunityGraph._utility` (0.1 * hourly in the
        # ranking) and the operator. A score is not hours — hours are passed
        # ONLY when the opportunity actually states them, else None (unknown),
        # which the engine already handles (effort 0 -> hourly 0.0, not a ratio).
        #
        # The same score still feeds `difficulty`, which IS score-shaped, so the
        # difficulty signal is preserved. Note the explicit None checks: the old
        # `or 0.5` turned an honest LLM 0 (trivial task) into 0.5.
        effort_score = getattr(opportunity, "effort_score", None)
        stated_hours = (getattr(opportunity, "time_required_hours", None)
                        or getattr(canonical, "estimated_effort", None) or None)
        skill_fit = getattr(opportunity, "skill_match", None)
        estimates = SemanticEstimate(
            skill_fit=None if skill_fit is None else float(skill_fit),
            effort_hours=None if not stated_hours else float(stated_hours),
            difficulty=None if effort_score is None else float(effort_score),
            competition=0.5,
            scam_risk=float(getattr(opportunity, "scam_prob", None) or 0.0),
        )
        evaluator = engine or OpportunityIntelligenceEngine()
        result = evaluator.evaluate(
            canonical,
            memory=memory,
            estimates=estimates,
        )
        opportunity.intelligence = result
        return result
    except Exception as exc:
        log_fn(
            f"[Intelligence] error for "
            f"{getattr(opportunity, 'id', '?')}: {exc}"
        )
        return None


__all__ = ["evaluate_intelligence"]
