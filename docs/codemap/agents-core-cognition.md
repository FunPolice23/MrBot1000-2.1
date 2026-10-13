<!-- generated 30 files -->

### `agents/core/__init__.py` — core package. (2L)


### `agents/core/account_profile.py` — Safe account-profile readiness for platform opportunities. (87L)

**Functions:**
- `validate_profile_data(data: Dict[str, Any]) -> Dict[str, Any]` (L64) — Validate operator-supplied profile data without retaining sensitive values.

**Classes:**
- `class AccountProfile` (L23) — Operator-approved, non-secret profile data for a platform draft.
  - `readiness() -> Dict[str, Any]` (L34)
  - `public_draft() -> Dict[str, Any]` (L52) — Return only fields safe to place in a reviewable profile draft.


### `agents/core/alerting.py` — agents/alerting.py — Real-time alerting rules layer (Phase 6). (495L)

**Functions:**
- `llm_spend_threshold_rule(name: str='LLM spend threshold, max_usd: float=10.0, window, ...) -> AlertRule` (L82) — Fire when estimated LLM spend from cloud providers in the window
- `survival_tier_change_rule(name: str='Survival tier chang, critical_only: bool=False) -> AlertRule` (L162) — Fire on any survival tier change event from the event logger.
- `safety_block_rule(name: str='Safety block') -> AlertRule` (L203) — Fire on any safety event where blocked=True.
- `pending_approval_aging_rule(name: str='Pending approval ag, max_age_seconds: int=900) -> AlertRule` (L237) — Fire when a pending approval item has aged past max_age_seconds.
- `earning_milestone_rule(name: str='Earning milestone', target_total: float=10.0, fire_once: bool=True) -> AlertRule` (L298) — Fire when cumulative earnings cross target_total.
- `add_default_rules()` (L471) — Add the common desktop-app alerting rules.

**Classes:**
- `class RuleKind(str, Enum)` (L29)
- `class AlertRule` (L41) — A single alerting rule.
  - `matches(event: Event) -> bool` (L68)
- `class AlertRuleEngine` (L346) — Evaluates alert rules against the event log and fires notifications.
  - `__init__(log_path: Optional[str]=None)` (L361)
  - `_get_lock()` (L367)
  - `instance() -> 'AlertRuleEngine'` (L374)
  - `reset_singleton()` (L382)
  - `add_rule(rule: AlertRule) -> AlertRule` (L388)
  - `add_rules(rules: List[AlertRule]) -> List[AlertRule]` (L392)
  - `remove_rule(rule_id: str) -> bool` (L396)
  - `get_rules() -> List[AlertRule]` (L403)
  - `enabled_rules() -> List[AlertRule]` (L406)
  - `enable_rule(rule_id: str, enabled: bool=True) -> bool` (L409)
  - `process_event(event: Event) -> List[str]` (L418) — Evaluate all rules against a single event.
  - `process_events(events: List[Event]) -> Dict[str, int]` (L436) — Process a batch of events and return per-rule fire counts.
  - `summary() -> Dict[str, Any]` (L446) — Return a summary dict for the GUI.


### `agents/core/architecture_boundaries.py` — Static architecture-boundary checks and legacy usage evidence. (82L)

**Functions:**
- `_imported_names(tree: ast.AST) -> Iterable[tuple[str, int]]` (L20)
- `check_import_boundaries(root: str | Path, files: Iterable[str], forbidden: dict[str, tuple[str, ...]]) -> list[BoundaryViolation]` (L29) — Return forbidden imports for files relative to ``root``.

**Classes:**
- `class BoundaryViolation` (L13)
- `class UsageLedger` (L53) — Thread-safe in-memory evidence for compatibility-path usage.
  - `__init__() -> None` (L56)
  - `record(path: str) -> None` (L60)
  - `snapshot() -> dict[str, int]` (L64)
  - `unused(paths: Iterable[str]) -> list[str]` (L68)


### `agents/core/comms.py` — comms.py — Structured internal message/event protocol for MrBot1000. (565L)

**Classes:**
- `class MessageType(str, Enum)` (L39) — All message/event types flowing through the bus.
- `class MessageStatus(str, Enum)` (L68)
- `class CancelledError(Exception)` (L111) — Raised inside a long-running handler when its token is cancelled.
  - `__init__(reason: Optional[str]=None)` (L113)
- `class Message` (L123) — Structured internal message.
  - `text() -> str` (L148)
  - `set_text(value: str) -> 'Message'` (L151)
  - `derive(mtype: MessageType, source: Optional[str]=None, destination: Optional[str]=None, **extra) -> 'Message'` (L155) — Create a child message that correlates back to this one.
  - `as_error(err: str) -> 'Message'` (L168)
  - `to_dict() -> Dict[str, Any]` (L172)
  - `from_dict(d: Dict[str, Any]) -> 'Message'` (L189)
