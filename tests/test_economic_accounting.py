"""tests/test_economic_accounting.py — Unified Economic Accounting Layer (v2.0.36j)."""

import os
import tempfile
import time
import unittest
from typing import List, Optional

from agents.evidence import (
    Evidence, EvidenceStatus, VerificationLevel, VerificationResult,
)
from agents.economic_accounting import (
    EconomicAccounting, EconomicProfile, ExpenseCategory, to_usd,
    PAYMENT_EVIDENCE_TYPES, EXPENSE_EVIDENCE_TYPES,
)


# ── Fake EvidenceStore (minimal interface needed by EconomicAccounting) ───────

class FakeEvidenceStore:
    """In-memory evidence store for testing."""
    def __init__(self, evidence_list: Optional[List[Evidence]] = None):
        self._evidence = list(evidence_list or [])

    def for_subject(self, subject_type: str, subject_id: str) -> List[Evidence]:
        return [e for e in self._evidence if e.subject_id == subject_id
                and e.subject_type == subject_type]

    def record(self, ev: Evidence) -> Evidence:
        self._evidence.append(ev)
        return ev

    def add(self, ev: Evidence) -> None:
        self._evidence.append(ev)


def _payment(subject_id: str, amount: float, currency: str = "usd",
             status: EvidenceStatus = EvidenceStatus.VERIFIED,
             evidence_type: str = "transaction_receipt",
             fees: float = 0.0, gas: float = 0.0) -> Evidence:
    """Create a payment evidence with given status."""
    ev = Evidence(
        source="test", evidence_type=evidence_type,
        subject_type="opportunity", subject_id=subject_id,
        amount=amount, currency=currency, fees=fees, gas=gas,
    )
    if status != EvidenceStatus.UNVERIFIED:
        vr = VerificationResult(status=status, method="test",
                                level=VerificationLevel.L3_EXTERNAL_SOURCE, actor="test")
        ev = ev.verify(vr)
    return ev


def _expense(subject_id: str, amount: float, evidence_type: str,
             currency: str = "usd",
             status: EvidenceStatus = EvidenceStatus.VERIFIED) -> Evidence:
    """Create an expense evidence."""
    ev = Evidence(
        source="test", evidence_type=evidence_type,
        subject_type="opportunity", subject_id=subject_id,
        amount=amount, currency=currency,
    )
    if status != EvidenceStatus.UNVERIFIED:
        vr = VerificationResult(status=status, method="test",
                                level=VerificationLevel.L3_EXTERNAL_SOURCE, actor="test")
        ev = ev.verify(vr)
    return ev


# ── Currency conversion ─────────────────────────────────────────────────────────

class TestCurrencyConversion(unittest.TestCase):
    def test_usd_identity(self):
        self.assertEqual(to_usd(100.0, "usd"), 100.0)

    def test_eth_conversion(self):
        self.assertEqual(to_usd(1.0, "eth"), 3500.0)

    def test_btc_conversion(self):
        self.assertEqual(to_usd(1.0, "btc"), 65000.0)

    def test_usdc_stable(self):
        self.assertEqual(to_usd(100.0, "usdc"), 100.0)

    def test_case_insensitive(self):
        self.assertEqual(to_usd(1.0, "ETH"), 3500.0)

    def test_custom_rates(self):
        rates = {"foo": 10.0}
        self.assertEqual(to_usd(5.0, "foo", rates), 50.0)


# ── USD opportunities ──────────────────────────────────────────────────────────

