<!-- generated 39 files -->

### `agents/services/__init__.py` — services package. (2L)


### `agents/services/analyst_worker.py` — analyst_worker.py — Proposal quality metrics analysis for MrBot1000 (338L)

**Classes:**
- `class ProposalMetrics` (L19) — Metrics collected from a code/proposal analysis.
- `class AnalystWorker(WorkerAgent)` (L33) — AnalystWorker — Analyzes code quality, proposal metrics, and winning rate drivers.
  - `__init__(api_key: str, log_signal, db=None)` (L46)
  - `analyze_proposal(proposal_text: str, proposal_id: str=None) -> ProposalMetrics` (L53) — Analyze a proposal and return quality metrics.
  - `_generate_recommendations(clarity: float, structure: str, bugs: List[str], missing: List[str]) -> List[str]` (L151) — Generate actionable improvement recommendations.
  - `evaluate_job_listing(job_record: dict, reputation: Optional[dict]=None) -> dict` (L172) — Evaluate a job listing for proposal quality potential.
  - `_assess_job_clarity(title: str, description: str) -> float` (L246) — Assess how clear a job listing's requirements are.
  - `generate_metrics_report() -> dict` (L272) — Generate a comprehensive report on proposal quality metrics.
  - `clear_metrics()` (L318) — Clear stored metrics.
  - `run_analysis_cycle(proposals: List[dict]) -> List[ProposalMetrics]` (L324) — Analyze a batch of proposals and return metrics.


### `agents/services/application_services.py` — Non-Qt application service factories used by the desktop composition root. (55L)

**Functions:**
- `build_earning_services(root_folder: str, portfolio_path=..., log_fn=...) -> EarningServices` (L36) — Build the canonical earning services without importing Qt.

**Classes:**
- `class EarningServices` (L11) — Shared earning services owned by one application process.
  - `pipeline() -> Any` (L17)
  - `portfolio() -> Any` (L21)
  - `run_store() -> Any` (L25)
  - `code_patch_service() -> Any` (L29)
  - `close() -> None` (L32)


### `agents/services/autonomous_loop.py` — agents/services/autonomous_loop.py — Phase 2: structured explanations + explanation builder. (1088L)
> Phase C SelfImprovementEngine + StrategyFeedback wired through its outcome callback.

**Classes:**
- `class StageResult` (L20)
- `class StageStatus` (L29)
- `class AutonomousResult` (L38)
  - `to_dict() -> Dict[str, Any]` (L53)
- `class ExplanationBuilder` (L78) — Builds structured, evidence-based explanations for decisions.
  - `__init__(stages: List[StageResult], facts: Any, decision: str, reason: str)` (L104)
  - `build() -> str` (L110) — Build the full explanation string.
  - `_build_proceed() -> str` (L120) — Build explanation for accepted opportunities.
  - `_build_reject() -> str` (L229) — Build explanation for rejected opportunities.
  - `_build_await() -> str` (L305) — Build explanation for approval-required opportunities.
  - `_get_stage_data(stage_name: str) -> Dict[str, Any]` (L324) — Get data dict from a specific stage result.
- `class AutonomousLoop` (L337) — Drives the unified 24-stage planning loop for a single opportunity.
  - `__init__(pipeline: Any, run_store: Any=None)` (L344)
  - `cancel(opportunity_id: str) -> bool` (L369) — Request cancellation of a queued or running opportunity.
  - `_check_limits(opportunity_id: str, started: float) -> None` (L375)
  - `run(opportunity: Any, facts: Any=None) -> AutonomousResult` (L384) — Run one opportunity subject to configured concurrency limits.
  - `_run(opportunity: Any, facts: Any=None) -> AutonomousResult` (L400) — Run the full 24-stage loop for a single opportunity.
  - `_stage_discovered(result, opp, facts)` (L489)
  - `_stage_deduplicate(result, opp, facts)` (L498)
  - `_stage_classify(result, opp, facts)` (L542)
  - `_stage_evaluate(result, opp, facts)` (L551)
  - `_stage_check_memory(result, opp, facts)` (L565)
  - `_stage_check_reputation(result, opp, facts)` (L578)
  - `_stage_check_skill_fit(result, opp, facts)` (L590)
  - `_stage_check_economics(result, opp, facts)` (L598)
  - `_stage_check_risk(result, opp, facts)` (L610)
  - `_stage_prioritize(result, opp, facts)` (L618)
  - `_stage_plan(result, opp, facts)` (L634)
  - `_stage_request_approval(result, opp, facts)` (L642) — Pause the loop for opportunities above the financial-exposure threshold.
  - `_stage_execute(result, opp, facts)` (L671)
  - `_stage_validate(result, opp, facts)` (L713)
  - `_stage_submit(result, opp, facts)` (L748)
  - `_stage_wait(result, opp, facts)` (L788)
  - `_stage_verify(result, opp, facts)` (L793)
  - `_stage_account(result, opp, facts)` (L845)
  - `_stage_learn(result, opp, facts)` (L875)
  - `_stage_rerank(result, opp, facts)` (L901)
  - `_finalize(result, facts, t0, decision, reason)` (L928)
  - `_persist_run(result: 'AutonomousResult', facts: Any) -> None` (L947) — Persist a finished run to the durable store (optional, best-effort).
  - `_replay_guard(opp_id: str) -> bool` (L969) — True when this opportunity already made an irreversible commitment.
  - `_begin_run(result: 'AutonomousResult', opp_id: str) -> None` (L994) — Write the in-flight run row before stage 1.
  - `_mark_irreversible(result: 'AutonomousResult', opp_id: str) -> None` (L1015) — Mark the idempotency key once an irreversible action has been sent.
  - `_sync_final_state(result: AutonomousResult, facts: Any) -> None` (L1032) — Sync the loop's final decision to the lifecycle and portfolio.
  - `_get_opp_from_facts(facts: Any)` (L1079) — Extract opportunity from facts store.


### `agents/services/autonomous_run_store.py` — agents/autonomous_run_store.py — Durable autonomous-run ledger (v2.1). (264L)

