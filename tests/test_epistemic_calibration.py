"""tests/test_epistemic_calibration.py — deterministic confidence classification."""

import unittest

from agents.evidence import Claim, VerificationLevel
from agents.fact_ledger import FactLedger, SourceKind
from agents.epistemic_calibration import (
    EpistemicLevel,
    classify,
    confidence,
    context_note,
    disclaimer,
)


def _claim(text="client accepted the work", subject_id="opp_1"):
    return Claim(source="llm:edward", evidence_type="state", assertion=text,
                 subject_id=subject_id)


class TestEpistemicCalibration(unittest.TestCase):

    def setUp(self):
        self.ledger = FactLedger()

    def _entry(self, source_kind=SourceKind.LLM):
        return self.ledger.record_claim(_claim(), source_kind)

    # ── Classification is deterministic and never model-rated ───────────────

    def test_none_is_unknown(self):
        self.assertEqual(classify(None), EpistemicLevel.UNKNOWN)
        self.assertEqual(confidence(None), 0.0)

    def test_proposed_is_speculative(self):
        e = self._entry()
        self.assertEqual(classify(e), EpistemicLevel.SPECULATIVE)
        self.assertEqual(confidence(e), 0.1)

    def test_supported_is_plausible_and_capped(self):
        e = self._entry()
        out = self.ledger.attach_evidence(e.claim_id, "ev_1",
                                          VerificationLevel.L1_SELF_REPORTED,
                                          method="human_attestation")
        self.assertEqual(classify(out), EpistemicLevel.PLAUSIBLE)
        # human_attestation is 0.30, below the 0.5 ceiling
        self.assertLessEqual(confidence(out), 0.5)
        self.assertEqual(confidence(out), 0.30)

    def test_verified_l3_is_corroborated(self):
        e = self._entry()
        out = self.ledger.attach_evidence(e.claim_id, "ev_api",
                                          VerificationLevel.L3_EXTERNAL_SOURCE,
                                          method="authenticated_api_response")
        self.assertEqual(classify(out), EpistemicLevel.CORROBORATED)
        self.assertEqual(confidence(out), 0.70)

    def test_verified_l5_is_confirmed(self):
        e = self._entry()
        out = self.ledger.attach_evidence(e.claim_id, "ev_tx",
                                          VerificationLevel.L5_CRYPTOGRAPHIC,
                                          method="blockchain_balance_delta")
        self.assertEqual(classify(out), EpistemicLevel.CONFIRMED)
        self.assertEqual(confidence(out), 1.00)

    def test_refuted_and_overridden_have_zero_confidence(self):
        e = self._entry()
        refuted = self.ledger.refute(e.claim_id)
        self.assertEqual(classify(refuted), EpistemicLevel.REFUTED)
        self.assertEqual(confidence(refuted), 0.0)

        e2 = self._entry()
        self.ledger.supersede_by_reference(e2.claim_id, "override_1")
        overridden = self.ledger.latest(e2.claim_id)
        self.assertEqual(classify(overridden), EpistemicLevel.OVERRIDDEN)
        self.assertEqual(confidence(overridden), 0.0)

    # ── Disclaimers ─────────────────────────────────────────────────────────

    def test_disclaimers_are_honest_and_distinct(self):
        self.assertIn("no verified information", disclaimer(None))
        self.assertIn("unverified", disclaimer(self._entry()))
        e = self._entry()
        out = self.ledger.attach_evidence(e.claim_id, "ev_api",
                                          VerificationLevel.L3_EXTERNAL_SOURCE,
                                          method="authenticated_api_response")
        self.assertIn("corroborated", disclaimer(out))

    # ── Aggregate context note ──────────────────────────────────────────────

    def test_context_note_excludes_closed_claims_and_is_bounded(self):
            good = self._entry()
            bad = self.ledger.record_claim(
                _claim("the client rejected the work"), SourceKind.LLM)
            self.ledger.refute(bad.claim_id)
            # pass the CURRENT revisions, as a caller would (ledger.all_claims())
            note = context_note([good, self.ledger.latest(bad.claim_id)])
            self.assertIn(good.statement, note)
            self.assertNotIn(bad.statement, note)
            self.assertIn("EPISTEMIC STATUS", note)

    def test_context_note_empty_when_nothing_standing(self):
        e = self._entry()
        self.ledger.refute(e.claim_id)
        self.assertEqual(context_note([self.ledger.latest(e.claim_id)]), "")

    def test_context_note_respects_max_claims(self):
        entries = [self._entry() for _ in range(12)]
        note = context_note(entries, max_claims=5)
        self.assertLessEqual(note.count("\n- "), 5)


if __name__ == "__main__":
    unittest.main()
