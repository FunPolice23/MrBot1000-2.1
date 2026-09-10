"""agents/opportunity_portfolio.py — persistent Opportunity Portfolio & Work Queue (v2.0.36h).

A higher-level work-management layer on top of the existing OpportunityLifecycleTracker.

The existing lifecycle (`_ALLOWED_TRANSITIONS`, `mark_final_outcome`, evidence-gated
`mark_paid_verified`) REMAINS AUTHORITATIVE for valid transitions. This portfolio tracks a
richer WorkStatus vocabulary (16 states), persists to sqlite for recovery after restart, and
delegates any lifecycle-affecting move to the lifecycle tracker. One-way coupling: portfolio →
lifecycle only. No import of portfolio inside lifecycle, so existing lifecycle tests stay green.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set


# ── Exceptions ────────────────────────────────────────────────────────────────

class IllegalTransitionError(Exception):
    """Raided when a WorkStatus or lifecycle transition is invalid."""


# ── WorkStatus enum (16 states) ────────────────────────────────────────────────

class WorkStatus(str, Enum):
    """Portfolio-level work status. Richer than the lifecycle stage vocabulary.

    Each WorkStatus maps to a lifecycle stage (see WorkStatusConfig.WORK_TO_LIFECYCLE).
    The lifecycle stays authoritative: a WorkStatus change that implies a lifecycle stage
    change is rejected if _ALLOWED_TRANSITIONS disallows it.
    """
    NEW = "NEW"
    EVALUATING = "EVALUATING"
    QUALIFIED = "QUALIFIED"
    RECOMMENDED = "RECOMMENDED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    COMPLETED = "COMPLETED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ABANDONED = "ABANDONED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES


_TERMININAL_STATUSES = frozenset({
    WorkStatus.PAID, WorkStatus.FAILED, WorkStatus.REJECTED,
    WorkStatus.EXPIRED, WorkStatus.ABANDONED,
})
_TERMINAL_STATUSES = _TERMININAL_STATUSES  # convenience alias


# ── WorkStatusConfig ───────────────────────────────────────────────────────────

class WorkStatusConfig:
    """Maps WorkStatus → lifecycle stage and defines valid WorkStatus transitions.

    The lifecycle stage mapping is authoritative: a WorkStatus change implies the mapped
    lifecycle stage. WorkStatus-only changes (e.g., QUALIFIED→RECOMMENDED, both lifecycle=queued)
    do NOT touch the lifecycle. BLOCKED/EXPIRED/ABANDONED/WAITING_EXTERNAL preserve the current
    lifecycle stage.
    """

    # WorkStatus → lifecycle stage
    WORK_TO_LIFECYCLE: Dict[WorkStatus, str] = {
        WorkStatus.NEW: "discovered",
        WorkStatus.EVALUATING: "researched",
        WorkStatus.QUALIFIED: "queued",
        WorkStatus.RECOMMENDED: "queued",
        WorkStatus.AWAITING_APPROVAL: "queued",
        WorkStatus.READY: "queued",
        WorkStatus.IN_PROGRESS: "in_progress",
        WorkStatus.BLOCKED: "__preserve__",       # keeps current lifecycle stage
        WorkStatus.WAITING_EXTERNAL: "submitted",
        WorkStatus.COMPLETED: "submitted",
        WorkStatus.PAYMENT_PENDING: "submitted",
        WorkStatus.PAID: "paid",
        WorkStatus.FAILED: "failed",
        WorkStatus.REJECTED: "rejected",
        WorkStatus.EXPIRED: "__preserve__",
        WorkStatus.ABANDONED: "__preserve__",
    }

    # Valid WorkStatus transitions (source → {targets})
    # Permissive but disallows nonsensical leaps (e.g., NEW→PAID).
    VALID_WORK_TRANSITIONS: Dict[WorkStatus, Set[WorkStatus]] = {
        WorkStatus.NEW: {
            WorkStatus.EVALUATING, WorkStatus.ABANDONED, WorkStatus.EXPIRED,
            WorkStatus.QUALIFIED,
        },
        WorkStatus.EVALUATING: {
            WorkStatus.QUALIFIED, WorkStatus.BLOCKED, WorkStatus.ABANDONED,
            WorkStatus.EXPIRED, WorkStatus.FAILED, WorkStatus.REJECTED,
        },
        WorkStatus.QUALIFIED: {
            WorkStatus.RECOMMENDED, WorkStatus.AWAITING_APPROVAL, WorkStatus.READY,
            WorkStatus.BLOCKED, WorkStatus.ABANDONED, WorkStatus.EXPIRED,
        },
        WorkStatus.RECOMMENDED: {
            WorkStatus.AWAITING_APPROVAL, WorkStatus.READY, WorkStatus.BLOCKED,
            WorkStatus.ABANDONED, WorkStatus.EXPIRED,
        },
        WorkStatus.AWAITING_APPROVAL: {
            WorkStatus.READY, WorkStatus.REJECTED, WorkStatus.BLOCKED,
            WorkStatus.ABANDONED, WorkStatus.EXPIRED,
        },
        WorkStatus.READY: {
            WorkStatus.IN_PROGRESS, WorkStatus.BLOCKED, WorkStatus.ABANDONED,
            WorkStatus.EXPIRED,
        },
        WorkStatus.IN_PROGRESS: {
            WorkStatus.COMPLETED, WorkStatus.BLOCKED, WorkStatus.WAITING_EXTERNAL,
            WorkStatus.FAILED, WorkStatus.ABANDONED,
        },
        WorkStatus.BLOCKED: {
            WorkStatus.READY, WorkStatus.IN_PROGRESS, WorkStatus.ABANDONED,
            WorkStatus.EXPIRED,
        },
        WorkStatus.WAITING_EXTERNAL: {
            WorkStatus.COMPLETED, WorkStatus.PAYMENT_PENDING, WorkStatus.IN_PROGRESS,
            WorkStatus.FAILED, WorkStatus.REJECTED, WorkStatus.BLOCKED,
        },
        WorkStatus.COMPLETED: {
            WorkStatus.PAYMENT_PENDING, WorkStatus.PAID, WorkStatus.BLOCKED,
            WorkStatus.WAITING_EXTERNAL,
        },
        WorkStatus.PAYMENT_PENDING: {
            WorkStatus.PAID, WorkStatus.BLOCKED, WorkStatus.FAILED,
        },
        WorkStatus.PAID: set(),          # terminal
        WorkStatus.FAILED: set(),        # terminal
        WorkStatus.REJECTED: set(),      # terminal
        WorkStatus.EXPIRED: set(),       # terminal
        WorkStatus.ABANDONED: set(),     # terminal
    }


# ── PortfolioEntry ─────────────────────────────────────────────────────────────

@dataclass
class PortfolioEntry:
    """A single opportunity in the portfolio with enriched portfolio-level fields."""
    opportunity_id: str
    opportunity_ref: Dict[str, Any] = field(default_factory=dict)
    work_status: WorkStatus = WorkStatus.NEW
    priority: float = 0.5              # 0..1, user/system override
    expected_value: float = 0.0        # USD
    expected_hourly_value: float = 0.0 # USD/hour
    deadline: float = 0.0              # unix ts; 0 = none
    confidence: float = 0.25           # 0..1
    risk: float = 0.5                  # 0..1
    effort: float = 0.0                # hours
    next_action: str = ""
    waiting_reason: str = ""
    evidence_status: str = "none"
    payment_status: str = "unpaid"
    blocked_reason: str = ""
    platform: str = ""
    category: str = ""
    task_type: str = ""
    skill_fit: float = 0.0             # 0..1
    policy_score: float = 0.0          # last computed
    lifecycle_stage: str = ""          # mirror of lifecycle's current stage (portfolio bookkeeping)
    added_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    policy_version: str = "v1"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["work_status"] = self.work_status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PortfolioEntry":
        d = dict(d)
        d["work_status"] = WorkStatus(d.get("work_status", "NEW"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── OpportunityPortfolio ────────────────────────────────────────────────────────

class OpportunityPortfolio:
    """Persistent portfolio of opportunities with WorkStatus transitions.

    Transition validity: a WorkStatus change is checked against VALID_WORK_TRANSITIONS
    first. If the new status implies a lifecycle stage change, the change is delegated to the
    lifecycle tracker (if injected). The lifecycle's _ALLOWED_TRANSITIONS is the final
    authority — a move the lifecycle disallows is rejected with IllegalTransitionError.
    """

    def __init__(self, db_path: str, lifecycle: Any = None):
        self.db_path = db_path
        self.lifecycle = lifecycle
        self._lock = threading.RLock()
        self._init_db()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS opportunity_portfolio (
                    opportunity_id TEXT PRIMARY KEY,
                    work_status TEXT NOT NULL,
                    priority REAL DEFAULT 0.5,
                    expected_value REAL DEFAULT 0.0,
                    expected_hourly_value REAL DEFAULT 0.0,
                    deadline REAL DEFAULT 0.0,
                    confidence REAL DEFAULT 0.25,
                    risk REAL DEFAULT 0.5,
                    effort REAL DEFAULT 0.0,
                    next_action TEXT DEFAULT '',
                    waiting_reason TEXT DEFAULT '',
                    evidence_status TEXT DEFAULT 'none',
                    payment_status TEXT DEFAULT 'unpaid',
                    blocked_reason TEXT DEFAULT '',
                    platform TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    task_type TEXT DEFAULT '',
                    skill_fit REAL DEFAULT 0.0,
                    policy_score REAL DEFAULT 0.0,
                    lifecycle_stage TEXT DEFAULT '',
                    added_at REAL,
                    updated_at REAL,
                    policy_version TEXT DEFAULT 'v1',
                    opportunity_ref_json TEXT DEFAULT '{}'
                )
            """)
            conn.commit()
            conn.close()

    def _row_to_entry(self, row: tuple) -> PortfolioEntry:
        """Convert a DB row (matching the column order in _init_db) to a PortfolioEntry."""
        # Columns: opportunity_id(0), work_status(1), priority(2), expected_value(3),
        # expected_hourly_value(4), deadline(5), confidence(6), risk(7), effort(8),
        # next_action(9), waiting_reason(10), evidence_status(11), payment_status(12),
        # blocked_reason(13), platform(14), category(15), task_type(16), skill_fit(17),
        # policy_score(18), lifecycle_stage(19), added_at(20), updated_at(21),
        # policy_version(22), opportunity_ref_json(23)
        ref = json.loads(row[23]) if row[23] else {}
        return PortfolioEntry(
            opportunity_id=row[0],
            work_status=WorkStatus(row[1]),
            priority=row[2],
            expected_value=row[3],
            expected_hourly_value=row[4],
            deadline=row[5],
            confidence=row[6],
            risk=row[7],
            effort=row[8],
            next_action=row[9],
            waiting_reason=row[10],
            evidence_status=row[11],
            payment_status=row[12],
            blocked_reason=row[13],
            platform=row[14],
            category=row[15],
            task_type=row[16],
            skill_fit=row[17],
            policy_score=row[18],
            lifecycle_stage=row[19] or "",
            added_at=row[20],
            updated_at=row[21],
            policy_version=row[22],
            opportunity_ref=ref,
        )

    def add(self, entry: PortfolioEntry) -> None:
        """Insert or replace a portfolio entry."""
        entry.added_at = entry.added_at or time.time()
        entry.updated_at = time.time()
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT OR REPLACE INTO opportunity_portfolio
                (opportunity_id, work_status, priority, expected_value, expected_hourly_value,
                 deadline, confidence, risk, effort, next_action, waiting_reason, evidence_status,
                 payment_status, blocked_reason, platform, category, task_type, skill_fit,
                 policy_score, lifecycle_stage, added_at, updated_at, policy_version,
                 opportunity_ref_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.opportunity_id, entry.work_status.value, entry.priority,
                entry.expected_value, entry.expected_hourly_value, entry.deadline,
                entry.confidence, entry.risk, entry.effort, entry.next_action,
                entry.waiting_reason, entry.evidence_status, entry.payment_status,
                entry.blocked_reason, entry.platform, entry.category, entry.task_type,
                entry.skill_fit, entry.policy_score, entry.lifecycle_stage,
                entry.added_at, entry.updated_at, entry.policy_version,
                json.dumps(entry.opportunity_ref, default=str),
            ))
            conn.commit()
            conn.close()

    def get(self, opportunity_id: str) -> Optional[PortfolioEntry]:
        """Get a single entry by ID."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT * FROM opportunity_portfolio WHERE opportunity_id=?",
                (opportunity_id,)
            ).fetchone()
            conn.close()
        if row is None:
            return None
        return self._row_to_entry(row)

    def update(self, entry: PortfolioEntry) -> None:
        """Update an existing entry (same as add — INSERT OR REPLACE)."""
        self.add(entry)

    def remove(self, opportunity_id: str) -> None:
        """Delete an entry."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM opportunity_portfolio WHERE opportunity_id=?", (opportunity_id,))
            conn.commit()
            conn.close()

    def list_all(self) -> List[PortfolioEntry]:
        """List all entries."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT * FROM opportunity_portfolio ORDER BY added_at").fetchall()
            conn.close()
        return [self._row_to_entry(r) for r in rows]

    def list_work(self, status: Optional[WorkStatus] = None) -> List[PortfolioEntry]:
        """List entries, optionally filtered by WorkStatus."""
        if status is None:
            return self.list_all()
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT * FROM opportunity_portfolio WHERE work_status=? ORDER BY added_at",
                (status.value,)
            ).fetchall()
            conn.close()
        return [self._row_to_entry(r) for r in rows]

    def count_by_status(self) -> Dict[str, int]:
        """Count entries per work status."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT work_status, COUNT(*) FROM opportunity_portfolio GROUP BY work_status"
            ).fetchall()
            conn.close()
        return {r[0]: r[1] for r in rows}

    # ── Recovery ──────────────────────────────────────────────────────────────

    def load_all(self) -> List[PortfolioEntry]:
        """Load all entries (for recovery after restart). Alias for list_all."""
        return self.list_all()

    # ── Transitions ────────────────────────────────────────────────────────────

    def transition_work_status(self, opportunity_id: str, new_status: WorkStatus,
                               **ctx: Any) -> PortfolioEntry:
        """Transition an entry to a new WorkStatus.

        Validates against VALID_WORK_TRANSITIONS first. If the new status implies a lifecycle
        stage change and a lifecycle tracker is injected, delegates the lifecycle move to the
        tracker (which enforces _ALLOWED_TRANSITIONS). Raises IllegalTransitionError on any
        invalidity.
        """
        entry = self.get(opportunity_id)
        if entry is None:
            raise IllegalTransitionError(f"Unknown opportunity: {opportunity_id}")
        old_status = entry.work_status

        # 1. Validate the WorkStatus transition
        allowed = WorkStatusConfig.VALID_WORK_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise IllegalTransitionError(
                f"Invalid WorkStatus transition: {old_status.value} → {new_status.value}")

        # 2. If it implies a lifecycle change, delegate to the lifecycle tracker
        if self.lifecycle is not None:
            lifecycle_stage = WorkStatusConfig.WORK_TO_LIFECYCLE.get(new_status)
            if lifecycle_stage and lifecycle_stage != "__preserve__":
                self._delegate_to_lifecycle(opportunity_id, old_status, new_status,
                                            lifecycle_stage, **ctx)

        # 3. Apply the WorkStatus change
        entry.work_status = new_status
        entry.updated_at = time.time()
        self.add(entry)
        return entry

    def _delegate_to_lifecycle(self, opportunity_id: str, old_status: WorkStatus,
                               new_status: WorkStatus, lifecycle_stage: str,
                               **ctx: Any) -> None:
        """Delegate a lifecycle-affecting move to the injected lifecycle tracker.

        The lifecycle tracker is the authority: if it rejects the move (e.g., via
        _ALLOWED_TRANSITIONS), we raise IllegalTransitionError and the WorkStatus change is NOT
        applied. If the entry is already at the target lifecycle stage, skip (idempotent for
        WorkStatus-only moves like QUALIFIED→READY that both map to 'queued').

        When the target lifecycle stage isn't directly reachable from the current stage (e.g.,
        READY→IN_PROGRESS maps to queued→in_progress, but the lifecycle requires
        queued→applied→in_progress), we WALK the lifecycle's transition graph and apply each
        intermediate stage — respecting the lifecycle's authority at every step.
        """
        # Determine the lifecycle's actual current stage (query it if it exposes get_state).
        current_lc = ""
        if hasattr(self.lifecycle, "get_state"):
            try:
                st = self.lifecycle.get_state(opportunity_id)
                if isinstance(st, dict):
                    current_lc = st.get("current_stage", "")
            except Exception:
                pass
        if current_lc == lifecycle_stage:
            return  # already there; WorkStatus-only change, no lifecycle move needed
        # Build the chain of lifecycle stages to traverse.
        stages = self._lifecycle_path(current_lc, lifecycle_stage)
        for stage in stages:
            self._apply_lifecycle_stage(opportunity_id, stage, **ctx)
        # Mirror the new stage on the portfolio entry
        entry = self.get(opportunity_id)
        if entry is not None:
            entry.lifecycle_stage = lifecycle_stage
            self.add(entry)

    def _lifecycle_path(self, start: str, goal: str) -> List[str]:
        """Find the shortest chain of lifecycle stages from start to goal using BFS over
        _ALLOWED_TRANSITIONS. Returns the list of stages to apply (excluding start). Raises
        IllegalTransitionError if goal is unreachable."""
        transitions = getattr(self.lifecycle, "_ALLOWED_TRANSITIONS", {})
        if start == goal:
            return []
        # BFS
        queue: List[tuple] = [(start, [])]
        visited = {start}
        while queue:
            current, path = queue.pop(0)
            for nxt in sorted(transitions.get(current, set())):
                if nxt == goal:
                    return path + [nxt]
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, path + [nxt]))
        raise IllegalTransitionError(
            f"No valid lifecycle path from '{start}' to '{goal}'")

    def _apply_lifecycle_stage(self, opportunity_id: str, lifecycle_stage: str,
                               **ctx: Any) -> None:
        """Apply a single lifecycle stage via the tracker's mark methods."""
        try:
            if lifecycle_stage == "paid":
                self.lifecycle.mark_paid_verified(opportunity_id, amount=ctx.get("amount", 0.0))
            elif lifecycle_stage == "failed":
                self.lifecycle.mark_failed(opportunity_id, ctx.get("note") or "failed")
            elif lifecycle_stage == "rejected":
                self.lifecycle.mark_rejected(opportunity_id, ctx.get("reason") or "rejected")
            else:
                self.lifecycle.mark_final_outcome(opportunity_id, outcome_state=lifecycle_stage)
        except Exception as e:
            raise IllegalTransitionError(
                f"Lifecycle rejected transition to {lifecycle_stage}: {e}") from e