**Classes:**
- `class _ClosingConnection` (L35) — SQLite connection whose context-manager exit also releases resources.
- `class AutonomousRunStore` (L45) — Thread-safe, append-friendly SQLite ledger for autonomous runs.
  - `__init__(db_path: str)` (L48)
  - `_conn() -> sqlite3.Connection` (L53)
  - `_managed_conn()` (L59) — Commit or roll back transactions, then always close the connection.
  - `_init_db() -> None` (L68)
  - `_json(obj: Any) -> str` (L117)
  - `save_run(run: Any, opportunity_id: str, model_metadata: Optional[Dic, ...) -> str` (L120) — Persist an AutonomousResult (or any object with a to_dict()/attrs).
  - `update_run_status(run_id: str, status: str, decision: Optional[str]=None, reason: Optional[str]=None) -> None` (L174)
  - `_summarize(data: Any, limit: int=160) -> str` (L191)
  - `is_idempotent(key: str) -> bool` (L200)
  - `mark_idempotent(key: str, run_id: str, opportunity_id: str) -> None` (L206)
  - `get_run(run_id: str) -> Optional[Dict[str, Any]]` (L215)
  - `list_runs(limit: int=50) -> List[Dict[str, Any]]` (L221)
  - `count() -> int` (L228)
  - `_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]` (L233)
  - `recover_incomplete(terminal: str='FAILED', reason: str='interrupted by rest) -> int` (L245) — Mark any non-terminal run as failed (restart safety). Returns count.


### `agents/services/cli_interface.py` — agents/cli_interface.py — Phase 6: CLI interface for MrBot1000 2.0. (214L)

**Functions:**
- `load_state(path: str=STATE_FILE) -> CLIState` (L34)
- `save_state(state: CLIState, path: str=STATE_FILE) -> None` (L45)
- `cli(ctx, verbose: bool)` (L56) — MrBot1000 2.0 — Dual-Brain Autonomous Earning Agent.
- `status(ctx)` (L72) — Show current system status.
- `scan(ctx, strategy: str, platform: str, query: str)` (L86) — Scan for opportunities.
- `evaluate(ctx, id: str, strategy: str)` (L108) — Evaluate an opportunity.
- `execute(ctx, id: str, dry_run: bool)` (L129) — Execute an opportunity (human-gated).
- `wallet(ctx)` (L151) — Show wallet status.
- `register(ctx, chain: str, name: str, approved: bool)` (L166) — Register on-chain identity (ERC-8004).
- `history(ctx)` (L183) — Show command history.
- `clear(ctx)` (L195) — Clear CLI state and history.
- `main()` (L207) — Entry point for the CLI.

**Classes:**
- `class CLIState` (L26) — Persisted CLI state.


### `agents/services/code_patch_service.py` — agents/code_patch_service.py — Approval-gated, rollback-safe code patching. (408L)

**Classes:**
- `class CodePatch` (L41) — A proposed file patch, approval-gated at every mutation step.
- `class CodePatchService` (L58) — Owns the backup/apply/verify/rollback lifecycle for approved patches.
  - `__init__(approval_queue: Any=None, root_dir: Optional[str]=None, bac, ...)` (L61)
  - `mark_in_use(target_or_module: str) -> None` (L88) — Record that a file (path or dotted module) is currently loaded/used.
  - `mark_free(target_or_module: str) -> None` (L94)
  - `_resolve_for_inuse(target_or_module: str) -> str | None` (L99)
  - `_in_use(target: str) -> bool` (L117)
  - `register_module(dotted: str, file_path: str) -> None` (L120) — Map a loaded module path to its file so apply knows it is in use.
  - `drain() -> list[dict]` (L125) — Apply all queued patches whose target is no longer in use.
  - `propose(patch: CodePatch) -> CodePatch` (L154) — Register the patch and enqueue it as an approval item.
  - `_is_approved(patch_id: str) -> bool` (L188) — True only when the exact approval item carrying this patch is APPROVED.
  - `_assert_patchable(patch: CodePatch) -> None` (L198)
  - `backup(target: str) -> str` (L233) — Copy target to the backup dir with a timestamp; return backup path.
  - `verify(patch: CodePatch) -> tuple[bool, str]` (L244) — Run the enabled verification for this patch. Never shells out.
  - `apply_approved(patch: CodePatch, approval_id: str='', skip_queue: bool=False) -> dict[str, Any]` (L260) — Backup -> write -> verify -> rollback-on-fail, only if approved.
  - `applied_patches() -> list[dict]` (L334) — Snapshot of the post-apply ledger (newest first).
  - `monitor_applied() -> list[CodePatch]` (L340) — Re-verify every applied patch; emit a new gated proposal on regression.
  - `_rollback(backup_path: str, target: str) -> bool` (L396) — Restore the exact original bytes from the backup.


### `agents/services/coder.py` — MrBot1000/agents/coder.py — Coder Worker Agent (213L)

**Classes:**
- `class CoderWorker(WorkerAgent)` (L23) — Coder Agent: Analyzes code problems and performs actual file modifications.
  - `__init__(api_key: str, log_signal=None, db=None)` (L49)
  - `_codebase_context() -> str` (L54)
  - `analyze_and_fix(file_path: str, issue_description: str) -> dict` (L60) — Analyze a file and implement fixes (real write).
  - `file_write(file_path: str, content: str, verify: bool=True) -> dict` (L154) — Write content to a file with optional validation.
  - `refactor(file_path: str, refactor_instructions: List[str]) -> dict` (L179) — Apply refactoring instructions to a file (real write).


### `agents/services/mrbot_cli.py` — mrbot_cli — read-only CLI for inspecting a live or offline MrBot1000 runtime. (502L)

**Functions:**
- `read_env() -> Dict[str, str]` (L54) — Read whitelist-sanitized .env values. Secrets never leave this function.
- `pretty_env(env: Dict[str, str]) -> str` (L73)
- `probe_models(port: int, timeout_s: float=4.0) -> Tuple[bool, str, List[Dict[str, Any]]]` (L88) — Return (is_running, model_id_or_empty, raw_entries).
- `device_from_env(env: Dict[str, str], which: str) -> str` (L101)
- `gpu_mem_info() -> Dict[str, str]` (L107) — Best-effort GPU memory from nvidia-smi, per device index.
- `cmd_providers(args)` (L125)
- `cmd_models(args)` (L207)
- `cmd_dialogue(args)` (L244) — Read the most recent DialogueTab state from the SQLite evidence store.
- `cmd_db_stats(args)` (L334)
- `cmd_logs(args)` (L386)
- `cmd_health(args)` (L411)
- `main(argv: Optional[List[str]]=None) -> int` (L475)


