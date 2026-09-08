import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from earning_pipeline import Opportunity
from agents.opportunity_lifecycle import OpportunityLifecycleTracker


class TestOpportunityStateMachine(unittest.TestCase):
    def test_invalid_transition_is_recorded(self):
        tracker = OpportunityLifecycleTracker()
        opportunity = Opportunity(id="opp_state_1", source="upwork", platform="Upwork")
        tracker.start(opportunity)

        tracker.mark_failed(opportunity.id, note="stopped")
        # mark_paid is a DEPRECATED unverified self-report: it must NOT flip a "failed"
        # opp to "paid" (Group 2/3 honesty fix). The attempt is recorded but rejected.
        tracker.mark_paid(opportunity.id, amount=25.0, note="after fail")

        state = tracker.get_state(opportunity.id)
        # A failed opp is NOT promoted to "paid" by an unverified self-reported payout
        # (Group 2/3 honesty fix). It stays failed; the paid attempt is recorded but rejected.
        self.assertNotEqual(state["current_stage"], "paid")
        self.assertNotEqual(state["status"], "paid")

    def test_valid_transition_updates_stage(self):
        tracker = OpportunityLifecycleTracker()
        opportunity = Opportunity(id="opp_state_2", source="fiverr", platform="Fiverr")
        tracker.start(opportunity)
        tracker.mark_researched(opportunity.id)
        tracker.mark_applied(opportunity.id)
        tracker.mark_in_progress(opportunity.id)
        tracker.mark_submitted(opportunity.id)
        # An unverified self-reported mark_paid must NOT flip to "paid" (honesty fix).
        tracker.mark_paid(opportunity.id, amount=120.0, note="paid")
        state = tracker.get_state(opportunity.id)
        self.assertEqual(state["current_stage"], "submitted")
        self.assertNotEqual(state["status"], "paid")

        # A real verified L3+ payment evidence DOES complete the transition to paid.
        from agents.evidence import Evidence, EvidenceStatus, VerificationLevel
        ev = Evidence.create(source="system", evidence_type="payment_gross",
                              subject_type="opportunity", subject_id=opportunity.id,
                              external_id="ext-2", amount=120.0, currency="usd",
                              verification_method="authenticated_api",
                              verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
                              status=EvidenceStatus.VERIFIED,
                              provenance={"producer": "payment_provider"})
        tracker.mark_paid_verified(opportunity.id, amount=120.0, evidence=ev)
        state2 = tracker.get_state(opportunity.id)
        self.assertEqual(state2["current_stage"], "paid")
        self.assertEqual(state2["status"], "paid")
        self.assertEqual(state2["last_amount"], 120.0)


if __name__ == "__main__":
    unittest.main()
