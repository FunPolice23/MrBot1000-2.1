"""Typed cognition artifacts for inspectable dual-brain orchestration.

These records describe reasoning state without exposing private chain-of-thought.
They are coordination contracts, not a second evidence system: factual claims
reference EvidenceStore records by id, while execution and approval state remains
owned by the dispatcher and human approval workflow.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class InformationKind(str, Enum):
    OBSERVATION = "observation"
    VERIFIED_FACT = "verified_fact"
    USER_CLAIM = "user_claim"
    MODEL_CLAIM = "model_claim"
    HYPOTHESIS = "hypothesis"
    ASSUMPTION = "assumption"
    DERIVED = "derived"


class ClaimStatus(str, Enum):
    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    EXPIRED = "expired"


class ApprovalState(str, Enum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    DEFERRED = "deferred"


class ActionState(str, Enum):
    PROPOSED = "proposed"
    BLOCKED = "blocked"
    READY = "ready"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"


class OutcomeState(str, Enum):
    EXPECTED = "expected"
    OBSERVED = "observed"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InformationItem:
    """A concise reasoning input; private token-level thought is excluded."""

    text: str
    kind: InformationKind
    evidence_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = ""
    expires_at: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.kind in (InformationKind.VERIFIED_FACT, InformationKind.DERIVED):
            if not self.evidence_ids:
                raise ValueError("verified facts and derived items require evidence_ids")


@dataclass(frozen=True)
class Claim:
    """A model-facing claim whose support is tracked separately from prose."""

    text: str
    kind: InformationKind = InformationKind.MODEL_CLAIM
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    evidence_ids: List[str] = field(default_factory=list)
    source: str = ""

    def can_support_action(self) -> bool:
        return self.status == ClaimStatus.SUPPORTED and bool(self.evidence_ids)


@dataclass(frozen=True)
class Option:
    title: str
    rationale: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    selected_option: str
    rationale: str
    evidence_ids: List[str] = field(default_factory=list)
    uncertainty: List[str] = field(default_factory=list)
    approval_state: ApprovalState = ApprovalState.NOT_REQUIRED


@dataclass(frozen=True)
class ApprovalRequest:
    action_id: str
    reason: str
    requested_by: str
    state: ApprovalState = ApprovalState.PENDING
    approval_id: str = field(default_factory=lambda: "apr_" + uuid.uuid4().hex[:20])


@dataclass(frozen=True)
class ActionIntent:
    action_id: str
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    state: ActionState = ActionState.PROPOSED
    approval_id: str = ""
    evidence_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolExecution:
    action_id: str
    tool_name: str
    status: str
    result: Dict[str, Any] = field(default_factory=dict)
    evidence_ids: List[str] = field(default_factory=list)
    execution_id: str = field(default_factory=lambda: "exe_" + uuid.uuid4().hex[:20])


@dataclass(frozen=True)
class Outcome:
    state: OutcomeState
    summary: str
    evidence_ids: List[str] = field(default_factory=list)
    outcome_id: str = field(default_factory=lambda: "out_" + uuid.uuid4().hex[:20])

    def can_update_learning(self) -> bool:
        return self.state == OutcomeState.VERIFIED and bool(self.evidence_ids)


@dataclass(frozen=True)
class Lesson:
    summary: str
    source_outcome_ids: List[str] = field(default_factory=list)
    verified: bool = False

    def can_be_promoted(self) -> bool:
        return self.verified and bool(self.source_outcome_ids)


@dataclass
class CognitionRecord:
    """Inspectable state shared between brains and the orchestration layer."""

    goal: str
    persona: str
    reasoning_mode: str = "direct"
    run_id: str = field(default_factory=lambda: "run_" + uuid.uuid4().hex[:20])
    turn_id: str = field(default_factory=lambda: "turn_" + uuid.uuid4().hex[:20])
    created_at: float = field(default_factory=time.time)
    observations: List[InformationItem] = field(default_factory=list)
    assumptions: List[InformationItem] = field(default_factory=list)
    hypotheses: List[InformationItem] = field(default_factory=list)
    claims: List[Claim] = field(default_factory=list)
    options: List[Option] = field(default_factory=list)
    decision: Decision | None = None
    approval: ApprovalRequest | None = None
    action: ActionIntent | None = None
    execution: ToolExecution | None = None
    outcome: Outcome | None = None

    def validate(self) -> List[str]:
        """Return deterministic contract violations without invoking a model."""
        errors: List[str] = []
        if not self.goal.strip():
            errors.append("goal is required")
        if not self.persona.strip():
            errors.append("persona is required")
        if self.decision and self.decision.selected_option and not self.options:
            errors.append("decision requires at least one option")
        for claim in self.claims:
            if claim.status == ClaimStatus.SUPPORTED and not claim.evidence_ids:
                errors.append("supported claims require evidence_ids")
        if self.action and self.action.state == ActionState.COMPLETED and not self.execution:
            errors.append("completed action requires tool execution proof")
        if self.execution and self.execution.action_id != (self.action.action_id if self.action else ""):
            errors.append("execution action_id must match action intent")
        if self.outcome and self.outcome.state == OutcomeState.VERIFIED:
            if not self.outcome.evidence_ids:
                errors.append("verified outcome requires evidence_ids")
        if self.approval and self.action and self.approval.action_id != self.action.action_id:
            errors.append("approval action_id must match action intent")
        return errors

    def is_valid(self) -> bool:
        return not self.validate()

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe summary suitable for Message.payload."""
        return {
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "goal": self.goal,
            "persona": self.persona,
            "reasoning_mode": self.reasoning_mode,
            "created_at": self.created_at,
            "observations": [item.__dict__ for item in self.observations],
            "assumptions": [item.__dict__ for item in self.assumptions],
            "hypotheses": [item.__dict__ for item in self.hypotheses],
            "claims": [claim.__dict__ for claim in self.claims],
            "options": [option.__dict__ for option in self.options],
            "decision": self.decision.__dict__ if self.decision else None,
            "approval": self.approval.__dict__ if self.approval else None,
            "action": self.action.__dict__ if self.action else None,
            "execution": self.execution.__dict__ if self.execution else None,
            "outcome": self.outcome.__dict__ if self.outcome else None,
        }


__all__ = [
    "ActionIntent", "ActionState", "ApprovalRequest", "ApprovalState",
    "Claim", "ClaimStatus", "CognitionRecord", "Decision", "InformationItem",
    "InformationKind", "Lesson", "Option", "Outcome", "OutcomeState",
    "ToolExecution",
]