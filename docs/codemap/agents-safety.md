<!-- generated 23 files -->

### `agents/safety/__init__.py` — Safety, authorization, and tool-execution boundaries. (87L)


### `agents/safety/approval.py` — agents/approval_queue.py — Human-approval queue for submissions, payments, and gates. (484L)
> The human-in-the-loop gate; record_payment/social_post require an APPROVED id from here.

**Functions:**
- `default_log_path() -> str` (L25) — Resolve where the approval queue is persisted. "" means in-memory only.
- `enqueue_approval(kind: ApprovalKind, title: str, description: str, requested_by: str='system', **kw) -> ApprovalItem` (L464)

**Classes:**
- `class ApprovalKind(str, Enum)` (L50)
- `class ApprovalStatus(str, Enum)` (L57)
- `class ApprovalItem` (L65) — A single pending approval item in the queue.
  - `to_dict() -> Dict[str, Any]` (L87)
  - `from_dict(d: Dict[str, Any]) -> 'ApprovalItem'` (L104)
- `class HumanApprovalQueue` (L121) — In-memory human-approval queue for the desktop app.
  - `__init__(log_path: Optional[str]=None)` (L132)
  - `_get_lock()` (L152)
  - `instance() -> 'HumanApprovalQueue'` (L159)
  - `reset_singleton()` (L174)
  - `enqueue(item: ApprovalItem) -> ApprovalItem` (L180) — Add a pending approval item and fire a notification.
  - `enqueue_submission(title: str, description: str, requested_by: str='system', d, ...) -> ApprovalItem` (L205)
  - `enqueue_payment(title: str, description: str, amount: float=0.0, currency: , ...) -> ApprovalItem` (L219)
  - `enqueue_gate(title: str, description: str, gate_type: str='', requested_, ...) -> ApprovalItem` (L234)
  - `decide(item_id: str, decision: ApprovalStatus, decided_by: str='human', notes: str='') -> bool` (L251) — Approve / deny / defer a pending item.
  - `deny(item_id: str, notes: str='') -> bool` (L296)
  - `defer(item_id: str, notes: str='') -> bool` (L299)
  - `approve(item_id: str, notes: str='') -> bool` (L302)
  - `pending() -> List[ApprovalItem]` (L307)
  - `all() -> List[ApprovalItem]` (L310)
  - `find_by_id(item_id: str) -> Optional[ApprovalItem]` (L313) — Look up an item by id, refusing decisions restored from a prior run.
  - `items_for_kind(kind: ApprovalKind) -> List[ApprovalItem]` (L333)
  - `pending_count() -> int` (L336)
  - `clear_all()` (L339) — Remove all items (e.g. on app exit or reset).
  - `_maybe_persist()` (L349)
  - `_load()` (L399) — Restore persisted items from the JSON log (best-effort).
  - `_find(item_id: str) -> Optional[ApprovalItem]` (L455)


### `agents/safety/authorization.py` — Canonical authorization boundary for state-changing operations. (78L)

**Classes:**
- `class AuthorizationResult` (L13)
- `class AuthorizedActionDispatcher` (L19) — Authorize an operation once, then optionally invoke its implementation.
  - `__init__(safety_gate: SafetyGate | None=None) -> None` (L22)
  - `authorize(name: str, arguments: Dict[str, Any], approved=..., grant=., ...) -> AuthorizationResult` (L25)
  - `dispatch(name: str, arguments: Dict[str, Any], handler: Callable[[ob, ...) -> str` (L51)


### `agents/safety/calling.py` — agents/tool_calling.py — Unified tool calling system for MrBot1000 personas. (232L)

