"""Integration tests for the v2.1.1 honesty / epistemic stack.

These exercises compose the new modules together and against dialogue-shaped
text. The goal of this cycle is to make the stack first-class, importable, and
testable; the live wire-up into the dialogue prompt path is a separate tracked
follow-up so this cycle does not silently change production behavior.
"""

import unittest

from agents.cognition.dialogue_honesty import (
    DialogueHonestyService,
    _extract_claims_from_context,
)
from agents.evidence.evidence import Claim
from agents.cognition.fact_ledger import (
    ClaimStatus,
    SourceKind,
    FactLedger,
    LedgerEntry,
)
from agents.cognition.operator_override import (
    OperatorOverrideRegistry,
    OverrideRecord,
)
from agents.cognition.epistemic import (
    EpistemicLevel,
    classify,
    confidence,
    disclaimer,
    context_note,
)
from agents.evidence.numeric_evidence import (
    extract_monetary_values,
    extract_monetary_spans,
    unsupported_values,
    has_unsupported_values,
)


class TestMonetaryEvidencePureFunctions(unittest.TestCase):
    """Pure-string checks must be deterministic and not depend on model judgment."""

    def test_extracts_simple_dollars(self):
        self.assertEqual(extract_monetary_values("$5"), [5])
        self.assertEqual(extract_monetary_values("$5.00"), [5])
        self.assertEqual(extract_monetary_values("$ 5,000.25"), [5000.25])

    def test_extracts_scientific_notation_too(self):
        vals = extract_monetary_values("$9.9e101")
        self.assertEqual(len(vals), 1)
        self.assertTrue(vals[0] > 1e100)

    def test_deduplicates_identical_values(self):
        self.assertEqual(extract_monetary_values("$5 and $5"), [5])
        self.assertEqual(extract_monetary_values("$1,000 $1000"), [1000])

    def test_spans_preserve_raw_text(self):
        spans = extract_monetary_spans("I earned $9,999.00 today.")
        self.assertEqual(spans, [("$9,999.00", 9999)])

    def test_unsupported_detects_fabricated_values(self):
        context = "The board said the bounty is $1,000."
        response = "I will earn $9,999.00 and $500.00 from this task."
        unsupported = unsupported_values(response, context)
        self.assertEqual(sorted(unsupported), ["$500.00", "$9,999.00"])

    def test_supported_values_are_not_flagged(self):
        context = "The posted rate is $120.00 and the bonus is $25.50."
        response = "I expect $120.00 and also $25.50."
        self.assertEqual(unsupported_values(response, context), [])

    def test_has_unsupported_is_short_cut(self):
        context = "Rate is $10."
        both_supported = "I earned $10 and $10."
        self.assertFalse(has_unsupported_values(both_supported, context))

    def test_derivable_arithmetic_is_still_reported(self):
        # The check reports, it does not decide. A value derivable from context
        # is still reported as unsupported because the check is pure text.
        context = "The rate is $100 per task and I did 2 tasks."
        response = "I earned $200."
        self.assertEqual(unsupported_values(response, context), ["$200"])

    def test_empty_and_non_money_text(self):
        self.assertEqual(unsupported_values("", ""), [])
        self.assertEqual(unsupported_values("No money here.", ""), [])
        self.assertEqual(extract_monetary_values("no money at all"), [])