# ── Convenience exports ────────────────────────────────────────────────────────

__all__ = [
    "WorkStatus",
    "PortfolioEntry",
    "OpportunityPortfolio",
    "WorkStatusConfig",
    "IllegalTransitionError",
    "QueuePolicy",
    "CapacityConfig",
    "WorkQueue",
]


# ── QueuePolicy ─────────────────────────────────────────────────────────────────

@dataclass
class QueuePolicy:
    """Configurable prioritization policy.

    The score is a weighted sum by default; a custom `scorer` callable can replace the formula
    entirely. Weights live here (in config), NOT hardcoded in the scorer logic — satisfies
    "don't hardcode one simplistic formula; make the policy configurable."
    """
    # Weights (all tunable)
    w_expected_hourly: float = 1.0
    w_confidence: float = 0.5
    w_risk: float = -0.8           # risk is bad → penalty
    w_skill_fit: float = 0.6
    w_deadline_urgency: float = 0.4
    w_effort: float = -0.3         # effort is cost → penalty
    w_priority_override: float = 2.0  # lets human priority jump the queue

    # Pluggable scorer: score(entry, now) -> float. If None, uses the weighted formula.
    scorer: Optional[Callable[["PortfolioEntry", float], float]] = None

    # Normalization bounds (for the default scorer)
    max_effort_hours: float = 40.0
    max_expected_hourly: float = 200.0

    def score(self, entry: PortfolioEntry, now: float) -> float:
        """Compute a priority score for an entry (higher = more attractive)."""
        if self.scorer is not None:
            return self.scorer(entry, now)
        # Normalize fields to ~0..1
        norm_ehv = max(0.0, min(1.0, entry.expected_hourly_value / max(1e-9, self.max_expected_hourly)))
        norm_effort = max(0.0, min(1.0, entry.effort / max(1e-9, self.max_effort_hours)))
        deadline_urgency = self._deadline_urgency(entry.deadline, now)
        # risk and effort are costs → (1 - value) so lower is better
        risk_good = 1.0 - max(0.0, min(1.0, entry.risk))
        effort_good = 1.0 - norm_effort
        return (
            self.w_expected_hourly * norm_ehv
            + self.w_confidence * max(0.0, min(1.0, entry.confidence))
            + self.w_risk * risk_good
            + self.w_skill_fit * max(0.0, min(1.0, entry.skill_fit))
            + self.w_deadline_urgency * deadline_urgency
            + self.w_effort * effort_good
            + self.w_priority_override * max(0.0, min(1.0, entry.priority))
        )

    @staticmethod
    def _deadline_urgency(deadline: float, now: float) -> float:
        """1.0 if due within 24h, decaying to 0.0 if >14d or no deadline."""
        if deadline <= 0:
            return 0.0  # no deadline → no urgency
        remaining = deadline - now
        if remaining <= 0:
            return 1.0  # past due → max urgency
        if remaining <= 86400:  # 24h
            return 1.0
        if remaining >= 86400 * 14:  # 14d
            return 0.0
        # linear decay between 24h and 14d
        return 1.0 - (remaining - 86400) / (86400 * 13)


