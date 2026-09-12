"""Canonical cognition state facade.

SharedContext may carry coordination hints, but durable cognition authority is
kept in CognitionLedger through this adapter.
"""

from agents.cognition import CognitionRecord
from agents.cognition_ledger import CognitionLedger


class CanonicalCognitionState:
    def __init__(self, ledger: CognitionLedger | None = None):
        self.ledger = ledger or CognitionLedger()

    def record(self, record: CognitionRecord):
        return self.ledger.record(record)

    def summary(self, run_id: str) -> dict:
        return self.ledger.summary_for_run(run_id)


__all__ = ["CanonicalCognitionState"]