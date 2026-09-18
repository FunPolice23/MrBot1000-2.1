"""tests/test_operator_override.py — human authority over model claims.

Pins the two boundaries that matter: an override carries authority (it can
supersede a model claim) but never evidence (it cannot manufacture a verified
fact), and it never lets automation skip a human gate.
"""

import unittest

from agents.evidence import Claim, VerificationLevel
from agents.fact_ledger import ClaimStatus, FactLedger, SourceKind
from agents.operator_override import (
    OperatorOverrideRegistry,
    OverrideError,
)


def _claim(text, subject_id="", source="llm:edward"):
    return Claim(source=source, evidence_type="state", assertion=text,
                 subject_id=subject_id)


class TestOperatorOverride(unittest.TestCase):

    def setUp(self):
        self.ledger = FactLedger()
        self.overrides = OperatorOverrideRegistry()

    # ── Issuing ─────────────────────────────────────────────────────────────

    def test_issue_creates_active_operator_authority(self):
        rec = self.overrides.issue("The Upwork contract was cancelled.",
                                   subject_id="opp_1")
        self.assertTrue(rec.active)
        self.assertEqual(rec.source_kind, SourceKind.OPERATOR)
        self.assertEqual(rec.issued_by, "operator")
        self.assertEqual(self.overrides.resolve("opp_1").statement,
                         "The Upwork contract was cancelled.")

    def test_blank_statement_is_refused(self):
        with self.assertRaises(OverrideError):
            self.overrides.issue("   ")

    # ── Auditability / append-only ──────────────────────────────────────────

    def test_revoke_is_append_only_and_deactivates(self):
        rec = self.overrides.issue("paid", subject_id="opp_1")
        self.overrides.revoke(rec.override_id, note="operator corrected himself")
        hist = self.overrides.history(rec.override_id)
        self.assertEqual([h.revision for h in hist], [0, 1])
        self.assertTrue(hist[0].active)          # original untouched
        self.assertFalse(hist[1].active)
        self.assertIsNone(self.overrides.resolve("opp_1"))

    def test_revoking_twice_is_refused(self):
        rec = self.overrides.issue("paid", subject_id="opp_1")
        self.overrides.revoke(rec.override_id)
        with self.assertRaises(OverrideError):
            self.overrides.revoke(rec.override_id)

    def test_amend_keeps_history(self):
        rec = self.overrides.issue("paid $10", subject_id="opp_1")
        self.overrides.amend(rec.override_id, "paid $25")
        hist = self.overrides.history(rec.override_id)
        self.assertEqual(hist[0].statement, "paid $10")
        self.assertEqual(hist[-1].statement, "paid $25")
        self.assertEqual(len(hist), 2)

    def test_records_are_immutable_and_serialisable(self):
        rec = self.overrides.issue("paid", subject_id="opp_1")
        with self.assertRaises(Exception):
            rec.active = False
        import json
        json.dumps(rec.to_dict())

    # ── Deterministic conflict resolution ───────────────────────────────────

    def test_subject_specific_override_beats_global(self):
        self.overrides.issue("Global: all payouts halted")
        self.overrides.issue("Opp 1 is settled", subject_id="opp_1")
        self.assertEqual(self.overrides.resolve("opp_1").statement,
                         "Opp 1 is settled")
        # a different subject falls back to the global statement
        self.assertEqual(self.overrides.resolve("opp_2").statement,
                         "Global: all payouts halted")

    def test_no_override_resolves_to_none(self):
        self.overrides.issue("Opp 1 is settled", subject_id="opp_1")
        self.assertIsNone(self.overrides.resolve("opp_9"))

    # ── Ledger integration ──────────────────────────────────────────────────

    def test_override_supersedes_conflicting_model_claim(self):
        entry = self.ledger.record_claim(_claim("client accepted", "opp_1"),
                                         SourceKind.LLM)
        self.overrides.issue("client did NOT accept", subject_id="opp_1")
        affected = self.overrides.apply_to_ledger(self.ledger)
        self.assertEqual(affected, [entry.claim_id])
        self.assertEqual(self.ledger.latest(entry.claim_id).status,
                         ClaimStatus.SUPERSEDED)

    def test_override_does_not_erase_tool_evidence(self):
        tool_entry = self.ledger.record_claim(_claim("api says paid", "opp_1"),
                                              SourceKind.TOOL)
        self.overrides.issue("not paid", subject_id="opp_1")
        self.overrides.apply_to_ledger(self.ledger)
        # authority does not delete evidence: the tool claim still stands
        self.assertEqual(self.ledger.latest(tool_entry.claim_id).status,
                         ClaimStatus.PROPOSED)

    def test_override_never_creates_verified_evidence(self):
        entry = self.ledger.record_claim(_claim("paid", "opp_1"), SourceKind.LLM)
        self.overrides.issue("I was paid", subject_id="opp_1")
        self.overrides.apply_to_ledger(self.ledger)
        # an override is authority, not evidence
        self.assertEqual(self.ledger.verified_claims(), [])
        self.assertNotEqual(self.ledger.latest(entry.claim_id).status,
                            ClaimStatus.VERIFIED)

    def test_override_does_not_silently_erase_evidence_verified_claim(self):
        # A model claim that deterministic evidence VERIFIED is not narration,
        # so an override must not auto-supersede it.
        entry = self.ledger.record_claim(_claim("api says paid", "opp_1"),
                                         SourceKind.LLM)
        self.ledger.attach_evidence(entry.claim_id, "ev_api_1",
                                    VerificationLevel.L3_EXTERNAL_SOURCE,
                                    method="authenticated_api_response")
        self.assertEqual(self.ledger.latest(entry.claim_id).status,
                         ClaimStatus.VERIFIED)
        self.overrides.issue("not paid", subject_id="opp_1")
        self.assertEqual(self.overrides.apply_to_ledger(self.ledger), [])
        self.assertEqual(self.ledger.latest(entry.claim_id).status,
                         ClaimStatus.VERIFIED)

    def test_override_leaves_other_subjects_alone(self):
        a = self.ledger.record_claim(_claim("a claim", "opp_1"), SourceKind.LLM)
        b = self.ledger.record_claim(_claim("b claim", "opp_2"), SourceKind.LLM)
        self.overrides.issue("override for opp_1", subject_id="opp_1")
        affected = self.overrides.apply_to_ledger(self.ledger)
        self.assertEqual(affected, [a.claim_id])
        self.assertEqual(self.ledger.latest(b.claim_id).status,
                         ClaimStatus.PROPOSED)

    def test_revoked_override_stops_applying(self):
        rec = self.overrides.issue("not paid", subject_id="opp_1")
        self.overrides.revoke(rec.override_id)
        entry = self.ledger.record_claim(_claim("paid", "opp_1"), SourceKind.LLM)
        self.assertEqual(self.overrides.apply_to_ledger(self.ledger), [])
        self.assertEqual(self.ledger.latest(entry.claim_id).status,
                         ClaimStatus.PROPOSED)


if __name__ == "__main__":
    unittest.main()
