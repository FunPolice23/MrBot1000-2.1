"""tests/test_dialogue_honesty.py — bounding + dedupe of the claim ledger.

The honesty service records model claims as PROPOSED. Left unbounded it grows
every turn and the injected epistemic note bloats the system prompt, which
measurably degrades small local models. These tests pin the bound and the
deduplication, and confirm the prune never drops an authoritative entry.
"""

import unittest

from agents.dialogue_honesty import DialogueHonestyService
from agents.evidence import VerificationLevel
from agents.fact_ledger import ClaimStatus


class TestDialogueHonestyBounding(unittest.TestCase):

    def test_repeated_claims_are_recorded_once(self):
        svc = DialogueHonestyService()
        text = "The platform pays is available in every country today."
        first = svc.record_claims(text)
        second = svc.record_claims(text)
        self.assertTrue(first)                      # something was extracted
        self.assertEqual(second, [])                # nothing new the 2nd time
        self.assertEqual(len(svc.ledger.all_claims()), len(first))

    def test_ledger_is_bounded(self):
        svc = DialogueHonestyService(max_claims=10)
        # Record many distinct claims; the ledger must not exceed the bound.
        for i in range(60):
            svc.record_claims(
                f"The opportunity number {i} is available and pays money.")
        self.assertLessEqual(len(svc.ledger.all_claims()), 10)

    def test_prune_never_drops_verified_claims(self):
        svc = DialogueHonestyService(max_claims=3)
        entry = svc.record_claims(
            "The api response is confirmed for this payment.")[0]
        svc.ledger.attach_evidence(
            entry.claim_id, "ev_api", VerificationLevel.L3_EXTERNAL_SOURCE,
            method="authenticated_api_response")
        # Flood with new unverified claims to force pruning.
        for i in range(20):
            svc.record_claims(f"The thing {i} is available and works well.")
        verified = svc.ledger.verified_claims()
        self.assertEqual([v.claim_id for v in verified], [entry.claim_id])

    def test_prune_keeps_operator_superseded_audit_trail(self):
        svc = DialogueHonestyService(max_claims=2)
        entry = svc.record_claims(
            "The client is going to accept this proposal soon.")[0]
        svc.ledger.supersede_by_reference(entry.claim_id, "override_1")
        for i in range(10):
            svc.record_claims(f"The item {i} is available and payable now.")
        latest = svc.ledger.latest(entry.claim_id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.status, ClaimStatus.SUPERSEDED)

    def test_epistemic_note_is_bounded(self):
        svc = DialogueHonestyService(max_claims=40)
        for i in range(40):
            svc.record_claims(f"The opportunity {i} is available and pays.")
        note = svc.epistemic_context_note(max_claims=5)
        self.assertLessEqual(note.count("\n- "), 5)

    def test_empty_ledger_produces_no_note(self):
        svc = DialogueHonestyService()
        self.assertEqual(svc.epistemic_context_note(), "")


if __name__ == "__main__":
    unittest.main()
