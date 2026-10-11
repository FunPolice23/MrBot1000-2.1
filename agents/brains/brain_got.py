"""Inspectable Graph-of-Thought records for model turns.

This is deliberately a public coordination trace, not private model reasoning.
It records the request, bounded tool outcomes, and the resulting status so the
Dialogue UI and both brain adapters share one observable contract.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from agents.cognition import (
    ThoughtEdge,
    ThoughtEdgeKind,
    ThoughtGraph,
    ThoughtNode,
    ThoughtNodeKind,
)
from agents.cognition.graph import SupportMeasure
from agents.cognition.reasoning_modes import PatternSelection, select_reasoning_pattern


@dataclass
class BranchCandidate:
    """One inspectable candidate thought for a branching (Tree/Graph-of-Thought) turn.

    This is a concise public candidate summary, never private chain-of-thought.
    The qualitative fields (payout/effort/risk) are recorded for transparency; the
    authoritative numeric score comes from deterministic evidence-backed support
    (``ThoughtGraph.measure_support``), so narration never becomes verification.
    """

    text: str
    rationale: str = ""
    evidence_ids: tuple[str, ...] = ()
    expected_payout: float | None = None
    effort: str = ""
    risk: str = ""

    def summary(self) -> str:
        parts = [self.text]
        if self.expected_payout is not None:
            parts.append(f"expected=${self.expected_payout:g}")
        if self.effort:
            parts.append(f"effort={self.effort}")
        if self.risk:
            parts.append(f"risk={self.risk}")
        return " · ".join(parts)


class BrainTurnGraph:
    """Build a small, deterministic GoT graph around one model invocation."""

    def __init__(
        self,
        role: str,
        goal: str,
        turn_id: str | None = None,
        pattern: PatternSelection | None = None,
    ):
        self.role = str(role or "unknown")
        self.turn_id = turn_id or "turn_" + uuid.uuid4().hex[:20]
        self.graph = ThoughtGraph()
        self.pattern = pattern or select_reasoning_pattern(goal)
        self._goal_id = f"goal:{self.turn_id}"
        self._option_id = f"option:{self.turn_id}"
        self._check_id = f"check:{self.turn_id}:evidence"
        self._decision_id = f"decision:{self.turn_id}"
        # Branch expansion state (Tree/Graph-of-Thoughts). Empty until
        # expand_branches() is called; when populated, the turn is a branching
        # turn and score_branches()/select_branch() rank and choose among them.
        self._branch_ids: list[str] = []
        self._branch_scores: list[SupportMeasure] = []
        self._selected_branch_id: str | None = None
        self.graph.add_node(ThoughtNode(
            self._goal_id, ThoughtNodeKind.GOAL,
            self._summary(goal, 600),
            source="operator",
            status=f"pattern:{self.pattern.pattern.value}"))
        self.graph.add_node(ThoughtNode(
            self._option_id, ThoughtNodeKind.OPTION,
            f"Generate a {self.role} response to the current request",
            source=self.role, status="running"))
        self.graph.add_node(ThoughtNode(
            self._check_id, ThoughtNodeKind.CHECK,
            "Check available evidence and tool results before making claims",
            source="brain_got", status="pending"))
        self.graph.add_edge(ThoughtEdge(
            self._option_id, self._check_id, ThoughtEdgeKind.DEPENDS_ON,
            note="response must respect current evidence"))
        self.graph.add_edge(ThoughtEdge(
            self._check_id, self._option_id, ThoughtEdgeKind.SUPPORTS,
            note="bounded evidence can support the response"))

    def record_decision(
        self,
        selected_option: str,
        rationale: str,
        *,
        evidence_ids: Iterable[str] = (),
    ) -> str:
        """Record a concise decision summary without recording private reasoning."""
        node_id = f"decision:{self.turn_id}"
        self.graph.add_node(ThoughtNode(
            node_id,
            ThoughtNodeKind.DECISION,
            self._summary(f"{selected_option}: {rationale}", 600),
            source=self.role,
            evidence_ids=tuple(evidence_ids),
            status="proposed",
        ))
        self.graph.add_edge(ThoughtEdge(
            node_id,
            self._check_id,
            ThoughtEdgeKind.DEPENDS_ON,
            note="decision requires the current evidence check",
        ))
        return node_id

    def record_action(
        self,
        action_id: str,
        tool_name: str,
        *,
        approval_required: bool = False,
        evidence_ids: Iterable[str] = (),
    ) -> str:
        """Record an action intent; this does not dispatch or authorize it."""
        node_id = f"action:{self.turn_id}:{action_id}"
        self.graph.add_node(ThoughtNode(
            node_id,
            ThoughtNodeKind.ACTION,
            self._summary(f"{tool_name} ({action_id})", 300),
            source=self.role,
            evidence_ids=tuple(evidence_ids),
            status="approval_required" if approval_required else "proposed",
        ))
        decision_id = f"decision:{self.turn_id}"
        if decision_id in self.graph.nodes:
            self.graph.add_edge(ThoughtEdge(
                node_id,
                decision_id,
                ThoughtEdgeKind.DERIVED_FROM,
                note="action remains subject to authorization",
            ))
        return node_id

    def record_execution(self, action_id: str, status: str, summary: str) -> str:
        """Record dispatcher-confirmed execution separately from the proposal."""
        node_id = f"execution:{self.turn_id}:{action_id}"
        self.graph.add_node(ThoughtNode(
            node_id,
            ThoughtNodeKind.OBSERVATION,
            self._summary(summary, 400),
            source="dispatcher",
            status=self._summary(status, 80),
        ))
        action_id_full = f"action:{self.turn_id}:{action_id}"
        if action_id_full in self.graph.nodes:
            self.graph.add_edge(ThoughtEdge(
                node_id,
                action_id_full,
                ThoughtEdgeKind.DERIVED_FROM,
                note="execution status comes from the dispatcher",
            ))
        return node_id

    # ── Branch expansion (Tree / Graph-of-Thoughts) ─────────────────────────
    def expand_branches(
        self,
        candidates: Iterable["BranchCandidate | Mapping[str, Any]"],
    ) -> list[str]:
        """Expand the turn into multiple candidate OPTION nodes (GoT branching).

        Bounded by ``self.pattern.max_branches`` (default 1). When the pattern
        allows only one branch (e.g. direct_dialogue), this is a no-op and the
        turn keeps its single linear option — so existing behaviour is unchanged
        for non-branching patterns.

        Each candidate becomes an OPTION node that:
          * DERIVED_FROM the goal (branches visibly stem from the goal),
          * DEPENDS_ON the evidence check (a branch must respect current evidence),
          * is SUPPORTED by a HYPOTHESIS child carrying its rationale + evidence
            (so ``measure_support`` propagates the branch's evidence into its score).

        Returns the created OPTION node ids (empty when the pattern disallows
        branching or no candidates were supplied).
        """
        limit = max(1, int(getattr(self.pattern, "max_branches", 1) or 1))
        normalized: list[BranchCandidate] = []
        for raw in candidates or ():
            if isinstance(raw, BranchCandidate):
                normalized.append(raw)
            elif isinstance(raw, Mapping):
                normalized.append(BranchCandidate(
                    text=str(raw.get("text", "")),
                    rationale=str(raw.get("rationale", "")),
                    evidence_ids=tuple(raw.get("evidence_ids", ()) or ()),
                    expected_payout=raw.get("expected_payout"),
                    effort=str(raw.get("effort", "")),
                    risk=str(raw.get("risk", "")),
                ))
            if len(normalized) >= limit:
                break
        if limit <= 1 or len(normalized) < 2:
            # Not a branching turn: keep the single linear option.
            return []
        created: list[str] = []
        for index, cand in enumerate(normalized):
            option_id = f"branch:{self.turn_id}:{index}"
            self.graph.add_node(ThoughtNode(
                option_id, ThoughtNodeKind.OPTION,
                self._summary(cand.summary(), 400),
                source=self.role,
                evidence_ids=tuple(cand.evidence_ids),
                status="proposed",
            ))
            self.graph.add_edge(ThoughtEdge(
                option_id, self._goal_id, ThoughtEdgeKind.DERIVED_FROM,
                note="candidate branch derived from the goal"))
            self.graph.add_edge(ThoughtEdge(
                option_id, self._check_id, ThoughtEdgeKind.DEPENDS_ON,
                note="branch must respect current evidence"))
            # A rationale/evidence child so the branch's evidence propagates into
            # its support score via measure_support().
            hyp_id = f"hypothesis:{self.turn_id}:{index}"
            hyp_text = cand.rationale or cand.text
            self.graph.add_node(ThoughtNode(
                hyp_id, ThoughtNodeKind.HYPOTHESIS,
                self._summary(hyp_text, 400),
                source=self.role,
                evidence_ids=tuple(cand.evidence_ids),
                status="proposed",
            ))
            self.graph.add_edge(ThoughtEdge(
                hyp_id, option_id, ThoughtEdgeKind.SUPPORTS,
                note="rationale/evidence supports this candidate branch"))
            created.append(option_id)
        self._branch_ids = created
        return created

    def score_branches(
        self,
        evidence_by_id: Mapping[str, Any] | None = None,
    ) -> list[SupportMeasure]:
        """Rank the expanded branches by deterministic evidence-backed support.

        Uses ``ThoughtGraph.rank_options`` (action_eligible > supported >
        uncontradicted > score). Stores and returns the ranked measures, best
        first. Returns [] when the turn has no branches.
        """
        if not self._branch_ids:
            return []
        self._branch_scores = self.graph.rank_options(
            self._branch_ids, evidence_by_id)
        return self._branch_scores

    def select_branch(self) -> str | None:
        """Record a scored DECISION that selects the best-ranked branch.

        Requires score_branches() to have run. Marks non-selected branches
        "rejected" and records a DECISION node naming the winner, its score and
        recommendation. Returns the decision node id, or None if there are no
        scored branches.
        """
        if not self._branch_scores:
            return None
        best = self._branch_scores[0]
        chosen = best.node_id
        best_node = self.graph.nodes.get(chosen)
        chosen_text = best_node.text if best_node else chosen
        score = round(best.direct_support + best.propagated_support, 3)
        self.graph.add_node(ThoughtNode(
            self._decision_id, ThoughtNodeKind.DECISION,
            self._summary(
                f"Selected branch: {chosen_text} "
                f"(score={score}, {best.recommendation})", 400),
            source=self.role,
            status="selected",
        ))
        self.graph.add_edge(ThoughtEdge(
            self._decision_id, chosen, ThoughtEdgeKind.DERIVED_FROM,
            note="decision selects the highest-ranked branch"))
        self.graph.add_edge(ThoughtEdge(
            self._decision_id, self._check_id, ThoughtEdgeKind.DEPENDS_ON,
            note="selection respects the current evidence check"))
        for measure in self._branch_scores[1:]:
            if measure.node_id in self.graph.nodes:
                self.graph.update_node(measure.node_id, status="rejected")
        self._selected_branch_id = chosen
        return self._decision_id

    @property
    def is_branching(self) -> bool:
        """Whether this turn expanded into multiple candidate branches."""
        return bool(self._branch_ids)

    @staticmethod
    def _summary(value: Any, limit: int = 800) -> str:
        text = " ".join(str(value or "").split())
        return text[:limit] or "No request supplied"

    def record_tool_trace(self, trace: Iterable[Mapping[str, Any]] | None) -> None:
        for index, entry in enumerate(trace or ()):
            name = self._summary(entry.get("name", "tool"), 120)
            status = self._summary(entry.get("status", "unknown"), 80)
            node_id = f"tool:{self.turn_id}:{index}"
            self.graph.add_node(ThoughtNode(
                node_id, ThoughtNodeKind.OBSERVATION,
                f"{name} returned status={status}",
                source=self.role, status=status))
            self.graph.add_edge(ThoughtEdge(
                node_id, self._check_id, ThoughtEdgeKind.DERIVED_FROM,
                note="tool trace is observable context, not verification by itself"))

    def finish(self, response: str, status: str = "completed") -> dict:
        self.record_tool_trace([])
        final_status = self._summary(status, 80)
        self.graph.update_node(
            self._option_id,
            status="completed" if final_status == "completed" else final_status,
            text=f"{self.role} response status={final_status}")
        self.graph.update_node(
            self._check_id,
            status="completed" if final_status == "completed" else "unresolved")
        outcome_id = f"outcome:{self.turn_id}"
        self.graph.add_node(ThoughtNode(
            outcome_id, ThoughtNodeKind.OUTCOME,
            f"Response produced: {self._summary(response, 240)}",
            source=self.role, status=final_status))
        self.graph.add_edge(ThoughtEdge(
            outcome_id, self._option_id, ThoughtEdgeKind.DERIVED_FROM,
            note="outcome records response status only"))
        # On a branching turn, the outcome also derives from the scored decision
        # so the chain reflects the chosen branch, not just the generic option.
        if self._selected_branch_id and self._decision_id in self.graph.nodes:
            self.graph.add_edge(ThoughtEdge(
                outcome_id, self._decision_id, ThoughtEdgeKind.DERIVED_FROM,
                note="outcome follows the selected branch decision"))
        branch_summary = None
        if self.is_branching:
            branch_summary = {
                "branches": len(self._branch_ids),
                "selected": self._selected_branch_id,
                "ranking": [
                    {
                        "node_id": m.node_id,
                        "score": round(m.direct_support + m.propagated_support, 3),
                        "recommendation": m.recommendation,
                        "action_eligible": m.action_eligible,
                    }
                    for m in self._branch_scores
                ],
            }
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "status": final_status,
            "pattern": {
                "name": self.pattern.pattern.value,
                "rationale": self.pattern.rationale,
                "max_branches": self.pattern.max_branches,
                "max_tool_calls": self.pattern.max_tool_calls,
                "checkpoint_required": self.pattern.checkpoint_required,
                "approval_required": self.pattern.approval_required,
            },
            "branching": self.is_branching,
            "branch_summary": branch_summary,
            "graph": self.graph.to_dict(),
        }


def start_brain_turn(
    role: str,
    goal: str,
    pattern: PatternSelection | None = None,
) -> BrainTurnGraph:
    return BrainTurnGraph(role, goal, pattern=pattern)


__all__ = ["BrainTurnGraph", "BranchCandidate", "start_brain_turn"]
