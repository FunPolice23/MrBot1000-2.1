"""agents/earning/economic_accounting.py — Unified Economic Accounting Layer (v2.0.36j).

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

Integrates with the Evidence subsystem (agents/evidence/evidence.py).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from agents.evidence.evidence import (
    Evidence, EvidenceStatus, VerificationLevel, VerificationResult,
)
from agents.earning.payment_evidence import PAYMENT_EVIDENCE_TYPES


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

    # ARCH-ENG-092: monetary evidence whose currency has no known USD rate, kept
    # in NATIVE units by currency so it is visible rather than silently dropped.
    # A 250,000 JPY payout converts to 0.0 USD (fail safe — it must never be
    # booked as revenue at a guessed rate) but the operator still needs to see
    # that it exists. {"JPY": 250000.0}.
    unconvertible_payment_amounts: Dict[str, float] = field(default_factory=dict)
    unconvertible_expense_amounts: Dict[str, float] = field(default_factory=dict)

    # ARCH-ENG-092 F5 (expense side): the two buckets above are only auditable if
    # something acts on them. `to_usd` fails safe by converting an unmapped
    # currency to 0.0, which is CORRECT for revenue (it can only reduce a
    # previously overstated number) but WRONG for an expense: `realized_expense`
    # then omits a cost that really exists, so `realized_net = gross - expense`
    # and `roi = net / expense` are both computed against a cost base that is too
    # small. Zeroing an unmapped EXPENSE therefore RAISES net and ROI — a hidden
    # cost is presented as free margin.
    #
    # This flag is the annotation: True whenever at least one VERIFIED expense
    # could not be valued, i.e. `realized_expense` is a LOWER BOUND on the real
    # cost and `realized_net`/`roi` are UPPER BOUNDS that must not be trusted for
    # ranking or reporting. It is exposed through `to_dict()` and honoured by
    # `aggregate()`, which refuses to report a net/ROI that silently ignores an
    # unvalued cost. The supported remedy stays what it always was: add a rate
    # for the currency (or re-book the evidence in a mapped currency) and the
    # flag clears itself.
    has_unconvertible_expense: bool = False

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
            "unconvertible_payment_amounts": dict(self.unconvertible_payment_amounts),
            "unconvertible_expense_amounts": dict(self.unconvertible_expense_amounts),
            # F5: surfaced next to the numbers it qualifies. A consumer that
            # reports `realized_net`/`roi` MUST surface this alongside them —
            # those figures are upper bounds whenever it is True.
            "has_unconvertible_expense": self.has_unconvertible_expense,
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


# ARCH-ENG-092: `to_usd` used `.get(currency, 1.0)`, so EVERY currency the rate
# table did not know was valued at exactly 1.0 USD. A 250,000 JPY payout was
# booked as $250,000 of verified revenue, a 250x overstatement, and so was an
# empty/None currency (the `Evidence.currency` default is `""`). An unknown
# currency is an UNKNOWN VALUE, not a USD-denominated one, and inventing a rate
# is the most expensive guess a financial report can make.
#
# FAIL SAFE, and the reason it fails safe this way: an unmapped currency
# converts to 0.0 USD, so the amount can never enter verified/unverified
# revenue, realized_gross or realized_net. It is 0.0 rather than None or an
# exception because EVERY caller feeds the result straight into `sum(...)` /
# `+=` — `EconomicAccounting.get_profile`, `get_verified_revenue`,
# `get_total_expenses` and `agents/core/state_reconciliation.py`. Returning
# None would raise TypeError inside those sums and raising would abort the
# accounting pass: both trade a wrong number for a crash, which is not an
# improvement. `is_convertible` is the escape hatch that keeps the money from
# being silently lost — `get_profile` records unmapped amounts on
# `unconvertible_payment_amounts` so an operator can see that 250,000 JPY
# exists and was NOT counted, instead of wondering where it went.
_UNCONVERTIBLE_USD = 0.0


def is_convertible(currency: str, rates: Optional[Dict[str, float]] = None) -> bool:
    """True iff `currency` has a known USD rate (ARCH-ENG-092).

    An empty/blank currency is NOT convertible: it is an unknown denomination,
    not a USD one.
    """
    r = rates or _DEFAULT_RATES
    key = str(currency or "").strip().lower()
    return bool(key) and key in r


def _record_unconvertible(bucket: Dict[str, float], currency: str, amount: float) -> None:
    """Accumulate a native, unvalued amount into `bucket` keyed by currency.

    ARCH-ENG-092: the single place that turns "this money exists but cannot be
    priced" into an auditable fact. Keys are the upper-cased currency code, or
    ``UNSPECIFIED`` when the evidence carries no currency at all.
    """
    key = str(currency or "").strip().upper() or "UNSPECIFIED"
    bucket[key] = bucket.get(key, 0.0) + float(amount or 0.0)


def to_usd(amount: float, currency: str, rates: Optional[Dict[str, float]] = None) -> float:
    """Convert an amount in `currency` to USD equivalent.

    ARCH-ENG-092: an unmapped/empty/unknown currency yields 0.0 USD (never face
    value). See the block comment above `_UNCONVERTIBLE_USD` for why this fails
    safe with 0.0 instead of None/raise, and use :func:`is_convertible` to
    distinguish "worth nothing" from "not convertible".
    """
    r = rates or _DEFAULT_RATES
    key = str(currency or "").strip().lower()
    rate = r.get(key)
    if rate is None:
        return _UNCONVERTIBLE_USD
    return float(amount) * float(rate)


# Evidence types that represent outgoing costs (expenses).
# ARCH-ENG-067: the `payment_*` names are what the money evidence producers actually
# emit — `make_money_evidence_set` (agents/evidence/evidence.py) and the autonomous
# loop's `_stage_account` both write `payment_fee` / `payment_gas` /
# `payment_llm_cost` / `payment_other_expense`. None of them was recognised here, so
# `realized_expense` was always 0.0 and `realized_net` always equalled
# `verified_revenue` — a $280 fee/gas/LLM bill on a $1000 payout was invisible.
EXPENSE_EVIDENCE_TYPES = {
    "platform_fee",
    "transaction_fee",
    "gas_fee",
    "llm_cost",
    "api_cost",
    "tool_cost",
    "other_expense",
    "cost",
    "payment_fee",
    "payment_gas",
    "payment_llm_cost",
    "payment_other_expense",
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
    "payment_fee": ExpenseCategory.PLATFORM_FEE.value,
    "payment_gas": ExpenseCategory.GAS.value,
    "payment_llm_cost": ExpenseCategory.LLM_COST.value,
    "payment_other_expense": ExpenseCategory.OTHER.value,
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
        verified_payments = [
            e for e in payment_evidences
            if e.status == EvidenceStatus.VERIFIED
            and e.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE
        ]
        unverified_payments = [e for e in payment_evidences if e.status != EvidenceStatus.VERIFIED and e.status != EvidenceStatus.REJECTED]
        rejected_payments = [e for e in payment_evidences if e.status == EvidenceStatus.REJECTED]

        profile.verified_revenue = sum(
            to_usd(e.amount, e.currency, self.rates) for e in verified_payments
        )
        profile.unverified_revenue = sum(
            to_usd(e.amount, e.currency, self.rates) for e in unverified_payments
        )
        # ARCH-ENG-092: record what could NOT be converted so fail-safe zeroing
        # is auditable rather than a silent disappearance of real money.
        for e in payment_evidences:
            if not is_convertible(e.currency, self.rates):
                _record_unconvertible(profile.unconvertible_payment_amounts, e.currency, e.amount)
        profile.pending_revenue = sum(
            to_usd(e.amount, e.currency, self.rates) for e in unverified_payments
            # ARCH-ENG-069: `EvidenceStatus.UNVERIFIED.value` is the UPPERCASE string
            # "UNVERIFIED", so the old lowercase comparison never matched and
            # `pending_revenue` was permanently 0.0 — manual/L1 money silently landed
            # in `unverified_revenue` instead of the "Pending verification" bucket the
            # design requires.
            if str(e.status.value).lower() == "unverified"
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
            if not is_convertible(e.currency, self.rates):
                _record_unconvertible(profile.unconvertible_expense_amounts, e.currency, e.amount)
        profile.realized_expense = sum(profile.expenses.values())
        profile.expense_count = len(verified_expenses)

        # Also capture fees/gas from payment evidence itself (if stored there)
        for e in verified_payments:
            if e.fees:
                profile.expenses[ExpenseCategory.PLATFORM_FEE.value] += to_usd(e.fees, e.currency, self.rates)
                if not is_convertible(e.currency, self.rates):
                    _record_unconvertible(profile.unconvertible_expense_amounts, e.currency, e.fees)
            if e.gas:
                profile.expenses[ExpenseCategory.GAS.value] += to_usd(e.gas, e.currency, self.rates)
                if not is_convertible(e.currency, self.rates):
                    _record_unconvertible(profile.unconvertible_expense_amounts, e.currency, e.gas)
            if e.other_expenses:
                profile.expenses[ExpenseCategory.OTHER.value] += to_usd(e.other_expenses, e.currency, self.rates)
                if not is_convertible(e.currency, self.rates):
                    _record_unconvertible(profile.unconvertible_expense_amounts, e.currency, e.other_expenses)
        profile.realized_expense = sum(profile.expenses.values())

        # ARCH-ENG-092 F5: an unvalued expense makes `realized_expense` a lower
        # bound, so `realized_net` and `roi` computed from it are upper bounds.
        # Annotate it so no consumer can present them as trustworthy.
        profile.has_unconvertible_expense = bool(profile.unconvertible_expense_amounts)

        # Net profit
        profile.realized_net = profile.realized_gross - profile.realized_expense

        # ROI
        # ARCH-ENG-092 F5: `realized_net / realized_expense` is a ratio whose
        # denominator is known to be too small when any expense is unvalued — the
        # true cost is >= the booked cost, so the true ROI is <= this number and
        # could be negative. Publishing it would rank an opportunity whose real
        # cost is hidden above one whose cost is fully known. 0.0 is the module's
        # existing "not computable" sentinel (it is what an expense-free profile
        # reports), so the number stays numeric for `sum()`/`+=` consumers while
        # no longer being read as a return.
        if profile.has_unconvertible_expense:
            profile.roi = 0.0
        elif profile.realized_expense > 0:
            profile.roi = profile.realized_net / profile.realized_expense
        else:
            profile.roi = 0.0

        # Net hourly rate
        if effort_hours > 0 and not profile.has_unconvertible_expense:
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
                "has_unconvertible_expense": False,
                "unconvertible_expense_amounts": {},
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

        # ARCH-ENG-092 F5: an unvalued expense is a cost that exists but cannot
        # be priced. Every `realized_net` that excluded it is an UPPER BOUND, so
        # the portfolio net/ROI built from them is an upper bound too — and the
        # failure mode of an upper bound on profit is that the bot ranks an
        # opportunity whose real cost is hidden above one whose cost is known.
        # Carry the annotation through so a consumer cannot present the totals
        # as a clean figure, and name the currencies involved.
        unconvertible_expenses: Dict[str, float] = {}
        for p in profiles:
            for cur, amt in (p.unconvertible_expense_amounts or {}).items():
                unconvertible_expenses[cur] = unconvertible_expenses.get(cur, 0.0) + amt
        has_unconvertible_expense = bool(unconvertible_expenses)

        avg_rev_err = sum(p.revenue_error for p in profiles) / len(profiles)
        avg_eff_err = sum(p.effort_error for p in profiles) / len(profiles)

        # F5: refuse to publish a ratio whose denominator is known to be too
        # small. When any expense is unvalued the true cost is >= the booked
        # cost, so the honest ROI is not computable; 0.0 keeps the number from
        # being read as a return while the raw sums stay visible for an operator.
        if has_unconvertible_expense:
            roi = 0.0
            hourly = 0.0
        else:
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
            # F5: the cost base for the above is incomplete; these say so.
            "has_unconvertible_expense": has_unconvertible_expense,
            "unconvertible_expense_amounts": unconvertible_expenses,
            "avg_revenue_error": avg_rev_err,
            "avg_effort_error": avg_eff_err,
            "opportunity_count": len(profiles),
            "verified_count": verified_count,
            "expenses_by_category": by_cat,
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    def get_verified_revenue(self, opportunity_id: str) -> float:
        """Quick accessor: verified revenue for one opportunity.

        Uses the SAME rule as :meth:`get_profile` (``status == VERIFIED`` **and**
        ``verification_level >= L3``). It used to accept any affirmative status at
        any level, so an L1 ``manual_attestation`` counted as verified revenue
        here while ``get_profile`` reported 0 for the same record — two
        authorities disagreeing about the same evidence. Nothing calls this
        today, so it was a trap rather than a live leak.
        """
        evs = self.evidence_store.for_subject("opportunity", opportunity_id)
        return sum(
            to_usd(e.amount, e.currency, self.rates)
            for e in evs
            if e.evidence_type in PAYMENT_EVIDENCE_TYPES
            and e.status == EvidenceStatus.VERIFIED
            and e.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE
        )

    def get_total_expenses(self, opportunity_id: str) -> float:
        """Quick accessor: total verified expenses for one opportunity.

        Matches ``get_profile``'s expense rule: VERIFIED status only.
        """
        evs = self.evidence_store.for_subject("opportunity", opportunity_id)
        total = 0.0
        for e in evs:
            if (e.evidence_type in EXPENSE_EVIDENCE_TYPES
                    and e.status == EvidenceStatus.VERIFIED):
                total += to_usd(e.amount, e.currency, self.rates)
        return total


__all__ = [
    "ExpenseCategory",
    "EconomicProfile",
    "EconomicAccounting",
    "to_usd",
    "is_convertible",
    "PAYMENT_EVIDENCE_TYPES",
    "EXPENSE_EVIDENCE_TYPES",
    "EVIDENCE_TYPE_TO_EXPENSE",
]