class TestUSD(unittest.TestCase):
    def test_simple_usd_payment(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 500.0, "usd"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 500.0)
        self.assertEqual(profile.realized_gross, 500.0)
        self.assertTrue(profile.has_verified_payment)

    def test_multiple_usd_payments(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 200.0, "usd"))
        store.add(_payment("opp-1", 300.0, "usd"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 500.0)
        self.assertEqual(profile.payment_count, 2)


# ── Crypto opportunities ───────────────────────────────────────────────────────

class TestCrypto(unittest.TestCase):
    def test_eth_payment(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 1.0, "eth"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 3500.0)  # converted to usd

    def test_btc_payment(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 0.5, "btc"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 32500.0)

    def test_mixed_usd_crypto(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 100.0, "usd"))
        store.add(_payment("opp-1", 1.0, "eth"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 3600.0)


# ── Platform fees ──────────────────────────────────────────────────────────────

class TestPlatformFees(unittest.TestCase):
    def test_platform_fee_deducted(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 1000.0, "usd"))
        store.add(_expense("opp-1", 100.0, "platform_fee"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 1000.0)
        self.assertEqual(profile.expenses[ExpenseCategory.PLATFORM_FEE.value], 100.0)
        self.assertEqual(profile.realized_expense, 100.0)
        self.assertEqual(profile.realized_net, 900.0)

    def test_fee_stored_on_payment_evidence(self):
        """Fees stored directly on payment evidence are counted."""
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 1000.0, "usd", fees=50.0))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.expenses[ExpenseCategory.PLATFORM_FEE.value], 50.0)
        self.assertEqual(profile.realized_net, 950.0)


# ── Gas fees ───────────────────────────────────────────────────────────────────

class TestGas(unittest.TestCase):
    def test_gas_expense(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 1.0, "eth"))
        store.add(_expense("opp-1", 0.01, "gas_fee", currency="eth"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.expenses[ExpenseCategory.GAS.value], 35.0)  # 0.01 * 3500

    def test_gas_on_payment(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 1.0, "eth", gas=0.005))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertAlmostEqual(profile.expenses[ExpenseCategory.GAS.value], 17.5, places=2)


# ── LLM costs ─────────────────────────────────────────────────────────────────

class TestLLMCosts(unittest.TestCase):
    def test_llm_cost(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 100.0, "usd"))
        store.add(_expense("opp-1", 5.0, "llm_cost"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.expenses[ExpenseCategory.LLM_COST.value], 5.0)
        self.assertEqual(profile.realized_net, 95.0)


# ── Zero revenue ───────────────────────────────────────────────────────────────

class TestZeroRevenue(unittest.TestCase):
    def test_no_evidence(self):
        store = FakeEvidenceStore()
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 0.0)
        self.assertEqual(profile.realized_net, 0.0)
        self.assertFalse(profile.has_verified_payment)
        self.assertEqual(profile.roi, 0.0)

    def test_advertised_not_revenue(self):
        """Advertised amount is tracked but NOT counted as revenue."""
        store = FakeEvidenceStore()
        acct = EconomicAccounting(store)

        class FakeOpp:
            advertised_amount = 1000.0
            currency = "usd"
            estimated_effort = 2.0

        profile = acct.get_profile("opp-1", FakeOpp())
        self.assertEqual(profile.advertised_value, 1000.0)
        self.assertEqual(profile.verified_revenue, 0.0)
        self.assertEqual(profile.realized_gross, 0.0)


# ── Partial payments ───────────────────────────────────────────────────────────

class TestPartialPayments(unittest.TestCase):
    def test_partial_then_full(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 200.0, "usd"))
        store.add(_payment("opp-1", 300.0, "usd"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 500.0)

    def test_unverified_partial(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 200.0, "usd", status=EvidenceStatus.UNVERIFIED))
        store.add(_payment("opp-1", 300.0, "usd", status=EvidenceStatus.VERIFIED))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 300.0)
        self.assertEqual(profile.unverified_revenue, 200.0)


# ── Failed payments ───────────────────────────────────────────────────────────

class TestFailedPayments(unittest.TestCase):
    def test_rejected_payment_not_revenue(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 500.0, "usd", status=EvidenceStatus.REJECTED))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 0.0)
        self.assertFalse(profile.has_verified_payment)


# ── Disputed payments ──────────────────────────────────────────────────────────

class TestDisputedPayments(unittest.TestCase):
    def test_disputed_not_verified(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 500.0, "usd", status=EvidenceStatus.CONFLICTED))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 0.0)
        self.assertGreater(profile.unverified_revenue, 0.0)


# ── Duplicate payments ─────────────────────────────────────────────────────────

