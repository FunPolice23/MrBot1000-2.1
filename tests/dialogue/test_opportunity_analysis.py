"""A3 — analyse_candidate digest tests.

Each test targets BEHAVIOUR (a blocker is / is not flagged, a requirement is /
is not captured, a viability tier is chosen) so it would FAIL if the parsing
were removed or weakened. Pure helper: no network, no LLM, no filesystem.
"""
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

from agents.dialogue.opportunity_analysis import analyse_candidate


def _opp(**kw):
    base = {
        "title": "Write a 500-word blog post",
        "description": "Remote writing gig. Paid via PayPal.",
        "location_requirements": "",
        "eligibility_requirements": "",
        "payment_type": "usd",
    }
    base.update(kw)
    return base


class AnalyseCandidateTest(unittest.TestCase):
    # ── the two cases the todo names ──────────────────────────────────────
    def test_http_402_is_a_blocker(self):
        res = analyse_candidate(_opp(http_status=402))
        self.assertEqual(res["viability"], "blocked")
        self.assertTrue(res["blockers"], "a 402 candidate must flag a blocker")
        self.assertTrue(any("402" in b for b in res["blockers"]))

    def test_paywall_text_is_a_blocker(self):
        res = analyse_candidate(_opp(
            description="Great gig. Subscribe to view the full requirements."))
        self.assertEqual(res["viability"], "blocked")
        self.assertTrue(res["blockers"])

    def test_location_restricted_gig_captures_requirement(self):
        res = analyse_candidate(_opp(
            description="Remote writing gig, US only. Paid via PayPal."))
        locs = [r for r in res["requirements"] if r["type"] == "location"]
        self.assertTrue(locs, "a location restriction must be captured")
        self.assertFalse(res["blockers"])
        # A location restriction is a hard requirement -> needs_review, not viable.
        self.assertEqual(res["viability"], "needs_review")

    def test_structured_location_field_captured(self):
        res = analyse_candidate(_opp(location_requirements="Must reside in Canada"))
        locs = [r for r in res["requirements"] if r["type"] == "location"]
        self.assertTrue(any("Canada" in r["detail"] for r in locs))

    # ── payment method + deliverable parsing ──────────────────────────────
    def test_payment_method_detected(self):
        res = analyse_candidate(_opp(description="Paid via Payoneer on delivery."))
        pays = [r["detail"] for r in res["requirements"] if r["type"] == "payment_method"]
        self.assertIn("Payoneer", pays)

    def test_crypto_payment_detected(self):
        res = analyse_candidate(_opp(description="Paid in USDC on completion."))
        pays = [r["detail"] for r in res["requirements"] if r["type"] == "payment_method"]
        self.assertIn("stablecoin", pays)

    def test_deliverable_captured(self):
        res = analyse_candidate(_opp(
            title="Design a landing page",
            description="You will design a landing page mockup."))
        deles = [r for r in res["requirements"] if r["type"] == "deliverable"]
        self.assertTrue(deles, "a deliverable must be captured")

    # ── viability tiers ───────────────────────────────────────────────────
    def test_plain_remote_gig_is_viable(self):
        res = analyse_candidate(_opp(
            description="Write articles. Paid via PayPal. No restrictions."))
        self.assertEqual(res["viability"], "viable")
        self.assertFalse(res["blockers"])

    def test_empty_entry_is_needs_review_not_viable(self):
        # Fail-closed: a candidate we cannot read is never assumed doable.
        res = analyse_candidate({})
        self.assertEqual(res["viability"], "needs_review")

    def test_eligibility_requirement_is_needs_review(self):
        res = analyse_candidate(_opp(eligibility_requirements="Must be 18+"))
        self.assertEqual(res["viability"], "needs_review")
        elig = [r for r in res["requirements"] if r["type"] == "eligibility"]
        self.assertTrue(elig)

    # ── shape / robustness ────────────────────────────────────────────────
    def test_return_shape(self):
        res = analyse_candidate(_opp())
        self.assertEqual(
            set(res.keys()), {"requirements", "viability", "blockers", "summary"})
        self.assertIsInstance(res["requirements"], list)
        self.assertIsInstance(res["blockers"], list)
        self.assertIn(res["viability"], {"viable", "needs_review", "blocked"})

    def test_accepts_portfolio_entry_shape(self):
        class _Entry:
            opportunity_ref = _opp(description="US only gig, paid via wire.")
            platform = "upwork"
        res = analyse_candidate(_Entry())
        locs = [r for r in res["requirements"] if r["type"] == "location"]
        self.assertTrue(locs)
        self.assertEqual(res["viability"], "needs_review")

    def test_never_raises_on_garbage(self):
        for junk in (None, 42, object(), {"title": None}, {"description": 123}):
            res = analyse_candidate(junk)  # must not raise
            self.assertIn("viability", res)


if __name__ == "__main__":
    unittest.main()
