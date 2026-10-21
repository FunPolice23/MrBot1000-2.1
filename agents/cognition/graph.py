"""Typed thought-graph artifacts for inspectable dual-brain orchestration.

The graph is a coordination contract, not a second evidence system: support
propagation is advisory and never grants authority, and factual claims reference
EvidenceStore records by id.

ARCH-ENG-233 (BG-01): the ``CognitionRecord`` record cluster that used to live
below this class (11 dataclasses plus the ledger/state/memory_promotion/
contradictions satellites) is deleted. It had no production consumer -- it was
loaded on every run through the package facade but never called by anything
outside its tests (docs/analysis/11R-cognition-graph-depth.md). Its evidence
gates were laxer than the live ``SupportMeasure.action_eligible`` gate, so the
deletion also removes the BG-02 two-strictness disagreement.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Mapping, Set, Tuple


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


__all__ = [
    "ThoughtEdge", "ThoughtEdgeKind", "ThoughtGraph",
    "ThoughtNode", "ThoughtNodeKind", "SupportMeasure",
]
