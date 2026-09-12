from agents.autonomy.self_improvement import OutcomeRecord, SelfImprovementEngine


def test_learning_ignores_unverified_outcomes():
    engine = SelfImprovementEngine()
    engine.record_outcome(OutcomeRecord(opportunity_id="unverified"))
    assert engine.state.total_outcomes == 0


def test_learning_accepts_evidence_backed_outcomes():
    engine = SelfImprovementEngine()
    engine.record_outcome(OutcomeRecord(
        opportunity_id="verified", strategy="test", platform="test",
        verified=True, evidence_ids=["ev-verified"],
    ))
    assert engine.state.total_outcomes == 1