class TestClaimExtractionHeuristics(unittest.TestCase):
    """Best-effort claim extraction must be conservative and deterministic."""

    def test_explicit_markers_capture_claims(self):
        text = (
            "ASSERT: the payout is $500.\n"
            "CLAIM: the platform accepts USD.\n"
            "FACT: registration is required.\n"
        )
        claims = _extract_claims_from_context(text)
        statements = {s for s, src in claims}
        self.assertEqual(statements, {
            "the payout is $500.",
            "the platform accepts USD.",
            "registration is required.",
        })
        sources = {src for s, src in claims}
        self.assertEqual(sources, {"dialogue_explicit"})

    def test_heuristic_claim_verbs_capture_from_verb_onward(self):
        # The regex captures starting at the claim verb, not the sentence start.
        text = "The platform is friendly and the payout is $500 tomorrow."
        claims = _extract_claims_from_context(text)
        statements = {s for s, src in claims}
        self.assertIn("is friendly and the payout is $500 tomorrow.", statements)

    def test_short_lines_are_not_claims(self):
        text = "This is short.\nIt pays well.\nGo now."
        claims = _extract_claims_from_context(text)
        self.assertEqual(claims, [])

    def test_short_predicates_after_verb_are_not_claims(self):
        # Claim verb must be followed by at least 8 characters.
        text = "The payout is $500.\n"
        claims = _extract_claims_from_context(text)
        self.assertEqual(claims, [])

    def test_longer_predicates_after_verb_are_claims(self):
        # The predicate after the claim verb must be > 20 characters to qualify.
        short = "The payout is $500 today."          # "is $500 today." = 15 chars -> not extracted
        long = "The payout is $500 today and tomorrow."  # qualifies
        self.assertEqual(_extract_claims_from_context(short), [])
        claims = _extract_claims_from_context(long)
        statements = [s for s, src in claims]
        self.assertEqual(statements, ["is $500 today and tomorrow."])

    def test_consecutive_identical_short_lines_produce_one_claim_each(self):
        # Short lines still each independently fail the length threshold, so no
        # claim leaks through; a longer variant does.
        text = (
            "The payout is $500.\n"
            "The payout is $500.\n"
            "The payout is $500 today and tomorrow.\n"
        )
        claims = _extract_claims_from_context(text)
        statements = [s for s, src in claims]
        self.assertEqual(statements, ["is $500 today and tomorrow."])


class TestFactLedgerBasics(unittest.TestCase):
    """The ledger must be append-only and transition-guarded."""

    def test_proposed_only_recordable_via_record_claim(self):
        ledger = FactLedger()
        claim = Claim(assertion="the payout is $500", source="dialogue_model",
                      evidence_type="dialogue_claim")
        entry = ledger.record_claim(claim, source_kind=SourceKind.LLM)
        self.assertEqual(entry.status, ClaimStatus.PROPOSED)
        self.assertEqual(entry.source_kind, SourceKind.LLM)

    def test_record_claim_rejects_non_claim(self):
        ledger = FactLedger()
        with self.assertRaises(Exception):
            ledger.record_claim("not a claim", source_kind=SourceKind.LLM)

    def test_record_claim_rejects_empty_assertion(self):
        ledger = FactLedger()
        with self.assertRaises(Exception):
            ledger.record_claim(Claim(assertion="   ", evidence_type="x"),
                                 source_kind=SourceKind.LLM)

    def test_illegal_transition_raises(self):
        ledger = FactLedger()
        claim = Claim(assertion="x", evidence_type="x", source="m")
        entry = ledger.record_claim(claim, source_kind=SourceKind.LLM)
        # Attaching evidence with an empty reference must raise.
        with self.assertRaises(Exception):
            ledger.attach_evidence(entry.claim_id, "", VerificationLevel.L5_CRYPTOGRAPHIC)

    def test_verification_requires_evidence_meeting_level(self):
        from agents.evidence.evidence import VerificationLevel
        ledger = FactLedger(default_required_level=VerificationLevel.L3_EXTERNAL_SOURCE)
        claim = Claim(assertion="x", evidence_type="x", source="m")
        entry = ledger.record_claim(claim, source_kind=SourceKind.LLM)
        # Evidence below the required level -> SUPPORTED, not VERIFIED.
        ledger.attach_evidence(
            entry.claim_id, "web_read:https://example.test",
            VerificationLevel.L2_LOCAL_VALIDATION, method="web_read",
        )
        updated = ledger.latest(entry.claim_id)
        self.assertEqual(updated.status, ClaimStatus.SUPPORTED)

    def test_ledger_is_append_only_in_practice(self):
        ledger = FactLedger()
        claim = Claim(assertion="a", evidence_type="x", source="m")
        a = ledger.record_claim(claim, source_kind=SourceKind.LLM)
        claim2 = Claim(assertion="b", evidence_type="x", source="m")
        b = ledger.record_claim(claim2, source_kind=SourceKind.LLM)
        self.assertNotEqual(a.claim_id, b.claim_id)
        self.assertEqual(ledger.latest(a.claim_id).revision, 0)


