"""ARCH-ENG-159 — the lifecycle gate still honoured the laundering shape.

ARCH-ENG-064 fixed an inverted-trust bug in
`OpportunityLifecycleTracker._is_verified_evidence`: it used to read
`ev.get("verified")`, but `Evidence.to_dict()` emits `status` /
`verification_level` / `verification_method` and NEVER a `verified` key. The
consequence was that a genuine L5 on-chain payout reported
`verified_revenue_usd() == 0.0` and appeared in `unverified_payouts()`, while a
hand-written dict `{"verified": True}` booked its full `expected_usd` as
revenue.

The fix added the status+level policy, but kept a legacy branch as a
compatibility affordance:

    status = str(ev.get("status", "") or "").upper()
    if not status:
        # Legacy dict shape: honour the explicit boolean only.
        return bool(ev.get("verified"))

ARCH-ENG-121 then hit exactly that branch from the other side.
`_tool_record_payment` built a hand-written dict

    {"verified": True, "method": "manual", "reference": ... or "agent-recorded"}

with NO `status` and NO `verification_level`, so an agent-supplied amount booked
as VERIFIED revenue — a bypass of the L3 external-source floor every other paid
path enforces. ARCH-ENG-121 fixed it at the CALLER: `_is_approved` now requires a
real `Evidence` object, and the handler refuses rather than defaulting to the
agent-authored string "agent-recorded".

ARCH-ENG-121 decided the policy was FAIL CLOSED — "an approval authorizes an
ACTION, not an AMOUNT and not a VERIFICATION" — and its docstring notes the
lifecycle function "honours that legacy shape". But the defence sat ONLY at the
caller. The GATE itself still returned True for the laundering dict, so any
other producer of that shape booked straight into `verified_revenue_usd()`.

This closes the gate. One trust rule per question: the gate itself now requires
an affirmative status AND `verification_level >= L3_EXTERNAL_SOURCE`, matching
`handlers._is_approved`.

This CANNOT reject a genuine record: `Evidence.to_dict()` ALWAYS emits `status`
and `verification_level`, so every dict produced by the evidence model carries
its own credentials and takes the policy path. The removed branch was reachable
only by a hand-built dict — which is the laundering shape, not a legacy encoding
of anything real.

And a state that fails is not lost: it keeps `status == "paid"` and still appears
in `unverified_payouts()`, so the operator sees the discrepancy instead of it
being silently booked.
"""

import unittest

from agents.earning.opportunity_lifecycle import OpportunityLifecycleTracker
from agents.evidence.evidence import (
    Evidence, EvidenceStatus, VerificationLevel, VerificationResult,
)

_is_verified = OpportunityLifecycleTracker._is_verified_evidence


class TestLegacyVerifiedBooleanIsRefused(unittest.TestCase):
    """ARCH-ENG-159 — the exact shape the branch used to honour."""

    def test_bare_verified_true_is_refused(self):
        """The laundering shape. This is the regression."""
        self.assertFalse(_is_verified({"verified": True}),
                         "a hand-written {'verified': True} still books revenue")

    def test_verified_true_with_a_full_expected_amount_is_refused(self):
        """Realistic shape: the amount is what makes the laundering valuable."""
        ev = {"verified": True, "amount": 9999.0, "method": "manual",
              "reference": "agent-recorded"}
        self.assertFalse(_is_verified(ev))

    def test_verified_true_with_status_but_no_level_is_refused(self):
        """ARCH-ENG-121 option (a) in reverse: a status alone is not enough."""
        self.assertFalse(_is_verified({"verified": True, "status": "VERIFIED"}))

    def test_verified_false_is_refused(self):
        self.assertFalse(_is_verified({"verified": False}))

    def test_empty_and_none_are_refused(self):
        self.assertFalse(_is_verified(None))
        self.assertFalse(_is_verified({}))
        self.assertFalse(_is_verified(""))