# ── CapacityConfig ──────────────────────────────────────────────────────────────

@dataclass
class CapacityConfig:
    """Configurable overcommit limits. Hard gates: select_next skips any entry exceeding a limit."""
    max_active_tasks: int = 3                # IN_PROGRESS simultaneously
    max_pending_applications: int = 5       # READY simultaneously
    max_simultaneous: int = 8               # total non-terminal in play
    max_high_risk: int = 1                  # risk > 0.7 counts
    max_financial_exposure: float = 1000.0  # USD sum of expected_value across IN_PROGRESS+WAITING_EXTERNAL
    max_platform_submissions: Dict[str, int] = field(default_factory=dict)  # per-platform READY+IN_PROGRESS


# ── WorkQueue ────────────────────────────────────────────────────────────────────

class WorkQueue:
    """Prioritized selection with hard overcommit enforcement.

    select_next walks the prioritized list, skipping any entry that would violate a capacity
    limit — so even if 50 opps are queued, only as many as capacity allows are selected.
    """

    def __init__(self, portfolio: OpportunityPortfolio, policy: QueuePolicy,
                 capacity: CapacityConfig):
        self.portfolio = portfolio
        self.policy = policy
        self.capacity = capacity

    # ── Scoring & ordering ──────────────────────────────────────────────────────

    def compute_scores(self, now: float) -> List[tuple]:
        """Compute policy_score for every non-terminal entry. Returns [(entry, score)]."""
        entries = [e for e in self.portfolio.list_all() if not e.work_status.is_terminal]
        scored = [(e, self.policy.score(e, now)) for e in entries]
        return scored

    def prioritized(self, now: float) -> List[PortfolioEntry]:
        """Return non-terminal entries sorted by policy_score descending (the queue order)."""
        scored = self.compute_scores(now)
        scored.sort(key=lambda x: x[1], reverse=True)
        return [e for e, _ in scored]

    # ── Capacity enforcement ────────────────────────────────────────────────────

    def _current_counts(self, now: float) -> Dict[str, Any]:
        """Snapshot current utilization across all capacity dimensions."""
        all_entries = self.portfolio.list_all()
        in_progress = [e for e in all_entries if e.work_status == WorkStatus.IN_PROGRESS]
        ready = [e for e in all_entries if e.work_status == WorkStatus.READY]
        waiting_external = [e for e in all_entries if e.work_status == WorkStatus.WAITING_EXTERNAL]
        high_risk = [e for e in all_entries if e.risk > 0.7 and not e.work_status.is_terminal]
        non_terminal = [e for e in all_entries if not e.work_status.is_terminal]
        # per-platform
        platform_counts: Dict[str, int] = {}
        for e in all_entries:
            if e.work_status in (WorkStatus.READY, WorkStatus.IN_PROGRESS) and e.platform:
                platform_counts[e.platform] = platform_counts.get(e.platform, 0) + 1
        return {
            "in_progress": len(in_progress),
            "pending_applications": len(ready),
            "waiting_external": len(waiting_external),
            "high_risk": len(high_risk),
            "non_terminal": len(non_terminal),
            "financial_exposure": sum(e.expected_value for e in in_progress + waiting_external),
            "platform_counts": platform_counts,
        }

    def would_exceed_capacity(self, entry: PortfolioEntry, counts: Dict[str, Any]) -> Optional[str]:
        """Check if adding `entry` to active work would exceed any capacity limit.
        Returns a reason string if it would exceed, or None if it fits.
        `counts` is the current/projected utilization snapshot."""
        # max_active_tasks
        if entry.work_status in (WorkStatus.IN_PROGRESS, WorkStatus.READY):
            if counts["in_progress"] >= self.capacity.max_active_tasks:
                return f"max_active_tasks ({self.capacity.max_active_tasks})"
            if counts["financial_exposure"] + entry.expected_value > self.capacity.max_financial_exposure:
                return f"max_financial_exposure ({self.capacity.max_financial_exposure})"
        # pending applications (READY)
        if entry.work_status == WorkStatus.READY:
            if counts["pending_applications"] >= self.capacity.max_pending_applications:
                return f"max_pending_applications ({self.capacity.max_pending_applications})"
        # simultaneous (any non-terminal)
        if counts["non_terminal"] >= self.capacity.max_simultaneous:
            return f"max_simultaneous ({self.capacity.max_simultaneous})"
        # high risk
        if entry.risk > 0.7 and counts["high_risk"] >= self.capacity.max_high_risk:
            return f"max_high_risk ({self.capacity.max_high_risk})"
        # per-platform
        if entry.platform and entry.work_status in (WorkStatus.READY, WorkStatus.IN_PROGRESS):
            plat_max = self.capacity.max_platform_submissions.get(entry.platform)
            if plat_max is not None:
                plat_count = counts["platform_counts"].get(entry.platform, 0)
                if plat_count >= plat_max:
                    return f"max_platform_submissions for {entry.platform} ({plat_max})"
        return None  # fits

    def select_next(self, now: float, limit: Optional[int] = None) -> List[PortfolioEntry]:
        """Select the next batch to act on, respecting capacity.

        Walks the prioritized list, skipping any entry that would exceed a capacity limit.
        Returns only as many as capacity allows — even if 50 are queued.
        """
        ordered = self.prioritized(now)
        selected: List[PortfolioEntry] = []
        counts = self._current_counts(now)
        for entry in ordered:
            if limit is not None and len(selected) >= limit:
                break
            reason = self.would_exceed_capacity(entry, counts)
            if reason is None:
                selected.append(entry)
                # Update projected counts for subsequent entries
                counts = self._projected_counts(counts, entry)
        return selected

    def _projected_counts(self, counts: Dict[str, Any], entry: PortfolioEntry) -> Dict[str, Any]:
        """Return a copy of counts with `entry` consumed (for selection tracking)."""
        import copy
        c = copy.deepcopy(counts)
        c["non_terminal"] = c.get("non_terminal", 0) + 1
        if entry.work_status == WorkStatus.READY:
            # Starting a READY entry consumes an active slot + a pending slot
            c["in_progress"] = c.get("in_progress", 0) + 1
            c["pending_applications"] = max(0, c.get("pending_applications", 0) - 1)
            c["financial_exposure"] = c.get("financial_exposure", 0) + entry.expected_value
            if entry.platform:
                c["platform_counts"][entry.platform] = c["platform_counts"].get(entry.platform, 0) + 1
        elif entry.work_status == WorkStatus.IN_PROGRESS:
            c["in_progress"] = c.get("in_progress", 0) + 1
            c["financial_exposure"] = c.get("financial_exposure", 0) + entry.expected_value
            if entry.risk > 0.7:
                c["high_risk"] = c.get("high_risk", 0) + 1
        return c

    def get_blocked(self) -> List[PortfolioEntry]:
        """Return BLOCKED entries with their blocked_reason."""
        return [e for e in self.portfolio.list_work(WorkStatus.BLOCKED)]

    def summary(self, now: float) -> Dict[str, Any]:
        """Summary dict: counts by status + exposure + remaining capacity."""
        counts = self._current_counts(now)
        by_status = self.portfolio.count_by_status()
        return {
            "by_status": by_status,
            "active_tasks": counts["in_progress"],
            "pending_applications": counts["pending_applications"],
            "simultaneous": counts["non_terminal"],
            "high_risk": counts["high_risk"],
            "financial_exposure": counts["financial_exposure"],
            "remaining_active": max(0, self.capacity.max_active_tasks - counts["in_progress"]),
            "remaining_simultaneous": max(0, self.capacity.max_simultaneous - counts["non_terminal"]),
        }