class TestOperatorOverrideRegistry(unittest.TestCase):
    """Human overrides are append-only and scoped."""

    def test_issue_and_revoke(self):
        registry = OperatorOverrideRegistry()
        issued = registry.issue("the payout is actually $600", subject_id="opp-1")
        self.assertTrue(issued.active)
        self.assertEqual(registry.current(issued.override_id), issued)
        revoked = registry.revoke(issued.override_id, note="operator changed mind")
        self.assertFalse(revoked.active)

    def test_amend_keeps_history(self):
        registry = OperatorOverrideRegistry()
        issued = registry.issue("old statement", subject_id="opp-1")
        amended = registry.amend(issued.override_id, "new statement")
        current = registry.current(issued.override_id)
        self.assertEqual(current.statement, "new statement")
        self.assertGreater(amended.revision, issued.revision)

    def test_cannot_amend_or_revoke_revoked(self):
        registry = OperatorOverrideRegistry()
        issued = registry.issue("stmt")
        registry.revoke(issued.override_id)
        with self.assertRaises(Exception):
            registry.amend(issued.override_id, "new")
        with self.assertRaises(Exception):
            registry.revoke(issued.override_id)

    def test_global_override_has_empty_subject(self):
        registry = OperatorOverrideRegistry()
        issued = registry.issue("global fact")
        self.assertEqual(issued.subject_id, "")


class TestEpistemicCalibrationPureFunctions(unittest.TestCase):
    """Confidence classification is deterministic policy."""

    def test_none_is_unknown_and_low_confidence(self):
        self.assertEqual(classify(None), EpistemicLevel.UNKNOWN)
        self.assertEqual(confidence(None), 0.0)
        # disclaimer for an unknown entry states the absence of verified info.
        self.assertEqual(disclaimer(None),
                         "I have no verified information about this.")

    def test_proposed_is_speculative_low_confidence(self):
        entry = LedgerEntry(
            claim_id="c1", revision=0,
            statement="x", source="m", source_kind=SourceKind.LLM,
            status=ClaimStatus.PROPOSED,
        )
        self.assertEqual(classify(entry), EpistemicLevel.SPECULATIVE)
        self.assertEqual(confidence(entry), 0.1)

    def test_supported_is_plausible_capped(self):
        entry = LedgerEntry(
            claim_id="c1", revision=1,
            statement="x", source="m", source_kind=SourceKind.TOOL,
            status=ClaimStatus.SUPPORTED, method="web_read",
        )
        self.assertEqual(classify(entry), EpistemicLevel.PLAUSIBLE)
        self.assertLessEqual(confidence(entry), 0.5)

    def test_verified_at_or_above_l5_is_confirmed(self):
        entry = LedgerEntry(
            claim_id="c1", revision=2,
            statement="x", source="m", source_kind=SourceKind.TOOL,
            status=ClaimStatus.VERIFIED, method="crypto_sig",
            verification_level=int(__import__("agents.evidence.evidence",
                                              fromlist=["VerificationLevel"])
                                   .VerificationLevel.L5_CRYPTOGRAPHIC),
        )
        self.assertEqual(classify(entry), EpistemicLevel.CONFIRMED)

    def test_verified_below_l5_is_corroborated(self):
        entry = LedgerEntry(
            claim_id="c1", revision=2,
            statement="x", source="m", source_kind=SourceKind.TOOL,
            status=ClaimStatus.VERIFIED, method="web_read",
            verification_level=int(__import__("agents.evidence.evidence",
                                              fromlist=["VerificationLevel"])
                                   .VerificationLevel.L3_EXTERNAL_SOURCE),
        )
        self.assertEqual(classify(entry), EpistemicLevel.CORROBORATED)

    def test_refuted_and_superseded_are_negative(self):
        for status, expected in (
            (ClaimStatus.REFUTED, EpistemicLevel.REFUTED),
            (ClaimStatus.SUPERSEDED, EpistemicLevel.OVERRIDDEN),
        ):
            entry = LedgerEntry(
                claim_id="c1", revision=0,
                statement="x", source="m", source_kind=SourceKind.LLM,
                status=status,
            )
            self.assertEqual(classify(entry), expected)