class TestGenuineEvidenceStillBooks(unittest.TestCase):
    """ARCH-ENG-159 — the floor is a floor, not a wall."""

    def test_l5_onchain_receipt_is_accepted(self):
        """The case ARCH-ENG-064 broke: a real L5 payout must book."""
        ev = {"status": "VERIFIED", "verification_level": 5,
              "verification_method": "blockchain_balance_delta", "amount": 750.0}
        self.assertTrue(_is_verified(ev),
                        "a genuine L5 on-chain payout is no longer counted — "
                        "this is the inverted-trust bug ARCH-ENG-064 fixed, "
                        "returning in the opposite direction")

    def test_l3_external_api_is_accepted(self):
        ev = {"status": "VERIFIED", "verification_level": 3,
              "verification_method": "authenticated_api_response", "amount": 500.0}
        self.assertTrue(_is_verified(ev))

    def test_partially_verified_at_l3_is_accepted(self):
        ev = {"status": "PARTIALLY_VERIFIED", "verification_level": 3}
        self.assertTrue(_is_verified(ev))

    def test_l2_local_validation_is_refused(self):
        """Below the external-source floor is not independent proof."""
        ev = {"status": "VERIFIED", "verification_level": 2,
              "verification_method": "local_validation"}
        self.assertFalse(_is_verified(ev))

    def test_non_affirmative_status_is_refused(self):
        for status in ("REJECTED", "CONFLICTED", "EXPIRED", "UNVERIFIED", "PENDING"):
            with self.subTest(status=status):
                self.assertFalse(
                    _is_verified({"status": status, "verification_level": 5}))

    def test_status_level_must_agree(self):
        """A high level does not rescue a non-affirmative status."""
        self.assertFalse(_is_verified({"status": "REJECTED", "verification_level": 5}))

    def test_unparseable_level_is_refused(self):
        self.assertFalse(_is_verified({"status": "VERIFIED",
                                       "verification_level": "not-a-number"}))

    def test_real_evidence_object_to_dict_is_accepted(self):
        """End to end: the model the app actually stores must pass.

        `Evidence.to_dict()` always emits status and verification_level, so a
        genuinely verified record can never be rejected by the stricter gate.
        """
        ev = Evidence.create(
            evidence_type="payment_gross", subject_type="opportunity",
            subject_id="opp-1", source="upwork_api", amount=500.0,
        ).verify(VerificationResult(
            status=EvidenceStatus.VERIFIED,
            method="authenticated_api_response",
            level=VerificationLevel.L4_INDEPENDENT_VERIFICATION,
            actor="test",
        ))
        self.assertTrue(_is_verified(ev.to_dict()))

    def test_real_l1_evidence_object_is_refused(self):
        """An `Evidence` carrying L1 must not book, same as a dict would not."""
        ev = Evidence.create(
            evidence_type="manual_attestation", subject_type="opportunity",
            subject_id="opp-2", source="operator", amount=500.0,
        ).verify(VerificationResult(
            status=EvidenceStatus.VERIFIED, method="manual_attestation",
            level=VerificationLevel.L1_SELF_REPORTED, actor="operator",
        ))
        self.assertFalse(_is_verified(ev.to_dict()),
                         "L1 manual attestation booked as verified revenue")


class TestTheGateAgreesWithTheHandler(unittest.TestCase):
    """ARCH-ENG-159 — one trust rule per question, in each trust context.

    Two gates answer "is this proof of payment?", and they run in different
    contexts:

      * `handlers._evidence_meets_l3` checks a LIVE tool argument, so it can
        demand a real `Evidence` OBJECT. ARCH-ENG-121: a hand-built dict "is
        itself agent-supplied, so accepting one would re-open the laundering
        path (the agent can write {"status": "VERIFIED", "verification_level":
        5} out of thin air)".

      * `OpportunityLifecycleTracker._is_verified_evidence` checks a PERSISTED
        record, which after a restart is necessarily a dict. It cannot demand an
        object, so it demands the dict carry its own credentials.

    The two therefore differ on exactly one shape: a fabricated dict carrying a
    fabricated status and level. That divergence is real and is asserted here
    rather than papered over — what matters is that the LAUNDERING shapes are
    refused by BOTH, and that the divergence is bounded.
    """

    LAUNDERING = (
        {"verified": True},
        {"verified": True, "amount": 9999.0, "method": "manual"},
        {"verified": False},
        {"status": "VERIFIED"},
        {"status": "REJECTED", "verification_level": 5},
        {"status": "VERIFIED", "verification_level": 2},
        {},
        None,
    )

    def test_both_refuse_every_laundering_shape(self):
        from agents.safety.handlers import _evidence_meets_l3

        for ev in self.LAUNDERING:
            with self.subTest(ev=ev):
                self.assertFalse(_is_verified(ev),
                                 f"the lifecycle gate accepted a laundering "
                                 f"shape: {ev}")
                self.assertFalse(_evidence_meets_l3(ev),
                                 f"the payment handler accepted a laundering "
                                 f"shape: {ev}")

    def test_a_genuine_l3_dict_is_accepted_by_the_persisted_record_gate(self):
        """After persistence a genuine L5 record IS a dict — it must still book.

        This is why the lifecycle gate cannot simply demand an object: after a
        restart `state.verification` is loaded from JSON.
        """
        genuine = {"status": "VERIFIED", "verification_level": 5,
                   "verification_method": "blockchain_balance_delta"}
        self.assertTrue(_is_verified(genuine))

    def test_the_context_divergence_is_documented_and_bounded(self):
        """A dict with a FABRICATED status+level is the one divergent shape.

        Asserted explicitly so that (a) the divergence cannot silently widen,
        and (b) if someone later closes it properly, this test tells them to
        update the ARCH-ENG-121 docstring rather than assume it was always so.
        """
        from agents.safety.handlers import _evidence_meets_l3

        fabricated = {"status": "VERIFIED", "verification_level": 5}
        # The handler refuses it: a dict is agent-supplied.
        self.assertFalse(_evidence_meets_l3(fabricated))
        # The persisted-record gate accepts it on its stated credentials.
        # Mitigating fact: `mark_paid_verified` no longer routes a plain dict
        # through the paid path at all — the legacy branch now applies this same
        # floor — and every production caller passes a real `Evidence`.
        self.assertTrue(_is_verified(fabricated))
        for ev in self.LAUNDERING:
            if ev and isinstance(ev, dict) and ev.get("status") == "VERIFIED" \
                    and ev.get("verification_level") is not None:
                continue
            with self.subTest(ev=ev):
                self.assertFalse(_is_verified(ev) and not _evidence_meets_l3(ev),
                                 f"the divergence widened beyond the fabricated "
                                 f"status+level shape: {ev}")


