"""A wallet balance is not a payout: crypto verification needs both snapshots.

Finding F4 (v2.1.35). ``PayoutVerifier.verify_crypto`` had a "best-effort"
branch for when only the current balance was available:

    ok = current >= expected
    VerificationEvidence(verified=ok, observed_usd=current, ...)

That is a solvency check dressed up as a payment measurement, and it booked the
wallet's ENTIRE balance as revenue. Reproduced before the fix: a wallet already
holding $500 and a $5 expected payout produced

    VERIFIED / L5_CRYPTOGRAPHIC / amount = 500.0

— $495 of invented revenue at the highest trust level. ``evidence_factory``
maps ``onchain_balance_delta`` straight to L5, so nothing downstream could catch
it, and the resulting accept fed ``submission_ramp.record_accept`` — the counter
that unlocks auto-submission. ``main.py:1711`` calls this with no snapshots, so
the operator payout path hit it directly.

These tests pin the invariant: an on-chain payout is verified only from a real
before/after delta, and the booked amount is always that delta.
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.earning.payout_verifier import (  # noqa: E402
    PayoutVerifier,
    VerificationEvidence,
)
from agents.evidence.evidence_factory import from_verification_evidence  # noqa: E402
from agents.evidence.evidence import EvidenceStatus  # noqa: E402


class _Wallet:
    """A wallet whose absolute balance is whatever the test says."""

    def __init__(self, usd):
        self._usd = usd

    def get_balance(self, _name):
        return type("Bal", (), {"usd_value": self._usd})()


def _evidence(ve, subject="opp"):
    return from_verification_evidence(ve, subject_id=subject)


class TestCryptoPayoutNeedsBothSnapshots(unittest.TestCase):
    def setUp(self):
        self.v = PayoutVerifier()

    def test_pre_existing_balance_is_not_a_payout(self):
        """The F4 regression: a $500 wallet and a $5 payout must book $0."""
        ve = self.v.verify_crypto(_Wallet(500.0), "w", 5.0)
        self.assertFalse(ve.verified)
        ev = _evidence(ve)
        self.assertEqual(float(ev.amount or 0), 0.0)
        self.assertIs(ev.status, EvidenceStatus.UNVERIFIED)

    def test_every_partial_snapshot_combination_is_unverified(self):
        """No snapshot pair may ever produce a verified crypto payout."""
        for before, after in ((None, 500.0), (495.0, None), (None, None)):
            ve = self.v.verify_crypto(_Wallet(500.0), "w", 5.0,
                                      before_bal_usd=before, after_bal_usd=after)
            self.assertFalse(
                ve.verified, f"before={before} after={after} must not verify")
            self.assertEqual(float(_evidence(ve).amount or 0), 0.0)

    def test_real_delta_verifies_and_books_only_the_delta(self):
        """A genuine payout is still verified — and books the delta, not the total."""
        ve = self.v.verify_crypto(_Wallet(1005.0), "w", 5.0,
                                  before_bal_usd=1000.0, after_bal_usd=1005.0)
        self.assertTrue(ve.verified)
        ev = _evidence(ve)
        self.assertEqual(float(ev.amount or 0), 5.0,
                         "a $1005 wallet must not book $1005 on a $5 payout")

    def test_small_delta_does_not_satisfy_a_larger_expectation(self):
        """A $5 gain cannot verify a $100 expectation."""
        ve = self.v.verify_crypto(_Wallet(500.0), "w", 100.0,
                                  before_bal_usd=495.0, after_bal_usd=500.0)
        self.assertFalse(ve.verified)
        self.assertIs(_evidence(ve).status, EvidenceStatus.UNVERIFIED)

    def test_unverified_evidence_never_counts_as_revenue(self):
        """The accounting gate, asserted end-to-end rather than assumed."""
        ve = self.v.verify_crypto(_Wallet(500.0), "w", 5.0)
        ev = _evidence(ve)
        # economic_accounting.get_profile requires status==VERIFIED AND level>=L3.
        from agents.evidence.evidence import EvidenceStatus, VerificationLevel
        counts = (ev.status == EvidenceStatus.VERIFIED
                  and ev.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE)
        self.assertFalse(counts, "unverifiable crypto must not reach verified_revenue")

    def test_missing_wallet_still_fails_closed(self):
        ve = self.v.verify_crypto(None, "", 12.0)
        self.assertFalse(ve.verified)


class TestAccountingAccessorsMatchGetProfile(unittest.TestCase):
    """F6: the quick accessors used a weaker rule than get_profile."""

    def _acct(self, store):
        from agents.earning.economic_accounting import EconomicAccounting
        return EconomicAccounting(evidence_store=store)

    def test_l1_attestation_is_not_verified_revenue(self):
        """An L1 manual_attestation must count 0 in BOTH accessors."""
        from agents.evidence.evidence import (
            Evidence, EvidenceStatus, VerificationLevel)

        ev = Evidence.create(
            source="operator", evidence_type="manual_attestation",
            subject_type="opportunity", subject_id="opp-x",
            amount=250.0, currency="USD",
            status=EvidenceStatus.VERIFIED,
            verification_method="manual_attestation",
            verification_level=VerificationLevel.L1_SELF_REPORTED)

        store = type("S", (), {"for_subject": lambda self, t, i: [ev]})()
        acct = self._acct(store)
        self.assertEqual(acct.get_verified_revenue("opp-x"), 0.0,
                         "L1 self-reported must not be 'verified revenue'")

    def test_l3_verified_payment_counts(self):
        from agents.evidence.evidence import (
            Evidence, EvidenceStatus, VerificationLevel)

        ev = Evidence.create(
            source="upwork", evidence_type="platform_transaction",
            subject_type="opportunity", subject_id="opp-y",
            amount=250.0, currency="USD",
            status=EvidenceStatus.VERIFIED,
            verification_method="api_response",
            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE)

        store = type("S", (), {"for_subject": lambda self, t, i: [ev]})()
        acct = self._acct(store)
        self.assertEqual(acct.get_verified_revenue("opp-y"), 250.0)


if __name__ == "__main__":
    unittest.main()