- `class CancellationToken` (L210) — Cooperative cancellation primitive for long-running bus handlers.
  - `__init__() -> None` (L213)
  - `cancel(reason: Optional[str]=None) -> None` (L218)
  - `cancelled() -> bool` (L224)
  - `is_cancelled() -> bool` (L227)
  - `raise_if_cancelled() -> None` (L230)
  - `wait(timeout: Optional[float]=None) -> bool` (L234)
- `class EventBus` (L245) — Thread-safe, typed, observable message router.
  - `__init__() -> None` (L259)
  - `instance() -> 'EventBus'` (L283)
  - `reset_instance() -> 'EventBus'` (L289) — Replace the singleton with a fresh one (used by tests).
  - `subscribe(handler: Handler) -> None` (L295)
  - `unsubscribe(handler: Handler) -> None` (L300)
  - `subscribe_type(mtype: MessageType, handler: Handler) -> None` (L309)
  - `subscribe_destination(dest: str, handler: Handler) -> None` (L315)
  - `subscribe_source(src: str, handler: Handler) -> None` (L321)
  - `_depth(msg: Message) -> int` (L328) — Walk the parent chain via _inflight to compute correlation depth.
  - `get_token(correlation_id: str) -> CancellationToken` (L342)
  - `publish(msg: Message, token: Optional[CancellationToken]=None) -> bool` (L351) — Route a message to all matching subscribers.
  - `_prior_sources(msg: Message) -> set` (L415) — Walk the parent chain for this correlation and collect every node
  - `_emit_error(original: Message) -> None` (L432)
  - `_deliver(msg: Message) -> None` (L444)
  - `cancel(message_id_or_correlation: str, reason: Optional[str]=None) -> bool` (L459) — Cancel by message_id or correlation_id. Returns True if a token was found.
  - `request(source: str, destination: str, mtype: MessageType, payload:, ...) -> Message` (L481)
  - `publish_error(correlation_id: str, source: str, destination: str, error: str) -> Message` (L498)
  - `snapshot() -> Dict[str, Any]` (L512)
  - `reset() -> None` (L522)


### `agents/core/comms_log.py` — comms_log.py — Durable log of in-flight messages for the EventBus. (169L)

**Classes:**
- `class MessageLog` (L29) — Append-oriented, thread-safe log of bus messages keyed by message_id.
  - `__init__(path: str=':memory:')` (L32)
  - `record(msg: Message) -> None` (L57)
  - `update_status(message_id: str, status: MessageStatus, error: Optional[str]=None) -> None` (L85)
  - `get(message_id: str) -> Optional[Dict[str, str]]` (L94)
  - `all() -> List[Dict[str, str]]` (L114)
  - `mark_orphans_cancelled(terminal_status: MessageStatus=MessageStatus.CANCEL) -> int` (L135) — On application boot, any message left PENDING or IN_FLIGHT was interrupted
  - `close() -> None` (L157)
  - `count() -> int` (L165)


### `agents/core/composition_root.py` — agents/composition_root.py — Unified application composition root (v2.1 Phase 3). (181L)
> Wires the whole object graph; most features connect here.

**Functions:**
- `build_composition_root(base_dir: Optional[str]=None, db_path: Optional[str]=None, , ...) -> CompositionRoot` (L57) — Construct one canonical set of shared pipeline/portfolio/run-store objects.

**Classes:**
- `class CompositionRoot` (L33) — The shared, canonical instances for one application process.
  - `close() -> None` (L44) — Release resources owned by the root (idempotent).


### `agents/core/configuration.py` — Typed, normalized operator configuration for provider integrations. (102L)

**Functions:**
- `_value(env: Mapping[str, str], key: str) -> str` (L45) — Return a cleaned env value (a comment-as-value is treated as empty).
- `provider_settings(name: str, env: Mapping[str, str] | None=None) -> ProviderSettings` (L51) — Resolve one provider from environment without exposing secret values.
- `all_provider_settings(env: Mapping[str, str] | None=None) -> dict[str, ProviderSettings]` (L76) — Return normalized settings for every supported provider.
- `redacted_configuration(env: Mapping[str, str] | None=None) -> dict[str, object]` (L81) — Return safe diagnostics for provider configuration.

**Classes:**
- `class ProviderSettings` (L16) — Normalized settings shared by provider adapters and diagnostics.


### `agents/core/cost_tracker.py` — agents/cost_tracker.py — Comprehensive cost tracking and spend caps (v2.1 Phase 1). (316L)

