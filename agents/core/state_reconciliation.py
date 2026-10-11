"""Read-only reconciliation across opportunity state stores.

The reconciler reports disagreements; it never repairs, promotes, or deletes state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from agents.earning.economic_accounting import to_usd
from agents.evidence.evidence import EvidenceStatus, VerificationLevel
from agents.earning.payment_evidence import PAYMENT_EVIDENCE_TYPES


@dataclass(frozen=True)
class ReconciliationConflict:
    opportunity_id: str
    category: str
    severity: str
    message: str
    sources: Dict[str, Any] = field(default_factory=dict)
    requires_human_review: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "sources": self.sources,
            "requires_human_review": self.requires_human_review,
        }


@dataclass
class ReconciliationReport:
    generated_at: float
    conflicts: List[ReconciliationConflict] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "conflict_count": len(self.conflicts),
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
        }


def reconcile_opportunity(
    opportunity_id: str,
    *,
    lifecycle: Any = None,
    portfolio: Any = None,
    evidence_store: Any = None,
    accounting: Any = None,
    run_store: Any = None,
) -> ReconciliationReport:
    """Compare available stores for one opportunity without mutating them."""
    import time

    report = ReconciliationReport(generated_at=time.time())
    lifecycle_state = _lifecycle_state(lifecycle, opportunity_id)
    portfolio_entry = _portfolio_entry(portfolio, opportunity_id)
    evidence = _evidence(evidence_store, opportunity_id)
    profile = _accounting_profile(accounting, opportunity_id)
    runs = _runs(run_store, opportunity_id)

    lifecycle_paid = lifecycle_state.get("status") == "paid"
    portfolio_paid = _value(portfolio_entry, "work_status") == "PAID"
    verified_payments = [
        item for item in evidence
        if item.evidence_type in PAYMENT_EVIDENCE_TYPES
        and getattr(item, "status", None) == EvidenceStatus.VERIFIED
        and getattr(item, "verification_level", VerificationLevel.L1_SELF_REPORTED)
        >= VerificationLevel.L3_EXTERNAL_SOURCE
        and getattr(item, "amount", 0.0) > 0.0
    ]
    has_verified_payment = bool(verified_payments)

    if lifecycle_paid and not has_verified_payment:
        report.conflicts.append(ReconciliationConflict(
            opportunity_id, "lifecycle_evidence", "high",
            "Lifecycle is paid but no positive verified payment evidence exists.",
            {"lifecycle": lifecycle_state, "verified_payment_count": 0},
        ))
    if has_verified_payment and not lifecycle_paid:
        report.conflicts.append(ReconciliationConflict(
            opportunity_id, "evidence_lifecycle", "high",
            "Positive verified payment evidence exists but lifecycle is not paid.",
            {"lifecycle": lifecycle_state, "verified_payment_count": len(verified_payments)},
        ))
    if portfolio_paid != lifecycle_paid:
        report.conflicts.append(ReconciliationConflict(
            opportunity_id, "portfolio_lifecycle", "high",
            "Portfolio payment state disagrees with lifecycle payment state.",
            {"portfolio": portfolio_entry, "lifecycle": lifecycle_state},
        ))

    verified_revenue = _number(profile, "verified_revenue")
    evidence_revenue = sum(
        to_usd(
            float(getattr(item, "amount", 0.0) or 0.0),
            getattr(item, "currency", "usd") or "usd",
        )
        for item in verified_payments
    )
    if abs(verified_revenue - evidence_revenue) > 1e-9:
        report.conflicts.append(ReconciliationConflict(
            opportunity_id, "evidence_accounting", "medium",
            "Accounting verified revenue disagrees with verified payment evidence.",
            {"accounting_verified_revenue": verified_revenue,
             "evidence_verified_revenue": evidence_revenue},
        ))

    if lifecycle_paid and any(_value(run, "status") == "FAILED" for run in runs):
        report.conflicts.append(ReconciliationConflict(
            opportunity_id, "run_lifecycle", "high",
            "A durable run is failed while lifecycle is paid.",
            {"lifecycle": lifecycle_state, "runs": runs},
        ))
    return report


def reconcile_many(opportunity_ids: Iterable[str], **stores: Any) -> ReconciliationReport:
    """Aggregate read-only reconciliation results for multiple opportunities."""
    import time

    report = ReconciliationReport(generated_at=time.time())
    for opportunity_id in opportunity_ids:
        report.conflicts.extend(
            reconcile_opportunity(opportunity_id, **stores).conflicts
        )
    return report


def _lifecycle_state(store: Any, opportunity_id: str) -> Dict[str, Any]:
    if store is None or not hasattr(store, "get_state"):
        return {}
    value = store.get_state(opportunity_id)
    return value if isinstance(value, dict) else {}


def _portfolio_entry(store: Any, opportunity_id: str) -> Any:
    if store is None or not hasattr(store, "get"):
        return None
    entry = store.get(opportunity_id)
    return entry.to_dict() if hasattr(entry, "to_dict") else entry


def _evidence(store: Any, opportunity_id: str) -> List[Any]:
    if store is None or not hasattr(store, "for_subject"):
        return []
    return list(store.for_subject("opportunity", opportunity_id) or [])


def _accounting_profile(store: Any, opportunity_id: str) -> Any:
    if store is None or not hasattr(store, "get_profile"):
        return None
    return store.get_profile(opportunity_id)


def _runs(store: Any, opportunity_id: str) -> List[Any]:
    if store is None or not hasattr(store, "list_runs"):
        return []
    return [run for run in store.list_runs(limit=1000)
            if _value(run, "opportunity_id") == opportunity_id]


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        value = source.get(key, default)
    else:
        value = getattr(source, key, default)
    return getattr(value, "value", value)


def _number(source: Any, key: str) -> float:
    try:
        return float(_value(source, key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["ReconciliationConflict", "ReconciliationReport", "reconcile_opportunity", "reconcile_many"]