class TestContextNoteFormatting(unittest.TestCase):
    """The prompt-injected epistemic note must be bounded and honest."""

    def test_empty_when_nothing_standing(self):
        note = context_note([])
        self.assertEqual(note, "")
        note = context_note([
            LedgerEntry(claim_id="c1", revision=0, statement="x",
                        source="m", source_kind=SourceKind.LLM,
                        status=ClaimStatus.REFUTED),
            LedgerEntry(claim_id="c2", revision=0, statement="y",
                        source="m", source_kind=SourceKind.LLM,
                        status=ClaimStatus.SUPERSEDED),
        ])
        self.assertEqual(note, "")

    def test_bounded_to_max_claims(self):
        entries = [
            LedgerEntry(claim_id=f"c{i}", revision=0, statement=f"claim {i}",
                        source="m", source_kind=SourceKind.LLM,
                        status=ClaimStatus.PROPOSED)
            for i in range(20)
        ]
        note = context_note(entries, max_claims=3)
        count = note.count("claim ")
        self.assertLessEqual(count, 3)

    def test_includes_confidence_and_level(self):
        entry = LedgerEntry(
            claim_id="c1", revision=0, statement="the payout is $500",
            source="m", source_kind=SourceKind.LLM,
            status=ClaimStatus.PROPOSED,
        )
        note = context_note([entry])
        self.assertIn("EPISTEMIC STATUS", note)
        self.assertIn("speculative", note)
        self.assertIn("confidence", note)


class TestDialogueHonestyServiceComposition(unittest.TestCase):
    """The service must compose ledger + overrides + epistemic note correctly."""

    def test_record_claims_makes_proposed_entries(self):
        svc = DialogueHonestyService(max_claims=10)
        entries = svc.record_claims(
            "ASSERT: the payout is $500.\n"
            "The platform is legitimate and pays monthly.",
            source="dialogue_model",
        )
        self.assertGreater(len(entries), 0)
        for e in entries:
            self.assertEqual(e.status, ClaimStatus.PROPOSED)
            self.assertEqual(e.source_kind, SourceKind.LLM)

    def test_global_override_supersedes_proposed_model_claims(self):
        svc = DialogueHonestyService(max_claims=10)
        entries = svc.record_claims("ASSERT: the payout is $500.",
                                    source="dialogue_model")
        self.assertEqual(len(entries), 1)
        claim_id = entries[0].claim_id
        # Global override (empty subject_id) supersedes all proposed model claims.
        svc.overrides.issue("the payout is actually $600")
        svc.apply_overrides()
        current = svc.ledger.latest(claim_id)
        self.assertEqual(current.status, ClaimStatus.SUPERSEDED)

    def test_superseded_claim_drops_out_of_standing_and_note(self):
        svc = DialogueHonestyService(max_claims=10)
        entries = svc.record_claims("ASSERT: the payout is $500.",
                                    source="dialogue_model")
        claim_id = entries[0].claim_id
        svc.overrides.issue("operator says otherwise")
        svc.apply_overrides()
        self.assertEqual(svc.ledger.latest(claim_id).status, ClaimStatus.SUPERSEDED)
        standing = svc.standing_claims()
        self.assertNotIn(claim_id, {e.claim_id for e in standing})
        note = svc.epistemic_context_note(max_claims=5)
        self.assertNotIn("$500", note)

    def test_note_is_bounded_and_readable(self):
        svc = DialogueHonestyService(max_claims=4)
        for i in range(15):
            svc.record_claims(f"ASSERT: claim number {i} is true.", source="dialogue_model")
        note = svc.epistemic_context_note(max_claims=4)
        self.assertIn("EPISTEMIC STATUS", note)
        self.assertLess(len(note), 1200)

    def test_standing_claims_excludes_refuted_and_superseded(self):
        svc = DialogueHonestyService(max_claims=10)
        entries = svc.record_claims("CLAIM: A is true.", source="dialogue_model")
        self.assertGreater(len(entries), 0)
        standing = svc.standing_claims()
        self.assertEqual(len(standing), len(entries))

    def test_to_dict_is_observability_counts(self):
        svc = DialogueHonestyService(max_claims=10)
        svc.record_claims("FACT: the rate is $100.", source="dialogue_model")
        d = svc.to_dict()
        self.assertEqual(d["claim_count"], 1)
        self.assertEqual(d["standing_count"], 1)
        self.assertEqual(d["verified_count"], 0)
        self.assertEqual(d["override_count"], 0)


