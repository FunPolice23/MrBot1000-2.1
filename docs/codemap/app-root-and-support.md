## app/ + root files

> Function-level map. `main.py` is the `MainWindow` entry point; `app/` holds application services. `app/ui.py` is now theme helpers only (the legacy 2D-office UI was removed).

### `app/__init__.py` — Application-layer services and bootstrap helpers. (2L)


### `app/action_pipeline.py` — action_pipeline.py — Controlled Action Pipeline for MrBot1000 (640L)

**Classes:**
- `class ProposedAction` (L41) — A structured action proposed by any agent.
- `class ValidationResult` (L58)
  - `summary() -> str` (L66)
- `class ExecutionResult` (L78)
- `class SyntaxValidator` (L90) — Parse Python source with ast.parse — catches all syntax errors.
  - `validate(code: str) -> ValidationResult` (L94)
- `class ApiUsageValidator` (L135) — Check that any API calls in the code use known, valid patterns.
  - `validate(code: str) -> ValidationResult` (L169)
- `class NullSafetyValidator` (L189) — Detect common null/None safety issues and bad attribute access patterns.
  - `validate(code: str) -> ValidationResult` (L195)
- `class SpellingValidator` (L224) — Basic English spelling check on string literals, comments, and
  - `validate(code: str) -> ValidationResult` (L246)
- `class ImportValidator` (L269) — Verify that all imports in the code are from our allowed dependency set.
  - `validate(code: str) -> ValidationResult` (L289)
- `class SecurityValidator` (L312) — Block dangerous operations.
  - `validate(code: str) -> ValidationResult` (L328)
- `class ActionPipeline` (L341) — Validates and executes proposed actions.
  - `__init__(root_folder: str, db=None, log_fn: Callable=None, safe_mode: bool=False)` (L357)
  - `set_summarizer(worker)` (L386) — Inject Summarizer worker for deep language checks.
  - `process(action: ProposedAction) -> ExecutionResult` (L390) — Full pipeline: validate → (optionally) fix → execute.
  - `_run_validators(code: str) -> ValidationResult` (L426)
  - `_execute(action: ProposedAction) -> ExecutionResult` (L454)
  - `_safe_path(rel: str) -> Optional[Path]` (L506) — Resolve a relative path and verify it stays inside ROOT_FOLDER.
  - `_exec_create_file(action: ProposedAction) -> ExecutionResult` (L521)
  - `_exec_modify_file(action: ProposedAction) -> ExecutionResult` (L543)
  - `_exec_delete_file(action: ProposedAction) -> ExecutionResult` (L565)
  - `_exec_self_improve(action: ProposedAction) -> ExecutionResult` (L578) — Self-improvement: the agent proposes a new version of one of its
  - `_exec_assist(action: ProposedAction) -> ExecutionResult` (L593) — Agent-to-agent assist: route the task result to another agent.
  - `_log_validation(action: ProposedAction, vr: ValidationResult)` (L607)
  - `_store_action(action: ProposedAction, outcome: str, message: str)` (L614)
  - `validate_only(code: str) -> ValidationResult` (L629) — Public helper — just validate without executing.
  - `quick_check(code: str) -> Tuple[bool, str]` (L633) — Fast yes/no check for UI display.


### `app/database.py` — database.py — SQLite persistence layer for the agent system. (676L)

**Classes:**
- `class AgentDB` (L18)
  - `__init__(db_path: str=DB_PATH)` (L19)
  - `_execute(sql, params=(), commit=False)` (L29)
  - `_create_tables()` (L36)
  - `get_cached_file(folder_path: str, relative_path: str, max_chars: int=None, current_mtime: float=None) -> str | None` (L215)
  - `save_file_to_cache(folder_path: str, relative_path: str, content: str, size: int, mtime: float)` (L233)
  - `clear_file_cache(folder_path: str=None)` (L243)
  - `log_thought(source: str, text: str)` (L253)
  - `get_thoughts(limit: int=500, source: str=None) -> list[dict]` (L260)
  - `log_llm_call(model: str, provider: str, trigger: str, prompt_chars: int,, ...)` (L276)
  - `_get_llm_stats_basic() -> dict` (L292) — Basic LLM stats (internal use).
  - `get_recent_llm_calls(limit: int=50) -> list[dict]` (L309)
  - `_est_tokens(prompt_chars: int, response_chars: int) -> tuple[float, float]` (L325)
  - `get_llm_cost_breakdown(days: int=30) -> list[dict]` (L330) — A3: estimated LLM spend per (model, provider) over `days`.
  - `get_llm_cost_usd(days: int=30) -> float` (L374) — A3: total estimated LLM API spend over `days` (USD).
  - `add_proposal(gig_title: str=None, platform: str=None, budget_usd: float=, ...) -> int` (L381) — Persist a drafted gig proposal so work survives restart and shows in
  - `get_proposals(limit: int=100) -> list[dict]` (L395)
  - `count_proposals() -> int` (L403)
  - `proposal_exists(gig_title: str, platform: str=None) -> bool` (L407) — True if a proposal draft already exists for this gig title+platform.
  - `in_instruction_allowlist(url: str) -> bool` (L437)
  - `in_instruction_blacklist(url: str) -> bool` (L443)
  - `add_quarantined_instruction(url: str, kind: str, title: str, content_hash: str, content: str) -> int` (L449)
  - `find_quarantined_by_hash(content_hash: str) -> dict | None` (L460)
  - `review_instruction(quarantine_id: int, approve: bool, url: str='', content_hash: str='', related: str='') -> str` (L468) — Move a pending instruction to allowed (allowlist) or blocked
  - `list_pending_instructions(limit: int=100) -> list[dict]` (L495)
  - `count_instruction_lists() -> dict` (L504)
  - `save_research_cache(research: dict)` (L511)
  - `load_latest_research_cache(folder_path: str) -> dict | None` (L528)
  - `log_action(trigger: str, action_text: str)` (L544)
  - `log_decision(trigger: str, full_text: str, action_part: str=None)` (L551)
  - `get_recent_actions(limit: int=20) -> list[dict]` (L559)
  - `ts_to_str(ts: float) -> str` (L569)
  - `close()` (L572) — Close the database connection; safe to call more than once.
  - `log_event(event_type: str, source: str, message: str)` (L599) — Log an event.
  - `get_recent_events(limit: int=100) -> list[dict]` (L608) — Get recent events.
  - `get_llm_stats() -> dict` (L618) — Get comprehensive LLM statistics.


