"""Portfolio projection for evaluated earning opportunities."""

from __future__ import annotations

from typing import Any, Callable


def sync_to_portfolio(
    opportunity: Any,
    *,
    portfolio: Any,
    log_fn: Callable[[str], None],
) -> None:
    """Create or update the portfolio projection for one opportunity."""
    if portfolio is None:
        return
    try:
        from agents.earning.opportunity_portfolio import (
            PortfolioEntry,
            WorkStatus,
            resolve_next_action,
        )

        verdict = getattr(opportunity, "intelligence", None)
        opportunity_id = (
            getattr(opportunity, "opportunity_id", None)
            or getattr(opportunity, "id", None)
        )
        if not opportunity_id:
            return
        action, reason = resolve_next_action(
            PortfolioEntry(opportunity_id=opportunity_id)
        )
        reference = (
            opportunity.to_dict()
            if hasattr(opportunity, "to_dict")
            else {
                "id": opportunity_id,
                "title": getattr(opportunity, "title", ""),
                "platform": getattr(opportunity, "platform", ""),
            }
        )
        entry = PortfolioEntry(
            opportunity_id=opportunity_id,
            opportunity_ref=reference,
            work_status=WorkStatus.EVALUATING,
            expected_value=(
                getattr(verdict, "expected_value", 0.0) if verdict else 0.0
            ),
            expected_hourly_value=(
                getattr(verdict, "expected_hourly_value", 0.0)
                if verdict else 0.0
            ),
            deadline=getattr(opportunity, "deadline", 0.0) or 0.0,
            confidence=(
                getattr(verdict, "confidence", 0.25) if verdict else 0.25
            ),
            risk=(
                getattr(verdict, "risk_penalty", 0.0) if verdict else 0.0
            ),
            effort=getattr(opportunity, "estimated_effort", 0.0) or 0.0,
            platform=getattr(opportunity, "platform", "") or "",
            category=(
                getattr(opportunity, "category", "")
                or getattr(opportunity, "type", "")
                or ""
            ),
            task_type=getattr(opportunity, "task_type", "") or "",
            skill_fit=getattr(verdict, "skill_fit", 0.0) if verdict else 0.0,
            next_action=action,
            waiting_reason=reason,
        )
        existing = portfolio.get(entry.opportunity_id)
        if existing is None:
            portfolio.add(entry)
        else:
            entry.work_status = existing.work_status
            entry.lifecycle_stage = existing.lifecycle_stage
            entry.added_at = existing.added_at
            portfolio.update(entry)
    except Exception as exc:
        log_fn(f"[PortfolioSync] {exc}")


__all__ = ["sync_to_portfolio"]
