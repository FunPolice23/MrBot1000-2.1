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

Goals are persisted to SQLite, reported into the event logger, and CREDITED
from it: ARCH-ENG-244 wired the tracker to the production event stream
(main.py forwards every logged event to process_event) and gave the
operator a management surface — the Management tab's Earning Goals card is
the only place goals are created, paused and viewed. Credits flow through
add_evidence only, whose verified-guard is the single decision that moves
money (BF-02): a credit exists if and only if the evidence row is verified
and its amount is positive.
"""
from __future__ import annotations

import json
import os
import sqlite3
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
    """Manages goals — create, update, add evidence, track progress.

    All goals and evidence are persisted to SQLite.
    """

    _instance: Optional["GoalTracker"] = None
    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(
            os.environ.get("LOCALAPPDATA", "."), "MrBot1000", "goals.db"
        )
        # Use a shared in-memory database so all connections see the
        # same tables (plain ":memory:" is per-connection in SQLite).
        self._connect_path = (
            "file::memory:?cache=shared" if self.db_path == ":memory:"
            else self.db_path
        )
        self._ensure_dir()
        self._init_db()

    @classmethod
    def instance(cls) -> "GoalTracker":
        if cls._instance is None:
            cls._instance = cls.__new__(cls)
            cls._instance.__init__()
        return cls._instance

    def _ensure_dir(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not db_dir.startswith(":"):
            os.makedirs(db_dir, exist_ok=True)

    def _connect(self):
        """Return a sqlite3 connection using the shared in-memory
        URI when applicable, otherwise a plain file connection."""
        return sqlite3.connect(
            "file::memory:?cache=shared" if self.db_path == ":memory:"
            else self.db_path,
            uri=self.db_path == ":memory:",
        )

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    path TEXT NOT NULL DEFAULT 'other',
                    target_usd REAL NOT NULL DEFAULT 0.0,
                    current_usd REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'active',
                    budget_usd REAL NOT NULL DEFAULT 0.0,
                    created_at REAL NOT NULL DEFAULT 0.0,
                    deadline REAL,
                    completed_at REAL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    amount_usd REAL NOT NULL DEFAULT 0.0,
                    url TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    verified INTEGER NOT NULL DEFAULT 0,
                    ts REAL NOT NULL DEFAULT 0.0,
                    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_evidence_goal_id
                ON evidence(goal_id)
            """)
            conn.commit()

    # ── CRUD ─────────────────────────────────────────────────────────────

    def create(self, goal: Goal) -> Goal:
        """Create a new goal."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO goals (id, title, description, path, target_usd, "
                "current_usd, status, budget_usd, created_at, deadline, "
                "completed_at, tags, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    goal.id, goal.title, goal.description, goal.path,
                    goal.target_usd, goal.current_usd, goal.status,
                    goal.budget_usd, goal.created_at, goal.deadline,
                    goal.completed_at, json.dumps(goal.tags),
                    json.dumps(goal.metadata),
                ),
            )
            conn.commit()
        return goal

    def get(self, goal_id: str) -> Optional[Goal]:
        """Get a goal by ID."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM goals WHERE id = ?", (goal_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_goal(row)

    def list_active(self) -> List[Goal]:
        """List all active goals."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM goals WHERE status = 'active' ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def list_all(self) -> List[Goal]:
        """List all goals."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM goals ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def update(self, goal: Goal) -> Goal:
        """Update a goal."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE goals SET title=?, description=?, path=?, target_usd=?, "
                "current_usd=?, status=?, budget_usd=?, created_at=?, deadline=?, "
                "completed_at=?, tags=?, metadata=? WHERE id=?",
                (
                    goal.title, goal.description, goal.path,
                    goal.target_usd, goal.current_usd, goal.status,
                    goal.budget_usd, goal.created_at, goal.deadline,
                    goal.completed_at, json.dumps(goal.tags),
                    json.dumps(goal.metadata), goal.id,
                ),
            )
            conn.commit()
        return goal

    def delete(self, goal_id: str) -> bool:
        """Delete a goal."""
        with self._connect() as conn:
            conn.execute("DELETE FROM evidence WHERE goal_id = ?", (goal_id,))
            conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
            conn.commit()
        return True

    # ── Evidence ─────────────────────────────────────────────────────────

    def add_evidence(self, goal_id: str, evidence: EvidenceRow) -> EvidenceRow:
        """Add an evidence row to a goal and update current_usd."""
        evidence.goal_id = goal_id
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evidence (id, goal_id, type, source, amount_usd, "
                "url, description, verified, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence.id, evidence.goal_id, evidence.type, evidence.source,
                    evidence.amount_usd, evidence.url, evidence.description,
                    1 if evidence.verified else 0, evidence.ts,
                ),
            )
            # Update goal's current_usd if evidence is verified and has an amount
            if evidence.verified and evidence.amount_usd > 0:
                conn.execute(
                    "UPDATE goals SET current_usd = current_usd + ? WHERE id = ?",
                    (evidence.amount_usd, goal_id),
                )
            conn.commit()
        return evidence

    def list_evidence(self, goal_id: str) -> List[EvidenceRow]:
        """List all evidence for a goal."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM evidence WHERE goal_id = ? ORDER BY ts DESC",
                (goal_id,),
            ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    # ── Progress ─────────────────────────────────────────────────────────

    # ARCH-ENG-244 (BF-02): `add_earnings` is DELETED. Its docstring claimed
    # "Add verified earnings to a goal" while its body was a bare
    # `UPDATE goals SET current_usd = current_usd + ?` — the verified-guard
    # the contract needed sat 35 lines away in the then-dead `add_evidence`,
    # and two spellings of one money decision sat 35 lines apart (11Q).
    # There is now exactly ONE credit path: add_evidence, whose guard
    # (`verified and amount_usd > 0`) is the single decision that moves
    # money. Event-driven credits (process_event) go through it.

    def check_completion(self, goal_id: str):
        """Check if a goal is completed and update status."""
        goal = self.get(goal_id)
        if goal is None:
            return
        if goal.status != GoalStatus.ACTIVE.value:
            return
        if goal.target_usd > 0 and goal.current_usd >= goal.target_usd:
            goal.status = GoalStatus.COMPLETED.value
            goal.completed_at = time.time()
            self.update(goal)

    # ── Summary ──────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for the GUI."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM goals WHERE status = 'active'"
            ).fetchone()[0]
            completed = conn.execute(
                "SELECT COUNT(*) FROM goals WHERE status = 'completed'"
            ).fetchone()[0]
            total_earned = conn.execute(
                "SELECT COALESCE(SUM(current_usd), 0.0) FROM goals"
            ).fetchone()[0]
            total_target = conn.execute(
                "SELECT COALESCE(SUM(target_usd), 0.0) FROM goals"
            ).fetchone()[0]
        overall_progress = 0.0
        if total_target > 0:
            overall_progress = min(100.0, (total_earned / total_target) * 100)
        return {
            "total_goals": total,
            "active_goals": active,
            "completed_goals": completed,
            "total_earned": round(total_earned, 2),
            "total_target": round(total_target, 2),
            "overall_progress": round(overall_progress, 1),
        }

    # ── Event processing (live: main.py forwards every logged event here) ─

    def process_event(self, event) -> None:
        """Process an event from the event logger and credit matching goals.

        Called for every logged event (from main.py's event-logger hook).
        This is ARCH-ENG-244's REAL contract: the production stream is
        ARCH-ENG-243's typed earning event (event_type "earning", details
        carrying revenue/cost/platform/success, action "finalized:<state>").
        The previous version invented a vocabulary ('earning.freelance',
        details['amount_usd']) that no live event ever used -- BF-03's
        recorded seam -- and its auto-match could credit a goal by a path
        string an event never carried.

        Crediting rules -- add_evidence is the ONLY credit path and keeps
        its verified-guard (BF-02), so a credit exists if and only if the
        evidence row is verified and its amount is positive:

        - amount comes from details["revenue"], the lifecycle's
          VERIFIED-EFFECTIVE value: a payment the ledger could not verify
          arrives as revenue 0, so the tracker can never credit an
          unverified dollar.
        - evidence rows: every goal-BOUND finalized outcome is RECORDed.
          It credits (verified=True) only when the effective state is
          "paid" (the verified-payment state); every other state is
          recorded with verified=False and never moves current_usd.
        - binding: an explicit details["goal_id"] or a "goal:<id>" tag
          binds the event to one goal. Without a binding, a paid finalize
          credits the first ACTIVE goal whose metadata.platforms declares
          the event's platform (operator-declared in the Management tab's
          Earning Goals card). With no explicit and no declared binding,
          the tracker does NOT guess what an unbound amount belongs to --
          no credit.
        """
        if not event or not hasattr(event, 'event_type'):
            return
        if getattr(event, 'event_type', '') != 'earning':
            return

        details = getattr(event, 'details', {}) or {}
        action = str(details.get('action', '') or '')
        if not action.startswith('finalized:'):
            return
        state = action.split(':', 1)[1].strip().lower()
        try:
            amount = float(details.get('revenue', 0.0) or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        platform = str(details.get('platform', '') or '')
        tags = getattr(event, 'tags', []) or []

        goal_id = details.get('goal_id')
        if not goal_id:
            for tag in tags:
                if isinstance(tag, str) and tag.startswith('goal:'):
                    goal_id = tag[len('goal:'):]
                    break

        if goal_id:
            # Explicit binding: record the outcome; credit only a verified
            # payment (the lifecycle's effective state is the authority).
            creditable = (state == 'paid' and amount > 0)
            self.add_evidence(goal_id, EvidenceRow(
                type='earning_event',
                source=platform or 'earning-event',
                amount_usd=amount,
                description=action,
                verified=creditable,
            ))
            self.check_completion(goal_id)
        elif state == 'paid' and amount > 0 and platform:
            # Operator-declared platform binding: the goal's
            # metadata.platforms names the platforms that count toward it.
            # No declared binding -> no credit: an unbound amount is not
            # something the tracker assigns by guesswork.
            want = platform.strip().lower()
            for goal in self.list_active():
                declared = [
                    str(p).strip().lower()
                    for p in (goal.metadata or {}).get('platforms', [])
                ]
                if want in declared:
                    self.add_evidence(goal.id, EvidenceRow(
                        type='earning_event', source=platform,
                        amount_usd=amount,
                        description=f'{action} (platform binding)',
                        verified=True,
                    ))
                    self.check_completion(goal.id)
                    break

    # ── Internal helpers ─────────────────────────────────────────────────

    def _row_to_goal(self, row: sqlite3.Row) -> Goal:
        return Goal(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            path=row["path"],
            target_usd=row["target_usd"],
            current_usd=row["current_usd"],
            status=row["status"],
            budget_usd=row["budget_usd"],
            created_at=row["created_at"],
            deadline=row["deadline"],
            completed_at=row["completed_at"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def _row_to_evidence(self, row: sqlite3.Row) -> EvidenceRow:
        return EvidenceRow(
            id=row["id"],
            goal_id=row["goal_id"],
            type=row["type"],
            source=row["source"],
            amount_usd=row["amount_usd"],
            url=row["url"],
            description=row["description"],
            verified=bool(row["verified"]),
            ts=row["ts"],
        )


__all__ = [
    "GoalTracker",
    "Goal",
    "EvidenceRow",
    "GoalStatus",
    "GoalPath",
]
