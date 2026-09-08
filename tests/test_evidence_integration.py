"""tests/test_evidence_integration.py — full Evidence loop through the lifecycle (v2.0.34aq). unittest style."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.evidence import Evidence, EvidenceStatus, VerificationLevel, VerificationResult
from agents.evidence_store import EvidenceStore
from agents.evidence_factory import from_upwork_submission, from_receipt_report
from agents.evidence_policy import is_transition_eligible, revenue_eligibility
from database import AgentDB
from agents.opportunity_lifecycle import OpportunityLifecycleTracker
from agents.chain_verifier import ReceiptReport


class TestEvidenceIntegration(unittest.TestCase):
    def test_submission_evidence_gates_paid_transition(self):
        db = AgentDB(tempfile.mkdtemp() + "/t.db")
        store = EvidenceStore(db)
        life = OpportunityLifecycleTracker(evidence_store=store)
        opp = "opp_int_1"
        life.start(type("O", (), {"id": opp})())

        sub = from_upwork_submission(proposal_id="prop-999", profile_id="prof_1",
                                     job_id="job_1", subject_id=opp)
        self.assertEqual(sub.status, EvidenceStatus.VERIFIED)
        life.mark_submitted(opp, note="submitted", evidence=sub)

        all_ev = store.for_subject("opportunity", opp)
        self.assertFalse(is_transition_eligible("SUBMITTED->PAID", all_ev))

        comp = Evidence.create(source="upwork", evidence_type="completion_confirmation",
                               subject_id=opp, status=EvidenceStatus.VERIFIED,
                               verification_method="api_response",
                               verification_level=VerificationLevel.L3_EXTERNAL_SOURCE)
        pay = Evidence.create(source="upwork", evidence_type="payment_confirmation",
                              subject_id=opp, status=EvidenceStatus.VERIFIED,
                              verification_method="platform_transaction",
                              verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
                              amount=120.0, currency="USD")
        store.record_many([comp, pay])
        all_ev = store.for_subject("opportunity", opp)
        self.assertTrue(is_transition_eligible("SUBMITTED->PAID", all_ev))

        st = life.mark_paid_verified(opp, amount=120.0, evidence=pay)
        self.assertEqual(st.status, "paid")
        self.assertIn(pay.id, st.evidence_ids)
        self.assertIn(sub.id, st.evidence_ids)

    def test_conflicted_submission_does_not_verify(self):
        sub = from_upwork_submission(proposal_id="", profile_id="prof_1", subject_id="opp_x",
                                     errored=True, error_text="HTTP 500")
        self.assertEqual(sub.status, EvidenceStatus.CONFLICTED)
        db = AgentDB(tempfile.mkdtemp() + "/t.db")
        store = EvidenceStore(db)
        store.record(sub)
        self.assertFalse(is_transition_eligible("IN_PROGRESS->SUBMITTED", [sub]))

    def test_chain_receipt_becomes_evidence(self):
        rep = ReceiptReport(before_usd=10.0, after_usd=22.43, delta_usd=12.43,
                           expected_usd=10.0, min_ratio=0.5, received_usd=12.43,
                           verified=True, note="received")
        ev = from_receipt_report(rep, subject_id="claim_z", wallet_name="w1")
        self.assertEqual(ev.status, EvidenceStatus.VERIFIED)
        self.assertEqual(ev.verification_level, VerificationLevel.L5_CRYPTOGRAPHIC)
        self.assertAlmostEqual(ev.amount, 12.43)
        self.assertEqual(ev.provenance.get("producer"), "chain_verifier")

    def test_revenue_split_verified_vs_pending(self):
        evs = [
            Evidence.create(source="ethereum", evidence_type="payment_gross", subject_id="o1",
                            status=EvidenceStatus.VERIFIED,
                            verification_method="blockchain_transaction_receipt",
                            verification_level=VerificationLevel.L5_CRYPTOGRAPHIC,
                            amount=50.0, currency="USD"),
            Evidence.create(source="operator", evidence_type="payment_gross", subject_id="o2",
                            status=EvidenceStatus.VERIFIED,
                            verification_method="manual_attestation",
                            verification_level=VerificationLevel.L1_SELF_REPORTED,
                            amount=40.0, currency="USD"),
        ]
        rev = revenue_eligibility(evs)
        self.assertAlmostEqual(rev["verified_revenue"], 50.0)
        self.assertAlmostEqual(rev["pending_revenue"], 40.0)


if __name__ == "__main__":
    unittest.main()
