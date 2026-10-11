"""Adapters between the legacy earning pipeline model and canonical opportunities.

The pipeline still exposes its historical ``Opportunity`` shape to callers, while
discovery and intelligence use ``agents.opportunity_models.Opportunity``.  Keeping
these translations here makes that compatibility boundary explicit and reusable.
"""

from __future__ import annotations

from typing import Any

from agents.earning.opportunity_models import Opportunity as CanonicalOpportunity


def canonical_to_legacy(canonical: Any, legacy_type: type) -> Any:
    """Convert a canonical opportunity to the pipeline's legacy shape."""
    return legacy_type(
        id=canonical.opportunity_id,
        source=canonical.source,
        type=canonical.category,
        title=canonical.title,
        description=canonical.description,
        platform=canonical.platform,
        payment_type=canonical.payment_type,
        payment_amount=canonical.advertised_amount,
        payment_currency=canonical.currency,
        estimated_usd_value=(
            canonical.estimated_net_value or canonical.advertised_amount
        ),
        min_amount=canonical.advertised_amount,
        risk_level=canonical.risk_level,
        url=canonical.external_url,
        status="new",
        found_at=canonical.discovered_at,
    )


def legacy_to_canonical(legacy: Any) -> CanonicalOpportunity:
    """Convert the pipeline's legacy opportunity to the canonical shape."""
    return CanonicalOpportunity(
        opportunity_id=legacy.id,
        source=legacy.source,
        platform=legacy.platform or legacy.source,
        title=legacy.title,
        description=legacy.description,
        category=legacy.type or "other",
        payment_type=(legacy.payment_type or "usd"),
        currency=(legacy.payment_currency or "USD"),
        advertised_amount=float(legacy.payment_amount or 0.0),
        estimated_net_value=float(
            legacy.estimated_usd_value or legacy.payment_amount or 0.0
        ),
        risk_level=legacy.risk_level or "low",
        external_url=legacy.url or "",
        source_reliability=0.5,
        scam_risk=float(getattr(legacy, "scam_prob", 0.0) or 0.0),
    )


__all__ = ["canonical_to_legacy", "legacy_to_canonical"]
