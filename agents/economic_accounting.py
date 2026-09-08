"""agents/economic_accounting.py — Unified Economic Accounting Layer (v2.0.36j).

Distinguishes:
  ADVERTISED_VALUE  — what the opportunity lists (never revenue)
  EXPECTED_VALUE    — probability-adjusted forecast (never revenue)
  REALIZED_GROSS    — sum of VERIFIED payment evidence
  REALIZED_EXPENSE  — sum of VERIFIED expense evidence
  REALIZED_NET      — realized_gross - realized_expense
  VERIFIED_REVENUE  — VERIFIED payment evidence
  UNVERIFIED_REVENUE — UNVERIFIED/PARTIALLY_VERIFIED payment evidence

Rules (non-negotiable):
  - Advertised payment is NOT revenue.
  - A successful submission is NOT revenue.
  - A generated deliverable is NOT revenue.
  - Revenue becomes realized ONLY when appropriate payment evidence exists.
  - Only VERIFIED evidence counts toward realized/verified revenue.

Integrates with the Evidence subsystem (agents/evidence.py).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from agents.evidence import (
    Evidence, EvidenceStatus, VerificationLevel, VerificationResult,
)


# ── Expense categories ──────────────────────────────────────────────────────────

class ExpenseCategory(str, Enum):
    PLATFORM_FEE = "platform_fee"
    TRANSACTION_FEE = "transaction_fee"
    GAS = "gas"
    LLM_COST = "llm_cost"
    API_COST = "api_cost"
    TOOL_COST = "tool_cost"
    OTHER = "other"


# ── Economic profile ────────────────────────────────────────────────────────────

@dataclass
class EconomicProfile:
    """Complete economic picture for one opportunity."""
    opportunity_id: str = ""
    currency: str = "usd"

    # Revenue hierarchy
    advertised_value: float = 0.0
    expected_value: float = 0.0
    realized_gross: float = 0.0
    verified_revenue: float = 0.0
    unverified_revenue: float = 0.0
    pending_revenue: float = 0.0

    # Expenses by category
    expenses: Dict[str, float] = field(default_factory=lambda: {
        cat.value: 0.0 for cat in ExpenseCategory
    })
    realized_expense: float = 0.0

    # Profitability
    realized_net: float = 0.0
    roi: float = 0.0               # net / expense (0 if no expense)
    net_hourly_rate: float = 0.0   # net / effort_hours
    effort_hours: float = 0.0

    # Prediction accuracy (expected vs actual)
    expected_revenue: float = 0.0
    actual_revenue: float = 0.0
    revenue_error: float = 0.0          # actual - expected
    revenue_error_pct: float = 0.0      # error / max(expected, epsilon)
    expected_effort: float = 0.0
    actual_effort: float = 0.0
    effort_error: float = 0.0
    expected_probability: float = 0.0
    actual_outcome: bool = False

    # Metadata
    payment_count: int = 0
    expense_count: int = 0
    has_verified_payment: bool = False
    computed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "opportunity_id": self.opportunity_id,
            "currency": self.currency,
            "advertised_value": self.advertised_value,
            "expected_value": self.expected_value,
            "realized_gross": self.realized_gross,
            "verified_revenue": self.verified_revenue,
            "unverified_revenue": self.unverified_revenue,
            "pending_revenue": self.pending_revenue,
            "expenses": self.expenses,
            "realized_expense": self.realized_expense,
            "realized_net": self.realized_net,
            "roi": self.roi,
            "net_hourly_rate": self.net_hourly_rate,
            "effort_hours": self.effort_hours,
            "expected_revenue": self.expected_revenue,
            "actual_revenue": self.actual_revenue,
            "revenue_error": self.revenue_error,
            "revenue_error_pct": self.revenue_error_pct,
            "expected_effort": self.expected_effort,
            "actual_effort": self.actual_effort,
            "effort_error": self.effort_error,
            "expected_probability": self.expected_probability,
            "actual_outcome": self.actual_outcome,
            "payment_count": self.payment_count,
            "expense_count": self.expense_count,
            "has_verified_payment": self.has_verified_payment,
            "computed_at": self.computed_at,
        }


# ── Currency conversion ─────────────────────────────────────────────────────────

# Simple USD conversion rates (extensible; could be fed from an API).
# Crypto amounts are stored in their native unit; usd_equivalent computed.
_DEFAULT_RATES: Dict[str, float] = {
    "usd": 1.0,
    "usdc": 1.0,
    "usdt": 1.0,
    "eth": 3500.0,
    "btc": 65000.0,
    "sol": 150.0,
    "matic": 0.7,
    "bnb": 600.0,
    "arb": 1.2,
    "op": 2.5,
    "base": 1.0,  # base ETH = ETH
}


def to_usd(amount: float, currency: str, rates: Optional[Dict[str, float]] = None) -> float:
    """Convert an amount in `currency` to USD equivalent."""
    r = rates or _DEFAULT_RATES
    return float(amount) * r.get((currency or "usd").lower(), 1.0)


# ── Payment evidence types ──────────────────────────────────────────────────────

# Evidence types that represent incoming payment (revenue).
PAYMENT_EVIDENCE_TYPES = {
    "transaction_receipt",
    "platform_payment",
    "payment",
    "payout",
    "airdrop_payout",
    "refund",
}

# Evidence types that represent outgoing costs (expenses).
EXPENSE_EVIDENCE_TYPES = {
    "platform_fee",
    "transaction_fee",
    "gas_fee",
    "llm_cost",
    "api_cost",
    "tool_cost",
    "other_expense",
    "cost",
}

# Map evidence type → expense category
EVIDENCE_TYPE_TO_EXPENSE: Dict[str, str] = {
    "platform_fee": ExpenseCategory.PLATFORM_FEE.value,
    "transaction_fee": ExpenseCategory.TRANSACTION_FEE.value,
    "gas_fee": ExpenseCategory.GAS.value,
    "llm_cost": ExpenseCategory.LLM_COST.value,
    "api_cost": ExpenseCategory.API_COST.value,
    "tool_cost": ExpenseCategory.TOOL_COST.value,
    "other_expense": ExpenseCategory.OTHER.value,
    "cost": ExpenseCategory.OTHER.value,
}


# ── Economic accounting engine ──────────────────────────────────────────────────

class EconomicAccounting:
    """Pure compute layer over EvidenceStore. No DB writes."""

    def __init__(self, evidence_store: Any, rates: Optional[Dict[str, float]] = None):
        self.evidence_store = evidence_store
        self.rates = rates or _DEFAULT_RATES

    # ── Profile builder ───────────────────────────────────────────────────────

    def get_profile(self, opportunity_id: str, opportunity: Any = None,
                    intel_verdict: Any = None, effort_hours: float = 0.0,
                    actual_effort: float = 0.0) -> EconomicProfile:
        """Build a complete EconomicProfile for an opportunity."""
        profile = EconomicProfile(opportunity_id=opportunity_id)
        profile.effort_hours = effort_hours
        profile.actual_effort = actual_effort

        # Advertised + expected from opportunity / intel
        if opportunity is not None:
            profile.advertised_value = float(getattr(opportunity, "advertised_amount", 0.0) or 0.0)
            profile.currency = getattr(opportunity, "currency", "usd") or "usd"
            profile.expected_effort = float(getattr(opportunity, "estimated_effort", 0.0) or 0.0)
        if intel_verdict is not None:
            profile.expected_value = float(getattr(intel_verdict, "expected_value", 0.0) or 0.0)
            profile.expected_revenue = float(getattr(intel_verdict, "expected_net_revenue", 0.0) or 0.0)
            profile.expected_probability = float(getattr(intel_verdict, "confidence", 0.0) or 0.0)

        # Query all evidence for this opportunity
        all_evidence = self.evidence_store.for_subject("opportunity", opportunity_id)

        # Classify evidence
        payment_evidences = [e for e in all_evidence if e.evidence_type in PAYMENT_EVIDENCE_TYPES]
        expense_evidences = [e for e in all_evidence if e.evidence_type in EXPENSE_EVIDENCE_TYPES]

        # Revenue: only from payment evidence, by status
        # Strict: only fully VERIFIED counts as verified revenue
        verified_payments = [e for e in payment_evidences if e.status == EvidenceStatus.VERIFIED]
        unverified_payments = [e for e in payment_evidences if e.status != EvidenceStatus.VERIFIED and e.status != EvidenceStatus.REJECTED]
        rejected_payments = [e for e in payment_evidences if e.status == EvidenceStatus.REJECTED]

        profile.verified_revenue = sum(
            to_usd(e.amount, e.currency, self.rates) for e in verified_payments
        )
        profile.unverified_revenue = sum(
            to_usd(e.amount, e.currency, self.rates) for e in unverified_payments
        )
        profile.pending_revenue = sum(
            to_usd(e.amount, e.currency, self.rates) for e in unverified_payments
            if e.status.value == "unverified"
        )
        profile.realized_gross = profile.verified_revenue
        profile.payment_count = len(payment_evidences)
        profile.has_verified_payment = len(verified_payments) > 0

        # Expenses: by category from VERIFIED expense evidence
        verified_expenses = [e for e in expense_evidences if e.status == EvidenceStatus.VERIFIED]
        for e in verified_expenses:
            cat = EVIDENCE_TYPE_TO_EXPENSE.get(e.evidence_type, ExpenseCategory.OTHER.value)
            amount_usd = to_usd(e.amount, e.currency, self.rates)
            profile.expenses[cat] += amount_usd
        profile.realized_expense = sum(profile.expenses.values())
        profile.expense_count = len(verified_expenses)

        # Also capture fees/gas from payment evidence itself (if stored there)
        for e in verified_payments:
            if e.fees:
                profile.expenses[ExpenseCategory.PLATFORM_FEE.value] += to_usd(e.fees, e.currency, self.rates)
            if e.gas:
                profile.expenses[ExpenseCategory.GAS.value] += to_usd(e.gas, e.currency, self.rates)
            if e.other_expenses:
                profile.expenses[ExpenseCategory.OTHER.value] += to_usd(e.other_expenses, e.currency, self.rates)
        profile.realized_expense = sum(profile.expenses.values())

        # Net profit
        profile.realized_net = profile.realized_gross - profile.realized_expense

        # ROI
        if profile.realized_expense > 0:
            profile.roi = profile.realized_net / profile.realized_expense
        else:
            profile.roi = 0.0

        # Net hourly rate
        if effort_hours > 0:
            profile.net_hourly_rate = profile.realized_net / effort_hours

        # Prediction accuracy
        profile.actual_revenue = profile.verified_revenue
        profile.revenue_error = profile.actual_revenue - profile.expected_revenue
        if profile.expected_revenue > 0:
            profile.revenue_error_pct = profile.revenue_error / profile.expected_revenue
        elif profile.actual_revenue > 0:
            profile.revenue_error_pct = 1.0  # found revenue where none expected
        else:
            profile.revenue_error_pct = 0.0

        profile.effort_error = actual_effort - profile.expected_effort
        profile.actual_outcome = profile.has_verified_payment

        return profile

    # ── Aggregate metrics ──────────────────────────────────────────────────────

    def aggregate(self, profiles: List[EconomicProfile]) -> Dict[str, Any]:
        """Aggregate metrics across multiple opportunities (for portfolio-level reporting)."""
        if not profiles:
            return {
                "total_advertised": 0.0, "total_expected": 0.0,
                "total_verified_revenue": 0.0, "total_unverified_revenue": 0.0,
                "total_expenses": 0.0, "total_net_profit": 0.0,
                "roi": 0.0, "net_hourly_rate": 0.0,
                "avg_revenue_error": 0.0, "avg_effort_error": 0.0,
                "opportunity_count": 0, "verified_count": 0,
            }

        total_advertised = sum(p.advertised_value for p in profiles)
        total_expected = sum(p.expected_value for p in profiles)
        total_verified = sum(p.verified_revenue for p in profiles)
        total_unverified = sum(p.unverified_revenue for p in profiles)
        total_expenses = sum(p.realized_expense for p in profiles)
        total_net = sum(p.realized_net for p in profiles)
        total_effort = sum(p.effort_hours for p in profiles)
        verified_count = sum(1 for p in profiles if p.has_verified_payment)

        # Aggregate expenses by category
        by_cat: Dict[str, float] = {}
        for p in profiles:
            for cat, amt in p.expenses.items():
                by_cat[cat] = by_cat.get(cat, 0.0) + amt

        avg_rev_err = sum(p.revenue_error for p in profiles) / len(profiles)
        avg_eff_err = sum(p.effort_error for p in profiles) / len(profiles)

        roi = (total_net / total_expenses) if total_expenses > 0 else 0.0
        hourly = (total_net / total_effort) if total_effort > 0 else 0.0

        return {
            "total_advertised": total_advertised,
            "total_expected": total_expected,
            "total_verified_revenue": total_verified,
            "total_unverified_revenue": total_unverified,
            "total_expenses": total_expenses,
            "total_net_profit": total_net,
            "total_effort_hours": total_effort,
            "roi": roi,
            "net_hourly_rate": hourly,
            "avg_revenue_error": avg_rev_err,
            "avg_effort_error": avg_eff_err,
            "opportunity_count": len(profiles),
            "verified_count": verified_count,
            "expenses_by_category": by_cat,
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    def get_verified_revenue(self, opportunity_id: str) -> float:
        """Quick accessor: verified revenue for one opportunity."""
        evs = self.evidence_store.for_subject("opportunity", opportunity_id)
        return sum(
            to_usd(e.amount, e.currency, self.rates)
            for e in evs
            if e.evidence_type in PAYMENT_EVIDENCE_TYPES and e.status.is_affirmative
        )

    def get_total_expenses(self, opportunity_id: str) -> float:
        """Quick accessor: total verified expenses for one opportunity."""
        evs = self.evidence_store.for_subject("opportunity", opportunity_id)
        total = 0.0
        for e in evs:
            if e.evidence_type in EXPENSE_EVIDENCE_TYPES and e.status.is_affirmative:
                total += to_usd(e.amount, e.currency, self.rates)
        return total


__all__ = [
    "ExpenseCategory",
    "EconomicProfile",
    "EconomicAccounting",
    "to_usd",
    "PAYMENT_EVIDENCE_TYPES",
    "EXPENSE_EVIDENCE_TYPES",
    "EVIDENCE_TYPE_TO_EXPENSE",
]
