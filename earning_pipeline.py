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

from agents.social_earning_platform import SocialEarningPlatform, SocialOpportunity
from agents.document_scanner import DocumentScanner, QualityController
from agents.airdrop_scanner import AirdropScanner, AirdropOpportunity
from agents.airdrop_claimer import AirdropClaimer
from agents.defi_scanner import DeFiScanner
from agents.microtask_client import MicrotaskClient, MicrotaskGig
from agents.fiverr_client import FiverrClient, FiverrGig
from agents.earning_discoverer import EarningDiscoverer, EarningOpportunity
from agents.opportunity_lifecycle import OpportunityLifecycleTracker
from earning_memory import EarningMemory
from agents.base_worker import _normalize_keep_alive
from agents.opportunity_models import Opportunity as CanonicalOpportunity
from agents.opportunity_intelligence import (
    OpportunityIntelligenceEngine, SemanticEstimate, EvaluationConfig, EvaluationResult,
)

ROOT_FOLDER = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT_FOLDER, "earning.db")
MEMORY_PATH = os.path.join(ROOT_FOLDER, "earning_memory.db")


def _is_affirmative_verification(state) -> bool:
    """H-3: True iff the lifecycle `state`'s payment evidence is affirmatively
    verified (VERIFIED / PARTIALLY_VERIFIED), so a ramp *win* is only credited on
    real, evidence-backed payment — never on an unverified self-reported 'paid' event.
    """
    if state is None:
        return False
    v = getattr(state, "verification", None)
    if not v:
        return False
    status = v.get("status") if isinstance(v, dict) else getattr(v, "status", None)
    if status is None:
        return False
    try:
        s = str(status).upper()
        return s in ("VERIFIED", "PARTIALLY_VERIFIED")
    except Exception:
        return False


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


@dataclass
class PipelineResult:
    success: bool
    opportunity: Optional[Opportunity] = None
    action_taken: str = ""
    message: str = ""
    timestamp: float = field(default_factory=time.time)


