<!-- generated 28 files -->

### `agents/brains/__init__.py` — brains package. (2L)


### `agents/brains/base_worker.py` — WorkerAgent provides base functionality for all MrBot1000 subagents: (327L)

**Functions:**
- `think_budget(level: str, chat: bool) -> int` (L139) — Thinking (reasoning) token reserve for the current model's context.
- `context_tokens(chat: bool) -> int` (L154) — The ACTUAL context-window size of the model being used, in tokens.
- `model_context_tokens(model: str) -> int` (L208)

**Classes:**
- `class WorkerAgent(WorkerProviderMixin, WorkerLLMMixin, WorkerProviderCallsMixin, WorkerFilesystemMixin)` (L263) — Base class for MrBot1000 subagents with LLM integration and secure I/O.
  - `shutdown_ollama_executor()` (L269) — Cancel queued legacy Ollama calls during application shutdown.
  - `__init__(api_key: str, log_signal, db=None, ollama_model: str | None, ...)` (L273)
  - `_get_shared_context()` (L319) — Lazy-load shared context for cross-model communication


### `agents/brains/big_brain.py` — Big Brain — Provider adapter for the main reasoning model. (616L)

**Functions:**
- `get_big_brain()` (L610) — Get or create the Big Brain singleton.

**Classes:**
- `class BigBrainAdapter` (L33) — Interface to the main reasoning model via llama-server on 5060 Ti.
  - `__init__(model=None, base_url=None, safety_gate: SafetyGate | None=None)` (L36)
  - `_get_client()` (L79) — Get OpenAI client for llama-server.
  - `_dialogue_protocol() -> dict` (L96)
  - `_get_first_available_model() -> str` (L102) — Auto-detect first available model in llama-server.
  - `get_available_models() -> list` (L113) — Get list of all downloaded models.
  - `set_model(model_name: str)` (L124) — Switch to a different model.
  - `_start_got_turn(prompt: str)` (L128)
  - `_finish_got_turn(turn, response: str, status: str='completed', branch_candid, ...) -> str` (L132)
  - `_hardware_line() -> str` (L150) — One line describing the device this brain runs on (N-brain).
  - `_build_system_prompt(query: str='', task_type: str='general') -> str` (L187) — Build system prompt with knowledge, personality, and specialization.
  - `_execute_tool_calls(tool_calls: list) -> list` (L219) — Execute tool calls from the model, with safety gate.
  - `analyze_with_tools(prompt: str, context: str='') -> str` (L277) — Deep reasoning and analysis with tool calling.
  - `analyze(prompt: str, context: str='') -> str` (L383) — Deep reasoning and analysis (legacy method, now uses tool calling).
  - `verify(claim: str) -> str` (L387) — Fact-check a claim from Small Brain.
  - `plan(goal: str) -> str` (L391) — Create a multi-step plan.
  - `revise(original_plan: str, feedback: str) -> str` (L395) — Revise a plan based on feedback.
  - `chat(user_message: str, history: list=None, system_prompt: str=N, ...) -> str` (L403) — Handle direct chat with tool calling support.


### `agents/brains/brain_got.py` — Inspectable Graph-of-Thought records for model turns. (384L)

**Functions:**
- `start_brain_turn(role: str, goal: str, pattern: PatternSelection | None=None) -> BrainTurnGraph` (L375)

**Classes:**
- `class BranchCandidate` (L26) — One inspectable candidate thought for a branching (Tree/Graph-of-Thought) turn.
  - `summary() -> str` (L42)
