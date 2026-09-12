from agents.workflow_engine import WorkflowEngine, WorkflowPhase


def test_workflow_requires_proof_at_phase_boundaries():
    class OpportunityStub:
        id = "opp-invariants"
        def to_dict(self):
            return {}

    engine = WorkflowEngine()
    engine.start_workflow(OpportunityStub())
    assert not engine.transition("opp-invariants", WorkflowPhase.VETTING)
    assert engine.transition("opp-invariants", WorkflowPhase.VETTING, data={"evidence_ids": ["ev-1"]})
    assert not engine.transition("opp-invariants", WorkflowPhase.PROPOSAL)
    assert engine.transition("opp-invariants", WorkflowPhase.PROPOSAL, data={"proposal": "draft"})
    assert not engine.transition("opp-invariants", WorkflowPhase.EXECUTION,
                                 data={"approval_state": "approved"})
    assert engine.transition("opp-invariants", WorkflowPhase.EXECUTION,
                             data={"approval_state": "approved", "action_id": "act-1"})