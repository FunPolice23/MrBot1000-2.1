from agents.cognition import (
    ActionIntent,
    ActionState,
    Claim,
    ClaimStatus,
    CognitionRecord,
    InformationItem,
    InformationKind,
    Option,
    Outcome,
    OutcomeState,
    ToolExecution,
)
from agents.comms import EventBus
from agents.comms_log import MessageLog
from agents.cognition_ledger import CognitionLedger


def test_verified_information_requires_evidence():
    try:
        InformationItem("fact", InformationKind.VERIFIED_FACT)
    except ValueError as exc:
        assert "evidence_ids" in str(exc)
    else:
        raise AssertionError("verified information without evidence must fail")


def test_completed_action_requires_matching_execution_proof():
    record = CognitionRecord(
        goal="inspect listing",
        persona="edward",
        options=[Option("inspect")],
        action=ActionIntent("act-1", "web_read", state=ActionState.COMPLETED),
    )
    assert "completed action requires tool execution proof" in record.validate()

    record.execution = ToolExecution("act-1", "web_read", "completed")
    assert record.is_valid()


def test_verified_outcome_can_update_learning_only_with_evidence():
    without_proof = Outcome(OutcomeState.VERIFIED, "paid")
    with_proof = Outcome(OutcomeState.VERIFIED, "paid", ["ev-1"])
    assert not without_proof.can_update_learning()
    assert with_proof.can_update_learning()


def test_claim_and_record_are_bus_serializable():
    claim = Claim("listing is open", status=ClaimStatus.SUPPORTED, evidence_ids=["ev-1"])
    assert claim.can_support_action()

    record = CognitionRecord(
        goal="inspect listing",
        persona="jacob",
        claims=[claim],
        observations=[InformationItem("page loaded", InformationKind.OBSERVATION)],
    )
    payload = record.to_dict()
    assert payload["persona"] == "jacob"
    assert payload["observations"][0]["kind"] == InformationKind.OBSERVATION
    assert payload["claims"][0]["status"] == ClaimStatus.SUPPORTED


def test_supported_claim_without_evidence_is_rejected():
    record = CognitionRecord(
        goal="review",
        persona="jacob",
        claims=[Claim("listing is open", status=ClaimStatus.SUPPORTED)],
    )
    assert "supported claims require evidence_ids" in record.validate()


def test_cognition_ledger_publishes_and_persists_record():
    bus = EventBus.reset_instance()
    log = MessageLog(":memory:")
    ledger = CognitionLedger(bus=bus, log=log)
    record = CognitionRecord(goal="review", persona="jacob")

    message = ledger.record(record)

    assert message.message_type.value == "COGNITION_UPDATE"
    assert ledger.get(message.message_id)["payload"]["cognition"]["run_id"] == record.run_id
    assert len(ledger.for_run(record.run_id)) == 1