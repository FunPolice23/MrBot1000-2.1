"""Source-specific earning task adapters."""

from __future__ import annotations

from typing import Any

from agents.core.feature_flags import feature_enabled


def execute_airdrop(
    opportunity: Any,
    *,
    result_type: type,
    evidence_store: Any = None,
    claimer_factory: Any = None,
) -> Any:
    """Plan an airdrop claim; real claiming remains human-gated."""
    if not feature_enabled("airdrop_claiming"):
        return result_type(
            success=False,
            opportunity=opportunity,
            action_taken="claim_blocked",
            message="Airdrop claiming is disabled by feature policy",
        )
    if claimer_factory is None:
        from agents.earning.airdrop_claimer import AirdropClaimer
        claimer_factory = AirdropClaimer
    from agents.earning.airdrop_scanner import AirdropOpportunity

    try:
        claimer = claimer_factory(evidence_store=evidence_store)
        target = AirdropOpportunity(
            id=opportunity.id,
            title=opportunity.title,
            description=opportunity.description,
            platform=opportunity.platform,
            token_symbol=opportunity.payment_currency,
            estimated_value_usd=opportunity.estimated_usd_value,
            risk_level=opportunity.risk_level or "low",
            url=opportunity.url,
            claim_url=opportunity.url,
        )
        try:
            plan = claimer.claim(target, confirm_cb=None)
        except TypeError as exc:
            if "confirm_cb" not in str(exc):
                raise
            plan = claimer.claim(target)
        if isinstance(plan, bool):
            if plan:
                opportunity.status = "claimed"
                opportunity.outcome = "claim result returned by adapter"
                return result_type(
                    success=True,
                    opportunity=opportunity,
                    action_taken="claim",
                    message="claimed",
                )
            opportunity.status = "claim_failed"
            return result_type(
                success=False,
                opportunity=opportunity,
                action_taken="claim",
                message="Airdrop adapter reported claim failure",
            )
        if hasattr(plan, "success"):
            success = bool(plan.success)
            opportunity.status = "claimed" if success else "claim_failed"
            return result_type(
                success=success,
                opportunity=opportunity,
                action_taken="claim",
                message=str(getattr(plan, "message", "claim result")),
            )
        opportunity.status = "claim_blocked"
        opportunity.outcome = "human approval required (B2 gate)"
        return result_type(
            success=False,
            opportunity=opportunity,
            action_taken="claim_blocked",
            message=(
                "Blocked: airdrop claim requires human approval "
                f"(risk={plan.risk_level}, "
                f"est=${plan.expected_value_usd:.2f}). "
                f"safe_to_claim={plan.safe_to_claim}"
            ),
        )
    except Exception as exc:
        return result_type(
            success=False,
            opportunity=opportunity,
            action_taken="claim_blocked",
            message=f"Claim blocked (error): {exc}",
        )


def execute_defi(opportunity: Any, *, result_type: type) -> Any:
    if not feature_enabled("defi_scanning"):
        return result_type(
            success=False,
            opportunity=opportunity,
            action_taken="none",
            message="DeFi operations are disabled by feature policy",
        )
    return result_type(
        success=False,
        opportunity=opportunity,
        action_taken="none",
        message="DeFi execution requires wallet setup - not implemented",
    )


def execute_microtask(opportunity: Any, *, result_type: type) -> Any:
    return result_type(
        success=False,
        opportunity=opportunity,
        action_taken="none",
        message="Microtask execution requires platform API keys",
    )


def execute_simple(opportunity: Any, *, result_type: type, memory: Any) -> Any:
    memory.record_outcome(
        opportunity.id,
        opportunity.status or "execute",
        "Action available",
        0.0,
        0.0,
        False,
        [opportunity.source],
    )
    return result_type(
        success=True,
        opportunity=opportunity,
        action_taken=opportunity.status or "execute",
        message=f"Action available: {opportunity.url}",
    )


__all__ = [
    "execute_airdrop",
    "execute_defi",
    "execute_microtask",
    "execute_simple",
]