class TestMarkPaidVerifiedRefusesTheLegacyDict(unittest.TestCase):
    """ARCH-ENG-159 — the transition itself, not only the revenue gate.

    The gate fix alone would have been half a fix. `mark_paid_verified` had its
    own legacy branch that read `evidence.get("verified")` and, on a truthy
    value, called `_mark_paid` DIRECTLY — so a state reached `status == "paid"`
    with `last_amount` set on nothing but a self-asserted boolean. With the gate
    closed, `verified_revenue_usd()` would return 0 for such a state, but the
    state would still read PAID everywhere else — a split truth on exactly the
    invariant `Agent.md` declares.

    The branch now applies the same L3 floor. A `VerificationEvidence`
    dataclass is converted to a real `Evidence` before this point, so the only
    things reaching it are plain dicts — agent-supplied by the ARCH-ENG-121
    argument.
    """

    def setUp(self):
        self.tracker = OpportunityLifecycleTracker()   # NO evidence store
        self.tracker.start(_opp("opp-launder"))

    def _state(self, oid="opp-launder"):
        """The lifecycle record. `status` is separate from `current_stage`.

        `_append(..., "submitted", ...)` records a HISTORY event and moves
        `current_stage`; it does not set `status`, which only `_mark_paid` does.
        So the refusal invariant is asserted on `status != "paid"`.
        """
        return self.tracker._states[oid]

    def test_bare_verified_true_dict_does_not_mark_paid(self):
        state = self.tracker.mark_paid_verified(
            "opp-launder", amount=9999.0,
            evidence={"verified": True, "method": "manual",
                      "summary": "agent says so"})
        self.assertNotEqual(state.status, "paid",
                            "a hand-written {'verified': True} marked the "
                            "lifecycle paid")
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)

    def test_it_does_not_book_revenue_either(self):
        self.tracker.mark_paid_verified(
            "opp-launder", amount=9999.0, evidence={"verified": True})
        self.assertEqual(self.tracker.verified_revenue_usd(), 0.0)
        self.assertEqual(self._state().last_amount, 0.0,
                         "last_amount was credited on a self-asserted boolean")

    def test_a_genuine_l5_dict_still_marks_paid(self):
        """The floor is a floor: a real externally-verified record still books."""
        state = self.tracker.mark_paid_verified(
            "opp-launder", amount=750.0,
            evidence={"status": "VERIFIED", "verification_level": 5,
                      "verification_method": "blockchain_balance_delta"})
        self.assertEqual(state.status, "paid")
        self.assertEqual(self.tracker.verified_revenue_usd(), 750.0)

    def test_l1_manual_dict_does_not_mark_paid(self):
        state = self.tracker.mark_paid_verified(
            "opp-launder", amount=500.0,
            evidence={"status": "VERIFIED", "verification_level": 1,
                      "verification_method": "manual_attestation"})
        self.assertNotEqual(state.status, "paid",
                            "an L1 manual attestation marked the lifecycle paid")

    def test_a_refused_transition_is_recorded_in_the_audit_trail(self):
        """A refusal must be explainable, not silent."""
        self.tracker.mark_paid_verified(
            "opp-launder", amount=9999.0, evidence={"verified": True})
        state = self._state()
        notes = " ".join(e.note for e in state.history)
        self.assertIn("NOT verified", notes,
                      f"the refusal was not recorded: {notes}")

    def test_the_refusal_reason_names_the_floor(self):
        """The operator is told WHY, not just that it failed."""
        self.tracker.mark_paid_verified(
            "opp-launder", amount=9999.0, evidence={"verified": True})
        notes = " ".join(e.note for e in self._state().history)
        self.assertIn("L3", notes,
                      f"the refusal did not name the floor it failed: {notes}")


def _opp(oid):
    class _O:
        pass
    o = _O()
    o.id = oid
    o.title = f"task {oid}"
    o.estimated_usd_value = 100.0
    o.deadline = 0.0
    return o


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-159 — assert the gate actually discriminates.

    A gate that returned False for everything would pass every "is refused"
    assertion above. These confirm it returns True for a genuine record, so the
    refusals are discrimination rather than a blanket deny.
    """

    def test_probe_confirms_the_gate_discriminates(self):
        genuine = {"status": "VERIFIED", "verification_level": 5}
        laundering = {"verified": True}
        self.assertTrue(_is_verified(genuine))
        self.assertFalse(_is_verified(laundering))
        self.assertNotEqual(_is_verified(genuine), _is_verified(laundering))


if __name__ == "__main__":
    unittest.main()