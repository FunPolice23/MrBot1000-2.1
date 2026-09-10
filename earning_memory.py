"""
earning_memory.py — Multi-tiered memory system for MrBot1000.

Tier 1: Opportunity Memory - tracks all discovered opportunities
Tier 2: Outcome Memory - tracks results of executed actions
Tier 3: Skill Memory - learns which jobs/skills are profitable
Tier 4: Reputation Memory - platform-level success/failure rates
Tier 5: Pattern Memory - learns patterns from successes/failures
"""

import os
import re
import json
import sqlite3
import threading
import time
from collections import defaultdict, Counter
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime

# ── Canonical enumerations for the expanded learning memory ───────────────
# These are the SINGLE SOURCE OF TRUTH for valid outcome states, failure
# causes, and success causes. Recording an unknown value is rejected (deterministic).

# OUTCOME_MEMORY lifecycle states an opportunity can pass through.
# NOTE: the user's list has "rejected" twice (once after "applied", once after
# "paid"). We preserve both meanings as distinct states:
#   rejected_apply  -> proposal/application was rejected (pre-acceptance)
#   rejected_pay    -> payment was rejected/disputed-rejected (post-acceptance)
OUTCOME_STATES = (
    "discovered", "evaluated", "rejected", "applied", "accepted",
    "started", "completed", "submitted", "rejected_apply", "rejected_pay",
    "failed", "paid", "payment_disputed", "abandoned",
)

# Structured failure causes — memory MUST store WHY, never just "failure".
FAILURE_CAUSES = (
    "poor_skill_fit", "bad_estimate", "low_payment", "client_rejection",
    "platform_rejection", "missed_requirement", "deadline_failure",
    "technical_failure", "automation_failure", "external_api_failure",
    "scam", "payment_failure", "excessive_effort", "low_roi",
    "insufficient_information", "user_cancellation",
)

# Structured success causes — memory MUST store WHY success happened.
SUCCESS_CAUSES = (
    "good_skill_fit", "high_payment", "strong_portfolio", "clear_requirements",
    "met_deadline", "technical_excellence", "automation_success",
    "reliable_platform", "low_competition", "good_client_fit",
    "fast_payment", "reusable_asset",
)

# Minimum samples before an aggregate earns real confidence (cold-start guard).
MIN_SAMPLES = 3

# Neutral prior used when data is insufficient (cold-start). Never hard-reject for lack of data.
NEUTRAL_RATE = 0.5
NEUTRAL_CONFIDENCE = 0.25

# Recency half-life (days) for time-weighted learning. Outcomes older than this contribute
# half as much to rolling metrics; raw history is RETAINED verbatim for audit (on-read weighting
# only — nothing is deleted or mutated).
RECENCY_HALF_LIFE_DAYS = 90.0

# How long (days) before an aggregate is considered "stale" for trend comparison.
RECENCY_TREND_WINDOW_DAYS = 30.0


def _confidence_for_samples(n: int) -> float:
    """Confidence grows with sample count, capped at 1.0; stays low at n=1..2."""
    if n <= 0:
        return 0.0
    if n < MIN_SAMPLES:
        return NEUTRAL_CONFIDENCE
    return min(1.0, NEUTRAL_CONFIDENCE + 0.15 * (n - MIN_SAMPLES))


def recency_weight(ts: float, now: float = None, half_life_days: float = RECENCY_HALF_LIFE_DAYS) -> float:
    """Time-decay weight for an event at timestamp `ts`.

    weight = 0.5 ** (age_days / half_life). A 0-day-old event weights 1.0; an event
    `half_life` days old weights 0.5; twice that ages to 0.25. Old outcomes thus
    contribute less to rolling metrics WITHOUT being deleted (audit history retained).
    """
    if ts is None or ts <= 0:
        return 0.0
    now = now if now is not None else time.time()
    age_days = max(0.0, (now - ts) / 86400.0)
    return 0.5 ** (age_days / max(0.0001, half_life_days))


def _safe_rate(success: int, total: int) -> float:
    return (success / total) if total else 0.0


# Stopwords stripped during query normalization (cheap, dependency-free).
_QUERY_STOPWORDS = {
    "a", "an", "the", "of", "for", "to", "and", "or", "in", "on", "at", "by", "with",
    "freelance", "paid", "task", "tasks", "job", "jobs", "gig", "gigs", "work", "online",
}


def _normalize_query(q: str) -> str:
    """Lowercase, strip punctuation, drop stopwords, dedupe -> canonical form.

    Lets the system recognize semantically related searches and learn that two
    near-identical queries can have very different economic outcomes (so we track
    the EXACT query too, but also group on the normalized form).
    """
    if not q:
        return ""
    toks = re.sub(r"[^a-z0-9 ]", " ", str(q).lower()).split()
    seen = []
    for t in toks:
        if t in _QUERY_STOPWORDS:
            continue
        if t not in seen:
            seen.append(t)
    return " ".join(seen)


# ── Search-strategy usefulness weights (v2.0.36g) ──────────────
# The system optimizes for USEFUL, LEGITIMATE, PROFITABLE opportunities — NOT raw result
# count. net_revenue is the dominant signal; duplicates are penalized.
_W_USEFUL = 10.0
_W_COMPLETE = 20.0
_W_PAID = 30.0
_W_DUP = 5.0
# Novel strategies (used_count < MIN_SAMPLES) get a NEUTRAL prior so historical performance
# never permanently suppresses a novel search (cold-start safe, exploration-preserving).
_COLD_START_USEFULNESS = 0.5


def _strategy_usefulness(used, result_count, useful, completed, paid, net_revenue, duplicates) -> float:
    """Composite economic usefulness of a search strategy (v2.0.36g).

    Returns a NEUTRAL prior for under-sampled (cold-start) strategies so they are
    neither suppressed nor dominant. For proven strategies, returns a PER-USE score that
    rewards profit + useful/completed/paid outcomes and penalizes duplicates — explicitly
    NOT the raw result count.
    """
    if used < MIN_SAMPLES:
        return float(_COLD_START_USEFULNESS)
    per_use = (float(net_revenue) + _W_USEFUL * useful + _W_COMPLETE * completed
               + _W_PAID * paid - _W_DUP * duplicates) / max(used, 1)
    return per_use


@dataclass
class MemoryEntry:
    """Base memory entry with timestamp."""
    memory_type: str
    key: str
    value: dict
    timestamp: float = field(default_factory=time.time)
    ttl: float = 86400 * 30  # Default 30 days

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl


@dataclass
class LearningMetrics:
    """The 11 required opportunity-learning metrics for one dimension (category/platform/task_type/global).

    Every aggregate carries `sample_size` + `confidence` + `cold_start` so the decision layer
    never over-learns from n=1. `recency_weighted` marks that averages use time-decay weights.
    Averages (revenue/net/effort/hourly/expected-vs-actual) are recency-weighted; rates are
    raw counts / total (sample-size guarded).
    """
    dim: str = "global"
    value: str = "global"
    # funnel rates
    attempt_rate: float = 0.0
    acceptance_rate: float = 0.0
    completion_rate: float = 0.0
    payment_rate: float = 0.0
    failure_rate: float = 0.0
    cancellation_rate: float = 0.0
    # averages (recency-weighted)
    average_revenue: float = 0.0
    average_net_profit: float = 0.0
    average_effort_hours: float = 0.0
    average_hourly_return: float = 0.0
    expected_vs_actual_return: float = 0.0  # actual_weighted / max(predicted_weighted, eps)
    # governance
    sample_size: int = 0
    confidence: float = 0.0
    cold_start: bool = True
    recency_weighted: bool = True