**Functions:**
- `_require_mutation_capability(authorization: object | None, tool_name: str) -> Optional[str]` (L56) — Prevent mutation implementations from being called outside dispatch.
- `_get_safety_gate() -> SafetyGate` (L69) — Return the shared authorization gate for chat tool execution.
- `_get_action_dispatcher() -> AuthorizedActionDispatcher` (L79)
- `_get_instruction_gate()` (L88) — Return the shared provenance gate used for remote skill documents.
- `_is_skill_document(url: str) -> bool` (L100)
- `_tool_result_status(result: str) -> str` (L119) — Classify the dispatcher result for the UI and dialogue ledger.
- `_tool_trace_entry(name: str, arguments: Dict[str, Any], result: str, source: str) -> Dict[str, Any]` (L129) — Build an explicit proposal/execution trace from the dispatcher result.
- `get_max_tokens_for_context(context_type: str) -> int` (L169) — Get max tokens based on context type.
- `classify_context_type(message: str) -> str` (L186) — Classify the context type based on message content.
- `add_anti_hallucination_rules(system_prompt: str) -> str` (L206) — Add anti-hallucination rules to system prompt.


### `agents/safety/circuit.py` — Per-provider circuit breaker for LLM calls (v2.0.34y, Section D4). (113L)

**Functions:**
- `_enabled() -> bool` (L26)
- `_failure_threshold() -> int` (L30)
- `_cooldown_seconds() -> float` (L37)
- `get_breaker() -> ProviderCircuitBreaker` (L110) — Shared, process-wide circuit breaker for `llm()`.

**Classes:**
- `class _ProviderState` (L44)
  - `__init__()` (L47)
- `class ProviderCircuitBreaker` (L52) — Tracks consecutive failures per provider and opens the circuit past a threshold.
  - `__init__()` (L55)
  - `is_open(name: str) -> bool` (L58) — True if the provider should be skipped right now (circuit open).
  - `record_failure(name: str) -> None` (L73)
  - `record_success(name: str) -> None` (L84)
  - `reset(name: str) -> None` (L91)
  - `snapshot() -> Dict[str, dict]` (L94) — Debug/observability view of current breaker state.


### `agents/safety/cost.py` — agents/cost_guard.py — Hard daily LLM spend cap (A4). (77L)

**Functions:**
- `is_local_provider(name: str) -> bool` (L16) — A provider is free/local (never skipped by the budget guard) iff it is Ollama.

**Classes:**
- `class CostGuard` (L26) — Daily LLM budget guard. budget_usd == 0 disables the guard (backward compat).
  - `__init__(daily_budget_usd: float=0.0)` (L29)
  - `from_env(env_key: str='LLM_DAILY_BUDGET_US) -> 'CostGuard'` (L36)
  - `daily_cost_usd(db) -> float` (L39) — Estimated spend in the last 24h, via database.get_llm_cost_usd(days=1).
  - `is_exceeded(db) -> bool` (L48) — True iff a budget is set AND estimated daily spend >= budget.
  - `should_skip(db, provider_name: str) -> bool` (L54) — Skip a BILLABLE provider when the daily cap is exceeded.
  - `status(db) -> dict` (L66)


### `agents/safety/dispatch.py` — Authorized tool dispatch boundary. (125L)

**Functions:**
- `_accepts_authorization(handler: Any) -> bool` (L13) — True when a tool handler declares the dispatch ``authorization`` kwarg.
- `execute_tool(name: str, arguments: Dict[str, Any], approved: bool=False) -> str` (L34) — Authorize and dispatch one tool without bypassing safety policy.


### `agents/safety/filesystem.py` — Filesystem and research mixin for the legacy worker fa?ade. (327L)

**Classes:**
- `class WorkerFilesystemMixin` (L18)
  - `safe_write_file(filename: str, content: str) -> bool` (L19) — Write a file safely inside ROOT_FOLDER only, with a pre-edit backup.
  - `restore_last_backup(filename: str) -> bool` (L89) — Restore the most recent .bak backup for `filename` (relative to root).
  - `research_all() -> dict` (L116) — Scan ROOT_FOLDER (.py files) and user-selected research_folder.
  - `file_index() -> str` (L245) — Return a compact index of all files in the research folder.
  - `read_specific_files(filenames: list, base_path: str=None) -> str` (L275) — Read full content of specific files by relative path.
  - `set_research_folder(path: str)` (L312) — Set the research folder path.
  - `stop()` (L316) — Signal the worker to stop running.
  - `is_running() -> bool` (L320) — Check if the worker is still running.