### `agents/services/self_audit.py` — agents/self_audit.py — Self-Audit & Continuous-Improvement Layer (v2.0.36j-T4). (692L)

**Classes:**
- `class AuditCategory(str, Enum)` (L32)
- `class Severity(str, Enum)` (L51)
- `class AuditFinding` (L62) — A structured improvement recommendation.
  - `to_dict() -> dict` (L82)
- `class AuditReport` (L107) — Complete audit results.
  - `critical_count() -> int` (L116)
  - `high_count() -> int` (L120)
  - `by_category(cat: AuditCategory) -> List[AuditFinding]` (L123)
  - `to_dict() -> dict` (L126)
- `class SelfAuditEngine` (L141) — Analyzes engine data to produce improvement recommendations. Pure analysis — no mutations.
  - `__init__(memory: Any, evidence_store: Any=None, accounting: Any=None, config: Optional[Dict]=None)` (L144)
  - `run_audit() -> AuditReport` (L161) — Run the full self-audit and return a report.
  - `_audit_repeated_failures(report: AuditReport) -> None` (L184) — Identify opportunities with repeated failure patterns.
  - `_audit_prediction_errors(report: AuditReport) -> None` (L220) — Identify systematic prediction errors.
  - `_audit_bad_strategies(report: AuditReport) -> None` (L273) — Identify search strategies with poor performance.
  - `_audit_poor_platforms(report: AuditReport) -> None` (L327) — Identify platforms with consistently poor outcomes.
  - `_audit_poor_categories(report: AuditReport) -> None` (L358) — Identify opportunity categories with poor performance.
  - `_audit_poor_task_types(report: AuditReport) -> None` (L388) — Identify task types with poor performance.
  - `_audit_low_performing_variants(report: AuditReport) -> None` (L419) — Identify low-performing proposal variants.
  - `_audit_high_cost_workflows(report: AuditReport) -> None` (L450) — Identify workflows where costs exceed expected profit.
  - `_audit_human_intervention(report: AuditReport) -> None` (L487) — Identify opportunities with recurring human intervention requirements.
  - `_audit_execution_failures(report: AuditReport) -> None` (L520) — Identify opportunities stuck in BLOCKED or FAILED states.
  - `_audit_stale_providers(report: AuditReport) -> None` (L548) — Identify providers that have not produced results recently.
  - `_audit_stale_categories(report: AuditReport) -> None` (L580) — Identify opportunity categories with no recent activity.
  - `_audit_security_problems(report: AuditReport) -> None` (L610) — Identify potential security concerns.
  - `_audit_documentation_drift(report: AuditReport) -> None` (L635) — Identify documentation that may have drifted from implementation.
  - `_get_all_platforms() -> List[str]` (L666) — Get all platform names from memory.
  - `_get_all_opportunity_ids() -> List[str]` (L675) — Get all opportunity IDs from memory.


### `agents/services/self_improvement_commands.py` — agents/self_improvement_commands.py — Agent-callable, approval-gated patch commands. (108L)

**Functions:**
- `_service_available(service: Any) -> bool` (L23)
- `propose_code_patch(service: Any, authored_by=..., motivation=..., detail=..., , ...) -> dict[str, Any]` (L27) — Propose a code patch. Enqueues a human-approval item; applies nothing.
- `approve_and_apply(service: Any, approval_id: str) -> dict[str, Any]` (L64) — Approve the exact approval item, then apply the patch (backup/verify/rollback).
- `decline_patch(service: Any, approval_id: str, notes: str='') -> dict[str, Any]` (L88) — Deny the approval item; no file is touched.


### `agents/services/task_executor.py` — Compatibility import for :mod:`agents.earning.executor`. (20L)


### `agents/services/workflow_engine.py` — agents/workflow_engine.py — Structured earning workflow engine (v2.1 Phase 1). (230L)

**Classes:**
- `class WorkflowPhase(Enum)` (L25)
- `class PhaseEntry` (L53)
- `class WorkflowState` (L61) — State of a single opportunity through the workflow.
  - `transition_to(new_phase: WorkflowPhase, note: str='', data: Dict=None)` (L74) — Transition to a new phase.
  - `transition_requirements_met(new_phase: WorkflowPhase, data: Dict) -> bool` (L88) — Require observable proof before entering consequential phases.
- `class WorkflowEngine` (L107) — Manage opportunity workflows from discovery to completion.
  - `__init__(cost_tracker: CostTracker=None)` (L110)
  - `register_callback(callback: Callable)` (L115) — Register a callback for workflow events.
  - `start_workflow(opportunity: Opportunity) -> WorkflowState` (L119) — Start a new workflow for an opportunity.
  - `get_workflow(opportunity_id: str) -> Optional[WorkflowState]` (L133) — Get workflow state by opportunity ID.
  - `get_active_workflows() -> List[WorkflowState]` (L137) — Get all active (not completed/failed/rejected) workflows.
  - `get_workflows_by_phase(phase: WorkflowPhase) -> List[WorkflowState]` (L142) — Get all workflows in a specific phase.
  - `transition(opportunity_id: str, new_phase: WorkflowPhase, note: str='', data: Dict=None) -> bool` (L146) — Transition a workflow to a new phase.
  - `update_phase_data(opportunity_id: str, phase: WorkflowPhase, data: Dict)` (L178) — Update data for a specific phase.
  - `record_earnings(opportunity_id: str, amount: float)` (L185) — Record earnings for a workflow.
  - `record_cost(opportunity_id: str, amount: float)` (L192) — Record costs for a workflow.
  - `get_metrics() -> Dict` (L199) — Get aggregate workflow metrics.
  - `_notify(event: str, state: WorkflowState)` (L223) — Notify callbacks of workflow events.


### `agents/services/workflow_planner.py` — (no module docstring) (61L)