class EarningMemory:
    """Multi-tiered memory system for earning pipeline with learning and decay."""

    def __init__(self, db_path: str = None, root_folder: str = None):
        self.db_path = db_path or os.path.join(
            root_folder or os.path.dirname(__file__), "earning_memory.db"
        )
        self._lock = threading.Lock()
        self._init_db()
        self._migrate_schema()
        
        # In-memory caches for fast access
        self._cache: Dict[str, dict] = {}
        self._stats: Dict[str, dict] = defaultdict(lambda: {
            "success": 0, "failed": 0, "total_revenue": 0.0,
            "last_success": None, "last_failure": None,
            "skills_matched": set(), "skill_count": 0
        })
        
        # Decay parameters
        self._decay_factor = 0.99  # Daily decay for old stats
        self._min_stats = {
            "success": 0, "failed": 0, "total_revenue": 0.0
        }

    def _init_db(self):
        """Initialize the memory database with all tables."""
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            -- Tier 1: Opportunity Memory
            CREATE TABLE IF NOT EXISTS opportunity_memory (
                key TEXT PRIMARY KEY,
                memory_data TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                created_at REAL,
                updated_at REAL
            );

            -- Tier 2: Outcome Memory
            CREATE TABLE IF NOT EXISTS outcome_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT NOT NULL,
                action_taken TEXT,
                result TEXT,
                revenue_usd REAL DEFAULT 0,
                time_spent_hours REAL DEFAULT 0,
                was_scam BOOLEAN DEFAULT 0,
                success BOOLEAN DEFAULT 0,
                tags TEXT,
                created_at REAL
            );

            -- Tier 3: Skill Memory
            CREATE TABLE IF NOT EXISTS skill_memory (
                skill TEXT PRIMARY KEY,
                success_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                total_revenue REAL DEFAULT 0,
                platforms TEXT,
                last_used REAL
            );

            -- Tier 4: Reputation Memory (per platform)
            CREATE TABLE IF NOT EXISTS reputation_memory (
                platform TEXT PRIMARY KEY,
                success_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                scam_count INTEGER DEFAULT 0,
                avg_revenue REAL DEFAULT 0,
                total_attempts INTEGER DEFAULT 0,
                last_attempt REAL
            );

            -- Tier 5: Pattern Memory (learning from outcomes)
            CREATE TABLE IF NOT EXISTS pattern_memory (
                pattern_type TEXT,
                pattern_key TEXT,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                total_revenue REAL DEFAULT 0,
                confidence REAL DEFAULT 0.0,
                last_seen REAL,
                PRIMARY KEY (pattern_type, pattern_key)
            );

            -- Learning History
            CREATE TABLE IF NOT EXISTS learning_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                learning_type TEXT NOT NULL,
                insight TEXT,
                confidence REAL,
                created_at REAL
            );

            -- Decay tracking
            CREATE TABLE IF NOT EXISTS decay_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT,
                entity_key TEXT,
                old_value REAL,
                new_value REAL,
                decay_factor REAL,
                applied_at REAL
            );

            -- ===== Expanded Learning Memory (v2.0.35) =====
            -- Each memory type is a STRUCTURED, bounded table (no unbounded text dump).
            -- Raw event tables are append-only; aggregate/summary tables are derived.

            -- 3. OPPORTUNITY MEMORY (timeline): what happened to an individual opportunity.
            CREATE TABLE IF NOT EXISTS opportunity_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                detail TEXT,
                ts REAL
            );

            -- 4. OUTCOME MEMORY (extended, append-only): one rich row per outcome event.
            CREATE TABLE IF NOT EXISTS outcome_memory_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT NOT NULL,
                outcome_state TEXT NOT NULL,
                platform TEXT,
                category TEXT,
                task_type TEXT,
                revenue REAL DEFAULT 0,
                cost REAL DEFAULT 0,
                net_profit REAL DEFAULT 0,
                effort_hours REAL DEFAULT 0,
                time_spent_hours REAL DEFAULT 0,
                strategy_used TEXT,
                proposal_variant TEXT,
                model_used TEXT,
                human_intervention BOOLEAN DEFAULT 0,
                automation_level REAL DEFAULT 0,
                reason TEXT,
                evidence TEXT,
                failure_cause TEXT,
                success_cause TEXT,
                disputed BOOLEAN DEFAULT 0,
                ts REAL
            );

            -- 5. REPUTATION MEMORY -> already reputation_memory (kept).

            -- 6. STRATEGY MEMORY: which strategies/variants succeed/fail + WHY.
            CREATE TABLE IF NOT EXISTS strategy_memory (
                strategy TEXT NOT NULL,
                variant TEXT,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                total_revenue REAL DEFAULT 0,
                success_cause TEXT,
                failure_cause TEXT,
                confidence REAL DEFAULT 0,
                last_seen REAL,
                PRIMARY KEY (strategy, variant)
            );

            -- 7. FAILURE MEMORY: structured causes, never just "failure".
            CREATE TABLE IF NOT EXISTS failure_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT,
                cause TEXT NOT NULL,
                platform TEXT,
                category TEXT,
                task_type TEXT,
                strategy_used TEXT,
                proposal_variant TEXT,
                details TEXT,
                revenue REAL DEFAULT 0,
                cost REAL DEFAULT 0,
                effort_hours REAL DEFAULT 0,
                ts REAL
            );

            -- 8. SUCCESS MEMORY: structured causes, WHY it worked.
            CREATE TABLE IF NOT EXISTS success_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT,
                cause TEXT NOT NULL,
                platform TEXT,
                category TEXT,
                task_type TEXT,
                strategy_used TEXT,
                proposal_variant TEXT,
                details TEXT,
                revenue REAL DEFAULT 0,
                cost REAL DEFAULT 0,
                effort_hours REAL DEFAULT 0,
                ts REAL
            );

            -- 9. USER PREFERENCE MEMORY: learned earning preferences.
            CREATE TABLE IF NOT EXISTS user_pref_memory (
                pref_key TEXT PRIMARY KEY,
                pref_value TEXT,
                confidence REAL DEFAULT 0,
                sample_size INTEGER DEFAULT 0,
                last_updated REAL
            );

            -- 10. SOURCE/PLATFORM MEMORY: per-source reliability + payout behavior.
            CREATE TABLE IF NOT EXISTS source_memory (
                source TEXT PRIMARY KEY,
                platform TEXT,
                discovered INTEGER DEFAULT 0,
                accepted INTEGER DEFAULT 0,
                paid INTEGER DEFAULT 0,
                disputed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                total_revenue REAL DEFAULT 0,
                avg_payout_hours REAL DEFAULT 0,
                reliability REAL DEFAULT 0,
                last_seen REAL
            );

            -- ===== Prediction Accuracy (v2.0.36d) =====
            -- Append-only log of predicted-vs-actual comparisons. Drives "prediction accuracy"
            -- tracking and lets the system learn from prediction error. Raw history retained.
            CREATE TABLE IF NOT EXISTS prediction_accuracy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT NOT NULL,
                dim TEXT NOT NULL,            -- category | platform | task_type | global
                dim_value TEXT NOT NULL,
                predicted_effort REAL DEFAULT 0,
                actual_effort REAL DEFAULT 0,
                predicted_revenue REAL DEFAULT 0,
                actual_revenue REAL DEFAULT 0,
                predicted_success_prob REAL DEFAULT 0,
                actual_success INTEGER DEFAULT 0,   -- 1 success, 0 failure
                effort_err_pct REAL DEFAULT 0,
                revenue_err_pct REAL DEFAULT 0,
                success_correct INTEGER DEFAULT 0,  -- 1 if predicted prob>=0.5 matched actual
                ts REAL
            );

            -- ===== Search Strategy (v2.0.36f) =====
            -- Tracks which generated search strategies actually produce profitable work. This is the
            -- learning link the user asked for: "learning which search strategies actually produce
            -- profitable work." Each strategy is generated (from skills/history/prefs/emerging/terms)
            -- and tagged onto discovered opportunities as provenance (strategy:<id>).
            CREATE TABLE IF NOT EXISTS search_strategy (
                strategy_id TEXT PRIMARY KEY,
                origin TEXT,                -- SKILL | HISTORICAL_CATEGORY | USER_PREFERENCE |
                                           -- EMERGING | PAST_SUCCESS_TERM | PAST_FAILED_TERM |
                                           -- PLATFORM_TERM | EXPLORATION
                query TEXT,                -- raw search query
                normalized_query TEXT,    -- lowercased/stemmed/stopword-stripped form
                platform TEXT,            -- platform the search targets (if known)
                category TEXT,            -- primary category (single canonical value)
                task_type TEXT,           -- task_type this strategy is tuned for
                source TEXT,              -- discovery source used
                categories TEXT,          -- JSON list (back-compat / multi)
                used_count INTEGER DEFAULT 0,
                result_count INTEGER DEFAULT 0,        -- total opps returned
                useful_result_count INTEGER DEFAULT 0, -- legit, on-topic, actionable opps
                duplicate_count INTEGER DEFAULT 0,     -- near-dup opps seen
                accepted INTEGER DEFAULT 0,            -- accepted offers
                completed INTEGER DEFAULT 0,           -- completed engagements
                paid INTEGER DEFAULT 0,                -- paid engagements
                net_revenue REAL DEFAULT 0,            -- sum of net revenue ($)
                effort_sum REAL DEFAULT 0,             -- sum of effort hours
                reward_sum REAL DEFAULT 0,             -- composite usefulness reward
                last_used REAL,
                created_at REAL
            );

            -- 1. CONVERSATIONAL MEMORY: user directives/feedback (summarized, not chat logs).
            CREATE TABLE IF NOT EXISTS conversational_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                directive TEXT NOT NULL,
                context TEXT,
                confidence REAL DEFAULT 0,
                ts REAL
            );

            -- 2. OPERATIONAL MEMORY: pipeline/run state (summarized).
            CREATE TABLE IF NOT EXISTS operational_memory (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL
            );

            -- Outcome <-> Evidence linkage (v2.0.36d). Many evidence records may back one
            -- outcome. Append-only; supports "associate evidence" in the learning loop.
            CREATE TABLE IF NOT EXISTS outcome_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                ts REAL
            );

            -- Create indexes
            CREATE INDEX IF NOT EXISTS idx_opp_type ON opportunity_memory(memory_type);
            CREATE INDEX IF NOT EXISTS idx_outcome_tags ON outcome_memory(tags);
            CREATE INDEX IF NOT EXISTS idx_skill_platforms ON skill_memory(platforms);
            CREATE INDEX IF NOT EXISTS idx_pattern_type ON pattern_memory(pattern_type);
            CREATE INDEX IF NOT EXISTS idx_decay_entity ON decay_log(entity_type, entity_key);
        """)
        conn.commit()
        conn.close()

    def _migrate_schema(self):
        """Non-destructive ALTERs for columns/tables added after a DB was first created.

        New tables are handled by CREATE IF NOT EXISTS in _init_db; existing tables need
        explicit ALTER ADD COLUMN (SQLite does not support ADD COLUMN IF NOT EXISTS).
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            # outcome_memory_v2 prediction columns (v2.0.36d)
            cols = {r[1] for r in cur.execute("PRAGMA table_info(outcome_memory_v2)").fetchall()}
            for col, ctype in (
                ("predicted_effort_hours", "REAL DEFAULT 0"),
                ("predicted_revenue", "REAL DEFAULT 0"),
                ("predicted_success_prob", "REAL DEFAULT 0"),
            ):
                if col not in cols:
                    cur.execute(f"ALTER TABLE outcome_memory_v2 ADD COLUMN {col} {ctype}")
            # search_strategy economic columns (v2.0.36g)
            scols = {r[1] for r in cur.execute("PRAGMA table_info(search_strategy)").fetchall()}
            for col, ctype in (
                ("normalized_query", "TEXT"),
                ("platform", "TEXT"),
                ("category", "TEXT"),
                ("task_type", "TEXT"),
                ("result_count", "INTEGER DEFAULT 0"),
                ("useful_result_count", "INTEGER DEFAULT 0"),
                ("duplicate_count", "INTEGER DEFAULT 0"),
                ("accepted", "INTEGER DEFAULT 0"),
                ("completed", "INTEGER DEFAULT 0"),
                ("paid", "INTEGER DEFAULT 0"),
                ("net_revenue", "REAL DEFAULT 0"),
                ("effort_sum", "REAL DEFAULT 0"),
            ):
                if col not in scols:
                    cur.execute(f"ALTER TABLE search_strategy ADD COLUMN {col} {ctype}")
            conn.commit()
            conn.close()

    def apply_decay(self, entity_type: str, entity_key: str, 
                    factor: float = 0.95) -> float:
        """Apply decay to stats. Returns new value."""
        new_value = self._apply_decay_to_stats(entity_type, entity_key, factor)
        
        # Log decay
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO decay_log (entity_type, entity_key, old_value, new_value, decay_factor, applied_at) VALUES (?, ?, ?, ?, ?, ?)",
                (entity_type, entity_key, 0, new_value, factor, time.time())
            )
            conn.commit()
            conn.close()
        
        return new_value

    def _apply_decay_to_stats(self, entity_type: str, entity_key: str, factor: float) -> float:
        """Apply decay to a specific stat."""
        # For simplicity, return 0 - actual implementation would update DB
        return 0.0

    def periodic_decay(self, decay_factor: float = 0.99):
        """Apply periodic decay to all stats."""
        # Update in-memory stats
        for key in self._stats:
            self._stats[key]["total_revenue"] *= decay_factor
            if self._stats[key]["success"] < 5:  # Decay near-zero stats faster
                self._stats[key]["total_revenue"] *= 0.95

    # ── Tier 1: Opportunity Memory ──────────────────────────────────

    def remember_opportunity(self, opp_id: str, memory_data: dict, opp_type: str):
        """Store an opportunity in memory."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT OR REPLACE INTO opportunity_memory
                   (key, memory_data, memory_type, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (opp_id, json.dumps(memory_data, default=str), opp_type,
                 time.time(), time.time())
            )
            conn.commit()
            conn.close()

        self._cache[f"opp_{opp_id}"] = memory_data

    def get_opportunity_history(self, opp_id: str) -> Optional[dict]:
        """Get history for a specific opportunity."""
        if f"opp_{opp_id}" in self._cache:
            return self._cache[f"opp_{opp_id}"]

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT memory_data, memory_type FROM opportunity_memory WHERE key=?",
                (opp_id,)
            ).fetchone()
            conn.close()

        if row:
            data = json.loads(row[0])
            self._cache[f"opp_{opp_id}"] = data
            return data
        return None

    def get_opportunities_by_type(self, opp_type: str, limit: int = 50) -> List[dict]:
        """Get all opportunities of a specific type."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT key, memory_data FROM opportunity_memory "
                "WHERE memory_type=? LIMIT ?",
                (opp_type, limit)
            ).fetchall()
            conn.close()

        return [json.loads(r[1]) for r in rows]

    # ── Tier 2: Outcome Memory ─────────────────────────────────────

    def record_outcome(self, opp_id: str, action: str, result: str,
                       revenue_usd: float = 0, time_spent: float = 0,
                       success: bool = True, tags: List[str] = None,
                       was_scam: bool = False):
        """Record an outcome from executing an action."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT INTO outcome_memory
                   (opportunity_id, action_taken, result, revenue_usd,
                    time_spent_hours, was_scam, success, tags, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (opp_id, action, result, revenue_usd, time_spent,
                 was_scam, success, json.dumps(tags or [], default=str), time.time())
            )
            conn.commit()
            conn.close()

        # Extract patterns from this outcome
        self._extract_patterns(opp_id, action, result, success, tags, revenue_usd)

        # Update stats
        self._update_stats_from_outcome(opp_id, success, revenue_usd, tags)

    def get_outcome_history(self, opp_id: str) -> List[dict]:
        """Get all outcomes for an opportunity."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT action_taken, result, revenue_usd, time_spent_hours, "
                "was_scam, success, tags, created_at "
                "FROM outcome_memory WHERE opportunity_id=?",
                (opp_id,)
            ).fetchall()
            conn.close()

        keys = ["action", "result", "revenue", "time_spent", "scam", "success", "tags", "ts"]
        return [dict(zip(keys, row)) for row in rows]

    def get_recent_outcomes(self, limit: int = 20) -> List[dict]:
        """Get most recent outcomes."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT opportunity_id, action_taken, result, revenue_usd, "
                "success, created_at FROM outcome_memory "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()

        keys = ["opp_id", "action", "result", "revenue", "success", "ts"]
        return [dict(zip(keys, row)) for row in rows]

    # ── Expanded Outcome Recording (v2.0.35) ──────────────────────────────
    # Rich, structured, append-only outcome events. Fans out into every memory
    # type so later analytics + the Opportunity Intelligence Engine priors update.
    # Deterministic: no LLM in the path. Never stores an unknown enum value.

    def record_opportunity_event(self, opp_id: str, stage: str, detail: str = ""):
        """3. OPPORTUNITY MEMORY: append a lifecycle event to an opportunity's timeline."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO opportunity_timeline (opportunity_id, stage, detail, ts) VALUES (?, ?, ?, ?)",
                (opp_id, stage, detail, time.time()),
            )
            conn.commit()
            conn.close()

    def record_outcome_v2(self, opp_id: str, outcome_state: str, *,
                          platform: str = "", category: str = "", task_type: str = "",
                          revenue: float = 0.0, cost: float = 0.0, net_profit: float = 0.0,
                          effort_hours: float = 0.0, time_spent_hours: float = 0.0,
                          strategy_used: str = "", proposal_variant: str = "",
                          model_used: str = "", human_intervention: bool = False,
                          automation_level: float = 0.0,
                          reason: str = "", evidence: str = "",
                          failure_cause: str = "", success_cause: str = "",
                          disputed: bool = False,
                          predicted_effort_hours: float = 0.0,
                          predicted_revenue: float = 0.0,
                          predicted_success_prob: float = 0.0) -> Optional[int]:
        """Record a rich outcome event across all learning-memory types.

        `outcome_state` must be one of OUTCOME_STATES (else rejected).
        `failure_cause` must be one of FAILURE_CAUSES (else ignored).
        `success_cause` must be one of SUCCESS_CAUSES (else ignored).
        `predicted_*` (optional) capture the pre-execution forecast so we can compute
        prediction error / accuracy (v2.0.36d). They default to 0 (no prediction recorded).

        Fan-out:
          - outcome_memory_v2 (append-only raw event)
          - opportunity_timeline (WHAT happened to this opportunity)
          - failure_memory / success_memory (structured WHY)
          - strategy_memory (strategy/variant success|failure + WHY)
          - source_memory (platform reliability counts + revenue)
          - category/task-type priors (so the Intelligence Engine updates)
          - reputation_memory (platform win/loss) for accepted/paid/rejected_pay
        Returns the outcome row id, or None if rejected.
        """
        if outcome_state not in OUTCOME_STATES:
            # Deterministic guard: never silently store an unknown state.
            return None
        fc = failure_cause if failure_cause in FAILURE_CAUSES else ""
        sc = success_cause if success_cause in SUCCESS_CAUSES else ""

        is_success = outcome_state in ("accepted", "completed", "submitted", "paid")
        is_failure = outcome_state in ("failed", "rejected_apply", "rejected_pay",
                                       "abandoned", "payment_disputed")
        if not net_profit:
            net_profit = revenue - cost

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute(
                """INSERT INTO outcome_memory_v2
                   (opportunity_id, outcome_state, platform, category, task_type,
                    revenue, cost, net_profit, effort_hours, time_spent_hours,
                    strategy_used, proposal_variant, model_used, human_intervention,
                    automation_level, reason, evidence, failure_cause, success_cause,
                    disputed, predicted_effort_hours, predicted_revenue, predicted_success_prob, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (opp_id, outcome_state, platform, category, task_type,
                 revenue, cost, net_profit, effort_hours, time_spent_hours,
                 strategy_used, proposal_variant, model_used, int(bool(human_intervention)),
                 automation_level, reason, evidence, fc, sc,
                 int(bool(disputed)),
                 predicted_effort_hours, predicted_revenue, predicted_success_prob,
                 time.time()),
            )
            oid = cur.lastrowid
            conn.commit()
            conn.close()

        # Opportunity timeline
        self.record_opportunity_event(opp_id, outcome_state,
                                     f"rev={revenue} net={net_profit} strat={strategy_used}")

        # Structured WHY memories
        if is_failure and fc:
            self._record_failure(opp_id, fc, platform, category, task_type,
                                 strategy_used, proposal_variant, reason or evidence,
                                 revenue, cost, effort_hours)
        if is_success and sc:
            self._record_success(opp_id, sc, platform, category, task_type,
                                 strategy_used, proposal_variant, reason or evidence,
                                 revenue, cost, effort_hours)

        # Strategy memory
        if strategy_used:
            self._record_strategy(strategy_used, proposal_variant, is_success, is_failure,
                                  revenue, sc, fc)

        # Source/platform memory
        if platform:
            self._record_source(platform, outcome_state, revenue)

        # Category / task-type priors (feed the Intelligence Engine)
        if category:
            self.record_category_outcome(category, is_success, revenue)
        if task_type:
            self.record_task_type_outcome(task_type, is_success, revenue)

        # Reputation (platform win/loss) for accept/pay/reject-pay outcomes
        if platform and outcome_state in ("accepted", "paid"):
            self.update_reputation(platform, success=True, revenue=revenue)
        elif platform and outcome_state in ("rejected_pay", "failed", "payment_disputed"):
            self.update_reputation(platform, success=False)

        # Prediction accuracy: compare forecast vs actual (v2.0.36d). Only meaningful when a
        # prediction was supplied (predicted_success_prob > 0 OR predicted_effort/revenue > 0).
        if (predicted_success_prob > 0.0 or predicted_effort_hours > 0.0 or predicted_revenue > 0.0):
            self._record_prediction(
                opp_id, outcome_state, platform, category, task_type,
                predicted_effort_hours, effort_hours,
                predicted_revenue, revenue,
                predicted_success_prob, is_success,
            )

        return oid

    def _record_prediction(self, opp_id, outcome_state, platform, category, task_type,
                           predicted_effort, actual_effort, predicted_revenue, actual_revenue,
                           predicted_success_prob, is_success):
        """Append a predicted-vs-actual comparison row (v2.0.36d). Deterministic."""
        def _err_pct(pred, actual):
            if pred == 0 and actual == 0:
                return 0.0
            if pred == 0:
                return 1.0  # completely missed (predicted nothing, got something)
            return abs(actual - pred) / abs(pred)

        effort_err = _err_pct(predicted_effort, actual_effort)
        revenue_err = _err_pct(predicted_revenue, actual_revenue)
        # success correct: did the model's probability forecast match the binary outcome?
        success_correct = 1 if ((predicted_success_prob >= 0.5) == bool(is_success)) else 0

        rows = [
            ("global", "global"),
            ("category", category or "unknown"),
            ("platform", platform or "unknown"),
            ("task_type", task_type or "unknown"),
        ]
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            for dim, dim_value in rows:
                if dim_value in ("", None):
                    continue
                conn.execute(
                    """INSERT INTO prediction_accuracy
                       (opportunity_id, dim, dim_value, predicted_effort, actual_effort,
                        predicted_revenue, actual_revenue, predicted_success_prob, actual_success,
                        effort_err_pct, revenue_err_pct, success_correct, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (opp_id, dim, dim_value,
                     predicted_effort, actual_effort, predicted_revenue, actual_revenue,
                     predicted_success_prob, 1 if is_success else 0,
                     effort_err, revenue_err, success_correct, time.time()),
                )
            conn.commit()
            conn.close()

    def link_outcome_evidence(self, opportunity_id: str, evidence_id: str):
        """Associate a verified Evidence record with an outcome (v2.0.36d). Append-only."""
        if not evidence_id:
            return
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO outcome_evidence (opportunity_id, evidence_id, ts) VALUES (?, ?, ?)",
                (opportunity_id, evidence_id, time.time()),
            )
            conn.commit()
            conn.close()

    def get_outcome_evidence(self, opportunity_id: str) -> List[str]:
        """Return evidence ids linked to an outcome."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT evidence_id FROM outcome_evidence WHERE opportunity_id=? ORDER BY ts",
                (opportunity_id,),
            ).fetchall()
            conn.close()
        return [r[0] for r in rows]

    # ── Search Strategy learning (v2.0.36f) ──────────────────────
    def record_search_strategy(self, strategy_id: str, origin: str, query: str,
                                categories: List[str], source: str,
                                platform: str = "", category: str = "",
                                task_type: str = "") -> None:
        """Record (or touch) a generated search strategy. Its ECONOMIC outcomes are
        learned over time via record_strategy_result(). We track the exact query AND a
        normalized form so the system can recognize semantically related searches that
        may have very different economic outcomes.
        """
        if not strategy_id:
            return
        cats_json = json.dumps(categories or [], ensure_ascii=False, default=str)
        norm = _normalize_query(query)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT INTO search_strategy
                   (strategy_id, origin, query, normalized_query, platform, category,
                    task_type, categories, source, used_count, created_at, last_used)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(strategy_id) DO UPDATE SET
                       used_count = used_count + 1, last_used = excluded.last_used,
                       origin = excluded.origin, source = excluded.source,
                       categories = excluded.categories,
                       normalized_query = excluded.normalized_query,
                       platform = COALESCE(excluded.platform, platform),
                       category = COALESCE(excluded.category, category),
                       task_type = COALESCE(excluded.task_type, task_type)""",
                (strategy_id, origin, query, norm, platform, category,
                 task_type, cats_json, source, time.time(), time.time()),
            )
            conn.commit()
            conn.close()

    def record_strategy_result(self, strategy_id: str, *, result_count: int = 0,
                               useful_result_count: int = 0, duplicate_count: int = 0,
                               accepted: int = 0, completed: int = 0, paid: int = 0,
                               net_revenue: float = 0.0, effort_hours: float = 0.0) -> None:
        """Learn the ECONOMIC outcome of a search strategy (v2.0.36g).

        Optimizes for USEFUL, LEGITIMATE, PROFITABLE opportunities — NOT raw result count.
        reward_sum is a composite usefulness reward:
            reward = useful_result_count * W_USEFUL
                   + completed * W_COMPLETE + paid * W_PAID
                   + net_revenue (linear, the dominant signal)
                   - duplicate_count * W_DUP   (penalize spammy/duplicate floods)
        """
        if not strategy_id:
            return
        reward = (useful_result_count * _W_USEFUL + completed * _W_COMPLETE
                  + paid * _W_PAID + float(net_revenue)
                  - duplicate_count * _W_DUP)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """UPDATE search_strategy SET
                       result_count = result_count + ?,
                       useful_result_count = useful_result_count + ?,
                       duplicate_count = duplicate_count + ?,
                       accepted = accepted + ?,
                       completed = completed + ?,
                       paid = paid + ?,
                       net_revenue = net_revenue + ?,
                       effort_sum = effort_sum + ?,
                       reward_sum = reward_sum + ?,
                       last_used = ?
                   WHERE strategy_id = ?""",
                (int(result_count), int(useful_result_count), int(duplicate_count),
                 int(accepted), int(completed), int(paid), float(net_revenue),
                 float(effort_hours), float(reward), time.time(), strategy_id),
            )
            conn.commit()
            conn.close()

    # Thin back-compat wrapper: the scheduler's record_outcome() historically called
    # record_strategy_outcome(success, reward). Map that onto the economic counters.
    def record_strategy_outcome(self, strategy_id: str, success: bool, reward: float = 0.0) -> None:
        if not strategy_id:
            return
        self.record_strategy_result(
            strategy_id, result_count=1, useful_result_count=1 if success else 0,
            completed=1 if success else 0, paid=1 if success else 0,
            net_revenue=float(reward) if success else 0.0)

    def get_search_strategy_stats(self, strategy_id: str) -> dict:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                """SELECT strategy_id, origin, query, normalized_query, platform, category,
                          task_type, source, used_count, result_count, useful_result_count,
                          duplicate_count, accepted, completed, paid, net_revenue,
                          effort_sum, reward_sum, last_used, created_at
                   FROM search_strategy WHERE strategy_id=?""",
                (strategy_id,),
            ).fetchone()
            conn.close()
        if not row:
            return {}
        (sid, origin, query, norm, platform, category, task_type, source, used,
         result_count, useful, dups, accepted, completed, paid, net_rev, effort,
         reward, last_used, created_at) = row
        used = int(used or 0)
        result_count = int(result_count or 0)
        useful = int(useful or 0)
        dups = int(dups or 0)
        accepted = int(accepted or 0)
        completed = int(completed or 0)
        paid = int(paid or 0)
        net_rev = float(net_rev or 0.0)
        effort = float(effort or 0.0)
        return {
            "strategy_id": sid, "origin": origin, "query": query, "normalized_query": norm,
            "platform": platform, "category": category, "task_type": task_type, "source": source,
            "used_count": used, "result_count": result_count, "useful_result_count": useful,
            "duplicate_count": dups, "accepted": accepted, "completed": completed, "paid": paid,
            "net_revenue": net_rev, "effort_sum": effort, "reward_sum": float(reward or 0.0),
            "last_used": float(last_used or 0.0), "created_at": float(created_at or 0.0),
            "useful_rate": _safe_rate(useful, result_count),
            "duplicate_rate": _safe_rate(dups, result_count) if result_count else 0.0,
            "acceptance_rate": _safe_rate(accepted, result_count),
            "completion_rate": _safe_rate(completed, result_count),
            "payment_rate": _safe_rate(paid, completed) if completed else 0.0,
            "avg_effort": (effort / completed) if completed else 0.0,
            "usefulness": _strategy_usefulness(used, result_count, useful, completed, paid, net_rev, dups),
            "cold_start": used < MIN_SAMPLES,
        }

    def top_search_strategies(self, n: int = 10, min_used: int = 1,
                              by: str = "usefulness") -> List[dict]:
        """Strategies ranked for EXPLOITATION.

        Default `by="usefulness"` ranks on the composite economic metric
        (useful + completed + paid + net_revenue - duplicates) — NOT raw result count.
        `by="success"` keeps the old success_count ordering for back-compat.
        Novel strategies (used_count < MIN_SAMPLES) are NOT suppressed: they are ranked
        with a neutral prior so the scheduler can still explore them.
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT strategy_id, origin, query, used_count, result_count,
                          useful_result_count, completed, paid, net_revenue,
                          duplicate_count, reward_sum
                   FROM search_strategy WHERE used_count >= ?""",
                (min_used,),
            ).fetchall()
            conn.close()
        out = []
        for r in rows:
            (sid, origin, query, used, result_count, useful, completed, paid,
             net_rev, dups, reward) = r
            used = int(used or 0)
            result_count = int(result_count or 0)
            useful = int(useful or 0)
            completed = int(completed or 0)
            paid = int(paid or 0)
            net_rev = float(net_rev or 0.0)
            dups = int(dups or 0)
            u = _strategy_usefulness(used, result_count, useful, completed, paid, net_rev, dups)
            out.append({
                "strategy_id": sid, "origin": origin, "query": query, "used_count": used,
                "result_count": result_count, "useful_result_count": useful,
                "completed": completed, "paid": paid, "net_revenue": net_rev,
                "reward_sum": float(reward or 0.0),
                "usefulness": u, "cold_start": used < MIN_SAMPLES,
            })
        if by == "success":
            out.sort(key=lambda d: (d["useful_result_count"], d["net_revenue"]), reverse=True)
        else:
            out.sort(key=lambda d: d["usefulness"], reverse=True)
        return out[:n]

    def explore_search_strategies(self, n: int = 10, max_used: int = MIN_SAMPLES) -> List[dict]:
        """Novel/under-tried strategies to keep EXPLORATION alive.

        Returns strategies with used_count <= max_used, ranked by recency (last_used desc)
        with a neutral usefulness prior — so historical performance never permanently
        suppresses a novel search. The scheduler's exploration floor then guarantees they
        get tried.
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT strategy_id, origin, query, used_count, last_used
                   FROM search_strategy WHERE used_count <= ? ORDER BY last_used DESC""",
                (max_used,),
            ).fetchall()
            conn.close()
        out = [{"strategy_id": r[0], "origin": r[1], "query": r[2],
                "used_count": int(r[3] or 0), "last_used": float(r[4] or 0.0),
                "usefulness": 0.0, "cold_start": True} for r in rows]
        return out[:n]

    def get_successful_search_terms(self, n: int = 20) -> List[str]:
        """Queries that have produced USEFUL/profitable work — feed exploitation.

        Ranked by composite usefulness (net_revenue + useful + completed + paid), not just
        result count, so a high-volume-but-useless query is NOT surfaced as a 'success'.
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT query, net_revenue, useful_result_count, completed, paid
                   FROM search_strategy WHERE used_count >= 1 AND useful_result_count > 0
                   ORDER BY (net_revenue + useful_result_count + completed + paid) DESC LIMIT ?""",
                (n,),
            ).fetchall()
            conn.close()
        return [r[0] for r in rows if r[0]]

    def get_failed_search_terms(self, n: int = 20) -> List[str]:
        """Queries that never produced useful work — feed avoidance/recycling.

        A query is 'failed' only if it has enough samples (used >= MIN_SAMPLES) and
        produced NO useful results. Low-sample novel queries are NOT flagged as failures
        (cold-start safe — they get a chance).
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT query FROM search_strategy
                   WHERE used_count >= ? AND useful_result_count = 0
                   ORDER BY used_count DESC LIMIT ?""",
                (MIN_SAMPLES, n),
            ).fetchall()
            conn.close()
        return [r[0] for r in rows if r[0]]

    def _record_failure(self, opp_id, cause, platform, category, task_type,
                        strategy_used, proposal_variant, details, revenue, cost, effort_hours):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT INTO failure_memory
                   (opportunity_id, cause, platform, category, task_type, strategy_used,
                    proposal_variant, details, revenue, cost, effort_hours, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (opp_id, cause, platform, category, task_type, strategy_used,
                 proposal_variant, details, revenue, cost, effort_hours, time.time()),
            )
            conn.commit()
            conn.close()

    def _record_success(self, opp_id, cause, platform, category, task_type,
                        strategy_used, proposal_variant, details, revenue, cost, effort_hours):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT INTO success_memory
                   (opportunity_id, cause, platform, category, task_type, strategy_used,
                    proposal_variant, details, revenue, cost, effort_hours, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (opp_id, cause, platform, category, task_type, strategy_used,
                 proposal_variant, details, revenue, cost, effort_hours, time.time()),
            )
            conn.commit()
            conn.close()

    def _record_strategy(self, strategy, variant, is_success, is_failure,
                         revenue, success_cause, failure_cause):
        variant = variant or ""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            # Upsert by (strategy, variant)
            row = conn.execute(
                "SELECT success_count, failure_count FROM strategy_memory WHERE strategy=? AND variant=?",
                (strategy, variant),
            ).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO strategy_memory
                       (strategy, variant, success_count, failure_count, total_revenue,
                        success_cause, failure_cause, confidence, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (strategy, variant, 1 if is_success else 0, 1 if is_failure else 0,
                     revenue, success_cause, failure_cause,
                     _confidence_for_samples(1), time.time()),
                )
            else:
                sc = int(row[0] or 0) + (1 if is_success else 0)
                fc = int(row[1] or 0) + (1 if is_failure else 0)
                total = sc + fc
                conf = _confidence_for_samples(total)
                conn.execute(
                    """UPDATE strategy_memory SET success_count=?, failure_count=?,
                       total_revenue = total_revenue + ?, confidence=?, last_seen=?
                       WHERE strategy=? AND variant=?""",
                    (sc, fc, revenue, conf, time.time(), strategy, variant),
                )
            conn.commit()
            conn.close()

    def _record_source(self, source, outcome_state, revenue):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("INSERT OR IGNORE INTO source_memory (source) VALUES (?)", (source,))
            col = {
                "discovered": "discovered",
                "accepted": "accepted",
                "paid": "paid",
                "payment_disputed": "disputed",
                "failed": "failed",
                "rejected_apply": "failed",
                "rejected_pay": "failed",
                "abandoned": "failed",
            }.get(outcome_state)
            if col:
                conn.execute(
                    f"UPDATE source_memory SET {col} = {col} + 1, last_seen = ? WHERE source = ?",
                    (time.time(), source),
                )
            if outcome_state == "paid":
                conn.execute(
                    "UPDATE source_memory SET total_revenue = total_revenue + ?, last_seen = ? WHERE source = ?",
                    (revenue, time.time(), source),
                )
            conn.commit()
            conn.close()

    # ── Tier 3: Skill Memory ───────────────────────────────────────

    def remember_success(self, skill: str, platform: str, revenue: float):
        """Remember that a skill was successful on a platform."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT success_count, total_revenue, platforms FROM skill_memory WHERE skill=?",
                (skill,)
            ).fetchone()

            now = time.time()
            if row is None:
                platforms = [platform]
                conn.execute(
                    """INSERT INTO skill_memory
                       (skill, success_count, failed_count, total_revenue, platforms, last_used)
                       VALUES (?, 1, 0, ?, ?, ?)""",
                    (skill, revenue, json.dumps(platforms, default=str), now)
                )
            else:
                success_count = int(row[0] or 0) + 1
                total_revenue = float(row[1] or 0.0) + revenue
                existing_platforms_raw = row[2]
                try:
                    existing_platforms = json.loads(existing_platforms_raw) if existing_platforms_raw else []
                except (TypeError, json.JSONDecodeError):
                    existing_platforms = []

                if not isinstance(existing_platforms, list):
                    existing_platforms = [str(existing_platforms)]
                if platform not in existing_platforms:
                    existing_platforms.append(platform)

                conn.execute(
                    """UPDATE skill_memory
                       SET success_count=?, total_revenue=?, platforms=?, last_used=?
                       WHERE skill=?""",
                    (success_count, total_revenue, json.dumps(existing_platforms, default=str), now, skill)
                )
            conn.commit()
            conn.close()

        self._stats[skill]["success"] += 1
        self._stats[skill]["total_revenue"] += revenue

    def get_successful_skills(self, min_success: int = 1, limit: int = 20) -> List[dict]:
        """Get skills that have been successful."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT skill, success_count, failed_count, total_revenue, platforms "
                "FROM skill_memory WHERE success_count >= ? ORDER BY total_revenue DESC LIMIT ?",
                (min_success, limit)
            ).fetchall()
            conn.close()

        keys = ["skill", "success", "failed", "revenue", "platforms"]
        result = []
        for row in rows:
            d = dict(zip(keys, row))
            d["platforms"] = json.loads(d["platforms"]) if isinstance(d["platforms"], str) else d["platforms"]
            result.append(d)
        return result

    # ── Tier 4: Reputation Memory ─────────────────────────────────

    def update_reputation(self, platform: str, success: bool, revenue: float = 0):
        """Update platform reputation."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            if success:
                conn.execute(
                    """INSERT INTO reputation_memory (platform, success_count, avg_revenue, total_attempts, last_attempt)
                       VALUES (?, 1, ?, 1, ?)
                       ON CONFLICT(platform) DO UPDATE SET
                         success_count = success_count + 1,
                         total_attempts = total_attempts + 1,
                         avg_revenue = (avg_revenue * (total_attempts - 1) + ?) / total_attempts,
                         last_attempt = ?""",
                    (platform, revenue, time.time(), revenue, time.time())
                )
            else:
                conn.execute(
                    """INSERT OR IGNORE INTO reputation_memory (platform) VALUES (?)""",
                    (platform,)
                )
                conn.execute(
                    """UPDATE reputation_memory SET failed_count = failed_count + 1,
                       total_attempts = total_attempts + 1, last_attempt = ?
                       WHERE platform = ?""",
                    (time.time(), platform)
                )
            conn.commit()
            conn.close()

    def get_platform_reputation(self, platform: str) -> dict:
        """Get reputation metrics for a platform."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT success_count, failed_count, scam_count, avg_revenue, total_attempts "
                "FROM reputation_memory WHERE platform=?",
                (platform,)
            ).fetchone()
            conn.close()

        if row:
            total = row[4]
            return {
                "platform": platform,
                "success": row[0],
                "failed": row[1],
                "scam": row[2],
                "avg_revenue": row[3],
                "total": total,
                "success_rate": row[0] / total if total else 0
            }
        return {"platform": platform, "success": 0, "failed": 0, "scam": 0, "avg_revenue": 0, "total": 0, "success_rate": 0}

    # ── A5: explicit win/loss intent API (thin wrappers over update_reputation) ──

    def record_win(self, platform: str, revenue: float = 0.0):
        """A5: a proposal on `platform` was accepted/won. Feeds the win-rate guard."""
        self.update_reputation(platform, success=True, revenue=revenue)

    def record_loss(self, platform: str):
        """A5: a proposal on `platform` was rejected/lost. Feeds the win-rate guard."""
        self.update_reputation(platform, success=False)

    def record_attempt(self, platform: str) -> None:
        """C2 (H39 fix): record that a proposal was *submitted* on `platform`,
        bumping `total_attempts` WITHOUT crediting a success or a failure.

        This lets the submission ramp's cold-start gate progress (need N
        submissions before auto-unlock is even considered) while keeping the
        win-rate honest: a mere submission is NOT counted as a win. The real
        accept/reject is recorded later via `record_win`/`record_loss` when the
        outcome is actually known (paid / rejected / failed).
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO reputation_memory (platform) VALUES (?)",
                    (platform,),
                )
                conn.execute(
                    "UPDATE reputation_memory SET total_attempts = total_attempts + 1, "
                    "last_attempt = ? WHERE platform = ?",
                    (time.time(), platform),
                )
                conn.commit()
            finally:
                conn.close()

    def get_all_reputations(self) -> List[dict]:
        """Get reputation for all platforms."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT platform, success_count, failed_count, scam_count, avg_revenue, total_attempts "
                "FROM reputation_memory ORDER BY total_attempts DESC"
            ).fetchall()
            conn.close()

        results = []
        for row in rows:
            total = row[5]
            success_rate = row[1] / total if total else 0
            results.append({
                "platform": row[0],
                "success": row[1],
                "failed": row[2],
                "scam": row[3],
                "avg_revenue": row[4],
                "total": total,
                "success_rate": success_rate
            })
        return results

    # ── Tier 5: Pattern Memory (Learning) ─────────────────────────

    def _extract_patterns(self, opp_id: str, action: str, result: str,
                          success: bool, tags: List[str], revenue: float):
        """Extract learning patterns from outcomes."""
        # Pattern: action type -> success
        self._store_pattern("action_success", action, success, revenue)
        
        # Pattern: tag combinations
        if tags:
            for tag in tags:
                self._store_pattern("tag_success", tag, success, revenue)
        
        # Pattern: platform + action combination
        opp_mem = self.get_opportunity_history(opp_id)
        if opp_mem:
            platform = opp_mem.get("platform", "unknown")
            self._store_pattern("platform_action", f"{platform}_{action}", success, revenue)

    def _store_pattern(self, pattern_type: str, pattern_key: str, 
                       success: bool, revenue: float):
        """Store a pattern in memory."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            if success:
                conn.execute(
                    """INSERT INTO pattern_memory 
                       (pattern_type, pattern_key, success_count, total_revenue, confidence, last_seen)
                       VALUES (?, ?, 1, ?, 0.8, ?)
                       ON CONFLICT(pattern_type, pattern_key) DO UPDATE SET
                         success_count = success_count + 1,
                         total_revenue = total_revenue + ?,
                         confidence = MIN(1.0, confidence + 0.1),
                         last_seen = ?""",
                    (pattern_type, pattern_key, revenue, time.time(), revenue, time.time())
                )
            else:
                conn.execute(
                    """INSERT INTO pattern_memory 
                       (pattern_type, pattern_key, failure_count, confidence, last_seen)
                       VALUES (?, ?, 1, 0.1, ?)
                       ON CONFLICT(pattern_type, pattern_key) DO UPDATE SET
                         failure_count = failure_count + 1,
                         confidence = MAX(0.0, confidence - 0.05),
                         last_seen = ?""",
                    (pattern_type, pattern_key, time.time(), time.time())
                )
            conn.commit()
            conn.close()

    def get_pattern_confidence(self, pattern_type: str, pattern_key: str) -> float:
        """Get confidence score for a pattern."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT confidence, success_count, failure_count FROM pattern_memory WHERE pattern_type=? AND pattern_key=?",
                (pattern_type, pattern_key)
            ).fetchone()
            conn.close()

        if row and row[0] > 0:
            return row[0]
        return 0.0

    # ── Cold-start-aware history helpers (reuse pattern_memory) ──
    # These give the Opportunity Intelligence Engine category- and task-type-level
    # historical performance WITHOUT a schema change. When no samples exist, the
    # engine applies its NEUTRAL PRIOR (never rejects for lack of data).

    def record_category_outcome(self, category: str, success: bool, revenue: float = 0.0):
        """Record an outcome for a category (feeds cold-start priors)."""
        if not category:
            return
        self._store_pattern("category_success", category, success, revenue)

    def get_category_history(self, category: str) -> dict:
        """Return {success, failed, total, success_rate, avg_revenue, confidence}."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT success_count, failure_count, total_revenue, confidence "
                "FROM pattern_memory WHERE pattern_type=? AND pattern_key=?",
                ("category_success", category),
            ).fetchone()
            conn.close()
        if row:
            success = int(row[0] or 0)
            failed = int(row[1] or 0)
            total = success + failed
            avg_rev = (row[2] or 0.0)
            return {
                "success": success, "failed": failed, "total": total,
                "success_rate": _safe_rate(success, total),
                "avg_revenue": avg_rev, "confidence": row[3] or 0.0,
            }
        return {"success": 0, "failed": 0, "total": 0, "success_rate": 0.0,
                "avg_revenue": 0.0, "confidence": 0.0}

    def record_task_type_outcome(self, task_type: str, success: bool, revenue: float = 0.0):
        """Record an outcome for a task-type (feeds cold-start priors)."""
        if not task_type:
            return
        self._store_pattern("tasktype_success", task_type, success, revenue)

    def get_task_type_history(self, task_type: str) -> dict:
        """Return {success, failed, total, success_rate, avg_revenue, confidence}."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT success_count, failure_count, total_revenue, confidence "
                "FROM pattern_memory WHERE pattern_type=? AND pattern_key=?",
                ("tasktype_success", task_type),
            ).fetchone()
            conn.close()
        if row:
            success = int(row[0] or 0)
            failed = int(row[1] or 0)
            total = success + failed
            return {
                "success": success, "failed": failed, "total": total,
                "success_rate": _safe_rate(success, total),
                "avg_revenue": (row[2] or 0.0), "confidence": row[3] or 0.0,
            }
        return {"success": 0, "failed": 0, "total": 0, "success_rate": 0.0,
                "avg_revenue": 0.0, "confidence": 0.0}


    def get_successful_patterns(self, pattern_type: str, min_confidence: float = 0.5) -> List[dict]:
        """Get patterns that have been successful."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT pattern_key, success_count, failure_count, total_revenue, confidence "
                "FROM pattern_memory WHERE pattern_type=? AND confidence >= ? ORDER BY confidence DESC",
                (pattern_type, min_confidence)
            ).fetchall()
            conn.close()

        keys = ["pattern", "success", "failed", "revenue", "confidence"]
        return [dict(zip(keys, row)) for row in rows]

    def get_win_rates_by_platform(self) -> List[dict]:
        """Return per-platform win-rate summary (reputation-backed).

        Answers 'Which platforms pay me reliably?' / 'Which platforms have poor
        acceptance rates?'. Each entry carries sample_size + confidence so callers
        stay cold-start safe.
        """
        reps = self.get_all_reputations()
        out = []
        for r in reps:
            total = int(r.get("total", 0) or 0)
            out.append({
                "platform": r.get("platform"),
                "success_rate": r.get("success_rate", 0.0),
                "scam_rate": _safe_rate(int(r.get("scam", 0) or 0), total) if total else 0.0,
                "avg_revenue": r.get("avg_revenue", 0.0),
                "sample_size": total,
                "confidence": _confidence_for_samples(total),
                "cold_start": total < MIN_SAMPLES,
            })
        return out

    # ── Analytics: answers the 12 user questions (confidence + sample size) ──
    # Every query returns aggregated values WITH sample_size + confidence so the
    # caller can stay cold-start safe (never overlearn from n=1).

    def _agg(self, rows, value_fn, label_key="key"):
        """Helper: build {value, sample_size, confidence, cold_start} from aggregated rows."""
        out = []
        for r in rows:
            n = int(r.get("total", 0) or 0)
            out.append({
                label_key: r.get(label_key),
                "value": value_fn(r),
                "sample_size": n,
                "confidence": _confidence_for_samples(n),
                "cold_start": n < MIN_SAMPLES,
            })
        return out

    def best_performing_task_types(self, limit: int = 10) -> List[dict]:
        """Q: What types of work do I perform best? (success_rate by task_type)."""
        rows = self.get_task_type_history_all()
        rows = [r for r in rows if r["total"] > 0]
        rows.sort(key=lambda r: r["success_rate"], reverse=True)
        return self._agg(rows[:limit], lambda r: r["success_rate"], "task_type")

    def most_reliable_platforms(self, limit: int = 10) -> List[dict]:
        """Q: Which platforms pay me reliably? (success_rate by platform, desc)."""
        rows = self.get_win_rates_by_platform()
        rows = [r for r in rows if r["sample_size"] > 0]
        rows.sort(key=lambda r: (r["success_rate"], r["avg_revenue"]), reverse=True)
        return rows[:limit]

    def highest_net_hourly_categories(self, limit: int = 10) -> List[dict]:
        """Q: Which categories have the highest net hourly return?

        Computed from outcome_memory_v2: net_profit / time_spent_hours, aggregated.
        """
        rows = self._category_net_hourly()
        rows.sort(key=lambda r: r["net_hourly"], reverse=True)
        return self._agg(rows[:limit], lambda r: r["net_hourly"], "category")

    def time_wasting_categories(self, limit: int = 10) -> List[dict]:
        """Q: Which categories repeatedly waste time? (low/negative net hourly + high effort)."""
        rows = self._category_net_hourly()
        rows.sort(key=lambda r: r["net_hourly"])
        return self._agg(rows[:limit], lambda r: r["net_hourly"], "category")

    def best_proposal_templates(self, limit: int = 10) -> List[dict]:
        """Q: Which proposal variants perform best? (success_rate by variant)."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT proposal_variant, COUNT(*) AS total, "
                "SUM(CASE WHEN outcome_state IN ('accepted','completed','submitted','paid') THEN 1 ELSE 0 END) AS success "
                "FROM outcome_memory_v2 WHERE proposal_variant <> '' GROUP BY proposal_variant"
            ).fetchall()
            conn.close()
        parsed = [{"proposal_variant": r[0], "total": r[1],
                   "success_rate": _safe_rate(r[2], r[1])} for r in rows]
        parsed.sort(key=lambda r: r["success_rate"], reverse=True)
        return self._agg(parsed[:limit], lambda r: r["success_rate"], "proposal_variant")

    def platforms_poor_acceptance(self, limit: int = 10) -> List[dict]:
        """Q: Which platforms have poor acceptance rates? (success_rate asc)."""
        rows = self.get_win_rates_by_platform()
        rows = [r for r in rows if r["sample_size"] > 0]
        rows.sort(key=lambda r: r["success_rate"])
        return rows[:limit]

    def task_types_high_completion(self, limit: int = 10) -> List[dict]:
        """Q: Which task types have high completion rates? (completed/accepted ratio)."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT task_type, COUNT(*) AS total, "
                "SUM(CASE WHEN outcome_state IN ('completed','accepted','submitted','paid') THEN 1 ELSE 0 END) AS done "
                "FROM outcome_memory_v2 WHERE task_type <> '' GROUP BY task_type"
            ).fetchall()
            conn.close()
        parsed = [{"task_type": r[0], "total": r[1],
                   "completion_rate": _safe_rate(r[2], r[1])} for r in rows]
        parsed.sort(key=lambda r: r["completion_rate"], reverse=True)
        return self._agg(parsed[:limit], lambda r: r["completion_rate"], "task_type")

    def profitable_but_often_fail(self, limit: int = 10) -> List[dict]:
        """Q: Which opportunities look profitable but usually fail?

        High advertised potential (from failure_memory cost/low revenue) but high
        failure rate. We flag categories/task_types where failure_count is high
        relative to success AND avg revenue of failures is non-trivial.
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT category, COUNT(*) AS fails, AVG(revenue) AS avg_rev "
                "FROM failure_memory WHERE category <> '' GROUP BY category"
            ).fetchall()
            conn.close()
        parsed = []
        for r in rows:
            cat = r[0]
            hist = self.get_category_history(cat)
            fails = int(r[1] or 0)
            total = hist.get("total", 0) or 0
            fail_rate = _safe_rate(fails, total) if total else 0.0
            parsed.append({
                "category": cat, "fail_rate": fail_rate,
                "sample_size": total, "avg_failed_revenue": r[2] or 0.0,
                "confidence": _confidence_for_samples(total),
                "cold_start": total < MIN_SAMPLES,
            })
        parsed.sort(key=lambda r: (r["fail_rate"], r["avg_failed_revenue"]), reverse=True)
        return parsed[:limit]

    def recurring_failure_causes(self, limit: int = 10) -> List[dict]:
        """Q: Which failures have recurring causes? (cause frequency, desc)."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT cause, COUNT(*) AS n FROM failure_memory GROUP BY cause ORDER BY n DESC"
            ).fetchall()
            conn.close()
        return [{"cause": r[0], "count": r[1],
                 "confidence": _confidence_for_samples(r[1]),
                 "cold_start": r[1] < MIN_SAMPLES} for r in rows[:limit]]

    def reusable_success_strategies(self, limit: int = 10) -> List[dict]:
        """Q: Which successful strategies should be reused? (strategy success_rate desc)."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT strategy, variant, success_count, failure_count, total_revenue "
                "FROM strategy_memory"
            ).fetchall()
            conn.close()
        parsed = []
        for r in rows:
            total = (r[2] or 0) + (r[3] or 0)
            parsed.append({
                "strategy": r[0], "variant": r[1],
                "value": _safe_rate(r[2] or 0, total) if total else 0.0,
                "sample_size": total, "total_revenue": r[4] or 0.0,
                "confidence": _confidence_for_samples(total),
                "cold_start": total < MIN_SAMPLES,
            })
        parsed.sort(key=lambda r: (r["value"], r["total_revenue"]), reverse=True)
        return parsed[:limit]

    def strategies_to_avoid(self, limit: int = 10) -> List[dict]:
        """Q: Which strategies should be avoided? (strategy success_rate asc)."""
        rows = self.reusable_success_strategies()
        return [r for r in rows if r["sample_size"] > 0][-limit:][::-1]

    def category_outcome_summary(self, category: str) -> dict:
        """Summarized knowledge for a category (used by decision layer)."""
        hist = self.get_category_history(category)
        n = hist.get("total", 0) or 0
        net = self._category_net_hourly()
        nh = next((x for x in net if x["category"] == category), None)
        return {
            "category": category,
            "success_rate": hist.get("success_rate", 0.0),
            "sample_size": n,
            "confidence": _confidence_for_samples(n),
            "cold_start": n < MIN_SAMPLES,
            "net_hourly": nh["net_hourly"] if nh else 0.0,
        }

    # ── Prediction Accuracy (v2.0.36d) ──────────────────────────────

    def get_prediction_accuracy(self, dim: str = "global", value: str = "global") -> dict:
        """Aggregate predicted-vs-actual error for a dimension (global/category/platform/task_type).

        Returns MAE/MAE% on effort & revenue, binary success-classification accuracy,
        plus sample_size, confidence, and cold_start. Deterministic; no LLM.
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT effort_err_pct, revenue_err_pct, success_correct "
                "FROM prediction_accuracy WHERE dim=? AND dim_value=?",
                (dim, value),
            ).fetchall()
            conn.close()

        n = len(rows)
        if n == 0:
            return {
                "dim": dim, "value": value,
                "effort_mae_pct": 0.0, "revenue_mae_pct": 0.0,
                "success_accuracy": 0.0,
                "sample_size": 0, "confidence": 0.0, "cold_start": True,
            }
        effort_errs = [r[0] for r in rows]
        revenue_errs = [r[1] for r in rows]
        correct = sum(1 for r in rows if r[2] == 1)
        return {
            "dim": dim, "value": value,
            "effort_mae_pct": sum(effort_errs) / n,
            "revenue_mae_pct": sum(revenue_errs) / n,
            "success_accuracy": correct / n,
            "sample_size": n,
            "confidence": _confidence_for_samples(n),
            "cold_start": n < MIN_SAMPLES,
        }

    # ── Opportunity Learning Metrics (v2.0.36d) ───────────────────
    # The 11 required metrics, computed with recency weighting so old outcomes do not
    # dominate forever (raw history retained for audit). Each carries sample_size +
    # confidence + cold_start.

    _ACCEPTED = ("accepted", "completed", "submitted", "paid")
    _COMPLETED = ("completed", "submitted", "paid")
    _PAID = ("paid",)
    _FAILED = ("failed", "rejected_apply", "rejected_pay", "payment_disputed")
    _CANCELLED = ("abandoned",)

    def compute_opportunity_metrics(self, dim: str = "global", value: str = "global",
                                    now: float = None) -> "LearningMetrics":
        """Compute the 11 required metrics for a dimension (global/category/platform/task_type)."""
        col_map = {"category": "category", "platform": "platform", "task_type": "task_type"}
        if dim in col_map:
            where = f"WHERE {col_map[dim]} = ?"
            params = (value,)
        else:
            where = ""
            params = ()

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                f"SELECT outcome_state, revenue, net_profit, effort_hours, time_spent_hours, "
                f"predicted_revenue, ts FROM outcome_memory_v2 {where}",
                params,
            ).fetchall()
            conn.close()

        n = len(rows)
        if n == 0:
            return LearningMetrics(dim=dim, value=value, sample_size=0,
                                   confidence=0.0, cold_start=True)

        attempts = n
        accepted = completed = paid = failed = cancelled = 0
        w_rev = w_net = w_eff = w_time = 0.0          # recency-weighted sums
        w_pred_rev = 0.0
        for state, rev, net, eff, t, pred_rev, ts in rows:
            w = recency_weight(ts, now)
            rev = rev or 0.0; net = net or 0.0; eff = eff or 0.0; t = t or 0.0
            pred_rev = pred_rev or 0.0
            w_rev += rev * w; w_net += net * w; w_eff += eff * w; w_time += t * w
            w_pred_rev += pred_rev * w
            if state in self._ACCEPTED: accepted += 1
            if state in self._COMPLETED: completed += 1
            if state in self._PAID: paid += 1
            if state in self._FAILED: failed += 1
            if state in self._CANCELLED: cancelled += 1

        # Recency-weighted averages = sum(value*w) / sum(w). Reuse the ts already fetched above.
        sum_w = sum(recency_weight(ts, now) for (_, _, _, _, _, _, ts) in rows) or 1.0

        average_revenue = w_rev / sum_w
        average_net_profit = w_net / sum_w
        average_effort_hours = w_eff / sum_w
        average_hourly_return = (w_net / sum_w) / (w_time / sum_w) if w_time > 0 else 0.0
        expected_vs_actual_return = (w_rev / sum_w) / (w_pred_rev / sum_w) if w_pred_rev > 0 else 0.0

        return LearningMetrics(
            dim=dim, value=value,
            attempt_rate=attempts / attempts,            # each recorded row is one attempt
            acceptance_rate=accepted / attempts,
            completion_rate=completed / attempts,
            payment_rate=paid / attempts,
            failure_rate=failed / attempts,
            cancellation_rate=cancelled / attempts,
            average_revenue=average_revenue,
            average_net_profit=average_net_profit,
            average_effort_hours=average_effort_hours,
            average_hourly_return=average_hourly_return,
            expected_vs_actual_return=expected_vs_actual_return,
            sample_size=n,
            confidence=_confidence_for_samples(n),
            cold_start=n < MIN_SAMPLES,
            recency_weighted=True,
        )

    def compute_all_metrics(self, dim: str = "category") -> List[LearningMetrics]:
        """Compute metrics across all known values of a dimension."""
        col_map = {"category": "category", "platform": "platform", "task_type": "task_type"}
        if dim not in col_map:
            return [self.compute_opportunity_metrics("global", "global")]
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            vals = [r[0] for r in conn.execute(
                f"SELECT DISTINCT {col_map[dim]} FROM outcome_memory_v2 WHERE {col_map[dim]} <> ''"
            ).fetchall()]
            conn.close()
        return [self.compute_opportunity_metrics(dim, v) for v in vals]

    def _category_net_hourly(self) -> List[dict]:
        """Compute net_profit / time_spent_hours aggregated by category from outcome_memory_v2."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT category, "
                "SUM(net_profit) AS net, SUM(time_spent_hours) AS hrs, COUNT(*) AS n "
                "FROM outcome_memory_v2 WHERE category <> '' GROUP BY category"
            ).fetchall()
            conn.close()
        out = []
        for r in rows:
            hrs = r[2] or 0.0
            out.append({
                "category": r[0],
                "net_hourly": (r[1] or 0.0) / hrs if hrs > 0 else 0.0,
                "total": r[3] or 0,
            })
        return out

    def get_task_type_history_all(self) -> List[dict]:
        """All task-type histories (wraps get_task_type_history over distinct keys)."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            keys = [r[0] for r in conn.execute(
                "SELECT DISTINCT pattern_key FROM pattern_memory WHERE pattern_type='tasktype_success'").fetchall()]
            conn.close()
        return [self.get_task_type_history(k) | {"task_type": k} for k in keys]

    def find_similar_opportunities(self, opp: dict, limit: int = 10) -> List[dict]:
        """Find similar opportunities based on learned patterns."""
        results = []
        
        # Search by platform
        platform = opp.get("platform", "")
        if platform:
            patterns = self.get_successful_patterns(f"platform_action", 0.3)
            for p in patterns[:limit]:
                results.append({"pattern": platform, "confidence": p["confidence"]})
        
        # Search by skills in description
        desc = opp.get("description", "").lower()
        skills = ["python", "ai", "data", "code", "write", "review"]
        matching_skills = [s for s in skills if s in desc]
        
        for skill in matching_skills:
            patterns = self.get_successful_patterns("tag_success", 0.3)
            for p in patterns[:limit]:
                results.append({"skill": skill, "confidence": p["confidence"]})
        
        return sorted(results, key=lambda x: x.get("confidence", 0), reverse=True)

    # ── Learning ───────────────────────────────────────────────────

    def store_learning(self, learning_type: str, insight: str, confidence: float = 0.5):
        """Store a learned insight."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO learning_history (learning_type, insight, confidence, created_at) "
                "VALUES (?, ?, ?, ?)",
                (learning_type, insight, confidence, time.time())
            )
            conn.commit()
            conn.close()

    def get_recent_learned(self, learning_type: str = None, limit: int = 10) -> List[dict]:
        """Get recent learned insights."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            if learning_type:
                rows = conn.execute(
                    "SELECT learning_type, insight, confidence, created_at "
                    "FROM learning_history WHERE learning_type=? ORDER BY created_at DESC LIMIT ?",
                    (learning_type, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT learning_type, insight, confidence, created_at "
                    "FROM learning_history ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            conn.close()

        keys = ["type", "insight", "confidence", "ts"]
        return [dict(zip(keys, row)) for row in rows]

    # ── Stats helpers ─────────────────────────────────────────────

    def _update_stats_from_outcome(self, opp_id: str, success: bool, revenue: float, tags):
        """Update in-memory stats from an outcome."""
        tag_list = tags or []
        for tag in tag_list:
            if success:
                self._stats[f"tag_{tag}"]["success"] += 1
                self._stats[f"tag_{tag}"]["total_revenue"] += revenue
            else:
                self._stats[f"tag_{tag}"]["failed"] += 1

    def get_memory_summary(self) -> dict:
        """Get a summary of all memory."""
        self.periodic_decay()  # Apply decay on summary
        
        total_opps = len([k for k in self._cache if k.startswith("opp_")])
        
        return {
            "memory_stats": {
                "cached_opportunities": total_opps,
                "tracked_skills": len([k for k in self._stats if "tag_" not in k]),
            },
            "top_platforms": self.get_all_reputations()[:10],
            "recent_learned": self.get_recent_learned(limit=5),
            "successful_skills": self.get_successful_skills(min_success=1),
            "successful_patterns": {
                "actions": self.get_successful_patterns("action_success"),
                "tags": self.get_successful_patterns("tag_success"),
            }
        }

    def clear_expired(self):
        """Clear expired memory entries."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "DELETE FROM opportunity_memory WHERE updated_at < ?",
                (time.time() - 86400 * 30,)  # 30 days
            )
            conn.commit()
            conn.close()