### `agents/safety/gate.py` — Safety gate for tool calling. (163L)
> MUTATING_TOOL_NAMES lives here (which tools need approval).

**Functions:**
- `canonical_tool_name(tool_name: str) -> str` (L87) — Return the real registry name for a tool or one of its aliases.
- `is_known_tool(tool_name: str) -> bool` (L92) — True if the name (or a documented alias) resolves to a classified tool.

**Classes:**
- `class SafetyDecision(str, Enum)` (L19)
- `class SafetyRule` (L26) — A safety rule for a tool.
- `class SafetyGate` (L98) — Safety gate for tool execution.
  - `__init__(auto_approve_readonly: bool=True)` (L101)
  - `check(tool_name: str, arguments: Dict) -> Tuple[bool, str, SafetyDecision]` (L105) — Check whether a tool call may run.
  - `get_pending_approvals() -> list` (L136) — Get list of pending approval requests.
  - `approve(tool_name: str, arguments: Dict) -> bool` (L148) — Approve the pending request that matches this tool call, if any.


### `agents/safety/gates.py` — agents/human_gates.py — Human-in-the-loop gate manager (v2.0.36i). (258L)

**Classes:**
- `class HumanGateType(str, Enum)` (L28)
- `class HumanGateRecord` (L44) — A single human gate for a task.
  - `to_dict() -> dict` (L53)
- `class HumanGateManager` (L66) — Determines when human input is required. Never bypasses.
  - `__init__(config: Optional[Dict]=None)` (L69)
  - `assess(task: Dict[str, Any], context: Dict[str, Any]) -> List[HumanGateRecord]` (L75) — Determine which gates apply based on task properties. Returns list of required gates.
  - `requires_human(task: Dict[str, Any], context: Dict[str, Any]) -> bool` (L163) — Quick check: does this task require any human gate?
  - `clear_gate(task_id: str, gate_type: HumanGateType, evidence: str='') -> bool` (L169) — Record human clearance for a gate. Returns True if found and cleared.
  - `get_pending_gates(task_id: str) -> List[HumanGateRecord]` (L180) — Return uncleared gates for a task.
  - `get_all_gates(task_id: str) -> List[HumanGateRecord]` (L184) — Return all gates for a task.
  - `all_cleared(task_id: str) -> bool` (L188) — Check if all gates for a task are cleared.
  - `_has_payment(task: Dict, context: Dict) -> bool` (L195)
  - `_task_text(task: Dict, context: Dict) -> str` (L203)
  - `_has_account_creation(task: Dict, context: Dict) -> bool` (L206)
  - `_has_profile_submission(task: Dict, context: Dict) -> bool` (L213)
  - `_has_contracts(task: Dict, context: Dict) -> bool` (L219)
  - `_has_signatures(task: Dict, context: Dict) -> bool` (L224)
  - `_has_identity(task: Dict, context: Dict) -> bool` (L228)
  - `_has_sensitive(task: Dict, context: Dict) -> bool` (L233)
  - `_has_irreversible(task: Dict, context: Dict) -> bool` (L238)
  - `_has_captcha(task: Dict, context: Dict) -> bool` (L243)
  - `_has_platform_manual(task: Dict, context: Dict) -> bool` (L247)


### `agents/safety/guard.py` — agents/safety_guard.py — Multi-layer safety orchestrator (v2.1 Phase 3). (783L)

**Classes:**
- `class SafetyLevel(Enum)` (L30)
- `class SafetyAction` (L39) — Represents an action to be checked.
- `class SafetyResult` (L51) — Result of safety checks.
  - `blocked() -> bool` (L61)
  - `flagged() -> bool` (L65)
- `class SafetyLayer` (L71) — Base class for a single safety layer.
  - `__init__(config: Dict=None)` (L77)
  - `enabled() -> bool` (L82)
  - `check(action: SafetyAction) -> Optional[SafetyResult]` (L85) — Check an action. Returns None to pass to next layer.
  - `reset()` (L89) — Reset layer state.
