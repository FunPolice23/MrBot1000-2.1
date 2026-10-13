"""ARCH-ENG-092 F5 — the expense side of the unmapped-currency fail safe.

092b fixed `to_usd` so an unmapped/empty currency converts to 0.0 USD instead of
a guessed 1.0 face-value rate. On the REVENUE side that is strictly correct: it
can only reduce a previously overstated number (250,000 JPY used to book as
$250,000 of verified revenue). On the EXPENSE side it is backwards — an expense
that converts to 0.0 is a cost that silently disappears, and

    realized_net = realized_gross - realized_expense
    roi          = realized_net   / realized_expense

both treat a smaller `realized_expense` as *better*. So zeroing an unconvertible
expense RAISES net and ROI: a hidden cost is presented as free margin, and any
consumer that ranks or reports on those numbers is steered toward opportunities
whose true cost it cannot see.

Reproduced against the real implementation before the fix, for a store holding
[payment_confirmation 1000.0 usd, platform_fee 400.0 usd, platform_fee 50000.0
"XXX"]:

    verified_revenue 1000.0
    realized_expense  400.0     <- the 50000 XXX fee converts to 0.0
    realized_net      600.0     <- presented as profit; a real 50000-unit cost
    roi                 1.5     <- was unvalued and is excluded
    unconvertible_expense_amounts {"XXX": 50000.0}  <- recorded, nothing read it

These tests pin the repaired invariant in both directions: an unconvertible
PAYMENT still never enters verified_revenue, and a profile carrying an
unconvertible EXPENSE is no longer presented as fully profitable.

Nothing here asserts a specific invented rate. The fix refuses to compute a
ratio whose denominator is known to be too small, rather than guessing what the
missing cost was worth. The `.get(currency, 1.0)` bug this descends from stays
regression-tested in tests/engineering/test_cycle_092_accounting.py, which is
untouched.
"""