**Classes:**
- `class WorkflowStep` (L8)
- `class WorkflowPlan` (L15)
- `class WorkflowPlanner` (L20) — Turn an opportunity into a practical execution plan.
  - `__init__()` (L23)
  - `build_plan(opportunity: Opportunity) -> WorkflowPlan` (L47)


### `agents/autonomy/__init__.py` — agents/autonomy/__init__.py — Phase 5: Autonomy subsystem. (54L)


### `agents/autonomy/agent_registry.py` — agents/autonomy/agent_registry.py — Phase 5: Agent Registry. (395L)

**Classes:**
- `class AgentStatus(Enum)` (L21)
- `class CapabilityCategory(Enum)` (L29)
- `class CapabilitySpec` (L41)
- `class AgentSpec` (L49) — A registered agent definition.
- `class DelegationResult` (L69)
- `class AgentRegistry` (L79) — Central registry for all agents in the MrBot1000 system.
  - `__init__(registry_path: Optional[str]=None)` (L86)
  - `register(name: str, role: str, capabilities: List[CapabilitySpec], m, ...) -> AgentSpec` (L93) — Register a new agent and return its spec.
  - `unregister(agent_id: str) -> bool` (L120) — Remove an agent from the registry.
  - `heartbeat(agent_id: str) -> bool` (L129) — Record a heartbeat for an agent. Returns False if unknown.
  - `get_agent(agent_id: str) -> Optional[AgentSpec]` (L142)
  - `get_agents_by_role(role: str) -> List[AgentSpec]` (L145)
  - `get_agents_by_capability(category: CapabilityCategory) -> List[AgentSpec]` (L148)
  - `get_all_agents() -> List[AgentSpec]` (L154)
  - `get_idle_agents() -> List[AgentSpec]` (L157)
  - `get_busy_agents() -> List[AgentSpec]` (L160)
  - `delegate_task(task_id: str, required_capabilities: List[str]=None, requir, ...) -> DelegationResult` (L163) — Assign work to the first idle agent matching every requirement.
  - `assign_task(agent_id: str, task_id: str, lease_seconds: float=300.0) -> bool` (L211) — Assign a task with an expiring lease. Returns False if unavailable.
  - `renew_lease(agent_id: str, lease_id: str, lease_seconds: float=300.0) -> bool` (L228) — Renew an owned, unexpired lease.
  - `request_cancellation(agent_id: str, lease_id: str) -> bool` (L242) — Request cooperative cancellation for the current lease.
  - `is_cancellation_requested(agent_id: str, lease_id: str) -> bool` (L251)
  - `release_task(agent_id: str, lease_id: str) -> bool` (L255) — Release a task lease without recording success or failure.
  - `complete_task(agent_id: str, success: bool=True, lease_id: str='') -> bool` (L264) — Complete only the currently owned, unexpired lease.
  - `_clear_lease(agent: AgentSpec) -> None` (L283)
  - `_reclaim_expired(agent: Optional[AgentSpec]) -> None` (L290)
  - `check_health(stale_seconds: float=300.0) -> Dict[str, Any]` (L298) — Check health of all agents. Returns summary dict.
  - `_load() -> None` (L326)
  - `_save() -> None` (L356)


### `agents/autonomy/cli.py` — agents/autonomy/cli.py — Phase 6: CLI interface for MrBot1000 2.0. (326L)

**Functions:**
- `cmd_earning_run(sources: Optional[str], max_risk: str) -> int` (L44) — Run a full earning cycle.
- `cmd_earning_status() -> int` (L57) — Show current earning state.
- `cmd_heartbeat_start(interval: float, credit_getter: str) -> int` (L69) — Start the heartbeat system.
- `cmd_heartbeat_status(credit_getter: str) -> int` (L86) — Show current tier and credits.
- `_resolve_credit_getter(spec: str)` (L102) — Resolve a credit getter from a spec string.
- `cmd_agents_list() -> int` (L118) — List registered agents.
- `cmd_agents_register(name: str, role: str, capabilities: str) -> int` (L133) — Register a new agent.
- `cmd_identity_card(name: str, description: str, capabilities: str, endpoint: str) -> int` (L151) — Generate an on-chain agent card.
- `cmd_identity_verify() -> int` (L167) — Verify on-chain identity.
- `cmd_self_improve_status() -> int` (L180) — Show learning state.
- `cmd_self_improve_run() -> int` (L194) — Run a self-improvement pass.
- `build_parser() -> argparse.ArgumentParser` (L215)
- `main(argv: Optional[List[str]]=None) -> int` (L276)


### `agents/autonomy/grants.py` — Capability-scoped, expiring autonomy grants. (43L)

**Classes:**
- `class AutonomyGrant` (L11) — An operator-issued grant; model output cannot create or extend one.
  - `allows(required_level=..., capability=..., now=...) -> bool` (L26)


### `agents/autonomy/heartbeat.py` — agents/autonomy/heartbeat.py — Phase 5: Heartbeat System (from Automaton). (208L)

**Classes:**
- `class SurvivalTier(Enum)` (L27)
- `class CreditSnapshot` (L35)
- `class HeartbeatRecord` (L42)
- `class CreditMonitor` (L51) — Monitors available credits / balance and reports snapshots.
  - `__init__(getter: Optional[Callable[[], float]]=None)` (L58)
  - `check() -> CreditSnapshot` (L62)
  - `_classify(credits: float) -> SurvivalTier` (L77)
  - `history() -> List[CreditSnapshot]` (L87)
- `class HeartbeatSystem` (L91) — Continuous operation heartbeat.
  - `__init__(interval: float=300.0, credit_getter: Optional[Callable[[],, ...)` (L99)
  - `run(max_ticks: Optional[int]=None) -> List[HeartbeatRecord]` (L113) — Main heartbeat loop.
  - `stop() -> None` (L164)
  - `_run_tier_tasks(snap: CreditSnapshot) -> int` (L167) — Run tasks appropriate for the current survival tier.
  - `_run_full_tasks() -> int` (L182) — All features active, full scanning.
  - `_run_reduced_tasks() -> int` (L187) — Reduced scanning, cheaper models.
  - `_run_low_tasks() -> int` (L192) — Minimal scanning, local only.


### `agents/autonomy/onchain_identity.py` — agents/autonomy/onchain_identity.py — Phase 5: On-Chain Identity (ERC-8004). (230L)