- `class BrainTurnGraph` (L53) — Build a small, deterministic GoT graph around one model invocation.
  - `__init__(role: str, goal: str, turn_id: str | None=None, pattern: PatternSelection | None=None)` (L56)
  - `record_decision(selected_option: str, rationale: str, evidence_ids=...) -> str` (L97) — Record a concise decision summary without recording private reasoning.
  - `record_action(action_id: str, tool_name: str, approval_required=..., evidence_ids=...) -> str` (L122) — Record an action intent; this does not dispatch or authorize it.
  - `record_execution(action_id: str, status: str, summary: str) -> str` (L150) — Record dispatcher-confirmed execution separately from the proposal.
  - `expand_branches(candidates: Iterable['BranchCandidate | Ma) -> list[str]` (L171) — Expand the turn into multiple candidate OPTION nodes (GoT branching).
  - `score_branches(evidence_by_id: Mapping[str, Any] | None=None) -> list[SupportMeasure]` (L244) — Rank the expanded branches by deterministic evidence-backed support.
  - `select_branch() -> str | None` (L260) — Record a scored DECISION that selects the best-ranked branch.
  - `is_branching() -> bool` (L296) — Whether this turn expanded into multiple candidate branches.
  - `_summary(value: Any, limit: int=800) -> str` (L301)
  - `record_tool_trace(trace: Iterable[Mapping[str, Any]] | ) -> None` (L305)
  - `finish(response: str, status: str='completed') -> dict` (L318)


### `agents/brains/shared_context.py` — shared_context.py — Cross-model communication layer for MrBot1000 (354L)

**Functions:**
- `get_shared_context(path: Optional[str]=None) -> SharedContext` (L348)

**Classes:**
- `class ModelContext` (L27) — Context entry for a specific model
- `class SharedState` (L39) — Global shared state across all models and agents
  - `to_dict() -> dict` (L48)
- `class SharedContext` (L66) — Thread-safe shared context for cross-model communication.
  - `__init__(path: str=None)` (L72)
  - `_ensure_file_exists()` (L78)
  - `_read_state() -> SharedState` (L83)
  - `_read_state_unlocked() -> SharedState` (L87)
  - `_write_state(state: SharedState)` (L111)
  - `_write_state_unlocked(state: SharedState)` (L115)
  - `update_model_context(model_name: str, **kwargs)` (L127) — Update context for a specific model
  - `get_model_context(model_name: str) -> Optional[ModelContext]` (L153) — Get context for a specific model
  - `get_all_model_contexts() -> Dict[str, ModelContext]` (L158) — Get contexts for all models
  - `add_global_task(task: str, assignee: str=None, priority: int=5)` (L165) — Add a cross-model task
  - `get_pending_tasks(model_name: str=None) -> List[Dict]` (L181) — Get pending tasks for a model or all pending tasks
  - `complete_task(task_id: str, result: str='')` (L189) — Mark a task as completed
  - `add_event(event_type: str, source: str, data: dict)` (L203) — Log a cross-model event
  - `add_signal(from_model: str, to_model: str, message: str, data: dict=None)` (L216) — Send a signal from one model to another
  - `get_signals(model_name: str, limit: int=10) -> List[Dict]` (L230) — Get signals intended for a model
  - `update_opportunity_lifecycle(opportunity_id: str, current_stage: str='discovered', statu, ...) -> Dict[str, Any]` (L237) — Persist a lifecycle snapshot for an opportunity in shared context.
  - `update_research_snapshot(research: Dict[str, Any]) -> Dict[str, Any]` (L260) — Persist a compact research snapshot so both models can reuse it.
  - `get_latest_research_snapshot() -> Optional[Dict[str, Any]]` (L280) — Return the latest shared research snapshot, if available.
  - `get_opportunity_lifecycle() -> List[Dict[str, Any]]` (L286) — Return recent opportunity lifecycle snapshots.
  - `query_model(model_name: str, question: str) -> str` (L296) — Query another model's context and get their relevant information.
  - `share_decision(model_name: str, decision: str, reasoning: List[str])` (L321) — Share a decision with other models
  - `get_working_directory() -> Path` (L339) — Get the path to the shared context file's directory


### `agents/brains/small_brain.py` — Small Brain — Provider adapter for the fast chat model. (476L)

**Functions:**
- `get_small_brain()` (L470) — Get or create the Small Brain singleton.

