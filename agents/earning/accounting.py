"""Accounting projections for earning reports."""

from __future__ import annotations

from typing import Any


def accounting_projection(
    *,
    portfolio: Any,
    accounting: Any,
    lifecycle: Any,
) -> dict:
    """Build verified/unverified revenue and expense fields for a report."""
    profiles = []
    for entry in portfolio.load_all():
        try:
            profiles.append(accounting.get_profile(entry.opportunity_id))
        except Exception:
            continue
    aggregate = accounting.aggregate(profiles)
    unverified = lifecycle.unverified_payouts()
    return {
        "verified_revenue_usd": aggregate["total_verified_revenue"],
        "unverified_revenue_usd": aggregate["total_unverified_revenue"],
        "total_expenses_usd": aggregate["total_expenses"],
        "net_profit_usd": aggregate["total_net_profit"],
        "roi": aggregate["roi"],
        "net_hourly_rate": aggregate["net_hourly_rate"],
        "expenses_by_category": aggregate.get("expenses_by_category", {}),
        "unverified_payouts_count": len(unverified),
        "unverified_payout_ids": unverified,
    }


__all__ = ["accounting_projection"]