**Classes:**
- `class AgentMetadata` (L20)
- `class AgentCard` (L29) — ERC-8004 agent card.
  - `to_dict() -> Dict[str, Any]` (L44)
  - `to_json() -> str` (L56)
- `class OnChainIdentity` (L60) — ERC-8004 on-chain identity manager.
  - `__init__(wallet_addr: Optional[str]=None, registry_path: Optional[str]=None)` (L68)
  - `generate_agent_card(name: str, description: str, capabilities: List[str], endpo, ...) -> AgentCard` (L81) — Generate an AgentCard from metadata.
  - `_compute_agent_id(name: str, endpoint: str) -> str` (L106) — Deterministic agent ID from name + endpoint + wallet.
  - `register(chain: str='ethereum', metadata: Optional[AgentMetadata]=No, ...) -> Dict[str, Any]` (L113) — Register the agent on-chain.
  - `_submit_on_chain(chain: str, metadata: Optional[AgentMetadata]) -> str` (L159) — Submit registration to the blockchain.
  - `verify(chain: str='ethereum', agent_address: str='') -> Dict[str, Any]` (L181) — Verify an agent's on-chain identity.
  - `_load() -> None` (L199)
  - `_save() -> None` (L212)


### `agents/autonomy/self_improvement.py` — agents/autonomy/self_improvement.py — Phase 5: Self-Improvement Engine. (289L)

**Classes:**
- `class Outcome(Enum)` (L21)
- `class OutcomeRecord` (L29)
- `class StrategyWeights` (L46) — Learned weights for a strategy's scoring factors.
  - `as_dict() -> Dict[str, float]` (L55)
  - `from_dict(d: Dict[str, float]) -> 'StrategyWeights'` (L65)
- `class LearningState` (L70) — Accumulated learning state for the self-improvement engine.
  - `overall_success_rate() -> float` (L81)
  - `net_roi() -> float` (L87)
- `class SelfImprovementEngine` (L97) — Learns from outcomes to improve future opportunity scoring.
  - `__init__(state_path: Optional[str]=None)` (L112)
  - `record_outcome(record: OutcomeRecord) -> None` (L120) — Record a completed opportunity outcome and trigger learning.
  - `get_strategy_weights(strategy: str) -> StrategyWeights` (L137)
  - `get_platform_reliability(platform: str) -> float` (L142)
  - `get_tag_success_rate(tag: str) -> float` (L145)
  - `get_recommendation() -> Dict[str, Any]` (L148) — Return a recommendation dict for the next opportunity scan.
  - `save(path: str) -> None` (L180)
  - `load(path: str) -> None` (L214)
  - `_update_platform_reliability(record: OutcomeRecord) -> None` (L230)
  - `_update_tag_rates(record: OutcomeRecord) -> None` (L237)
  - `_adjust_weights() -> None` (L245) — Adjust strategy weights based on accumulated outcomes.
  - `_strategy_score(weights: StrategyWeights) -> float` (L272)


### `agents/discovery/__init__.py` — discovery package. (2L)


### `agents/discovery/discovery_engine.py` — agents/discovery_engine.py — Orchestration for pluggable opportunity discovery. (113L)

**Classes:**
- `class DiscoveryStats` (L30)
- `class DiscoveryEngine` (L40) — Runs registered sources, dedups, isolates failures, reports stats.
  - `__init__(sources: List[OpportunitySource]=None, throttle: bool=True)` (L43)
  - `add_source(src: OpportunitySource) -> 'DiscoveryEngine'` (L49) — Register an additional source WITHOUT modifying core pipeline code.
  - `sources() -> List[OpportunitySource]` (L54)
  - `discover_all(page: int=1, query: str | None=None) -> Tuple[List[Opportunity], Dict[str, str],` (L57)
  - `reset_dedup() -> None` (L102)
  - `_acquire(name: str) -> None` (L106)


### `agents/discovery/discovery_port.py` — Application-facing discovery boundary. (59L)

**Classes:**
- `class BuiltinDiscoveryService` (L15) — Adapt the built-in source registry to a narrow pipeline-facing port.
  - `__init__(source_factory=..., engine_factory=..., log_fn=...) -> None` (L18)
  - `discover(requested: Iterable[str], page=..., query=...) -> tuple[list[Opportunity], dict[str, str],` (L32)


### `agents/discovery/discovery_scheduler.py` — discovery_scheduler.py — dynamic opportunity discovery scheduler (v2.0.36f). (389L)

**Classes:**
- `class SourceState` (L51)
  - `is_suspended(now: float) -> bool` (L61)
  - `backoff_seconds(base: float=600.0) -> float` (L64)
- `class DiscoveryTask` (L70)
- `class SchedulerConfig` (L80)
- `class DiscoveryScheduler` (L90) — Dynamic, history-driven discovery scheduler.
  - `__init__(memory=None, generator: Optional[SearchStrategyGenerat=None, ...)` (L93)
  - `_state(source: str) -> SourceState` (L103)
  - `_in_working_hours(now: float) -> bool` (L110)
  - `_source_quality(source: str) -> Tuple[float, float]` (L122) — Return (reliability 0..1, avg_revenue) for a source from memory.
  - `_category_profit(category: str) -> float` (L133) — Recent profitability of a category (success_rate * avg_revenue), normalized-ish.
  - `_update_source_timing(source: str, now: float) -> None` (L145)
  - `select_tasks(sources: List[str], now: Optional[float]=None) -> List[DiscoveryTask]` (L161)
  - `_can_run(source: str, now: float) -> bool` (L272)
  - `_category_fresh(category: str, now: float) -> bool` (L280)
  - `_profitable_categories() -> List[str]` (L284)
  - `_known_skills() -> List[str]` (L295)
  - `_user_preferences() -> List[str]` (L305)
  - `record_outcome(source: str, strategy_id: str, success=..., revenue=..., error=..., now=...) -> None` (L310)
  - `mark_searched(category: str, now: Optional[float]=None) -> None` (L327)
  - `run_task(task: DiscoveryTask, discover_fn, now: Optional[float]=None) -> Tuple[List, str]` (L331) — Execute ONE discovery task through a VALIDATED provider interface.
  - `tick(discover_fn, sources: Optional[List[str]]=None, now: Optional[float]=None) -> dict` (L365) — Run one discovery cycle. Returns a stats dict; discovered opps carry strategy provenance.