### `app/earning_learning_loop.py` — earning_learning_loop.py — Opportunity Learning Loop orchestration + governance (v2.0.36d). (238L)

**Functions:**
- `_is_security_policy(param: str) -> bool` (L54)

**Classes:**
- `class LearningGovernor` (L61) — Enforces that learning only adjusts ranking/recommendation params within bounds,
  - `can_adjust(param: str) -> bool` (L66)
  - `is_security_policy(param: str) -> bool` (L71)
  - `propose_adjustment(param: str, suggested: float, base: Optional[float]=None) -> Dict[str, Any]` (L74) — Return a clamped, bounded adjustment decision.
  - `propose_suppression(dim: str, value: str, failure_rate: float, sample_size: int) -> Dict[str, Any]` (L94) — Decide whether (and how far) a dimension may be de-prioritized after failures.
- `class LearningDelta` (L116) — What changed as a result of processing one outcome (for audit + future-eval handoff).
- `class LearningLoop` (L128) — Orchestrates the 10-step feedback pipeline after a meaningful outcome.
  - `__init__(memory: EarningMemory, governor: Optional[LearningGovernor]=None)` (L136)
  - `process_outcome(opportunity_id: str, outcome_state=..., predicted=..., actu, ...) -> LearningDelta` (L140) — Run steps 1-10. Returns a LearningDelta (audit + governance decisions).
  - `refuse_security_policy_change(param: str, suggested: float=0.0) -> bool` (L235) — True if the governor refuses to adjust `param` (security policy / unknown).


### `app/earning_memory.py` — earning_memory.py — Multi-tiered memory system for MrBot1000. (1998L)

**Functions:**
- `_confidence_for_samples(n: int) -> float` (L70) — Confidence grows with sample count, capped at 1.0; stays low at n=1..2.
- `recency_weight(ts: float, now: float=None, half_life_days: float=RECENCY_HALF_LIFE_DA) -> float` (L79) — Time-decay weight for an event at timestamp `ts`.
- `_safe_rate(success: int, total: int) -> float` (L93)
- `_normalize_query(q: str) -> str` (L104) — Lowercase, strip punctuation, drop stopwords, dedupe -> canonical form.
- `_strategy_usefulness(used, result_count, useful, completed, paid, net_revenue, duplicates) -> float` (L135) — Composite economic usefulness of a search strategy (v2.0.36g).
- `create_memory(db_path: str=None) -> EarningMemory` (L1961) — Factory function to create an EarningMemory instance.

**Classes:**
- `class MemoryEntry` (L151) — Base memory entry with timestamp.
  - `is_expired() -> bool` (L159)