**Classes:**
- `class SmallBrainAdapter` (L24) — Interface to the fast chat model through the active provider.
  - `__init__(model=None, base_url=None)` (L27)
  - `_get_client()` (L59) — Get OpenAI client for llama-server.
  - `_dialogue_protocol() -> dict` (L76)
  - `_get_first_available_model() -> str` (L82) — Auto-detect first available model in llama-server.
  - `get_available_models() -> list` (L93) — Get list of all downloaded models.
  - `set_model(model_name: str)` (L104) — Switch to a different model.
  - `_start_got_turn(prompt: str)` (L108)
  - `_finish_got_turn(turn, response: str, status: str='completed', branch_candid, ...) -> str` (L112)
  - `_hardware_line() -> str` (L127) — One line describing the device this brain runs on (N-brain).
  - `_build_system_prompt(query: str='') -> str` (L164) — Build a tiered system prompt for the configured chat model.
  - `chat(user_message: str, history: list=None, system_prompt: str=N, ...) -> str` (L229) — Handle conversation with tool calling support.
  - `review(plan: str) -> str` (L434) — Review Big Brain's plan for red flags.
  - `should_escalate(user_message: str) -> bool` (L441) — Determine if a message needs Big Brain.
  - `classify(text: str) -> str` (L454) — Quick classification of an opportunity.
  - `search_opportunities(query: str) -> str` (L460) — Search for opportunities (placeholder for Discovery Engine integration).


### `agents/brains/worker_budget.py` — Context-window lookup for the legacy worker compatibility layer. (48L)

**Functions:**
- `model_context_tokens(model: str, ollama_available=..., cache=...) -> int` (L11) — Return a model context length with bounded Ollama probing and fallback.


### `agents/brains/worker_llm_mixin.py` — LLM retry/fallback orchestration for the legacy worker fa?ade. (229L)

**Classes:**
- `class WorkerLLMMixin` (L14)
  - `llm(system: str, user: str, chat=..., **kwargs) -> str` (L15) — Call LLM with retries, multiple providers, and max_tokens.


### `agents/brains/worker_provider.py` — Provider-value normalization helpers for the legacy worker layer. (21L)

**Functions:**
- `normalize_keep_alive(value) -> object` (L4) — Normalize Ollama keep-alive values to accepted forms.


### `agents/brains/worker_provider_calls.py` — Legacy provider-call compatibility mixin. (144L)

**Classes:**
- `class WorkerProviderCallsMixin` (L15)
  - `_call_openai(model: str, system: str, user: str, max_tokens: int, chat: bool=False) -> str` (L16)
  - `_call_anthropic(model: str, system: str, user: str, max_tokens: int, chat: bool=False) -> str` (L29)
  - `_call_ollama(model: str, system: str, user: str, max_tokens: int, chat: , ...) -> str` (L42)


### `agents/brains/worker_provider_mixin.py` — Provider registry and selection mixin for the legacy worker fa?ade. (354L)

**Classes:**
- `class WorkerProviderMixin` (L8)
  - `_chat_model_effective() -> str | None` (L9)
  - `_ollama_model_names() -> list[str]` (L22)
  - `_role_allows(ad: object, chat: bool) -> bool` (L46) — Whether this provider may serve the given role (main/chat).
  - `_build_provider_registry() -> list` (L77) — Return the ordered list of configured provider adapters.
  - `invalidate_provider_registry()` (L218) — v2.0.34ak: drop the cached adapter registry so the NEXT llm() call rebuilds
  - `_build_providers(chat: bool) -> list` (L227) — Return (name, func, model_key, default_model) tuples for available adapters.
  - `_cost_aware_enabled() -> bool` (L318)
  - `_cloud_failover_enabled() -> bool` (L321) — v2.1.37 (ARCH-ENG-044): whether cloud providers may be used as a
  - `_provider_out_price(model: str)` (L330) — D3: out-token price (USD/1M) for `model`, or None if unknown/free.
  - `_provider_hint(chat: bool) -> str | None` (L341) — Primary provider name for this mode (used to pick tokenizer/context hint).


### `agents/brains/worker_safety.py` — Filesystem and content safety helpers for legacy workers. (74L)

**Functions:**
- `is_safe_path(base: Path, candidate: Path) -> bool` (L24) — Ensure a candidate stays under base and cannot escape via a symlink.
- `is_safe_filename(name: str) -> bool` (L46)
- `is_safe_mime(file_path: Path) -> bool` (L52)
- `fingerprint(value: str) -> str` (L57)
- `ts_now() -> str` (L61)


### `agents/brains/worker_thinking.py` — Thinking-response helpers for the legacy worker compatibility layer. (79L)