### `agents/discovery/discovery_sources.py` — agents/discovery_sources.py — Existing platform integrations as pluggable sources. (445L)

**Functions:**
- `is_junk_listing_title(title: str) -> bool` (L52) — True when a listing title is SEO spam / a placeholder rather than real work.
- `all_builtin_sources() -> List[BaseOpportunitySource]` (L429) — Return instances of every existing-integration source.

**Classes:**
- `class UpworkSource(BaseOpportunitySource)` (L75)
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None) -> List[Opportunity]` (L78)
- `class FiverrSource(BaseOpportunitySource)` (L108)
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None) -> List[Opportunity]` (L111)
- `class SocialSource(BaseOpportunitySource)` (L134)
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None, page: int=1) -> List[Opportunity]` (L137)
- `class AirdropSource(BaseOpportunitySource)` (L160)
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None, page: int=1) -> List[Opportunity]` (L163)
- `class DefiSource(BaseOpportunitySource)` (L185)
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None) -> List[Opportunity]` (L188)
- `class MicrotaskSource(BaseOpportunitySource)` (L220)
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None) -> List[Opportunity]` (L223)
- `class UgigSource(BaseOpportunitySource)` (L245) — Read public hiring listings from uGig without requiring credentials.
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None, page: int=1) -> List[Opportunity]` (L255)
- `class MoltbookSource(BaseOpportunitySource)` (L312) — Discover AI-agent work leads from Moltbook's semantic post search.
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None) -> List[Opportunity]` (L326)
- `class ContentSource(BaseOpportunitySource)` (L374) — DEPRECATED / REMOVED from default discovery (v2.0.36p).
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None) -> List[Opportunity]` (L386)
- `class DynamicSource(BaseOpportunitySource)` (L391) — Legacy EarningDiscoverer (Reddit/Twitter/GitHub-bounty/referral/faucet).
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None, page: int=1) -> List[Opportunity]` (L396)


### `agents/discovery/discovery_strategies.py` — discovery_strategies.py — multi-origin search-strategy generation (v2.0.36f). (204L)

**Functions:**
- `_make_id(*parts) -> str` (L74)

**Classes:**
- `class SearchStrategy` (L58) — A validated, executable search strategy (never an LLM action itself).
  - `provenance_tag() -> str` (L70)
- `class SearchStrategyGenerator` (L79) — Deterministic, offline-by-default generator. Optional LLM suggester (fails safe).
  - `__init__(emerging_categories: Optional[List[str]]=None, platform_ter, ...)` (L82)
  - `set_suggester(fn: Callable[[dict], List[str]]) -> None` (L89) — Optional LLM hook. Receives a context dict, returns suggested query strings.
  - `generate(known_skills=..., successful_categories=..., preferences=.., ...) -> List[SearchStrategy]` (L95) — Produce a diverse set of candidate strategies across all origins.
  - `is_failed_term(query: str) -> bool` (L202)


### `agents/discovery/scrape_resilience.py` — Scraper resilience helpers (v2.0.34s, Section C3). (180L)

**Functions:**
- `pick_ua(rotate: bool=True, idx: int=0) -> str` (L57) — Return a User-Agent string.
- `detect_captcha(text: str) -> bool` (L70) — Cheap heuristic: does ``text`` look like a captcha/interstitial page?
- `_parse_retry_after(value: Optional[str], default: float, max_wait: float=60.0) -> float` (L78) — Parse an HTTP ``Retry-After`` value (seconds int, or HTTP-date).
- `honor_retry_after(resp, max_wait=..., default_wait=...) -> float` (L107) — If ``resp`` is a 429/503 with Retry-After, sleep (capped) and return wait.
- `retry_on_429(func, max_retries=..., max_wait=..., default_wait=...)` (L133) — Call ``func`` (returns a requests.Response-like). On 429/503, honor
- `_resp_text(resp) -> str` (L169)

**Classes:**
- `class RateLimitedError(Exception)` (L49) — Raised when a request is rate-limited and retries are exhausted.
- `class CaptchaBlockedError(Exception)` (L53) — Raised when the response appears to be a captcha/interstitial.


### `agents/discovery/web_discovery.py` — agents/web_discovery.py — Generic web discovery source (pluggable, gated). (177L)

