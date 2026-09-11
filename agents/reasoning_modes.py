"""Reasoning-mode policy for dual-brain tasks.

Modes are orchestration policies, not claims about private model reasoning. The
router keeps ordinary Dialogue short and selects more expensive structures only
when the task warrants them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReasoningMode(str, Enum):
    DIRECT = "direct"
    REACT = "react"
    SKELETON = "skeleton"
    TREE = "tree"
    GRAPH = "graph"


@dataclass(frozen=True)
class ModePolicy:
    mode: ReasoningMode
    retrieve_evidence: bool = False
    max_candidates: int = 1
    max_tool_rounds: int = 0

    @property
    def instruction(self) -> str:
        instructions = {
            ReasoningMode.DIRECT: (
                "Answer directly in 2-5 sentences. Do not expose private reasoning."
            ),
            ReasoningMode.REACT: (
                "Use a short evidence loop: identify the missing fact, call one "
                "read-only tool now, inspect its result, then state what is verified "
                "and what remains uncertain. Do not claim a search happened unless "
                "the tool returned a result."
            ),
            ReasoningMode.SKELETON: (
                "Start with a compact 3-5 step outline, then expand only the next "
                "step that is needed. Keep assumptions and approval gates explicit."
            ),
            ReasoningMode.TREE: (
                "Generate at most three materially different options, score each "
                "against payout, effort, risk, and evidence quality, then recommend "
                "one option. Do not execute an option before approval."
            ),
            ReasoningMode.GRAPH: (
                "Represent the task as dependencies: goal, evidence nodes, decision "
                "nodes, approval gates, and execution nodes. Resolve the next blocked "
                "dependency only; do not jump to execution."
            ),
        }
        return instructions[self.mode]


def select_reasoning_mode(
    task: str,
    *,
    requires_research: bool = False,
    candidate_count: int = 0,
    dependency_count: int = 0,
) -> ModePolicy:
    """Select a bounded orchestration policy from task shape.

    This deliberately uses transparent signals. It is a routing hint, not an
    LLM-authored decision, and callers can override it for a known workflow.
    """
    text = (task or "").lower()
    if dependency_count >= 3 or any(
        token in text for token in ("dependencies", "workflow", "multi-stage", "coordinate")
    ):
        return ModePolicy(ReasoningMode.GRAPH, retrieve_evidence=True, max_tool_rounds=1)
    if candidate_count >= 2 or any(
        token in text for token in ("compare", "alternatives", "options", "best platform")
    ):
        return ModePolicy(ReasoningMode.TREE, retrieve_evidence=True, max_candidates=3)
    if requires_research or any(
        token in text for token in ("verify", "research", "current", "listing", "skill.md", "evidence")
    ):
        return ModePolicy(ReasoningMode.REACT, retrieve_evidence=True, max_tool_rounds=1)
    if any(
        token in text for token in ("plan", "roadmap", "steps", "implement")
    ):
        return ModePolicy(ReasoningMode.SKELETON, retrieve_evidence=True)
    return ModePolicy(ReasoningMode.DIRECT)


__all__ = ["ModePolicy", "ReasoningMode", "select_reasoning_mode"]
