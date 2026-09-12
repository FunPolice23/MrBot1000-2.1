"""Bounded, evidence-aware discussion protocol for dual-brain collaboration."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Set


class DiscussionStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


class DiscussionPurpose(str, Enum):
    PROPOSE = "propose"
    VERIFY = "verify"
    CHALLENGE = "challenge"
    REVISE = "revise"
    CONCLUDE = "conclude"


@dataclass(frozen=True)
class DiscussionTurn:
    speaker: str
    purpose: DiscussionPurpose
    summary: str
    evidence_ids: List[str] = field(default_factory=list)
    changed_decision: bool = False
    requests_next_step: str = ""
    turn_id: str = field(default_factory=lambda: "dt_" + uuid.uuid4().hex[:20])
    created_at: float = field(default_factory=time.time)


class BoundedDiscussion:
    """Coordinate a finite exchange without treating conversation as authority."""

    def __init__(self, goal: str, *, max_turns: int = 6):
        if not goal.strip():
            raise ValueError("goal is required")
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self.goal = goal
        self.max_turns = max_turns
        self.status = DiscussionStatus.ACTIVE
        self.turns: List[DiscussionTurn] = []
        self.blocked_reason = ""
        self.resolution = ""

    @property
    def remaining_turns(self) -> int:
        return max(0, self.max_turns - len(self.turns))

    @property
    def evidence_ids(self) -> Set[str]:
        return {evidence_id for turn in self.turns for evidence_id in turn.evidence_ids}

    def add_turn(self, turn: DiscussionTurn) -> bool:
        """Accept one turn, rejecting turns after terminal state or budget."""
        if self.status is not DiscussionStatus.ACTIVE:
            return False
        if len(self.turns) >= self.max_turns:
            self.status = DiscussionStatus.BUDGET_EXHAUSTED
            return False
        if not turn.speaker.strip() or not turn.summary.strip():
            raise ValueError("speaker and summary are required")

        previous_evidence = self.evidence_ids
        if (turn.purpose is DiscussionPurpose.CHALLENGE
                and not set(turn.evidence_ids) - previous_evidence):
            self.blocked_reason = "challenge requires new evidence"
            return False

        self.turns.append(turn)
        if turn.purpose is DiscussionPurpose.CONCLUDE:
            self.status = DiscussionStatus.RESOLVED
            self.resolution = turn.summary
        elif len(self.turns) >= self.max_turns:
            self.status = DiscussionStatus.BUDGET_EXHAUSTED
        return True

    def block(self, reason: str) -> None:
        if self.status is DiscussionStatus.ACTIVE:
            self.status = DiscussionStatus.BLOCKED
            self.blocked_reason = reason.strip() or "discussion blocked"

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "max_turns": self.max_turns,
            "status": self.status.value,
            "blocked_reason": self.blocked_reason,
            "resolution": self.resolution,
            "turns": [turn.__dict__ for turn in self.turns],
        }


__all__ = ["BoundedDiscussion", "DiscussionPurpose", "DiscussionStatus", "DiscussionTurn"]