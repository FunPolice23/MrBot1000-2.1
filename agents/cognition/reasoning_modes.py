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


class ReasoningPattern(str, Enum):
    """Bounded orchestration patterns, not private model reasoning."""

    DIRECT_DIALOGUE = "direct_dialogue"
    REACT = "react"
    TREE_OF_THOUGHTS = "tree_of_thoughts"
    GRAPH_OF_THOUGHTS = "graph_of_thoughts"
    LATS = "lats"
    EPISODIC_MEMORY = "episodic_memory"
    TOOL_DISCOVERY = "tool_discovery"
    PARALLEL_TOOLS = "parallel_tools"
    CHECKPOINT_LOOP = "checkpoint_loop"
    SPECIFICATION_DRIVEN = "specification_driven"
    WORKFLOW_EVAL = "workflow_eval"
    MEMORY_SYNTHESIS = "memory_synthesis"
    LLM_OBSERVABILITY = "llm_observability"


@dataclass(frozen=True)
class PatternSelection:
    pattern: ReasoningPattern
    rationale: str
    max_branches: int = 1
    max_tool_calls: int = 0
    checkpoint_required: bool = False
    approval_required: bool = False


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


def select_reasoning_pattern(
    task: str,
    *,
    requires_research: bool = False,
    candidate_count: int = 0,
    dependency_count: int = 0,
    tool_count: int = 0,
    needs_memory: bool = False,
    risk: str = "low",
    long_running: bool = False,
) -> PatternSelection:
    """Select one bounded pattern from transparent task-shape signals.

    The result controls orchestration limits only. It never decides whether an
    external action is authorized; that remains the dispatcher and evidence
    policy's responsibility.
    """
    text = (task or "").lower()
    normalized_risk = str(risk or "low").lower()
    if any(token in text for token in ("benchmark", "evaluate workflow", "acceptance test", "mocked tool")):
        return PatternSelection(
            ReasoningPattern.WORKFLOW_EVAL,
            "the task requests measurable evaluation before production use",
            max_tool_calls=2,
            checkpoint_required=True,
        )
    if any(token in text for token in ("specification", "acceptance criteria", "requirements")):
        return PatternSelection(
            ReasoningPattern.SPECIFICATION_DRIVEN,
            "explicit requirements should constrain implementation and validation",
            max_tool_calls=1,
            checkpoint_required=True,
        )
    if any(token in text for token in ("summarize execution logs", "synthesize memory", "lessons learned")):
        return PatternSelection(
            ReasoningPattern.MEMORY_SYNTHESIS,
            "execution history must be summarized before promoting a lesson",
            max_tool_calls=1,
        )
    if any(token in text for token in ("trace", "latency", "cost", "observability")):
        return PatternSelection(
            ReasoningPattern.LLM_OBSERVABILITY,
            "the task requires linked model, tool, and outcome telemetry",
            max_tool_calls=1,
        )
    if long_running:
        return PatternSelection(
            ReasoningPattern.CHECKPOINT_LOOP,
            "long-running work requires resumable checkpoints",
            max_tool_calls=3,
            checkpoint_required=True,
            approval_required=normalized_risk in {"medium", "high"},
        )
    if dependency_count >= 3 or any(
        token in text for token in ("dependencies", "workflow", "multi-stage", "coordinate")
    ):
        return PatternSelection(
            ReasoningPattern.GRAPH_OF_THOUGHTS,
            "interdependent steps benefit from explicit dependency edges",
            max_branches=3,
            max_tool_calls=2,
            approval_required=normalized_risk in {"medium", "high"},
        )
    if normalized_risk == "high" and candidate_count >= 2:
        return PatternSelection(
            ReasoningPattern.LATS,
            "high-risk alternatives need bounded search and verification",
            max_branches=3,
            max_tool_calls=2,
            approval_required=True,
        )
    if candidate_count >= 2 or any(
        token in text for token in ("compare", "alternatives", "options", "best platform")
    ):
        return PatternSelection(
            ReasoningPattern.TREE_OF_THOUGHTS,
            "multiple alternatives should be compared before selection",
            max_branches=3,
            max_tool_calls=1,
        )
    if tool_count >= 2:
        return PatternSelection(
            ReasoningPattern.PARALLEL_TOOLS,
            "independent read-only tools can be evaluated concurrently",
            max_tool_calls=min(tool_count, 3),
        )
    if needs_memory:
        return PatternSelection(
            ReasoningPattern.EPISODIC_MEMORY,
            "past verified outcomes may improve the current decision",
            max_tool_calls=1,
        )
    if requires_research or any(
        token in text for token in ("verify", "research", "current", "listing", "evidence")
    ):
        return PatternSelection(
            ReasoningPattern.REACT,
            "a missing fact should be retrieved and checked before responding",
            max_tool_calls=1,
        )
    if any(token in text for token in ("discover tool", "available tool", "capability")):
        return PatternSelection(
            ReasoningPattern.TOOL_DISCOVERY,
            "the task requires capability discovery before invocation",
            max_tool_calls=1,
        )
    return PatternSelection(
        ReasoningPattern.DIRECT_DIALOGUE,
        "small conversational work does not warrant branching",
    )


__all__ = [
    "ModePolicy",
    "PatternSelection",
    "ReasoningMode",
    "ReasoningPattern",
    "select_reasoning_mode",
    "select_reasoning_pattern",
]
