"""Graph-of-Thought planning for opportunity discovery and evaluation.

This module uses GoT to compare ways to investigate an opportunity. It does
not turn expected value into payment truth and does not authorize execution.
The existing filter, lifecycle, approval, evidence, and accounting gates remain
authoritative after this planner returns its ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, Iterable, List, Mapping

from agents.cognition import (
    SupportMeasure,
    ThoughtEdge,
    ThoughtEdgeKind,
    ThoughtGraph,
    ThoughtNode,
    ThoughtNodeKind,
)


@dataclass(frozen=True)
class OpportunityGraphRank:
    opportunity_id: str
    utility_score: float
    support: SupportMeasure
    next_check: str

    @property
    def recommendation(self) -> str:
        if self.support.recommendation == "contradicted":
            return "avoid_pending_reconciliation"
        if self.support.action_eligible:
            return "candidate_for_existing_gates"
        return "investigate_before_action"

    def to_dict(self) -> dict:
        return {
            "opportunity_id": self.opportunity_id,
            "utility_score": round(self.utility_score, 4),
            "support": self.support.to_dict(),
            "next_check": self.next_check,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class GraphBudget:
    """Hard limits for one bounded opportunity decision search."""

    max_candidates: int = 64
    max_nodes: int = 256
    max_cost: float = float("inf")
    max_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.max_candidates < 1 or self.max_nodes < 2:
            raise ValueError("GoT graph budgets must allow at least one option and goal")
        if self.max_cost < 0.0 or self.max_seconds <= 0.0:
            raise ValueError("GoT cost and time budgets must be positive")


class OpportunityGraphPlanner:
    """Build and rank a bounded GoT graph for evaluated opportunities."""

    def __init__(
        self,
        opportunities: Iterable[Any],
        evidence_by_id: Mapping[str, Any] | None = None,
        budget: GraphBudget | None = None,
    ):
        self.budget = budget or GraphBudget()
        self.opportunities: List[Any] = []
        self.rejected_alternatives: List[dict[str, str]] = []
        self.evidence_by_id = evidence_by_id or {}
        self.graph = ThoughtGraph()
        self._option_ids: List[str] = []
        self._started_at = time.monotonic()
        self._load_candidates(opportunities)
        self._build()

    @staticmethod
    def _estimated_cost(opportunity: Any) -> float:
        intelligence = getattr(opportunity, "intelligence", None)
        return max(0.0, float(getattr(intelligence, "model_cost", 0.0) or 0.0))

    def _reject(self, opportunity: Any, reason: str) -> None:
        self.rejected_alternatives.append({
            "opportunity_id": self._id(opportunity),
            "reason": reason,
        })

    def _load_candidates(self, opportunities: Iterable[Any]) -> None:
        total_cost = 0.0
        for opportunity in opportunities:
            if len(self.opportunities) >= self.budget.max_candidates:
                self._reject(opportunity, "candidate_budget_exceeded")
                continue
            projected_nodes = 1 + (len(self.opportunities) + 1) * 2
            if projected_nodes > self.budget.max_nodes:
                self._reject(opportunity, "node_budget_exceeded")
                continue
            if time.monotonic() - self._started_at > self.budget.max_seconds:
                self._reject(opportunity, "time_budget_exceeded")
                continue
            estimated_cost = self._estimated_cost(opportunity)
            if total_cost + estimated_cost > self.budget.max_cost:
                self._reject(opportunity, "cost_budget_exceeded")
                continue
            total_cost += estimated_cost
            self.opportunities.append(opportunity)

    @staticmethod
    def _id(opportunity: Any) -> str:
        return str(getattr(opportunity, "id", getattr(opportunity, "opportunity_id", "")))

    def _build(self) -> None:
        self.graph.add_node(ThoughtNode(
            "discovery-goal", ThoughtNodeKind.GOAL,
            "Find high-value opportunities worth the next verified check",
            source="earning_pipeline",
        ))
        for opportunity in self.opportunities:
            opportunity_id = self._id(opportunity)
            if not opportunity_id:
                continue
            option_id = f"option:{opportunity_id}"
            check_id = f"check:{opportunity_id}:evidence"
            evidence_ids = tuple(getattr(opportunity, "evidence_ids", ()) or ())
            self.graph.add_node(ThoughtNode(
                option_id,
                ThoughtNodeKind.OPTION,
                str(getattr(opportunity, "title", opportunity_id)),
                source=str(getattr(opportunity, "source", "")),
            ))
            self.graph.add_node(ThoughtNode(
                check_id,
                ThoughtNodeKind.CHECK,
                "Verify source, terms, effort, risk, and payment path",
                source="earning_pipeline",
                evidence_ids=evidence_ids,
            ))
            self.graph.add_edge(ThoughtEdge(
                option_id, "discovery-goal", ThoughtEdgeKind.ENABLES,
                note="candidate discovery branch",
            ))
            self.graph.add_edge(ThoughtEdge(
                option_id, check_id, ThoughtEdgeKind.DEPENDS_ON,
                note="do not advance this option before its next check",
            ))
            self.graph.add_edge(ThoughtEdge(
                check_id, option_id, ThoughtEdgeKind.SUPPORTS,
                note="verified check supports candidate consideration",
            ))
            self._option_ids.append(option_id)

    @staticmethod
    def _utility(opportunity: Any) -> float:
        evaluation = getattr(opportunity, "intelligence", None)
        if evaluation is None:
            return 0.0
        expected = max(0.0, float(getattr(evaluation, "expected_value", 0.0) or 0.0))
        hourly = max(0.0, float(getattr(evaluation, "expected_hourly_value", 0.0) or 0.0))
        confidence = min(1.0, max(0.0, float(getattr(evaluation, "confidence", 0.0) or 0.0)))
        risk = max(0.0, float(getattr(evaluation, "risk_penalty", 0.0) or 0.0))
        return (expected * (0.5 + 0.5 * confidence)) + (0.1 * hourly) - risk

    def rank(self) -> List[OpportunityGraphRank]:
        measures = {
            option_id: self.graph.measure_support(option_id, self.evidence_by_id)
            for option_id in self._option_ids
        }
        by_id = {self._id(opportunity): opportunity for opportunity in self.opportunities}
        ranked = []
        for option_id, measure in measures.items():
            opportunity_id = option_id.split(":", 1)[1]
            ranked.append(OpportunityGraphRank(
                opportunity_id,
                self._utility(by_id[opportunity_id]),
                measure,
                f"check:{opportunity_id}:evidence",
            ))
        return sorted(
            ranked,
            key=lambda item: (item.recommendation == "candidate_for_existing_gates",
                              item.utility_score),
            reverse=True,
        )

    def audit_summary(self) -> dict[str, Any]:
        """Return bounded-search metadata and compact rejected alternatives."""
        return {
            "budget": {
                "max_candidates": self.budget.max_candidates,
                "max_nodes": self.budget.max_nodes,
                "max_cost": self.budget.max_cost,
                "max_seconds": self.budget.max_seconds,
            },
            "accepted_candidates": len(self.opportunities),
            "graph_nodes": len(self.graph.nodes),
            "graph_edges": len(self.graph.edges),
            "rejected_alternatives": list(self.rejected_alternatives),
        }


__all__ = ["GraphBudget", "OpportunityGraphPlanner", "OpportunityGraphRank"]