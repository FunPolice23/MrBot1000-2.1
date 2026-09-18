"""Tests for the deterministic monetary-evidence check.

The check exists because a model may only legitimately cite a value it was shown.
A number in the reply that appears nowhere in the supplied context is unsupported.
These tests also pin the correct attribution: a value that came from the board is
NOT flagged (the pipeline is at fault there), while a value the model invented IS.
"""
import unittest

from agents.numeric_evidence import (
    extract_monetary_values,
    has_unsupported_values,
    unsupported_values,
)

# Real strings from the observed log.
_BOARD = (
    "Expected Value: $9,828,150.00\n"
    "Real Reward $9,828,150\n"
    "Expected Value: $560.00\n"
    "expected value of $1.000e+82\n"
    "hourly rates ranging from $0.10 to $1,800.00\n"
)


class TestNumericEvidence(unittest.TestCase):
    def test_value_quoted_from_context_is_supported(self):
        response = "The bounty pays $9,828,150.00 and the airdrop pays $560.00."
        self.assertEqual(unsupported_values(response, _BOARD), [])

    def test_scientific_notation_from_context_is_supported(self):
        response = "One listing claims $1.000e+82 which is impossible."
        self.assertEqual(unsupported_values(response, _BOARD), [])

    def test_comma_form_is_normalised_against_plain_form(self):
        # Context carries $9,828,150; response cites $9828150.00 -> same value.
        self.assertEqual(
            unsupported_values("It pays $9828150.00.", "Reward $9,828,150"), [])

    def test_invented_value_is_flagged(self):
        response = "I can earn $4,500 per week from this."
        self.assertEqual(unsupported_values(response, _BOARD), ["$4,500"])

    def test_mixed_response_flags_only_the_invented_value(self):
        response = ("The bounty pays $9,828,150.00, and I estimate "
                    "$7,000.00 in extras.")
        self.assertEqual(unsupported_values(response, _BOARD), ["$7,000.00"])

    def test_empty_context_flags_every_cited_value(self):
        response = "It pays $10 and $20."
        self.assertEqual(unsupported_values(response, ""), ["$10", "$20"])

    def test_no_monetary_values_produces_no_findings(self):
        self.assertEqual(unsupported_values("Nothing to report here.", _BOARD), [])

    def test_zero_is_handled(self):
        self.assertEqual(
            unsupported_values("The payout is $0.00.", "Payout $0.00"), [])

    def test_duplicate_citations_reported_once(self):
        response = "It pays $7,000 and again $7,000."
        self.assertEqual(unsupported_values(response, _BOARD), ["$7,000"])

    def test_has_unsupported_values_helper(self):
        self.assertTrue(has_unsupported_values("I earn $4,500.", _BOARD))
        self.assertFalse(has_unsupported_values("It pays $560.00.", _BOARD))

    def test_extract_deduplicates_and_keeps_order(self):
        values = extract_monetary_values("$5 then $10 then $5")
        self.assertEqual([str(v) for v in values], ["5", "10"])

    def test_values_beyond_context_precision_do_not_collapse(self):
        """Regression: normalize() rounded to 28 sig digits and merged distinct values.

        10**81 and 10**81 + 1 are different numbers; the old code normalised both
        to 1E+81 so the second was reported as supported. This is the magnitude
        class of the incident value, so it must not regress.
        """
        a = "1" + "0" * 81
        b = "1" + "0" * 80 + "1"
        self.assertNotEqual(a, b)
        self.assertEqual(unsupported_values(f"worth ${b}", f"ev=${a}"), [f"${b}"])

    def test_scientific_values_beyond_precision_stay_distinct(self):
        a = "1.00000000000000000000000000001e+82"
        b = "1.00000000000000000000000000002e+82"
        self.assertEqual(
            unsupported_values(f"worth ${b}", f"ev=${a}"), [f"${b}"])

    def test_equal_values_in_different_forms_still_match(self):
        """Exact comparison must still treat 1.0 and 1.00 as the same value."""
        self.assertEqual(unsupported_values("pays $1.00", "pays $1.0"), [])
        self.assertEqual(
            unsupported_values("pays $1e+81", "pays $" + "1" + "0" * 81), [])

    def test_unparseable_tokens_are_ignored(self):
        self.assertEqual(unsupported_values("$ not a number $x", _BOARD), [])


if __name__ == "__main__":
    unittest.main()
