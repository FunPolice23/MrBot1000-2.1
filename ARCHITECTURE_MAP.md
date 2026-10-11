# MrBot1000 architecture map

## Executive assessment

MrBot1000 is feature-rich and has strong safety, evidence, and recovery
concepts, but it is larger and more coupled than a single-process desktop
application needs to be. The repository currently contains approximately:

- 328 tracked files.
- 301 tracked Python files.
- 78,340 tracked Python lines.
- 158 modules under `agents/`.
- 23 modules under `gui/`.
- 99 test modules.

The size is not uniformly problematic. Most of the complexity is concentrated
in a small number of integration hubs and in several overlapping subsystems.
The highest-value reduction is not deleting features immediately; it is
separating the canonical runtime from optional adapters and retiring duplicate
or legacy paths.

## Runtime topology

```text
main.py
  ├─ Qt application and MainWindow
  ├─ AgentDB / settings / event logger / notifications
  ├─ application_services.build_earning_services()
  │    └─ composition_root.build_composition_root()
  │         ├─ EarningPipeline
  │         │    ├─ OpportunityLifecycle
  │         │    ├─ EvidenceStore
  │         │    ├─ EconomicAccounting
  │         │    ├─ TaskExecutor
  │         │    └─ AutonomousLoop
  │         ├─ OpportunityPortfolio
  │         └─ AutonomousRunStore
  ├─ WorkerAgent / provider registry
  ├─ ManagerThread
  └─ SummarizerThread
```

The GUI currently remains the largest composition boundary. It knows about
providers, workers, pipelines, settings, Qt threads, persistence, themes, and
shutdown. The new `agents/application_services.py` extraction is the first
step toward narrowing that boundary.

## Major subsystem map

### 1. Application and GUI

Primary files:

- `main.py` — application startup, MainWindow, settings, worker wiring,
  shutdown, provider UI integration.
- `gui/tab_builders.py` — tab construction and cross-tab wiring.
- `gui/dual_brain_control.py` — provider/model/GPU controls and server
  lifecycle.
- `gui/dialogue_tab.py` — dialogue context, model interaction, tool traces.
- `gui/provider_config_widget.py` — provider configuration UI.
- `ui.py` — shared visual widgets and thought panels.
- `theme_config.py`, `effects.py`, `gui/performance.py` — presentation and
  rendering configuration.

Assessment: this is the primary coupling hotspot. `main.py`,
`gui/tab_builders.py`, and `gui/dual_brain_control.py` should eventually be
split into application services, view models, and thin Qt views.

### 2. Model and provider runtime

Primary files:

- `agents/base_worker.py` — legacy/general provider registry and LLM worker.
- `agents/big_brain.py`, `agents/small_brain.py` — role-specific model
  behavior.
- `agents/dual_brain_runtime.py` — canonical role/provider/device runtime.
- `agents/configuration.py` — normalized provider configuration layer.
- `agents/provider_manager.py` — provider lifecycle and status.
- `agents/provider_hot_reload.py` — runtime provider refresh.
- `agents/providers/` — provider adapters.
- `provider_models.py` — discovery, pricing, and model metadata.
- `agents/llm_runtime.py`, `agents/runtime_stats.py`, `agents/cost_tracker.py`,
  `agents/cost_guard.py` — runtime and cost controls.

Assessment: there are two configuration paradigms: the newer dual-brain
runtime and the older broad environment-driven provider registry in
`base_worker.py`. This is a major consolidation target. The normalized
configuration module exists, but adoption is not complete.

### 3. Dialogue, cognition, and prompting

Primary files:

- `agents/summarizer.py`
- `agents/chat_router.py`
- `agents/cognition.py`
- `agents/cognition_ledger.py`
- `agents/brain_got.py`
- `agents/earning_got.py`
- `agents/dual_brain_coordinator.py`
- `agents/discussion.py`
- `agents/personas.py`
- `agents/prompt_assembly.py`
- `agents/prompting_engine.py`
- `agents/prompt_sanitize.py`
- `agents/task_router.py`
- `agents/reasoning_modes.py`
- `agents/dialogue_honesty.py`

Assessment: this area contains overlapping concepts for cognition, planning,
thought graphs, prompting, dialogue, and coordination. Some are observability
or policy layers, while others are execution paths. A canonical request
pipeline should eventually distinguish:

1. Context assembly.
2. Model invocation.
3. Tool authorization.
4. Evidence recording.
5. User-facing explanation.

#### Pattern selection and decision traces

`agents/reasoning_modes.py` is the bounded pattern router. It selects a
transparent orchestration pattern from task shape rather than asking a model to
choose an unbounded strategy:

| Task shape | Pattern | Intended use |
|---|---|---|
| Small conversational request | Direct dialogue | One concise response |
| Missing current fact | ReAct | One bounded retrieve/check cycle |
| Multiple alternatives | Tree-of-Thoughts | Compare up to three options |
| Interdependent workflow | Graph-of-Thoughts | Track dependencies and blocked nodes |
| High-risk alternatives | LATS | Bounded search plus verification |
| Verified prior outcomes are useful | Episodic memory | Retrieve relevant experience |
| Multiple independent read-only lookups | Parallel tools | Concurrent bounded reads |
| Long-running work | Checkpoint loop | Resume from explicit checkpoints |
| Explicit requirements or acceptance criteria | Specification-driven | Constrain work before implementation |
| Benchmarking or mocked-tool validation | Workflow evals | Measure behavior before enabling rollout |
| Execution-log learning | Memory synthesis | Promote only verified lessons |
| Trace, cost, or latency investigation | LLM observability | Link model/tool/outcome spans |

The selector is a routing hint, not a decision authority. Each
`BrainTurnGraph` records the selected pattern and concise public nodes for
decision, action intent, approval status, dispatcher-confirmed execution, and
outcome. Private token-level reasoning is never persisted. A model proposal
can create a graph node, but only evidence policy, authorization, and the
action dispatcher can permit execution.

