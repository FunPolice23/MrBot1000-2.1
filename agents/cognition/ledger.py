"""Durable cognition ledger backed by the canonical EventBus message path."""

from __future__ import annotations

from typing import List, Optional

from agents.core.comms import EventBus, Message, MessageType
from agents.core.comms_log import MessageLog
from agents.cognition import CognitionRecord


class CognitionLedger:
    """Publish and persist inspectable cognition records without model internals."""

    def __init__(self, bus: Optional[EventBus] = None, log: Optional[MessageLog] = None):
        self.bus = bus or EventBus.instance()
        self.log = log or MessageLog(":memory:")

    def record(self, record: CognitionRecord) -> Message:
        violations = record.validate()
        if violations:
            raise ValueError("invalid cognition record: " + "; ".join(violations))
        message = Message(
            message_type=MessageType.COGNITION_UPDATE,
            source=record.persona,
            destination="coordinator",
            correlation_id=record.run_id,
            payload={"cognition": record.to_dict()},
        )
        self.log.record(message)
        self.bus.publish(message)
        return message

    def get(self, message_id: str):
        return self.log.get(message_id)

    def for_run(self, run_id: str) -> List[dict]:
        return [item for item in self.log.all() if item["correlation_id"] == run_id]

    def summary_for_run(self, run_id: str) -> dict:
        """Return inspectable state counts without exposing private thought."""
        messages = self.for_run(run_id)
        records = [message.get("payload", {}).get("cognition", {}) for message in messages]
        graphs = [record.get("thought_graph", {}) for record in records]
        return {
            "run_id": run_id,
            "updates": len(records),
            "personas": sorted({record.get("persona", "") for record in records if record.get("persona")}),
            "claims": sum(len(record.get("claims", [])) for record in records),
            "actions": sum(1 for record in records if record.get("action")),
            "executions": sum(1 for record in records if record.get("execution")),
            "outcomes": sum(1 for record in records if record.get("outcome")),
            "evidence_ids": sorted({
                evidence_id
                for record in records
                for claim in record.get("claims", [])
                for evidence_id in claim.get("evidence_ids", [])
            }),
            "thought_graphs": sum(1 for graph in graphs if graph.get("nodes")),
            "thought_nodes": sum(len(graph.get("nodes", [])) for graph in graphs),
            "thought_edges": sum(len(graph.get("edges", [])) for graph in graphs),
        }


__all__ = ["CognitionLedger"]