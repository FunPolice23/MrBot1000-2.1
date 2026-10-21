"""ARCH-ENG-122 — a gross figure substituted for an unstated net must be
reported as gross.

`opportunity_intelligence` fell back to `advertised_amount` whenever
`estimated_net_value` was unset, then wrote the result into
`reasons["estimated_net_payment"]` — a net-labelled field — and reported
`sufficiency["payment_amount_known"] = True`. Gross is not net: platform fees
and haircuts are real and unmodelled, so the EV carried a gross number under a
net label and a caller could not tell "net stated" from "gross substituted".

The advertised figure is still the best available estimate and the verdict
policy is unchanged — the defect was the SILENT relabelling. Now the basis is
recorded and confidence is reduced.
"""
import sys
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.earning.opportunity_intelligence import (
    OpportunityIntelligenceEngine, SemanticEstimate,
)
from agents.earning.opportunity_models import Opportunity


def _opp(**kw):
    base = dict(
        opportunity_id="o1", source="s", platform="p", title="T",
        description="d", category="coding", advertised_amount=0.0,
        estimated_net_value=0.0, estimated_effort=0.0, scam_risk=0.0,
        risk_level="low", source_reliability=0.5, currency="USD",
    )
    base.update(kw)
    return Opportunity(**base)


class TestGrossIsNotNet(unittest.TestCase):
    def setUp(self):
        self.engine = OpportunityIntelligenceEngine()

    def _eval(self, **kw):
        est = SemanticEstimate(skill_fit=0.8, difficulty=0.3, competition=0.3,
                               effort_hours=kw.pop("effort_hours", 5.0))
        return self.engine.evaluate(_opp(**kw), estimates=est)

    def test_unstated_net_is_flagged_as_gross_substitution(self):
        """advertised=500, net unset: the estimate is gross, and must say so."""
        r = self._eval(advertised_amount=500.0, estimated_net_value=0.0)
        self.assertAlmostEqual(r.reasons["estimated_net_payment"], 500.0)
        self.assertEqual(
            r.reasons.get("estimated_net_payment_basis"),
            "advertised_gross (net not stated)",
        )
        self.assertFalse(r.data_sufficiency["net_payment_known"])

    def test_stated_net_is_not_flagged(self):
        """A real stated net must NOT be labelled as a gross substitution."""
        r = self._eval(advertised_amount=500.0, estimated_net_value=450.0)
        self.assertAlmostEqual(r.reasons["estimated_net_payment"], 450.0)
        self.assertNotIn("estimated_net_payment_basis", r.reasons)
        self.assertTrue(r.data_sufficiency["net_payment_known"])

    def test_gross_substitution_lowers_confidence(self):
        """The same listing scored with a stated net must not be more confident
        than when the net was merely substituted by the gross."""
        stated = self._eval(advertised_amount=500.0, estimated_net_value=450.0)
        substituted = self._eval(advertised_amount=500.0, estimated_net_value=0.0)
        self.assertLess(substituted.confidence, stated.confidence)

    def test_no_amount_at_all_still_reports_unknown(self):
        """Nothing stated anywhere: no estimate, no basis claim.

        A listing with no amount at all is structurally INVALID and short-circuits
        before the factor model runs, so it never reaches factor 6 — which is the
        correct fail-closed routing. What must hold is that nothing fabricated an
        amount on the way out.
        """
        r = self._eval(advertised_amount=0.0, estimated_net_value=0.0)
        self.assertEqual(r.reasons.get("estimated_net_payment", 0.0), 0.0)
        self.assertNotIn("estimated_net_payment_basis", r.reasons)
        self.assertNotIn("net_payment_known", r.data_sufficiency)
        self.assertEqual(r.verdict, "blocked")

    def test_verdict_policy_unchanged(self):
        """The fix must not alter verdict routing — only honest reporting."""
        substituted = self._eval(advertised_amount=500.0, estimated_net_value=0.0,
                                 effort_hours=5.0)
        stated = self._eval(advertised_amount=500.0, estimated_net_value=500.0,
                            effort_hours=5.0)
        self.assertEqual(substituted.verdict, stated.verdict)
        self.assertIn(stated.verdict, ("attractive", "marginal", "poor"))

    def test_sufficiency_keys_present(self):
        """`net_payment_known` must exist on every assessment that reaches the
        factor model (i.e. every listing with a stated amount)."""
        for advertised, net in ((500.0, 450.0), (500.0, 0.0)):
            with self.subTest(advertised=advertised, net=net):
                r = self._eval(advertised_amount=advertised, estimated_net_value=net)
                self.assertIn("net_payment_known", r.data_sufficiency)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