- `class CostGuardLayer(SafetyLayer)` (L94) — Enforces daily/weekly LLM spend limits.
  - `__init__(config: Dict=None)` (L100)
  - `check(action: SafetyAction) -> Optional[SafetyResult]` (L105)
- `class RecursionDetectorLayer(SafetyLayer)` (L130) — Detects and blocks recursive loops.
  - `__init__(config: Dict=None)` (L155)
  - `check(action: SafetyAction) -> Optional[SafetyResult]` (L169)
  - `pop()` (L228) — Retire the last in-flight call, recording it for the repeat rule.
  - `reset()` (L240)
- `class ToolFirewallLayer(SafetyLayer)` (L246) — Enforces tool allow/deny lists.
  - `__init__(config: Dict=None)` (L252)
  - `check(action: SafetyAction) -> Optional[SafetyResult]` (L258)
  - `add_to_denylist(tool_name: str)` (L289)
  - `add_to_allowlist(tool_name: str)` (L292)
  - `remove_from_denylist(tool_name: str)` (L295)
  - `remove_from_allowlist(tool_name: str)` (L298)
- `class HumanApprovalLayer(SafetyLayer)` (L302) — Requires human approval for high-value actions.
  - `__init__(config: Dict=None)` (L308)
  - `set_approval_callback(callback: Callable)` (L320) — Set callback for when human approves/rejects.
  - `pending_approvals() -> List[Dict]` (L325) — Back-compat view of this layer's still-pending requests.
  - `check(action: SafetyAction) -> Optional[SafetyResult]` (L329)
  - `_enqueue_to_shared_queue(approval_id: str, action: SafetyAction, reasons: List[str]) -> bool` (L400) — Mirror this request into HumanApprovalQueue. Best-effort.
  - `_prune_owned_locked()` (L455) — Drop decided records so _owned cannot grow without bound.
  - `approve(approval_id: str) -> bool` (L474) — Approve a pending action.
  - `reject(approval_id: str) -> bool` (L497) — Reject a pending action.
  - `_decide_in_shared_queue(approval_id: str, approved: bool) -> bool` (L517) — Record the human's decision in the shared queue, if we mirrored it.
  - `get_pending() -> List[Dict]` (L532) — Get all pending approvals.
- `class RateLimiterLayer(SafetyLayer)` (L569) — Rate limiting per tool and per provider.
  - `__init__(config: Dict=None)` (L575)
  - `check(action: SafetyAction) -> Optional[SafetyResult]` (L584)
  - `_check_rate(counters: Dict[str, List[float]], key: str, now: float, limit: int) -> bool` (L618) — Check if a call is within rate limit.
  - `get_remaining(key: str, limit: int=None) -> int` (L632) — Get remaining calls for a key.
- `class SafetyGuard` (L643) — Central safety orchestrator. Checks all layers.
  - `__init__(config: Dict=None)` (L646)
  - `_setup_layers()` (L652) — Initialize all safety layers.
  - `check(action: SafetyAction) -> SafetyResult` (L677) — Run all safety layers on an action.
  - `check_and_raise(action: SafetyAction)` (L719) — Check and raise SafetyViolation if blocked.
  - `get_layer(name: str) -> Optional[SafetyLayer]` (L726) — Get a specific safety layer by name.
  - `get_status() -> Dict` (L733) — Get status of all safety layers.
  - `reset()` (L750) — Reset all layers.
  - `get_pending_approvals() -> List[Dict]` (L755) — Get pending human approvals.
  - `approve(approval_id: str) -> bool` (L762) — Approve a pending action.
  - `reject(approval_id: str) -> bool` (L769) — Reject a pending action.
- `class SafetyViolation(Exception)` (L777) — Raised when a safety check blocks an action.
  - `__init__(result: SafetyResult)` (L780)


### `agents/safety/handlers.py` — Domain tool handlers used by the authorized dispatcher. (455L)
> query_db (multi-DB, D1), record_payment (D2), social_post (D3) tool handlers.