**Functions:**
- `split_thinking(content: str)` (L10) — Return ``(thinking, answer)`` from a model response.
- `read_think_level(chat: bool) -> str` (L24)
- `model_emits_reasoning(model_name: str) -> bool` (L40) — Heuristic: does *model_name* look like a reasoning/thinking model?
- `record_model_reasoning(model_name: str) -> None` (L68) — Remember that *model_name* emitted a reasoning channel at runtime.


### `agents/brains/worker_workspace.py` — Workspace inspection helpers for legacy worker compatibility. (47L)

**Functions:**
- `project_file_tree(max_files: int=200) -> str` (L17) — Return a grounded text tree of real project files.


### `agents/dialogue/__init__.py` — dialogue package. (2L)


### `agents/dialogue/chat_completion.py` — Streaming OpenAI-compatible tool completion loop. (454L)
> _seed_executed_calls_from_history = cross-turn re-read guard (Phase A).

**Functions:**
- `_seed_executed_calls_from_history(history, executed_text_calls: set) -> None` (L13) — Pre-seed the executed-text-call set from prior turns in the transcript.
- `chat_with_tools(client, model: str, system_prompt: str, user_message: str, , ...) -> str` (L48)


### `agents/dialogue/chat_router.py` — (no module docstring) (220L)

**Functions:**
- `_format_lifecycle_status(lifecycle: List[dict], compact: bool=True) -> str` (L11) — Return a compact, human-readable lifecycle summary for chat prompts.

**Classes:**
- `class ChatDecision` (L63)
- `class ChatRouter` (L69) — Route human chat between chat and main-model workflows while building runtime context.
  - `__init__()` (L72)
  - `classify(message: str) -> ChatDecision` (L86)
  - `build_runtime_context(research_folder: Optional[str], user_message: str='', lifec, ...) -> str` (L96) — Build chat context.


### `agents/dialogue/discussion.py` — Bounded, evidence-aware discussion protocol for dual-brain collaboration. (102L)

**Classes:**
- `class DiscussionStatus(str, Enum)` (L12)
- `class DiscussionPurpose(str, Enum)` (L19)
- `class DiscussionTurn` (L28)
- `class BoundedDiscussion` (L39) — Coordinate a finite exchange without treating conversation as authority.
  - `__init__(goal: str, max_turns=...)` (L42)
  - `remaining_turns() -> int` (L55)
  - `evidence_ids() -> Set[str]` (L59)
  - `add_turn(turn: DiscussionTurn) -> bool` (L62) — Accept one turn, rejecting turns after terminal state or budget.
  - `block(reason: str) -> None` (L86)
  - `to_dict() -> dict` (L91)


### `agents/runtime/__init__.py` — Runtime services and telemetry package. (44L)


### `agents/runtime/agent.py` — Event-driven runtime for cooperating agents. (209L)

**Classes:**
- `class AgentEventKind(str, Enum)` (L19)
- `class AgentDescriptor` (L29)
- `class AgentState` (L37)
- `class AgentEvent` (L51)
- `class AgentRuntime` (L60) — Small deterministic scheduler for event-driven agent collaboration.
  - `__init__(goal: str, agents: Iterable[AgentDescriptor], bus=...)` (L63)
  - `publish(kind: AgentEventKind, source: str, payload=..., priority=...) -> AgentEvent` (L81)
  - `record_turn(agent_id: str, text: str, intents=...) -> AgentEvent` (L119)
  - `next_opportunity(exclude=...) -> AgentState | None` (L138)
  - `interrupt(source: str, target: str, reason: str) -> AgentEvent` (L161)
  - `set_availability(agent_id: str, availability: str) -> None` (L169)
  - `update_goal(goal: str) -> None` (L174)
  - `snapshot() -> dict[str, Any]` (L181)


### `agents/runtime/context.py` — Read-only live workspace context for the dual-brain prompts. (227L)

**Functions:**
- `register_component(name: str, component: Any) -> None` (L13) — Register a live GUI/domain component for read-only prompt context.
- `_component(name: str) -> Any` (L21)
- `_short(value: Any, limit: int=240) -> str` (L26)
- `_untrusted(value: Any, source: str, limit: int=240) -> str` (L31) — Bound external-origin text, neutralize injection, mark it UNTRUSTED.
- `_opportunity_context() -> list[str]` (L64)
- `_approval_context() -> list[str]` (L97)
- `_reputation_context() -> list[str]` (L123)
- `_paper_context() -> list[str]` (L138)
- `_analytics_context() -> list[str]` (L160)
- `_insights_context() -> list[str]` (L182)
- `build_workspace_context() -> str` (L198) — Return a bounded, read-only snapshot for model situational awareness.