- `class LearningMetrics` (L164) — The 11 required opportunity-learning metrics for one dimension (category/platform/task_type/global).
- `class EarningMemory` (L194) — Multi-tiered memory system for earning pipeline with learning and decay.
  - `__init__(db_path: str=None, root_folder: str=None)` (L197)
  - `_init_db()` (L219) — Initialize the memory database with all tables.
  - `_migrate_schema()` (L498) — Non-destructive ALTERs for columns/tables added after a DB was first created.
  - `apply_decay(entity_type: str, entity_key: str, factor: float=0.95) -> float` (L537) — Apply decay to stats. Returns new value.
  - `_apply_decay_to_stats(entity_type: str, entity_key: str, factor: float) -> float` (L554) — Apply decay to a specific stat.
  - `periodic_decay(decay_factor: float=0.99)` (L559) — Apply periodic decay to all stats.
  - `remember_opportunity(opp_id: str, memory_data: dict, opp_type: str)` (L569) — Store an opportunity in memory.
  - `get_opportunity_history(opp_id: str) -> Optional[dict]` (L585) — Get history for a specific opportunity.
  - `get_opportunities_by_type(opp_type: str, limit: int=50) -> List[dict]` (L604) — Get all opportunities of a specific type.
  - `record_outcome(opp_id: str, action: str, result: str, revenue_usd: float=0, ...)` (L619) — Record an outcome from executing an action.
  - `get_outcome_history(opp_id: str) -> List[dict]` (L643) — Get all outcomes for an opportunity.
  - `get_recent_outcomes(limit: int=20) -> List[dict]` (L658) — Get most recent outcomes.
  - `record_opportunity_event(opp_id: str, stage: str, detail: str='')` (L678) — 3. OPPORTUNITY MEMORY: append a lifecycle event to an opportunity's timeline.
  - `record_outcome_v2(opp_id: str, outcome_state: str, platform=..., category=..., ...) -> Optional[int]` (L689) — Record a rich outcome event across all learning-memory types.
  - `_record_prediction(opp_id, outcome_state, platform, category, task_type, predi, ...)` (L801) — Append a predicted-vs-actual comparison row (v2.0.36d). Deterministic.
  - `link_outcome_evidence(opportunity_id: str, evidence_id: str)` (L842) — Associate a verified Evidence record with an outcome (v2.0.36d). Append-only.
  - `get_outcome_evidence(opportunity_id: str) -> List[str]` (L855) — Return evidence ids linked to an outcome.
  - `record_search_strategy(strategy_id: str, origin: str, query: str, categories: List, ...) -> None` (L867) — Record (or touch) a generated search strategy. Its ECONOMIC outcomes are
  - `record_strategy_result(strategy_id: str, result_count=..., useful_result_count=..., ...) -> None` (L901) — Learn the ECONOMIC outcome of a search strategy (v2.0.36g).
  - `record_strategy_outcome(strategy_id: str, success: bool, reward: float=0.0) -> None` (L943)
  - `get_search_strategy_stats(strategy_id: str) -> dict` (L951)
  - `top_search_strategies(n: int=10, min_used: int=1, by: str='usefulness') -> List[dict]` (L994) — Strategies ranked for EXPLOITATION.
  - `explore_search_strategies(n: int=10, max_used: int=MIN_SAMPLES) -> List[dict]` (L1039) — Novel/under-tried strategies to keep EXPLORATION alive.
  - `get_successful_search_terms(n: int=20) -> List[str]` (L1060) — Queries that have produced USEFUL/profitable work — feed exploitation.
  - `get_failed_search_terms(n: int=20) -> List[str]` (L1077) — Queries that never produced useful work — feed avoidance/recycling.
  - `_record_failure(opp_id, cause, platform, category, task_type, strategy_used, ...)` (L1095)
  - `_record_success(opp_id, cause, platform, category, task_type, strategy_used, ...)` (L1110)
  - `_record_strategy(strategy, variant, is_success, is_failure, revenue, success_cause, failure_cause)` (L1125)
  - `_record_source(source, outcome_state, revenue)` (L1159)
  - `remember_success(skill: str, platform: str, revenue: float)` (L1188) — Remember that a skill was successful on a platform.
  - `get_successful_skills(min_success: int=1, limit: int=20) -> List[dict]` (L1232) — Get skills that have been successful.
  - `update_reputation(platform: str, success: bool, revenue: float=0)` (L1253) — Update platform reputation.
  - `get_platform_reputation(platform: str) -> dict` (L1282) — Get reputation metrics for a platform.
  - `record_win(platform: str, revenue: float=0.0)` (L1308) — A5: a proposal on `platform` was accepted/won. Feeds the win-rate guard.
  - `record_loss(platform: str)` (L1312) — A5: a proposal on `platform` was rejected/lost. Feeds the win-rate guard.
  - `record_attempt(platform: str) -> None` (L1316) — C2 (H39 fix): record that a proposal was *submitted* on `platform`,
  - `get_all_reputations() -> List[dict]` (L1342) — Get reputation for all platforms.
  - `_extract_patterns(opp_id: str, action: str, result: str, success: bool, tags: List[str], revenue: float)` (L1369) — Extract learning patterns from outcomes.
  - `_store_pattern(pattern_type: str, pattern_key: str, success: bool, revenue: float)` (L1386) — Store a pattern in memory.
  - `get_pattern_confidence(pattern_type: str, pattern_key: str) -> float` (L1417) — Get confidence score for a pattern.
  - `record_category_outcome(category: str, success: bool, revenue: float=0.0)` (L1436) — Record an outcome for a category (feeds cold-start priors).
  - `get_category_history(category: str) -> dict` (L1442) — Return {success, failed, total, success_rate, avg_revenue, confidence}.
  - `record_task_type_outcome(task_type: str, success: bool, revenue: float=0.0)` (L1465) — Record an outcome for a task-type (feeds cold-start priors).
  - `get_task_type_history(task_type: str) -> dict` (L1471) — Return {success, failed, total, success_rate, avg_revenue, confidence}.
  - `get_successful_patterns(pattern_type: str, min_confidence: float=0.5) -> List[dict]` (L1494) — Get patterns that have been successful.
  - `get_win_rates_by_platform() -> List[dict]` (L1508) — Return per-platform win-rate summary (reputation-backed).
  - `_agg(rows, value_fn, label_key='key')` (L1534) — Helper: build {value, sample_size, confidence, cold_start} from aggregated rows.
  - `best_performing_task_types(limit: int=10) -> List[dict]` (L1548) — Q: What types of work do I perform best? (success_rate by task_type).
  - `most_reliable_platforms(limit: int=10) -> List[dict]` (L1555) — Q: Which platforms pay me reliably? (success_rate by platform, desc).
  - `highest_net_hourly_categories(limit: int=10) -> List[dict]` (L1562) — Q: Which categories have the highest net hourly return?
  - `time_wasting_categories(limit: int=10) -> List[dict]` (L1571) — Q: Which categories repeatedly waste time? (low/negative net hourly + high effort).
  - `best_proposal_templates(limit: int=10) -> List[dict]` (L1577) — Q: Which proposal variants perform best? (success_rate by variant).
  - `platforms_poor_acceptance(limit: int=10) -> List[dict]` (L1592) — Q: Which platforms have poor acceptance rates? (success_rate asc).
  - `task_types_high_completion(limit: int=10) -> List[dict]` (L1599) — Q: Which task types have high completion rates? (completed/accepted ratio).
  - `profitable_but_often_fail(limit: int=10) -> List[dict]` (L1614) — Q: Which opportunities look profitable but usually fail?
  - `recurring_failure_causes(limit: int=10) -> List[dict]` (L1644) — Q: Which failures have recurring causes? (cause frequency, desc).
  - `reusable_success_strategies(limit: int=10) -> List[dict]` (L1656) — Q: Which successful strategies should be reused? (strategy success_rate desc).
  - `strategies_to_avoid(limit: int=10) -> List[dict]` (L1678) — Q: Which strategies should be avoided? (strategy success_rate asc).
  - `category_outcome_summary(category: str) -> dict` (L1683) — Summarized knowledge for a category (used by decision layer).
  - `get_prediction_accuracy(dim: str='global', value: str='global') -> dict` (L1700) — Aggregate predicted-vs-actual error for a dimension (global/category/platform/task_type).
  - `compute_opportunity_metrics(dim: str='global', value: str='global', now: float=None) -> 'LearningMetrics'` (L1747) — Compute the 11 required metrics for a dimension (global/category/platform/task_type).
  - `compute_all_metrics(dim: str='category') -> List[LearningMetrics]` (L1816) — Compute metrics across all known values of a dimension.
  - `_category_net_hourly() -> List[dict]` (L1829) — Compute net_profit / time_spent_hours aggregated by category from outcome_memory_v2.
  - `get_task_type_history_all() -> List[dict]` (L1849) — All task-type histories (wraps get_task_type_history over distinct keys).
  - `find_similar_opportunities(opp: dict, limit: int=10) -> List[dict]` (L1858) — Find similar opportunities based on learned patterns.
  - `store_learning(learning_type: str, insight: str, confidence: float=0.5)` (L1883) — Store a learned insight.
  - `get_recent_learned(learning_type: str=None, limit: int=10) -> List[dict]` (L1895) — Get recent learned insights.
  - `_update_stats_from_outcome(opp_id: str, success: bool, revenue: float, tags)` (L1918) — Update in-memory stats from an outcome.
  - `get_memory_summary() -> dict` (L1928) — Get a summary of all memory.
  - `clear_expired()` (L1948) — Clear expired memory entries.


