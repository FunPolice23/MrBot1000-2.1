from agents.earning.got import OpportunityGraphPlanner
from agents.evidence.evidence import Evidence, EvidenceStatus, VerificationLevel


class _Evaluation:
    def __init__(self, expected_value, hourly, confidence, risk_penalty=0.0):
        self.expected_value = expected_value
        self.expected_hourly_value = hourly
        self.confidence = confidence
        self.risk_penalty = risk_penalty


class _Opportunity:
    def __init__(self, opportunity_id, title, evaluation, evidence_ids=()):
        self.id = opportunity_id
        self.title = title
        self.source = "test"
        self.intelligence = evaluation
        self.evidence_ids = evidence_ids


def _evidence(evidence_id):
    return Evidence(
        id=evidence_id,
        source="test",
        evidence_type="research_summary",
        status=EvidenceStatus.VERIFIED,
        verification_level=VerificationLevel.L3_EXTERNAL_SOURCE,
        verification_method="authenticated_api_response",
    )


def test_planner_ranks_utility_but_marks_unverified_options_for_investigation():
    opportunities = [
        _Opportunity("low", "Lower value", _Evaluation(10, 4, 0.8)),
        _Opportunity("high", "Higher value", _Evaluation(100, 20, 0.8)),
    ]
    planner = OpportunityGraphPlanner(opportunities)

    ranked = planner.rank()

    assert [item.opportunity_id for item in ranked] == ["high", "low"]
    assert all(item.recommendation == "investigate_before_action" for item in ranked)
    assert all(not item.support.action_eligible for item in ranked)


def test_verified_check_can_make_an_option_candidate_for_existing_gates():
    opportunity = _Opportunity("verified", "Verified option", _Evaluation(50, 10, 0.8), ("ev-1",))
    planner = OpportunityGraphPlanner([opportunity], {"ev-1": _evidence("ev-1")})

    result = planner.rank()[0]

    assert result.support.action_eligible
    assert result.recommendation == "candidate_for_existing_gates"