**Functions:**
- `_tool_web_search(args: Dict[str, Any]) -> str` (L15) — Search the web.
- `_tool_web_read(args: Dict[str, Any]) -> str` (L26) — Read a web page.
- `_tool_web_check(args: Dict[str, Any]) -> str` (L76) — Check website status.
- `_tool_workshop_list(args: Dict[str, Any]) -> str` (L92) — List workshop files.
- `_tool_workshop_read(args: Dict[str, Any]) -> str` (L108) — Read a workshop file.
- `_tool_workshop_write(args: Dict[str, Any], authorization=...) -> str` (L118) — Write a workshop file.
- `_tool_workshop_mkdir(args: Dict[str, Any], authorization=...) -> str` (L133) — Create a workshop folder.
- `_tool_workshop_storage(args: Dict[str, Any]) -> str` (L148) — Report workshop quota and disk usage.
- `_tool_workshop_search(args: Dict[str, Any]) -> str` (L158) — Search workshop files.
- `_tool_workshop_proposal(args: Dict[str, Any], authorization=...) -> str` (L174) — Create a proposal.
- `_tool_workshop_account(args: Dict[str, Any], authorization=...) -> str` (L189) — Add an account.
- `_tool_workshop_payment(args: Dict[str, Any], authorization=...) -> str` (L204) — Add a payment method.
- `_tool_file_read(args: Dict[str, Any]) -> str` (L221) — Read a file.
- `_tool_file_write(args: Dict[str, Any], authorization=...) -> str` (L232) — Write a file.
- `_tool_file_list(args: Dict[str, Any]) -> str` (L247) — List directory.
- `set_lifecycle_tracker(tracker) -> None` (L304) — Inject the OpportunityLifecycleTracker for the record_payment tool.
- `_evidence_meets_l3(ev) -> bool` (L310) — ARCH-ENG-121: true only for a real `Evidence` carrying its own affirmative status AND verification_level >= L3_EXTERNAL_SOURCE. A dict (including a serialized `Evidence.to_dict()`) is refused because it is agent-supplied.
- `_evidence_detail(ev) -> str` — Never-raising description of supplied evidence for refusal messages.
- `_tool_record_payment(args: Dict[str, Any], authorization=...) -> str` (L371) — Record a verified payment against an opportunity (HIGH_TRUST). ARCH-ENG-121: fails closed unless `evidence_ref` resolves in the authoritative EvidenceStore to a stored record meeting the L3 floor for THIS opportunity. An approval authorizes the action, not the amount or its verification.
- `set_social_writer(writer) -> None` (L331) — Inject a callable(post_payload) -> result for confirmed write endpoints.
- `_tool_social_post(args: Dict[str, Any], authorization=...) -> str` (L341) — Post content to a social/agent network (HIGH-TRUST, approval-gated).
- `_tool_run_command(args: Dict[str, Any], authorization=...) -> str` (L386) — Run a shell command.
- `_resolve_db_path(db_name: str) -> str` (L413) — Resolve an allowlisted store name to its DB path under PROJECT_ROOT.
- `_tool_query_db(args: Dict[str, Any]) -> str` (L433) — Run a read-only SQL query against an allowlisted store (default agent.db).


### `agents/safety/instructions.py` — agents/instruction_gate.py — Instruction Provenance Gate (v2.0.22 S1) (215L)
> Prompt-injection provenance gate: platform SKILL.md is UNTRUSTED data, never directives.

**Classes:**
- `class QuarantinedInstruction` (L33) — Result of a gate check/fetch. `trusted` means it may be acted upon.
  - `__init__(url: str, status: str, content: str='', content_hash: str=', ...)` (L36)
  - `trusted() -> bool` (L48) — Only explicitly-allowed instructions are trusted for action.