from __future__ import annotations

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.evidence.evidence import (
    Evidence,
    EvidenceStatus,
    VerificationLevel,
)
from agents.earning.economic_accounting import (
    EconomicAccounting,
    EconomicProfile,
    is_convertible,
    to_usd,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

class _EvidenceStoreStub:
    """Minimal EvidenceStore surface the accounting layer uses."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def record(self, ev):
        self.items.append(ev)
        return ev

    def get(self, evidence_id):
        for ev in self.items:
            if getattr(ev, "id", None) == evidence_id:
                return ev
        return None

    def for_subject(self, subject_type, subject_id):
        return [e for e in self.items
                if e.subject_type == subject_type and e.subject_id == subject_id]


def _evidence(subject_id, amount, evidence_type, currency="usd",
              method="authenticated_api",
              level=VerificationLevel.L3_EXTERNAL_SOURCE,
              status=EvidenceStatus.VERIFIED, fees=0.0, gas=0.0):
    return Evidence.create(
        source="system", evidence_type=evidence_type,
        subject_type="opportunity", subject_id=subject_id,
        external_id=f"ext-{subject_id}-{evidence_type}",
        amount=amount, currency=currency, verification_method=method,
        verification_level=level, status=status,
        fees=fees, gas=gas,
        provenance={"producer": "payment_provider"})


def _profile(items, **kwargs):
    return EconomicAccounting(_EvidenceStoreStub(items)).get_profile(
        "opp-f5", **kwargs)


# ── The reproduced defect ────────────────────────────────────────────────────

class TestUnconvertibleExpenseIsNotPresentedAsFreeMargin(unittest.TestCase):
    """A cost that cannot be valued must not be reported as zero cost."""

    def test_reproduced_case_is_flagged_as_having_an_unvalued_cost(self):
        """The exact reproduction: [1000 usd payment, 400 usd fee, 50000 XXX fee]."""
        p = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 400.0, "platform_fee", currency="usd"),
            _evidence("opp-f5", 50000.0, "platform_fee", currency="XXX"),
        ])
        # The unconvertible fee is still excluded from the USD expense total —
        # 092b's fail-safe direction is preserved, no invented rate.
        self.assertAlmostEqual(p.verified_revenue, 1000.0, places=2)
        self.assertAlmostEqual(p.realized_expense, 400.0, places=2)
        self.assertEqual(p.unconvertible_expense_amounts.get("XXX"), 50000.0)
        # ...but the profile now says so, instead of presenting 600.0 net and
        # 1.5 ROI as if the 50000-unit cost were free.
        self.assertTrue(
            p.has_unconvertible_expense,
            "a profile with an unvalued expense must be annotated as such — "
            "otherwise realized_net/roi are read as trustworthy")

    def test_roi_is_not_published_for_a_profile_with_an_unvalued_cost(self):
        """ROI is a ratio whose denominator is known to be too small."""
        p = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 400.0, "platform_fee", currency="usd"),
            _evidence("opp-f5", 50000.0, "platform_fee", currency="XXX"),
        ])
        self.assertEqual(
            p.roi, 0.0,
            "the true cost is >= the booked 400.0, so the true ROI is <= 1.5 "
            "and may be negative; publishing 1.5 ranks a hidden cost as profit")

    def test_net_hourly_rate_is_not_published_for_a_profile_with_an_unvalued_cost(self):
        p = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 400.0, "platform_fee", currency="usd"),
            _evidence("opp-f5", 50000.0, "platform_fee", currency="XXX"),
        ], effort_hours=2.0)
        self.assertEqual(
            p.net_hourly_rate, 0.0,
            "an upper bound on net divided by effort is not an hourly rate")

    def test_expense_only_unconvertible_cost_is_flagged(self):
        """No revenue at all, and the whole cost is unvalued: still a cost."""
        p = _profile([
            _evidence("opp-f5", 50000.0, "platform_fee", currency="XXX"),
        ])
        self.assertAlmostEqual(p.realized_expense, 0.0, places=2)
        self.assertTrue(p.has_unconvertible_expense)
        self.assertEqual(p.roi, 0.0)

    def test_blank_currency_expense_is_flagged_as_unspecified(self):
        """`Evidence.currency` defaults to `""` — an unknown denomination."""
        p = _profile([
            _evidence("opp-f5", 300.0, "platform_fee", currency=""),
        ])
        self.assertTrue(p.has_unconvertible_expense)
        self.assertEqual(p.unconvertible_expense_amounts.get("UNSPECIFIED"), 300.0)

    def test_unvalued_fee_stored_on_payment_evidence_is_flagged(self):
        """Fees/gas carried on payment evidence take the same expense path."""
        p = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 0.0, "payment_confirmation", currency="XXX",
                      fees=250.0, gas=40.0),
        ])
        self.assertTrue(p.has_unconvertible_expense)
        self.assertEqual(p.unconvertible_expense_amounts.get("XXX"), 290.0)


# ── The other direction: unconvertible REVENUE must still be excluded ────────

class TestUnconvertiblePaymentStillExcludedFromRevenue(unittest.TestCase):
    """092b's fail-safe direction is NOT weakened by the F5 fix."""

    def test_unmapped_payment_is_not_verified_revenue(self):
        p = _profile([
            _evidence("opp-f5", 250000.0, "payment_confirmation", currency="JPY"),
        ])
        self.assertAlmostEqual(
            p.verified_revenue, 0.0, places=2,
            msg="an unconvertible currency must not enter verified revenue")
        self.assertAlmostEqual(p.realized_gross, 0.0, places=2)
        self.assertAlmostEqual(p.realized_net, 0.0, places=2)
        self.assertEqual(p.unconvertible_payment_amounts.get("JPY"), 250000.0)
        # No expense was unvalued, so the expense-side flag stays clear.
        self.assertFalse(p.has_unconvertible_expense)

    def test_blank_currency_payment_is_not_verified_revenue(self):
        p = _profile([
            _evidence("opp-f5", 480.0, "payment_confirmation", currency="",
                      method="blockchain_balance_delta",
                      level=VerificationLevel.L5_CRYPTOGRAPHIC),
        ])
        self.assertAlmostEqual(p.verified_revenue, 0.0, places=2)
        self.assertAlmostEqual(p.realized_net, 0.0, places=2)
        self.assertFalse(p.has_unconvertible_expense)

    def test_to_usd_still_returns_zero_for_an_unmapped_currency(self):
        """The fix must not change `to_usd`'s return value (0.0, not None)."""
        for cur in ("JPY", "GBP", "EUR", "XXX", "", "   ", None):
            with self.subTest(currency=repr(cur)):
                self.assertEqual(
                    to_usd(1000.0, cur), 0.0,
                    f"{cur!r} has no known USD rate; it must NOT be face-value $1000")
        # ...and it stays numeric, because every caller feeds it into sum()/+=.
        self.assertEqual(
            sum(to_usd(a, c) for a, c in ((1.0, "usd"), (2.0, "JPY"))), 1.0)

    def test_helper_accessors_still_fail_safe(self):
        acct = EconomicAccounting(_EvidenceStoreStub([
            _evidence("opp-f5", 250000.0, "payment_confirmation", currency="JPY"),
        ]))
        self.assertAlmostEqual(acct.get_verified_revenue("opp-f5"), 0.0, places=2)
        acct2 = EconomicAccounting(_EvidenceStoreStub([
            _evidence("opp-f5", 50000.0, "payment_fee", currency="GBP"),
        ]))
        self.assertAlmostEqual(
            acct2.get_total_expenses("opp-f5"), 0.0, places=2,
            msg="the quick accessor keeps 092b's fail-safe; the annotation "
                "lives on the profile, which is the reporting authority")


# ── Mapped currencies are unaffected ─────────────────────────────────────────

class TestMappedCurrenciesAreUnaffected(unittest.TestCase):
    """No over-correction: fully convertible profiles compute exactly as before."""

    def test_usd_fee_still_produces_net_and_roi(self):
        p = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 400.0, "platform_fee", currency="usd"),
        ], effort_hours=2.0)
        self.assertAlmostEqual(p.verified_revenue, 1000.0, places=2)
        self.assertAlmostEqual(p.realized_expense, 400.0, places=2)
        self.assertAlmostEqual(p.realized_net, 600.0, places=2)
        self.assertAlmostEqual(p.roi, 1.5, places=6)
        self.assertAlmostEqual(p.net_hourly_rate, 300.0, places=6)
        self.assertFalse(p.has_unconvertible_expense)
        self.assertEqual(p.unconvertible_expense_amounts, {})

    def test_mapped_crypto_fee_still_produces_net_and_roi(self):
        p = _profile([
            _evidence("opp-f5", 1.0, "payment_confirmation", currency="eth"),
            _evidence("opp-f5", 0.01, "gas_fee", currency="eth"),
        ])
        self.assertAlmostEqual(p.verified_revenue, 3500.0, places=2)
        self.assertAlmostEqual(p.realized_expense, 35.0, places=2)
        self.assertAlmostEqual(p.realized_net, 3465.0, places=2)
        self.assertFalse(p.has_unconvertible_expense)

    def test_custom_rates_clear_the_flag(self):
        """The supported remedy: add a rate and the annotation clears itself."""
        rates = dict({"usd": 1.0})
        rates["jpy"] = 0.0067
        self.assertTrue(is_convertible("JPY", rates))
        p = EconomicAccounting(_EvidenceStoreStub([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 30000.0, "platform_fee", currency="JPY"),
        ]), rates=rates).get_profile("opp-f5")
        self.assertAlmostEqual(p.realized_expense, 201.0, places=2)
        self.assertFalse(p.has_unconvertible_expense)
        self.assertAlmostEqual(p.roi, 3.97, places=1)
        self.assertEqual(p.unconvertible_expense_amounts, {})

    def test_mixed_mapped_and_unmapped_expense_keeps_the_mapped_part(self):
        """Only the unvalued part is withheld; the booked cost is still real."""
        p = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 100.0, "platform_fee", currency="usd"),
            _evidence("opp-f5", 9000.0, "platform_fee", currency="XXX"),
        ])
        self.assertAlmostEqual(p.realized_expense, 100.0, places=2)
        self.assertAlmostEqual(p.realized_net, 900.0, places=2)
        self.assertTrue(p.has_unconvertible_expense)
        self.assertEqual(p.roi, 0.0)