The pattern vocabulary is informed by the public
[Agentic Patterns catalogue](https://www.agentic-patterns.com/). Catalog
patterns are adapted to existing MrBot1000 boundaries rather than copied as
independent subsystems. Progressive autonomy, tool compartmentalization,
retention, and sensitive-data handling remain platform policies and cannot be
selected away by an agent.

#### Actionable feature surfaces

Social Activity is no longer only a passive event table: its `Scan Social
Sources` action runs the existing feature-gated discovery pipeline off the GUI
thread, persists provenance through the earning pipeline, and presents the
result as an evaluation/review queue. It does not submit, register, or contact
any platform.

Self-Improvement remains a ranking/recommendation learner. Its UI now derives a
next action from verified successful search terms when available; otherwise it
explicitly asks for a verified outcome before changing rankings. Autonomous
Learning similarly translates durable run states into an operator next step
(approval review, failure investigation, payment verification, or next
eligible evaluation). Neither surface is allowed to turn a learned preference
into authorization.

#### Dialogue tab execution map

The Dialogue tab is a Qt orchestration surface, not a separate model runtime.
It coordinates two already-created adapters:

```text
MainWindow tab_specs
  └─ lazy create_dialogue_tab() [gui/tab_builders.py]
       ├─ BigBrainAdapter       [agents/big_brain.py]
       ├─ SmallBrainAdapter     [agents/small_brain.py]
       └─ DialogueTab           [gui/dialogue_tab.py]
            ├─ goal / phase state
            ├─ bounded context assembly
            ├─ DialogueWorker(QThread)
            ├─ streamed progress throttler
            ├─ transcript + task/sidebar widgets
            └─ persistence/logging bridges
```

##### User-facing controls and behavior

| Control/surface | Effect |
|---|---|
| Goal + Set Goal | Sets the single active objective, resets the lifecycle phase/question count, emits `goal_changed`, and marks an in-flight turn for replacement. |
| Human input + Send | Appends a human turn, persists it for both brains, selects the requested reply persona, and starts one background turn. |
| Auto-Step | Runs a bounded sequence (`_max_auto_steps`, default 10); lifecycle phases select the next persona. |
| Live | Runs the lifecycle continuously until Stop or `DIALOGUE_MAX_EXCHANGES` ends it. |
| Step | Runs exactly one persona turn without advancing the autonomous lifecycle speaker override. |
| Force Forward | Adds a loop-breaking directive and advances the dialogue rather than silently restarting the same prompt. |
| Reset | Clears the in-memory transcript, goal-facing lists, phase, and run flags; it does not erase persisted database history. |
| Progress bar | Shows an indeterminate generation state; streamed chunks are throttled before reaching Qt widgets. |

##### Turn lifecycle

1. `respond()` rejects overlapping workers, synchronizes provider-selected
   models, chooses the active persona, builds the persona/system contract, and
   snapshots a bounded context.
2. `DialogueWorker` runs `brain.chat()` on a `QThread` with
   `dialogue_mode=True`, the model-size turn budget, and a streaming callback.
3. Provider streaming is implemented in `agents/tool_calling.py`; it uses the
   OpenAI-compatible `/v1/chat/completions` endpoint and forwards content
   chunks to the worker.
4. The worker rejects malformed, repetitive, stalled, narrated-tool, and
   truncated-inline-reasoning output. A recovery attempt can use a bounded
   2048-token budget when a Qwen-style `<think>` block consumes the normal
   budget.
5. `_on_response_ready()` applies transport/empty/duplicate/semantic checks,
   appends accepted text to the transcript, records honesty/decision state,
   persists the turn, and optionally chains the next Live/Auto-Step turn.
6. Generation IDs, cooperative cancellation, retired workers, and stale
   progress guards prevent late Qt signals from mutating a newer turn.

##### State ownership

| State | Owner | Lifetime |
|---|---|---|
| `conversation_history` | `DialogueTab` | Current UI session; bounded when context is assembled |
| `goal`, `_phase_index`, `current_speaker` | `DialogueTab` | Current UI session |
| `is_running`, `live_running`, `_auto_steps_left` | `DialogueTab` | Current run |
| retry/duplicate counters | `DialogueTab` and `DialogueWorker` | Current turn/run |
| model, endpoint, context, temperature | Brain adapters/runtime configuration | Application/provider lifetime |
| streamed response and cancellation flag | `DialogueWorker` | One background turn |
| thought graph/tool trace | Brain adapter | Latest completed model call |

##### Context and prompt inputs

`get_dialogue_context()` combines the active goal and lifecycle instruction,
recent human/persona transcript, recent questions and loop signals, opportunity
board entries, blocked/pending states, honesty/evidence notes, operator
directive, response contract, model tier, tool instructions, and mandatory
untrusted-content/dialogue-control/work-tracker tails. The final context is
character-bounded (`DIALOGUE_CONTEXT_CHAR_LIMIT`, with an in-code default) and
the recent transcript is separately limited. The same context is passed as the
user message to the selected adapter; `history` is intentionally empty at the
worker boundary to avoid duplicate prompt injection.

##### Persistence and cross-tab wiring

- Human and accepted persona turns are written through
  `agents.program_knowledge.get_database().log_conversation()`; human turns
  are sent to both brain memories, persona turns to the corresponding brain.
- Per-turn operational records are appended to
  `logs/dialogue_YYYYMMDD.log` by `gui/dialogue_log.py`.
- `DialogueHonestyService` records claims/overrides and supplies epistemic
  context for non-tiny tiers.
- Dialogue goals mirror to Collaboration through `goal_changed`; Collaboration
  goals mirror back through the bridge in `gui/tab_builders.py`.
- Provider model changes stop the current turn through
  `on_model_changed()`.
- Chat-to-Dialogue bridging is conditionally wired in `gui/tab_builders.py`,
  but currently calls `ingest_exchange()` while `DialogueTab` does not define
  that method. It is therefore a documented integration gap: ordinary Chat
  exchanges do not reliably enter the Dialogue transcript.

##### Environment and runtime inputs

The active local setup uses `BIG_BRAIN_URL`/`SMALL_BRAIN_URL`, explicit
`BIG_BRAIN_MODEL`/`SMALL_BRAIN_MODEL`, role context sizes, temperatures, and
role max-token settings from `.env`. Dialogue-specific limits include
`DIALOGUE_HISTORY_LIMIT`, `DIALOGUE_CONTEXT_CHAR_LIMIT`,
`DIALOGUE_TURN_MAX_TOKENS`, and `DIALOGUE_MAX_EXCHANGES`. The adapters also
honor provider protocol/model-profile settings and local LLM timeout controls.

##### Main risks and reduction targets

1. `gui/dialogue_tab.py` owns UI, lifecycle policy, prompt/context assembly,
   persistence, retries, safety presentation, and worker lifecycle in one
   2,000+ line module.
2. The same response is subject to worker-level malformed-output retries and
   tab-level transport/empty/duplicate retries; these must remain separately
   observable to avoid retry amplification.
3. Model/provider configuration is synchronized from the GUI at turn start,
   so a provider change can invalidate a worker unless generation cancellation
   completes cleanly.
4. Best-effort persistence catches failures, which preserves UI availability
   but can hide lost dialogue history; diagnostics should expose persistence
   failures rather than silently treating them as success.
5. The next safe extraction is a non-Qt `DialogueTurnService` containing
   context assembly, turn classification, retry policy, and persistence
   commands, leaving `DialogueTab` as a view/controller.

The first part of that extraction is now implemented in
`agents/dialogue_conversation.py`. `NaturalDialogue` retains the complete
spoken Edward/Jacob (and human) text while separately annotating questions,
proposals, action intents, decision markers, evidence IDs, and optional GoT
node links. `DialogueTab` records accepted human and persona turns into this
bounded transcript. These annotations are advisory: a conversational
`APPROVED`, a GoT recommendation, or a model question cannot authorize an
external action; the existing evidence and authorization gates remain
authoritative.

Live mode is now an event-driven runtime rather than a paired-round loop.
`agents/agent_runtime.py` owns generic agent descriptors, mutable working
state, event records, attention, availability, and speaking opportunities.
Runtime events are also published as typed `COGNITION_UPDATE` messages through
the shared `agents.comms.EventBus`, so UI projections and future agents can
react without taking ownership of the scheduler.

Live recovery is intentionally non-terminal. Empty, malformed, duplicate, and
provider-error outputs are not admitted as persona turns; they produce a
bounded recovery directive, an observable retry message, and a delayed retry
for the same speaking opportunity. Live maintains one independent inference
worker per persona, so Edward and Jacob can generate and finish concurrently;
completion order, not a fixed Edward-first turn order, determines which event
is incorporated next. Live only stops from an explicit operator Stop,
model/provider replacement, an unavailable runtime, or an intentional
configured exchange limit. Manual and Auto-Step retain their bounded retry and
stop behavior. If the operator has not entered a goal, the personas use the
default earning objective `Earn any amount of money or crypto`; the objective
is always editable before or during a session. Dialogue adapter calls disable
model reasoning mode for Qwen/DeepSeek-style profiles: their reasoning channel
can consume the entire bounded output budget and produce no visible
conversation, even while the server reports normal token throughput. GoT
artifacts remain available to the runtime and observability layers; they are
not a prerequisite for ordinary persona speech. Each Dialogue context also
receives a bounded read-only projection of the latest Social Activity events,
Self-Improvement learning records, and Autonomous Learning run states, so both
personas can discuss discovered leads, verified learning, and pending/failing
runs without treating those records as authorization.

Thinking-channel handling is capability-based:

- Inline `<think>...</think>` output and provider `reasoning_content` are
  stripped from the persona transcript while the visible answer is retained.
- Models with no thinking channel are sent ordinary dialogue requests.
- Live dialogue defaults to visible-answer mode (`DIALOGUE_ENABLE_THINKING` is
  unset), preventing private reasoning from consuming the whole response
  budget.
- Operators may opt in with `DIALOGUE_ENABLE_THINKING=1` for compatible
  Qwen/DeepSeek/Nemotron-style models; those turns receive a larger bounded
  generation budget and still require a visible final response.

The model profile registry also identifies GLM-4 and Liquid LFM models
explicitly. GLM uses its gMASK/sop family template while remaining a normal
visible-answer dialogue model; LFM is treated as a visible-answer,
non-tool-calling family. This prevents either active model from inheriting
inappropriate Qwen/Gemma/ generic-Llama assumptions.
Edward and Jacob remain stable identities with driver/navigator roles, but
they are no longer special-case scheduling branches. A completed natural turn
publishes a runtime event, updates the speaking agent's state, and lets the
attention scheduler select the next useful speaker; an agent may eventually
remain silent, ask, challenge, investigate, or interrupt rather than speaking
merely because a turn is owed. Manual, Step, and Auto-Step retain their
bounded sequential behavior. Runtime state is advisory: evidence, decision
policy, authorization, and action results remain authoritative.

### 4. Opportunity discovery and earning

Primary files:

- `earning_pipeline.py`
- `agents/earning_discoverer.py`
- `agents/discovery_engine.py`
- `agents/earning_discovery_service.py`
- `agents/discovery_sources.py`
- `agents/discovery_scheduler.py`
- `agents/discovery_strategies.py`
- `agents/opportunity_scanner.py`
- `agents/opportunity_intelligence.py`
- `agents/earning_opportunity_adapters.py`
- `agents/opportunity_models.py`
- `agents/earning_evaluation_service.py`
- `agents/earning_intelligence_service.py`
- `agents/earning_ranking_service.py`
- `agents/earning_portfolio_service.py`
- `agents/earning_submission_service.py`
- `agents/earning_proposal_service.py`
- `agents/earning_execution_service.py`
- `agents/earning_task_adapters.py`
- `agents/earning_evidence_service.py`
- `agents/earning_payment_service.py`
- `agents/earning_accounting_service.py`
- `agents/opportunity_lifecycle.py`
- `agents/opportunity_portfolio.py`
- `agents/opportunity_commands.py`
- `agents/opportunity_dialogue_bridge.py`
- `agents/freelance_finder.py`
- `agents/job_search_worker.py`
- platform clients such as `fiverr_client.py`, `upwork_client.py`,
  `microtask_client.py`, and `social_earning_platform.py`.

Assessment: this is a legitimate domain, but it is spread across discovery,
evaluation, lifecycle, portfolio, execution, and platform-specific modules.
The domain should be retained, but platform adapters should implement a small
interface and should not leak provider/network details into lifecycle logic.

The earning-domain decomposition is now underway. The legacy pipeline's
translation boundary is owned by `agents/earning_opportunity_adapters.py`;
discovery orchestration and canonical-result persistence are owned by
`agents/earning_discovery_service.py`;
provider-facing semantic scoring and deterministic heuristic fallback are owned
by `agents/earning_evaluation_service.py`; the pipeline still owns the
portfolio projection and graph ranking, while
`agents/earning_intelligence_service.py` owns the canonical conversion and
policy-backed intelligence evaluation;
`agents/earning_ranking_service.py` owns evidence-aware Graph-of-Thoughts
ranking and rank attachment;
`agents/earning_portfolio_service.py` owns the deterministic projection from
evaluated opportunities into the persistent portfolio queue;
`agents/earning_submission_service.py` owns submission-ramp bookkeeping so
attempts advance the human/automation gate without falsely recording wins;
`agents/earning_proposal_service.py` owns proposal review, confirmation/ramp
gates, throttled client submission, and submission evidence creation;
`agents/earning_execution_service.py` owns source-to-executor dispatch while
the guarded source-specific adapters remain on the compatibility pipeline
until their own provider boundaries are migrated;
`agents/earning_task_adapters.py` now owns the airdrop, DeFi, microtask, and
simple/referral source-specific execution adapters, including their feature
and human-approval policy checks;
`agents/earning_evidence_service.py` owns pending manual-attestation
construction and affirmative-verification checks; lifecycle transitions remain
authoritative in `OpportunityLifecycleTracker`;
`agents/earning_payment_service.py` owns realized gas ledger writes and reads;
`agents/earning_accounting_service.py` owns the verified/unverified
revenue-and-expense projection used by pipeline reports;
`earning_pipeline.py` remains the compatibility facade and delegates both
canonical-to-legacy discovery adaptation and legacy-to-canonical intelligence
input through that module. This preserves the public
`earning_pipeline.Opportunity` API while making the next discovery,
evaluation, and execution service moves independently testable.

The unified browser controller now lives in `agents/integrations/browser.py`;
`agents/web_controller.py` remains a compatibility façade, while freelance
and microtask discovery use the canonical browser integration.

Ethical web scraping now lives in `agents/integrations/scraper.py`;
`agents/web_scraper.py` remains a compatibility façade, and GUI worker tooling
uses the canonical scraper path.

### 5. Execution and workspace

Primary files:

- `action_pipeline.py`
- `agents/task_executor.py`
- `agents/task_validator.py`
- `agents/task_validators.py`
- `agents/task_workspace.py`
- `agents/task_spec.py`
- `agents/workflow_engine.py`
- `agents/workflow_planner.py`
- `agents/workshop.py`
- `agents/workspace_context.py`
- `agents/tool_calling.py`
- `agents/tools.py`
- `agents/tool_safety.py`
- `agents/safety_gate.py`
- `agents/sql_safety.py`

Assessment: the safety boundary is valuable, but `action_pipeline.py`,
`tool_calling.py`, `tools.py`, and task execution overlap. The desired target
is one mutation authorization service with adapters for file, command,
workshop, and external actions.

### 6. Evidence, accounting, and trust

Primary files:

- `agents/evidence.py`
- `agents/evidence_factory.py`
- `agents/evidence_policy.py`
- `agents/evidence_store.py`
- `agents/payment_evidence.py`
- `agents/numeric_evidence.py`
- `agents/fact_ledger.py`
- `agents/provenance.py`
- `agents/trust_boundary.py`
- `agents/instruction_gate.py`
- `agents/epistemic_calibration.py`
- `agents/contradictions.py`
- `agents/state_reconciliation.py`
- `agents/economic_accounting.py`
- `agents/payout_verifier.py`

Assessment: this is one of the strongest conceptual areas. It should become a
clearly isolated domain service because it is the system's authoritative
truth boundary. Avoid duplicating evidence-like structures in cognition,
memory, goals, and opportunity modules.

### 7. Autonomous execution and recovery

Primary files:

- `agents/autonomous_loop.py`
- `agents/autonomous_run_store.py`
- `agents/recovery.py`
- `agents/comms.py`
- `agents/comms_log.py`
- `agents/autonomy/heartbeat.py`
- `agents/autonomy/agent_registry.py`
- `agents/autonomy/self_improvement.py`
- `agents/autonomy/cli.py`

Assessment: the durable run store and restart recovery are good foundations.
The remaining concern is scale: queue bounds, rate limits, backpressure,
provider quotas, and priority scheduling are not yet unified in one scheduler.

### 8. Financial, wallet, and trading features

Primary files:

- `agents/live_trading.py`
- `agents/paper_trading.py`
- `agents/crypto_payments.py`
- `agents/real_crypto_operator.py`
- `agents/wallet.py`
- `agents/wallet_crypto.py`
- `agents/wallet_manager.py`
- `agents/gas_estimator.py`
- `agents/chain_verifier.py`
- `agents/defi_scanner.py`
- `agents/rug_screen.py`
- `agents/backtesting.py`

Assessment: these are high-risk optional capabilities. They should be
isolated behind an explicit feature boundary and should not be imported or
initialized by the default desktop path unless enabled.

### 9. Memory and learning

Primary files:

- `earning_memory.py`
- `agents/layered_memory.py`
- `agents/memory_promotion.py`
- `agents/program_knowledge.py`
- `agents/shared_context.py`
- `agents/goal_system.py`
- `agents/learning_safety.py`
- `agents/self_audit.py`
- `agents/reputation.py`

Assessment: this is a second major overlap zone. Memory, goals, learning,
program knowledge, and shared context should have explicit ownership and
retention policies. Otherwise data is duplicated across SQLite stores and
in-memory caches.

## Persistence map

The current authoritative stores are:

| Store | Intended authority |
|---|---|
| `agent.db` | Agent events, thoughts, settings, instruction provenance, and general evidence |
| `earning.db` | Earning pipeline lifecycle, pipeline records, and accounting-related state |
| `earning_memory.db` | Opportunity memory and learning outcomes |
| `opportunity_portfolio.db` | Queue/work-status projection |
| `autonomous_runs.db` | Durable autonomous runs, stages, and idempotency |
| `goals.db` | Goal subsystem |
| `job_search.db` | Job-search subsystem |
| `dual_brain.db` | Dual-brain/UI runtime state |

The first five are documented in
[agents/persistence_contract.py](agents/persistence_contract.py). The remaining
databases need the same authority/projection classification before further
scaling work.

## Complexity concentration

Largest tracked Python modules:

| Module | Approx. lines | Main concern |
|---|---:|---|
| `gui/dual_brain_control.py` | 3,557 | GUI, subprocesses, provider lifecycle, hardware/configuration |
| `main.py` | 3,231 | Application composition and cross-subsystem integration |
| `gui/tab_builders.py` | 2,827 | UI construction and cross-tab wiring |
| `gui/dialogue_tab.py` | 1,909 | Dialogue, context, model workers, tool visibility |
| `earning_memory.py` | 1,803 | Large memory/learning domain |
| `earning_pipeline.py` | 1,551 | Discovery/evaluation/execution/lifecycle orchestration |
| `manager.py` | 1,485 | Heartbeat, worker scheduling, UI/runtime coordination |
| `agents/base_worker.py` | 1,290 | Legacy provider registry and general worker behavior |
| `ui.py` | 1,246 | Shared UI widgets and thought visualization |
| `agents/tool_calling.py` | 1,141 | Tool definitions, dispatch, safety, parsing, execution |

These ten files account for a disproportionate amount of system complexity.
They should be the first targets for extraction and dependency reduction.

## Likely over-bloated or overlapping areas

### High-confidence consolidation targets

1. **Provider configuration**
   - `main.py`
   - `gui/provider_config_widget.py`
   - `gui/dual_brain_control.py`
   - `agents/base_worker.py`
   - `agents/dual_brain_runtime.py`
   - `agents/configuration.py`

2. **Tool and mutation execution**
   - `action_pipeline.py`
   - `agents/tool_calling.py`
   - `agents/tools.py`
   - `agents/task_executor.py`
   - `agents/workflow_engine.py`

3. **Memory and learning**
   - `earning_memory.py`
   - `agents/layered_memory.py`
   - `agents/memory_promotion.py`
   - `agents/program_knowledge.py`
   - `agents/shared_context.py`

4. **Opportunity orchestration**
   - `earning_pipeline.py`
   - `agents/discovery_engine.py`
   - `agents/earning_discoverer.py`
   - `agents/opportunity_scanner.py`
   - `agents/opportunity_intelligence.py`

5. **GUI composition**
   - `main.py`
   - `gui/tab_builders.py`
   - `gui/dual_brain_control.py`

### Features that should be optional modules

- Live trading.
- Wallet and crypto operations.
- Airdrop claiming.
- DeFi scanning.
- Web/social platform automation.
- Cloud provider integrations.
- Self-improvement and autonomous learning.

They should not increase default startup cost or failure surface when disabled.

## Phase 1 refactoring baseline and compatibility contracts

Phase 1 establishes the measured baseline and the contracts that must remain
stable while the integration hubs are extracted. The following counts were
generated from the current tracked source tree; they are sizing and coupling
signals, not a reason to rewrite a module wholesale.

| Surface | Lines | Top-level symbols | Imports | Primary responsibility currently mixed in |
|---|---:|---:|---:|---|
| `gui/dual_brain_control.py` | 3,841 | 8 | 13 | Qt UI, provider lifecycle, GPU/process management, model selection, VRAM checks, and the handler bridge |
| `main.py` | 3,561 | 14 | 31 | Application composition, environment writes, workers, startup, shutdown, tabs, logging, and provider wiring |
| `gui/tab_builders.py` | 3,354 | 4 | 11 | Lazy tabs, refresh/lifecycle behavior, feature builders, workers, and cross-tab bridges |
| `earning_memory.py` | 1,998 | 9 | 10 | SQLite persistence, metrics, scoring, recency, strategy usefulness, and memory entries |
| `earning_pipeline.py` | 1,719 | 4 | 15 | Opportunity models, discovery/evaluation, lifecycle, GoT, feature flags, and memory |
| `manager.py` | 1,656 | 3 | 13 | Qt thread orchestration, queues, routing, heartbeat, worker assignment, and runtime stats |
| `agents/base_worker.py` | 1,435 | 12 | 13 | Legacy provider runtime, token/context policy, filesystem helpers, registry state, and compatibility exports |
| `agents/tool_calling.py` | 1,252 | 35 | 12 | Tool schemas, authorization, handlers, streaming transport, response cleanup, and text tool parsing |
| `library.py` | 812 | 19 | 16 | Queues, prompt/response helpers, memory, logging, file watching, caches, registries, and text utilities |

### Current import ownership findings

- GUI/provider modules import guarded environment writes from `main.py`;
  environment persistence must move behind an application service before
  `main.py` is reduced.
- `manager.py`, `earning_pipeline.py`, GUI builders, agents, and tests import
  compatibility symbols from `agents/base_worker.py`.
- Agents and tests import unrelated services from `library.py`, so it must
  become a compatibility re-export module before its contents are split.
- Tests directly import `MainWindow`, `ManagerThread`, `WorkerAgent`,
  `BrainLaunchWorker`, `DualBrainControl`, `ProviderStatusChecker`, and
  `TabBuildersMixin`; these are public compatibility surfaces until migration
  tests prove otherwise.
- `gui/dual_brain_control.py` currently exposes provider behavior through a
  dynamic handler bridge that delegates implementations to
  `BrainLaunchWorker`. This bridge is a known wiring risk and is scheduled for
  removal only after explicit service methods exist.
- `agents/tool_calling.py` already delegates mutation authorization to
  `agents/authorized_actions.py`; extraction must preserve that single
  authorization path rather than creating another dispatcher.

### Compatibility contracts for extraction

1. **Provider runtime authority** — new services read normalized role/provider/
   device/model configuration from `agents/configuration.py` and
   `agents/dual_brain_runtime.py`. GUI code emits requests and renders state;
   it does not become a second configuration authority.
2. **Dual Brain GUI API** — preserve `DualBrainControl`,
   `ProviderStatusChecker`, `BrainLaunchWorker`, model-change signals,
   provider-probe signals, start/stop behavior, and thread cleanup while the
   implementation moves behind services.
3. **Application environment API** — preserve `EnvWriteRefused`,
   `env_file_path`, `set_env_values`, and guarded-write semantics while their
   implementation moves out of `main.py`.
4. **Tab builder API** — preserve `TabBuildersMixin`, lazy construction,
   tab-index stability, current-tab restoration, goal bridges, and
   visibility-aware refresh behavior.
5. **Legacy worker API** — preserve `WorkerAgent`, `ROOT_FOLDER`,
   `context_tokens`, `project_file_tree`, registry access, and legacy provider
   behavior through temporary re-exports.
6. **Tool safety API** — preserve `get_all_tools`, `execute_tool`,
   `chat_with_tools`, response sanitization, approval queue behavior, safe mode,
   and the `AuthorizedActionDispatcher` boundary.
7. **Manager runtime API** — preserve `ManagerThread` signals, queue limits,
   worker assignment, heartbeat behavior, `RuntimeStats` compatibility imports,
   and shutdown semantics.
8. **Earning domain authority** — preserve lifecycle/evidence/persistence
   authority and equivalent scoring, memory promotion, and payment-evidence
   behavior while the domain is split.

### Removal gate

A compatibility module or alias may be removed only when:

- Import-boundary tests pass.
- Focused behavior tests pass.
- GUI/thread shutdown tests pass where applicable.
- Runtime usage evidence shows no supported callers for the observation
  window.
- A repository-wide search finds no active imports of the removed symbol.

## Phase 2 provider and application-service extraction

Phase 2 has moved the first application and provider boundaries without
changing public GUI behavior:

- `app/environment.py` owns guarded `.env` persistence. `main.py` re-exports
  `EnvWriteRefused`, `env_file_path`, and `set_env_values` for compatibility.
- `agents/provider_lifecycle.py` owns provider probing, loaded-model checks,
  model load/unload calls, model-id normalization, and probe caching without
  importing Qt.
- `gui/brain_launch_worker.py` owns llama-server process launch, adoption,
  readiness, cancellation, and process logging.
- `gui/provider_workers.py` owns provider probe and stop QThreads.
- `gui/provider_lifecycle_backend.py` owns provider-control operations used by
  the Qt facade.
- `gui/dual_brain_control.py` is now a `ProviderLifecycleBackend` facade plus
  widget-specific GPU/settings presentation. The dynamic `_provider_handler`
  bridge has been removed.

Historical imports from `gui.dual_brain_control` remain available while
callers migrate. Worker classes and provider status are compatibility
re-exports, while lifecycle methods are normal inherited methods rather than
dynamically installed handlers.

## Phase 3 tab construction and lifecycle extraction

Tab construction is now composed from focused mixins and worker modules:

- `gui/tab_lifecycle.py` owns scroll wrapping, lazy tab replacement, current-tab
  restoration, background pause/resume traversal, and first-show Settings
  refresh behavior.
- `gui/tab_workers.py` owns the data-explorer, live-portfolio, and social
  discovery QThreads.
- `gui/tab_feature_builders.py` owns feature-specific `create_*_tab` methods.
- `gui/tab_builders.py` composes `TabLifecycleMixin` and
  `FeatureTabBuildersMixin` as the compatibility-facing `TabBuildersMixin`.

This keeps `MainWindow`'s existing mixin import and tab-builder method surface
stable while removing lifecycle and worker mechanics from the feature-builder
module.

## Phase 4 tool-calling boundary extraction

Tool calling is now split into explicit compatibility-preserving boundaries:

- `agents/tool_registry.py` owns the canonical tool schemas exposed to model
  providers.
- `agents/tool_handlers.py` owns web, workshop, filesystem, system, and
  database handler implementations.
- `agents/tool_dispatch.py` owns the single authorization and dispatch entry
  point.
- `agents/tool_response.py` owns reasoning-channel cleanup, visible-response
  extraction, tool syntax removal, and text tool-call parsing.
- `agents/chat_completion.py` owns the streaming completion loop and bounded
  tool rounds.
- `agents/tool_calling.py` remains the compatibility-facing import surface and
  retains shared policy helpers and compatibility symbols.

The dispatcher continues to route every mutating operation through
`AuthorizedActionDispatcher`; the extraction does not introduce a second
authorization path.

## Phase 5 legacy worker runtime extraction

The legacy `WorkerAgent` runtime now composes focused compatibility mixins:

- `worker_provider_mixin.py` owns provider registry construction, ordering,
  role filtering, model selection, cost-aware selection, and invalidation.
- `worker_llm_mixin.py` owns context-aware output budgeting, retries, provider
  fallback, circuit-breaker interaction, cost guards, and telemetry.
- `worker_provider_calls.py` owns the legacy OpenAI, Anthropic, and Ollama
  call adapters.
- `worker_filesystem.py` owns safe writes, backups, research scans, file
  indexing, and specific-file reads.
- `worker_budget.py`, `worker_thinking.py`, `worker_provider.py`,
  `worker_safety.py`, and `worker_workspace.py` own pure helper policies.

`agents/base_worker.py` remains the compatibility façade and state owner for
existing `WorkerAgent`, `ROOT_FOLDER`, provider helper, registry, and file-tree
imports. The extraction does not change provider order, retry semantics,
filesystem safety, or public worker APIs.

## Phase 6 library compatibility decomposition

The legacy root `library.py` now serves as a compatibility façade:

- `text_utils.py` owns truncation, fingerprints, timestamps, word counts,
  code-fence extraction, and safe JSON parsing.
- `agents/prompt_utils.py` owns `ChainOfThought`, `PromptBuilder`, and
  `ResponseParser`.
- `agents/conversation_memory.py` owns `ConversationMemory` and
  `SpeechPatternBank`.
- `agents/runtime_services.py` owns `TaskQueue`, `AgentLogger`, `FileWatcher`,
  `EmbeddingCache`, and `WorkerRegistry`.
- `library.py` intentionally retains `TokenBucket` and `retry_llm` as the
  compatibility owner because existing tests and platform throttling patch the
  module clock directly.

Existing `from library import ...` imports remain valid. The lazy
`agents/__init__.py` exports prevent the compatibility façade from eagerly
importing every worker and avoid package-initialization cycles.

## Agents package organization plan

The `agents/` package currently contains 162 modules, including several
existing subpackages and a large flat root. Future moves must be staged by
ownership; no broad filesystem move should precede import and public-symbol
inventory.

### Target layout

```text
agents/
  runtime/        # worker runtime, context budgets, registries, recovery
  providers/      # provider adapters, provider configuration/lifecycle
  cognition/      # cognition records, ledgers, reasoning, planning
  dialogue/       # personas, dialogue state, honesty, communication
  earning/        # opportunities, discovery, lifecycle, proposals, tasks
  evidence/       # evidence, provenance, facts, verification, accounting
  safety/         # gates, authorization, trust, SQL and capability policy
  tools/          # schemas, dispatch, handlers, response/completion adapters
  persistence/    # durable stores, canonical state, reconciliation
  integrations/   # web, platforms, job search, external service clients
  optional/       # trading, wallet/crypto, social, airdrop, DeFi, autonomy
```

Existing `autonomy/`, `platforms/`, and `providers/` packages remain valid
boundaries and should be expanded rather than duplicated. Root-level modules
such as `base_worker.py`, `tool_calling.py`, and `dual_brain_runtime.py` stay
as compatibility façades until all callers migrate.

### Collision and authority review

The following names require an explicit canonical owner before moving:

- `tool_calling.py` and `tools.py` — tool schemas/dispatch versus legacy tool
  helpers.
- `safety_gate.py`, `safety_guard.py`, `authorized_actions.py`, and
  `tool_safety.py` — authorization, policy, and input safety must not become
  duplicate mutation boundaries.
- `discovery_engine.py`, `discovery_port.py`, `discovery_scheduler.py`,
  `discovery_sources.py`, and `discovery_strategies.py` — separate ports,
  scheduling, source adapters, and strategy generation.
- `task_validator.py` and `task_validators.py` — establish one validator
  registry and preserve compatibility imports.
- `wallet.py`, `wallet_crypto.py`, `wallet_manager.py`, and
  `crypto_payments.py` — separate storage/crypto primitives from optional
  operator integrations.
- `worker_*` helpers and `base_worker.py` — runtime façade versus pure helper
  modules.

### Migration rules

1. Add the destination package and `__init__.py` before moving a module.
2. Move one ownership slice at a time and preserve root-level re-exports.
3. Prefer absolute canonical imports inside `agents`; compatibility imports
   are allowed only at façades and are tracked for removal.
4. Keep optional modules lazy and behind feature flags.
5. Do not change authority, safety, persistence, or lifecycle semantics while
   changing paths.
6. Remove scratch files such as `tmp_small_brain_new.py` only after repository
   usage searches and runtime usage evidence show they are unused.
7. Validate package-wide imports after every slice, not only at the end.

## Healthy areas to preserve

- Explicit human approval for mutating tools.
- Fail-closed action validation.
- Evidence-based lifecycle transitions.
- Durable autonomous-run persistence and idempotency.
- State reconciliation across stores.
- Safe mode.
- Provider/model role separation.
- Redacted configuration diagnostics.
- Broad domain-level tests.

## Recommended target architecture

```text
Qt views
  ↓
Application services
  ↓
Domain services
  ├─ Opportunity service
  ├─ Evidence/accounting service
  ├─ Autonomy scheduler
  ├─ Provider/model service
  └─ Authorized action service
  ↓
Ports/adapters
  ├─ SQLite repositories
  ├─ LLM providers
  ├─ Platform clients
  ├─ Wallet/exchange adapters
  └─ Filesystem/workshop
```

The key rule should be that domain services do not import Qt, subprocess
details, provider SDKs, or direct environment parsing. Those concerns belong
in adapters and application services.

## Trim/reduction sequence

1. Finish normalized provider configuration adoption.
2. Extract provider lifecycle from `gui/dual_brain_control.py`.
3. Split `main.py` into bootstrap, settings, runtime lifecycle, and shutdown
   services.
4. Create one authorized-action dispatcher for all mutations.
5. Consolidate the opportunity orchestration interfaces.
6. Establish one memory/learning ownership model.
7. Move live financial and social adapters behind optional feature packages.
8. Add authority contracts for all remaining SQLite databases.
9. Add import-boundary checks so GUI and optional adapters do not leak into
   core domain modules.
10. Delete or archive obsolete compatibility paths only after usage metrics and
    tests confirm they are unused.

## Current conclusion

MrBot1000 is in good shape conceptually but not yet lean. It has a strong
product core surrounded by many integrations and historical layers. The
appropriate goal is not a wholesale rewrite. It is a staged reduction of
integration hubs, duplicate configuration paths, overlapping memory/tool
systems, and default startup surface.

## Blueprint adoption progress

The 2.1 blueprint is being adopted incrementally rather than copied as a
second runtime. The first non-breaking slice separates economic prediction
from decision policy in `agents/economic_policy.py`. `EconomicPrediction`
preserves payout, success/payment probabilities, independent costs, productive
time, payment delay, confidence, freshness, and assumptions. `DecisionPolicy`
and `evaluate_prediction()` apply deterministic thresholds and capability
gates, producing `SELECT`, `DEFER`, `RESEARCH_MORE`, or `REJECT` records.

This contract is intentionally additive: the existing opportunity-intelligence
verdicts and earning pipeline remain authoritative until integration tests
demonstrate equivalent behavior. Future slices should connect the contract to
the read-only evaluation flow. The opportunity GoT planner now also enforces
candidate, node, cost, and elapsed-time budgets and retains compact rejection
reasons in its audit summary. Layered memory retrieval now preserves
provenance/verification metadata and excludes quarantined entries. The
authorization dispatcher accepts optional, expiring capability-scoped
autonomy grants while preserving existing callers. Persistence authority now
explicitly classifies portfolio and dual-brain stores as projections and goals
and job-search stores as separate subsystem authorities. Discovery selection
and source orchestration now cross the narrow
`agents/discovery_port.py` boundary; evaluation, memory writes, and lifecycle
transitions remain in the pipeline until their contracts are extracted.

## Performance and consolidation execution contract

The reduction work should be delivered in measurable vertical slices:

1. **Baseline telemetry:** record startup duration, idle CPU/memory, prompt
   characters/tokens, first-token latency, total model latency, retries, and
   GUI refresh/update counts. Metrics must be available without a live provider.
2. **Prompt budget:** every request uses exactly one bounded mode:
   `fast` (4,000 characters), `standard` (10,000), or `deep` (18,000).
   Existing technique names remain compatibility labels, but techniques must
   not be stacked implicitly.
3. **Shared GUI refresh:** visible views consume a shared runtime snapshot;
   hidden views stop active timers rather than polling at a slower interval.
4. **Provider authority:** `agents/configuration.py` and
   `agents/dual_brain_runtime.py` are the only provider configuration
   authorities. Legacy callers migrate through adapters before removal.
5. **Mutation authority:** all mutating work crosses one deterministic
   authorization/validation dispatcher, preserving human gates and safe mode.
6. **Optional boundaries:** trading, wallet/crypto, social automation, cloud
   SDKs, self-improvement, and autonomous learning are lazy and disabled by
   default unless explicitly configured.
7. **Removal gate:** a legacy path is deleted only after import-boundary tests,
   targeted behavior tests, and runtime usage evidence show that it is unused.

Phase 1 is implemented with provider-independent in-memory telemetry for
startup duration, process CPU, Python memory, prompt characters/tokens, model
latency, first-token latency, errors, retries, and GUI refresh batches. Phase
2 is implemented with bounded `fast`/`standard`/`deep` prompt enforcement at
both adaptive and caller-supplied system-prompt boundaries. The next slices
should continue migrating secondary views to the shared refresh coordinator.

Phase 3 is implemented for the active operational views: approval, earning,
collaboration, notifications, payments, and provider configuration. They now
register callbacks with `gui/refresh_coordinator.py`, which uses one timer and
refreshes only visible entries; hidden views stop polling rather than falling
back to a 15-second background timer. The coordinator is deliberately
visibility-aware so future snapshot/event integration can replace callbacks
without changing each view's lifecycle hooks.

Phase 4 is complete: the provider adapter registry in
`agents/base_worker.py` now consumes normalized values from
`agents/configuration.py` for supported provider URLs, models, chat models,
and enablement, including the legacy `DISABLE_LM_STUDIO` spelling. Existing
provider defaults and role-specific gates remain compatible. Provider
discovery/probing in `agents/provider_manager.py` now consumes the same
normalized settings for local endpoints and cloud-key presence, while
role/provider selection resolves through `DualBrainRuntime`. The remaining
direct environment read there is for locating the external llama-server binary,
which is launcher infrastructure rather than provider configuration.

Phase 5 is complete for mutation authorization. `agents/authorized_actions.py`
is now the canonical authorization dispatcher: it delegates classification to
`SafetyGate`, returns explicit blocked/pending/allowed results, and only
invokes an implementation after authorization. `agents/tool_calling.py` uses
this dispatcher for all chat tools, while `action_pipeline.py` can require the
same boundary with `metadata["authorization_required"]` and an explicit
approval marker. Existing validators, human approval queue behavior, and safe
mode remain intact. `TaskExecutor` and `workflow_engine` continue to manage
domain lifecycle/status transitions; they do not directly perform machine
mutations and therefore do not duplicate the dispatcher.

Phase 6 is complete for optional capability boundaries. The new
`agents/feature_flags.py` registry fails closed for live trading, crypto
operations, airdrops, DeFi, social automation, self-improvement, and
autonomous learning. Legacy `ENABLE_*` names remain compatible, but the new
`MRBOT_ENABLE_*` values take precedence. Live Portfolio and Strategy
Simulator tabs are omitted unless live trading is explicitly enabled.
Earning-pipeline imports for social, airdrop, DeFi, microtask, and dynamic
discovery are lazy, and disabled airdrop/DeFi sources and execution paths
return explicit policy-blocked results without importing their adapters.

Phase 7 is complete as a controlled removal gate. The
`agents/architecture_boundaries.py` checker enforces that core domain modules
do not import Qt, GUI modules, or provider SDKs, and that application bootstrap
does not eagerly import optional trading, wallet, DeFi, airdrop, or social
adapters. `UsageLedger` provides runtime evidence for compatibility paths;
paths may be removed only after boundary tests pass and the ledger shows zero
observed uses for the supported observation window. No legacy path is deleted
without that evidence.

Phase 8 (earning-domain decomposition) is complete. Opportunity model
translation, discovery, evaluation, intelligence, graph ranking, portfolio
projection, proposal submission, task adapters, evidence helpers, payment
ledger access, and accounting projections now have explicit service
boundaries. Lifecycle, evidence, and accounting authority remains in the
existing composition root and canonical domain services. The compatibility
pipeline continues to preserve the legacy public API.

The final Phase 8 validation gate passed 172 focused discovery, evaluation,
ranking, portfolio, proposal, evidence, payment, accounting, and section-D
tests, plus compilation of the pipeline and all `agents/earning_*.py` modules.

## Phase 9 manager orchestration

Phase 9 has started with `agents/manager_routing.py`, which owns pure intent
classification and worker-specialty routing. `manager.py` retains compatibility
wrappers and all Qt signal/thread behavior. A missing `threading` and
`defaultdict` import exposed by the extracted conversation-memory boundary was
also restored, and the manager/comms regression set now passes.

`agents/manager_queues.py` now owns bounded operator/task queue insertion,
including the drop-oldest overflow policy. `manager.py` retains the queue
objects and compatibility methods while delegating the queue mutation policy.

`agents/manager_workers.py` now owns worker roster registration, free-worker
selection, and busy/free ownership state. Qt signal emission remains supplied
through callbacks by `ManagerThread`, and the legacy `_roster` view remains
available for compatibility.

`agents/manager_scheduler.py` now owns adaptive poll backoff and idle-heartbeat
due-time policy. `ManagerThread` retains the heartbeat loop, work execution,
signals, and shutdown lifecycle while delegating cadence decisions.

`agents/manager_metrics.py` now owns manager heartbeat metric projections,
summary formatting, and composition of runtime telemetry with queue backlog
state. `ManagerThread.get_runtime_stats()` remains the compatibility entry
point and preserves its output shape.

`agents/manager_shutdown.py` owns the Qt-independent, idempotent stop request
policy. `ManagerThread.stop()` remains the public lifecycle entry point; Qt
thread ownership and signal behavior stay in `manager.py`.

## Runtime package organization

The standalone runtime telemetry implementation now lives in
`agents/runtime/stats.py`, exported through `agents/runtime/__init__.py`.
`agents/runtime_stats.py` remains a compatibility façade for existing imports;
new runtime code should use the package boundary.

Process/model performance telemetry similarly lives in
`agents/runtime/performance.py`, with `agents/performance_telemetry.py`
preserved as a compatibility façade.

Manager runtime metrics are implemented in
`agents/runtime/manager_metrics.py`; the original
`agents/manager_metrics.py` import remains supported.

The remaining manager policies now follow the same boundary:
`manager_queues.py`, `manager_routing.py`, `manager_scheduler.py`,
`manager_shutdown.py`, and `manager_workers.py` are implemented under
`agents/runtime/`. Their original module paths remain compatibility façades,
while `manager.py` uses the canonical runtime package imports.

The former `agents/runtime_services.py` implementation now lives in
`agents/runtime/services.py`, covering task queues, structured agent logging,
file watching, embedding caching, and dynamic worker discovery. The original
module remains a compatibility façade, and `library.py` uses the canonical
package path.

Provider-facing semantic opportunity evaluation now lives in
`agents/earning/evaluation.py`; `agents/earning_evaluation_service.py` remains
a compatibility façade, and the pipeline imports the canonical path.

Deterministic earning intelligence evaluation now lives in
`agents/earning/intelligence.py`; `agents/earning_intelligence_service.py`
remains a compatibility façade, and the pipeline uses the canonical package.

## Optional integrations package organization

The Upwork client now lives in `agents/integrations/upwork.py`;
`agents/upwork_client.py` remains a compatibility façade. Internal earning,
discovery, and job-search callers use the canonical optional-integration path.

The Fiverr client now lives in `agents/integrations/fiverr.py`;
`agents/fiverr_client.py` remains a compatibility façade, while earning,
discovery, and job-search callers use the canonical integration path.

Wallet storage, encryption, and manager adapters now live in
`agents/integrations/wallet.py`, `wallet_crypto.py`, and `wallet_manager.py`.
The original root modules remain compatibility façades; canonical payment,
chain-verification, and wallet-manager callers use the integration package.

Crypto payment intent and transaction packaging now live in
`agents/integrations/crypto.py`; `agents/crypto_payments.py` remains a
compatibility façade, while the real-crypto operator uses the canonical
integration module.

The WebEyes browsing adapter now lives in `agents/integrations/web_eyes.py`;
`agents/web_eyes.py` remains a compatibility façade so existing tool-handler
patch points stay stable.

The microtask client now lives in `agents/integrations/microtask.py`;
`agents/microtask_client.py` remains a compatibility façade, while earning,
discovery, and microtask execution callers use the canonical integration path.

The configurable web search provider now lives in `agents/integrations/web.py`;
`agents/web_provider.py` remains a compatibility façade, while job search and
web discovery use the canonical integration path.

Evidence-aware graph ranking now lives in `agents/earning/ranking.py`;
`agents/earning_ranking_service.py` remains a compatibility façade, and the
pipeline imports the canonical ranking boundary.

Portfolio projection now lives in `agents/earning/portfolio.py`;
`agents/earning_portfolio_service.py` remains a compatibility façade, and the
pipeline uses the canonical portfolio boundary.

Submission-ramp bookkeeping now lives in `agents/earning/submission.py`;
`agents/earning_submission_service.py` remains a compatibility façade, and
the pipeline uses the canonical earning package.

Safety-gated proposal submission now lives in `agents/earning/proposal.py`;
`agents/earning_proposal_service.py` remains a compatibility façade, and the
pipeline imports the canonical proposal boundary.

Source-to-executor dispatch now lives in `agents/earning/execution.py`;
`agents/earning_execution_service.py` remains a compatibility façade, and the
pipeline uses the canonical execution boundary.

Source-specific task adapters now live in `agents/earning/tasks.py`;
`agents/earning_task_adapters.py` remains a compatibility façade, while the
pipeline uses the canonical task package.

Earning evidence helpers now live in `agents/earning/evidence.py`;
`agents/earning_evidence_service.py` remains a compatibility façade, and the
pipeline uses the canonical evidence boundary.

Payment-side gas ledger operations now live in `agents/earning/payment.py`;
`agents/earning_payment_service.py` remains a compatibility façade, while
economic accounting authority remains unchanged.

Accounting report projections now live in `agents/earning/accounting.py`;
`agents/earning_accounting_service.py` remains a compatibility façade, while
`EconomicAccounting` remains the calculation authority.

Earning Graph-of-Thought planning now lives in `agents/earning/got.py`;
`agents/earning_got.py` remains a compatibility façade, and ranking/pipeline
code uses the canonical earning package.

The legacy dynamic web discoverer now lives in
`agents/earning/discoverer.py`; `agents/earning_discoverer.py` remains a
compatibility façade. It is intentionally not eagerly exported from the
earning package because its optional web dependencies must remain lazy.

The guarded local earning capability now lives in
`agents/earning/capability.py`; `agents/earning_capability.py` remains a
compatibility façade, and the GUI/CLI use the canonical earning package.

## Safety and tools package organization

The canonical tool schema registry now lives in `agents/safety/tools.py`;
`agents/tool_registry.py` remains a compatibility façade, and tool-calling
internals use the safety package path.

Authorized tool dispatch now lives in `agents/safety/dispatch.py`;
`agents/tool_dispatch.py` remains a compatibility façade, and tool-calling
uses the canonical safety boundary.

Pure tool-response cleanup and text-call parsing now live in
`agents/safety/response.py`; `agents/tool_response.py` remains a compatibility
façade, and tool-calling uses the canonical response boundary.

Domain tool handlers now live in `agents/safety/handlers.py`;
`agents/tool_handlers.py` remains a compatibility façade, and tool-calling
uses the canonical handler module.

Shared local-tool safety policy now lives in `agents/safety/policy.py`;
`agents/tool_safety.py` remains a compatibility façade, and tool, gate, and
calling modules use the canonical policy path.

The unified tool-calling implementation now lives in
`agents/safety/calling.py`; `agents/tool_calling.py` remains a compatibility
façade, while handlers and chat completion use the canonical safety module.

The authoritative safety-gate implementation now lives in
`agents/safety/gate.py`; `agents/safety_gate.py` remains a compatibility
façade, preserving the single tool-classification authority.

The canonical mutation authorization boundary now lives in
`agents/safety/authorization.py`; `agents/authorized_actions.py` remains a
compatibility façade, and tool calling uses the safety package directly.

High-trust action enforcement now lives in `agents/safety/trust.py`;
`agents/trust_boundary.py` remains a compatibility façade, and learning and
opportunity scanning use the canonical trust boundary.

The multi-layer safety orchestrator now lives in `agents/safety/guard.py`;
`agents/safety_guard.py` remains a compatibility façade, and platform/crypto
mutation adapters use the canonical safety guard.

Task-scoped local deliverable workspaces now live in
`agents/safety/workspace.py`; `agents/task_workspace.py` remains a
compatibility façade, and earning, manager, and microtask code use the
canonical workspace boundary.

Worker filesystem and research operations now live in
`agents/safety/filesystem.py`; `agents/worker_filesystem.py` remains a
compatibility façade, and the worker runtime uses the canonical safety path.

Read-only SQLite validation and execution now live in
`agents/safety/sql.py`; `agents/sql_safety.py` remains a compatibility façade,
and database tool paths use the canonical safety module.

The older Big Brain tool-definition/dispatch helper now lives in
`agents/safety/legacy_tools.py`; `agents/tools.py` remains a compatibility
façade, while Big Brain and task routing use the canonical safety path.

Discovery orchestration now lives in `agents/earning/discovery.py`; the
original `agents/earning_discovery_service.py` path remains a compatibility
façade, and the earning pipeline uses the canonical package path.

The reusable provider-independent LLM runtime helpers now live in
`agents/runtime/llm.py`. The former `agents/llm_runtime.py` path remains a
compatibility façade, while worker internals use the canonical runtime path.

The event-driven cooperating-agent state machine now lives in
`agents/runtime/agent.py`, with `agents/agent_runtime.py` retained as a
compatibility façade. Dialogue uses the canonical runtime package directly.

## Cognition and Dialogue package organization

The existing `agents/cognition.py` module is an established public
Graph-of-Thought boundary. A package named `agents/cognition/` must not be
introduced until that module is migrated as a whole; doing so would shadow the
module and break existing imports. The migration is now complete: graph contracts live in
`agents/cognition/graph.py`, reasoning policies live in
`agents/cognition/reasoning_modes.py`, and `agents/cognition.py` remains a
compatibility façade.

Dialogue honesty enforcement now lives in
`agents/cognition/dialogue_honesty.py`; the original
`agents/dialogue_honesty.py` import remains supported, and the Dialogue tab
uses the canonical cognition package.

Natural Dialogue turn records now live in `agents/cognition/dialogue.py`;
`agents/dialogue_conversation.py` remains a compatibility façade, and the
Dialogue tab uses the canonical package path.

The durable cognition ledger now lives in `agents/cognition/ledger.py`;
`agents/cognition_ledger.py` remains a compatibility façade, and canonical
state wiring imports the package path directly.

Contradiction cases now live in `agents/cognition/contradictions.py`; the
legacy `agents/contradictions.py` import remains supported.

Memory-promotion policy now lives in `agents/cognition/memory_promotion.py`;
the original `agents/memory_promotion.py` path remains a compatibility
façade.

The canonical cognition state adapter now lives in
`agents/cognition/state.py`; `agents/canonical_state.py` remains a
compatibility façade.

The canonical dual-brain collaboration coordinator now lives in
`agents/cognition/coordinator.py`; `agents/dual_brain_coordinator.py` remains a
compatibility façade, and GUI feature construction uses the package path.

Persona identities and role contracts now live in
`agents/cognition/personas.py`; `agents/personas.py` remains a compatibility
façade for GUI and brain callers.

Deterministic epistemic calibration now lives in
`agents/cognition/epistemic.py`; `agents/epistemic_calibration.py` remains a
compatibility façade, and Dialogue honesty uses the canonical package path.

The append-only fact ledger now lives in `agents/cognition/fact_ledger.py`;
`agents/fact_ledger.py` remains a compatibility façade, while epistemic,
honesty, and operator-override modules use the canonical cognition path.

Operator authority records now live in `agents/cognition/operator_override.py`;
`agents/operator_override.py` remains a compatibility façade, and Dialogue
honesty uses the canonical cognition path.

## Earning package organization

The canonical opportunity translation boundary now lives in
`agents/earning/opportunity_adapters.py`; the original
`agents/earning_opportunity_adapters.py` path remains a compatibility façade.
The earning pipeline and discovery/intelligence services use the canonical
package path.

The canonical dual-brain role/provider/device runtime now lives in
`agents/runtime/dual_brain.py`; `agents/dual_brain_runtime.py` remains a
compatibility façade, and the cognition coordinator uses the runtime package
directly.
Human approval queue handling now lives in `agents/safety/approval.py`;
`agents/approval_queue.py` remains a compatibility façade, while dispatch and
safety-gate paths use the canonical approval boundary.

Remote instruction provenance and quarantine now live in
`agents/safety/instructions.py`; `agents/instruction_gate.py` remains a
compatibility façade, while tool and opportunity paths use the canonical
instruction boundary.

LLM spend-limit enforcement now lives in `agents/safety/cost.py`;
`agents/cost_guard.py` remains a compatibility façade, while the safety guard
and worker provider path use the canonical cost boundary.

Provider circuit-breaking now lives in `agents/safety/circuit.py`;
`agents/circuit_breaker.py` remains a compatibility façade, while the safety
guard and worker LLM path use the canonical circuit boundary.

Human-in-the-loop gate policy now lives in `agents/safety/gates.py`;
`agents/human_gates.py` remains a compatibility façade, and the earning
pipeline uses the canonical safety gate package.

The learning-to-action safety boundary now lives in
`agents/safety/learning.py`; `agents/learning_safety.py` remains a
compatibility façade and cannot bypass trust or human-approval controls.
Read-only live workspace context now lives in `agents/runtime/context.py`;
`agents/workspace_context.py` remains a compatibility façade, while program
knowledge uses the canonical runtime path.

The deterministic earning capability validator now lives in
`agents/earning/validator.py`; `agents/task_validator.py` remains a
compatibility façade, and pipeline wiring uses the canonical earning path.

Task-specific deterministic validators now live in
`agents/earning/validators.py`; `agents/task_validators.py` remains a
compatibility façade, and task execution/autonomous-loop callers use the
canonical earning package.

## Whole-program restructuring plan

This section is the current source of truth for the remaining architecture
work. The goal is not a blind file move; each migration must preserve public
contracts, runtime behavior, safety gates, persistence schemas, and GUI
responsiveness.

### Current completion status

| Area | Canonical package | Status | Remaining work |
|---|---|---:|---|
| Runtime telemetry and manager policies | `agents/runtime/` | Complete | Split the remaining Qt thread/loop hub |
| Cognition and Dialogue contracts | `agents/cognition/` | Mostly complete | Move prompt, communication, and memory integration |
| Earning and task domain | `agents/earning/` | Mostly complete | Finish optional domain adapters and import migration |
| Safety and tool calling | `agents/safety/` | Mostly complete | Migrate remaining callers and validate one authority |
| Optional integrations | `agents/integrations/` | In progress | Move trading, payout, social, airdrop, DeFi, and provider adapters |
| Persistence | Not yet grouped | Pending | Extract repositories without duplicating authorities |
| Application composition | `app/` | Started | Move startup, wiring, and shutdown out of `main.py` |
| GUI presentation | `gui/` | Partial | Split views, widgets, builders, services, and lifecycle |

### Target ownership model

```text
main.py
  -> app.bootstrap
      -> app.application
          -> app.runtime_wiring
              -> agents.runtime
              -> agents.providers
              -> agents.workers
              -> agents.cognition
              -> agents.earning
              -> agents.safety
              -> agents.integrations
              -> agents.persistence
          -> gui.views / gui.builders / gui.services
          -> app.shutdown
```

Ownership rules:

1. `main.py` starts the process only; it must not own domain orchestration.
2. `app/` composes services and owns application lifetime, not business policy.
3. `gui/` presents state and emits user intent; it must not become an authority
   for provider, evidence, accounting, lifecycle, or authorization decisions.
4. `agents/runtime/` owns loops, scheduling, role/device runtime, telemetry,
   and runtime coordination.
5. `agents/cognition/` owns inspectable cognition state, Dialogue records,
   prompt context, claims, and coordination traces; it does not authorize
   actions.
6. `agents/earning/` owns opportunity/task domain behavior and projections;
   lifecycle, evidence, accounting, and approval authorities remain singular.
7. `agents/safety/` owns authorization, human approval, trust, tool execution,
   filesystem, SQL, and instruction provenance controls.
8. `agents/integrations/` contains optional external adapters and must be
   lazy-importable without network calls or GUI blocking during startup.
9. `agents/persistence/` provides repositories and storage adapters but may
   not replace existing domain authorities.

### Planned package layout

```text
app/
  bootstrap.py                 # process and QApplication startup
  application.py               # application composition and lifetime
  runtime_wiring.py            # workers, providers, manager, summarizer
  shutdown.py                  # ordered, idempotent resource teardown
  environment.py               # guarded environment persistence

agents/
  runtime/
    manager_thread.py          # Qt-facing compatibility thread
    manager_loop.py            # Qt-independent work/heartbeat loop
    context.py                 # read-only runtime context
    dual_brain.py              # role/provider/device contract
  cognition/
    dialogue.py                # turn records and intent annotations
    prompting.py               # prompt assembly and budget policy
    communication.py           # event/message adapters
    memory.py                  # cognition-facing memory projections
  earning/
    opportunities.py            # canonical opportunity projections
    tasks.py                   # task adapters and execution inputs
    lifecycle.py                # lifecycle integration façade
    accounting.py               # accounting projections
  safety/
    calling.py                 # canonical model tool-calling path
    authorization.py           # single mutation authorization boundary
    approval.py                # human approval queue
  integrations/
    providers.py                # optional provider adapters
    trading.py                  # paper/live trading adapters
    wallet.py                   # wallet and crypto adapters
    web.py                      # web/search/browser adapters
    platforms.py                # platform clients
  persistence/
    repositories.py              # explicit storage adapters
    migrations.py                # schema/version management
  workers/
    worker_agent.py              # composed worker runtime
    provider_calls.py            # worker/provider bridge

gui/
  views/                        # thin Qt views
  widgets/                      # reusable widgets and panels
  builders/                     # tab and feature construction
  services/                     # GUI-facing service adapters
  lifecycle/                    # timers, workers, server/provider lifecycle
```

The layout is a target boundary, not permission to create duplicate modules.
Existing canonical modules should be moved or re-exported only after their
imports, patch points, and authority relationships are understood.

### Whole-program wiring migration

The following wiring must be audited and updated as each package moves:

| Current surface | Canonical destination | Required wiring checks |
|---|---|---|
| `main.py` startup | `app.bootstrap` | QApplication order, settings, DB, logging, environment |
| `main.py` service construction | `app.runtime_wiring` | Worker/provider/manager dependency injection |
| `main.py` shutdown | `app.shutdown` | Timers, servers, threads, DBs, providers, idempotency |
| `manager.py` loop | `agents.runtime.manager_loop` | Queue contracts, heartbeat, metrics, stop behavior |
| `manager.py` signals | `agents.runtime.manager_thread` | Qt signal names, payloads, thread affinity |
| `base_worker.py` provider path | `agents.providers`/`agents.runtime` | Model selection, fallback, throttling, circuit state |
| `earning_pipeline.py` | `agents.earning` | Legacy `Opportunity` API, lifecycle, evidence, accounting |
| `database.py` and memory stores | `agents.persistence` | Schema compatibility and authority ownership |
| `tab_builders.py` and `ui.py` | `gui.builders`/`gui.widgets` | Tab labels, signal wiring, lazy construction |
| `dual_brain_control.py` | `gui.services`/`agents.runtime` | Non-blocking probes and provider lifecycle |

### Migration gates

Every structural move must pass these gates before the next hub is changed:

1. The old import path still resolves when compatibility is required.
2. The new canonical import path resolves without importing optional network
   or GUI dependencies unnecessarily.
3. No new authority or duplicate state store is introduced.
4. Focused tests pass for the affected subsystem.
5. GUI construction remains non-blocking.
6. Shutdown remains idempotent and releases owned resources.
7. Import searches identify remaining legacy callers and patch points.

### Completion criteria

The whole-program restructuring is complete only when:

- `main.py`, `manager.py`, and `earning_pipeline.py` are thin composition or
  compatibility layers.
- Provider/model selection uses one canonical runtime contract.
- Each mutation has one authorization boundary.
- Evidence, lifecycle, accounting, cognition, and persistence authorities are
  unique and documented.
- Internal imports use canonical packages.
- Remaining façades have identified external callers or explicit deprecation
  coverage.
- No scratch or generated artifacts remain in source-controlled paths.
- Runtime, Dialogue, earning, safety, integration, GUI, provider, shutdown,
  and startup-responsiveness validation suites pass.

## Target program structure and migration plan

The remaining broad restructuring follows these ownership boundaries:

```text
app/
  bootstrap.py       # QApplication/process startup only
  application.py     # composition root and application lifetime
  runtime_wiring.py  # workers, providers, manager, summarizer, signals
  shutdown.py        # ordered, idempotent teardown

agents/
  runtime/           # loops, manager runtime, telemetry, dual-brain runtime
  cognition/         # Dialogue state, prompts, claims, ledgers, coordination
  earning/           # opportunities, tasks, validation, execution, accounting projections
  safety/            # tools, authorization, approvals, trust, filesystem, SQL policy
  integrations/      # optional platform, web, wallet, crypto, trading adapters
  persistence/       # repositories grouped by existing authority
  providers/         # provider adapters and normalized provider contracts
  workers/           # worker implementations and worker composition

gui/
  views/             # thin Qt views
  widgets/           # reusable presentation widgets
  builders/          # tab/view construction
  services/          # GUI-facing application service adapters
  lifecycle/         # timers, workers, provider/server lifecycle
```

Migration order:

1. Extract application bootstrap and runtime wiring from `main.py`.
2. Split the Qt-facing manager thread from its runtime loop and signal bridge.
3. Separate persistence repositories without duplicating lifecycle, evidence,
   accounting, cognition, or memory authorities.
4. Consolidate provider configuration around the canonical dual-brain/runtime
   contract and migrate provider/model-selection callers.
5. Split GUI composition and shared widgets from application services.
6. Migrate internal imports to canonical package paths while retaining only
   verified compatibility façades.
7. Remove unreachable compatibility bodies and audit legacy files.
8. Run import, boundary, runtime, Dialogue, provider, GUI, shutdown, and
   startup-responsiveness validation gates.

High-risk wiring surfaces requiring explicit regression coverage are
`main.py`, `manager.py`, `earning_pipeline.py`, `base_worker.py`,
`provider_manager.py`, `gui/tab_builders.py`, `gui/tab_feature_builders.py`,
`gui/dual_brain_control.py`, and `database.py`. Personal GitHub publishing
scripts are explicitly outside this migration plan.

The deterministic task execution engine now lives in
`agents/earning/executor.py`; `agents/task_executor.py` remains a
compatibility façade, and pipeline wiring uses the canonical earning package.

Task classification and specialization routing now live in
`agents/earning/router.py`; `agents/task_router.py` remains a compatibility
façade, and Big Brain uses the canonical earning route.

The deterministic capability taxonomy and registry now live in
`agents/earning/capabilities.py`; `agents/capability_registry.py` remains a
compatibility façade, and the capability validator uses the canonical package.

Reusable task specifications and deterministic requirement inference now live
in `agents/earning/spec.py`; `agents/task_spec.py` remains a compatibility
façade, and validator, executor, and autonomous-loop callers use the
canonical earning package.