### `agents/runtime/device_registry.py` — agents/runtime/device_registry.py — Detected compute devices + operator policy. (488L)

**Functions:**
- `_settings_path(root: Optional[str]=None) -> str` (L122)
- `policy_path(root: Optional[str]=None) -> str` (L127) — Return the device-policy file path, honoring the test isolation override.
- `load_policy(root: Optional[str]=None) -> DevicePolicy` (L146) — Read the device policy from settings.json (absent/partial -> defaults).
- `merge_settings_file(updates: dict, root: Optional[str]=None) -> bool` (L164) — Merge `updates` into settings.json, preserving every other top-level key.
- `save_policy(policy: DevicePolicy, root: Optional[str]=None) -> bool` (L223) — Merge the device policy into settings.json, preserving other keys.
- `_detect_cpu() -> ComputeDevice` (L284) — Best-effort CPU / system-RAM detection. Never raises.
- `_detect_gpus() -> List[ComputeDevice]` (L314) — Detect GPUs with stable UUIDs via nvidia-smi; fall back to the provider
- `detect_devices(include_cpu: bool=True) -> List[ComputeDevice]` (L366) — All detected compute devices: GPUs (by VRAM desc) then the CPU pool.
- `resolve_assignments(devices: List[ComputeDevice], policy: DevicePolicy) -> List[DeviceAssignment]` (L386) — Apply the operator policy to detected devices.
- `brain_placements(assignments: List[DeviceAssignment], base_port: int=1234) -> List[dict]` (L420) — Turn enabled assignments into ordered brain placements with ports.
- `format_assignments(assignments: List[DeviceAssignment]) -> str` (L469) — Human-readable summary for the Live Log / diagnostics.

**Classes:**
- `class ComputeDevice` (L51) — One detected compute device (a GPU or the CPU/RAM pool).
  - `is_gpu() -> bool` (L63)
  - `is_cpu() -> bool` (L67)
  - `capability_class() -> str` (L70) — 'big' | 'small' | 'none' by memory (and cores for CPU).
  - `label() -> str` (L86)
- `class DevicePolicy` (L96) — Per-device enable/role/model/settings choices, keyed by stable device id.
  - `is_enabled(dev: ComputeDevice, default: bool=True) -> bool` (L109)
  - `role_override(dev: ComputeDevice) -> str` (L112)
  - `model_for(dev: ComputeDevice) -> str` (L115)
  - `settings_for(dev: ComputeDevice) -> Dict[str, object]` (L118)
- `class DeviceAssignment` (L377) — A device paired with the brain class it will host under current policy.


### `agents/runtime/dual_brain.py` — agents/dual_brain_runtime.py — Canonical dual-brain runtime & configuration (v2.1). (1086L)
> MTP (ARCH-ENG-092) + mmproj auto-detect (ARCH-ENG-072) live here; --device CUDA{n} flag built here.

**Functions:**
- `_server_bin(prefix: str='') -> str` (L80)
- `estimate_model_size_b(model_name: str) -> Optional[float]` (L480) — Estimate total parameter size from a model filename or identifier.
- `is_cpu_decision_model(model_name: str, max_params_b: float=CPU_SMALL_MODEL_MAX_) -> bool` (L488) — Return whether a model is small enough for CPU decision support.
- `choose_cpu_decision_model(configured: str, candidates: List[str]) -> str` (L494) — Choose a configured or smallest discovered model for CPU fallback.
- `build_slot_config(placement: Dict[str, Any], slot: int, role: 'BrainRole') -> BrainConfig` (L503) — Build a BrainConfig for one device placement (N-brain slot 2+).
- `_apply_saved_settings(cfg: 'BrainConfig', saved: Dict[str, object]) -> None` (L544) — Apply a persisted per-device settings dict onto a slot's BrainConfig.
- `apply_hardware_fallback(config: BrainConfig, gpu_indexes: set[int]) -> BrainConfig` (L585) — Normalize a role config against detected GPUs without inventing hardware.
- `build_config(role: BrainRole, env: Optional[Dict[str, str]]=None) -> BrainConfig` (L620) — Build a ``BrainConfig`` for a role from environment (or an injected map).
- `default_contract() -> Dict[str, Any]` (L1064) — Return the canonical default role→GPU/endpoint contract as a dict.

