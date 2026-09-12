from agents.cognition import Claim, ClaimStatus, CognitionRecord
from agents.cognition_ledger import CognitionLedger


def test_ledger_exposes_summary_without_private_reasoning():
    ledger = CognitionLedger()
    record = CognitionRecord(
        goal="inspect",
        persona="Edward",
        claims=[Claim("ready", status=ClaimStatus.SUPPORTED, evidence_ids=["ev-1"])],
    )
    ledger.record(record)
    summary = ledger.summary_for_run(record.run_id)
    assert summary["claims"] == 1
    assert summary["evidence_ids"] == ["ev-1"]
    assert "reasoning_chain" not in summary