- `class InstructionGate` (L57) — Central provenance gate for external instructions/playbooks.
  - `__init__(db, fetcher=..., timeout=..., user_agent=...)` (L60)
  - `check(url: str, kind=...) -> QuarantinedInstruction` (L72) — Check an instruction URL's trust status WITHOUT fetching content.
  - `fetch_instruction(url: str, kind=..., title=...) -> QuarantinedInstruction` (L92) — Fetch an external instruction through the gate.
  - `review(quarantine_id: int, approve: bool, url=..., content_hash=..., related=...) -> str` (L138) — Human-in-the-loop decision. approve -> allowlist, else -> blacklist
  - `pending(limit: int=100)` (L147)
  - `counts() -> dict` (L150)
  - `_find_pending_by_url(url: str)` (L155)
  - `_hash(content: str) -> str` (L161)
  - `_is_safe_fetch_url(url: str) -> bool` (L171)
  - `_default_fetch(url: str) -> str` (L205)


### `agents/safety/learning.py` — Safety boundary between learned preferences and action authorization. (21L)

**Classes:**
- `class LearningSafetyBoundary` (L6) — Allow learning to rank options, never to bypass trust controls.
  - `__init__(trust_boundary: TrustBoundary | None=None)` (L9)
  - `authorize(action: str, human_approved=..., instruction_trusted=...) -> tuple[bool, str]` (L12)


### `agents/safety/legacy_tools.py` — Tool definitions for Big Brain tool calling. (214L)

**Functions:**
- `_read_file(path: str) -> str` (L19)
- `_write_file(path: str, content: str) -> str` (L29)
- `_list_dir(path: str) -> List[str]` (L39)
- `_run_command(cmd: str, cwd: Optional[str]=None) -> str` (L47)
- `execute_tool(name: str, arguments: Dict[str, Any]) -> str` (L181) — Execute a tool by name with given arguments.


### `agents/safety/policy.py` — Shared safety policy for model-invoked local tools. (46L)

**Functions:**
- `resolve_project_path(raw_path: str, allow_missing=...) -> Path` (L14) — Resolve a tool path and require it to remain inside the project root.
- `command_argv(command: str) -> list[str]` (L29) — Parse a command without invoking a shell or shell metacharacters.
- `resolve_command_cwd(raw_cwd: str | None) -> Path` (L44) — Resolve an optional command working directory inside the workspace.


### `agents/safety/provider_rate_limiter.py` — Per-provider rate limiting + daily budget (Phase F, ARCH-ENG-091). (200L)

**Functions:**
- `is_local_provider(name: str) -> bool` (L37)
- `_defaults_for(name: str)` (L51)
- `get_provider_rate_limiter() -> ProviderRateLimiter` (L172)
- `ensure_table(db_path: Optional[str]=None) -> None` (L180) — Create the daily-calls table if absent (safe to call repeatedly).

**Classes:**
- `class ProviderRateLimiter` (L55) — Per-provider token-bucket rate limit + persisted daily call cap.
  - `__init__(db_path: Optional[str]=None)` (L58)
  - `rate_for(provider: str) -> float` (L65)
  - `max_calls_for(provider: str) -> int` (L75)
  - `_bucket(provider: str) -> TokenBucket` (L85)
  - `_today() -> str` (L95)
  - `_calls_today(provider: str) -> int` (L98)
  - `_bump(provider: str) -> None` (L112)
  - `check(provider: str) -> Dict` (L127) — Return {"allow": bool, "reason": str}. Does NOT consume a token.
  - `acquire(provider: str, block=..., timeout=...) -> Dict` (L136) — Rate-limit + count one call. Returns {"allow", "reason"}.
  - `status() -> Dict[str, Dict]` (L154) — Per-provider view for the Settings/DB tabs.


### `agents/safety/response.py` — Pure response cleanup and text tool-call parsing. (290L)

