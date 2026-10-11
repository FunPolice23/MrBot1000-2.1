"""Execution dispatch for earning opportunities."""

from __future__ import annotations

from typing import Any, Callable


def execute_opportunity(
    opportunity: Any,
    *,
    result_type: type,
    airdrop_fn: Callable[[Any], Any],
    defi_fn: Callable[[Any], Any],
    microtask_fn: Callable[[Any], Any],
    simple_fn: Callable[[Any], Any],
) -> Any:
    """Route an opportunity to its guarded execution adapter."""
    if opportunity.source == "airdrop":
        return airdrop_fn(opportunity)
    if opportunity.source == "defi":
        return defi_fn(opportunity)
    if opportunity.source == "microtask":
        return microtask_fn(opportunity)
    if opportunity.source in ["referral", "faucet"]:
        return simple_fn(opportunity)
    if opportunity.source == "content":
        return result_type(
            success=False,
            opportunity=opportunity,
            action_taken="none",
            message=(
                "Content execution requires platform integration "
                "— not implemented"
            ),
        )
    return result_type(
        success=False,
        opportunity=opportunity,
        action_taken="none",
        message=f"No executor for {opportunity.source}",
    )


__all__ = ["execute_opportunity"]