# ── Next-action resolver ───────────────────────────────────────────────────────

# Mapping of WorkStatus → (next_action, waiting_reason).
_NEXT_ACTION_MAP: Dict[WorkStatus, tuple] = {
    WorkStatus.NEW: ("evaluate", "pending intelligence evaluation"),
    WorkStatus.EVALUATING: ("review_verdict", "awaiting evaluation verdict"),
    WorkStatus.QUALIFIED: ("recommend", "ready for policy recommendation"),
    WorkStatus.RECOMMENDED: ("await_approval", "attractive — needs human approval"),
    WorkStatus.AWAITING_APPROVAL: ("wait_for_approval", "human decision pending"),
    WorkStatus.READY: ("begin_work", "approved and queued to start"),
    WorkStatus.IN_PROGRESS: ("continue_work", "actively being worked"),
    WorkStatus.BLOCKED: ("unblock_or_abandon", "blocked"),
    WorkStatus.WAITING_EXTERNAL: ("follow_up", "awaiting external response"),
    WorkStatus.COMPLETED: ("await_payment", "work delivered"),
    WorkStatus.PAYMENT_PENDING: ("follow_up_payment", "payment expected"),
    WorkStatus.PAID: ("none", "terminal"),
    WorkStatus.FAILED: ("none", "terminal"),
    WorkStatus.REJECTED: ("none", "terminal"),
    WorkStatus.EXPIRED: ("none", "terminal"),
    WorkStatus.ABANDONED: ("none", "terminal"),
}