# ── Serialisation and aggregation ────────────────────────────────────────────

class TestAnnotationIsSurfacedToConsumers(unittest.TestCase):
    """The data must reach every surface a consumer reads."""

    def test_to_dict_exposes_the_flag(self):
        p = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 50000.0, "platform_fee", currency="XXX"),
        ])
        d = p.to_dict()
        self.assertIs(d["has_unconvertible_expense"], True)
        self.assertEqual(d["unconvertible_expense_amounts"], {"XXX": 50000.0})
        # The raw sums stay visible for an operator; only the ratio is withheld.
        self.assertAlmostEqual(d["realized_net"], 1000.0, places=2)

    def test_clean_profile_to_dict_reports_false(self):
        p = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 100.0, "platform_fee", currency="usd"),
        ])
        d = p.to_dict()
        self.assertIs(d["has_unconvertible_expense"], False)

    def test_default_profile_reports_false(self):
        """A hand-built EconomicProfile must not claim an unvalued cost."""
        p = EconomicProfile(opportunity_id="opp-d")
        self.assertFalse(p.has_unconvertible_expense)
        self.assertIs(p.to_dict()["has_unconvertible_expense"], False)

    def test_aggregate_withholds_roi_and_names_the_currencies(self):
        clean = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 400.0, "platform_fee", currency="usd"),
        ])
        tainted = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 50000.0, "platform_fee", currency="XXX"),
        ])
        agg = EconomicAccounting(_EvidenceStoreStub([])).aggregate([clean, tainted])
        self.assertAlmostEqual(agg["total_verified_revenue"], 2000.0, places=2)
        self.assertAlmostEqual(agg["total_net_profit"], 1600.0, places=2)
        self.assertTrue(agg["has_unconvertible_expense"])
        self.assertEqual(agg["unconvertible_expense_amounts"], {"XXX": 50000.0})
        self.assertEqual(
            agg["roi"], 0.0,
            "a portfolio ROI built on an incomplete cost base must not be "
            "published as a return")

    def test_aggregate_of_clean_profiles_still_computes_roi(self):
        clean = _profile([
            _evidence("opp-f5", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-f5", 400.0, "platform_fee", currency="usd"),
        ], effort_hours=2.0)
        agg = EconomicAccounting(_EvidenceStoreStub([])).aggregate([clean])
        self.assertFalse(agg["has_unconvertible_expense"])
        self.assertEqual(agg["unconvertible_expense_amounts"], {})
        self.assertAlmostEqual(agg["roi"], 1.5, places=6)
        self.assertAlmostEqual(agg["net_hourly_rate"], 300.0, places=6)

    def test_aggregate_empty_carries_the_flag_keys(self):
        agg = EconomicAccounting(_EvidenceStoreStub([])).aggregate([])
        self.assertIs(agg["has_unconvertible_expense"], False)
        self.assertEqual(agg["unconvertible_expense_amounts"], {})


if __name__ == "__main__":
    unittest.main()