**Classes:**
- `class CostConfig` (L24) — Cost tracking configuration.
  - `load(path: str='') -> 'CostConfig'` (L36) — Load config from file.
  - `save(path: str='')` (L44) — Save config to file.
- `class SpendRecord` (L55) — Single spend record.
  - `to_dict() -> dict` (L70)
  - `from_dict(data: dict) -> 'SpendRecord'` (L83)
- `class CostTracker` (L89) — Track and limit LLM spending.
  - `__init__(config: CostConfig=None)` (L92)
  - `_load_state()` (L101) — Load spend records from disk.
  - `_save_state()` (L111) — Persist spend records to disk.
  - `record_spend(model: str, provider: str, prompt_tokens: int, completion_t, ...)` (L125) — Record a spend event.
  - `get_spend(days: int=1) -> float` (L145) — Get total spend in the last N days.
  - `get_spend_by_model(days: int=1) -> Dict[str, float]` (L150) — Get spend breakdown by model.
  - `get_spend_by_provider(days: int=1) -> Dict[str, float]` (L159) — Get spend breakdown by provider.
  - `get_spend_by_platform(days: int=1) -> Dict[str, float]` (L168) — Get spend breakdown by platform.
  - `check_cap(period: str='daily') -> Tuple[bool, float, float]` (L177) — Check if a spend cap is exceeded.
  - `get_remaining_budget(period: str='daily') -> float` (L197) — Get remaining budget for a period.
  - `should_allow_call(estimated_cost: float, period: str='daily') -> bool` (L202) — Check if a call should be allowed based on budget.
  - `get_forecast(days: int=7) -> Dict[str, float]` (L207) — Forecast future spend based on recent history.
  - `get_alerts() -> List[dict]` (L216) — Get active alerts.
  - `clear_alerts()` (L220) — Clear all alerts.
  - `_check_alerts()` (L225) — Check for budget alerts.
  - `get_status() -> dict` (L282) — Get comprehensive cost status.


### `agents/core/event_logger.py` — agents/event_logger.py — Unified structured event logger (Phase 6). (518L)

**Functions:**
- `log_event(event_type: str, message: str, level: str=EventLevel.INFO.valu, source: str='', **kw) -> Event` (L504)

**Classes:**
- `class EventLevel(str, Enum)` (L32)
- `class EventType(str, Enum)` (L43) — High-level category for filtering in the GUI.
- `class Event` (L58) — A single structured event in the unified log.
  - `to_dict() -> Dict[str, Any]` (L81)
  - `from_dict(d: Dict[str, Any]) -> 'Event'` (L98)
  - `compute_hash() -> str` (L114) — Compute SHA-256 hash of this event's content chained to prev_hash.
  - `iso_ts() -> str` (L121)
- `class StructuredEventLogger` (L127) — Unified event logger with rotating JSONL + in-memory index.
  - `__init__(log_dir: Optional[str]=None, max_file_mb: int=20, max_files, ...)` (L133)
  - `_get_lock()` (L161)
  - `instance() -> 'StructuredEventLogger'` (L168)
  - `reset_singleton()` (L176)
  - `add_event_callback(callback: Callable[[Event], None])` (L182) — Register a callback to be called on every logged event.
  - `remove_event_callback(callback: Callable[[Event], None])` (L187) — Remove a previously registered callback.
  - `_ensure_dir()` (L194)
  - `_current_log_path() -> str` (L199)
  - `_should_rotate(event_size: int) -> bool` (L203)
  - `_rotate()` (L210) — Close current file and start a fresh one.
  - `_prune_old_files()` (L217) — Keep only the most recent max_files log files.
  - `_index_event(idx: int, ev: Event)` (L235)
  - `log(event: Event) -> Event` (L246) — Log an event. Hash-chains it to the previous event for tamper
  - `_write_event(event: Event)` (L277)
  - `_maybe_rotate(event_size: int)` (L297)
  - `_prune_in_memory()` (L301)
  - `query(event_type: Optional[str]=None, level: Optional[str]=None, , ...) -> List[Event]` (L316) — Query the in-memory event log.
  - `recent(event_type: Optional[str]=None, level: Optional[str]=None, limit: int=50) -> List[Event]` (L357) — Recent events, newest first.
  - `count_by_type() -> Dict[str, int]` (L372)
  - `last_event_of_type(event_type: str) -> Optional[Event]` (L378)
  - `clear_in_memory()` (L384) — Free in-memory events (logged events in JSONL are preserved).
  - `info(event_type: str, message: str, source: str='', details: Dic, ...)` (L394)
  - `warning(event_type: str, message: str, source: str='', details: Dic, ...)` (L407)
  - `error(event_type: str, message: str, source: str='', details: Dic, ...)` (L420)
  - `critical(event_type: str, message: str, source: str='', details: Dic, ...)` (L433)
  - `earning_event(action: str, revenue: float=0.0, cost: float=0.0, platform:, ...)` (L448)
  - `safety_event(gate_type: str, blocked: bool, description: str='', **kw)` (L462)
  - `llm_spend_event(model: str, provider: str, tokens: int, est_usd: float, **kw)` (L475)
  - `heartbeat_event(tier: str, credits: float, tasks_run: int, errors: int, **kw)` (L488)


