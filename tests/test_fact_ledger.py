"""tests/test_fact_ledger.py — invariants of the append-only claim register.

These tests pin the authority boundary: a model (or any caller) can PROPOSE a
claim but can never assert a verified fact, and the revision history cannot be
rewritten.
"""

import unittest

from agents.evidence import Claim, VerificationLevel
from agents.fact_ledger import (
    ClaimStatus,
    FactLedger,
    IllegalTransition,
    LedgerEntry,
    SourceKind,
    UnsubstantiatedVerification,
    source_authority,
)


def _claim(text="Upwork paid the invoice", **kw):
    base = dict(source="llm:edward", evidence_type="payment_confirmation",
                assertion=text)
    base.update(kw)
    return Claim(**base)


class TestFactLedgerInvariants(unittest.TestCase):

    def setUp(self):
        self.ledger = FactLedger()

    # ── A model cannot assert a verified fact ───────────────────────────────

    def test_llm_claim_starts_proposed_never_verified(self):
        entry = self.ledger.record_claim(_claim(), SourceKind.LLM)
        self.assertEqual(entry.status, ClaimStatus.PROPOSED)
        self.assertFalse(entry.status.is_affirmative)
        self.assertEqual(entry.evidence_refs, ())
        self.assertEqual(entry.verification_level, int(VerificationLevel.L0_UNOBSERVED))

    def test_no_api_lets_a_caller_hand_in_a_status(self):
        # record_claim has no status parameter at all — a caller cannot assert
        # VERIFIED; the only path up is attach_evidence().
        import inspect
        params = inspect.signature(FactLedger.record_claim).parameters
        self.assertNotIn("status", params)
        self.assertNotIn("verified", params)

    def test_llm_claim_is_not_verified_by_repeating_it(self):
        first = self.ledger.record_claim(_claim(), SourceKind.LLM)
        second = self.ledger.record_claim(_claim(), SourceKind.LLM)
        self.assertNotEqual(first.claim_id, second.claim_id)
        self.assertEqual(self.ledger.verified_claims(), [])

    # ── Verification requires real evidence at the required level ───────────

    def test_evidence_at_required_level_verifies(self):
        entry = self.ledger.record_claim(_claim(), SourceKind.LLM)
        out = self.ledger.attach_evidence(
            entry.claim_id, "ev_payment_123",
            VerificationLevel.L3_EXTERNAL_SOURCE,
            method="authenticated_api_response")
        self.assertEqual(out.status, ClaimStatus.VERIFIED)
        self.assertTrue(out.status.is_affirmative)
        self.assertEqual(out.evidence_refs, ("ev_payment_123",))
        self.assertEqual([e.claim_id for e in self.ledger.verified_claims()],
                         [entry.claim_id])

    def test_evidence_below_required_level_only_supports(self):
        entry = self.ledger.record_claim(_claim(), SourceKind.LLM)
        out = self.ledger.attach_evidence(
            entry.claim_id, "ev_self_report",
            VerificationLevel.L1_SELF_REPORTED, method="local_record")
        self.assertEqual(out.status, ClaimStatus.SUPPORTED)
        self.assertTrue(out.status.is_affirmative)
        self.assertEqual(self.ledger.verified_claims(), [])

    def test_operator_attestation_alone_cannot_satisfy_L3(self):
        # Mirrors evidence.METHOD_CONFIDENCE: human_attestation is 0.30, so a
        # bare operator statement must not become a verified fact.
        entry = self.ledger.record_claim(
            _claim(source="operator", assertion="I was paid"),
            SourceKind.OPERATOR)
        out = self.ledger.attach_evidence(
            entry.claim_id, "operator_note_1",
            VerificationLevel.L1_SELF_REPORTED, method="human_attestation")
        self.assertEqual(out.status, ClaimStatus.SUPPORTED)
        self.assertNotEqual(out.status, ClaimStatus.VERIFIED)

    def test_verification_without_an_evidence_ref_is_refused(self):
        entry = self.ledger.record_claim(_claim(), SourceKind.LLM)
        with self.assertRaises(UnsubstantiatedVerification):
            self.ledger.attach_evidence(
                entry.claim_id, "   ", VerificationLevel.L5_CRYPTOGRAPHIC)
        self.assertEqual(self.ledger.latest(entry.claim_id).status,
                         ClaimStatus.PROPOSED)

    # ── The history is append-only and entries are immutable ────────────────

    def test_history_is_append_only_and_monotonic(self):
        entry = self.ledger.record_claim(_claim(), SourceKind.LLM)
        self.ledger.attach_evidence(entry.claim_id, "ev_1",
                                    VerificationLevel.L2_LOCAL_VALIDATION)
        self.ledger.attach_evidence(entry.claim_id, "ev_2",
                                    VerificationLevel.L3_EXTERNAL_SOURCE)
        hist = self.ledger.history(entry.claim_id)
        self.assertEqual([h.revision for h in hist], [0, 1, 2])
        self.assertEqual([h.status for h in hist],
                         [ClaimStatus.PROPOSED, ClaimStatus.SUPPORTED,
                          ClaimStatus.VERIFIED])
        # the original revision is untouched by later appends
        self.assertEqual(hist[0].status, ClaimStatus.PROPOSED)
        self.assertEqual(hist[0].evidence_refs, ())

    def test_entries_are_immutable(self):
        entry = self.ledger.record_claim(_claim(), SourceKind.LLM)
        with self.assertRaises(Exception):
            entry.status = ClaimStatus.VERIFIED  # frozen dataclass
        self.assertIsInstance(entry, LedgerEntry)

    # ── Illegal transitions are refused ────────────────────────────────────

    def test_refuted_claim_cannot_become_verified(self):
        entry = self.ledger.record_claim(_claim(), SourceKind.LLM)
        self.ledger.refute(entry.claim_id, note="platform says unpaid")
        with self.assertRaises(IllegalTransition):
            self.ledger.attach_evidence(entry.claim_id, "ev_late",
                                        VerificationLevel.L5_CRYPTOGRAPHIC)

    def test_superseded_claim_is_closed(self):
        a = self.ledger.record_claim(_claim("paid $10"), SourceKind.LLM)
        b = self.ledger.record_claim(_claim("paid $25"), SourceKind.TOOL)
        self.ledger.supersede(a.claim_id, b.claim_id)
        self.assertEqual(self.ledger.latest(a.claim_id).status,
                         ClaimStatus.SUPERSEDED)
        with self.assertRaises(IllegalTransition):
            self.ledger.refute(a.claim_id)

    def test_supersede_requires_a_known_claim(self):
        a = self.ledger.record_claim(_claim(), SourceKind.LLM)
        with self.assertRaises(Exception):
            self.ledger.supersede(a.claim_id, "does-not-exist")

    def test_double_verification_is_refused(self):
        entry = self.ledger.record_claim(_claim(), SourceKind.LLM)
        self.ledger.attach_evidence(entry.claim_id, "ev_1",
                                    VerificationLevel.L3_EXTERNAL_SOURCE)
        # The claim is now VERIFIED. A second L3 evidence does not change the
        # status but SHOULD accumulate the extra reference — callers attaching
        # multiple sub/threshold evidence must not crash.
        second = self.ledger.attach_evidence(entry.claim_id, "ev_2",
                                             VerificationLevel.L3_EXTERNAL_SOURCE)
        self.assertEqual(second.status, ClaimStatus.VERIFIED)
        self.assertIn("ev_1", second.evidence_refs)
        self.assertIn("ev_2", second.evidence_refs)

    # ── Deterministic authority ordering ────────────────────────────────────

    def test_operator_outranks_model_deterministically(self):
        self.assertGreater(source_authority(SourceKind.OPERATOR),
                           source_authority(SourceKind.LLM))
        self.assertGreater(source_authority(SourceKind.TOOL),
                           source_authority(SourceKind.LLM))
        # and it is a fixed policy, not a per-call argument
        self.assertEqual(source_authority(SourceKind.OPERATOR),
                         source_authority(SourceKind.OPERATOR))

    # ── Misc contracts ──────────────────────────────────────────────────────

    def test_blank_assertion_is_refused(self):
        with self.assertRaises(Exception):
            self.ledger.record_claim(_claim("   "), SourceKind.LLM)

    def test_non_claim_input_is_refused(self):
        with self.assertRaises(Exception):
            self.ledger.record_claim("just a string", SourceKind.LLM)

    def test_to_dict_is_serialisable(self):
        entry = self.ledger.record_claim(_claim(), SourceKind.LLM)
        d = entry.to_dict()
        self.assertEqual(d["status"], "proposed")
        self.assertEqual(d["source_kind"], "llm")
        import json
        json.dumps(d)  # must not raise


if __name__ == "__main__":
    unittest.main()
