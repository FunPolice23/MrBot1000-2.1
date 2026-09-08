"""tests/test_evidence_audit_fixups.py — regression tests for the v2.0.34aq audit fixes.

Covers:
- mark_paid_verified must accept a legacy VerificationEvidence (no AttributeError on .get)
- a crypto-only L5 balance_delta marks paid even without submission/completion evidence
  (uses CLAIMED->REVENUE_REALIZED, not only SUBMITTED->PAID)
- unverified crypto does NOT mark paid
- from_verification_evidence maps subject_type + level correctly
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.evidence import EvidenceStatus, VerificationLevel
from agents.evidence_store import EvidenceStore
from agents.evidence_factory import from_verification_evidence
from agents.opportunity_lifecycle import OpportunityLifecycleTracker
from agents.payout_verifier import PayoutVerifier, VerificationEvidence
from database import AgentDB


class FakeWallet:
    def __init__(self, usd): self.usd_value = usd
    def get_balance(self, name=None): return self


class TestAuditFixups(unittest.TestCase):
    def _life(self):
        db = AgentDB(tempfile.mkdtemp() + "/au.db")
        return OpportunityLifecycleTracker(evidence_store=EvidenceStore(db))

    def test_crypto_only_l5_marks_paid_without_submission(self):
        life = self._life()
        opp = "opp_crypto_1"
        life.start(type("O", (), {"id": opp})())
        verifier = PayoutVerifier()
        ve = verifier.verify_crypto(FakeWallet(112.0), "w1", expected_usd=12.0,
                                    before_bal_usd=100.0, after_bal_usd=112.0)
        self.assertTrue(ve.verified)
        st = life.mark_paid_verified(opp, amount=12.0, evidence=ve)
        self.assertEqual(st.status, "paid")  # eligible via CLAIMED->REVENUE_REALIZED (L5)

    def test_unverified_crypto_does_not_mark_paid(self):
        life = self._life()
        opp = "opp_crypto_2"
        life.start(type("O", (), {"id": opp})())
        verifier = PayoutVerifier()
        ve = verifier.verify_crypto(None, "", expected_usd=12.0)  # no wallet -> unverified
        self.assertFalse(ve.verified)
        st = life.mark_paid_verified(opp, amount=12.0, evidence=ve)
        self.assertNotEqual(st.status, "paid")

    def test_factory_maps_crypto_to_opportunity_and_l5(self):
        ve = VerificationEvidence(method="onchain_balance_delta", verified=True,
                                  expected_usd=12.0, observed_usd=12.0, reference="0xabc")
        ev = from_verification_evidence(ve, subject_id="oX")
        self.assertEqual(ev.subject_type, "opportunity")
        self.assertEqual(ev.status, EvidenceStatus.VERIFIED)
        self.assertEqual(ev.verification_level, VerificationLevel.L5_CRYPTOGRAPHIC)
        self.assertEqual(ev.evidence_type, "balance_delta")


if __name__ == "__main__":
    unittest.main()
