<!-- generated 48 files -->

### `agents/providers/__init__.py` — Provider adapters for MrBot1000 (v2.0.25). (30L)


### `agents/providers/anthropic_adapter.py` — Anthropic provider adapter (v2.0.25). (56L)

**Classes:**
- `class AnthropicAdapter` (L10)
  - `__init__(name: str='anthropic', api_key_env=..., default_model=..., , ...)` (L11)
  - `available() -> bool` (L23)
  - `complete(model: str, system: str, user: str, max_tokens: int, chat: bool=False, **kwargs) -> str` (L33)
  - `context_for(model: str) -> int` (L54)


### `agents/providers/context_table.py` — Static per-provider/model context-window table (v2.0.25). (63L)

**Functions:**
- `lookup_context(provider: str, model: str, default: int=128000) -> int` (L46) — Return the static context window for provider+model, or default.


### `agents/providers/gguf_meta.py` — agents/gguf_meta.py — dependency-light GGUF metadata reader (stdlib only). (426L)
> validate_model + arch_supported (unknown-arch pre-launch warning, v2.1.77).

**Functions:**
- `_read_val(f, vtype: int)` (L30)
- `_skip_val(f, vtype: int) -> None` (L55) — Advance the file pointer past one metadata value (used when we only need
- `_first(x)` (L77) — Scalar, or list -> max (MoE stores per-layer kv heads as arrays; the KV
- `read_metadata(path: str) -> Dict[str, Any]` (L85) — Return the model's GGUF metadata K/V as a dict. Empty on failure.
- `_skip_fast(f, vtype: int) -> None` (L110) — Advance past one value using seeks for fixed-size scalars and string
- `read_scalar_metadata(path: str, wanted_keys) -> Dict[str, Any]` (L142) — Read only ``wanted_keys`` from the GGUF header, skipping everything else.
- `read_header_metadata(path: str, max_array_len: int=4096) -> Dict[str, Any]` (L196) — Read every SCALAR/STRING K/V pair, and small arrays, skipping big arrays.
- `_skip_array_body(f, atype: int, alen: int) -> None` (L248) — Skip ``alen`` elements of type ``atype`` (header already consumed).
- `read_tensor_names(path: str) -> set[str]` (L271) — Read GGUF tensor names without touching tensor data.
- `validate_model(path: str) -> list[str]` (L296) — Return deterministic GGUF compatibility errors before server startup.
- `detect_arch(path: str) -> str` (L328) — Return the GGUF's architecture string ("" if unreadable).
- `arch_supported(path: str) -> bool` (L333) — True if the model's arch is in the known-supported set (soft check).
- `estimate_vram_gb(path: str, context: int=8192, kv_type_bytes: int=2) -> Dict[str, Any]` (L341) — Estimate a model's VRAM footprint.


### `agents/providers/huggingface_models.py` — Hugging Face GGUF discovery and safe download helpers. (557L)

**Functions:**
- `provider_install_targets() -> list[ProviderInstallTarget]` (L33) — Return provider-aware destinations using environment overrides first.
- `_https_url(url: str) -> str` (L127)
- `_validate_response_url(url: str) -> str` (L137) — Reject redirects outside Hugging Face and its signed download hosts.
- `_parse_params(text: str) -> Optional[float]` (L142)
- `_parse_context(text: str) -> Optional[int]` (L152)
- `_parse_quantization(name: str) -> str` (L158)
- `_architecture(text: str) -> str` (L167)
- `_is_moe(text: str) -> Optional[bool]` (L175)
- `_artifact_from_sibling(repo_id: str, sibling: dict[str, Any]) -> Optional[GGUFArtifact]` (L188)
- `free_space(path: Path) -> int` (L447)
- `download_artifact(artifact: GGUFArtifact, destination: Path, pause_event: Any, ...) -> Path` (L451) — Download atomically, resuming a partial file and verifying known hashes.
- `_response_total_bytes(response: requests.Response, existing: int, artifact_size: int, resumed: bool) -> int` (L548) — Normalize full and ranged HTTP lengths into one absolute file size.

**Classes:**
- `class ProviderInstallTarget` (L23) — A provider-specific destination and the action needed after download.
- `class GGUFArtifact` (L52)
  - `size_label() -> str` (L60)
- `class HuggingFaceGGUFModel` (L72)
  - `type_label() -> str` (L95)
  - `params_label() -> str` (L103)
  - `size_band() -> str` (L107)
  - `size_label() -> str` (L115)
  - `site_url() -> str` (L123)
- `class HuggingFaceModelService` (L205) — Small API client kept independent from Qt for easy testing.
  - `__init__(session: Optional[requests.Session]=None)` (L208)
  - `search(query: str='', page: int=0, limit: int=100, task: str='', library: str='') -> list[HuggingFaceGGUFModel]` (L212)
  - `_summary_model(item: dict[str, Any]) -> HuggingFaceGGUFModel` (L240) — Build a result from the list endpoint without N+1 network calls.
  - `inspect(repo_id: str, summary: Optional[dict[str, Any]]=None) -> HuggingFaceGGUFModel` (L268)
  - `_get_model(repo_id: str) -> dict[str, Any]` (L339)
  - `_get_raw(repo_id: str, filename: str) -> str` (L345)
  - `_get_json(repo_id: str, filename: str) -> dict[str, Any]` (L353)
  - `_get_tree(repo_id: str) -> list[dict[str, Any]]` (L364)
  - `_base_model(data: dict[str, Any], card: dict[str, Any], tags: list[str]) -> str` (L374)
  - `_config_architecture(config: dict[str, Any]) -> str` (L386)
  - `_config_moe(config: dict[str, Any]) -> Optional[bool]` (L394)
  - `_config_context(config: dict[str, Any]) -> Optional[int]` (L403)
  - `_description(readme: str, data: dict[str, Any], base_data: dict[str, Any]) -> str` (L417)
  - `_capabilities(data: dict[str, Any], tags: list[str], readme: str) -> list[str]` (L427)
  - `_category(task: str, tags: list[str], capabilities: list[str]) -> str` (L436)


### `agents/providers/model_capabilities.py` — Model capability detection — Multi-Token Prediction (Phase G, ARCH-ENG-092). (70L)
> MTP detection via tensor names; fail-safe unknown=unsupported.

**Functions:**
- `detect_mtp(model_path: str) -> Dict[str, Any]` (L27) — Return {"supported": bool, "reason": str, "head_tensors": int}.
- `mtp_tooltip(model_path: str) -> str` (L60) — A short, human sentence for the GUI tooltip / status.


### `agents/providers/model_profile.py` — Model-profile detection for MrBot1000. (559L)

**Functions:**
- `_read_gguf_metadata(model_path: str) -> dict[str, Any]` (L309) — Read GGUF metadata from a model file (best-effort).
- `detect_family_from_metadata(model_path: str) -> Optional[str]` (L318) — Detect model family from GGUF tokenizer metadata.
- `detect_family_from_filename(model_path: str) -> Optional[str]` (L352) — Detect model family from filename patterns.
- `detect_family_from_server_props(base_url: str) -> Optional[str]` (L361) — Detect model family from llama-server /props endpoint.
- `detect_model_family(model_path: Optional[str]=None, base_url: Optional[str]=None) -> str` (L391) — Detect model family using all available sources.
- `get_profile(family: str) -> dict[str, Any]` (L426) — Get a model-family profile by ID, falling back to generic chatml.
- `get_model_profile(model_path: Optional[str]=None, base_url: Optional[str]=Non, ...) -> dict[str, Any]` (L433) — Detect family and return its profile.
- `supports_tool_calling(profile: dict[str, Any]) -> bool` (L461) — Whether the model supports OpenAI-style function calling.
- `supports_thinking(profile: dict[str, Any]) -> bool` (L466) — Whether the model supports a thinking/reasoning mode.
- `wants_enable_thinking(profile: dict[str, Any]) -> bool` (L471) — Whether to send extra_body={"chat_template_kwargs":{"enable_thinking":True}}.
- `needs_flat_system(profile: dict[str, Any]) -> bool` (L476) — Whether the system prompt must be folded into the first user message.
- `supports_vision(profile: dict[str, Any] | None=None, model_name: str | None=None) -> bool` (L493) — Best-effort: whether the model can accept image input.
- `extract_thinking_from_content(content: str, profile: dict[str, Any]) -> tuple[str, str]` (L514) — Extract thinking blocks from content based on family format.
- `build_extra_body(profile: dict[str, Any], enable_thinking: bool=True) -> dict[str, Any]` (L542) — Build the extra_body dict for a model-family-compatible request.
- `describe_profile(profile: dict[str, Any]) -> str` (L552) — Human-readable summary for logging.


### `agents/providers/model_recommendations.py` — Per-model recommended llama.cpp settings (Phase G, ARCH-ENG-095). (154L)
> recommend(path) joins family + MTP detection into per-model settings.

**Functions:**
- `_detect_family(model_path: str) -> Optional[str]` (L111)
- `recommend(model_path: str) -> Dict[str, Any]` (L119) — Return recommended settings for a model, joined with live MTP detection.
- `summary(model_path: str) -> str` (L143) — A short human-readable recommendation line for the GUI status.


### `agents/providers/ollama_adapter.py` — Ollama provider adapter (v2.0.25). (99L)

**Functions:**
- `_normalize_keep_alive(v: str) -> str | int` (L15)

**Classes:**
- `class OllamaAdapter` (L24)
  - `shutdown_executor()` (L28) — Cancel queued calls during application shutdown.
  - `__init__(name: str='ollama', disabled_env=..., order=..., chat_model=...)` (L32)
  - `available() -> bool` (L41)
  - `complete(model: str, system: str, user: str, max_tokens: int, chat: bool=False, **kwargs) -> str` (L50)
  - `context_for(model: str) -> int` (L84)


### `agents/providers/openai_compatible.py` — OpenAI-compatible provider adapter (v2.0.25). (370L)

**Functions:**
- `get_llama_server_capabilities(base_url: str, timeout: float=1.5) -> dict` (L34) — Read optional llama-server chat-template capabilities.
- `resolve_chat_protocol(model: str, capabilities: dict | None, default_tools: bool=False) -> dict` (L69) — Resolve message/tool compatibility from server facts with safe fallback.
- `os_getenv(key: str, default: str='') -> str` (L235) — Read an env var with comment-as-value corruption removed.
- `_stream_timeout_seconds() -> float` (L248) — Return a bounded provider timeout from the environment.
- `_build_provider_timeout(openai_module, read=...)` (L260) — Build an openai.Timeout with a short connect and a long read.
- `_connect_timeout_seconds() -> float` (L276) — Return the TCP-connect timeout for provider calls.
- `_is_safe_base_url(url: str) -> bool` (L290) — SSRF guard for provider base_url (v2.1: relaxed for local providers).

**Classes:**
- `class OpenAICompatibleAdapter` (L89)
  - `__init__(name: str, api_key_env=..., base_url=..., default_model=..., ...)` (L90)
  - `available() -> bool` (L105)
  - `complete(model: str, system: str, user: str, max_tokens: int, chat: , ...) -> str` (L124) — Call the model and return the answer text.
  - `context_for(model: str) -> int` (L228)
- `class LlamaCppAdapter(OpenAICompatibleAdapter)` (L327) — Local llama.cpp (llama-server) provider - no API key required.
  - `__init__(name, api_key_env=..., base_url=..., default_model=..., con, ...)` (L334)
  - `available() -> bool` (L349)
  - `complete(model, system, user, max_tokens, chat=False, **kwargs)` (L363)


### `agents/providers/provider_hot_reload.py` — agents/provider_hot_reload.py — Hot-reload provider configuration without restart. (143L)

**Classes:**
- `class ProviderHotReload` (L19) — Monitors and applies provider configuration changes at runtime.
  - `__init__()` (L24)
  - `instance() -> 'ProviderHotReload'` (L33)
  - `register_callback(callback: Callable[[Dict[str, str]], Non)` (L38) — Register a callback to be called when config changes.
  - `unregister_callback(callback: Callable[[Dict[str, str]], Non)` (L43) — Unregister a callback.
  - `start_monitoring(interval: float=2.0)` (L48) — Start monitoring .env file for changes.
  - `stop_monitoring()` (L56) — Stop monitoring.
  - `_monitor_loop(interval: float)` (L62) — Main monitoring loop.
  - `_check_for_changes()` (L71) — Check if .env file has changed and notify callbacks.
  - `_read_env_file() -> Dict[str, str]` (L101) — Read .env file and return config dict.
  - `_notify_callbacks(changes: Dict[str, str])` (L115) — Notify all registered callbacks of config changes.
  - `apply_changes(changes: Dict[str, str])` (L123) — Apply configuration changes to the running application.


### `agents/providers/provider_lifecycle.py` — Provider probing and model lifecycle operations independent of Qt. (189L)

**Classes:**
- `class ProviderStatusChecker` (L13) — Probe local and controllable provider endpoints.
  - `check_llama_server(port=1234, timeout=10, refresh=False)` (L21)
  - `check_endpoint(url, timeout=10)` (L40)
  - `_provider_root(endpoint)` (L50)
  - `check_loaded_provider(provider, endpoint, timeout=5)` (L54)
  - `load_provider_model(provider, endpoint, model, timeout=30)` (L83)
  - `unload_provider_model(provider, endpoint, model='', timeout=30)` (L97)
  - `_post_json(url, body, timeout)` (L125)
  - `clear_cache(port=None)` (L140)
  - `extract_model_ids(data)` (L148)
  - `model_ids_match(selected, reported)` (L163)
  - `check_llama_process(port=None)` (L174)


### `agents/providers/provider_manager.py` — agents/provider_manager.py — Provider detection and management for MrBot1000. (613L)

**Functions:**
- `supported_tensor_types(compute_capability: str='', cpu: bool=False) -> List[str]` (L66) — Return conservative llama.cpp KV types for detected hardware.

**Classes:**
- `class ProviderType(str, Enum)` (L24)
- `class ProviderStatus(str, Enum)` (L39)
- `class GPUInfo` (L47) — Information about a GPU.
  - `tensor_types() -> List[str]` (L61) — Tensor/KV precisions appropriate for this CUDA capability.
- `class ProviderInfo` (L87) — Information about a provider.
- `class ProviderManager` (L106) — Detects and manages providers.
  - `__init__()` (L111)
  - `instance() -> 'ProviderManager'` (L122)
  - `_settings(name: str)` (L128) — Read provider connection settings from the normalized authority.
  - `detect_providers() -> Dict[str, ProviderInfo]` (L133) — Detect all available providers.
  - `_detect_gpus()` (L168) — Detect GPUs using nvidia-smi.
  - `_detect_local_providers()` (L195) — Detect local providers.
  - `refresh_provider_models(provider_name: str) -> List[str]` (L218) — Refresh models for one local provider without rebuilding all state.
  - `_detect_ollama()` (L257) — Detect Ollama.
  - `_detect_vllm()` (L285) — Detect vLLM.
  - `_detect_lm_studio()` (L317) — Detect LM Studio.
  - `_detect_koboldcpp()` (L350) — Detect KoboldCpp.
  - `_detect_llamacpp()` (L380) — Detect llama.cpp.
  - `_detect_cloud_providers()` (L415) — Detect cloud providers.
  - `get_providers(detect: bool=True) -> Dict[str, ProviderInfo]` (L464) — Get all detected providers.
  - `get_gpus(detect: bool=True) -> List[GPUInfo]` (L477) — Get all detected GPUs (see ``get_providers`` for ``detect``).
  - `get_running_providers(detect: bool=True) -> Dict[str, ProviderInfo]` (L483) — Get only running providers (see ``get_providers`` for ``detect``).
  - `warm_up() -> None` (L488) — Kick off the initial detection on a background daemon thread.
  - `_detect_once() -> Dict[str, ProviderInfo]` (L504) — Run the initial detection exactly once, even under concurrent
  - `normalize_provider_name(name: str) -> str` (L516) — Return the runtime/provider-config spelling for a provider name.
  - `resolve_enabled_provider(local: bool=True) -> Optional[str]` (L525) — Resolve the explicitly enabled provider, or ``None``.
  - `get_local_providers() -> Dict[str, ProviderInfo]` (L546) — Get local providers.
  - `get_cloud_providers() -> Dict[str, ProviderInfo]` (L550) — Get cloud providers.
  - `set_provider_status(name: str, status: str | ProviderStatus) -> bool` (L554) — Set the runtime status for a provider without losing it on re-detect.
  - `get_provider(name: str, detect: bool=True) -> Optional[ProviderInfo]` (L562) — Get a specific provider (see ``get_providers`` for ``detect``).
  - `get_gpu(index: int) -> Optional[GPUInfo]` (L566) — Get a specific GPU.
  - `assign_provider_to_gpu(provider_name: str, gpu_index: int)` (L573) — Assign a provider to a GPU.
  - `get_summary() -> Dict[str, Any]` (L581) — Get a summary of all providers and GPUs.


### `agents/knowledge/__init__.py` — knowledge package. (2L)


### `agents/knowledge/help_catalog.py` — agents/help_catalog.py — Static feature-help catalog for MrBot1000 v2.1 (v2.1). (576L)

**Functions:**
- `lookup(keyword: str='') -> List[dict]` (L539) — Return catalog entries matching keyword (case-insensitive substring).
- `catalog_text() -> str` (L560) — Return a readable plain-text rendering of every catalog entry.


### `agents/knowledge/layered_memory.py` — Layered, freshness-aware retrieval over the existing program memory store. (144L)

**Classes:**
- `class MemoryLayer(str, Enum)` (L11)
- `class MemoryEntry` (L34)
  - `is_expired(now: Optional[float]=None) -> bool` (L52)
  - `is_stale(max_age_seconds: Optional[float], now: Optional[float]=None) -> bool` (L62)
- `class LayeredMemoryRetriever` (L75) — Retrieve memories by layer without promoting or mutating them.
  - `__init__(database)` (L78)
  - `layer_for(category: str, source: str='') -> MemoryLayer` (L82)
  - `retrieve(query: str='', layers=..., limit=..., min_confidence=..., now=..., max_age_seconds=...) -> List[MemoryEntry]` (L94)
  - `_confidence(row: dict) -> float` (L136)


### `agents/knowledge/llama_setting_help.py` — Short help text for the advanced llama.cpp settings (Phase G, ARCH-ENG-094). (71L)
> LLAMA_SETTING_HELP catalog backs Provider Control tooltips + '?' button.

**Functions:**
- `tooltip(key: str, default: str='') -> str` (L65) — Return the help text for a setting key, or ``default`` if unknown.


### `agents/knowledge/program_knowledge.py` — (no module docstring) (429L)

**Functions:**
- `get_database() -> MemoryDatabase` (L409) — Get or create the memory database singleton.
- `get_personality_engine() -> PersonalityEngine` (L416) — Get or create the personality engine singleton.
- `get_knowledge_context() -> KnowledgeContext` (L423) — Get or create the knowledge context singleton.

**Classes:**
- `class ProgramKnowledge` (L24) — Static knowledge about MrBot1000 that both brains need.
- `class MemoryDatabase` (L108) — Persistent memory storage for both brains.
  - `__init__(db_path: Path=DB_PATH)` (L111)
  - `_connect() -> sqlite3.Connection` (L115) — Open a short-lived connection tuned for concurrent local access.
  - `_init_db()` (L123) — Initialize the database tables.
  - `add_memory(category: str, title: str, content: str, importance: float=, ...)` (L172) — Add a new memory.
  - `get_memories(category: str=None, limit: int=10, min_importance: float=0.0) -> List[Dict]` (L186) — Retrieve memories, optionally filtered by category.
  - `search_memories(query: str, limit: int=5) -> List[Dict]` (L204) — Search memories by content.
  - `log_conversation(brain: str, role: str, message: str, context: str='')` (L215) — Log a conversation turn.
  - `get_conversation_history(brain: str, limit: int=20) -> List[Dict]` (L223) — Get recent conversation history for a brain.
  - `update_personality(brain: str, trait: str, value: float)` (L234) — Update a personality trait for a brain.
  - `get_personality(brain: str) -> Dict[str, float]` (L242) — Get all personality traits for a brain.
  - `log_decision(decision: str, outcome: str=None, success: int=None, lesson: str='')` (L251) — Log a decision and its outcome for learning.
  - `get_lessons(limit: int=10) -> List[Dict]` (L259) — Get recent lessons learned from decisions.
- `class PersonalityEngine` (L271) — Dynamic personality system that evolves based on interactions.
  - `__init__(db: MemoryDatabase)` (L287)
  - `get_system_prompt_addon(brain: str) -> str` (L290) — Generate a personality addon for the system prompt.
  - `evolve_from_interaction(brain: str, user_message: str, response: str)` (L320) — Evolve personality based on interaction patterns.
  - `_adjust_trait(brain: str, trait: str, delta: float)` (L341) — Adjust a personality trait.
- `class KnowledgeContext` (L352) — Builds context from knowledge base and memory for injection into prompts.
  - `__init__(db: MemoryDatabase)` (L355)
  - `build_context(brain: str, query: str='') -> str` (L358) — Build a context string for the given brain and query.


### `agents/knowledge/prompt_assembly.py` — Shared prompt assembly helpers for the two model adapters. (25L)

**Functions:**
- `assemble_role_prompt(base_prompt: str, role: str, query: str, personality, knowl, ...) -> str` (L4) — Append role-specific material in one predictable order.


### `agents/knowledge/prompt_sanitize.py` — MrBot1000/agents/prompt_sanitize.py — Prompt-injection hardening for untrusted text. (110L)

**Functions:**
- `neutralize_instructions(text: str) -> str` (L75) — Best-effort strip of common injection patterns from untrusted text.
- `sanitize_external_text(text: str, source=...) -> str` (L89) — Sanitize untrusted external text before it enters an LLM prompt.


### `agents/knowledge/prompt_utils.py` — Prompt construction and structured response helpers. (172L)

**Classes:**
- `class ChainOfThought` (L10) — Accumulate reasoning steps and render them into a single prompt section.
  - `__init__()` (L22)
  - `step(label: str, content: str) -> 'ChainOfThought'` (L25)
  - `render(numbered: bool=True) -> str` (L29)
  - `clear()` (L36)
- `class PromptBuilder` (L46) — Fluent helper for building structured prompts.
  - `__init__()` (L60)
  - `role(description: str) -> 'PromptBuilder'` (L63)
  - `context(text: str, label: str='CONTEXT') -> 'PromptBuilder'` (L67)
  - `instruction(text: str) -> 'PromptBuilder'` (L71)
  - `constraint(text: str) -> 'PromptBuilder'` (L75)
  - `example(text: str) -> 'PromptBuilder'` (L79)
  - `raw(text: str) -> 'PromptBuilder'` (L83)
  - `build(separator: str='\n\n') -> str` (L87)
  - `build_system() -> str` (L96) — Return only ROLE + CONSTRAINT lines — suitable as system prompt.
- `class ResponseParser` (L108) — Parse key:value fields and JSON blocks from LLM responses.
  - `__init__(text: str)` (L119)
  - `field(key: str, default: str='') -> str` (L122) — Extract 'KEY: value' from the text (case-insensitive).
  - `json_list() -> List[str]` (L128) — Extract the first JSON array found in the text.
  - `json_object() -> Dict` (L138) — Extract the first JSON object found in the text.
  - `has_keyword(*keywords) -> bool` (L148)
  - `classify(options: Dict[str, List[str]], default: str='unknown') -> str` (L152) — Classify response by counting keyword matches per option.


### `agents/knowledge/prompting_engine.py` — Prompting Engine for MrBot1000 — adaptive prompt construction. (485L)

**Functions:**
- `prompt_budget(context: Optional[Dict]=None) -> PromptBudget` (L54) — Resolve one bounded prompt mode from request context or environment.
- `prompt_telemetry() -> Dict[str, Any]` (L66) — Return a copy of prompt-size telemetry for diagnostics and tests.
- `_record_prompt(mode: str, technique: str, char_count: int) -> None` (L78)
- `_bounded_text(text: str, limit: int) -> str` (L91)
- `enforce_prompt_budget(prompt: str, context: Optional[Dict]=None) -> str` (L98) — Bound prompts supplied by callers that bypass ``adaptive_prompt``.
- `select_technique(task_type: str, context: Optional[Dict]=None) -> str` (L183) — Select the best prompting technique for a task type.
- `get_technique_suffix(technique_key: str) -> str` (L230) — Get the prompt suffix for a technique.
- `build_few_shot_examples(task_type: str) -> List[Dict[str, str]]` (L236) — Return few-shot examples for a task type.
- `adaptive_prompt(task_type: str, base_prompt: str, context: Optional[Dict]=N, ...) -> str` (L280) — Construct an adaptive prompt with the right technique + memory.
- `_memory_suffix_for_task(task_type: str) -> str` (L328) — Retrieve memory of successful patterns for a task type.
- `record_successful_pattern(task_type: str, technique: str, tips: List[str], success: bool=True)` (L353) — Record a successful/unsuccessful prompt pattern for future use.
- `get_brain_recommendation(brain_role: str, task_type: str, model_path: str='', model_name: str='') -> Dict[str, Any]` (L404) — Get recommendations for which prompting technique to use.
- `_detect_param_size(model_path: str='', model_name: str='') -> float` (L450) — Detect model parameter count in billions.

**Classes:**
- `class PromptBudget` (L29) — Bound prompt growth without changing the public technique API.


### `agents/knowledge/proposal_reviewer.py` — agents/proposal_reviewer.py — Pre-submission review gate (A1). (208L)

**Functions:**
- `_extract_requirements(job_text: str) -> List[str]` (L78) — Pull candidate requirement strings from a job posting.
- `_coverage(requirements: List[str], cover: str) -> (float, List[str])` (L100) — Return (coverage_fraction, missing_list).

**Classes:**
- `class ReviewResult` (L32)
  - `summary() -> str` (L43)
- `class ProposalReviewer` (L132) — Content-quality + requirements-coverage gate for gig proposals.
  - `__init__(analyst=None)` (L135)
  - `review(job_description: str, cover: str, job_title: str='') -> ReviewResult` (L139) — Run the full gate. Returns a ReviewResult (never raises).


### `agents/knowledge/proposal_templates.py` — Proposal intro A/B rotation + win tracking (v2.0.34w, Section D2). (129L)

**Functions:**
- `_variant_id(idx: int) -> str` (L43)
- `_idx_from_variant(variant: str) -> int` (L47)
- `pick_intro(platform: str, memory=None) -> str` (L54) — Return the intro text to use for ``platform``.
- `best_intro(platform: str, memory=None) -> Optional[str]` (L67) — Return the best variant id for ``platform`` once enough samples exist.
- `record_win(platform: str, variant: str, memory=None) -> None` (L109) — Persist a proposal win for ``variant`` on ``platform``.
- `record_loss(platform: str, variant: str, memory=None) -> None` (L120) — Persist a proposal loss for ``variant`` on ``platform``.


### `agents/knowledge/proposal_writer.py` — agents/proposal_writer.py — Proposal/cover letter writer for freelance gigs (v2.1 Path 1). (121L)

**Classes:**
- `class ProposalDraft` (L16) — A generated proposal draft.
- `class ProposalWriter` (L28) — Write tailored proposals for freelance opportunities.
  - `__init__(persona_name: str='Jacob')` (L31)
  - `write(opportunity: Dict[str, Any], tone: str='professional') -> ProposalDraft` (L34) — Write a proposal for an opportunity.
  - `_generate_body(title: str, description: str, skills: List[str], tone: str) -> str` (L55) — Generate proposal body.
  - `_pick_intro(tone: str) -> str` (L72)
  - `_pick_skill_line(skills: List[str]) -> str` (L79)
  - `_pick_evidence(skills: List[str]) -> str` (L84)
  - `_pick_close(tone: str) -> str` (L93)
  - `_estimate_bid(budget: str, description: str) -> str` (L99) — Estimate a reasonable bid.
  - `batch_write(opportunities: List[Dict[str, Any]], tone: str='professional') -> List[ProposalDraft]` (L118) — Write proposals for multiple opportunities.


### `agents/knowledge/workshop.py` — agents/workshop.py — Workshop workspace manager for MrBot1000 personas. (890L)

**Functions:**
- `_atomic_write_json(path: str, data: Any) -> None` (L29) — Write `data` to `path` atomically (temp + fsync + os.replace).
- `get_workshop() -> Workshop` (L801) — Get the global Workshop instance.
- `read_workshop_file(filepath: str) -> str` (L811) — Read a file from the workshop.
- `write_workshop_file(filepath: str, content: str) -> bool` (L815) — Write a file to the workshop.
- `list_workshop_files(subdir: str='') -> List[Dict[str, Any]]` (L819) — List files in a workshop subdirectory.
- `search_workshop(query: str) -> List[Dict[str, str]]` (L823) — Search workshop files.
- `create_proposal(title: str, client: str, description: str, **kwargs) -> str` (L827) — Create a new proposal.
- `create_research_note(title: str, content: str, **kwargs) -> str` (L831) — Create a research note.
- `get_template(name: str) -> str` (L835) — Get a template.
- `get_workshop_storage() -> Dict[str, int]` (L840) — Return current workshop quota and free-space statistics.

**Classes:**
- `class Workshop` (L85) — Workspace manager for persona agents.
  - `__init__(root: str=None, max_bytes: int=None)` (L88)
  - `_ensure_dirs()` (L103) — Create all workshop directories if they don't exist.
  - `_safe_path(filepath: str) -> Optional[str]` (L108) — Resolve a path strictly inside this workshop root.
  - `_usage_bytes() -> int` (L122)
  - `storage_stats() -> Dict[str, int]` (L132) — Return quota and physical free-space information for the workshop.
  - `_can_write(path: str, content_size: int) -> bool` (L143)
  - `create_folder(folder: str) -> bool` (L154) — Create an organized folder inside the workshop root.
  - `read_file(filepath: str) -> str` (L167) — Read a file from the workshop.
  - `write_file(filepath: str, content: str) -> bool` (L178) — Write a file to the workshop.
  - `append_file(filepath: str, content: str) -> bool` (L195) — Append to a file in the workshop.
  - `list_files(subdir: str='') -> List[Dict[str, Any]]` (L212) — List files in a workshop subdirectory.
  - `list_dirs(subdir: str='') -> List[str]` (L235) — List subdirectories.
  - `file_exists(filepath: str) -> bool` (L245) — Check if a file exists.
  - `get_file_info(filepath: str) -> Dict[str, Any]` (L250) — Get file info.
  - `create_proposal(title: str, client: str, description: str, platform: str='', ...) -> str` (L269) — Create a new proposal document.
  - `get_proposal(filename: str) -> str` (L312) — Read a proposal file.
  - `list_proposals() -> List[Dict[str, Any]]` (L316) — List all proposals.
  - `update_proposal_status(filename: str, status: str) -> bool` (L320) — Update proposal status.
  - `add_research(title: str, content: str, tags: List[str]=None) -> str` (L331) — Add a research note.
  - `read_research(filename: str) -> str` (L362) — Read a research file.
  - `list_research() -> List[Dict[str, Any]]` (L366) — List all research files.
  - `create_script(name: str, language: str, description: str, code: str) -> str` (L372) — Create a new script.
  - `read_script(filename: str) -> str` (L403) — Read a script file.
  - `list_scripts() -> List[Dict[str, Any]]` (L407) — List all scripts.
  - `create_application(platform: str, job_type: str, details: Dict[str, str]) -> str` (L413) — Create a job application document.
  - `list_applications() -> List[Dict[str, Any]]` (L446) — List all applications.
  - `add_account(platform: str, username: str, email: str, password: str='', url: str='', notes: str='') -> bool` (L452) — Add a platform account.
  - `get_account(platform: str) -> Dict[str, str]` (L479) — Get account info for a platform.
  - `list_accounts() -> List[Dict[str, str]]` (L484) — List all accounts.
  - `remove_account(platform: str) -> bool` (L489) — Remove an account.
  - `_load_accounts() -> Dict[str, Dict[str, str]]` (L503) — Load accounts from file.
  - `_save_accounts(accounts: Dict[str, Dict[str, str]])` (L523) — Save accounts to file atomically (temp + fsync + os.replace).
  - `add_payment_method(method: str, identifier: str, memo: str='', is_crypto: bool=False) -> bool` (L534) — Add a payment method.
  - `get_payment_method(method: str) -> Dict[str, str]` (L557) — Get payment method info.
  - `list_payment_methods() -> List[Dict[str, str]]` (L562) — List all payment methods.
  - `_load_payments() -> Dict[str, Dict[str, str]]` (L567) — Load payments from file.
  - `_save_payments(payments: Dict[str, Dict[str, str]])` (L586) — Save payments to file atomically (temp + fsync + os.replace).
  - `add_deliverable(title: str, content: str, client: str='', platform: str='') -> str` (L592) — Add a deliverable.
  - `list_deliverables() -> List[Dict[str, Any]]` (L613) — List all deliverables.
  - `get_template(template_name: str) -> str` (L619) — Get a template by name.
  - `save_template(name: str, content: str) -> str` (L700) — Save a custom template.
  - `add_note(title: str, content: str, tags: List[str]=None) -> str` (L709) — Add a note.
  - `list_notes() -> List[Dict[str, Any]]` (L729) — List all notes.
  - `search_files(query: str, subdir: str='') -> List[Dict[str, str]]` (L735) — Search files by name or content.
  - `get_stats() -> Dict[str, int]` (L773) — Get workspace statistics.
  - `get_workspace_summary() -> str` (L782) — Get a summary of the workspace.


### `agents/integrations/__init__.py` — Optional external platform and provider integrations. (3L)


### `agents/integrations/browser.py` — agents/web_controller.py — Unified web controller with search, browsing, scraping (v2.1 Phase 2/3). (415L)

**Functions:**
- `_robots_checker()` (L37) — Lazy singleton RobotsChecker (caches fetched robots.txt per host).

**Classes:**
- `class WebController` (L46)
  - `__init__(headless: bool=True, timeout: int=30)` (L47)
  - `search(query: str, max_results: int=8) -> Dict[str, Any]` (L55)
  - `search_news(query: str, max_results: int=8) -> Dict[str, Any]` (L75)
  - `ddgr_fallback(query: str, max_results: int=5) -> Dict[str, Any]` (L97) — Fallback search using duckduckgo-search if ddgs is missing.
  - `read_page(url: str) -> Dict[str, Any]` (L115) — Read a page and extract usable data, escalating to a headless
  - `_read_with_playwright(url: str) -> Dict[str, Any]` (L200) — One headless-browser attempt for JS-rendered / bot-gated pages.
  - `scrape(url: str) -> Dict[str, Any]` (L240) — Scrape a URL and return structured data.
  - `_ensure_browser()` (L272)
  - `browse(url: str) -> Dict[str, Any]` (L282)
  - `screenshot(url: str) -> Dict[str, Any]` (L314)
  - `close()` (L328)
  - `check_site(url: str) -> Dict[str, Any]` (L339)
  - `get_domain_info(url: str) -> Dict[str, str]` (L356)
  - `extract_emails(text: str) -> List[str]` (L367)
  - `extract_phones(text: str) -> List[str]` (L372)
  - `extract_prices(text: str) -> List[str]` (L383)
  - `extract_socials(text: str) -> List[str]` (L388)
  - `format_search(data: Dict[str, Any]) -> str` (L392)
  - `format_page(page: Dict[str, Any]) -> str` (L403)


### `agents/integrations/crypto.py` — agents/crypto_payments.py — Real crypto payment integration (v2.1 Path 3). (258L)

**Classes:**
- `class CryptoPaymentError(Exception)` (L29)
- `class CryptoPaymentRequest` (L34)
  - `to_dict() -> Dict[str, Any]` (L48)
- `class CryptoPayments` (L65) — Handle real crypto payments with safety gates.
  - `__init__(wallet_manager: WalletManager, human_approval_required: bool=True)` (L68)
  - `_check_sdks() -> Dict[str, bool]` (L75)
  - `get_sdk_status() -> Dict[str, Any]` (L85)
  - `create_payment(from_address: str, to_address: str, amount: float, currency, ...) -> CryptoPaymentRequest` (L92) — Create a payment request.
  - `simulate_payment(request: CryptoPaymentRequest) -> Dict[str, Any]` (L125) — Simulate a payment locally (no chain interaction).
  - `try_real_payment(request: CryptoPaymentRequest, rpc_url: str='', private_key: str='') -> Dict[str, Any]` (L140) — Attempt real on-chain payment if SDKs available.
  - `_solana_pay(request: CryptoPaymentRequest, rpc_url: str, private_key: str) -> Dict[str, Any]` (L157)
  - `_evm_pay(request: CryptoPaymentRequest, rpc_url: str, private_key: str) -> Dict[str, Any]` (L189)
  - `confirm_payment(request_id: str, confirmations: int=1) -> Dict[str, Any]` (L219)
  - `list_payments(status: Optional[str]=None) -> List[CryptoPaymentRequest]` (L239)
  - `get_request(request_id: str) -> Optional[CryptoPaymentRequest]` (L245)
  - `get_status() -> Dict[str, Any]` (L248)


### `agents/integrations/fiverr.py` — agents/fiverr_client.py — Fiverr gig discovery for MrBot1000. (239L)

**Classes:**
- `class FiverrGig` (L29)
  - `to_dict() -> dict` (L40)
- `class FiverrClient` (L57) — Discover Fiverr gigs via the public search results page.
  - `__init__()` (L70)
  - `_parse_search(query: str) -> List[dict]` (L83) — Fetch the Fiverr search results page and extract gig cards.
  - `find_gigs(query: str='python', limit: int=20) -> List[FiverrGig]` (L165) — Find gigs via the Fiverr search results page (RSS is dead -> 404).
  - `_scrape_gig_page(url: str) -> dict` (L193) — Scrape individual gig page for budget and skills.


### `agents/integrations/microtask.py` — agents/microtask_client.py — Microtask platform integration for MrBot1000. (156L)

**Classes:**
- `class MicrotaskGig` (L14)
  - `to_dict() -> dict` (L25)
- `class MicrotaskClient` (L42) — Client for microtask platforms that pay for AI/ML work.
  - `__init__()` (L56)
  - `find_gigs(platform: str='remotasks', query: str='ai ml data') -> List[MicrotaskGig]` (L62)
  - `_search_remotasks(query: str) -> List[MicrotaskGig]` (L82)
  - `_search_scale_ai(query: str) -> List[MicrotaskGig]` (L117)


### `agents/integrations/scraper.py` — agents/web_scraper.py — Ethical web scraping fallback (v2.1 Phase 2). (291L)

**Classes:**
- `class RateLimiter` (L23) — Rate limiter for polite scraping.
  - `__init__(requests_per_minute: int=10)` (L26)
  - `wait(url: str='')` (L31) — Wait if needed to respect rate limits.
- `class RobotsChecker` (L41) — Check robots.txt compliance.
  - `__init__()` (L44)
  - `is_allowed(url: str, user_agent: str='*') -> bool` (L47) — Check if scraping is allowed by robots.txt.
  - `_fetch_robots(base: str) -> List[str]` (L66) — Fetch and parse robots.txt.
- `class HTMLExtractor(HTMLParser)` (L91) — Extract structured data from HTML.
  - `__init__()` (L94)
  - `handle_starttag(tag, attrs)` (L104)
  - `handle_endtag(tag)` (L122)
  - `handle_data(data)` (L136)
  - `get_text() -> str` (L146) — Get extracted text.
  - `get_all() -> Dict` (L150) — Get all extracted data.
- `class WebScraper` (L159) — Ethical web scraper with rate limiting and robots.txt compliance.
  - `__init__(requests_per_minute: int=10, respect_robots: bool=True)` (L162)
  - `_get_user_agent() -> str` (L172) — Rotate user agents.
  - `scrape(url: str, extract_tables: bool=False) -> Dict` (L178) — Scrape a URL and extract data.
  - `scrape_multiple(urls: List[str], extract_tables: bool=False) -> List[Dict]` (L219) — Scrape multiple URLs.
  - `extract_emails(text: str) -> List[str]` (L227) — Extract email addresses from text.
  - `extract_phones(text: str) -> List[str]` (L232) — Extract phone numbers from text.
  - `extract_prices(text: str) -> List[Dict]` (L237) — Extract price information from text.
  - `extract_structured_data(html: str) -> List[Dict]` (L243) — Extract JSON-LD structured data from HTML.
  - `extract_open_graph(html: str) -> Dict` (L255) — Extract Open Graph metadata from HTML.
  - `extract_meta_tags(html: str) -> Dict` (L263) — Extract all meta tags from HTML.
  - `search_and_extract(url: str, keywords: List[str]) -> Dict` (L271) — Scrape a URL and extract only relevant content based on keywords.


### `agents/integrations/upwork.py` — agents/upwork_client.py — Upwork API client for MrBot1000. (219L)

**Classes:**
- `class UpworkGig` (L19)
  - `to_dict() -> dict` (L30)
- `class UpworkClient` (L47) — Upwork OAuth2 client with token refresh.
  - `__init__(client_id: str, client_secret: str, access_token: str, refresh_token: str)` (L50)
  - `_refresh_token() -> bool` (L62) — Refresh OAuth2 access token.
  - `_request(method: str, endpoint: str, **kwargs) -> Optional[dict]` (L90) — Make authenticated request with auto token refresh.
  - `find_gigs(q: str='python', category: str='software-dev', limit: int=20) -> List[UpworkGig]` (L117) — Search for freelance gigs.
  - `can_submit() -> bool` (L157) — True if OAuth tokens are present (a submit is even possible).
  - `_get_authenticated_profile() -> Optional[str]` (L162) — Return the authenticated Upwork profile id (cached). H1: real `submitted_by`
  - `submit_proposal(job_id: str, cover: str, budget: float=0.0, attachments: Optional[list]=None) -> Optional[dict]` (L177) — Submit a cover/proposal for a job via the Upwork REST API.


### `agents/integrations/wallet.py` — agents/wallet.py — Wallet management for crypto payments (v2.1 Phase 4). (191L)

**Classes:**
- `class Chain(str, Enum)` (L23)
- `class Wallet` (L31)
- `class WalletManager` (L42) — Manages crypto wallets for the agent system.
  - `__init__(state_path: str='')` (L45)
  - `_load()` (L50) — Load wallets from disk.
  - `_save()` (L69) — Save wallets to disk.
  - `add_wallet(address: str, chain: Chain, currency: str='') -> Wallet` (L89) — Add a wallet.
  - `remove_wallet(address: str) -> bool` (L100) — Remove a wallet.
  - `get_wallet(address: str) -> Optional[Wallet]` (L108) — Get wallet by address.
  - `list_wallets(chain: Optional[Chain]=None) -> List[Wallet]` (L112) — List wallets, optionally filtered by chain.
  - `update_balance(address: str, balance: float) -> bool` (L119) — Update wallet balance.
  - `get_total_balance(chain: Optional[Chain]=None) -> Dict[str, float]` (L129) — Get total balance across wallets.
  - `_validate_address(address: str, chain: Chain) -> bool` (L139) — Basic address validation.
  - `get_status() -> Dict` (L149) — Get wallet manager status.
- `class PaymentTx` (L158) — Represents a payment transaction.
  - `__init__(tx_id: str, from_addr: str, to_addr: str, amount: float, currency: str, chain: Chain)` (L161)
  - `confirm(tx_hash: str, confirmations: int=1)` (L173)
  - `to_dict() -> Dict` (L178)


### `agents/integrations/wallet_crypto.py` — agents/wallet_crypto.py — Encrypt wallet secrets at rest (B1). (177L)

**Functions:**
- `_require_fernet()` (L27)
- `generate_key() -> str` (L33) — Return a new Fernet key (urlsafe-base64 32-byte) as a string.
- `_validate_key(key: str) -> str` (L38) — Validate `key` is a usable Fernet key; raise otherwise.
- `load_or_create_key(key_path: 'str | Path') -> str` (L54) — Load the Fernet key from `key_path`, or generate + persist it (mode 0o600).
- `is_encrypted(value: str) -> bool` (L97) — True if `value` looks like one of our Fernet tokens (not cleartext).
- `encrypt_str(key: str, plaintext: str) -> str` (L104) — Encrypt a secret string → a stored token. Empty/whitespace stays empty.
- `decrypt_str(key: str, token: str) -> str` (L113) — Decrypt a stored token → secret. Non-encrypted input is returned as-is
- `encrypt_if_needed(key: str, value: str) -> str` (L126) — Encrypt `value` only if it's non-empty AND not already encrypted.
- `decrypt_if_needed(key: str, value: str) -> str` (L133) — Decrypt `value` if it's an encrypted token, else return it unchanged.
- `contains_secret(text: str) -> bool` (L158) — True if `text` looks like it contains a secret (key/seed/token).
- `redact_secrets(text: str) -> str` (L165) — Replace any detected secret in `text` with `[REDACTED-SECRET]`.


### `agents/integrations/wallet_manager.py` — agents/wallet_manager.py — Wallet management for MrBot1000. (346L)

**Functions:**
- `resolve_wallet_root(db_path: str=None) -> 'Path'` (L25)

**Classes:**
- `class WalletBalance` (L37)
- `class Transaction` (L45)
- `class WalletManager` (L56) — Manages crypto wallets for MrBot1000.
  - `__init__(root_folder: str='.', encryption_key: str=None)` (L65)
  - `_store_secret(private_key: str) -> dict` (L90) — Return the wallet dict with the private key encrypted (or "" if empty).
  - `encryption_unavailable() -> bool` (L119) — True when secrets cannot be encrypted at rest (key missing/invalid).
  - `_load_wallets()` (L123)
  - `_save_wallets()` (L131)
  - `add_solana_wallet(name: str, address: str, private_key: str='')` (L145)
  - `add_ethereum_wallet(name: str, address: str, private_key: str='')` (L156)
  - `get_private_key(name: str) -> Optional[str]` (L167) — Recover the decrypted private key for `name` (or None).
  - `get_balance(wallet_name: str) -> Optional[WalletBalance]` (L187)
  - `_get_solana_balance(address: str) -> Optional[WalletBalance]` (L199)
  - `_get_ethereum_balance(address: str) -> Optional[WalletBalance]` (L230)
  - `_get_sol_price() -> float` (L261)
  - `_get_eth_price() -> float` (L275)
  - `list_wallets() -> List[dict]` (L289)
  - `record_realized_gas(chain: str, usd: float, note: str='') -> None` (L297) — Append a realized-gas cost row to `gas_ledger.json`.
  - `total_realized_gas_usd() -> float` (L325) — Sum of realized-gas costs (0.0 if none / file missing).


### `agents/integrations/web.py` — MrBot1000/agents/web_provider.py - Configurable web search provider. (193L)

**Functions:**
- `_provider_name() -> str` (L38)
- `_max_results() -> int` (L42)
- `_normalize_ddgs(raw: List[dict]) -> List[Dict[str, str]]` (L49)
- `_normalize_tavily(raw: dict) -> List[Dict[str, str]]` (L63)
- `_normalize_brave(raw: dict) -> List[Dict[str, str]]` (L77)
- `_sanitize_snippet(text: str) -> str` (L91) — Neutralize prompt-injection patterns in untrusted web snippets (v2.0.24c).
- `_search_ddgs(query: str, limit: int) -> List[Dict[str, str]]` (L109)
- `_search_tavily(query: str, limit: int) -> List[Dict[str, str]]` (L116)
- `_search_brave(query: str, limit: int) -> List[Dict[str, str]]` (L126)
- `search(query: str) -> List[Dict[str, str]]` (L161) — Return normalized web results for ``query``.


### `agents/integrations/web_eyes.py` — agents/web_eyes.py — Web browsing and search capabilities for MrBot1000 personas. (475L)

**Functions:**
- `get_web_eyes() -> WebEyes` (L423) — Get the global WebEyes instance.
- `search_web(query: str, max_results: int=5) -> str` (L433) — Search the web and return formatted results.
- `read_url(url: str) -> str` (L440) — Read a URL and return formatted summary.
- `browse_to(url: str) -> Dict[str, Any]` (L447) — Browse to a URL (async).
- `check_site(url: str) -> Dict[str, Any]` (L454) — Check if a website is online.

**Classes:**
- `class WebEyes` (L25) — Web browsing and search interface for persona agents.
  - `__init__(headless: bool=True, timeout: int=30)` (L28)
  - `search(query: str, max_results: int=5) -> List[Dict[str, str]]` (L36) — Search the web with a dependency fallback.
  - `search_news(query: str, max_results: int=5) -> List[Dict[str, str]]` (L76) — Search news via DuckDuckGo.
  - `launch_browser()` (L96) — Launch a headless browser.
  - `browse(url: str) -> Dict[str, Any]` (L106) — Browse a URL and return page content.
  - `fill_form(url: str, form_data: Dict[str, str]) -> Dict[str, Any]` (L144) — Fill and submit a form.
  - `screenshot(url: str) -> Optional[str]` (L171) — Take a screenshot of a page.
  - `close()` (L188) — Close the browser.
  - `read_page(url: str) -> Dict[str, Any]` (L200) — Read an HTML page or API response and extract usable data.
  - `_read_with_playwright(url: str) -> Dict[str, Any]` (L276) — Fallback for JS-rendered pages. Returns {} if Playwright unavailable.
  - `extract_emails(text: str) -> List[str]` (L309) — Extract email addresses from text.
  - `extract_urls(text: str) -> List[str]` (L314) — Extract URLs from text.
  - `extract_prices(text: str) -> List[str]` (L319) — Extract price information from text.
  - `check_website_status(url: str) -> Dict[str, Any]` (L326) — Check if a website is online and get response info.
  - `get_domain_info(url: str) -> Dict[str, str]` (L346) — Get domain information.
  - `format_search_results(results: List[Dict[str, str]]) -> str` (L357) — Format search results for display.
  - `format_page_summary(page: Dict[str, Any]) -> str` (L380) — Format a page summary for display.


### `agents/platforms/__init__.py` — agents/platforms/__init__.py — Platform adapter exports (v2.1 Phase 1). (32L)


### `agents/platforms/base.py` — agents/platforms/base.py — PlatformAdapter ABC (v2.0.22 S3) (99L)

**Classes:**
- `class PlatformAdapter(ABC)` (L27) — Base class for all platform integrations.
  - `__init__(gate: InstructionGate, boundary: Optional[TrustBoundary]=No, ...)` (L37)
  - `instruction_url() -> Optional[str]` (L48) — Return the location of this platform's playbook/SKILL.md, if any.
  - `fetch_instructions() -> QuarantinedInstruction` (L52) — Fetch the platform's instruction file THROUGH the gate.
  - `list_actions() -> List[str]` (L69) — Return the actions this adapter supports (for UI / planning).
  - `execute_action(action: str, payload: dict | None=None, human_confirmed=...) -> dict` (L72) — Execute a platform action under the trust boundary.
  - `_do_action(action: str, payload: dict, confirmed_by_human=...) -> dict` (L96) — Concrete action implementation. Only called when the boundary allows.


### `agents/platforms/credential_vault.py` — Platform credential vault (Phase B). (155L)

**Functions:**
- `_default_dir() -> Path` (L36)

**Classes:**
- `class CredentialVault` (L43) — Encrypted-at-rest store for per-platform login secrets.
  - `__init__(directory: 'str | Path | None'=None)` (L46)
  - `_load_key() -> str` (L54)
  - `_read_store() -> Dict[str, Dict[str, str]]` (L63)
  - `_write_store(store: Dict[str, Dict[str, str]]) -> None` (L72)
  - `_restrict_file(path: Path) -> None` (L78)
  - `set(platform: str, field: str, secret: str) -> None` (L95) — Store one encrypted secret for a platform field. Empty secret is a
  - `set_many(platform: str, secrets: Dict[str, str]) -> None` (L105) — Store several fields at once (e.g. email + password).
  - `get(platform: str, field: str) -> str` (L116) — Return the DECRYPTED secret for in-process use only.
  - `get_all(platform: str) -> Dict[str, str]` (L128) — Return all DECRYPTED secrets for a platform (in-process use only).
  - `has_platform(platform: str) -> bool` (L135)
  - `list_platforms() -> List[str]` (L138) — Platform names only — NEVER any secret value.
  - `fields_for(platform: str) -> List[str]` (L142) — Field names stored for a platform — names only, no values.
  - `delete(platform: str, field: Optional[str]=None) -> None` (L146)


### `agents/platforms/fiverr.py` — agents/platforms/fiverr.py — Fiverr adapter stub (v2.0.22 S3) (41L)

**Classes:**
- `class FiverrAdapter(PlatformAdapter)` (L14)
  - `instruction_url()` (L20)
  - `list_actions()` (L25)
  - `_do_action(action, payload, confirmed_by_human=...)` (L28)


### `agents/platforms/github.py` — agents/platforms/github.py — GitHub API adapter (v2.1 Phase 1). (404L)

**Classes:**
- `class GitHubAdapter(PlatformAdapter)` (L25) — GitHub API adapter with real PAT integration.
  - `__init__(gate, boundary=None, credentials=..., enabled=...)` (L33)
  - `instruction_url()` (L39)
  - `list_actions()` (L42)
  - `_do_action(action, payload, confirmed_by_human=...)` (L54)
  - `_ensure_auth()` (L73) — Ensure we have a valid token.
  - `_api_call(endpoint: str, params: dict=None, method: str='GET', data: dict=None) -> dict` (L80) — Make an authenticated API call with rate limiting.
  - `_search_issues(payload: dict) -> dict` (L117) — Search for issues with labels.
  - `_read_issue(payload: dict) -> dict` (L186) — Read full issue details.
  - `_search_repos(payload: dict) -> dict` (L221) — Search for repositories.
  - `_read_repo(payload: dict) -> dict` (L279) — Read repository details.
  - `_create_pr(payload: dict, confirmed_by_human: bool) -> dict` (L313) — Create a pull request (requires human confirmation).
  - `_create_issue(payload: dict, confirmed_by_human: bool) -> dict` (L356) — Create an issue (requires human confirmation).
  - `_get_user() -> dict` (L397) — Get current user.
  - `_get_rate_limit() -> dict` (L401) — Get rate limit status.


### `agents/platforms/prolific.py` — agents/platforms/prolific.py — Prolific API adapter (v2.1 Phase 1). (217L)

**Classes:**
- `class ProlificAdapter(PlatformAdapter)` (L23) — Prolific API adapter with real API key integration.
  - `__init__(gate, boundary=None, credentials=..., enabled=...)` (L31)
  - `instruction_url()` (L37)
  - `list_actions()` (L40)
  - `_do_action(action, payload, confirmed_by_human=...)` (L49)
  - `_ensure_auth()` (L62) — Ensure we have a valid API key.
  - `_api_call(endpoint: str, params: dict=None, method: str='GET', data: dict=None) -> dict` (L69) — Make an authenticated API call with rate limiting.
  - `_search_studies(payload: dict) -> dict` (L106) — Search for available studies.
  - `_read_study(payload: dict) -> dict` (L145) — Read full study details.
  - `_check_eligibility(payload: dict) -> dict` (L176) — Check eligibility for a study.
  - `_submit_participation(payload: dict, confirmed_by_human: bool) -> dict` (L194) — Submit participation (requires human confirmation).
  - `_get_profile() -> dict` (L214) — Get current user profile.


### `agents/platforms/reddit.py` — agents/platforms/reddit.py — Reddit adapter stub (v2.0.22 S3) (35L)

**Classes:**
- `class RedditAdapter(PlatformAdapter)` (L12)
  - `instruction_url()` (L17)
  - `list_actions()` (L21)
  - `_do_action(action, payload, confirmed_by_human=...)` (L24)


### `agents/platforms/registration.py` — Gated platform sign-up / registration (Phase B). (274L)

**Classes:**
- `class RegistrationPlan` (L36) — A proposed registration, awaiting human approval. Nothing is executed.
  - `to_dict() -> Dict[str, Any]` (L48)
- `class RegistrationService` (L73) — Approval-gated account creation. Never fabricates or stores credentials.
  - `__init__(instruction_gate=None, boundary=None, approval_queue=None)` (L76)
  - `_require_gate()` (L84) — Fail closed: no registration without the full safety stack wired.
  - `propose(platform: str, signup_url: str, instruction_url: Optional[str]=None) -> Dict[str, Any]` (L98) — Fetch the platform playbook (quarantined) and build a RegistrationPlan.
  - `_detect_fields_from_page(page: Dict[str, Any]) -> List[str]` (L147) — Best-effort: which credential-ish fields does this form likely have?
  - `_draft_steps(plan: RegistrationPlan) -> List[str]` (L159)
  - `register(platform: str, signup_url: str, form_selectors: Dict[str, s, ...) -> Dict[str, Any]` (L170) — Execute registration ONLY behind a recorded human approval.
  - `register_with_vault(platform: str, signup_url: str, form_selectors: Dict[str, s, ...) -> Dict[str, Any]` (L212) — Execute registration using credentials from the ENCRYPTED VAULT.
  - `_fill(signup_url: str, platform: str, form_selectors: Dict[str, s, ...) -> Dict[str, Any]` (L253) — Drive the registration form. Shared by register/register_with_vault.


### `agents/platforms/registry.py` — agents/platforms/registry.py — Platform adapter registry (v2.1 Phase 1). (55L)

**Functions:**
- `get_adapter_class(platform: str) -> Optional[Type[PlatformAdapter]]` (L31) — Get adapter class by platform name.
- `list_adapters() -> List[str]` (L36) — List all available adapter names.
- `create_adapter(platform: str, gate, boundary=None, credentials=..., enabled=...) -> Optional[PlatformAdapter]` (L41) — Create an adapter instance by platform name.
- `create_all_adapters(gate, boundary=None, credentials=..., enabled=...) -> Dict[str, PlatformAdapter]` (L49) — Create all available adapters.


### `agents/platforms/upwork.py` — agents/platforms/upwork.py — Upwork API adapter (v2.1 Phase 1). (259L)

**Classes:**
- `class UpworkAdapter(PlatformAdapter)` (L24) — Upwork API adapter with real OAuth 2.0 integration.
  - `__init__(gate, boundary=None, credentials=..., enabled=...)` (L32)
  - `instruction_url()` (L39)
  - `list_actions()` (L42)
  - `_do_action(action, payload, confirmed_by_human=...)` (L52)
  - `_ensure_auth()` (L67) — Ensure we have a valid access token.
  - `_api_call(endpoint: str, params: dict=None) -> dict` (L95) — Make an authenticated API call with rate limiting.
  - `_search_jobs(payload: dict) -> dict` (L125) — Search for jobs with filters.
  - `_read_job(payload: dict) -> dict` (L164) — Read full job details.
  - `_draft_proposal(payload: dict) -> dict` (L196) — Draft a proposal locally (not submitted).
  - `_submit_proposal(payload: dict, confirmed_by_human: bool) -> dict` (L217) — Submit a proposal (requires human confirmation).
  - `_get_profile() -> dict` (L252) — Get current user profile.
  - `_get_categories() -> dict` (L256) — Get available job categories.