class TestDuplicatePayments(unittest.TestCase):
    def test_duplicate_evidence_both_counted_by_amount(self):
        """Duplicate payment evidence (same tx) — amounts are summed (dedup is
        the EvidenceStore's job before recording). Here both are present."""
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 500.0, "usd"))
        store.add(_payment("opp-1", 500.0, "usd"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        # Both counted (dedup is upstream in EvidenceStore)
        self.assertEqual(profile.verified_revenue, 1000.0)
        self.assertEqual(profile.payment_count, 2)


# ── Verified vs unverified revenue ────────────────────────────────────────────

class TestVerifiedUnverified(unittest.TestCase):
    def test_separates_verified_unverified(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 100.0, "usd", status=EvidenceStatus.VERIFIED))
        store.add(_payment("opp-1", 50.0, "usd", status=EvidenceStatus.UNVERIFIED))
        store.add(_payment("opp-1", 25.0, "usd", status=EvidenceStatus.PARTIALLY_VERIFIED))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.verified_revenue, 100.0)
        self.assertEqual(profile.unverified_revenue, 75.0)


# ── Negative-profit opportunities ──────────────────────────────────────────────

class TestNegativeProfit(unittest.TestCase):
    def test_expenses_exceed_revenue(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 100.0, "usd"))
        store.add(_expense("opp-1", 200.0, "llm_cost"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.realized_net, -100.0)
        self.assertLess(profile.roi, 0.0)


# ── ROI and hourly rate ────────────────────────────────────────────────────────

class TestROIHourly(unittest.TestCase):
    def test_roi(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 200.0, "usd"))
        store.add(_expense("opp-1", 100.0, "platform_fee"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1")
        self.assertEqual(profile.roi, 1.0)  # (200-100)/100

    def test_net_hourly_rate(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 500.0, "usd"))
        store.add(_expense("opp-1", 100.0, "llm_cost"))
        acct = EconomicAccounting(store)
        profile = acct.get_profile("opp-1", effort_hours=2.0)
        self.assertEqual(profile.net_hourly_rate, 200.0)  # 400 / 2


# ── Prediction accuracy ─────────────────────────────────────────────────────────

class TestPredictionAccuracy(unittest.TestCase):
    def test_revenue_error(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 500.0, "usd"))
        acct = EconomicAccounting(store)

        class FakeIntel:
            expected_value = 400.0
            expected_net_revenue = 400.0
            confidence = 0.8

        profile = acct.get_profile("opp-1", intel_verdict=FakeIntel())
        self.assertEqual(profile.expected_revenue, 400.0)
        self.assertEqual(profile.actual_revenue, 500.0)
        self.assertEqual(profile.revenue_error, 100.0)
        self.assertAlmostEqual(profile.revenue_error_pct, 0.25)

    def test_effort_error(self):
        store = FakeEvidenceStore()
        acct = EconomicAccounting(store)

        class FakeOpp:
            advertised_amount = 0.0
            currency = "usd"
            estimated_effort = 5.0

        profile = acct.get_profile("opp-1", FakeOpp(), actual_effort=3.0)
        self.assertEqual(profile.expected_effort, 5.0)
        self.assertEqual(profile.actual_effort, 3.0)
        self.assertEqual(profile.effort_error, -2.0)


# ── Aggregate metrics ──────────────────────────────────────────────────────────

class TestAggregate(unittest.TestCase):
    def test_aggregate_multiple(self):
        store = FakeEvidenceStore()
        store.add(_payment("opp-1", 100.0, "usd"))
        store.add(_payment("opp-2", 200.0, "usd"))
        # opp-3 has no payment evidence
        acct = EconomicAccounting(store)
        p1 = acct.get_profile("opp-1")
        p2 = acct.get_profile("opp-2")
        p3 = acct.get_profile("opp-3")
        agg = acct.aggregate([p1, p2, p3])
        self.assertEqual(agg["total_verified_revenue"], 300.0)
        self.assertEqual(agg["opportunity_count"], 3)
        self.assertEqual(agg["verified_count"], 2)

    def test_aggregate_empty(self):
        acct = EconomicAccounting(FakeEvidenceStore())
        agg = acct.aggregate([])
        self.assertEqual(agg["opportunity_count"], 0)


if __name__ == "__main__":
    unittest.main()
