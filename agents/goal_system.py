"""agents/goal_system.py — Goal tracking for MrBot1000 earning tasks.

A Goal is a verifiable unit of earning work. Examples:
- "Earn $10 on Upwork this week"
- "Complete 5 Prolific studies"
- "Find 3 bounty opportunities on GitHub"
- "Backtest 2 trading strategies"

Each goal has:
- target_usd: the monetary target
- current_usd: verified earnings so far
- evidence: list of verifiable proof rows
- status: active | completed | failed | paused
- path: which earning path (freelance, microtask, crypto, bounty, trading)
- budget_usd: max LLM spend allowed for this goal
- deadline: optional timestamp

Goals are persisted to SQLite and reported into the event logger.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class GoalStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class GoalPath(str, Enum):
    FREELANCE = "freelance"
    MICROTASK = "microtask"
    CRYPTO = "crypto"
    BOUNTY = "bounty"
    TRADING = "trading"
    CONTENT = "content"
    OTHER = "other"


@dataclass
class EvidenceRow:
    """A single piece of verifiable proof for a goal."""
    id: str = ""
    goal_id: str = ""
    type: str = ""           # opportunity_found, proposal_sent, payment_received, work_submitted
    source: str = ""         # upwork, prolific, gitcoin, etc.
    amount_usd: float = 0.0
    url: str = ""
    description: str = ""
    verified: bool = False   # human-verified or auto-verified
    ts: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex
        if self.ts == 0.0:
            self.ts = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "type": self.type,
            "source": self.source,
            "amount_usd": self.amount_usd,
            "url": self.url,
            "description": self.description,
            "verified": self.verified,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidenceRow":
        return cls(
            id=d.get("id", ""),
            goal_id=d.get("goal_id", ""),
            type=d.get("type", ""),
            source=d.get("source", ""),
            amount_usd=d.get("amount_usd", 0.0),
            url=d.get("url", ""),
            description=d.get("description", ""),
            verified=d.get("verified", False),
            ts=d.get("ts", 0.0),
        )


@dataclass
class Goal:
    """A single earning goal."""
    id: str = ""
    title: str = ""
    description: str = ""
    path: str = GoalPath.OTHER.value
    target_usd: float = 0.0
    current_usd: float = 0.0
    status: str = GoalStatus.ACTIVE.value
    budget_usd: float = 0.0
    created_at: float = 0.0
    deadline: Optional[float] = None
    completed_at: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex
        if self.created_at == 0.0:
            self.created_at = time.time()

    @property
    def progress_pct(self) -> float:
        if self.target_usd <= 0:
            return 0.0
        return min(100.0, (self.current_usd / self.target_usd) * 100)

    @property
    def is_overdue(self) -> bool:
        if self.deadline is None:
            return False
        return time.time() > self.deadline and self.status == GoalStatus.ACTIVE.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "path": self.path,
            "target_usd": self.target_usd,
            "current_usd": self.current_usd,
            "status": self.status,
            "budget_usd": self.budget_usd,
            "created_at": self.created_at,
            "deadline": self.deadline,
            "completed_at": self.completed_at,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Goal":
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            path=d.get("path", GoalPath.OTHER.value),
            target_usd=d.get("target_usd", 0.0),
            current_usd=d.get("current_usd", 0.0),
            status=d.get("status", GoalStatus.ACTIVE.value),
            budget_usd=d.get("budget_usd", 0.0),
            created_at=d.get("created_at", 0.0),
            deadline=d.get("deadline"),
            completed_at=d.get("completed_at"),
            tags=d.get("tags", []),
            metadata=d.get("metadata", {}),
        )


class GoalTracker:
    """Manages goals — create, update, add evidence, track progress."""

    _instance: Optional["GoalTracker"] = None

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(
            os.environ.get("LOCALAPPDATA", "."), "MrBot1000", "goals.db"
        )
        self._ensure_dir()

    @classmethod
    def instance(cls) -> "GoalTracker":
        if cls._instance is None:
            cls._instance = cls.__new__(cls)
            cls._instance.__init__()
        return cls._instance

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    # ── CRUD ─────────────────────────────────────────────────────────────

    def create(self, goal: Goal) -> Goal:
        """Create a new goal."""
        # TODO: persist to SQLite
        return goal

    def get(self, goal_id: str) -> Optional[Goal]:
        """Get a goal by ID."""
        return None

    def list_active(self) -> List[Goal]:
        """List all active goals."""
        return []

    def list_all(self) -> List[Goal]:
        """List all goals."""
        return []

    def update(self, goal: Goal) -> Goal:
        """Update a goal."""
        return goal

    def delete(self, goal_id: str) -> bool:
        """Delete a goal."""
        return True

    # ── Evidence ─────────────────────────────────────────────────────────

    def add_evidence(self, goal_id: str, evidence: EvidenceRow) -> EvidenceRow:
        """Add an evidence row to a goal and update current_usd."""
        evidence.goal_id = goal_id
        return evidence

    def list_evidence(self, goal_id: str) -> List[EvidenceRow]:
        """List all evidence for a goal."""
        return []

    # ── Progress ─────────────────────────────────────────────────────────

    def add_earnings(self, goal_id: str, amount_usd: float, source: str = ""):
        """Add verified earnings to a goal."""
        pass

    def check_completion(self, goal_id: str):
        """Check if a goal is completed and update status."""
        pass

    # ── Summary ──────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for the GUI."""
        return {
            "total_goals": 0,
            "active_goals": 0,
            "completed_goals": 0,
            "total_earned": 0.0,
            "total_target": 0.0,
            "overall_progress": 0.0,
        }


__all__ = [
    "GoalTracker",
    "Goal",
    "EvidenceRow",
    "GoalStatus",
    "GoalPath",
]
