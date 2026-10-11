"""Typed cognition artifacts for inspectable dual-brain orchestration.

These records describe reasoning state without exposing private chain-of-thought.
They are coordination contracts, not a second evidence system: factual claims
reference EvidenceStore records by id, while execution and approval state remains
owned by the dispatcher and human approval workflow.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Mapping, Set, Tuple


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


class ThoughtNodeKind(str, Enum):
    """Inspectable reasoning artifacts, not private token-level thoughts."""

    GOAL = "goal"
    OBSERVATION = "observation"
    EVIDENCE = "evidence"
    CLAIM = "claim"
    HYPOTHESIS = "hypothesis"
    OPTION = "option"
    DECISION = "decision"
    CHECK = "check"
    APPROVAL = "approval"
    ACTION = "action"
    OUTCOME = "outcome"


class ThoughtEdgeKind(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DEPENDS_ON = "depends_on"
    DERIVED_FROM = "derived_from"
    ENABLES = "enables"
    INVALIDATES = "invalidates"


@dataclass(frozen=True)
class ThoughtNode:
    """One concise, inspectable graph node; it never contains chain-of-thought."""

    node_id: str
    kind: ThoughtNodeKind
    text: str
    source: str = ""
    evidence_ids: Tuple[str, ...] = ()
    status: str = "proposed"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind.value,
            "text": self.text,
            "source": self.source,
            "evidence_ids": list(self.evidence_ids),
            "status": self.status,
        }


@dataclass(frozen=True)
class ThoughtEdge:
    """A typed relationship between two inspectable reasoning nodes."""

    source_id: str
    target_id: str
    kind: ThoughtEdgeKind
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind.value,
            "note": self.note,
        }


@dataclass(frozen=True)
class SupportMeasure:
    """Deterministic support summary; it is advisory and never grants authority."""

    node_id: str
    direct_support: float
    propagated_support: float
    contradiction: float
    unresolved_dependencies: int
    evidence_ids: List[str] = field(default_factory=list)
    recommendation: str = "insufficient_support"

    @property
    def action_eligible(self) -> bool:
        """Whether the graph is sufficiently supported to recommend a gate check."""
        return (
            self.recommendation == "supported"
            and self.contradiction == 0.0
            and self.unresolved_dependencies == 0
            and bool(self.evidence_ids)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "direct_support": self.direct_support,
            "propagated_support": self.propagated_support,
            "contradiction": self.contradiction,
            "unresolved_dependencies": self.unresolved_dependencies,
            "evidence_ids": list(self.evidence_ids),
            "recommendation": self.recommendation,
            "action_eligible": self.action_eligible,
        }


class ThoughtGraph:
    """Bounded, inspectable Graph-of-Thought support structure.

    Evidence objects are supplied by the caller when support is measured. An
    evidence ID alone never increases support, which prevents model narration
    from becoming verification.
    """

    def __init__(self):
        self.nodes: Dict[str, ThoughtNode] = {}
        self.edges: List[ThoughtEdge] = []

    def add_node(self, node: ThoughtNode) -> ThoughtNode:
        if not node.node_id.strip() or not node.text.strip():
            raise ValueError("thought nodes require node_id and text")
        if node.node_id in self.nodes:
            raise ValueError(f"duplicate thought node: {node.node_id}")
        self.nodes[node.node_id] = node
        return node

    def add_edge(self, edge: ThoughtEdge) -> ThoughtEdge:
        if edge.source_id not in self.nodes or edge.target_id not in self.nodes:
            raise ValueError("thought edges must reference existing nodes")
        if edge.source_id == edge.target_id and edge.kind == ThoughtEdgeKind.DEPENDS_ON:
            raise ValueError("a dependency cannot point to itself")
        candidate = self.edges + [edge]
        if edge.kind == ThoughtEdgeKind.DEPENDS_ON and self._has_dependency_cycle(candidate):
            raise ValueError("thought dependency cycle detected")
        self.edges.append(edge)
        return edge

    def update_node(self, node_id: str, **changes: Any) -> ThoughtNode:
        """Replace an existing node with a status/text update."""
        if node_id not in self.nodes:
            raise KeyError(node_id)
        unknown = set(changes) - {"text", "source", "evidence_ids", "status"}
        if unknown:
            raise ValueError(f"unsupported thought node fields: {sorted(unknown)}")
        updated = replace(self.nodes[node_id], **changes)
        self.nodes[node_id] = updated
        return updated

    def _has_dependency_cycle(self, edges: List[ThoughtEdge]) -> bool:
        graph: Dict[str, List[str]] = {}
        for edge in edges:
            if edge.kind == ThoughtEdgeKind.DEPENDS_ON:
                graph.setdefault(edge.source_id, []).append(edge.target_id)
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def visit(node_id: str) -> bool:
            if node_id in visiting:
                return True
            if node_id in visited:
                return False
            visiting.add(node_id)
            if any(visit(child) for child in graph.get(node_id, [])):
                return True
            visiting.remove(node_id)
            visited.add(node_id)
            return False

        return any(visit(node_id) for node_id in graph)

    def measure_support(
        self,
        node_id: str,
        evidence_by_id: Mapping[str, Any] | None = None,
        _seen: Set[str] | None = None,
    ) -> SupportMeasure:
        """Measure direct and propagated support without changing graph state.

        Evidence confidence comes from deterministic ``Evidence.confidence`` and
        affirmative status. Supporting nodes propagate their strongest score without
        compounding it; contradictions subtract their source score. This keeps graph
        propagation useful while ensuring evidence-backed support remains necessary.
        """
        if node_id not in self.nodes:
            raise KeyError(node_id)
        evidence_by_id = evidence_by_id or {}
        seen = set(_seen or set())
        if node_id in seen:
            return SupportMeasure(node_id, 0.0, 0.0, 1.0, 1, [])
        seen.add(node_id)
        node = self.nodes[node_id]
        candidate_evidence_ids = node.evidence_ids
        evidence_ids = []
        direct_values = []
        for evidence_id in candidate_evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or not getattr(getattr(evidence, "status", None), "is_affirmative", False):
                continue
            direct_values.append(float(getattr(evidence, "confidence", 0.0) or 0.0))
            evidence_ids.append(evidence_id)
        direct = max(direct_values, default=0.0)
        incoming = [edge for edge in self.edges if edge.target_id == node_id]
        outgoing_dependencies = [
            edge for edge in self.edges
            if edge.source_id == node_id and edge.kind == ThoughtEdgeKind.DEPENDS_ON
        ]
        propagated = 0.0
        contradiction = 1.0 if node.status in ("contradicted", "refuted") else 0.0
        unresolved = 0
        for edge in incoming:
            if edge.kind not in (ThoughtEdgeKind.SUPPORTS, ThoughtEdgeKind.CONTRADICTS):
                continue
            child = self.measure_support(edge.source_id, evidence_by_id, seen)
            if edge.kind == ThoughtEdgeKind.SUPPORTS:
                propagated = max(propagated, child.direct_support, child.propagated_support)
                evidence_ids.extend(child.evidence_ids)
            elif edge.kind == ThoughtEdgeKind.CONTRADICTS:
                source_node = self.nodes[edge.source_id]
                contradiction = max(
                    contradiction,
                    1.0 if source_node.status in ("contradicted", "refuted")
                    else max(child.direct_support, child.propagated_support),
                )
        for edge in outgoing_dependencies:
            prerequisite = self.measure_support(edge.target_id, evidence_by_id, seen)
            if prerequisite.recommendation != "supported":
                unresolved += 1
        combined = max(direct, min(1.0, propagated))
        if contradiction:
            recommendation = "contradicted"
        elif unresolved:
            recommendation = "blocked"
        elif combined >= 0.7 and evidence_ids:
            recommendation = "supported"
        else:
            recommendation = "insufficient_support"
        return SupportMeasure(
            node_id, direct, propagated, contradiction, unresolved,
            sorted(set(evidence_ids)), recommendation,
        )

    def measure_all(self, evidence_by_id: Mapping[str, Any] | None = None) -> Dict[str, SupportMeasure]:
        """Measure every node for diagnostics and UI summaries."""
        return {
            node_id: self.measure_support(node_id, evidence_by_id)
            for node_id in self.nodes
        }

    def rank_options(
        self,
        option_ids: List[str],
        evidence_by_id: Mapping[str, Any] | None = None,
    ) -> List[SupportMeasure]:
        """Rank option nodes by support, preferring uncontradicted evidence-backed choices."""
        measures = []
        for option_id in option_ids:
            node = self.nodes.get(option_id)
            if node is None or node.kind != ThoughtNodeKind.OPTION:
                raise ValueError(f"rank_options expects OPTION nodes: {option_id}")
            measures.append(self.measure_support(option_id, evidence_by_id))
        return sorted(
            measures,
            key=lambda measure: (
                measure.action_eligible,
                measure.recommendation == "supported",
                measure.contradiction == 0.0,
                measure.direct_support + measure.propagated_support,
            ),
            reverse=True,
        )

    def validate(self) -> List[str]:
        errors = []
        for edge in self.edges:
            if edge.source_id not in self.nodes or edge.target_id not in self.nodes:
                errors.append("edge references missing node")
        if self._has_dependency_cycle(self.edges):
            errors.append("thought dependency cycle detected")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
        }


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
    thought_graph: ThoughtGraph = field(default_factory=ThoughtGraph)
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
        errors.extend(self.thought_graph.validate())
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
            "thought_graph": self.thought_graph.to_dict(),
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
    "ThoughtEdge", "ThoughtEdgeKind", "ThoughtGraph", "ThoughtNode",
    "ThoughtNodeKind", "SupportMeasure", "ToolExecution",
]