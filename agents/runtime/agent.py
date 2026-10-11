"""Event-driven runtime for cooperating agents.

The runtime owns agent identity, mutable working state, and speaking
opportunities.  Natural language remains a presentation of state changes; it
does not authorize tools, evidence, or mutations.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from agents.core.comms import EventBus, Message, MessageType


class AgentEventKind(str, Enum):
    TURN_COMPLETED = "turn_completed"
    QUESTION_RAISED = "question_raised"
    PROPOSAL_MADE = "proposal_made"
    EVIDENCE_UPDATED = "evidence_updated"
    INTERRUPT = "interrupt"
    HUMAN_INPUT = "human_input"


@dataclass(frozen=True)
class AgentDescriptor:
    agent_id: str
    identity: str
    role: str
    capabilities: tuple[str, ...] = ()


@dataclass
class AgentState:
    descriptor: AgentDescriptor
    current_goal: str = ""
    confidence: float = 0.5
    availability: str = "available"
    attention: float = 1.0
    pending_questions: list[str] = field(default_factory=list)
    proposed_actions: list[str] = field(default_factory=list)
    beliefs: dict[str, float] = field(default_factory=dict)
    last_event_id: str = ""
    last_spoke_at: float = 0.0


@dataclass(frozen=True)
class AgentEvent:
    kind: AgentEventKind
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    event_id: str = field(default_factory=lambda: "agent_event_" + uuid.uuid4().hex[:20])
    created_at: float = field(default_factory=time.time)


class AgentRuntime:
    """Small deterministic scheduler for event-driven agent collaboration."""

    def __init__(self, goal: str, agents: Iterable[AgentDescriptor], *, bus: EventBus | None = None):
        if not goal.strip():
            raise ValueError("goal is required")
        descriptors = tuple(agents)
        if not descriptors:
            raise ValueError("at least one agent is required")
        if len({agent.agent_id for agent in descriptors}) != len(descriptors):
            raise ValueError("agent ids must be unique")
        self.goal = goal.strip()
        self.states = {
            agent.agent_id: AgentState(agent, current_goal=self.goal)
            for agent in descriptors
        }
        self._order = {agent.agent_id: index for index, agent in enumerate(descriptors)}
        self.events: list[AgentEvent] = []
        self.active_agent_id: str | None = None
        self.bus = bus

    def publish(
        self,
        kind: AgentEventKind,
        source: str,
        *,
        payload: dict[str, Any] | None = None,
        priority: int = 5,
    ) -> AgentEvent:
        if source not in self.states and source != "human":
            raise ValueError(f"unknown event source: {source}")
        event = AgentEvent(kind, source, payload or {}, priority)
        self.events.append(event)
        if self.bus is not None:
            self.bus.publish(
                Message(
                    message_type=MessageType.COGNITION_UPDATE,
                    source=source,
                    destination="agent_runtime",
                    priority=priority,
                    payload={
                        "event_id": event.event_id,
                        "event_kind": kind.value,
                        **event.payload,
                    },
                )
            )
        for agent_id, state in self.states.items():
            if agent_id == source:
                state.attention = max(0.0, state.attention - 0.1)
            elif state.availability == "available":
                state.attention = min(1.0, state.attention + (0.2 if priority >= 7 else 0.1))
                state.last_event_id = event.event_id
        if kind == AgentEventKind.INTERRUPT:
            target = str(event.payload.get("target", ""))
            if target in self.states:
                self.states[target].attention = 1.0
        return event

    def record_turn(self, agent_id: str, text: str, *, intents: Iterable[str] = ()) -> AgentEvent:
        if agent_id not in self.states:
            raise ValueError(f"unknown agent: {agent_id}")
        intent_values = tuple(intents)
        state = self.states[agent_id]
        state.last_spoke_at = time.time()
        state.attention = 0.0
        state.pending_questions = [
            text.strip()
        ] if "question" in intent_values and text.strip() else []
        state.proposed_actions = [
            text.strip()
        ] if any(item in intent_values for item in ("proposal", "action")) and text.strip() else []
        return self.publish(
            AgentEventKind.TURN_COMPLETED,
            agent_id,
            payload={"text": text, "intents": list(intent_values)},
        )

    def next_opportunity(self, *, exclude: str | None = None) -> AgentState | None:
        available = [
            state for state in self.states.values()
            if state.availability == "available" and state.descriptor.agent_id != exclude
        ]
        if not available:
            available = [
                state for state in self.states.values()
                if state.availability == "available"
            ]
        if not available:
            return None
        selected = max(
            available,
            key=lambda state: (
                state.attention,
                -state.last_spoke_at,
                -self._order[state.descriptor.agent_id],
            ),
        )
        self.active_agent_id = selected.descriptor.agent_id
        return selected

    def interrupt(self, source: str, target: str, reason: str) -> AgentEvent:
        return self.publish(
            AgentEventKind.INTERRUPT,
            source,
            payload={"target": target, "reason": reason},
            priority=10,
        )

    def set_availability(self, agent_id: str, availability: str) -> None:
        if agent_id not in self.states:
            raise ValueError(f"unknown agent: {agent_id}")
        self.states[agent_id].availability = availability

    def update_goal(self, goal: str) -> None:
        if not goal.strip():
            raise ValueError("goal is required")
        self.goal = goal.strip()
        for state in self.states.values():
            state.current_goal = self.goal

    def snapshot(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "active_agent_id": self.active_agent_id,
            "agents": {
                agent_id: {
                    "identity": state.descriptor.identity,
                    "role": state.descriptor.role,
                    "current_goal": state.current_goal,
                    "confidence": state.confidence,
                    "availability": state.availability,
                    "attention": state.attention,
                    "pending_questions": list(state.pending_questions),
                    "proposed_actions": list(state.proposed_actions),
                    "last_event_id": state.last_event_id,
                }
                for agent_id, state in self.states.items()
            },
        }


__all__ = [
    "AgentDescriptor",
    "AgentEvent",
    "AgentEventKind",
    "AgentRuntime",
    "AgentState",
]
