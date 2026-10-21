"""
earning_pipeline.py — Earning pipeline engine for MrBot1000.

Replaces agent-based orchestration with a direct, efficient pipeline:
  1. DISCOVER → Scan for opportunities (gigs, airdrops, DeFi, content)
  2. EVALUATE → Score and rank opportunities using Ollama
  3. FILTER → Apply user preferences and risk limits
  4. EXECUTE → Take safe automated actions
  5. TRACK → Log outcomes and update reputation
"""

import os
import time
import json
import re
import sqlite3
import threading
from typing import Any, List, Dict, Optional, Callable
from dataclasses import dataclass, field

from agents.earning.opportunity_lifecycle import OpportunityLifecycleTracker
from app.earning_memory import EarningMemory
from agents.brains.base_worker import _normalize_keep_alive
from agents.earning.opportunity_models import Opportunity as CanonicalOpportunity
from agents.earning.got import OpportunityGraphPlanner
from agents.earning.opportunity_adapters import (
    canonical_to_legacy,
    legacy_to_canonical,
)
from agents.earning.discovery import EarningDiscoveryService
from agents.earning.evaluation import evaluate_opportunity
from agents.earning.intelligence import evaluate_intelligence
from agents.earning.ranking import rank_opportunities
from agents.earning.portfolio import sync_to_portfolio
from agents.earning.submission import record_ramp_submission
from agents.earning.proposal import submit_gig_proposal as submit_proposal_service
from agents.earning.execution import execute_opportunity
from agents.earning.tasks import (
    execute_airdrop,
    execute_defi,
    execute_microtask,
    execute_simple,
)
from agents.earning.evidence import (
    build_manual_attestation,
    is_affirmative_verification,
)
from agents.earning.payment import (
    record_realized_gas as record_payment_gas,
    total_realized_gas,
)
from agents.earning.accounting import accounting_projection

# Compatibility patch point for legacy callers/tests. The optional adapter is
# resolved lazily by the task adapter when this remains unset.
AirdropClaimer = None

ROOT_FOLDER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_FOLDER, "earning.db")
MEMORY_PATH = os.path.join(ROOT_FOLDER, "earning_memory.db")


def _is_affirmative_verification(state) -> bool:
    """H-3: True iff the lifecycle `state`'s payment evidence is affirmatively
    verified (VERIFIED / PARTIALLY_VERIFIED), so a ramp *win* is only credited on
    real, evidence-backed payment — never on an unverified self-reported 'paid' event.
    """
    return is_affirmative_verification(state)


@dataclass
class Opportunity:
    id: str
    source: str = ""
    type: str = ""
    title: str = ""
    description: str = ""
    platform: str = ""
    payment_type: str = "usd"
    payment_amount: float = 0.0
    payment_currency: str = "USD"
    estimated_usd_value: float = 0.0
    min_amount: float = 1.0  # Minimum expected payout
    time_required_hours: float = 0.0
    risk_level: str = "low"
    skill_match: float = 0.0
    effort_score: float = 0.5
    urgency: float = 0.0
    url: str = ""
    status: str = "new"
    found_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    outcome: str = ""
    history: List[Dict] = field(default_factory=list)
    got_rank: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    success: bool
    opportunity: Optional[Opportunity] = None
    action_taken: str = ""
    message: str = ""
    timestamp: float = field(default_factory=time.time)