**Classes:**
- `class BrainRole(str, Enum)` (L54)
- `class BrainConfig` (L127) — Resolved, validated configuration for one brain role.
  - `models_path() -> str` (L225) — HTTP path for listing models for this provider kind.
  - `build_llama_command(model_path: str='') -> List[str]` (L235) — Build the llama-server launch command for this role.
  - `get_template_info(model_path: str) -> dict` (L370) — Get template info for logging purposes.
  - `_model_needs_raise_exception(model_path: str) -> bool` (L386) — Check if a model's chat template uses raise_exception().
  - `_get_fallback_template(model_path: str) -> str` (L402) — Get a compatible built-in chat template for models with broken templates.
  - `to_dict() -> Dict[str, Any]` (L459)
- `class DualBrainRuntime` (L758) — Authoritative runtime/configuration owner for both brain roles.
  - `__init__(big: Optional[BrainConfig]=None, small: Optional[BrainConfig]=None)` (L768)
  - `from_env(env: Optional[Dict[str, str]]=None) -> 'DualBrainRuntime'` (L789)
  - `provider_diagnostics(env: Optional[Dict[str, str]]=None) -> Dict[str, Any]` (L794) — Return redacted normalized provider settings for operator diagnostics.
  - `config(role: BrainRole) -> BrainConfig` (L801)
  - `endpoint(role: BrainRole) -> str` (L804)
  - `model(role: BrainRole) -> str` (L807)
  - `device(role: BrainRole) -> int` (L810)
  - `set_model(role: BrainRole, model_name: str) -> None` (L813)
  - `slots() -> List[BrainConfig]` (L819) — Ordered brain slots (>= 2). Slots 0/1 are the BIG/SMALL role configs.
  - `slot_config(slot: int) -> Optional[BrainConfig]` (L828) — Return the config for slot ``slot`` (0-based), or None if out of range.
  - `slot_for_device(device_id: str) -> Optional[BrainConfig]` (L835) — Return the slot config bound to ``device_id`` (registry stable id).
  - `sync_slots(placements: List[Dict[str, Any]]) -> List[BrainConfig]` (L845) — Resize the slot list to match detected device placements.
  - `validate_isolation() -> Dict[str, Any]` (L940) — Confirm the canonical role→GPU pairing holds.
  - `_http_get(url: str, timeout: float) -> Optional[str]` (L966)
  - `list_models(role: BrainRole, refresh: bool=False) -> List[str]` (L976) — Return model ids available on a role's server. Bounded; [] if offline.
  - `health(role: BrainRole, refresh: bool=False) -> Dict[str, Any]` (L1008) — Health snapshot for a role. Never raises; reports reachable/offline.
  - `_model_ids_match(selected: str, reported: str) -> bool` (L1043)
  - `snapshot(refresh_health: bool=False) -> Dict[str, Any]` (L1054) — Full runtime snapshot for dashboards (per-role + isolation).


### `agents/runtime/hardware_plan.py` — agents/runtime/hardware_plan.py — Detect hardware and plan brain allocation. (239L)

**Functions:**
- `_classify(vram_gb: float) -> str` (L98)
- `detect_cpu_target() -> HardwareTarget` (L106) — Best-effort CPU / system-RAM detection. Never raises.
- `_gpu_targets_from_manager() -> List[HardwareTarget]` (L146) — Read detected GPUs from the ProviderManager singleton (no re-probe).
- `build_brain_plan(cpu_enabled: bool=False, base_port: int=1234) -> BrainPlan` (L163) — Detect hardware and recommend a brain allocation.
- `format_brain_plan(plan: BrainPlan) -> str` (L218) — Human-readable summary for the Live Log / diagnostics.