def resolve_next_action(entry: PortfolioEntry) -> tuple:
    """Deterministic (action, reason) for a portfolio entry based on its WorkStatus."""
    action, reason = _NEXT_ACTION_MAP.get(entry.work_status, ("none", "unknown"))
    if entry.work_status == WorkStatus.BLOCKED and entry.blocked_reason:
        reason = entry.blocked_reason
    elif entry.work_status == WorkStatus.WAITING_EXTERNAL and entry.waiting_reason:
        reason = entry.waiting_reason
    return (action, reason)


def apply_next(portfolio: OpportunityPortfolio, entry: PortfolioEntry,
               now: float, **ctx: Any) -> PortfolioEntry:
    """Advance an entry to its next logical WorkStatus based on its current status.

    - NEW → EVALUATING
    - EVALUATING → QUALIFIED
    - QUALIFIED → RECOMMENDED
    - RECOMMENDED → READY
    - READY → IN_PROGRESS (delegates lifecycle)
    - IN_PROGRESS → COMPLETED
    - COMPLETED → PAYMENT_PENDING
    - PAYMENT_PENDING → PAID
    - Terminal states: no-op (returns entry unchanged).

    Returns the updated entry.
    """
    if entry.work_status.is_terminal:
        return entry
    advance_map: Dict[WorkStatus, WorkStatus] = {
        WorkStatus.NEW: WorkStatus.EVALUATING,
        WorkStatus.EVALUATING: WorkStatus.QUALIFIED,
        WorkStatus.QUALIFIED: WorkStatus.RECOMMENDED,
        WorkStatus.RECOMMENDED: WorkStatus.READY,
        WorkStatus.READY: WorkStatus.IN_PROGRESS,
        WorkStatus.IN_PROGRESS: WorkStatus.COMPLETED,
        WorkStatus.COMPLETED: WorkStatus.PAYMENT_PENDING,
        WorkStatus.PAYMENT_PENDING: WorkStatus.PAID,
    }
    next_status = advance_map.get(entry.work_status)
    if next_status is None:
        return entry
    return portfolio.transition_work_status(entry.opportunity_id, next_status, **ctx)