### `agents/core/feature_flags.py` — Explicit feature boundaries for optional and high-risk capabilities. (66L)

**Functions:**
- `_truthy(value: str) -> bool` (L30)
- `feature_enabled(name: str, env: Mapping[str, str] | None=None) -> bool` (L34) — Return whether an optional feature is explicitly enabled.
- `feature_status(env: Mapping[str, str] | None=None) -> dict[str, bool]` (L51) — Return safe, non-secret feature state for diagnostics.
- `feature_env_key(name: str) -> str` (L56) — Return the canonical environment key for a known feature.


### `agents/core/notifications.py` — agents/notifications.py — Notification service: Windows toast + in-app panel. (214L)

**Functions:**
- `notify(title: str, message: str, level: str=NotifLevel.INFO.valu, **kw)` (L203) — Module-level convenience; uses singleton.

**Classes:**
- `class NotifLevel(str, Enum)` (L15)
- `class Notif` (L25) — A single notification event.
- `class NotificationService` (L44) — Central notification hub.
  - `__init__()` (L55)
  - `instance() -> 'NotificationService'` (L65)
  - `reset_singleton()` (L73)
  - `push(title: str, message: str, level: str=NotifLevel.INFO.valu, , ...) -> Notif` (L79)
  - `_enqueue(note: Notif)` (L98)
  - `history(limit: int=100) -> List[Notif]` (L109)
  - `recent(level: Optional[str]=None, limit: int=50) -> List[Notif]` (L112)
  - `pending() -> List[Notif]` (L118) — Return items that have not been acknowledged/dismissed.
  - `dismiss(note_id: str) -> bool` (L123) — Remove a sticky note from history.
  - `subscribe(cb: Callable[[Notif], None])` (L133)
  - `unsubscribe(cb: Callable[[Notif], None])` (L136)
  - `try_toast(note: Notif)` (L144) — Attempt a system toast; non-fatal if unavailable.
  - `_send_toast(note: Notif)` (L153)
  - `detect_toast_support()` (L168) — Check once whether win10toast is importable.
  - `info(title: str, message: str, **kw)` (L178)
  - `success(title: str, message: str, **kw)` (L181)
  - `warning(title: str, message: str, **kw)` (L184)
  - `error(title: str, message: str, **kw)` (L187)
  - `approval_required(title: str, message: str, **kw)` (L190)
  - `critical(title: str, message: str, **kw)` (L196)


### `agents/core/persistence_contract.py` — Canonical ownership contract for MrBot1000's SQLite stores. (112L)
> STORE_AUTHORITIES allowlist used by the multi-DB query_db resolver.

**Functions:**
- `validate_store_paths(paths: Mapping[str, str | Path]) -> None` (L75) — Validate configured store paths before opening any database.
- `authority_for(name: str) -> StoreAuthority` (L98) — Return the contract entry for a store name.

**Classes:**
- `class StoreAuthority` (L16) — Authoritative persistence boundary for one domain.


### `agents/core/recovery.py` — Measurable recovery progress for bounded autonomous retries. (41L)

**Classes:**
- `class RecoveryTracker` (L10)
  - `attempt(state_fingerprint: str, evidence_ids: Iterable[str]=()) -> bool` (L17) — Accept a retry only when it changes state or adds evidence.
  - `exhausted() -> bool` (L37)


### `agents/core/state_reconciliation.py` — Read-only reconciliation across opportunity state stores. (188L)

**Functions:**
- `reconcile_opportunity(opportunity_id: str, lifecycle=..., portfolio=..., evidence, ...) -> ReconciliationReport` (L53) — Compare available stores for one opportunity without mutating them.
- `reconcile_many(opportunity_ids: Iterable[str], **stores) -> ReconciliationReport` (L128) — Aggregate read-only reconciliation results for multiple opportunities.
- `_lifecycle_state(store: Any, opportunity_id: str) -> Dict[str, Any]` (L140)
- `_portfolio_entry(store: Any, opportunity_id: str) -> Any` (L147)
- `_evidence(store: Any, opportunity_id: str) -> List[Any]` (L154)
- `_accounting_profile(store: Any, opportunity_id: str) -> Any` (L160)
- `_runs(store: Any, opportunity_id: str) -> List[Any]` (L166)
- `_value(source: Any, key: str, default: Any=None) -> Any` (L173)
- `_number(source: Any, key: str) -> float` (L181)

