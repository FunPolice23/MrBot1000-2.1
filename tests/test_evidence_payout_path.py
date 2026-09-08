"""tests/test_evidence_payout_path.py — reproduces the main.py payout verification path
(v2.0.34aq): PayoutVerifier.verify_crypto returns a legacy VerificationEvidence dataclass,
which mark_paid_verified must convert (not crash on .get) and gate on policy.
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.evidence import EvidenceStatus
from agents.evidence_store import EvidenceStore
from agents.evidence_factory import from_verification_evidence
from agents.opportunity_lifecycle import OpportunityLifecycleTracker
from agents.payout_verifier import PayoutVerifier, VerificationEvidence
from database import AgentDB


class FakeWallet:
    def __init__(self, usd): self.usd_value = usd
    def get_balance(self, name=None): return self


class TestPayoutPath(unittest.TestCase):
    def test_verification_evidence_is_plain_dataclass_not_evidence(self):
        # documents the reality the fix must handle
        ve = VerificationEvidence(method="onchain_balance_delta", verified=True,
                                  expected_usd=12.0, observed_usd=12.0)
        self.assertFalse(hasattr(ve, "status"))
        self.assertTrue(hasattr(ve, "verified"))
        self.assertTrue(hasattr(ve, "method"))

    def test_mark_paid_verified_accepts_verification_evidence_no_crash(self):
        db = AgentDB(tempfile.mkdtemp() + "/p.db")
        store = EvidenceStore(db)
        life = OpportunityLifecycleTracker(evidence_store=store)
        opp = "opp_pay_1"
        life.start(type("O", (), {"id": opp})())

        # simulate submission + completion evidence so the transition can be eligible
        from agents.evidence import Evidence, VerificationLevel
        sub = Evidence.create(source="upwork", evidence_type="platform_submission",
                              subject_id=opp, status=EvidenceStatus.VERIFIED,
                              verification_method="authenticated_api_response",
                              verification_level=VerificationLevel.L3_EXTERNAL_SOURCE)
        comp = Evidence.create(source="upwork", evidence_type="completion_confirmation",
                               subject_id=opp, status=EvidenceStatus.VERIFIED,
                               verification_method="api_response",
                               verification_level=VerificationLevel.L3_EXTERNAL_SOURCE)
        store.record_many([sub, comp])

        # verify_crypto returns a plain VerificationEvidence (the main.py path)
        verifier = PayoutVerifier()
        ve = verifier.verify_crypto(FakeWallet(112.0), "w1", expected_usd=12.0,
                                    before_bal_usd=100.0, after_bal_usd=112.0)
        self.assertIsInstance(ve, VerificationEvidence)
        self.assertTrue(ve.verified)

        # this used to raise AttributeError (.get on a dataclass); now converts + gates
        st = life.mark_paid_verified(opp, amount=12.0, evidence=ve)
        self.assertEqual(st.status, "paid")
        # payment evidence was recorded under the opportunity subject
        all_ev = store.for_subject("opportunity", opp)
        payments = [e for e in all_ev if e.evidence_type in
                    ("balance_delta", "manual_attestation", "platform_transaction")]
        self.assertTrue(any(e.status == EvidenceStatus.VERIFIED for e in payments))

    def test_unverified_crypto_does_not_mark_paid(self):
        db = AgentDB(tempfile.mkdtemp() + "/p2.db")
        store = EvidenceStore(db)
        life = OpportunityLifecycleTracker(evidence_store=store)
        opp = "opp_pay_2"
        life.start(type("O", (), {"id": opp})())
        from agents.evidence import Evidence, VerificationLevel
        sub = Evidence.create(source="upwork", evidence_type="platform_submission",
                              subject_id=opp, status=EvidenceStatus.VERIFIED,
                              verification_method="authenticated_api_response",
                              verification_level=VerificationLevel.L3_EXTERNAL_SOURCE)
        comp = Evidence.create(source="upwork", evidence_type="completion_confirmation",
                               subject_id=opp, status=EvidenceStatus.VERIFIED,
                               verification_method="api_response",
                               verification_level=VerificationLevel.L3_EXTERNAL_SOURCE)
        store.record_many([sub, comp])
        verifier = PayoutVerifier()
        ve = verifier.verify_crypto(None, "", expected_usd=12.0)  # no wallet -> unverified
        self.assertFalse(ve.verified)
        st = life.mark_paid_verified(opp, amount=12.0, evidence=ve)
        # unverified payment -> NOT paid (stayed at prior stage)
        self.assertNotEqual(st.status, "paid")

    def test_factory_from_verification_evidence_maps_fields(self):
        ve = VerificationEvidence(method="onchain_balance_delta", verified=True,
                                  expected_usd=12.0, observed_usd=12.0, reference="0xabc")
        ev = from_verification_evidence(ve, subject_id="opp_x")
        self.assertEqual(ev.subject_type, "opportunity")
        self.assertEqual(ev.status, EvidenceStatus.VERIFIED)
        self.assertEqual(ev.verification_method, "blockchain_balance_delta")
        self.assertEqual(ev.verification_level.value, 5)  # L5 CRYPTOGRAPHIC


if __name__ == "__main__":
    unittest.main()
