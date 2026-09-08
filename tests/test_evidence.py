"""tests/test_evidence.py — Evidence subsystem domain + store + policy (v2.0.34aq). unittest style."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.evidence import (
    Evidence, EvidenceStatus, VerificationLevel, VerificationResult, Claim, make_money_evidence_set,
)
from agents.evidence_store import EvidenceStore
from agents.evidence_policy import is_transition_eligible, revenue_eligibility
from database import AgentDB


class TestEvidence(unittest.TestCase):
    def test_evidence_immutable_verify_appends_history(self):
        ev = Evidence.create(source="upwork", evidence_type="platform_submission",
                              subject_id="opp_1", status=EvidenceStatus.UNVERIFIED)
        self.assertEqual(ev.status, EvidenceStatus.UNVERIFIED)
        res = VerificationResult(status=EvidenceStatus.VERIFIED, method="authenticated_api_response",
                                 level=VerificationLevel.L3_EXTERNAL_SOURCE, actor="upwork_client")
        ev2 = ev.verify(res)
        self.assertEqual(ev.status, EvidenceStatus.UNVERIFIED)   # original unchanged
        self.assertEqual(len(ev.history), 0)
        self.assertEqual(ev2.status, EvidenceStatus.VERIFIED)
        self.assertEqual(len(ev2.history), 1)
        self.assertEqual(ev2.history[0].method, "authenticated_api_response")

    def test_status_enum_has_six_values(self):
        self.assertEqual({s.value for s in EvidenceStatus},
                         {"UNVERIFIED", "PARTIALLY_VERIFIED", "VERIFIED", "REJECTED",
                          "CONFLICTED", "EXPIRED"})

    def test_conflicted_on_api_error(self):
        ev = Evidence.create(source="upwork", evidence_type="platform_submission",
                              subject_id="opp_2", status=EvidenceStatus.UNVERIFIED,
                              verification_method="api_response")
        res = VerificationResult(status=EvidenceStatus.CONFLICTED, method="api_response",
                                 level=VerificationLevel.L1_SELF_REPORTED,
                                 note="HTTP 500 after local submit attempt")
        ev2 = ev.verify(res)
        self.assertEqual(ev2.status, EvidenceStatus.CONFLICTED)
        self.assertFalse(ev2.is_verified())

    def test_verification_levels_ordering(self):
        self.assertGreater(VerificationLevel.L5_CRYPTOGRAPHIC, VerificationLevel.L3_EXTERNAL_SOURCE)
        self.assertLess(VerificationLevel.L1_SELF_REPORTED, VerificationLevel.L3_EXTERNAL_SOURCE)

    def test_is_verified_respects_min_level(self):
        ev = Evidence.create(source="operator", evidence_type="manual_attestation",
                             subject_id="opp_3", status=EvidenceStatus.VERIFIED,
                             verification_method="manual_attestation",
                             verification_level=VerificationLevel.L1_SELF_REPORTED)
        self.assertFalse(ev.is_verified(VerificationLevel.L3_EXTERNAL_SOURCE))
        self.assertTrue(ev.is_verified(VerificationLevel.L1_SELF_REPORTED))

    def test_store_append_only_and_query(self):
        db = AgentDB(tempfile.mkdtemp() + "/t.db")
        store = EvidenceStore(db)
        ev = Evidence.create(source="ethereum", evidence_type="balance_delta",
                             subject_type="airdrop_claim", subject_id="claim_1",
                             status=EvidenceStatus.VERIFIED,
                             verification_method="blockchain_balance_delta",
                             verification_level=VerificationLevel.L5_CRYPTOGRAPHIC,
                             amount=12.43, currency="USDC")
        store.record(ev)
        got = store.for_subject("airdrop_claim", "claim_1")
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0].amount, 12.43)
        self.assertEqual(len(store.history(ev.id)), 1)

    def test_policy_submitted_to_paid_requires_evidence(self):
        subs = [Evidence.create(source="upwork", evidence_type="platform_submission",
                                subject_id="opp_4", status=EvidenceStatus.VERIFIED,
                                verification_method="authenticated_api_response",
                                verification_level=VerificationLevel.L3_EXTERNAL_SOURCE)]
        self.assertFalse(is_transition_eligible("SUBMITTED->PAID", subs))
        full = subs + [
            Evidence.create(source="upwork", evidence_type="completion_confirmation",
                            subject_id="opp_4", status=EvidenceStatus.VERIFIED,
                            verification_method="api_response",
                            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE),
            Evidence.create(source="upwork", evidence_type="payment_confirmation",
                            subject_id="opp_4", status=EvidenceStatus.VERIFIED,
                            verification_method="platform_transaction",
                            verification_level=VerificationLevel.L3_EXTERNAL_SOURCE),
        ]
        self.assertTrue(is_transition_eligible("SUBMITTED->PAID", full))

    def test_revenue_eligibility_split(self):
        evs = make_money_evidence_set(gross=100.0, currency="USD", fees=20.0, gas=0.0,
                                     llm_cost=0.8, other=2.0, subject_id="opp_5",
                                     level=VerificationLevel.L5_CRYPTOGRAPHIC)
        for i, e in enumerate(evs):
            if e.evidence_type == "payment_gross":
                evs[i] = e.verify(VerificationResult(status=EvidenceStatus.VERIFIED,
                             method="blockchain_transaction_receipt",
                             level=VerificationLevel.L5_CRYPTOGRAPHIC))
        rev = revenue_eligibility(evs)
        self.assertAlmostEqual(rev["verified_revenue"], 100.0)
        self.assertAlmostEqual(rev["verified_expenses"], 22.8)

    def test_manual_attestation_stays_pending_not_hard(self):
        evs = [Evidence.create(source="operator", evidence_type="payment_gross",
                               subject_id="opp_6", status=EvidenceStatus.VERIFIED,
                               verification_method="manual_attestation",
                               verification_level=VerificationLevel.L1_SELF_REPORTED,
                               amount=50.0, currency="USD")]
        rev = revenue_eligibility(evs)
        self.assertAlmostEqual(rev["verified_revenue"], 0.0)
        self.assertAlmostEqual(rev["pending_revenue"], 50.0)

    def test_claim_is_not_trusted_evidence(self):
        c = Claim(source="llm", evidence_type="completion_confirmation", subject_id="opp_7",
                 assertion="the client appears to have accepted the work")
        self.assertFalse(hasattr(c, "status"))
        self.assertFalse(hasattr(c, "verify"))


if __name__ == "__main__":
    unittest.main()