**Classes:**
- `class ReconciliationConflict` (L17)
  - `to_dict() -> Dict[str, Any]` (L25)
- `class ReconciliationReport` (L37)
  - `has_conflicts() -> bool` (L42)
  - `to_dict() -> Dict[str, Any]` (L45)


### `agents/cognition/__init__.py` — Canonical cognition contracts and bounded reasoning policies. (97L)


### `agents/cognition/contradictions.py` — First-class contradiction cases for competing claims. (64L)

**Functions:**
- `open_contradiction(subject: str, claims: List[Claim]) -> ContradictionCase` (L58)

**Classes:**
- `class ContradictionStatus(str, Enum)` (L13)
- `class ContradictionCase` (L20)
  - `resolve(selected_claim: Claim, evidence_ids: List[str]) -> bool` (L29)
  - `block(reason: str) -> None` (L41)
  - `to_dict() -> dict` (L46)


### `agents/cognition/coordinator.py` — agents/dual_brain_coordinator.py — Canonical cross-model collaboration (v2.1). (327L)

**Classes:**
- `class CollaborationStage(str, Enum)` (L45)
- `class StageRun` (L91)
  - `to_dict() -> Dict[str, Any]` (L103)
- `class RunRecord` (L117)
  - `ok() -> bool` (L130)
  - `to_dict() -> Dict[str, Any]` (L133)
- `class DualBrainCoordinator` (L148) — Deterministic, typed, durable handoff orchestrator between the roles.
  - `__init__(runtime: Optional[DualBrainRuntime]=None, model_fn: Optiona, ...)` (L151)
  - `_noop_model(role: BrainRole, stage: CollaborationStage, prompt: str) -> str` (L166)
  - `get_run(run_id: str) -> Optional[RunRecord]` (L170)
  - `list_runs(limit: int=50) -> List[RunRecord]` (L173)
  - `_record(msg: Message) -> None` (L180)
  - `collaborate(goal: str, stages: Optional[List[CollaborationSta=None) -> RunRecord` (L187) — Run the typed plan→research→review→execute handoff for ``goal``.
  - `_run_stage(run: RunRecord, stage: CollaborationStage) -> StageRun` (L221)
  - `_emit(mtype: MessageType, run: RunRecord) -> None` (L306) — Publish a terminal/update event about a run (observability).


### `agents/cognition/dialogue.py` — Natural dual-brain conversation records separate from GoT and authority. (148L)

**Functions:**
- `_clean_matches(matches: Iterable[str]) -> tuple[str, ...]` (L40)

**Classes:**
- `class DialogueIntent(str, Enum)` (L18)
- `class DialogueTurn` (L45) — One complete natural-language turn plus queryable annotations.
  - `to_dict() -> dict[str, object]` (L59)
- `class NaturalDialogue` (L74) — Bounded transcript that preserves speech while exposing structured cues.
  - `__init__(goal: str, max_turns=...)` (L77)
  - `remaining_turns() -> int` (L87)
  - `add_turn(speaker: str, text: str, evidence_ids=..., got_node_id=...) -> DialogueTurn` (L90) — Retain the exact turn and derive non-authoritative conversation cues.
  - `transcript(limit=...) -> str` (L134)
  - `to_dict() -> dict[str, object]` (L138)


### `agents/cognition/dialogue_honesty.py` — agents/dialogue_honesty.py — Honesty enforcement for model dialogue (v2.1.1). (213L)

**Functions:**
- `_extract_claims_from_context(context: str) -> list[tuple[str, str]]` (L24) — Best-effort extraction of factual claims from model output text.

**Classes:**
- `class DialogueHonestyService` (L79) — Single service that coordinates the three honesty modules for dialogue.
  - `__init__(max_claims: int=60) -> None` (L98)
  - `record_claims(response_text: str, source: str='dialogue_model', subject_t, ...) -> list[LedgerEntry]` (L108) — Record each extracted claim as PROPOSED (model may not self-verify).
  - `apply_overrides() -> None` (L152) — Apply active operator overrides to any conflicting claims.
  - `epistemic_context_note(max_claims: int=8) -> str` (L188) — Return the epistemic framing for all standing claims.
  - `standing_claims() -> list[LedgerEntry]` (L199)
  - `to_dict() -> dict` (L206)


### `agents/cognition/epistemic.py` — agents/epistemic_calibration.py — Deterministic confidence classification. (115L)