# Convenience function
def create_memory(db_path: str = None) -> EarningMemory:
    """Factory function to create an EarningMemory instance."""
    return EarningMemory(db_path=db_path)


# Quick test
if __name__ == "__main__":
    import tempfile, os
    
    tmp_db = tempfile.mktemp(suffix=".db")
    mem = EarningMemory(db_path=tmp_db)
    
    # Test opportunity memory
    mem.remember_opportunity("test_123", {"title": "Test Gig", "value": 100}, "gig")
    print(f"Stored opportunity: {mem.get_opportunity_history('test_123')}")
    
    # Test outcome memory
    mem.record_outcome("test_123", "apply", "Applied successfully", 100, 0.5, True, ["clawgig"])
    print("Recorded outcome")
    
    # Test skill memory
    mem.remember_success("python", "ClawGig", 100)
    print(f"Skills: {mem.get_successful_skills()}")
    
    # Test reputation
    mem.update_reputation("ClawGig", True, 100)
    print(f"Reputation: {mem.get_platform_reputation('ClawGig')}")
    
    # Test patterns
    patterns = mem.get_successful_patterns("action_success")
    print(f"Patterns: {len(patterns)} learned")
    
    # Test memory summary
    summary = mem.get_memory_summary()
    print(f"Summary: {summary['memory_stats']}")
    
    os.unlink(tmp_db)
    print("Memory system test: PASSED")