**Functions:**
- `_tool_name_pattern() -> str` (L14) — Regex alternation of every real tool name, from the canonical registry.
- `_remove_tool_syntax(text: str) -> str` (L50) — Remove visible tool-invocation fragments from a user-facing answer.
- `_remove_reasoning_channels(text: str) -> str` (L148) — Remove channel-formatted reasoning while preserving visible answer text.
- `_remove_think_blocks(text: str) -> str` (L169) — Remove LFM/Gemma think blocks without exposing hidden reasoning.
- `_visible_response_content(message: Any, profile: dict[str, Any]=None) -> str` (L178) — Extract only user-visible answer text from an OpenAI message.
- `_parse_tool_call_from_text(text: str) -> Optional[tuple]` (L214) — Parse tool call patterns from text.


### `agents/safety/sql.py` — Read-only SQLite execution for model-facing database tools. (54L)
> SELECT-only enforcement for model-facing DB reads.

**Functions:**
- `_readonly_authorizer(action: int, _arg1: Any, _arg2: Any, _database: Any, _source: Any) -> int` (L18) — Allow only query planning/read operations.
- `_prepare_readonly(conn: sqlite3.Connection, sql: str) -> None` (L25) — Compile one statement with writes and side effects denied.
- `validate_readonly_sql(sql: str, db_path: str | Path) -> None` (L32) — Raise ValueError unless *sql* is one valid, read-only SQLite statement.
- `execute_readonly_query(sql: str, db_path: str | Path, limit: int=50) -> str` (L44) — Validate and execute a bounded read-only query with guaranteed cleanup.


### `agents/safety/tool_safety.py` — Compatibility import for :mod:`agents.safety.policy`. (16L)


### `agents/safety/tools.py` — Canonical tool schema registry. (246L)

**Functions:**
- `get_all_tools() -> List[Dict[str, Any]]` (L6) — Get all available tool definitions.


### `agents/safety/trust.py` — agents/trust_boundary.py — High-trust action boundary (v2.0.22 S2) (90L)

**Classes:**
- `class TrustBoundary` (L44) — Decides whether an action may proceed and whether it needs a human.
  - `__init__(ai_policy=...)` (L47)
  - `is_high_trust(action: str) -> bool` (L52)
  - `requires_human_confirmation(action: str, instruction_trusted: bool=False) -> bool` (L55) — True if this action must wait for explicit human confirmation.
  - `may_auto_execute(action: str, instruction_trusted: bool=False) -> tuple[bool, str]` (L73) — Returns (allowed, reason). `allowed` is strictly for LOW_TRUST


### `agents/safety/workspace.py` — TaskWorkspace — per-task deliverable workspace for MrBot1000. (285L)

**Functions:**
- `workspace_for(job: Dict[str, Any], root_folder: str=None, log_signal=None) -> TaskWorkspace` (L275) — Convenience factory from a JobRecord dict (or to_dict()).

**Classes:**
- `class TaskWorkspace` (L44) — A sandboxed folder where one gig's deliverables are produced + verified.
  - `__init__(platform: str, job_id: str, root_folder: str=None, log_signal=None)` (L47)
  - `_inside_root(p: Path, root: Path=None) -> bool` (L65)
  - `ensure() -> Path` (L72)
  - `_safe_file_path(filename: str) -> Optional[Path]` (L78) — Resolve a deliverable filename strictly inside this workspace.
  - `save(filename: str, content: str) -> bool` (L89) — Write a deliverable into the workspace (backs up existing first).
  - `list_files() -> List[str]` (L109) — Return deliverable file paths (relative to workspace) as strings.
  - `infer_requirements(job: Dict[str, Any]) -> List[str]` (L122) — Derive expected-output hints from a JobRecord dict.
  - `verify(requirements: Optional[List[str]]=None, job: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` (L147) — Check the workspace's files satisfy the gig requirements.
  - `_status_file() -> Path` (L184)
  - `set_status(status: str, extra: Optional[Dict[str, Any]]=None) -> None` (L187)
  - `_read_status() -> Dict[str, Any]` (L199)
  - `status() -> str` (L214)
  - `complete(requirements: Optional[List[str]]=None, job: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` (L219) — Verify requirements; if met, mark done and archive deliverables.
  - `submit() -> Dict[str, Any]` (L253) — Hand the work back. Local packaging only (no network upload yet).