### `app/earning_pipeline.py` — earning_pipeline.py — Earning pipeline engine for MrBot1000. (1486L)
> Phase C: stores run_store, lazy strategy_feedback property, SelfImprovementEngine wiring.

**Functions:**
- `_is_affirmative_verification(state) -> bool` (L64) — H-3: True iff the lifecycle `state`'s payment evidence is affirmatively

**Classes:**
- `class Opportunity` (L73)
- `class PipelineResult` (L100)
- `class EarningPipeline` (L108) — Main earning pipeline engine with integrated memory system.
  - `__init__(db_path: str=DB_PATH, memory_path: str=None, log_fn: Callab, ...)` (L111)
  - `close() -> None` (L197) — Release SQLite resources held by the pipeline.
  - `_init_db()` (L216)
  - `_db_execute(sql, params=(), commit=False)` (L256)
  - `discover(sources: List[str]=None, on_found=None, page: int=1, query: str=None) -> List[Opportunity]` (L267) — Run discovery sources and return raw opportunities.
  - `run_discovery_cycle(sources: Optional[List[str]]=None, now: Optional[float]=None) -> dict` (L289) — Self-driving discovery cycle powered by the Dynamic Discovery Scheduler (v2.0.36f).
  - `_record_strategy_outcome(opportunity_id: str, outcome_state: str, revenue=..., cost=..., effort_hours=...) -> None` (L334) — Feed a finalized opportunity outcome into the learning systems.
  - `_feed_self_improvement(opportunity_id: str, outcome_state: str, hist: dict, revenu, ...) -> None` (L377) — Record a finalized outcome into the SelfImprovementEngine (Phase C).
  - `_adapt_to_legacy(o) -> 'Opportunity'` (L422) — Adapt the canonical structured Opportunity to the pipeline's model.
  - `_legacy_to_canonical(o) -> 'CanonicalOpportunity'` (L431) — Adapt the pipeline's legacy Opportunity to the canonical structured model
  - `_intelligence_for(o) -> Optional['EvaluationResult']` (L436) — Run the Opportunity Intelligence Engine on a legacy Opportunity.
  - `_discover_source(source: str) -> List[Opportunity]` (L452) — SECURE: Only valid sources allowed - no dead/external APIs.
  - `_discover_upwork() -> List[Opportunity]` (L489)
  - `_discover_fiverr() -> List[Opportunity]` (L523)
  - `_discover_social() -> List[Opportunity]` (L546) — Discover opportunities from social platforms (Reddit, Twitter, LinkedIn, etc.).
  - `_discover_airdrops() -> List[Opportunity]` (L570)
  - `_discover_defi() -> List[Opportunity]` (L594)
  - `_discover_microtasks() -> List[Opportunity]` (L630)
  - `_discover_content() -> List[Opportunity]` (L652) — LEGACY: previously returned 3 hardcoded static entries (Mirror.xyz,
  - `_discover_dynamic() -> List[Opportunity]` (L661)
  - `evaluate(opportunities: List[Opportunity]) -> List[Opportunity]` (L689) — Score opportunities using Ollama or heuristics.
  - `strategy_feedback()` (L734) — Lazy StrategyFeedback: run outcomes -> per-platform stats (Phase C).
  - `self_improvement()` (L763) — Lazy SelfImprovementEngine: learns from VERIFIED outcomes (Phase C).
  - `_sync_to_portfolio(opp: Opportunity) -> None` (L784) — Create/update a PortfolioEntry from an evaluated opportunity (deterministic).
  - `_evaluate_opportunity(opp: Opportunity) -> Opportunity` (L792)
  - `filter(opportunities: List[Opportunity], max_risk: str='medium', m, ...) -> List[Opportunity]` (L802)
  - `_apply_memory_boost(opp, platform_reps)` (L876) — Apply memory-based boosts and penalties to opportunity scoring.
  - `execute(opportunity: Opportunity) -> PipelineResult` (L901) — Execute an opportunity action.
  - `_execute_airdrop(opp: Opportunity) -> PipelineResult` (L913)
  - `_execute_defi(opp: Opportunity) -> PipelineResult` (L921)
  - `_execute_microtask(opp: Opportunity) -> PipelineResult` (L927)
  - `_execute_simple(opp: Opportunity) -> PipelineResult` (L933) — Execute simple opportunities like referrals and faucets.
  - `_record_ramp_submission(opp) -> None` (L953) — C2 (H39 fix): record that a proposal was *submitted* on opp.platform.
  - `submit_gig_proposal(opp: Opportunity, draft: str, reviewer=None, confirm_cb=None, client=None) -> PipelineResult` (L967) — Submit a gig proposal through the review + human-confirm gate.
  - `record_realized_gas(chain: str, usd: float, note: str='') -> None` (L1125) — B4: record realized on-chain gas cost into the wallet gas ledger.
  - `get_revenue_report(days: int=30) -> dict` (L1138)
  - `get_memory_summary() -> dict` (L1206) — Get memory system summary for dashboard.
  - `get_platform_reputation(platform: str) -> dict` (L1210) — Get reputation for a specific platform.
  - `get_successful_skills(min_success: int=1) -> List[dict]` (L1214) — Get skills that have been successful.
  - `run_full_cycle(sources: List[str]=None, max_risk: str='medium') -> PipelineResult` (L1220) — Run complete discovery → evaluate → filter → execute cycle (legacy 4-stage).
  - `run_autonomous_loop(sources: List[str]=None, max_risk: str='medium', max_opportunities: int=10) -> dict` (L1257) — Run the unified 24-stage autonomous planning loop.
  - `load_memory(limit: int=1000) -> List[dict]` (L1307) — Load all stored opportunities into cache.
  - `get_opportunities_by_type(opp_type: str, limit: int=50) -> List[dict]` (L1315) — Get all opportunities of a specific type.
  - `get_recent_outcomes(limit: int=20) -> List[dict]` (L1319) — Get most recent outcomes.
  - `get_platform_reputations() -> List[dict]` (L1323) — Get reputation for all platforms.
  - `track_opportunity(opportunity: Opportunity, stage: str, note: str='', amount: float=0.0)` (L1327) — Update an opportunity's lifecycle state.
  - `_record_ramp_real_outcome(opportunity, accepted=..., verified=..., verified_amount=...) -> None` (L1421) — Record a *real* accept/reject into the submission ramp reputation,
  - `build_workflow_plan(opportunity: Opportunity)` (L1455) — Create a concrete execution plan for an opportunity.
  - `get_recent_learned(learning_type: str=None, limit: int=10) -> List[dict]` (L1462) — Get recent learned insights.
  - `search_opportunities_by_keyword(keyword: str, limit: int=20) -> List[dict]` (L1466) — Search opportunities by keyword in title/description.
  - `get_opportunity_stats() -> dict` (L1478) — Get statistics about discovered opportunities.


### `app/effects.py` — Visual effects engine (v2.0.26). (208L)

**Functions:**
- `style_hints_qss(fx: EffectSettings, theme: dict) -> str` (L88) — QSS fragment for effects that Qt's stylesheet engine actually supports.
- `apply_shadow(widget, theme: dict, fx: EffectSettings, radius: int=12, blur: int=18)` (L157) — Attach a soft drop shadow to a widget (button/card). No-op if disabled.
- `apply_antialiasing(app) -> None` (L195) — Enable high-DPI + antialiasing hints on the QApplication (cheap, safe).

**Classes:**
- `class EffectSettings` (L21)
  - `from_env(env: dict | None=None) -> 'EffectSettings'` (L34)
  - `effective() -> 'EffectSettings'` (L58) — Apply the quality-mode master switch: Performance flattens everything.
  - `to_env_dict() -> dict` (L75)


### `app/environment.py` — Guarded environment-file persistence for the application layer. (160L)

**Functions:**
- `_read_env_lines(path: Path) -> list[str]` (L16)
- `env_file_path() -> Path` (L30) — Return the live `.env` path, honoring the test isolation override.
- `clean_env_value(value: str) -> str` (L36) — Return an env value with any trailing inline comment removed.
- `_env_write_refusal() -> str` (L70) — Return a refusal reason, or an empty string when writes are allowed.
- `set_env_values(values: dict, path=...) -> bool` (L80) — Persist values atomically while preserving unknown keys and comments.

**Classes:**
- `class EnvWriteRefused(RuntimeError)` (L26) — Raised when a `.env` write is refused by test isolation policy.


### `app/library.py` — agents/library.py — Shared utility library for all MrBot1000 agent workers. (139L)
> TokenBucket has try_acquire non-blocking variant (Phase F).

**Functions:**
- `retry_llm(max_attempts: int=3, backoff: float=1.5, exceptions=(Exception,))` (L95) — Decorator that retries an LLM-calling function with exponential back-off.

**Classes:**
- `class TokenBucket` (L38) — Thread-safe token-bucket rate limiter.
  - `__init__(rate: float=1.0, capacity: float=5.0)` (L48)
  - `acquire(tokens: float=1.0)` (L55)
  - `try_acquire(tokens: float=1.0, timeout: float=0.0) -> bool` (L69) — Non-blocking acquire.


### `app/provider_models.py` — Cloud-provider model discovery + pricing for the Settings tab. (637L)

**Functions:**
- `classify_model_band(params_billion: Optional[float], moe=..., active_params_billion=...) -> str` (L137) — Classify a model by runtime-relevant parameter count.
- `infer_model_parameters(model_id: str) -> tuple[Optional[float], Optional[float]]` (L162) — Infer total and active MoE parameters from a model identifier.
- `_enrich_size_metadata(models: list[ModelInfo]) -> list[ModelInfo]` (L182) — Fill missing size metadata from explicit model-id notation.
- `_price_for(model_id: str) -> tuple[Optional[float], Optional[float]]` (L247) — Longest-prefix match against the static pricing table.
- `_arch_hint_for(model_id: str) -> dict` (L291) — Best-effort static architecture hint from the id prefix.
- `get_arch_info(model_id: str, live=...) -> dict` (L301) — Return architecture metadata for `model_id`.
- `is_moe(model_id: str, live=...) -> bool` (L364) — Convenience: True if the model is a Mixture-of-Experts architecture.
- `_cache_key(provider: str, base_url: str) -> str` (L380)
- `_load_cache() -> dict` (L384)
- `_save_cache(data: dict) -> None` (L392)
- `_get_json(url: str, headers: dict, timeout: int=15) -> Optional[dict]` (L405)
- `_from_openrouter(base_url: str, api_key: str) -> list[ModelInfo]` (L415)
- `_from_openai_compatible(base_url: str, api_key: str, vendor: str='') -> list[ModelInfo]` (L446) — Works for OpenAI, Gemini (OpenAI-compat base), Groq, DeepSeek, Mistral,
- `_from_anthropic() -> list[ModelInfo]` (L490)
- `_nvidia_free_models() -> list[ModelInfo]` (L499) — Curated NVIDIA NIM free-tier fallback (build.nvidia.com).
- `is_fetchable(provider: str) -> bool` (L566)
- `fetch_models(provider: str, api_key: str, base_url: str='', use_cache: bool=True) -> list[ModelInfo]` (L570) — Return models for a provider. Returns [] on any failure (caller falls
- `clear_cache(provider: str='', base_url: str='') -> None` (L624) — Drop cached models (e.g. after a manual refresh).

**Classes:**
- `class ModelInfo` (L41)
  - `arch_label() -> str` (L59)
  - `params_label() -> str` (L67)
  - `size_band() -> str` (L74) — Return the runtime-oriented model band used by role guidance.
  - `size_label() -> str` (L83) — Display total size and the active MoE size when they differ.
  - `price_out_display() -> str` (L94)
  - `combo_text() -> str` (L106)
  - `tooltip() -> str` (L116)


### `app/startup_validation.py` — (no module docstring) (94L)

**Functions:**
- `validate_startup_environment(env: Optional[Dict[str, str]]=None, log_fn: Optional[Callable[[str], None]=None) -> StartupValidationReport` (L16) — Validate runtime prerequisites and return a structured startup report.

**Classes:**
- `class StartupValidationReport` (L8)


### `app/text_utils.py` — Shared text and serialization helpers without package side effects. (54L)

**Functions:**
- `truncate(text: str, max_chars: int, ellipsis: str='…') -> str` (L12)
- `fingerprint(text: str) -> str` (L18)
- `ts_now() -> str` (L22)
- `word_count(text: str) -> int` (L26)
- `extract_code_blocks(text: str) -> List[str]` (L30)
- `strip_code_fences(text: str) -> str` (L34)
- `safe_json_loads(text: str, default=None)` (L38)


### `app/theme_config.py` — (no module docstring) (213L)

**Functions:**
- `_fill(theme: dict) -> dict` (L32) — Ensure every token is present and non-empty, deriving new ones from legacy keys.
- `_lerp_color(a: str, b: str, t: float) -> str` (L67) — Linear-interpolate two #rrggbb colors; t=0 -> a, t=1 -> b.
- `resolve_theme_definition(theme_name: str, env=None) -> dict` (L85) — Return a complete theme definition for a builtin preset or the custom theme.
- `save_custom_theme(theme_values: dict, env=None, env_path: str | None=None) -> dict` (L198) — Persist custom theme colors to the environment and .env file.


### `app/ui.py` — ui.py — Enhanced UI v4: separated thought windows, richer sprites, (89L)

**Functions:**
- `ui_style(widget, restyle_fn)` (L45) — Apply a TH()-token stylesheet AND register it for live re-styling.
- `restyle_ui()` (L58) — Re-apply every registered tokenized stylesheet (call on theme change).
- `set_ui_theme(theme: dict)` (L67)
- `set_effects(animations=...)` (L80) — Toggle whether ui.py draws particle/gear animations.
- `TH(key: str, fallback: str='#888888') -> str` (L86)


### `app/version.py` — MrBot1000 public release version. (5L)


---

### `main.py` — MrBot1000 Desktop Application entry point

### `main.py` — main.py - MrBot1000 Desktop Application (3508L)

**Functions:**
- `_sanitize_sys_path()` (L46)
- `_ensure_qt_font_directory()` (L108) — Point Qt at the system font directory when PySide6's bundled folder is missing.
- `validate_clipboard_json(text: str) -> tuple[bool, dict | None, str]` (L240) — SECURE: Validate clipboard JSON content.
- `_log_html(ts: str, severity: str, msg: str, color: str) -> str` (L344) — Render one log entry as safe HTML for the live-log QTextEdit.
- `_contrast(hex_color: str) -> str` (L364) — Return '#000000' or '#ffffff' for readable text on a bg color.
- `_log_shutdown_warning(worker) -> None` (L378) — Note a worker that did not stop within the grace period.

**Classes:**
- `class HttpWorker(QThread)` (L271)
  - `__init__(method, url, tag, **kwargs)` (L274)
  - `run()` (L281)
- `class PipelineWorker(QThread)` (L295) — Run the (network-bound) earning pipeline OFF the GUI thread so the app
  - `__init__(sources, max_risk, db_path, log_fn)` (L302)
  - `run()` (L309)
- `class ModelFetchWorker(QThread)` (L319) — Fetch cloud-provider models (w/ pricing) OFF the GUI thread.
  - `__init__(provider: str, api_key: str, base_url: str)` (L326)
  - `run()` (L332)
- `class MainWindow(TabBuildersMixin, QMainWindow)` (L395)
  - `__init__()` (L403)
  - `_check_dependencies()` (L618) — Import every package pinned in requirements.txt; warn (never crash) on
  - `_validate_model_config(main_model: str | None, chat_model: str | None)` (L668) — Emit clear startup warnings about model configuration problems.
  - `shutdown()` (L687) — Tear down worker threads and DB cleanly (idempotent).
  - `_disconnect_worker_signals(worker)` (L729) — Disconnect every signal on a stopping worker from its GUI receivers.
  - `_stop_tab_background_threads()` (L803) — Stop QThread/QTimer resources owned by lazily-built tab widgets.
  - `_stop_orphan_tab_threads(tabs)` (L841) — Stop any QThread still running inside a tab widget's subtree.
  - `closeEvent(event)` (L890)
  - `_shutdown_ollama()` (L894)
  - `_on_bus_event(msg)` (L920) — Surface structured bus events in the GUI.
  - `_on_approval_queue_change(item)` (L941) — Called when an approval item is enqueued. Refresh GUI panels.
  - `_refresh_approval_panel_and_alert()` (L948) — Refresh the approval list and its tab-level alert on the GUI thread.
  - `_on_approval_decided(item_id, status, notes)` (L955) — Refresh the approval tab alert after a human decision.
  - `_execute_approved_action(item)` (L991) — Run an approved ACTION item's tool, re-reading the queue decision.
  - `_execute_approved_submission(item)` (L1053) — Send an approved SUBMISSION via the Earning tab's submitter.
  - `_refresh_approval_alert()` (L1090) — Update the Approvals tab label, color, and pending-count tooltip.
  - `_tab_index_by_label(label)` (L1111) — Find a tab by its stable base label, ignoring an alert count suffix.
  - `_on_event_logged(event)` (L1121) — Called when an event is logged. Evaluate alerting rules.
  - `_on_provider_config_changed(changes: dict)` (L1130) — Handle provider configuration changes at runtime (no restart needed).
  - `_safe_log(msg: str)` (L1154)
  - `_replay_log_buffer()` (L1162) — Push all buffered log entries into the (now built) log_table widget.
  - `_append_log_to_table(entry)` (L1188) — Append a single log entry to the log table widget.
  - `_show_log_details()` (L1239) — Show full details of the selected log entry in the details panel.
  - `_export_logs()` (L1264) — Export the current log buffer to a text file.
  - `_append_log(msg: str, source: str='', category: str='', details: str='')` (L1279)
  - `_set_log_auto_scroll(checked: bool)` (L1362)
  - `_apply_log_filter()` (L1366)
  - `_do_apply_log_filter()` (L1378)
  - `_clear_log()` (L1397)
  - `create_ui()` (L1402)
  - `_maybe_auto_start_servers()` (L1511) — Deferred hook: delegate to the Providers & GPU tab's auto-start.
  - `_start_self_improve_monitor()` (L1524) — Start the background post-apply monitor for self-improvement.
  - `_run_self_improve_monitor()` (L1549) — Re-verify applied patches; queue new gated proposals on regression.
  - `_size_for_screen()` (L1566) — Choose a usable initial size on the current display.
  - `_set_window_mode(mode: str, persist: bool=True)` (L1597) — Switch presentation mode without rebuilding or reparenting the UI.
  - `_log(msg)` (L1631) — Write a log line to the Providers & GPU tab if available.
  - `_toggle_pause(checked)` (L1644)
  - `_human_send(text: str)` (L1648)
  - `_build_payout_verifier()` (L1654)
  - `_verify_and_mark_paid()` (L1661) — GUI: verify a payout (on-chain or manual ref) before marking paid.
  - `_build_upwork_client()` (L1745) — Construct an UpworkClient from .env creds (or None if absent).
  - `_build_reviewer()` (L1761)
  - `_review_proposal_draft()` (L1768) — Run the review gate on the current draft + job description and show the result.
  - `_submit_proposal_gui()` (L1784) — GUI entry: review gate -> human confirm -> submit via pipeline (records lifecycle).
  - `_on_proposal_submitted(job_id, result)` (L1858)
  - `_format_ago(seconds: float) -> str` (L1874) — Format seconds as human-readable 'ago' string.
  - `_apply_llm_budget(text: str)` (L1887) — A4: apply the daily LLM budget cap live (no restart).
  - `_apply_winrate(text: str)` (L1897) — A5: apply the win-rate auto-decline threshold live (percent, no restart).
  - `select_research_folder()` (L1907)
  - `force_safe_improve()` (L1915)
  - `force_research_rescan()` (L1920)
  - `clear_file_cache()` (L1925)
  - `_refresh_cache_stats()` (L1935) — Update the cache statistics label in the Settings tab.
  - `refresh_db_stats()` (L1960) — Refresh DB Stats tab with data from app.database.
  - `_refresh_review_queue()` (L2059) — Populate the review queue list + counts from the instruction gate.
  - `_review_selected(approve: bool)` (L2078) — Human-in-the-loop decision on the selected pending instruction.
  - `_run_http(method, url, tag, **kwargs)` (L2114)
  - `_on_http_result(tag: str, response)` (L2123)
  - `refresh_balance()` (L2152) — Shows wallet address as balance display.
  - `manual_payout()` (L2167) — SECURE: Requires triple confirmation for any payout action.
  - `_run_earning_cycle()` (L2224)
  - `_on_cycle_finished(result)` (L2245)
  - `_on_cycle_error(errmsg)` (L2262)
  - `_refresh_earnings_dashboard()` (L2271)
  - `register_autonomous()` (L2277)
  - `test_api_connection()` (L2291)
  - `_role_enabled(role_combo) -> tuple[bool, bool]` (L2349) — Map a Role combo ('Both'/'Main only'/'Chat only'/'Disabled') to
  - `_fetch_provider_models(provider: str, combos, key_edit, base_edit)` (L2370) — Fetch a cloud provider's models (w/ pricing) into the model combos.
  - `_drop_fetch_worker(worker)` (L2407)
  - `_on_models_fetched(provider: str, combos, models)` (L2411)
  - `_refresh_model_info(live=False)` (L2435) — v2.0.34ab (F6): populate the Model Info panel for the selected main + chat models.
  - `_copy_model_info_to_clipboard()` (L2475) — Copy the model info text to clipboard.
  - `_fetch_ollama_models() -> list[str]` (L2483) — Best-effort fetch of locally-installed Ollama models from the running
  - `refresh_ollama_models()` (L2502) — Refresh Ollama models in a background thread to avoid GUI freeze.
  - `_on_ollama_refreshed(models)` (L2522) — Handle Ollama model refresh completion (GUI thread).
  - `populate_ollama_model_combos()` (L2546) — v2.0.34al: silently populate the Settings model dropdowns from the
  - `save_settings()` (L2593)
  - `_save_provider_list()` (L2953) — Write providers.json-style provider config (no secrets).
  - `_settings_snapshot() -> dict` (L2994) — Capture provider-relevant env values for restart-diffing.
  - `_settings_require_restart(prev: dict) -> bool` (L3028)
  - `_prompt_restart()` (L3050) — Warn that a restart is required and offer to restart now.
  - `restart_app()` (L3066) — Cleanly relaunch the application in-place.
  - `_on_pipeline_validated(action, result)` (L3090)
  - `_on_pipeline_executed(action, result)` (L3097)
  - `_on_pipeline_rejected(action, reason)` (L3103)
  - `_validate_clipboard_code()` (L3108) — Quick-validate whatever code is in the clipboard.
  - `apply_theme(theme_name: str, fx_override=None)` (L3127)
  - `_t(key: str, fallback: str='#888888') -> str` (L3234) — Resolve a theme color token for widget-level styling (Phase E).
  - `_restyle_themeable()` (L3242) — Re-apply theme tokens to statically-styled widgets on theme change.
  - `_apply_shadow_effects(theme: dict, fx)` (L3256) — Apply or clear the soft-shadow effect on container widgets.
  - `_open_theme_customizer(current_theme: str)` (L3286) — Open per-area color pickers for the Custom theme, with live preview.
  - `_apply_custom_live(vals: dict)` (L3405) — Persist + apply a custom-theme preview immediately (real-time).
  - `_apply_effects_now()` (L3419) — Re-apply theme using the LIVE effect-toggle state (not the persisted
  - `_build_effect_settings(fx_override=None)` (L3451)


---

## Non-Python support files (skills / scripts / prompts / docs / config)

### skills/ — agent skill documents (the brains read these)
> Repo-local curated skills. NOTE: any *platform* SKILL.md fetched at runtime is
> UNTRUSTED data per the security policy (`agents/safety/instructions.py`); these are curated.
- **skills/document-qa.md** — Document Q&A skill.
- **skills/job-execution-plan.md** — Job-execution-planning skill.
- **skills/moltbook-agent.md** — Moltbook agent onboarding skill (mirrors moltbook_agent.py).
- **skills/opportunity-evaluation.md** — Opportunity-evaluation skill.
- **skills/opportunity-execution.md** — Opportunity-execution skill.
- **skills/opportunity-filtering.md** — Opportunity-filtering skill.
- **skills/opportunity-lifecycle.md** — Opportunity-lifecycle skill.
- **skills/social-discovery.md** — Social-discovery skill.

### scripts/ — brain launchers (PowerShell / BAT)
- **scripts/launch_llamacpp_brain.ps1** — Shared llama.cpp launcher for brain roles (Big/Small); canonical programmatic launch.
- **scripts/start_big_brain_llamacpp.ps1** — Start Big Brain via llama.cpp (`-Role Big`).
- **scripts/start_small_brain_llamacpp.ps1** — Start Small Brain via llama.cpp (`-Role Small`).
- **scripts/start_small_brain_ollama.ps1** / **.bat** — Start Small Brain via Ollama (Ollama disabled on this box — legacy).
- **scripts/launch_lm_studio.ps1** / **.bat** — Launch LM Studio with the 5060 Ti only (hides the 1660 Super).
- **scripts/start_dual_brain.ps1** — Start LM Studio for dual-brain GPU isolation.

### prompts/ — brain persona prompts
- **prompts/big_brain.txt** — Big-brain system/persona prompt (Edward Hurst).
- **prompts/small_brain.txt** — Small-brain system/persona prompt (Jacob Stanley).

### docs/ — project documentation
- **docs/MAINTENANCE_PLAN_2026-10-12.md** — Maintenance plan (Phases A–G tracked here).
- **docs/MODEL_RECOMMENDATIONS.md** — Per-model recommended llama.cpp settings (Phase G4).
- **docs/PHASE_C_AUDIT.md** — Phase C audit (outcome-loop closure).
- **docs/PHASE_D_AUDIT.md** — Phase D audit (agent tooling gaps).
- **docs/codemap/** — This codebase map.

### root config / meta files
- **.gitignore** — Gotcha (memory): `_*.py` once matched every `__init__.py`; fixed with `!__init__.py`.
- **.gitattributes** — Line-ending/attribute config.
- **.env.example** — Env template (secrets masked; never overwrite live `.env`).
- **requirements.txt** / **requirements.lock.txt** — Dependencies + lock.
- **CHANGELOG.md** — Version history (v2.1.x chain).
- **ARCHITECTURE_MAP.md** — High-level architecture map.
- **README.md** / **OPERATIONS.md** / **Agent.md** / **RELEASE_CHECKLIST.md** / **DEADCODE_REPORT.md** — Readme, ops runbook, agent contract, release checklist, deadcode report.
- **Skill.md** — Root skill/agent instructions (excluded from publish mirror; untrusted at runtime).
- **schedule_prompt.md** — Scheduled-cron prompt content.
- **run_lead_routine.py** — Lead-generation routine entry point (excluded from publish mirror).