**Classes:**
- `class HardwareTarget` (L50) — One place a brain could run: a GPU or the CPU/system-RAM pool.
  - `is_gpu() -> bool` (L60)
  - `label() -> str` (L63)
- `class PlannedBrain` (L71) — A recommended brain placement produced by the planner.
  - `label() -> str` (L78)
- `class BrainPlan` (L84) — The full recommended allocation for the detected hardware.
  - `big_brain() -> Optional[PlannedBrain]` (L91)
  - `small_brain() -> Optional[PlannedBrain]` (L94)


### `agents/runtime/llm.py` — Standalone, dependency-light helpers for running LLMs across providers. Extracted (135L)

**Functions:**
- `model_arch_info(model: str, live=...) -> dict` (L15) — Return architecture metadata for an Ollama `model` (dense vs MoE, experts, params, context).
- `detect_vram_gb() -> int` (L29) — Best-effort detection of total GPU VRAM in GB (0 if none / unknown).
- `vram_gb() -> int` (L64)
- `num_gpu_for(model: str, chat: bool) -> int | None` (L71) — v2.0.34ab (Section E F5): resolve `num_gpu` (GPU layers) for an Ollama call.
- `estimate_tokens(text, provider=None)` (L100) — Rough token count for a prompt string. OpenAI uses tiktoken; else chars/4.
- `_trim_to_tokens(text, budget_tokens, provider=None)` (L114) — Keep the TAIL (most recent content); cut from the front when over budget.
- `fit_prompt_to_ctx(system, user, budget_tokens, provider=None)` (L124) — Defensively truncate (system, user) so est_tokens(system+user) <= budget.


### `agents/runtime/performance.py` — Provider-independent process and model performance telemetry. (97L)

**Classes:**
- `class PerformanceTelemetry` (L15) — Thread-safe counters and timings for runtime diagnostics.
  - `__init__() -> None` (L18)
  - `mark_startup_complete() -> float` (L31)
  - `record_prompt(chars: int, tokens: int=0) -> None` (L37)
  - `record_model_call(latency_ms: float, first_token_latency_ms=..., ok=...) -> None` (L42)
  - `record_retry(count: int=1) -> None` (L58)
  - `record_gui_update(count: int=1) -> None` (L62)
  - `snapshot() -> dict[str, Any]` (L66)


### `agents/runtime/services.py` — Runtime service helpers formerly provided by the library hub. (227L)

**Classes:**
- `class TaskQueue` (L17) — Priority task queue with deduplication (ignores exact duplicate tasks).
  - `__init__()` (L31)
  - `put(task: str, priority: int=5)` (L36)
  - `get(block: bool=True, timeout: float=1.0) -> Tuple[str, int]` (L45)
  - `clear()` (L60)
- `class AgentLogger` (L69) — Thin structured logger.  Writes to an AgentDB if provided, otherwise
  - `__init__(db=None, source: str='Agent', signal=None, max_buffer: int=500)` (L82)
  - `_emit(level: str, text: str)` (L89)
  - `info(text: str)` (L104)
  - `warn(text: str)` (L105)
  - `error(text: str)` (L106)
  - `debug(text: str)` (L107)
  - `event(name: str, data: Dict=None)` (L109)
  - `recent(n: int=20) -> List[str]` (L113)
- `class FileWatcher` (L120) — Watch a set of files/directories for changes via mtime polling.
  - `__init__(interval: float=5.0)` (L131)
  - `watch(path: str)` (L137)
  - `check() -> List[str]` (L141)
  - `_check_file(path: str, changed: List[str])` (L157)
- `class EmbeddingCache` (L171) — Simple keyword-based cache to avoid repeating very similar LLM calls.
  - `__init__(similarity_threshold: float=0.8, max_size: int=200)` (L186)
  - `_tokenize(text: str) -> frozenset` (L193)
  - `get(query: str) -> Optional[str]` (L196)
  - `put(key: str, value: str)` (L206)
  - `clear()` (L213)


### `agents/runtime/stats.py` — Thread-safe telemetry for the manager heartbeat loop. (62L)

**Classes:**
- `class RuntimeStats` (L8)
  - `__init__()` (L9)
  - `record_cycle(ms: float, ok=..., kind=...)` (L22)
  - `snapshot() -> dict` (L40)

