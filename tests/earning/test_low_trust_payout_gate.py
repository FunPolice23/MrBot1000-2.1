"""ARCH-ENG-043 — a low-trust (L1) payout must never reach a 'paid' lifecycle
or credit a submission-ramp win.

Root cause closed here: ``OpportunityLifecycleTracker.mark_paid_verified``'s
"No store + Evidence" branch flipped ``status`` to ``paid`` on ANY affirmative
Evidence, with no trust-level check. ``evidence_factory`` maps a
``manual_reference`` payout (an operator-typed transaction reference) to
``VERIFIED @ L1_SELF_REPORTED``, so a store-less tracker marked that as paid,
``is_affirmative_verification`` agreed, and the caller credited a ramp WIN.

The ramp win-rate is the counter that unlocks auto-submission
(``SubmissionRamp.requires_human``), so unverified/self-reported money could
have talked the system into submitting real proposals with no human in the
loop — the exact failure mode v2.1.36's F4 fix closed on the revenue side.

Reproduced by execution BEFORE the fix (store-less tracker, L1 manual
attestation): ``status='paid'`` and ``is_affirmative_verification=True``, i.e.
a ramp win was credited. After the fix the same call yields ``'active'`` and
no win, while genuine L3/L5 payouts still verify.
"""

import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.earning.evidence import is_affirmative_verification
from agents.earning.opportunity_lifecycle import OpportunityLifecycleTracker
from agents.earning.payout_verifier import VerificationEvidence
from agents.evidence.evidence import VerificationLevel
from agents.evidence.evidence_factory import from_verification_evidence


def _manual_payout(subject_id, amount=250.0, ref="bank-txn-abc123"):
    """An operator-attested payout: VERIFIED, but only at L1 (self-reported)."""
    return from_verification_evidence(
        VerificationEvidence(method="manual_reference", verified=True,
                             expected_usd=amount, observed_usd=amount,
                             reference=ref),
        subject_id=subject_id)


def _api_payout(subject_id, amount=250.0):
    """A genuine external API statement: VERIFIED at L3."""
    return from_verification_evidence(
        VerificationEvidence(method="api_statement", verified=True,
                             expected_usd=amount, observed_usd=amount,
                             reference="stmt-777"),
        subject_id=subject_id)


def _onchain_payout(subject_id, amount=5.0):
    """A genuine on-chain balance delta: VERIFIED at L5."""
    return from_verification_evidence(
        VerificationEvidence(method="onchain_balance_delta", verified=True,
                             expected_usd=amount, observed_usd=amount,
                             reference="0xdeadbeef"),
        subject_id=subject_id)


def _tracker(evidence_store=None):
    """A lifecycle tracker that never touches disk or a real DB."""
    t = OpportunityLifecycleTracker.__new__(OpportunityLifecycleTracker)
    t._evidence_store = evidence_store
    t._states = {}
    t._history = []
    t._state_path = os.path.join(tempfile.mkdtemp(), "lifecycle_states.json")
    return t


class _FakeStore:
    """Minimal EvidenceStore stand-in (same surface the lifecycle uses)."""

    def __init__(self):
        self.items = []

    def record(self, ev):
        self.items.append(ev)
        return ev

    def get(self, eid):
        return next((e for e in self.items if e.id == eid), None)

    def for_subject(self, subject_type, subject_id):
        return [e for e in self.items if e.subject_id == subject_id]


def _would_credit_ramp_win(state):
    """Mirror of both ramp-credit call sites (pipeline + GUI operator payout)."""
    return state.status == "paid" and is_affirmative_verification(state)