**Classes:**
- `class WebDiscoverySource(BaseOpportunitySource)` (L60) — Generic web discovery. Disabled by default; MOCK-FIRST; human-review gated.
  - `__init__(mock: bool=False, feeds: List[str]=None, allow: bool=None)` (L65)
  - `is_enabled() -> bool` (L74)
  - `_mock_discover() -> List[Opportunity]` (L78)
  - `_real_discover(query: Optional[str]=None) -> List[Opportunity]` (L92) — Fetch real feeds and parse real items. NEVER invents listings.
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None) -> List[Opportunity]` (L170)


### `agents/evidence/__init__.py` — evidence package. (2L)


### `agents/evidence/document_scanner.py` — agents/document_scanner.py — Document scanning, analysis, and QA verification. (407L)

**Classes:**
- `class DocumentAnalysis` (L21) — Result of document analysis.
- `class WorkVerification` (L38) — Verification of completed work before submission.
- `class DocumentScanner` (L51) — Scans and analyzes documents for quality verification.
  - `__init__(quality_threshold: float=0.7)` (L54)
  - `analyze_document(path: str, expected_word_count: int=None) -> DocumentAnalysis` (L58) — Analyze a document for quality and completeness.
  - `_read_document(path: str) -> str` (L112) — Read document content from various formats.
  - `_read_pdf(path: str) -> str` (L141) — Extract text from PDF using pymupdf or basic extraction.
  - `_calculate_readability(text: str) -> float` (L171) — Calculate Flesch-Kincaid readability score (0-1).
  - `_count_syllables(text: str) -> int` (L185) — Estimate syllable count.
  - `_assess_quality(content: str, readability: float, completeness: float) -> Tuple[List[str], List[str], str]` (L214) — Assess document quality and return notes, suggestions, and risk.
  - `_generate_checksum(content: str) -> str` (L255) — Generate checksum for content verification.
  - `verify_completion(work_id: str, expected_outputs: List[str], actual_files: List[str]) -> WorkVerification` (L260) — Verify that all expected outputs are present and complete.
- `class QualityController` (L316) — Controls quality gates before work submission.
  - `__init__(min_quality: float=0.8, require_reviews: int=0)` (L319)
  - `pre_submit_check(work_files: List[str], expected_outputs: List[str]) -> Dict` (L324) — Run all quality checks before allowing submission.
  - `double_check(work_files: List[str], review_by_ai: bool=True) -> Dict` (L343) — Double-check work using multiple verification methods.
  - `_check_consistency(files: List[str]) -> Dict` (L370) — Check if files are consistent with each other.


### `agents/evidence/evidence.py` — agents/evidence/evidence.py — First-class Evidence / provenance domain objects (v2.0.34aq). (432L)

**Functions:**
- `method_confidence(method: str) -> float` (L110) — Deterministic confidence of a verification method (LLM-independent).
- `make_money_evidence_set(gross: float, currency: str, fees: float=0.0, gas: float=0., ...) -> List[Evidence]` (L390) — Split one payment into provenance-preserving component Evidence records.

**Classes:**
- `class EvidenceStatus(str, Enum)` (L39)
  - `is_affirmative() -> bool` (L48) — True if the evidence currently supports the claim (VERIFIED or partial).
  - `is_terminal() -> bool` (L53)
- `class VerificationLevel(int, Enum)` (L58) — Trust level of the evidence. Higher = stronger external proof.
- `class VerificationResult` (L117) — One verification attempt. Appended to Evidence.history; never mutated.
- `class Evidence` (L130) — A first-class, immutable evidence/provenance record.
  - `create(**kwargs) -> 'Evidence'` (L174)
  - `verify(result: VerificationResult) -> 'Evidence'` (L194) — Return a NEW Evidence with `result` appended; status/level/method reflect it.
  - `is_verified(min_level: VerificationLevel=VerificationLevel.L3) -> bool` (L220) — Affirmative AND at/above the required trust level.
  - `confidence() -> float` (L225) — Deterministic trust in this evidence, derived from its verification METHOD (policy),
  - `dup_key() -> str` (L231) — Content fingerprint for duplicate detection. Two records describing the SAME
  - `mark_verified(method: str, level: VerificationLevel, actor: str='', note:, ...) -> 'Evidence'` (L246)
  - `mark_rejected(method: str, level: VerificationLevel, actor: str='', note: str='') -> 'Evidence'` (L252)
  - `mark_conflicted(method: str, level: VerificationLevel, actor: str='', note: str='') -> 'Evidence'` (L258)
  - `mark_expired(method: str='local_record', level: VerificationLevel=Verifi, ...) -> 'Evidence'` (L264)
  - `to_dict() -> Dict[str, Any]` (L271)
  - `from_dict(d: Dict[str, Any]) -> 'Evidence'` (L305)
- `class VerificationEvidence(Evidence)` (L346) — Legacy alias. `payout_verifier` emits Evidence; old code reading
  - `verified() -> bool` (L351)
  - `summary() -> str` (L355)
- `class Claim` (L364) — An unverified assertion. The LLM / a subsystem proposes this; a deterministic
- `class EvidenceRequirement` (L381) — What evidence a lifecycle transition needs before it may fire.


### `agents/evidence/evidence_factory.py` — agents/evidence_factory.py — Turn existing producer outputs into Evidence (v2.0.34aq). (163L)

**Functions:**
- `from_receipt_report(report, source: str='ethereum', subject_id: str='', wallet_, ...) -> Evidence` (L24) — Map a `chain_verifier.ReceiptReport` to a balance_delta Evidence.
- `from_eligibility_report(report, source: str='ethereum', subject_id: str='', wallet_, ...) -> Evidence` (L49)
- `from_verification_evidence(ve: VerificationEvidence, subject_id: str='', producer: str='payout_verifier') -> Evidence` (L66) — Convert the legacy payout_verifier.VerificationEvidence into the new Evidence.
- `from_upwork_submission(proposal_id: str, profile_id: str, job_id: str='', subject_, ...) -> Evidence` (L93) — A real platform submission. Verified via authenticated_api_response (L3) when the API
- `from_external_reconciliation(report, source: str='reconciliation', subject_id: str='', s, ...) -> Evidence` (L121) — Map an independent external reconciliation (e.g. bank statement vs on-chain delta, a
- `from_blockchain_receipt(report, source: str='ethereum', subject_id: str='', wallet_, ...) -> Evidence` (L145) — Map an on-chain transaction receipt to a VERIFIED evidence at L5 CRYPTOGRAPHIC.


### `agents/evidence/evidence_policy.py` — agents/evidence_policy.py — Verification policy: what evidence a transition needs, (208L)

**Functions:**
- `requirement_for(transition: str) -> EvidenceRequirement | None` (L99)
- `_slot_satisfied(slot: Slot, req: EvidenceRequirement, evidence: List[Evidence]) -> bool` (L103) — True if `slot` is satisfied by at least one evidence in `evidence`.
- `is_transition_eligible(transition: str, evidence: List[Evidence]) -> bool` (L119) — True iff every required slot is present with status VERIFIED/PARTIALLY_VERIFIED at/above
- `revenue_eligibility(evidence: List[Evidence]) -> Dict[str, float]` (L139) — Split a subject's monetary evidence into verified / pending / unverified revenue.
- `confidence_for(ev: Evidence) -> float` (L176) — Deterministic method-based confidence (LLM-independent). See MethodConfidence in evidence.py.
- `reconcile(ev: Evidence, reconciler: str, note: str='', method: str='e, ...) -> Evidence` (L182) — Promote a non-affirmative (CONFLICTED/REJECTED/UNVERIFIED) evidence to VERIFIED via

**Classes:**
- `class EvidenceRequirement` (L27) — What evidence a lifecycle transition needs.


### `agents/evidence/evidence_store.py` — agents/evidence/evidence_store.py — Append-only persistence + query for Evidence (v2.0.34aq). (154L)

**Classes:**
- `class EvidenceStore` (L23)
  - `__init__(db)` (L24) — `db` is an `AgentDB` instance (has `_execute(sql, params, commit=...)` + `_lock`).
  - `record(ev: Evidence) -> Evidence` (L29) — Persist one evidence record. Idempotent on id (INSERT OR REPLACE keeps history
  - `record_many(evs: List[Evidence]) -> None` (L54)
  - `get(evidence_id: str) -> Optional[Evidence]` (L59)
  - `for_subject(subject_type: str, subject_id: str) -> List[Evidence]` (L66)
  - `subject_ids(subject_type: str='opportunity') -> List[str]` (L74) — Return distinct subject IDs for read-only reconciliation and reporting.
  - `for_type(evidence_type: str, subject_type: str=None, subject_id: str=None) -> List[Evidence]` (L83)
  - `by_status(status: EvidenceStatus) -> List[Evidence]` (L94)
  - `children(parent_evidence_id: str) -> List[Evidence]` (L101)
  - `find_duplicate(ev: Evidence) -> Optional[Evidence]` (L109) — Return an EXISTING record with the same content fingerprint (dup_key), if any.
  - `is_duplicate(ev: Evidence) -> bool` (L131)
  - `confidence_for(ev: Evidence) -> float` (L134)
  - `history(evidence_id: str) -> List[Evidence]` (L138) — All rows ever written for an id, oldest first (immutability audit trail).
  - `_row_to_evidence(row) -> Evidence` (L148)


### `agents/evidence/numeric_evidence.py` — agents/numeric_evidence.py — deterministic evidence check for monetary values. (91L)

**Functions:**
- `_to_decimal(raw: str) -> Decimal | None` (L25) — Parse a matched number to an exact Decimal, or None if unusable.
- `extract_monetary_values(text: str) -> List[Decimal]` (L48) — Every monetary value in the text, exact, deduplicated, order kept.
- `extract_monetary_spans(text: str) -> List[Tuple[str, Decimal]]` (L61) — (raw_text, value) for each monetary occurrence, in order, not deduped.
- `unsupported_values(response_text: str, context_text: str) -> List[str]` (L71) — Monetary values cited in the response but absent from the supplied context.
- `has_unsupported_values(response_text: str, context_text: str) -> bool` (L88) — True when the response cites at least one value with no evidence.


### `agents/evidence/provenance.py` — agents/provenance.py — Truth-status labels + provenance chain (v2.0.36k). (170L)

**Classes:**
- `class TruthStatus(str, Enum)` (L28)
  - `reliability_rank() -> int` (L36) — Higher = more reliable. Used to compare/resolve conflicting info.
- `class ProvenanceRecord` (L50) — How a piece of information came to be.
  - `to_dict() -> dict` (L58)
- `class InfoAtom` (L68) — A single piece of information with truth status and provenance.
  - `to_dict() -> dict` (L77)
  - `is_at_least(status: TruthStatus) -> bool` (L83) — Check if this info meets a minimum reliability threshold.
- `class ProvenanceChain` (L91) — Ordered chain of records showing how a conclusion was reached.
  - `add(record: ProvenanceRecord) -> None` (L96)
  - `to_dict() -> dict` (L99)
- `class FactStore` (L105) — Stores information atoms for one opportunity, grouped by key.
  - `__init__(opportunity_id: str)` (L109)
  - `add(atom: InfoAtom) -> None` (L114) — Add an information atom. Preserves truth status as-is.
  - `get(key: str) -> List[InfoAtom]` (L121) — Get all atoms for a key.
  - `get_best(key: str) -> Optional[InfoAtom]` (L125) — Get the most reliable atom for a key.
  - `get_best_value(key: str, default: Any=None) -> Any` (L132) — Get the most reliable value for a key.
  - `has_fact(key: str) -> bool` (L137) — Check if we have a FACT for this key.
  - `has_verified(key: str) -> bool` (L141) — Check if we have a VERIFIED_RESULT or FACT for this key.
  - `explain(key: str) -> str` (L146) — Generate a human-readable explanation of what we know about a key.
  - `to_dict() -> dict` (L155)


### `agents/polish/cli_interface.py` — agents/polish/cli_interface.py — Phase 6: CLI Interface. (178L)

**Functions:**
- `main(argv: Optional[List[str]]=None) -> int` (L170)

**Classes:**
- `class CLIInterface` (L17) — Command-line interface for MrBot1000.
  - `__init__(registry=None, heartbeat=None, identity=None, audit=None)` (L24)
  - `_build_parser() -> argparse.ArgumentParser` (L31)
  - `run(args: Optional[List[str]]=None) -> Dict[str, Any]` (L69) — Parse and execute CLI arguments. Returns result dict.
  - `_cmd_agents(args) -> Dict[str, Any]` (L89)
  - `_cmd_heartbeat(args) -> Dict[str, Any]` (L105)
  - `_cmd_identity(args) -> Dict[str, Any]` (L116)
  - `_cmd_log(args) -> Dict[str, Any]` (L128)
  - `_cmd_learn(args) -> Dict[str, Any]` (L147)
  - `_cmd_self_test(args) -> Dict[str, Any]` (L150)


### `agents/polish/comprehensive_logging.py` — agents/polish/comprehensive_logging.py — Phase 6: Comprehensive Logging. (118L)

**Classes:**
- `class Severity(Enum)` (L19)
- `class AuditEvent` (L27) — A single structured audit log entry.
  - `__init__(event: str, severity: Severity=Severity.INFO, source: str=', ...)` (L30)
  - `to_dict() -> Dict[str, Any]` (L44)
  - `to_json() -> str` (L53)
- `class AuditLogger` (L57) — Thread-safe structured audit logger with optional file output.
  - `__init__(log_path: Optional[str]=None, max_entries: int=10000)` (L60)
  - `log(event: str, severity: Severity=Severity.INFO, source: str=', ...) -> AuditEvent` (L66) — Record an audit event. Returns the event for chaining.
  - `_persist(ev: AuditEvent) -> None` (L88)
  - `get_entries(severity: Optional[Severity]=None, source: Optional[str]=None, limit: int=100) -> List[Dict[str, Any]]` (L96) — Retrieve entries, newest first, optionally filtered.
  - `clear() -> None` (L112)

