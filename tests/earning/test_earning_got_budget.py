from agents.earning.got import GraphBudget, OpportunityGraphPlanner


class _Evaluation:
    expected_value = 10.0
    expected_hourly_value = 2.0
    confidence = 0.5
    risk_penalty = 0.0


class _Opportunity:
    source = "test"
    intelligence = _Evaluation()
    evidence_ids = ()

    def __init__(self, opportunity_id):
        self.id = opportunity_id
        self.title = opportunity_id


def test_candidate_budget_preserves_rejected_alternatives():
    planner = OpportunityGraphPlanner(
        [_Opportunity("one"), _Opportunity("two")],
        budget=GraphBudget(max_candidates=1),
    )

    assert [item.opportunity_id for item in planner.rank()] == ["one"]
    assert planner.rejected_alternatives == [{
        "opportunity_id": "two",
        "reason": "candidate_budget_exceeded",
    }]
    assert planner.audit_summary()["accepted_candidates"] == 1


def test_node_budget_is_enforced_before_graph_expansion():
    planner = OpportunityGraphPlanner(
        [_Opportunity("one"), _Opportunity("two")],
        budget=GraphBudget(max_candidates=2, max_nodes=4),
    )

    assert [item.opportunity_id for item in planner.rank()] == ["one"]
    assert planner.rejected_alternatives[0]["reason"] == "node_budget_exceeded"