**Functions:**
- `classify(entry: Optional[LedgerEntry]) -> EpistemicLevel` (L41) — Classify a ledger entry's epistemic standing (deterministic).
- `confidence(entry: Optional[LedgerEntry]) -> float` (L60) — Deterministic confidence in [0, 1] for a ledger entry.
- `disclaimer(entry: Optional[LedgerEntry]) -> str` (L77) — A short, honest framing for a single claim (for prompt injection).
- `context_note(entries: List[LedgerEntry], max_claims: int=8) -> str` (L97) — Aggregate epistemic framing for a set of claims (for prompt injection).

**Classes:**
- `class EpistemicLevel(str, Enum)` (L26)


### `agents/cognition/fact_ledger.py` — agents/cognition/fact_ledger.py — Append-only register of claims and their verification. (371L)
> Append-only claim register (anti-fabrication Fact Ledger).

**Functions:**
- `source_authority(kind: SourceKind) -> int` (L52) — Deterministic authority rank for a claim source (higher wins).

**Classes:**
- `class SourceKind(str, Enum)` (L32) — Who asserted a claim. Only OPERATOR carries human authority.
- `class ClaimStatus(str, Enum)` (L57)
  - `is_affirmative() -> bool` (L65) — True if the ledger currently treats the claim as standing.
- `class LedgerError(Exception)` (L90) — Base class for ledger violations.
- `class IllegalTransition(LedgerError)` (L94) — A requested status change is not permitted from the current status.
- `class UnsubstantiatedVerification(LedgerError)` (L98) — VERIFIED was requested without evidence that meets the requirement.
- `class LedgerEntry` (L103) — One immutable revision of one claim. Never mutated after creation.
  - `authority() -> int` (L123)
  - `to_dict() -> Dict[str, Any]` (L126)
- `class FactLedger` (L146) — In-memory, append-only claim register.
  - `__init__(default_required_level: VerificationLevel=DEFAULT_MIN_LEVEL)` (L154)
  - `record_claim(claim: Claim, source_kind: SourceKind, required_level: Optional[VerificationLevel]=None) -> LedgerEntry` (L160) — Record a claim as PROPOSED.
  - `attach_evidence(claim_id: str, evidence_ref: str, level: VerificationLevel, method: str='', note: str='') -> LedgerEntry` (L192) — Attach deterministic evidence and advance the claim's status.
  - `refute(claim_id: str, note: str='', method: str='human_attestation') -> LedgerEntry` (L240) — Mark a claim as REFUTED. Refutation is terminal for the claim.
  - `supersede(claim_id: str, by_claim_id: str, note: str='') -> LedgerEntry` (L248) — Mark a claim as SUPERSEDED by a later claim.
  - `supersede_by_reference(claim_id: str, reference: str, note: str='') -> LedgerEntry` (L257) — Mark a claim as SUPERSEDED by an external authority reference.
  - `latest(claim_id: str) -> Optional[LedgerEntry]` (L275)
  - `history(claim_id: str) -> List[LedgerEntry]` (L279) — Full immutable revision history for a claim (append-only).
  - `all_claims() -> List[LedgerEntry]` (L283)
  - `by_status(status: ClaimStatus) -> List[LedgerEntry]` (L286)
  - `verified_claims() -> List[LedgerEntry]` (L289) — Claims backed by evidence meeting their requirement.
  - `claims_about(subject_id: str) -> List[LedgerEntry]` (L296)
  - `prune(max_claims: int) -> int` (L299) — Drop the oldest unverified claims so the ledger cannot grow forever.
  - `_latest(claim_id: str) -> LedgerEntry` (L329)
  - `_assert_transition(current: ClaimStatus, new: ClaimStatus) -> None` (L336)
  - `_append(current: LedgerEntry, status=..., evidence_refs=..., verifi, ...) -> LedgerEntry` (L344) — Append a new immutable revision derived from ``current``.


### `agents/cognition/graph.py` — Typed cognition artifacts for inspectable dual-brain orchestration. (523L)

**Classes:**
- `class InformationKind(str, Enum)` (L18)
- `class ClaimStatus(str, Enum)` (L28)
- `class ApprovalState(str, Enum)` (L35)
- `class ActionState(str, Enum)` (L44)
- `class OutcomeState(str, Enum)` (L53)
- `class ThoughtNodeKind(str, Enum)` (L61) — Inspectable reasoning artifacts, not private token-level thoughts.
- `class ThoughtEdgeKind(str, Enum)` (L77)
- `class ThoughtNode` (L87) — One concise, inspectable graph node; it never contains chain-of-thought.
  - `to_dict() -> Dict[str, Any]` (L100)