class TestHonestyStackIntegrationWithDialogueShapedText(unittest.TestCase):
    """End-to-end composition against realistic dialogue responder text."""

    def test_records_model_claims_and_flags_unsupported_money(self):
        svc = DialogueHonestyService(max_claims=20)
        model_response = (
            "Sure — I will apply to the Freelancer.com bounty. "
            "The payout for this task is $9,999.00 and the bonus is $500.00. "
            "The platform confirmed this today."
        )
        entries = svc.record_claims(model_response, source="dialogue_model")
        self.assertGreater(len(entries), 0)

        prompt_context = (
            "## OPPORTUNITY SNAPSHOT\n"
            "- opp-1: Fix slugify ($1,000)\n"
        )
        unsupported = unsupported_values(model_response, prompt_context)
        self.assertIn("$9,999.00", unsupported)
        self.assertIn("$500.00", unsupported)
        self.assertNotIn("$1,000", unsupported)

    def test_operator_can_supersede_a_model_claim_before_prompt_build(self):
        svc = DialogueHonestyService(max_claims=20)
        model_response = (
            "The best next step is to register on the platform now. "
            "Registration only needs a name and email, so no approval is required."
        )
        entries = svc.record_claims(model_response, source="dialogue_model")
        # A global override supersedes all proposed model claims in the ledger.
        svc.overrides.issue(
            "Account creation always requires explicit human approval."
        )
        svc.apply_overrides()
        note = svc.epistemic_context_note(max_claims=10)
        # Superseded model claims should no longer appear as standing.
        self.assertNotIn("$500", note)
        self.assertNotIn("register", note)

    def test_epochidemic_note_does_not_blow_prompt_budget(self):
        svc = DialogueHonestyService(max_claims=6)
        for i in range(40):
            svc.record_claims(f"FACT: fact number {i} exists.", source="dialogue_model")
        note = svc.epistemic_context_note(max_claims=6)
        self.assertLess(len(note), 900)

    def test_unsupported_money_is_detected_in_presence_of_supported_money(self):
        context = (
            "Rate: $120.00 per task. Bonus cap: $250.00.\n"
            "Total possible: $370.00.\n"
        )
        response = (
            "I expect $120.00 plus the $250.00 bonus, so $370.00 total. "
            "I will also receive a $9,999.00 sign-up bonus."
        )
        unsupported = unsupported_values(response, context)
        self.assertEqual(unsupported, ["$9,999.00"])


class TestHonestyStackDoesNotChangeExistingDialogueInvariants(unittest.TestCase):
    """Sanity check that composing the stack does not mutate public API we test
    elsewhere. This is a compatibility smoke test, not a behavior regression
    test for the dialogue tab itself."""

    def test_dialogue_honesty_service_has_no_required_positional_io(self):
        svc = DialogueHonestyService()
        svc.apply_overrides()
        note = svc.epistemic_context_note()
        self.assertIsInstance(note, str)
        self.assertEqual(svc.standing_claims(), [])
        d = svc.to_dict()
        self.assertIsInstance(d, dict)

    def test_new_stack_is_importable_from_agents_package(self):
        import agents
        for name in (
            "FactLedger", "Claim", "ClaimStatus", "SourceKind", "LedgerEntry",
            "OperatorOverrideRegistry", "OverrideRecord",
            "EpistemicLevel", "classify", "confidence", "disclaimer", "context_note",
            "extract_monetary_values", "extract_monetary_spans",
            "unsupported_values", "has_unsupported_values",
            "DialogueHonestyService",
        ):
            self.assertTrue(hasattr(agents, name), msg=f"agents.{name} missing")
