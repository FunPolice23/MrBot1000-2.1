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
        estimates = SemanticEstimate(
            skill_fit=float(getattr(opportunity, "skill_match", None) or 0.5),
            effort_hours=float(getattr(opportunity, "effort_score", None) or 0.0),
            difficulty=float(getattr(opportunity, "effort_score", None) or 0.5),
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
