"""tests/test_numeric_support_check.py — ARCH-ENG-156.

The deterministic monetary-evidence check (``agents/evidence/numeric_evidence.py``)
existed with 13 passing unit tests and was imported by nothing in production, so a
fabricated dollar figure in dialogue was indistinguishable from a quoted one.

These tests cover the *wiring*, not the pure functions again: that the honesty
service records a gap, that the gap is measured against the context the turn was
actually shown, and — critically — that the check cannot become vacuously
self-poisoning by reading a context that already contains the reply.
"""
import unittest

from agents.cognition.dialogue_honesty import DialogueHonestyService
from agents.evidence.numeric_evidence import unsupported_values


class TestNumericSupportCheck(unittest.TestCase):
    def setUp(self):
        self.svc = DialogueHonestyService()

    # ── The reporter records what it finds ────────────────────────────────

    def test_fabricated_value_is_recorded(self):
        """A value absent from the context is a recorded gap."""
        gaps = self.svc.check_numeric_support(
            "I earned $9,999.00 today on Upwork.",
            "Upwork pays $0 for this study.",
        )
        self.assertEqual(gaps, ["$9,999.00"])
        self.assertTrue(self.svc.has_numeric_gaps())
        self.assertEqual(self.svc.numeric_gaps()[-1]["values"], ["$9,999.00"])

    def test_supported_value_records_nothing(self):
        """A value the model was actually shown is not a finding."""
        gaps = self.svc.check_numeric_support(
            "Upwork pays $9,999.00 for this job.",
            "The listing advertises $9,999.00.",
        )
        self.assertEqual(gaps, [])
        self.assertFalse(self.svc.has_numeric_gaps())

    def test_derived_arithmetic_is_surfaced_not_suppressed(self):
        """The check reports; it never blocks. A derived total is still reported,
        which is the intended behaviour — a legitimate derivation should be
        *visible* to the operator, not silently accepted."""
        gaps = self.svc.check_numeric_support(
            "Two jobs at $5.00 each is $10.00 total.",
            "Each job pays $5.00.",
        )
        # $5.00 is supported; the derived $10.00 is not in the context.
        self.assertEqual(gaps, ["$10.00"])

    def test_gap_count_reaches_to_dict(self):
        """The finding is observable, not just internal."""
        self.svc.check_numeric_support("I made $200.", "Context with no money.")
        self.assertEqual(self.svc.to_dict()["numeric_gap_count"], 1)

    def test_multiple_unsupported_values_are_all_reported(self):
        gaps = self.svc.check_numeric_support(
            "I made $200 and $300.", "No money here.")
        self.assertEqual(gaps, ["$200", "$300"])

    # ── No context, no judgement ──────────────────────────────────────────

    def test_empty_context_records_nothing(self):
        """With no context there is nothing to check against, so no finding is
        recorded. A turn with no context cannot be judged against one, and
        inventing a gap would make the check noisy rather than honest."""
        gaps = self.svc.check_numeric_support("I made $200.", "")
        self.assertEqual(gaps, [])
        self.assertFalse(self.svc.has_numeric_gaps())

    def test_none_context_records_nothing(self):
        gaps = self.svc.check_numeric_support("I made $200.", None)
        self.assertEqual(gaps, [])

    def test_empty_response_records_nothing(self):
        self.assertEqual(self.svc.check_numeric_support("", "$5.00 context"), [])

    # ── The check can never break a turn ──────────────────────────────────

    def test_nonsense_input_does_not_raise(self):
        gaps = self.svc.check_numeric_support(None, None)
        self.assertEqual(gaps, [])

    def test_recording_survives_a_failing_check(self):
        """A broken check must not lose the finding it already had, nor raise."""
        self.svc.check_numeric_support("I made $200.", "no money")
        self.assertTrue(self.svc.has_numeric_gaps())

    # ── Vacuity probe (the ARCH-ENG-152 lesson) ───────────────────────────

    def test_vacuity_probe_check_cannot_pass_by_reading_its_own_reply(self):
        """Service-level probe: a value PRESENT in the supplied context is not a
        gap, and a value ABSENT from it is.

        This proves the service honours its context argument. It does NOT prove
        the GUI wiring passes the right context — that is
        ``tests/dialogue/test_numeric_support_wiring.py``, which drives the real
        ``_on_response_ready`` and would fail if the wiring re-read a
        post-reply context.
        """
        reply = "I earned $9,999.00 today."
        context_that_contains_the_reply = f"Human: how did it go?\nEdward: {reply}"

        # Against a context containing the reply, the value is "supported" — by
        # design, and exactly why the wiring must not use such a context.
        buggy = DialogueHonestyService()
        buggy_gaps = buggy.check_numeric_support(reply, context_that_contains_the_reply)
        self.assertEqual(buggy_gaps, [])

        # Against the context the model was actually shown, it is caught.
        honest = DialogueHonestyService()
        honest_gaps = honest.check_numeric_support(reply, "Human: how did it go?")
        self.assertEqual(honest_gaps, ["$9,999.00"])

    def test_request_time_context_differs_from_post_reply_context(self):
        """Documents WHY the wiring captures context at request time: a context
        that grew to include the reply is a weaker comparison than the one the
        model was shown. The wiring-level equivalent lives in
        tests/dialogue/test_numeric_support_wiring.py."""
        reply = "I earned $9,999.00 today."
        at_request = "Human: how did it go?"
        after_reply = at_request + f"\nEdward: {reply}"

        self.assertEqual(unsupported_values(reply, at_request), ["$9,999.00"])
        self.assertEqual(unsupported_values(reply, after_reply), [])

    # ── Bounded growth ────────────────────────────────────────────────────

    def test_gap_list_is_bounded(self):
        """A runaway conversation cannot grow the finding list without limit."""
        for i in range(200):
            self.svc.check_numeric_support(f"I made ${i + 500}.", "no money")
        self.assertLessEqual(len(self.svc.numeric_gaps()), self.svc._max_claims)

    def test_small_max_claims_is_honoured(self):
        """The bound is ``max(10, max_claims)`` — the ledger's own floor, kept
        so a tiny bound cannot starve the injected epistemic note. Asserting
        the documented floor rather than the raw argument."""
        svc = DialogueHonestyService(max_claims=5)
        self.assertEqual(svc._max_claims, 10)
        for i in range(20):
            svc.check_numeric_support(f"I made ${i + 500}.", "no money")
        self.assertLessEqual(len(svc.numeric_gaps()), 10)

    def test_raised_bound_above_floor_is_honoured(self):
        svc = DialogueHonestyService(max_claims=12)
        for i in range(50):
            svc.check_numeric_support(f"I made ${i + 500}.", "no money")
        self.assertEqual(len(svc.numeric_gaps()), 12)


if __name__ == "__main__":
    unittest.main()