class EarningPipeline:
    """Main earning pipeline engine with integrated memory system.

    ARCH-ENG-254 (W-04): six accessors with zero callers --
    `get_opportunity_stats`, `_db_execute`, `load_memory`,
    `build_workflow_plan`, `_legacy_to_canonical` and
    `get_platform_reputations` -- were deleted here. Nothing read them.
    """

    def __init__(self, db_path: str = DB_PATH,
                 memory_path: str = None,
                 log_fn: Callable = None,
                 portfolio: Any = None,
                 run_store: Any = None):
        self.db_path = db_path
        self.memory_path = memory_path or MEMORY_PATH
        self._log = log_fn or print
        self._lock = threading.Lock()
        self._init_db()
        # v2.0.36h: Opportunity Portfolio (optional; back-compat — pipeline works without it)
        self.portfolio = portfolio

        # Initialize memory system
        self.memory = EarningMemory(db_path=self.memory_path)
        self.discovery_service = EarningDiscoveryService(
            memory=self.memory,
            log_fn=self._log,
            legacy_type=Opportunity,
        )
        # v2.0.34aq: EvidenceStore (backed by AgentDB's evidence table, same db_path) so the
        # lifecycle gates transitions on Evidence and records provenance.
        from agents.evidence.evidence_store import EvidenceStore
        from app.database import AgentDB
        self.evidence_store = EvidenceStore(AgentDB(db_path=self.db_path))
        # v2.0.36d: Opportunity Learning Loop — injected into the lifecycle so final outcomes
        # flow back into memory (which evaluate() already consumes via category/task-type/
        # reputation priors). Deterministic; the loop enforces security/governance bounds.
        from app.earning_learning_loop import LearningLoop
        self.learning_loop = LearningLoop(self.memory)
        # v2.0.36g: wire search-strategy outcome recorder (deterministic; extracts
        # strategy:<id> from the opportunity's provenance and updates Search Strategy Memory).
        self.lifecycle = OpportunityLifecycleTracker(
            evidence_store=self.evidence_store, learning_loop=self.learning_loop,
            outcome_callback=self._record_strategy_outcome,
            # v2.0.36k Group 4 (M-1): persist lifecycle state across restarts so a
            # restart does not silently lose the authoritative lifecycle (the
            # persistent portfolio could otherwise still claim PAID).
            state_path=os.path.join(os.path.dirname(os.path.abspath(self.db_path))
                                    if self.db_path else ".", "lifecycle_states.json"))
        # v2.0.36f: Dynamic Discovery Scheduler — self-driving, history-aware opportunity discovery.
        # The scheduler decides which sources/when/how-often/categories to search (exploration/
        # exploitation balanced) and only ever drives VALIDATED provider interfaces. The LLM is
        # never given an external action by the scheduler.
        from agents.discovery.discovery_scheduler import DiscoveryScheduler, SchedulerConfig
        from agents.discovery.discovery_strategies import SearchStrategyGenerator
        self.discovery_scheduler = DiscoveryScheduler(
            memory=self.memory,
            generator=SearchStrategyGenerator(),
            config=SchedulerConfig(),
        )
        # v2.0.36i: Generalized Task Executor (14-step pipeline with validators + human gates)
        # ARCH-ENG-158: the evidence store is wired in because steps 12/14 of that
        # pipeline decide whether an opportunity is PAID. Without it they can only
        # fail closed — which is the correct default, but it would mean the
        # pipeline could never observe a real payout.
        from agents.earning.executor import TaskExecutor
        from agents.earning.validator import CapabilityValidator
        from agents.safety.gates import HumanGateManager
        self.task_executor = TaskExecutor(
            portfolio=self.portfolio,
            capability_validator=CapabilityValidator(),
            human_gate_manager=HumanGateManager(),
            evidence_store=self.evidence_store,
        )
        # v2.0.36j: Unified Economic Accounting Layer
        from agents.earning.economic_accounting import EconomicAccounting
        self.accounting = EconomicAccounting(self.evidence_store)
        # v2.0.36j-T4: Self-Audit Engine
        from agents.services.self_audit import SelfAuditEngine
        self.self_audit = SelfAuditEngine(self.memory, self.evidence_store, self.accounting)
        # v2.0.36k: Unified Autonomous Planning Loop
        from agents.services.autonomous_loop import AutonomousLoop
        # v2.1 Phase 3: inject the durable run store so loop results persist.
        self.run_store = run_store
        self.autonomous_loop = AutonomousLoop(self, run_store=run_store)
        # v2.1.71 Phase C: strategy feedback (lazy) — aggregates recorded
        # autonomous-run outcomes per platform so ranking is informed by what
        # has actually paid. None until first use; safe when run_store/portfolio
        # are absent (feedback is advisory and simply not applied).
        self._strategy_feedback = None
        # v2.1.72 Phase C: SelfImprovementEngine (lazy) — learns platform
        # reliability, tag success rates, and strategy weights from VERIFIED
        # opportunity outcomes (evidence-gated). Fed from the same lifecycle
        # outcome_callback as search-strategy memory. Persisted next to the DB.
        self._self_improvement = None
        # v2.0.34at: Opportunity Intelligence Engine (lazy; created on first use).
        self._intel_engine = None
        self._last_opportunity_graph = None
        self._last_opportunity_graph_ranks = []

    def close(self) -> None:
        """Release SQLite resources held by the pipeline.

        Windows cannot unlink a WAL database while the AgentDB connection remains
        open.  The GUI and short-lived workers both need an explicit lifecycle
        hook instead of relying on interpreter shutdown.
        """
        evidence_store = getattr(self, "evidence_store", None)
        db = getattr(evidence_store, "_db", None)
        close = getattr(db, "close", None)
        if callable(close):
            close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT,
                description TEXT,
                platform TEXT,
                payment_type TEXT DEFAULT 'usd',
                payment_amount REAL DEFAULT 0,
                payment_currency TEXT DEFAULT 'USD',
                estimated_usd_value REAL DEFAULT 0,
                time_required_hours REAL DEFAULT 0,
                risk_level TEXT DEFAULT 'low',
                skill_match REAL DEFAULT 0,
                effort_score REAL DEFAULT 0.5,
                urgency REAL DEFAULT 0,
                url TEXT,
                status TEXT DEFAULT 'new',
                found_at REAL,
                completed_at REAL DEFAULT 0,
                outcome TEXT
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                opportunity_id TEXT,
                action TEXT,
                result TEXT,
                revenue_usd REAL DEFAULT 0,
                revenue_currency TEXT DEFAULT 'USD',
                time_spent_hours REAL DEFAULT 0,
                was_scam BOOLEAN DEFAULT 0
            );
        """)
        conn.commit()
        conn.close()

    # ── Stage 1: DISCOVER ──────────────────────────────────

    def discover(self, sources: List[str] = None,
                 on_found=None, page: int = 1, query: str = None
                  ) -> List[Opportunity]:
        """Run discovery sources and return raw opportunities.

        v2.0.34as: discovery is now driven by the pluggable DiscoveryEngine +
        structured Opportunity model. Each requested source name maps to a
        BaseOpportunitySource (see agents.discovery_sources). The engine handles
        throttling, cross-source dedup, failure isolation, and provenance tagging.
        Results are adapted to the pipeline's working Opportunity model so the rest
        of the pipeline (evaluate/lifecycle) is unchanged.

        *query* (optional) drives the generic web source's real provider search
        so a scan can be targeted instead of only using the fixed seed feeds.
        """
        opportunities = self.discovery_service.discover(
            sources=sources,
            on_found=on_found,
            page=page,
            query=query,
        )
        # ARCH-ENG-224: REPORT WHAT THE SCAN ACTUALLY PRODUCED.
        #
        # The DiscoveryScheduler decides what to search next from per-source
        # reliability, and it is the only reader of that data
        # (`_source_quality`). But nothing on the live path ever told it: the
        # scan stats were discarded inside `EarningDiscoveryService.discover`,
        # and `record_outcome` was only ever called from `run_task`, which lives
        # in `run_discovery_cycle` -- a method with no callers.
        #
        # So the scheduler selected tasks using a reliability table that stayed
        # empty forever, and `strategy_memory` / `search_strategy` /
        # `learning_history` were empty in the live database while discovery ran
        # continuously. Discovery worked; nothing it learned was ever kept.
        #
        # Recording outcomes here closes the loop with real per-source numbers
        # rather than a guess. A source that errored is recorded as an error so
        # its backoff grows; a source that returned results is recorded as a
        # clean run. `success` stays False because finding an opportunity is not
        # the same as earning from it -- that signal arrives later through the
        # opportunity lifecycle, which already writes to memory directly.
        try:
            stats = getattr(self.discovery_service, "last_stats", None)
            if stats is not None:
                by_source = dict(getattr(stats, "by_source", {}) or {})
                for name, count in by_source.items():
                    self.discovery_scheduler.record_outcome(
                        name, f"scan:{name}", success=False, revenue=0.0,
                        error=False)
                for name, _err in (getattr(stats, "errors", {}) or {}).items():
                    self.discovery_scheduler.record_outcome(
                        name, f"scan:{name}", success=False, revenue=0.0,
                        error=True)
                by_category = dict(getattr(stats, "by_category", {}) or {})
                for cat in by_category:
                    self.discovery_scheduler.mark_searched(cat)
        except Exception as exc:      # never fail a scan over telemetry
            self._log(f"[Discover] scheduler feedback skipped: {exc}")
        return opportunities

    def run_discovery_cycle(self, sources: Optional[List[str]] = None,
                             now: Optional[float] = None) -> dict:
        """Self-driving discovery cycle powered by the Dynamic Discovery Scheduler (v2.0.36f).

        The scheduler selects which sources/categories/strategies to search this tick (using
        historical performance + exploration/exploitation balance) and executes ONLY through
        VALIDATED provider interfaces (built-in sources' discover()). The LLM is never given a
        network/external action here. Discovered opportunities are tagged with the strategy that
        produced them (provenance) so the system learns which search strategies pay off.

        Returns the scheduler tick stats dict.
        """
        requested = sources or [
            "social", "upwork", "fiverr", "airdrop",
            "defi", "microtask", "ugig", "moltbook", "web", "dynamic",
        ]
        from agents.discovery.discovery_sources import all_builtin_sources
        from agents.earning.opportunity_models import OpportunityDeduplicator
        by_name = {s.name: s for s in all_builtin_sources()}
        valid = [n for n in requested if n in by_name]

        def discover_fn(source_name: str, strategy):
            """VALIDATED provider interface: run one built-in source's discover().

            v2.0.36p: thread the scheduler's per-task query (and categories) into the
            source so discovery actually varies per tick instead of every source
            re-running its hardcoded default query. Sources that can't scope by query
            simply ignore it.
            """
            src = by_name.get(source_name)
            if src is None or not src.is_enabled():
                return []
            q = getattr(strategy, "query", None) if strategy else None
            cats = getattr(strategy, "categories", None) if strategy else None
            try:
                return list(src.discover(query=q, categories=cats))
            except Exception as e:  # isolate one bad source
                self._log(f"[Scheduler] source {source_name} error: {e}")
                return []

        stats = self.discovery_scheduler.tick(discover_fn, sources=valid, now=now)

        # ARCH-ENG-282 (F-01): TURN THE SCHEDULER'S READ SIDE INTO THE LIVE
        # DISCOVERY STAGE.
        #
        # `tick()` ran the selected tasks and then returned only counts, and
        # `run_discovery_cycle` was the sole caller -- so even its counts went
        # nowhere. The pipeline's live `run_full_cycle` called the separate
        # `discover()` path, and the scheduler could never decide what to
        # search next from results the live cycle actually produced.
        #
        # The scheduler now returns the canonical opportunities it found. They
        # are deduplicated with the same identity contract the DiscoveryEngine
        # uses, persisted through the one `remember_and_adapt` helper (so
        # provenance/history is identical to a manual scan), and returned as
        # the legacy shape the evaluate/filter stages consume.
        canonical_found = stats.get("found") or []
        deduped = OpportunityDeduplicator().filter(list(canonical_found))
        legacy_found = []
        for canonical in deduped:
            try:
                adapted = self.discovery_service.remember_and_adapt(canonical)
            except Exception as exc:  # one malformed record must not abort a cycle
                self._log(f"[Scheduler] adapt skipped: {exc}")
                continue
            legacy_found.append(adapted)
        stats["found"] = legacy_found
        self._log(f"[Scheduler] tick: {stats['tasks']} tasks, "
                  f"{stats['opportunities']} opps "
                  f"(explore {stats['exploration']}/exploit {stats['exploitation']}), "
                  f"{len(legacy_found)} new")
        return stats

    def _record_strategy_outcome(self, opportunity_id: str, outcome_state: str, *,
                                 revenue: float = 0.0, cost: float = 0.0,
                                 effort_hours: float = 0.0) -> None:
        """Feed a finalized opportunity outcome into the learning systems.

        Two sinks, both deterministic (no LLM, no network):
        1. Search Strategy Memory (v2.0.36g) — records the economic outcome
           against the discovery `strategy:<id>` so the scheduler ranks by
           usefulness. Only when a strategy id is present.
        2. SelfImprovementEngine (v2.1.72 Phase C) — learns platform
           reliability, tag success rates, and strategy weights from VERIFIED
           outcomes (it ignores records without evidence_ids, so unverified
           outcomes never distort learning). Runs for every finalized outcome.
        """
        if not opportunity_id:
            return
        hist = self.memory.get_opportunity_history(opportunity_id) or {}

        # ARCH-ENG-243 (BD-01): every finalized outcome is a typed earning
        # event -- the live reporter the Insights panel's outcomes table and
        # event feed read (it consumes `earning` events' details:
        # platform/revenue/status). Effective values arrive from the
        # lifecycle: a payment verified down is recorded with revenue 0, so
        # the panel can never show a win the ledger refused. Guarded:
        # telemetry must never break the learning feed.
        try:
            from agents.core.event_logger import StructuredEventLogger
            _state = (outcome_state or "").lower()
            StructuredEventLogger.instance().earning_event(
                action=f"finalized:{_state}",
                revenue=float(revenue or 0.0), cost=float(cost or 0.0),
                platform=str(hist.get("platform", "") or ""),
                success=_state in ("accepted", "completed", "paid", "submitted"))
        except Exception:
            pass

        # 2) SelfImprovementEngine — verified-outcome learning (Phase C).
        self._feed_self_improvement(opportunity_id, outcome_state, hist,
                                    revenue=revenue, cost=cost,
                                    effort_hours=effort_hours)

        sid = self._strategy_id_from_provenance(hist.get("provenance", ""))
        if not sid:
            return
        os_ = (outcome_state or "").lower()
        accepted = os_ in ("accepted", "completed", "paid", "submitted")
        completed = os_ in ("completed", "paid")
        paid = os_ == "paid"
        useful = 1 if accepted else 0
        self.memory.record_strategy_result(
            sid, result_count=1, useful_result_count=useful,
            accepted=1 if accepted else 0, completed=1 if completed else 0,
            paid=1 if paid else 0, net_revenue=max(0.0, float(revenue) - float(cost)),
            effort_hours=float(effort_hours))

    @staticmethod
    def _strategy_id_from_provenance(provenance: str) -> str:
        """Extract `strategy:<id>` from a provenance string ('' when absent)."""
        for token in str(provenance or "").split("::"):
            if token.startswith("strategy:"):
                return token.split(":", 1)[1].strip()
        return ""

    def _feed_self_improvement(self, opportunity_id: str, outcome_state: str,
                               hist: dict, *, revenue: float, cost: float,
                               effort_hours: float) -> None:
        """Record a finalized outcome into the SelfImprovementEngine (Phase C).

        The engine only learns from VERIFIED outcomes (it requires
        `verified` and non-empty `evidence_ids`), so this passes whatever
        evidence the lifecycle attached; unverified outcomes are ignored by the
        engine, never fabricating a learning signal. Never raises.
        """
        engine = self.self_improvement
        if engine is None:
            return
        try:
            from agents.autonomy.self_improvement import OutcomeRecord, Outcome
            os_ = (outcome_state or "").lower()
            success = os_ in ("completed", "paid")
            # Evidence: the lifecycle links paid/verified evidence ids to the
            # opportunity; only a paid/verified outcome carries them, which is
            # exactly the engine's gate.
            evidence_ids = []
            try:
                evidence_ids = self.memory.get_outcome_evidence(opportunity_id) or []
            except Exception:
                evidence_ids = []
            verified = bool(os_ == "paid" and evidence_ids)
            # ARCH-ENG-280 (A-01): the read side needs keys that actually exist
            # in the discovery history. The scheduler tags provenance with
            # `strategy:<id>` (it never writes a "strategy" key), and discovery
            # records category/task_type rather than a "tags" list -- so the
            # old `hist.get("strategy", "")` and `hist.get("tags", [])` made
            # every learned key empty and the getters always returned defaults.
            strategy = self._strategy_id_from_provenance(hist.get("provenance", ""))
            if not strategy:
                strategy = str(hist.get("task_type", "")
                               or hist.get("category", "") or "")
            tags = list(hist.get("tags", []) or [])
            for key in ("category", "task_type", "platform"):
                value = str(hist.get(key, "") or "").strip()
                if value and value not in tags:
                    tags.append(value)
            record = OutcomeRecord(
                opportunity_id=opportunity_id,
                strategy=strategy,
                platform=str(hist.get("platform", "") or ""),
                outcome=Outcome.SUCCESS.value if success else Outcome.FAILURE.value,
                revenue=float(revenue or 0.0),
                cost=float(cost or 0.0),
                effort_hours=float(effort_hours or 0.0),
                risk_level=str(hist.get("risk_level", "unknown") or "unknown"),
                success_probability=float(hist.get("success_probability", 0.0) or 0.0),
                tags=tags,
                verified=verified,
                evidence_ids=list(evidence_ids),
            )
            engine.record_outcome(record)
        except Exception as exc:
            self._log(f"[SelfImprovement] outcome feed skipped: {exc}")

    @staticmethod
    def _adapt_to_legacy(o) -> "Opportunity":
        """Adapt the canonical structured Opportunity to the pipeline's model.

        Keeps evaluate()/lifecycle/main.py working unchanged while the discovery
        subsystem uses the richer structured representation.
        """
        return canonical_to_legacy(o, Opportunity)

    def _intelligence_for(self, o) -> Optional["EvaluationResult"]:
        """Run the Opportunity Intelligence Engine on a legacy Opportunity.

        The LLM scores (skill_match/effort/risk/scam_prob) are passed as SEMANTIC
        ESTIMATES only; the engine combines them with memory history + policy to
        decide the verdict deterministically. The result is attached to the legacy
        opp as `o.intelligence` (back-compat: legacy fields untouched).
        Returns None if evaluation cannot run.
        """
        return evaluate_intelligence(
            o,
            memory=self.memory,
            engine=self._intel_engine,
            log_fn=self._log,
        )

    # ── Stage 2: EVALUATE ──────────────────────────────────

    def evaluate(self, opportunities: List[Opportunity]
                 ) -> List[Opportunity]:
        """Score opportunities using Ollama or heuristics."""
        evaluated = []

        for opp in opportunities:
            try:
                scored = self._evaluate_opportunity(opp)
                # Attach the structured expected-value intelligence verdict
                # (deterministic; LLM scores feed it as semantic estimates only).
                self._intelligence_for(scored)
                evaluated.append(scored)
                # v2.0.36h: sync to portfolio (EV, confidence, skill_fit, risk, effort from verdict)
                self._sync_to_portfolio(scored)
            except Exception as e:
                self._log(
                    f"[Evaluate] Error evaluating {opp.id}: {e}"
                )
                # M-6 fix: on total evaluation failure, mark the opp as `eval_error`
                # (NOT "evaluated") and DROP it from the executable set. The prior code
                # appended it as "evaluated" so a malformed opp could still flow downstream
                # through filter/execute. Now we skip it: a failed evaluation is not a
                # successful evaluation.
                opp.status = "eval_error"
                continue
            time.sleep(0.5)

        if not evaluated:
            self._last_opportunity_graph = OpportunityGraphPlanner([])
            self._last_opportunity_graph_ranks = []
            return evaluated

        (
            evaluated,
            self._last_opportunity_graph,
            self._last_opportunity_graph_ranks,
        ) = rank_opportunities(
            evaluated,
            evidence_store=self.evidence_store,
            log_fn=self._log,
            strategy_feedback=self.strategy_feedback,
        )
        return evaluated

    @property
    def strategy_feedback(self):
        """Lazy StrategyFeedback: run outcomes -> per-platform stats (Phase C).

        The platform resolver reads the portfolio entry's platform for a run's
        opportunity_id. Returns None when there is no run store or portfolio, so
        ranking simply skips the advisory adjustment.
        """
        if self._strategy_feedback is not None:
            return self._strategy_feedback
        if self.run_store is None or self.portfolio is None:
            return None
        try:
            from agents.earning.strategy_feedback import StrategyFeedback

            def _resolve(opportunity_id: str) -> str:
                try:
                    entry = self.portfolio.get(opportunity_id)
                    return getattr(entry, "platform", "") or ""
                except Exception:
                    return ""

            self._strategy_feedback = StrategyFeedback(
                self.run_store, _resolve)
        except Exception as exc:
            self._log(f"[Feedback] strategy feedback unavailable: {exc}")
            return None
        return self._strategy_feedback

    @property
    def self_improvement(self):
        """Lazy SelfImprovementEngine: learns from VERIFIED outcomes (Phase C).

        Adjusts platform reliability, tag success rates, and strategy weights
        only from outcomes that carry evidence (the engine itself ignores
        unverified records). Persisted to self_improvement_state.json next to
        the DB so learning survives restarts. None if the engine can't load.
        """
        if self._self_improvement is not None:
            return self._self_improvement
        try:
            from agents.autonomy.self_improvement import SelfImprovementEngine
            state_path = os.path.join(
                os.path.dirname(os.path.abspath(self.db_path)),
                "self_improvement_state.json")
            self._self_improvement = SelfImprovementEngine(state_path=state_path)
        except Exception as exc:
            self._log(f"[SelfImprovement] engine unavailable: {exc}")
            return None
        return self._self_improvement

    def _sync_to_portfolio(self, opp: Opportunity) -> None:
        """Create/update a PortfolioEntry from an evaluated opportunity (deterministic)."""
        sync_to_portfolio(
            opp,
            portfolio=self.portfolio,
            log_fn=self._log,
        )

    def _evaluate_opportunity(self, opp: Opportunity) -> Opportunity:
        return evaluate_opportunity(
            opp,
            memory=self.memory,
            log_fn=self._log,
            normalize_keep_alive=_normalize_keep_alive,
        )

    # ── Stage 3: FILTER ────────────────────────────────────

    def filter(self, opportunities: List[Opportunity],
                 max_risk: str = "medium",
                 min_skill_match: float = 0.3,
                 min_usd_value: float = 0.0,
                 payment_types: List[str] = None
                 ) -> List[Opportunity]:
        payment_types = payment_types or [
            "usd", "crypto", "token",
        ]
        risk_order = {"low": 0, "medium": 1, "high": 2}
        max_risk_val = risk_order.get(max_risk, 1)

        # Get platform reputations for intelligent filtering
        platform_reps = {}
        for opp in opportunities:
            rep = self.memory.get_platform_reputation(opp.platform)
            platform_reps[opp.platform] = rep

        filtered = []
        for opp in opportunities:
            if opp.payment_type not in payment_types:
                continue

            risk_level = getattr(opp, "risk_level", "low") or "low"
            if isinstance(risk_level, (list, tuple, set)):
                risk_level = risk_level[0] if risk_level else "low"
            if isinstance(risk_level, str):
                risk_level = risk_level.lower()

            if risk_order.get(risk_level, 2) > max_risk_val:
                continue

            skill_match = getattr(opp, "skill_match", 0.0)
            if skill_match > 0 and skill_match < min_skill_match:
                continue

            estimated_value = getattr(opp, "estimated_usd_value", 0.0)
            if estimated_value < min_usd_value:
                continue

            # A5: win-rate feedback loop (HARD decline). The reputation for this
            # platform was already fetched above (platform_reps). If the proven
            # win-rate is below the configured threshold with enough samples, drop
            # the opportunity so we stop wasting proposals + LLM $ on losers.
            # Cold-start safe (guard only declines with sufficient samples).
            try:
                from agents.earning.win_rate_guard import WinRateGuard
                _wrg = WinRateGuard.from_env()
                _rep = platform_reps.get(opp.platform, {})
                if _wrg.should_decline(_rep):
                    self._log(
                        f"[WinRate] auto-declined {opp.platform} opp "
                        f"(win-rate {_rep.get('success_rate', 0.0):.0%} < "
                        f"{_wrg.decline_below:.0%}); filtered out")
                    continue
            except Exception:
                pass

            # Apply memory-based boosts and penalties
            self._apply_memory_boost(opp, platform_reps)
            # ARCH-ENG-280 (A-01): verified-outcome learning now reaches the
            # live ranking decision. This is a bounded nudge, not a replacement
            # for the deterministic risk/value gates above.
            self._apply_self_improvement(opp)

            filtered.append(opp)

        # Sort by value * skill_match / effort.
        #
        # ARCH-ENG-124: the divisor was `effort_score + 0.1`. `effort_score` is a
        # 0..1 SCORE (lower = easier), so +0.1 made the easiest opportunity rank
        # 10x higher than the hardest purely from the floor: measured with
        # net=$2,500 and skill_match=0.7, effort 0.1 -> 8,750.0 while 0.5 ->
        # 2,916.7, a 3x swing with no change in value or skill. `_apply_memory_boost`
        # compounds it (`max(0.1, score*0.7)` -> 0.035+0.1 floor). `+1.0` bounds
        # the whole 0..1 range to a 2x spread, which is what a difficulty
        # *modifier* should do; the ordering (easier ranks higher) is unchanged.
        filtered.sort(
            key=lambda o: (
                o.estimated_usd_value * o.skill_match
            ) / (o.effort_score + 1.0),
            reverse=True,
        )

        return filtered


    def _apply_memory_boost(self, opp, 
                            platform_reps):
        """Apply memory-based boosts and penalties to opportunity scoring."""
        # Platform reputation boost
        rep = platform_reps.get(opp.platform, {})
        success_rate = rep.get('success_rate', 0)
        if success_rate > 0.8:
            # Boost skill match for trusted platforms
            opp.skill_match = min(1.0, opp.skill_match + 0.15)
            # Reduce effort score
            opp.effort_score = max(0.1, opp.effort_score * 0.7)
        elif success_rate < 0.3 and success_rate > 0:
            # Penalize untrustworthy platforms
            opp.skill_match = max(0.0, opp.skill_match - 0.2)
            opp.risk_level = 'high'

        # Pattern-based boost for known good actions
        pattern_conf = self.memory.get_pattern_confidence(
            f'platform_action', f'{opp.platform}_execute'
        )
        if pattern_conf > 0.7:
            opp.skill_match = min(1.0, opp.skill_match + 0.1)

    def _apply_self_improvement(self, opp) -> None:
        """ARCH-ENG-280 (A-01): let verified-outcome learning adjust ranking.

        `SelfImprovementEngine` had three read methods (`get_strategy_weights`,
        `get_platform_reliability`, `get_tag_success_rate`) with ZERO callers.
        It learned into a file and nothing in a live decision ever read the
        result. This is the read side: platform reliability, tag success, and
        the learned strategy weight are blended into one bounded signal that
        nudges `skill_match`/`effort_score` before the sort.

        Cold start is neutral: below `MIN_OUTCOMES` the engine's own guidance
        says not to adjust, so the opportunity is returned untouched. Any
        failure is logged and the deterministic ranking is used unchanged.
        """
        engine = self.self_improvement
        if engine is None:
            return
        try:
            if engine.state.total_outcomes < engine.MIN_OUTCOMES:
                return
            hist = self.memory.get_opportunity_history(opp.id) or {}
            strategy = self._strategy_id_from_provenance(
                hist.get("provenance", ""))
            if not strategy:
                strategy = str(hist.get("task_type", "")
                               or hist.get("category", "")
                               or getattr(opp, "type", "") or "")
            tags = list(hist.get("tags", []) or [])
            for key in ("category", "task_type", "platform"):
                value = str(hist.get(key, "") or "").strip()
                if value and value not in tags:
                    tags.append(value)

            platform = str(hist.get("platform", "")
                           or getattr(opp, "platform", "") or "")
            platform_rel = float(engine.get_platform_reliability(platform))
            rates = [float(engine.get_tag_success_rate(t)) for t in tags]
            tag_rate = sum(rates) / len(rates) if rates else 0.5
            strategy_score = float(engine.score_strategy(strategy))

            # All three reads are centred on their neutral 0.5 so an engine at
            # rest produces exactly zero adjustment.
            signal = (0.5 * (platform_rel - 0.5)
                      + 0.3 * (tag_rate - 0.5)
                      + 0.2 * (strategy_score - 0.5))
            signal = max(-0.5, min(0.5, signal))

            skill = float(getattr(opp, "skill_match", 0.0) or 0.0)
            effort = float(getattr(opp, "effort_score", 0.5) or 0.5)
            if signal > 0:
                opp.skill_match = min(1.0, skill + min(0.15, signal * 0.3))
                opp.effort_score = max(
                    0.1, effort * (1.0 - min(0.20, signal * 0.4)))
            elif signal < 0:
                opp.skill_match = max(0.0, skill + max(-0.20, signal * 0.4))
                opp.effort_score = min(
                    1.0, effort * (1.0 + min(0.30, -signal * 0.6)))

            # Audit surface: the GUI/report can show WHY ranking moved.
            opp.learning_signal = {
                "outcomes": int(engine.state.total_outcomes),
                "platform": platform,
                "platform_reliability": round(platform_rel, 4),
                "tags": tags,
                "tag_success_rate": round(tag_rate, 4),
                "strategy": strategy,
                "strategy_score": round(strategy_score, 4),
                "signal": round(signal, 4),
            }
        except Exception as exc:
            self._log(f"[SelfImprovement] read-side adjustment skipped: {exc}")

    # ── Stage 4: EXECUTE ───────────────────────────────────

    def execute(self, opportunity: Opportunity
                ) -> PipelineResult:
        """Execute an opportunity action."""
        return execute_opportunity(
            opportunity,
            result_type=PipelineResult,
            airdrop_fn=self._execute_airdrop,
            defi_fn=self._execute_defi,
            microtask_fn=self._execute_microtask,
            simple_fn=self._execute_simple,
        )

    def _execute_airdrop(self, opp: Opportunity) -> PipelineResult:
        return execute_airdrop(
            opp,
            result_type=PipelineResult,
            evidence_store=getattr(self, "evidence_store", None),
            claimer_factory=AirdropClaimer,
        )

    def _execute_defi(self, opp: Opportunity) -> PipelineResult:
        return execute_defi(
            opp,
            result_type=PipelineResult,
        )

    def _execute_microtask(self, opp: Opportunity) -> PipelineResult:
        return execute_microtask(
            opp,
            result_type=PipelineResult,
        )

    def _execute_simple(self, opp: Opportunity) -> PipelineResult:
        """Execute simple opportunities like referrals and faucets.

        H-5 fix: discovering an "Action available" URL is NOT a paid/revenue
        outcome. Previously this called `self.memory.record_outcome(...,
        opp.min_amount * 0.5, 0.1, True, [opp.source])` — recording a *successful*
        outcome WITH revenue (min_amount*0.5) for a mere discoverable link. That
        fabricated success + revenue, polluting reputation, success_memory, category
        priors and accounting-adjacent metrics. Now we only record a neutral
        "available" event (no success flag, no revenue) and never update reputation
        as a win. A real verified payout must come through the evidence-gated paid
        path (mark_paid_verified), not from finding a link.
        """
        return execute_simple(
            opp,
            result_type=PipelineResult,
            memory=self.memory,
        )

    # ── C2: submission ramp outcome recorder ─────────────────────────────────
    def _record_ramp_submission(self, opp) -> None:
        """C2 (H39 fix): record that a proposal was *submitted* on opp.platform.

        This bumps the attempt count (so the cold-start gate can progress) but
        does NOT credit a win — a submission is not an acceptance. The real
        accept/reject is recorded later in `track_opportunity` when the outcome
        (paid / rejected / failed) is actually known.
        """
        record_ramp_submission(
            opp,
            memory=getattr(self, "memory", None),
        )

    # ── A1: Gig proposal submission (review → confirm → submit) ──────────────
    def submit_gig_proposal(self, opp: Opportunity, draft: str,
                            reviewer=None, confirm_cb=None,
                            client=None) -> PipelineResult:
        """Submit a gig proposal through the review + human-confirm gate.

        Flow:
          1. ProposalReviewer checks the draft meets the job's requirements and
             is finished (no errors / missing sections). If it fails, the
             proposal is BLOCKED — never submitted.
          2. If the review passes and a `confirm_cb` is supplied, it is called
             with a human-readable summary; submission only proceeds if the
             callback returns truthy (human confirmed). No callback => blocked
             (fail-safe: never auto-submit).
          3. On confirm, the injected `client` (UpworkClient or test mock)
             submits; success/failure is recorded in the lifecycle.

        Returns PipelineResult. Never raises; failures are normal outcomes.
        """
        return submit_proposal_service(
            opp,
            draft,
            result_type=PipelineResult,
            reviewer=reviewer,
            confirm_cb=confirm_cb,
            client=client,
            default_client=getattr(self, "_upwork_client", None),
            memory=getattr(self, "memory", None),
            trust_boundary=getattr(self, "trust_boundary", None),
            track_fn=self.track_opportunity,
            record_submission_fn=self._record_ramp_submission,
            lifecycle=getattr(self, "lifecycle", None),
            # ARCH-ENG-249 (AF-01): the `proposals` table had a writer
            # (`add_proposal`) and a dedup guard (`proposal_exists`) with ZERO
            # callers anywhere in the tree, while DB Stats displayed
            # `count_proposals()` live -- a KPI that was structurally always
            # zero. Persist the submitted proposal here, once per
            # title+platform, at the point the submission actually succeeded.
            persist_proposal_fn=self._persist_submitted_proposal,
        )

    def _persist_submitted_proposal(self, opp: Opportunity, draft: str) -> None:
        """Record a SUBMITTED proposal in the proposals table (ARCH-ENG-249).

        AF-01's dedup guard existed for exactly this: the job queue can
        re-discover the same gig, and the original save path "blindly inserted
        a new row each time". `proposal_exists` is now the guard it was
        written to be, so a re-discovered gig cannot add a second row.

        Never raises: a persistence failure must not turn a proposal that the
        platform accepted into a reported submission failure. The submission
        itself is already recorded by the lifecycle/ramp path.
        """
        title = (getattr(opp, "title", "") or "").strip()
        platform = (getattr(opp, "platform", "") or "").strip()
        if not title and not platform:
            return
        try:
            # Local import, like the file's other AgentDB uses: app.database
            # imports this module's types, so a module-level import would
            # cycle. (A swallowed NameError here is exactly how the first
            # version of this method wrote nothing.)
            from app.database import AgentDB
            db = AgentDB(db_path=self.db_path)
            try:
                if db.proposal_exists(title, platform or None):
                    return
                db.add_proposal(
                    gig_title=title,
                    platform=platform,
                    budget_usd=float(
                        getattr(opp, "payment_amount", 0.0) or 0.0),
                    draft=draft or "",
                    status="submitted",
                )
            finally:
                db.close()
        except Exception:
            pass

    # ── Stage 5: TRACK ─────────────────────────────────────

    def record_realized_gas(self, chain: str, usd: float, note: str = "") -> None:
        """B4: record realized on-chain gas cost into the wallet gas ledger.

        The net-profit report (Stage 5) reads this total so chain fees are subtracted
        from verified revenue. Never raises.
        """
        record_payment_gas(
            db_path=self.db_path,
            chain=chain,
            usd=usd,
            note=note,
        )

    def get_revenue_report(self, days: int = 30) -> dict:
        since = time.time() - (days * 86400)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                "SELECT SUM(revenue_usd), COUNT(*), "
                "SUM(time_spent_hours) FROM outcomes WHERE ts > ?",
                (since,),
            )
            row = cursor.fetchone()
            conn.close()

        report = {
            "total_revenue_usd": row[0] or 0.0,
            "total_outcomes": row[1] or 0,
            "total_time_hours": row[2] or 0.0,
            "avg_revenue_per_outcome": (
                row[0] / row[1] if row[1] and row[0] else 0.0
            ),
            "period_days": days,
        }
        # A2: honest, verified revenue (cross-checked against payment evidence).
        try:
            report.update(
                accounting_projection(
                    portfolio=self.portfolio,
                    accounting=self.accounting,
                    lifecycle=self.lifecycle,
                )
            )
        except Exception:
            report["verified_revenue_usd"] = 0.0
            report["unverified_payouts_count"] = 0
            report["unverified_payout_ids"] = []

        # A3: net-profit = verified revenue − LLM cost − gas.
        _adb = None
        try:
            from app.database import AgentDB
            _adb = AgentDB(db_path=self.db_path)
            llm_cost = _adb.get_llm_cost_usd(days)
        except Exception:
            llm_cost = 0.0
        finally:
            if _adb is not None:
                _adb.close()
        # Gas capture: B4 — realized chain gas from the wallet gas ledger (was 0.0 stub).
        gas_est = total_realized_gas(db_path=self.db_path)
        verified = report.get("verified_revenue_usd", 0.0)
        net = round(verified - llm_cost - gas_est, 2)
        roi = 0.0
        # ROI vs cost: if there is any cost, net/cost*100; otherwise 100% (pure margin
        # on local/free) capped to avoid divide-by-zero. If net negative, ROI negative.
        if llm_cost > 0:
            roi = round(net / llm_cost * 100.0, 1)
        elif verified > 0:
            roi = 100.0
        try:
            cost_by_model = _adb.get_llm_cost_breakdown(days)
        except Exception:
            cost_by_model = []
        report["llm_cost_usd_est"] = llm_cost
        report["estimated_gas_usd"] = gas_est
        report["net_profit_usd"] = net
        report["roi_pct"] = roi
        report["cost_by_model"] = cost_by_model
        return report

    def get_memory_summary(self) -> dict:
        """Get memory system summary for dashboard."""
        return self.memory.get_memory_summary()

    def get_platform_reputation(self, platform: str) -> dict:
        """Get reputation for a specific platform."""
        return self.memory.get_platform_reputation(platform)

    def get_successful_skills(self, min_success: int = 1) -> List[dict]:
        """Get skills that have been successful."""
        return self.memory.get_successful_skills(min_success=min_success)

    # ── Full cycle ───────────────────────────────────────────

    def run_full_cycle(self, sources: List[str] = None,
                       max_risk: str = "medium") -> PipelineResult:
        """Run complete discovery → evaluate → filter → execute cycle (legacy 4-stage).

        For the full 24-stage unified loop, use `run_autonomous_loop()`.
        """
        self._log("Starting full earning cycle...")

        # 1. Discover (ARCH-ENG-282 / F-01: scheduler-driven; the scheduler's
        # selected tasks and their discovered opportunities are this stage's
        # input, not a parallel dead path).
        cycle = self.run_discovery_cycle(sources=sources)
        opps = list(cycle.get("found") or [])
        if not cycle.get("tasks"):
            # Operator-triggered run outside every source's cooldown / working
            # window: keep the explicit scan available rather than returning an
            # empty cycle the operator cannot explain.
            self._log("[Scheduler] no source due; running an explicit scan")
            opps = self.discover(sources=sources)
        self._log(f"Discovered {len(opps)} opportunities")

        # 2. Evaluate
        evaluated = self.evaluate(opps)
        self._log(f"Evaluated {len(evaluated)} opportunities")

        # 3. Filter
        filtered = self.filter(evaluated, max_risk=max_risk)
        self._log(f"Filtered to {len(filtered)} opportunities")

        # 4. Execute (only safe actions)
        results = []
        executable_sources = {"airdrop", "referral", "faucet"}
        for opp in filtered:
            if opp.source in executable_sources:
                result = self.execute(opp)
                results.append(result)
                self._log(f"Executed {opp.source}: {result.message}")

        total_revenue = sum(r.opportunity.min_amount
                           for r in results if r.success)

        # ARCH-ENG-236 (AJ-01): the self-audit engine was constructed here but
        # run_audit() had no production caller anywhere (11r self-audit depth
        # pass). It runs once per full cycle and publishes its HONEST
        # conclusion: with the ARCH-ENG-158 outcome tables empty by design,
        # the resting state is "insufficient data" -- never a clean bill of
        # health -- and only real findings or genuinely complete data claim
        # anything more.
        self.run_self_audit()

        return PipelineResult(
            success=len(results) > 0,
            message=f"Cycle complete: {len(results)}/{len(filtered)} succeeded",
        )

    def run_self_audit(self):
        """Run the self-audit engine once and log its honest conclusion.

        ARCH-ENG-236 (AJ-01/AJ-02): this is the missing last hop between the
        constructed engine and the live cycle. The report's ``conclusion()``
        distinguishes "no problems found" (every audit saw a data basis and
        none errored) from "insufficient data" (audits whose tables are
        empty -- the designed ARCH-ENG-158 resting state). Audit errors are
        reported as errors, not silence.

        Returns the AuditReport for programmatic callers (tests, future
        surfaces); the log line is the primary production output.
        """
        try:
            report = self.self_audit.run_audit()
        except Exception as exc:  # the audit itself must never break the cycle
            self._log(f"[SelfAudit] engine error: {exc}")
            return None
        self._log(f"[SelfAudit] {report.conclusion()}")
        return report

    def run_autonomous_loop(self, sources: List[str] = None,
                            max_risk: str = "medium",
                            max_opportunities: int = 10) -> dict:
        """Run the unified 24-stage autonomous planning loop.

        DISCOVER → DEDUPLICATE → CLASSIFY → EVALUATE → CHECK MEMORY → CHECK REPUTATION
        → CHECK SKILL FIT → CHECK ECONOMICS → CHECK RISK → PRIORITIZE → PLAN
        → REQUEST APPROVAL IF REQUIRED → EXECUTE → VALIDATE → SUBMIT → WAIT
        → VERIFY → ACCOUNT → LEARN → RE-RANK FUTURE OPPORTUNITIES
        """
        self._log("Starting unified autonomous loop...")

        # 1. Discover (same scheduler-driven stage as run_full_cycle).
        cycle = self.run_discovery_cycle(sources=sources)
        opps = list(cycle.get("found") or [])
        if not cycle.get("tasks"):
            self._log("[Scheduler] no source due; running an explicit scan")
            opps = self.discover(sources=sources)
        self._log(f"Discovered {len(opps)} opportunities")

        # 2. Evaluate
        evaluated = self.evaluate(opps)
        self._log(f"Evaluated {len(evaluated)} opportunities")

        # 3. Filter
        filtered = self.filter(evaluated, max_risk=max_risk)
        self._log(f"Filtered to {len(filtered)} opportunities")

        # 4. Run the autonomous loop on each opportunity
        results = []
        for opp in filtered[:max_opportunities]:
            try:
                result = self.autonomous_loop.run(opp)
                results.append(result)
                self._log(f"Loop {opp.id}: {result.decision} ({result.decision_reason})")
            except Exception as e:
                self._log(f"Loop error for {opp.id}: {e}")

        proceeded = sum(1 for r in results if r.decision == "proceed")
        rejected = sum(1 for r in results if r.decision == "reject")
        awaiting = sum(1 for r in results if r.decision == "await_approval")

        return {
            "success": True,
            "message": f"Autonomous loop complete: {proceeded} proceeded, {rejected} rejected, {awaiting} awaiting approval",
            "results": [r.to_dict() for r in results],
            "total_discovered": len(opps),
            "total_evaluated": len(evaluated),
            "total_filtered": len(filtered),
            "total_processed": len(results),
        }

    # ── Memory Query API ────────────────────────────────────────

    def get_opportunities_by_type(self, opp_type: str, limit: int = 50) -> List[dict]:
        """Get all opportunities of a specific type."""
        return self.memory.get_opportunities_by_type(opp_type, limit)

    def get_recent_outcomes(self, limit: int = 20) -> List[dict]:
        """Get most recent outcomes."""
        return self.memory.get_recent_outcomes(limit)

    def track_opportunity(self, opportunity: Opportunity, stage: str, note: str = "", amount: float = 0.0):
        """Update an opportunity's lifecycle state."""
        try:
            from agents.brains.shared_context import get_shared_context
        except Exception:
            get_shared_context = None

        state = self.lifecycle.start(opportunity)
        if stage == "researched":
            state = self.lifecycle.mark_researched(opportunity.id, note)
        elif stage == "applied":
            state = self.lifecycle.mark_applied(opportunity.id, note)
        elif stage == "in_progress":
            state = self.lifecycle.mark_in_progress(opportunity.id, note)
        elif stage == "submitted":
            state = self.lifecycle.mark_submitted(opportunity.id, note)
        elif stage == "paid":
            # M-4 fix: an operator-attested reference (a free-text txn id / note) is NOT
            # independent verification. The legacy dict path treated `verified: True` as a
            # paid event (manual_reference -> manual_attestation @ L1_SELF_REPORTED, but
            # status=VERIFIED), which flipped the lifecycle to "paid" and credited revenue
            # with no independent check -- contradicting `evidence_policy.reconcile` (which
            # refuses manual attestation). Now a manual reference is recorded as a PENDING
            # manual attestation (UNVERIFIED, L1): it shows up in `unverified_payouts()` and
            # must be reconciled independently before it can count as revenue. It must NEVER
            # auto-flip the lifecycle to "paid" or credit a ramp win.
            # The lifecycle transition + ramp accounting is performed further below (after the
            # shared-context sync) so the verified-paid decision drives the ramp win-rate.
            evidence = build_manual_attestation(note, amount)
            state = self.lifecycle.mark_paid_verified(
                opportunity.id, amount=amount, evidence=evidence)
        elif stage == "failed":
            state = self.lifecycle.mark_failed(opportunity.id, note)

        # P3 (comms redesign): publish a structured OPPORTUNITY_UPDATE on the
        # EventBus instead of writing a JSON-file SharedContext mirror. The bus
        # is the single source of truth for cross-model state notifications;
        # the authoritative lifecycle/evidence stores are never touched here.
        # Legacy SharedContext JSON is retained as a read-only fallback in
        # chat_router (so older Chat context still works) but is no longer written.
        try:
            from agents.core.comms import EventBus, Message, MessageType
            bus = EventBus.instance()
            bus.publish(Message(
                MessageType.OPPORTUNITY_UPDATE,
                source="earning_pipeline",
                destination="any",
                payload={
                    "opportunity_id": opportunity.id,
                    "current_stage": getattr(state, "current_stage", ""),
                    "status": getattr(state, "status", ""),
                    "last_amount": getattr(state, "last_amount", 0.0),
                    "note": note or "",
                },
            ))
        except Exception:
            pass

        # Keep best-effort backwards-compat SharedContext write ONLY if callers
        # still rely on the file (deprecated; scheduled for removal).
        if get_shared_context is not None:
            try:
                get_shared_context().update_opportunity_lifecycle(
                    opportunity.id,
                    current_stage=state.current_stage,
                    status=state.status,
                    last_amount=state.last_amount,
                    note=note,
                )
            except Exception:
                pass

        # C2 (H39 fix): record the REAL proposal outcome for the submission ramp,
        # so win-rate reflects acceptances, not mere submissions.
        #   paid            -> accept (win)
        #   rejected/failed -> reject (loss)
        #   other stages    -> no reputation change (already counted at submit)
        if stage == "paid":
            # A2/H-3: only credit a ramp *accept* (win) when the payment is actually
            # verified, i.e. the lifecycle flipped to paid with affirmative verification.
            # An unverified "paid" call (advertised-amount self-report, no evidence) must
            # NOT inflate the win-rate that gates future auto-submission.
            state = self.lifecycle.mark_paid_verified(
                opportunity.id, amount=amount, evidence=evidence)
            verified_paid = (getattr(state, "status", "") == "paid"
                             and _is_affirmative_verification(state))
            self._record_ramp_real_outcome(
                opportunity, accepted=verified_paid, verified=verified_paid,
                verified_amount=state.last_amount if verified_paid else 0.0)
        elif stage in ("rejected", "failed"):
            self._record_ramp_real_outcome(opportunity, accepted=False)

        return state

    def _record_ramp_real_outcome(self, opportunity, *, accepted: bool,
                                 verified: bool = False, verified_amount: float = 0.0) -> None:
        """Record a *real* accept/reject into the submission ramp reputation,
        and (D2) credit the proposal intro A/B variant that was used.

        H-3 fix: a `paid` win is only credited to the ramp (record_accept) when
        `verified` is True — i.e. backed by an L3+ payment evidence. Unverified
        self-reported "paid" calls are recorded as a *reject-equivalent* (no win)
        so the cold-start gate is trained on real outcomes, not phantom wins.
        """
        try:
            from agents.earning.submission_ramp import get_ramp
            ramp = get_ramp(getattr(self, "memory", None))
            platform = getattr(opportunity, "platform", "unknown")
            if accepted and verified:
                ramp.record_accept(platform, revenue=float(verified_amount or 0.0))
            else:
                # Either a genuine loss (rejected/failed) or an unverified "paid"
                # self-report — do NOT credit a win. Record a reject so the ramp
                # win-rate stays honest (a non-payment is at best a non-win).
                ramp.record_reject(platform)
            # D2: feed the proposal-intro A/B outcome (best-effort; variant may
            # be absent if the opp wasn't drafted through the proposal helper).
            variant = getattr(opportunity, "proposal_variant", None)
            if variant:
                from agents.knowledge.proposal_templates import record_win, record_loss
                mem = getattr(self, "memory", None)
                if accepted and verified:
                    record_win(platform, variant, memory=mem)
                else:
                    record_loss(platform, variant, memory=mem)
        except Exception:
            pass  # never break the lifecycle path over bookkeeping

    def get_recent_learned(self, learning_type: str = None, limit: int = 10) -> List[dict]:
        """Get recent learned insights."""
        return self.memory.get_recent_learned(learning_type, limit)