- `class ThoughtEdge` (L112) — A typed relationship between two inspectable reasoning nodes.
  - `to_dict() -> Dict[str, Any]` (L120)
- `class SupportMeasure` (L130) — Deterministic support summary; it is advisory and never grants authority.
  - `action_eligible() -> bool` (L142) — Whether the graph is sufficiently supported to recommend a gate check.
  - `to_dict() -> Dict[str, Any]` (L151)
- `class ThoughtGraph` (L164) — Bounded, inspectable Graph-of-Thought support structure.
  - `__init__()` (L172)
  - `add_node(node: ThoughtNode) -> ThoughtNode` (L176)
  - `add_edge(edge: ThoughtEdge) -> ThoughtEdge` (L184)
  - `update_node(node_id: str, **changes) -> ThoughtNode` (L195) — Replace an existing node with a status/text update.
  - `_has_dependency_cycle(edges: List[ThoughtEdge]) -> bool` (L206)
  - `measure_support(node_id: str, evidence_by_id: Mapping[str, Any] | None=None, _seen: Set[str] | None=None) -> SupportMeasure` (L228) — Measure direct and propagated support without changing graph state.
  - `measure_all(evidence_by_id: Mapping[str, Any] | None=None) -> Dict[str, SupportMeasure]` (L299) — Measure every node for diagnostics and UI summaries.
  - `rank_options(option_ids: List[str], evidence_by_id: Mapping[str, Any] | None=None) -> List[SupportMeasure]` (L306) — Rank option nodes by support, preferring uncontradicted evidence-backed choices.
  - `validate() -> List[str]` (L329)
  - `to_dict() -> Dict[str, Any]` (L338)
- `class InformationItem` (L346) — A concise reasoning input; private token-level thought is excluded.
- `class Claim` (L365) — A model-facing claim whose support is tracked separately from prose.
  - `can_support_action() -> bool` (L374)
- `class Option` (L379)
- `class Decision` (L387)
- `class ApprovalRequest` (L396)
- `class ActionIntent` (L405)
- `class ToolExecution` (L415)
- `class Outcome` (L425)
  - `can_update_learning() -> bool` (L431)
- `class Lesson` (L436)
  - `can_be_promoted() -> bool` (L441)
- `class CognitionRecord` (L446) — Inspectable state shared between brains and the orchestration layer.
  - `validate() -> List[str]` (L467) — Return deterministic contract violations without invoking a model.
  - `is_valid() -> bool` (L491)
  - `to_dict() -> Dict[str, Any]` (L494) — Return a JSON-safe summary suitable for Message.payload.


### `agents/cognition/ledger.py` — Durable cognition ledger backed by the canonical EventBus message path. (65L)

**Classes:**
- `class CognitionLedger` (L12) — Publish and persist inspectable cognition records without model internals.
  - `__init__(bus: Optional[EventBus]=None, log: Optional[MessageLog]=None)` (L15)
  - `record(record: CognitionRecord) -> Message` (L19)
  - `get(message_id: str)` (L34)
  - `for_run(run_id: str) -> List[dict]` (L37)
  - `summary_for_run(run_id: str) -> dict` (L40) — Return inspectable state counts without exposing private thought.


### `agents/cognition/memory_promotion.py` — Promotion gate from transient cognition/outcomes into durable memory. (54L)

**Classes:**
- `class PromotionDecision` (L12)
- `class MemoryPromotionPolicy` (L18) — Allow durable lessons only when their outcome evidence is verified.
  - `evaluate(lesson: Lesson, outcomes: Iterable[Outcome]) -> PromotionDecision` (L21)
  - `promote(database, lesson: Lesson, outcomes: Iterable[Outcome], title=..., expires_days=...) -> PromotionDecision` (L35) — Persist a verified lesson using the existing memory database.


### `agents/cognition/operator_override.py` — agents/operator_override.py — Human authority over model claims. (200L)
> Human authority over model claims (Operator Override).

**Classes:**
- `class OverrideError(Exception)` (L31) — Base class for override violations.
- `class OverrideRecord` (L36) — One immutable revision of an operator override.
  - `source_kind() -> SourceKind` (L50)
  - `to_dict() -> Dict[str, Any]` (L54)