class EarningPipeline:
    """Main earning pipeline engine with integrated memory system."""

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
        # v2.0.34aq: EvidenceStore (backed by AgentDB's evidence table, same db_path) so the
        # lifecycle gates transitions on Evidence and records provenance.
        from agents.evidence_store import EvidenceStore
        from database import AgentDB
        self.evidence_store = EvidenceStore(AgentDB(db_path=self.db_path))
        # v2.0.36d: Opportunity Learning Loop — injected into the lifecycle so final outcomes
        # flow back into memory (which evaluate() already consumes via category/task-type/
        # reputation priors). Deterministic; the loop enforces security/governance bounds.
        from earning_learning_loop import LearningLoop
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
        from agents.discovery_scheduler import DiscoveryScheduler, SchedulerConfig
        from agents.discovery_strategies import SearchStrategyGenerator
        self.discovery_scheduler = DiscoveryScheduler(
            memory=self.memory,
            generator=SearchStrategyGenerator(),
            config=SchedulerConfig(),
        )
        # v2.0.36i: Generalized Task Executor (14-step pipeline with validators + human gates)
        from agents.task_executor import TaskExecutor
        from agents.task_validator import CapabilityValidator
        from agents.human_gates import HumanGateManager
        self.task_executor = TaskExecutor(
            portfolio=self.portfolio,
            capability_validator=CapabilityValidator(self.memory),
            human_gate_manager=HumanGateManager(),
        )
        # v2.0.36j: Unified Economic Accounting Layer
        from agents.economic_accounting import EconomicAccounting
        self.accounting = EconomicAccounting(self.evidence_store)
        # v2.0.36j-T4: Self-Audit Engine
        from agents.self_audit import SelfAuditEngine
        self.self_audit = SelfAuditEngine(self.memory, self.evidence_store, self.accounting)
        # v2.0.36k: Unified Autonomous Planning Loop
        from agents.autonomous_loop import AutonomousLoop
        # v2.1 Phase 3: inject the durable run store so loop results persist.
        self.autonomous_loop = AutonomousLoop(self, run_store=run_store)
        # v2.0.34at: Opportunity Intelligence Engine (lazy; created on first use).
        self._intel_engine = None

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

    def _db_execute(self, sql, params=(), commit=False):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(sql, params)
            if commit:
                conn.commit()
            conn.close()
            return cursor

    # ── Stage 1: DISCOVER ──────────────────────────────────

    def discover(self, sources: List[str] = None,
                 on_found=None
                  ) -> List[Opportunity]:
        """Run discovery sources and return raw opportunities.

        v2.0.34as: discovery is now driven by the pluggable DiscoveryEngine +
        structured Opportunity model. Each requested source name maps to a
        BaseOpportunitySource (see agents.discovery_sources). The engine handles
        throttling, cross-source dedup, failure isolation, and provenance tagging.
        Results are adapted to the pipeline's working Opportunity model so the rest
        of the pipeline (evaluate/lifecycle) is unchanged.
        """
        requested = sources or [
            "social", "upwork", "fiverr", "airdrop",
            "defi", "microtask", "ugig", "web", "content", "dynamic",
        ]
        valid_sources = {
            "social", "upwork", "fiverr", "airdrop",
            "defi", "microtask", "ugig", "web", "content", "dynamic",
        }

        from agents.discovery_sources import all_builtin_sources
        from agents.discovery_engine import DiscoveryEngine

        # Map requested names -> source instances (skip unknown/invalid).
        by_name = {s.name: s for s in all_builtin_sources()}
        engine_sources = [by_name[n] for n in requested if n in by_name]
        skipped = [n for n in requested if n not in valid_sources]
        for n in skipped:
            self._log(f"[Discover] Invalid source '{n}' blocked")

        engine = DiscoveryEngine(engine_sources, throttle=False)
        found, errors, stats = engine.discover_all()
        for name, err in errors.items():
            self._log(f"[Discover] Error from {name}: {err}")

        all_opps = []
        for o in found:
            # Persist provenance + taxonomy so the external origin stays identifiable.
            self.memory.remember_opportunity(o.opportunity_id, {
                "title": o.title,
                "description": o.description,
                "platform": o.platform,
                "type": o.category,
                "source": o.source,
                "category": o.category,
                "subcategory": o.subcategory,
                "task_type": o.task_type,
                "payment_type": o.payment_type,
                "currency": o.currency,
                "advertised_amount": o.advertised_amount,
                "min_amount": o.advertised_amount,
                "provenance": o.provenance,
            }, o.category)
            adapted = self._adapt_to_legacy(o)
            all_opps.append(adapted)
            if on_found is not None:
                on_found(adapted)
            self._log(f"[Discover] Found {o.title!r} ({o.category}) from {o.source}")
            time.sleep(0.2)

        return all_opps

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
            "defi", "microtask", "ugig", "web", "content", "dynamic",
        ]
        from agents.discovery_sources import all_builtin_sources
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
        self._log(f"[Scheduler] tick: {stats['tasks']} tasks, "
                  f"{stats['opportunities']} opps "
                  f"(explore {stats['exploration']}/exploit {stats['exploitation']})")
        return stats

    def _record_strategy_outcome(self, opportunity_id: str, outcome_state: str, *,
                                 revenue: float = 0.0, cost: float = 0.0,
                                 effort_hours: float = 0.0) -> None:
        """v2.0.36g: feed a finalized opportunity outcome into Search Strategy Memory.

        Deterministic: reads the opportunity's stored provenance (set at discovery time as
        `strategy:<id>`), extracts the search-strategy id, and records the ECONOMIC outcome
        (useful/accepted/completed/paid + net revenue - effort). The discovery scheduler then
        ranks exploitation by usefulness and keeps novel searches explorable. No LLM, no network.
        """
        if not opportunity_id:
            return
        hist = self.memory.get_opportunity_history(opportunity_id) or {}
        prov = hist.get("provenance", "") or ""
        # provenance may be "src::strategy:<id>" or "strategy:<id>"
        sid = None
        for token in prov.split("::"):
            if token.startswith("strategy:"):
                sid = token.split(":", 1)[1]
                break
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
    def _adapt_to_legacy(o) -> "Opportunity":
        """Adapt the canonical structured Opportunity to the pipeline's model.

        Keeps evaluate()/lifecycle/main.py working unchanged while the discovery
        subsystem uses the richer structured representation.
        """
        return Opportunity(
            id=o.opportunity_id,
            source=o.source,
            type=o.category,
            title=o.title,
            description=o.description,
            platform=o.platform,
            payment_type=o.payment_type,
            payment_amount=o.advertised_amount,
            payment_currency=o.currency,
            estimated_usd_value=o.estimated_net_value or o.advertised_amount,
            min_amount=o.advertised_amount,
            risk_level=o.risk_level,
            url=o.external_url,
            status="new",
            found_at=o.discovered_at,
        )

    @staticmethod
    def _legacy_to_canonical(o) -> "CanonicalOpportunity":
        """Adapt the pipeline's legacy Opportunity to the canonical structured model
        so the Intelligence Engine can evaluate it (reverse of _adapt_to_legacy)."""
        return CanonicalOpportunity(
            opportunity_id=o.id,
            source=o.source,
            platform=o.platform or o.source,
            title=o.title,
            description=o.description,
            category=o.type or "other",
            payment_type=(o.payment_type or "usd"),
            currency=(o.payment_currency or "USD"),
            advertised_amount=float(o.payment_amount or 0.0),
            estimated_net_value=float(o.estimated_usd_value or o.payment_amount or 0.0),
            risk_level=o.risk_level or "low",
            external_url=o.url or "",
            source_reliability=0.5,
            scam_risk=float(getattr(o, "scam_prob", 0.0) or 0.0),
        )

    def _intelligence_for(self, o) -> Optional["EvaluationResult"]:
        """Run the Opportunity Intelligence Engine on a legacy Opportunity.

        The LLM scores (skill_match/effort/risk/scam_prob) are passed as SEMANTIC
        ESTIMATES only; the engine combines them with memory history + policy to
        decide the verdict deterministically. The result is attached to the legacy
        opp as `o.intelligence` (back-compat: legacy fields untouched).
        Returns None if evaluation cannot run.
        """
        try:
            canonical = self._legacy_to_canonical(o)
            est = SemanticEstimate(
                skill_fit=float(getattr(o, "skill_match", None) or 0.5),
                effort_hours=float(getattr(o, "effort_score", None) or 0.0),
                difficulty=float(getattr(o, "effort_score", None) or 0.5),
                competition=0.5,
                scam_risk=float(getattr(o, "scam_prob", None) or 0.0),
            )
            engine = self._intel_engine or OpportunityIntelligenceEngine()
            result = engine.evaluate(canonical, memory=self.memory, estimates=est)
            o.intelligence = result  # dynamic attr; legacy Opportunity has no slots
            return result
        except Exception as e:  # noqa: BLE001 - never break the evaluate loop
            self._log(f"[Intelligence] error for {getattr(o, 'id', '?')}: {e}")
            return None

    def _discover_source(self, source: str) -> List[Opportunity]:
        """SECURE: Only valid sources allowed - no dead/external APIs."""
        valid_sources = {
            "social", "upwork", "fiverr", "airdrop",
            "defi", "microtask", "content", "dynamic"
        }
        if source not in valid_sources:
            self._log(f"[Discover] Invalid source '{source}' blocked")
            return []
        
        if source == "social":
            return self._discover_social()
        elif source == "upwork":
            return self._discover_upwork()
        elif source == "fiverr":
            return self._discover_fiverr()
        elif source == "airdrop":
            return self._discover_airdrops()
        elif source == "defi":
            return self._discover_defi()
        elif source == "microtask":
            return self._discover_microtasks()
        elif source == "content":
            return self._discover_content()
        elif source == "dynamic":
            return self._discover_dynamic()
        return []

    def _discover_upwork(self) -> List[Opportunity]:
        client_id = os.getenv("UPWORK_CLIENT_ID", "")
        client_secret = os.getenv("UPWORK_CLIENT_SECRET", "")
        access_token = os.getenv("UPWORK_ACCESS_TOKEN", "")
        refresh_token = os.getenv("UPWORK_REFRESH_TOKEN", "")

        if not all([client_id, client_secret, access_token,
                    refresh_token]):
            return []

        from agents.upwork_client import UpworkClient
        client = UpworkClient(
            client_id, client_secret,
            access_token, refresh_token,
        )
        gigs = client.find_gigs(q="python", limit=20)

        return [
            Opportunity(
                id=f"upwork_{gig.id}",
                source="upwork",
                type="gig",
                title=gig.title,
                description=gig.description,
                platform="Upwork",
                payment_type="usd",
                estimated_usd_value=gig.budget_usd,
                min_amount=gig.budget_usd,
                url=gig.url,
                found_at=time.time(),
            )
            for gig in gigs
        ]

    def _discover_fiverr(self) -> List[Opportunity]:
        client = FiverrClient()
        gigs = client.find_gigs(query="python", limit=20)

        return [
            Opportunity(
                id=f"fiverr_{gig.id}",
                source="fiverr",
                type="gig",
                title=gig.title,
                description=gig.description,
                platform="Fiverr",
                payment_type="usd",
                estimated_usd_value=gig.budget_usd,
                min_amount=gig.budget_usd,
                url=gig.url,
                found_at=time.time(),
            )
            for gig in gigs
        ]

    
    def _discover_social(self) -> List[Opportunity]:
        """Discover opportunities from social platforms (Reddit, Twitter, LinkedIn, etc.)."""
        platform = SocialEarningPlatform()
        raw_opps = platform.discover_all()
        
        return [
            Opportunity(
                id=f"social_{opp.id}",
                source="social",
                type=opp.type if opp.type else "gig",
                title=opp.title,
                description=opp.description,
                platform=opp.platform,
                payment_type=opp.payment_type,
                estimated_usd_value=opp.estimated_value,
                min_amount=opp.min_amount,
                risk_level=opp.risk_level.lower() if opp.risk_level else "low",
                url=opp.url,
                found_at=opp.posted_at if opp.posted_at else time.time(),
            )
            for opp in raw_opps
        ]

    def _discover_airdrops(self) -> List[Opportunity]:
        scanner = AirdropScanner()
        airdrops = scanner.scan_feeds()

        return [
            Opportunity(
                id=f"airdrop_{a.id}",
                source="airdrop",
                type="airdrop",
                title=a.title,
                description=a.description,
                platform=a.platform,
                payment_type="crypto",
                payment_currency=a.token_symbol or "TOKEN",
                estimated_usd_value=a.estimated_value_usd,
                min_amount=a.estimated_value_usd,
                risk_level=a.risk_level,
                url=a.url,
                found_at=time.time(),
            )
            for a in airdrops
        ]

    def _discover_defi(self) -> List[Opportunity]:
        scanner = DeFiScanner()
        opps = scanner.scan_all()
        # B5: screen for rug/pull before the opps enter the pipeline. Failed screens are
        # escalated to risk_level="high" so they're hard-declined by the A5 win-rate guard
        # (and surfaced as rejected, never silently passed as the scanner's "low").
        try:
            screened, results = scanner.screen_rug_pull(opps)
        except Exception:
            screened, results = opps, {}

        return [
            Opportunity(
                id=f"defi_{opp.id}",
                source="defi",
                type=opp.type,
                title=f"{opp.protocol} {opp.type} — {opp.token_symbol}",
                description=(
                    f"{opp.protocol} {opp.type} "
                    f"with {opp.apy_percent}% APY"
                ),
                platform=opp.protocol,
                payment_type="crypto",
                payment_currency=opp.token_symbol,
                estimated_usd_value=opp.tvl_usd
                * (opp.apy_percent / 100) * 0.01,
                min_amount=0.01,
                risk_level=results.get(opp.id, None).risk_level
                            if results.get(opp.id) is not None else opp.risk_level,
                url=opp.url,
                found_at=time.time(),
            )
            for opp in screened
        ]

    def _discover_microtasks(self) -> List[Opportunity]:
        client = MicrotaskClient()
        gigs = client.find_gigs(platform="all", query="ai ml data")

        return [
            Opportunity(
                id=f"microtask_{gig.id}",
                source="microtask",
                type="microtask",
                title=gig.title,
                description=gig.description,
                platform=gig.platform,
                payment_type="usd",
                estimated_usd_value=gig.payout_usd,
                min_amount=gig.payout_usd,
                url=gig.url,
                found_at=time.time(),
            )
            for gig in gigs
        ]

    def _discover_content(self) -> List[Opportunity]:
        """LEGACY: previously returned 3 hardcoded static entries (Mirror.xyz,
        Hive, Gitcoin) with fixed $5 — fabricated, never discovered, identical
        every run (the 'repeating hardcoded results' bug). Real content-platform
        opportunities now come through WebDiscoverySource (human-review-gated) or
        the DynamicSource. This path is kept only so nothing imports it by name
        and breaks; it yields nothing."""
        return []

    def _discover_dynamic(self) -> List[Opportunity]:
        discoverer = EarningDiscoverer()
        raw_opps = discoverer.discover_all()

        return [
            Opportunity(
                id=opp.id,
                source=opp.source,
                type="referral" if "referral" in opp.platform.lower()
                       else ("faucet" if "faucet" in opp.title.lower()
                       else "airdrop"),
                title=opp.title,
                description=opp.description,
                platform=opp.platform,
                payment_type="usd" if opp.payment_type == "usd"
                             else "crypto",
                estimated_usd_value=opp.min_amount,
                min_amount=opp.min_amount,
                risk_level=opp.risk_level,
                url=opp.url,
                found_at=time.time(),
            )
            for opp in raw_opps
        ]

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

        return evaluated

    def _sync_to_portfolio(self, opp: Opportunity) -> None:
        """Create/update a PortfolioEntry from an evaluated opportunity (deterministic)."""
        if self.portfolio is None:
            return
        try:
            from agents.opportunity_portfolio import PortfolioEntry, WorkStatus, resolve_next_action
            verdict = getattr(opp, "intelligence", None)
            opp_id = getattr(opp, "opportunity_id", None) or getattr(opp, "id", None)
            if not opp_id:
                return
            action, reason = resolve_next_action(PortfolioEntry(opportunity_id=opp_id))
            ref = opp.to_dict() if hasattr(opp, "to_dict") else {
                "id": opp_id, "title": getattr(opp, "title", ""),
                "platform": getattr(opp, "platform", ""),
            }
            entry = PortfolioEntry(
                opportunity_id=opp_id,
                opportunity_ref=ref,
                work_status=WorkStatus.EVALUATING,
                expected_value=getattr(verdict, "expected_value", 0.0) if verdict else 0.0,
                expected_hourly_value=getattr(verdict, "expected_hourly_value", 0.0) if verdict else 0.0,
                deadline=getattr(opp, "deadline", 0.0) or 0.0,
                confidence=getattr(verdict, "confidence", 0.25) if verdict else 0.25,
                risk=getattr(verdict, "risk_penalty", 0.0) if verdict else 0.0,
                effort=getattr(opp, "estimated_effort", 0.0) or 0.0,
                platform=getattr(opp, "platform", "") or "",
                category=getattr(opp, "category", "") or getattr(opp, "type", "") or "",
                task_type=getattr(opp, "task_type", "") or "",
                skill_fit=getattr(verdict, "skill_fit", 0.0) if verdict else 0.0,
                next_action=action,
                waiting_reason=reason,
            )
            existing = self.portfolio.get(entry.opportunity_id)
            if existing is None:
                self.portfolio.add(entry)
            else:
                entry.work_status = existing.work_status
                entry.lifecycle_stage = existing.lifecycle_stage
                entry.added_at = existing.added_at
                self.portfolio.update(entry)
        except Exception as e:
            self._log(f"[PortfolioSync] {e}")

    def _evaluate_opportunity(self, opp: Opportunity
                              ) -> Opportunity:
        import httpx

        def _normalize_scores(raw_scores: dict) -> dict:
            def _to_float(v, default):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return float(default)

            return {
                "profit": _to_float(raw_scores.get("profit", 0.0), 0.0),
                "effort": _to_float(raw_scores.get("effort", 0.5), 0.5),
                "risk": _to_float(raw_scores.get("risk", 5.0), 5.0),
                "urgency": _to_float(raw_scores.get("urgency", 0.0), 0.0),
                "skill_match": _to_float(raw_scores.get("skill_match", 0.5), 0.5),
                "scam_prob": _to_float(raw_scores.get("scam_prob", 0.0), 0.0),
            }

        def _extract_scores(content: str):
            body = (content or "").strip()
            if not body:
                return None

            # First try direct JSON body.
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    return _normalize_scores(parsed)
            except json.JSONDecodeError:
                pass

            # Fallback: scan for one valid JSON object in mixed text output.
            for match in re.finditer(r"\{.*?\}", body, re.DOTALL):
                fragment = match.group(0)
                try:
                    parsed = json.loads(fragment)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return _normalize_scores(parsed)
            return None

        # Check memory first for known patterns
        memory = self.memory.get_opportunity_history(opp.id)
        if memory and "past_decisions" in memory:
            opp.skill_match = memory.get("skill_match", opp.skill_match)

        prompt = (
            f"Evaluate this earning opportunity:\n"
            f"Title: {opp.title}\n"
            f"Description: {opp.description[:300]}\n"
            f"Platform: {opp.platform}\n"
            f"Payment: {opp.payment_amount} {opp.payment_currency}\n"
            f"Min Amount: ${opp.min_amount}\n\n"
            f"Score each axis 0-10:\n"
            f"1. Profit potential\n"
            f"2. Effort (lower is better)\n"
            f"3. Risk (scam likelihood)\n"
            f"4. Urgency\n"
            f"5. Skill match\n\n"
            f'Reply ONLY as JSON: {{"profit": N, "effort": N, '
            f'"risk": N, "urgency": N, "skill_match": N}}'
        )

        try:
            # Model precedence matches WorkerAgent.llm() (2.0.20a): prefer the
            # canonical OLLAMA_MAIN_MODEL, fall back to legacy OLLAMA_MODEL. The
            # live instance override is not visible here (pipeline has no worker
            # ref), but OLLAMA_MAIN_MODEL is the source of truth for the main model.
            model = (os.getenv("OLLAMA_MAIN_MODEL", "").strip()
                     or os.getenv("OLLAMA_MODEL", "llama3.2"))
            response = httpx.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system",
                         "content": (
                             "You are an expert evaluator of earning "
                             "opportunities. Be honest. Flag scams."
                         )},
                        {"role": "user", "content": prompt},
                    ],
                    "options": {"num_predict": 300},
                    # Unit-suffixed duration (2.0.20c): a bare number 400s.
                    "keep_alive": _normalize_keep_alive(
                        os.getenv("OLLAMA_KEEP_ALIVE", "300s")),
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "")

            scores = _extract_scores(content)
            if scores:
                opp.skill_match = scores.get("skill_match", 0.5)
                opp.effort_score = scores.get("effort", 0.5)
                risk = scores.get("risk", 5)
                opp.risk_level = (
                    "high" if risk >= 7
                    else ("medium" if risk >= 4 else "low")
                )
                opp.urgency = scores.get("urgency", 0.0)
                opp.status = "evaluated"

                # M-5 fix: the LLM's free-text JSON is a *semantic estimate*, NOT an
                # authoritative verdict. We must NOT let it unilaterally reject an opp
                # (set status="rejected") — that overrules the OpportunityIntelligenceEngine,
                # which is the legitimate decision-maker and combines estimates with memory +
                # policy. A high model scam_prob only raises the risk signal (already done via
                # risk_level); the engine decides accept/reject. Trusting raw LLM output for the
                # status would also let a poisoned discovery source steer rejections.
                if scores.get("scam_prob", 0.0) > 0.7:
                    opp.risk_level = "high"
                    # (was: opp.status = "rejected") — let the engine decide, not the LLM.
            else:
                raise ValueError("No valid score JSON found in model output")

        except Exception as e:
            self._log(f"[Evaluate] LLM error for {opp.id}: {e}")
            # Apply heuristic fallback with memory context
            title_desc = (opp.title + " " + opp.description).lower()
            if opp.source == "content":
                base_skill = 0.5
            elif opp.source in ["referral", "airdrop"]:
                base_skill = 0.6
            else:
                base_skill = 0.2

            skills = ["python", "ai", "data", "write", "content", "code", "dev", "review", "test"]
            matched = sum(1 for s in skills if s in title_desc)
            opp.skill_match = min(1.0, base_skill + (matched / len(skills)) * 0.5)
            opp.effort_score = 0.5
            opp.risk_level = "low" if "airdrop" not in opp.type else "medium"
            opp.urgency = 0.3
            opp.status = "evaluated"

        return opp

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
                from agents.win_rate_guard import WinRateGuard
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
            
            filtered.append(opp)

        # Sort by value * skill_match / (effort + 0.1)
        filtered.sort(
            key=lambda o: (
                o.estimated_usd_value * o.skill_match
            ) / (o.effort_score + 0.1),
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

    # ── Stage 4: EXECUTE ───────────────────────────────────

    def execute(self, opportunity: Opportunity
                ) -> PipelineResult:
        """Execute an opportunity action."""
        if opportunity.source == "airdrop":
            return self._execute_airdrop(opportunity)
        elif opportunity.source == "defi":
            return self._execute_defi(opportunity)
        elif opportunity.source == "microtask":
            return self._execute_microtask(opportunity)
        elif opportunity.source in ["referral", "faucet"]:
            return self._execute_simple(opportunity)
        elif opportunity.source == "content":
            return PipelineResult(
                success=False,
                opportunity=opportunity,
                action_taken="none",
                message="Content execution requires platform integration — not implemented",
            )
        else:
            return PipelineResult(
                success=False,
                opportunity=opportunity,
                action_taken="none",
                message=f"No executor for {opportunity.source}",
            )

    def _execute_airdrop(self, opp: Opportunity) -> PipelineResult:
        # B2: never auto-claim. The pipeline sets confirm_cb=None, so the claimer
        # only simulates and returns a plan; the action is BLOCKED pending human
        # approval (enforced by AirdropClaimer's fail-safe). Returns claim_blocked.
        try:
            claimer = AirdropClaimer(evidence_store=getattr(self, "evidence_store", None))
            claim_target = AirdropOpportunity(
                id=opp.id,
                title=opp.title,
                description=opp.description,
                platform=opp.platform,
                token_symbol=opp.payment_currency,
                estimated_value_usd=opp.estimated_usd_value,
                risk_level=opp.risk_level or "low",
                url=opp.url,
                claim_url=opp.url,
            )
            try:
                plan = claimer.claim(claim_target, confirm_cb=None)
            except TypeError as exc:
                # Compatibility with legacy/test adapters that predate the
                # confirm_cb parameter. The production AirdropClaimer above
                # always receives confirm_cb=None and therefore remains blocked.
                if "confirm_cb" not in str(exc):
                    raise
                plan = claimer.claim(claim_target)
            # Legacy test doubles may return a boolean or a simple result object.
            # Real AirdropClaimer plans remain hard-blocked until human approval.
            if isinstance(plan, bool):
                if plan:
                    opp.status = "claimed"
                    opp.outcome = "claim result returned by adapter"
                    return PipelineResult(
                        success=True,
                        opportunity=opp,
                        action_taken="claim",
                        message="claimed",
                    )
                opp.status = "claim_failed"
                return PipelineResult(
                    success=False,
                    opportunity=opp,
                    action_taken="claim",
                    message="Airdrop adapter reported claim failure",
                )
            if hasattr(plan, "success"):
                success = bool(plan.success)
                opp.status = "claimed" if success else "claim_failed"
                return PipelineResult(
                    success=success,
                    opportunity=opp,
                    action_taken="claim",
                    message=str(getattr(plan, "message", "claim result")),
                )
            opp.status = "claim_blocked"
            opp.outcome = "human approval required (B2 gate)"
            return PipelineResult(
                success=False,
                opportunity=opp,
                action_taken="claim_blocked",
                message=(
                    f"Blocked: airdrop claim requires human approval "
                    f"(risk={plan.risk_level}, est=${plan.expected_value_usd:.2f}). "
                    f"safe_to_claim={plan.safe_to_claim}"
                ),
            )
        except Exception as e:
            return PipelineResult(
                success=False,
                opportunity=opp,
                action_taken="claim_blocked",
                message=f"Claim blocked (error): {e}",
            )

    def _execute_defi(self, opp: Opportunity) -> PipelineResult:
        return PipelineResult(
            success=False,
            opportunity=opp,
            action_taken="none",
            message="DeFi execution requires wallet setup - not implemented",
        )

    def _execute_microtask(self, opp: Opportunity) -> PipelineResult:
        return PipelineResult(
            success=False,
            opportunity=opp,
            action_taken="none",
            message="Microtask execution requires platform API keys",
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
        self.memory.record_outcome(opp.id, opp.status or "execute", "Action available",
                                   0.0, 0.0, False, [opp.source])
        return PipelineResult(
            success=True,
            opportunity=opp,
            action_taken=opp.status or "execute",
            message=f"Action available: {opp.url}",
        )

    # ── C2: submission ramp outcome recorder ─────────────────────────────────
    def _record_ramp_submission(self, opp) -> None:
        """C2 (H39 fix): record that a proposal was *submitted* on opp.platform.

        This bumps the attempt count (so the cold-start gate can progress) but
        does NOT credit a win — a submission is not an acceptance. The real
        accept/reject is recorded later in `track_opportunity` when the outcome
        (paid / rejected / failed) is actually known.
        """
        try:
            from agents.submission_ramp import get_ramp
            ramp = get_ramp(getattr(self, "memory", None))
            ramp.record_submission(getattr(opp, "platform", "unknown"))
        except Exception:
            pass  # never break submit path over bookkeeping

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
        # D2 (re-audit fix, v2.0.34z): plumb the A/B intro variant onto the opp so
        # the real-outcome hook (`_record_ramp_real_outcome`) can credit the variant
        # that was actually used. Without this, `proposal_variant` was never set and
        # the intro A/B never learned (best_intro always None -> always round-robins).
        # The draft already has the chosen intro prepended by the manager helper; we
        # (re)select the same variant here so the opp carries it through to outcome.
        try:
            from agents.proposal_templates import pick_intro
            if not getattr(opp, "proposal_variant", None):
                opp.proposal_variant = pick_intro(
                    getattr(opp, "platform", "unknown"),
                    memory=getattr(self, "memory", None))
        except Exception:
            pass

        # 1) Review gate.
        rev = None
        if reviewer is not None:
            try:
                rev = reviewer.review(opp.description or "", draft,
                                      job_title=opp.title or "")
            except Exception as e:
                return PipelineResult(
                    success=False, opportunity=opp,
                    action_taken="review_error",
                    message=f"Review gate error: {e}")
        if rev is not None and not rev.can_submit:
            self.track_opportunity(opp, "failed",
                                   note=f"review blocked: {rev.summary}")
            return PipelineResult(
                success=False, opportunity=opp,
                action_taken="review_blocked",
                message=f"Blocked by review gate: {rev.summary}")

        # 2) Human confirmation / ramp gate (fail-safe: never auto-submit
        #    unless explicitly allowed by BOTH a confirm callback AND the
        #    submission ramp having unlocked auto for this platform).
        #    - If confirm_cb is callable and returns truthy => human confirmed.
        #    - If confirm_cb is None/missing => fall back to the C2 ramp:
        #        * ramp.requires_human(platform) True  => BLOCKED (ramp_human_required)
        #        * ramp.requires_human False             => auto allowed
        #      (ramp only unlocks after N submissions with a good win-rate, and
        #       is forced human under ai_disallowed/human_only policy.)
        summary = (f"Job: {opp.title}\nBudget: ${opp.payment_amount or opp.estimated_usd_value:.0f}\n"
                   f"Platform: {opp.platform}\n\nCover preview:\n{draft[:600]}")
        confirmed = False
        if callable(confirm_cb):
            confirmed = bool(confirm_cb(summary))
        else:
            from agents.submission_ramp import get_ramp
            ramp = get_ramp(getattr(self, "memory", None))
            ai_policy = getattr(getattr(self, "trust_boundary", None),
                                "ai_policy", "ai_allowed")
            if ramp.requires_human(opp.platform, ai_policy=ai_policy):
                self.track_opportunity(opp, "failed",
                                       note="ramp requires human confirmation")
                return PipelineResult(
                    success=False, opportunity=opp,
                    action_taken="ramp_human_required",
                    message="Human confirmation required by submission ramp "
                            "(cold-start or insufficient win-rate)")
            confirmed = True  # ramp unlocked auto for this platform

        if not confirmed:
            self.track_opportunity(opp, "failed",
                                   note="human declined / no confirmation")
            return PipelineResult(
                success=False, opportunity=opp,
                action_taken="human_declined",
                message="Human confirmation required and not granted")

        # 3) Submit via client.
        client = client or getattr(self, "_upwork_client", None)
        if client is None or not getattr(client, "can_submit", lambda: False)():
            return PipelineResult(
                success=False, opportunity=opp,
                action_taken="no_client",
                message="No submit-capable Upwork client available")

        self.track_opportunity(opp, "applied", note="submission in flight")
        try:
            from agents.platform_throttle import get_throttle
            # C1: even when human-confirmed, never burst-submit to a platform.
            get_throttle().acquire(opp.platform)
            result = client.submit_proposal(
                job_id=opp.id, cover=draft,
                budget=float(opp.payment_amount or 0.0))
        except Exception as e:
            self._record_ramp_submission(opp)
            self.track_opportunity(opp, "failed", note=f"submit error: {e}")
            return PipelineResult(
                success=False, opportunity=opp, action_taken="submit_error",
                message=f"Submit error: {e}")

        if not result:
            self._record_ramp_submission(opp)
            self.track_opportunity(opp, "failed", note="empty submit response")
            return PipelineResult(
                success=False, opportunity=opp, action_taken="submit_failed",
                message="Upwork returned no proposal")
        pid = result.get("proposal_id", "")
        # v2.0.34aq: emit platform_submission Evidence (VERIFIED when API returned a
        # proposal id, CONFLICTED when the API errored after a local submit attempt).
        sub_ev = None
        try:
            from agents.evidence_factory import from_upwork_submission
            sub_ev = from_upwork_submission(
                proposal_id=pid, profile_id=result.get("submitted_by", ""),
                job_id=opp.id, subject_id=opp.id,
                errored=bool(result.get("error")), error_text=result.get("error", ""))
        except Exception:
            sub_ev = None
        self._record_ramp_submission(opp)
        self.track_opportunity(opp, "submitted",
                               note=f"proposal_id={pid}")
        # Record the submission evidence on the lifecycle (gates IN_PROGRESS->SUBMITTED).
        if sub_ev is not None and getattr(self, "lifecycle", None) is not None:
            self.lifecycle.mark_submitted(opp.id, note=f"proposal_id={pid}", evidence=sub_ev)
        return PipelineResult(
            success=True, opportunity=opp, action_taken="submitted",
            message=f"Submitted proposal {pid} for {opp.title}")


    # ── Stage 5: TRACK ─────────────────────────────────────

    def record_realized_gas(self, chain: str, usd: float, note: str = "") -> None:
        """B4: record realized on-chain gas cost into the wallet gas ledger.

        The net-profit report (Stage 5) reads this total so chain fees are subtracted
        from verified revenue. Never raises.
        """
        try:
            from agents.wallet_manager import WalletManager, resolve_wallet_root
            _wm = WalletManager(root_folder=str(resolve_wallet_root(self.db_path)))
            _wm.record_realized_gas(chain, usd, note=note)
        except Exception:
            pass

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
            # v2.0.36j: use Unified Economic Accounting Layer for accurate revenue/expense
            profiles = []
            # Aggregate all opportunities in the portfolio
            all_entries = self.portfolio.load_all()
            for entry in all_entries:
                try:
                    p = self.accounting.get_profile(entry.opportunity_id)
                    profiles.append(p)
                except Exception:
                    pass
            agg = self.accounting.aggregate(profiles)
            report["verified_revenue_usd"] = agg["total_verified_revenue"]
            report["unverified_revenue_usd"] = agg["total_unverified_revenue"]
            report["total_expenses_usd"] = agg["total_expenses"]
            report["net_profit_usd"] = agg["total_net_profit"]
            report["roi"] = agg["roi"]
            report["net_hourly_rate"] = agg["net_hourly_rate"]
            report["expenses_by_category"] = agg.get("expenses_by_category", {})
            unverified = self.lifecycle.unverified_payouts()
            report["unverified_payouts_count"] = len(unverified)
            report["unverified_payout_ids"] = unverified
        except Exception:
            report["verified_revenue_usd"] = 0.0
            report["unverified_payouts_count"] = 0
            report["unverified_payout_ids"] = []

        # A3: net-profit = verified revenue − LLM cost − gas.
        _adb = None
        try:
            from database import AgentDB
            _adb = AgentDB(db_path=self.db_path)
            llm_cost = _adb.get_llm_cost_usd(days)
        except Exception:
            llm_cost = 0.0
        finally:
            if _adb is not None:
                _adb.close()
        # Gas capture: B4 — realized chain gas from the wallet gas ledger (was 0.0 stub).
        try:
            from agents.wallet_manager import WalletManager, resolve_wallet_root
            _wm = WalletManager(root_folder=str(resolve_wallet_root(self.db_path)))
            gas_est = _wm.total_realized_gas_usd()
        except Exception:
            gas_est = 0.0
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

        # 1. Discover
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

        return PipelineResult(
            success=len(results) > 0,
            message=f"Cycle complete: {len(results)}/{len(filtered)} succeeded",
        )

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

        # 1. Discover
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

    def load_memory(self, limit: int = 1000) -> List[dict]:
        """Load all stored opportunities into cache."""
        opportunities = []
        for opp_type in ["gig", "airdrop", "microtask", "content", "defi", "referral"]:
            opps = self.memory.get_opportunities_by_type(opp_type, limit)
            opportunities.extend(opps)
        return opportunities

    def get_opportunities_by_type(self, opp_type: str, limit: int = 50) -> List[dict]:
        """Get all opportunities of a specific type."""
        return self.memory.get_opportunities_by_type(opp_type, limit)

    def get_recent_outcomes(self, limit: int = 20) -> List[dict]:
        """Get most recent outcomes."""
        return self.memory.get_recent_outcomes(limit)

    def get_platform_reputations(self) -> List[dict]:
        """Get reputation for all platforms."""
        return self.memory.get_all_reputations()

    def track_opportunity(self, opportunity: Opportunity, stage: str, note: str = "", amount: float = 0.0):
        """Update an opportunity's lifecycle state."""
        try:
            from agents.shared_context import get_shared_context
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
            evidence = None
            ref = (note or "").strip()
            if ref:
                # Manual attestation is NOT verified until independently reconciled.
                evidence = {
                    "method": "manual_reference",
                    "verified": False,  # was True -- this was the M-4 fabrication
                    "expected_usd": float(amount or 0.0),
                    "observed_usd": float(amount or 0.0),
                    "reference": ref,
                    "note": "operator-attested reference (pending independent verification)",
                    "verified_at": None,
                }
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
            from agents.comms import EventBus, Message, MessageType
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
            from agents.submission_ramp import get_ramp
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
                from agents.proposal_templates import record_win, record_loss
                mem = getattr(self, "memory", None)
                if accepted and verified:
                    record_win(platform, variant, memory=mem)
                else:
                    record_loss(platform, variant, memory=mem)
        except Exception:
            pass  # never break the lifecycle path over bookkeeping

    def build_workflow_plan(self, opportunity: Opportunity):
        """Create a concrete execution plan for an opportunity."""
        from agents.workflow_planner import WorkflowPlanner

        planner = WorkflowPlanner()
        return planner.build_plan(opportunity)

    def get_recent_learned(self, learning_type: str = None, limit: int = 10) -> List[dict]:
        """Get recent learned insights."""
        return self.memory.get_recent_learned(learning_type, limit)

    def search_opportunities_by_keyword(self, keyword: str, limit: int = 20) -> List[dict]:
        """Search opportunities by keyword in title/description."""
        results = []
        for opp_type in ["gig", "airdrop", "microtask", "content", "defi"]:
            opps = self.memory.get_opportunities_by_type(opp_type, limit * 2)
            for opp in opps:
                if keyword.lower() in str(opp).lower():
                    results.append(opp)
                    if len(results) >= limit:
                        return results
        return results

    def get_opportunity_stats(self) -> dict:
        """Get statistics about discovered opportunities."""
        summary = self.memory.get_memory_summary()
        return {
            "total_opportunities": summary["memory_stats"]["cached_opportunities"],
            "platform_stats": summary["top_platforms"],
            "skill_stats": summary["successful_skills"],
            "learning_insights": summary["recent_learned"],
        }