class TestLowTrustPayoutCannotReachPaid(unittest.TestCase):
    """An L1 self-reported payout is not evidence that money arrived."""

    def tearDown(self):
        for st in list(getattr(self, "_paths", [])):
            shutil.rmtree(os.path.dirname(st), ignore_errors=True)

    def _t(self, store=None):
        t = _tracker(store)
        self._paths = getattr(self, "_paths", []) + [t._state_path]
        return t

    # ── The regression itself ────────────────────────────────────────────────

    def test_l1_manual_attestation_no_store_is_not_paid(self):
        """THE regression: store-less tracker + L1 manual attestation was 'paid'."""
        state = self._t().mark_paid_verified(
            "opp-l1", amount=250.0, evidence=_manual_payout("opp-l1"))
        self.assertNotEqual(
            state.status, "paid",
            "an L1 self-reported payout must not flip the lifecycle to paid")

    def test_l1_manual_attestation_no_store_credits_no_ramp_win(self):
        """The safety consequence: no ramp win, so auto-submission stays locked."""
        state = self._t().mark_paid_verified(
            "opp-l1b", amount=250.0, evidence=_manual_payout("opp-l1b"))
        self.assertFalse(
            _would_credit_ramp_win(state),
            "a low-trust payout must not advance the win-rate that unlocks "
            "auto-submission")

    def test_l1_manual_attestation_with_store_is_not_paid(self):
        """The policy-gated (with-store) path must refuse the same L1 payout.

        Note this is a CONTROL, not a regression test for this change: the
        with-store refusal comes from the pre-existing
        ``evidence_policy.is_transition_eligible`` gate, which already rejected
        L1 before ARCH-ENG-043. It is kept so that if the no-store and with-store
        paths ever diverge, the asymmetry shows up here.
        """
        state = self._t(_FakeStore()).mark_paid_verified(
            "opp-l1c", amount=250.0, evidence=_manual_payout("opp-l1c"))
        self.assertNotEqual(state.status, "paid")

    def test_status_with_but_no_level_does_not_raise(self):
        """A duck-typed evidence carrying a status but verification_level=None
        must fail closed without raising (the audit message must not assume a
        level is present)."""
        class _Odd:
            # Mirrors the EvidenceStatus surface mark_paid_verified touches.
            status = type("S", (), {"value": "VERIFIED", "is_affirmative": True})()
            verification_level = None
            verification_method = "odd"

            def to_dict(self):
                return {"status": "VERIFIED", "verification_level": None}
        state = self._t().mark_paid_verified("opp-odd", amount=250.0,
                                             evidence=_Odd())
        self.assertNotEqual(state.status, "paid")
        self.assertEqual(state.last_amount, 0.0)

    def test_affirmative_accepts_an_evidence_object_not_just_a_dict(self):
        """The trust floor must work on an Evidence object as well as on its
        to_dict() form — str(EvidenceStatus.VERIFIED) is
        'EvidenceStatus.VERIFIED' on Python 3.14, so a naive str() comparison
        silently returns False for every object."""
        class S:
            pass
        hi, lo = S(), S()
        hi.verification = _api_payout("obj-hi")
        lo.verification = _manual_payout("obj-lo")
        self.assertTrue(is_affirmative_verification(hi),
                        "a real L3 Evidence object must be recognised")
        self.assertFalse(is_affirmative_verification(lo),
                         "an L1 Evidence object must not pass the L3 floor")

    def test_l1_books_no_revenue(self):
        """No amount is realised from an unproven payout."""
        state = self._t().mark_paid_verified(
            "opp-l1d", amount=250.0, evidence=_manual_payout("opp-l1d"))
        self.assertEqual(state.last_amount, 0.0,
                         "an unverified payout must not book any amount")

    # ── The fail-closed branch must tolerate evidence=None ───────────────────

    def test_none_evidence_no_store_is_not_paid(self):
        """`evidence=None` reached this branch and must not raise."""
        state = self._t().mark_paid_verified("opp-none", amount=250.0,
                                             evidence=None)
        self.assertNotEqual(state.status, "paid")
        self.assertEqual(state.last_amount, 0.0)

    # ── Controls: genuine payouts must still verify ──────────────────────────

    def test_l3_api_statement_still_verifies(self):
        state = self._t().mark_paid_verified(
            "opp-l3", amount=250.0, evidence=_api_payout("opp-l3"))
        self.assertEqual(state.status, "paid")
        self.assertAlmostEqual(state.last_amount, 250.0)
        self.assertTrue(_would_credit_ramp_win(state),
                        "a genuine L3 payment MUST still credit a ramp win")

    def test_l5_onchain_delta_still_verifies(self):
        state = self._t().mark_paid_verified(
            "opp-l5", amount=5.0, evidence=_onchain_payout("opp-l5"))
        self.assertEqual(state.status, "paid")
        self.assertTrue(_would_credit_ramp_win(state))

    def test_l3_with_zero_amount_is_refused(self):
        """The amount gate the with-store path enforces applies here too."""
        state = self._t().mark_paid_verified(
            "opp-l3z", amount=0.0, evidence=_api_payout("opp-l3z"))
        self.assertNotEqual(state.status, "paid",
                            "a non-positive amount is not realised revenue")


class TestAffirmativeVerificationTrustFloor(unittest.TestCase):
    """`is_affirmative_verification` must consider trust LEVEL, not just status."""

    def _state(self, status, level):
        class S:
            pass
        s = S()
        s.verification = {"status": status, "verification_level": int(level)}
        return s

    def test_l1_verified_is_not_affirmative_for_money(self):
        self.assertFalse(is_affirmative_verification(self._state("VERIFIED", 1)))

    def test_l2_verified_is_not_affirmative_for_money(self):
        self.assertFalse(is_affirmative_verification(self._state("VERIFIED", 2)))

    def test_l3_verified_is_affirmative(self):
        self.assertTrue(is_affirmative_verification(self._state("VERIFIED", 3)))

    def test_l5_verified_is_affirmative(self):
        self.assertTrue(is_affirmative_verification(self._state("VERIFIED", 5)))

    def test_partially_verified_l1_is_not_affirmative(self):
        self.assertFalse(
            is_affirmative_verification(self._state("PARTIALLY_VERIFIED", 1)))

    def test_unverified_status_never_affirmative(self):
        self.assertFalse(is_affirmative_verification(self._state("UNVERIFIED", 5)))

    def test_missing_level_fails_closed(self):
        class S:
            pass
        s = S()
        s.verification = {"status": "VERIFIED"}  # legacy self-report: no level
        self.assertFalse(is_affirmative_verification(s),
                         "a record with no trust level must not pass an L3 floor")

    def test_none_state_is_not_affirmative(self):
        self.assertFalse(is_affirmative_verification(None))

    def test_floor_matches_the_policy_constant(self):
        """The floor must equal the policy's L3 external-source level."""
        self.assertEqual(int(VerificationLevel.L3_EXTERNAL_SOURCE), 3)


if __name__ == "__main__":
    unittest.main()