- `class OperatorOverrideRegistry` (L68) — Append-only register of human overrides.
  - `__init__()` (L71)
  - `issue(statement: str, subject_id: str='', issued_by: str='operator', note: str='') -> OverrideRecord` (L76) — Record a human statement. This is the only way to create authority.
  - `revoke(override_id: str, note: str='') -> OverrideRecord` (L97) — Deactivate an override (append-only; the record is not deleted).
  - `amend(override_id: str, statement: str, note: str='') -> OverrideRecord` (L104) — Replace the text of an active override, keeping the history.
  - `current(override_id: str) -> Optional[OverrideRecord]` (L117)
  - `history(override_id: str) -> List[OverrideRecord]` (L121)
  - `active() -> List[OverrideRecord]` (L124)
  - `active_for(subject_id: str) -> List[OverrideRecord]` (L128) — Active overrides that cover a subject (its own, plus global ones).
  - `resolve(subject_id: str) -> Optional[OverrideRecord]` (L135) — Return the operator statement that governs a subject, if any.
  - `apply_to_ledger(ledger: FactLedger) -> List[str]` (L148) — Supersede conflicting *model* claims in the ledger.
  - `_current(override_id: str) -> OverrideRecord` (L179)
  - `_append(current: OverrideRecord, statement=..., active=..., note=...) -> OverrideRecord` (L185)


### `agents/cognition/personas.py` — agents/personas.py — Persona identities for the two collaborating models (v2.1). (347L)

**Functions:**
- `display_name_for(role: PersonaRole) -> str` (L58) — Return the configured display name for a stable persona role.
- `persona_for_brain_role(brain_role) -> Optional[Persona]` (L304)
- `persona_for_key(key: str) -> Optional[Persona]` (L321)
- `all_personas() -> List[Persona]` (L332)

**Classes:**
- `class PersonaRole(str, Enum)` (L17)
- `class RoleContract` (L23) — Machine-readable responsibilities shared by prompts and orchestration.
  - `prompt_block() -> str` (L34)
- `class Persona` (L65)
  - `db_key() -> str` (L78)
  - `current_name() -> str` (L82) — Return the user-configured name while preserving the role default.
  - `current_identity() -> str` (L88) — Update the identity sentence without changing the stable persona role.
  - `personality_addon() -> str` (L92)
  - `memory_context(query: str='') -> str` (L99)
  - `build_system_prompt(goal: str='', query: str='', compact: bool=False, tiny: boo, ...) -> str` (L106) — Return a minimal system prompt focused on tool usage.


### `agents/cognition/reasoning_modes.py` — Reasoning-mode policy for dual-brain tasks. (239L)

**Functions:**
- `select_reasoning_mode(task: str, requires_research=..., candidate_count=..., dependency_count=...) -> ModePolicy` (L87) — Select a bounded orchestration policy from task shape.
- `select_reasoning_pattern(task: str, requires_research=..., candidate_count=..., depe, ...) -> PatternSelection` (L119) — Select one bounded pattern from transparent task-shape signals.

**Classes:**
- `class ReasoningMode(str, Enum)` (L14)
- `class ReasoningPattern(str, Enum)` (L22) — Bounded orchestration patterns, not private model reasoning.
- `class PatternSelection` (L41)
- `class ModePolicy` (L51)
  - `instruction() -> str` (L58)


### `agents/cognition/speaker_registry.py` — agents/cognition/speaker_registry.py — N-brain speaker roster. (251L)

**Functions:**
- `_env_name(slot: int, tier: str) -> str` (L77) — Return the operator-configured name for a slot, or "" if unset.
- `_default_name(slot: int, tier: str, big_seen: int, small_seen: int) -> str` (L95) — Default display name for a slot from the per-tier pool.
- `build_speakers(placements: List[Dict], brains: Optional[Dict[int, object]]=None) -> List[Speaker]` (L117) — Build the speaker roster from device placements.
- `speaker_for_slot(speakers: List[Speaker], slot: int) -> Optional[Speaker]` (L170)
- `speaker_for_key(speakers: List[Speaker], key: str) -> Optional[Speaker]` (L177)
- `speaker_for_name(speakers: List[Speaker], name: str) -> Optional[Speaker]` (L184)
- `default_pingpong_order(speakers: List[Speaker]) -> List[Speaker]` (L192) — The classic 1-big + 1-small ping-pong order (Edward, Jacob).
- `build_team_brief(speakers: List[Speaker], self_speaker: Optional[Speaker], goal: str='') -> str` (L205) — Build the multi-brain council block injected into a brain's system prompt.

**Classes:**
- `class Speaker` (L56) — One dialogue participant: a named brain on a detected device.
  - `is_big() -> bool` (L69)
  - `is_small() -> bool` (L73)


### `agents/cognition/state.py` — Canonical cognition state facade. (22L)

**Classes:**
- `class CanonicalCognitionState` (L11)
  - `__init__(ledger: CognitionLedger | None=None)` (L12)
  - `record(record: CognitionRecord)` (L15)
  - `summary(run_id: str) -> dict` (L18)

