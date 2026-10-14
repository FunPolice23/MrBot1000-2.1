# MrBot1000 v2.1.99 — Multi-Brain AI-Powered Earning Agent

A real-time AI agent system for automated earning opportunity discovery, execution, and lifecycle tracking. It is local-first: the default brain runtime runs on your machine across every detected GPU and the CPU/RAM pool, while optional cloud providers are explicitly configured by the operator.

> **New here?** See [`docs/codemap/`](docs/codemap/README.md) for a full
> function-level map of every file, and [`docs/LEGACY_AUDIT.md`](docs/LEGACY_AUDIT.md)
> for the status of the retired central-Manager architecture.

## Highlights (through v2.1.99)

- **Device-centric N-brain runtime** (`agents/runtime/device_registry.py` + `agents/runtime/dual_brain.py`): one source of truth for device→slot→role→endpoint/model. The runtime detects every GPU and the CPU/RAM pool and assigns each an ordered slot — slot 0/1 are the classic Big/Small brains (back-compat), slots 2+ are extra devices (e.g. a CPU/RAM brain). Per-device enable/role/model/settings persist in `settings.json`. The active local or cloud provider is selected from Settings.
- **Shared-skills peer council Dialogue** (`agents/cognition/speaker_registry.py`): every enabled brain runs the same earning-agent skillset, differing only by a customizable per-device name (Edward Hurst, Jacob Stanley, Chris Borrows, …). Each brain independently reads the shared transcript — human + teammates + tool results — and decides whether to answer the human, react to a teammate, or push the goal. Names are editable in the Management tab (`BIG_BRAIN_NAME`/`SMALL_BRAIN_NAME`/`BRAIN_SLOT{n}_NAME`).
- **Graph-of-Thought branch expansion** (`agents/brains/brain_got.py`): when the reasoning pattern allows branching (tree/graph-of-thoughts), a turn expands into multiple candidate OPTION nodes, scored by deterministic evidence-backed support (`ThoughtGraph.rank_options`), with a scored DECISION selecting the winner. The per-turn graph is a public coordination trace — never private chain-of-thought — and the "Thoughts" view shows the ranking and the selected pattern.
- **Canonical cross-model collaboration** (`agents/cognition/coordinator.py`): deterministic plan→research→review→execute handoff on the EventBus with a durable MessageLog ledger; model_fn injected (mock-first, cycle-safe).
- **Durable autonomous runs** (`agents/services/autonomous_run_store.py`): SQLite run/stage/idempotency ledger with restart recovery; autonomous-loop results now survive restarts.
- **Unified composition root** (`agents/core/composition_root.py`): one shared pipeline/portfolio/run_store/lifecycle per process.
- **First real paper/human-gated earning capability** (`agents/earning/capability.py`): produces a real TaskWorkspace deliverable, validates it deterministically, stops on human gates, packages locally, and records submission evidence — never fabricates payment or success.
- **Cloud-failover control** (`CLOUD_FAILOVER_ENABLED`): a real toggle in Provider Configuration that gates whether cloud providers are used as a backup when the local brain fails. When off, only local providers are contacted; a provider whose Role is "Disabled" is never used regardless.
- **Dialogue and Management consolidation**: Dialogue now tracks goals, tasks,
  and progress; redundant Collaboration and Memory & Stream tabs are removed.
- **Web Browser tab = the agents' live browsing surface** (v2.1.84): a
  `QWebEngineView` renders each page the personas fetch with real page loading,
  driven by a GUI-thread-safe nav bus (`gui/widgets/web_nav_bus.py`). When a
  persona runs `web_read`/`web_search`, the URL loads here in real time and a
  timestamped activity log records every action; recent activity is replayed when
  the (lazy-built) tab is first opened. The agents' data still comes from
  `web_eyes` text extraction — the tab is the visual mirror.
- **Live tok/s telemetry** (v2.1.80-85): the Providers & GPU window shows live
  generation speed (tok/s, tokens, elapsed) per device during Dialogue and Chat,
  tracking total generation (thinking + answer). DB Stats reports avg tok/s,
  prompt/completion tokens, and DB size. MTP (multi-token prediction) is detected
  per model and greyed out when unsupported.
- **Robust tool chain + teardown** (v2.1.81-83): the agents' `web_search`/
  `web_read`/tool dispatch works end-to-end (fixed a handler-map import that
  broke every tool); narrated-but-never-executed "I need to verify" stalls are
  rejected; and DialogueWorker teardown aborts cleanly so a window close never
  crashes the app (the `Qt6Core 0xc0000409` class).
- **Custom brain names**: Big Brain and Small Brain display names can be edited
  and saved in Provider Configuration. Internal role keys remain stable.
- **Dialogue evidence visibility**: the personas retain their
  natural narrated reasoning, while dispatcher-confirmed tool calls appear as
  separate events with arguments, status, source, and a bounded result preview.
- **Conversational awareness**: persona prompts and the Dialogue context header
  instruct each brain to read what the human and teammates just said and react
  specifically — answer the human, engage a teammate's point, vary the opening,
  and hold a genuine opinion — instead of replaying a fixed script.
- **Opportunity-aware Dialogue**: scanned candidates from the Opportunities tab
  are supplied to all personas as read-only context, clearly separated from
  verified evidence, approval, and execution.
- **Graph-of-Thought observability**: inspectable goals, claims, options, checks,
  dependencies, support, and contradictions are recorded without storing private
  chain-of-thought. Support measurements guide the next check but never grant
  evidence status, approval, payment truth, or execution authority.
- **Human approval visibility**: Approvals is directly beside Dialogue, and a
  selected request stays highlighted while the queue refreshes. The detail view
  shows the complete read-only request, including structured arguments and
  payload data. When requests are pending, the tab label shows the count and
  changes to an amber alert color with a review tooltip; it clears after the
  human decides.
- **Explicit local model selection**: brain model fields are
  blank by default. The application never guesses a local `.gguf` filename or
  launches a nonexistent model; choose a real model and save it when a role
  should have a persistent default.
- **Per-brain settings + console timings**: every enabled device (incl. CPU/RAM)
  has editable context/gpu-layers/threads/batch/kv/split/temperature in Providers
  & GPU, persisted per device. Temperature no longer reverts after save, and
  llama-server runs with `--perf` so a visible console shows live token/timing
  stats.
- **Performance-aware freshness**: active GUI tabs use fast refresh intervals,
  while hidden operational tabs continue polling every 15 seconds so shared
  state remains current for the brains without keeping every view at full
  polling cost.

## Quick Start

For a concise deployment, recovery, approval, and emergency-stop workflow,
see [OPERATIONS.md](OPERATIONS.md). Before releasing changes, use the
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). For a full subsystem map,
dependency assessment, and consolidation plan, see
[ARCHITECTURE_MAP.md](ARCHITECTURE_MAP.md).

```bash
python main.py
```

### Local brain launchers

The canonical llama.cpp launchers are:

```powershell
.\scripts\launch_llamacpp_brain.ps1 -Role Big
.\scripts\launch_llamacpp_brain.ps1 -Role Small
.\scripts\start_big_brain_llamacpp.ps1
.\scripts\start_small_brain_llamacpp.ps1
```

The Ollama launcher is separate and explicitly named:

```powershell
.\scripts\start_small_brain_ollama.ps1
```

`start_small_brain_ollama.bat` is only a thin compatibility wrapper around
the PowerShell launcher. The personal GitHub publishing utilities are kept
outside the application scripts in the ignored `tools/github_publish/` folder.

Edward and Jacob share a persistent `ai_workshop` for proposals, research,
documents, scripts, applications, templates, notes, and deliverables. Set the
human-approved location before starting the application with
`MRBOT_WORKSHOP_ROOT` (or `AI_WORKSHOP_ROOT`). If the folder already exists it
is reused; otherwise MrBot creates the organized structure. The default quota
is 10 GiB and can be changed with `MRBOT_WORKSHOP_MAX_BYTES`.

To exercise the workflow without making real changes, run in safe mode:

```bash
python main.py -sm
# or
python main.py --safe-mode
```

This is equivalent to setting `MRBOT_SAFE_MODE=true` for the session.

### Optional capabilities

Trading, crypto operations, airdrop claiming, DeFi scanning, social
automation, self-improvement, and autonomous learning are disabled by default.
Open **Settings → Optional Features**, enable the capabilities you want, and
click **Save All Settings**. Feature-dependent tabs are added or removed after
the application restarts. The settings are persisted as `MRBOT_ENABLE_*`
values in `.env`; direct environment configuration remains supported for
headless runs. When enabled, **Social Activity**, **Self-Improvement**, and
**Autonomous Learning** provide read-only progress monitors backed by the
persisted event, learning-history, and autonomous-run stores.

Requires: Python 3.11+, the packages listed in `requirements.txt`, and either
the default local llama.cpp servers or another configured provider. The default
brain contract uses llama-server on ports 1234 and 1235; extra devices (CPU/RAM
or another GPU) get their own sequential port. Anthropic and
OpenAI are optional cloud integrations; install them only when those providers
are enabled:

```bash
python -m pip install -r requirements-cloud.txt
```

### Safe Mode

Safe mode validates actions and skips real file changes while the workflow is exercised. It can be enabled three ways:

```bash
python main.py -sm              # CLI flag (alias for MRBOT_SAFE_MODE=true)
# or
set MRBOT_SAFE_MODE=true        # Windows env var
export MRBOT_SAFE_MODE=true     # Linux/macOS env var
python main.py
```

Safe mode can also be toggled from the Management tab at runtime.

## What It Does

- Scans Reddit, Fiverr, Upwork, airdrop feeds, DeFi protocols, microtask platforms, and web-search targets across freelance marketplaces, AI-agent work, crypto/Web3 jobs, open-source/security bounties, user testing, and paid studies. Web-search findings remain human-review-only until separately approved for action.
- Evaluates and ranks opportunities using the configured Big Brain/Small Brain runtime **plus** a deterministic Opportunity Intelligence Engine (LLM scores feed it as semantic estimates only — never the sole decision-maker)
- Executes safe, repeatable actions with full validation through a 14-step Task Execution pipeline with deterministic validators + human gates
- Tracks opportunities through discovery → researched → applied → in_progress → submitted → paid/failed with explicit, auditable stage transitions
- Surfaces startup warnings and runtime issues so configuration gaps are visible early
- Supports a safe mode that validates actions and skips real file changes while the workflow is being exercised
- Shares research snapshots across the manager and chat-side runtime context so both models can benefit from the same knowledge base
- Supplies the Dialogue tab with read-only scanned opportunity candidates so the
  personas can inspect, compare, and propose work from the current opportunity
  queue
- Distinguishes narrated tool intent from actual dispatcher-confirmed tool calls;
  only real returned tool results count as evidence
- Tracks earnings and payouts locally in SQLite with **Unified Economic Accounting** (verified vs unverified revenue, LLM cost, gas, net profit, ROI, net hourly rate)
- Runs a self-audit engine that identifies improvement opportunities across 14 categories without mutating safety constraints
- Supports llama.cpp, Ollama, LM Studio, vLLM, KoboldCpp, and supported cloud providers through the Settings and Providers & GPU surfaces. The interface adapts to whichever enabled provider is active; if none is enabled, it reports that no provider is in use.
- Maintains per-brain conversation memory (via the Dialogue/N-device MemoryDatabase) that survives restarts
- Dynamically schedules discovery sources based on historical performance (exploration/exploitation balance)

### Live Portfolio and Trading

The **Live Portfolio** surface is separate from the **Strategy Simulator**. It
does not create a fictional starting balance: equity, free cash, and balances
come from the configured exchange. Live execution is disabled by default and
requires an explicitly enabled account, exchange credentials, current market
data, deterministic risk checks, and human approval for orders outside the
configured low-risk preapproval band.

Optional exchange support uses `ccxt`:

```bash
python -m pip install -r requirements-live.txt
```

The Live Portfolio exchange selector includes Coinbase, Kraken, Binance,
Gemini, Bitfinex, OKX, Bybit, KuCoin, Bitstamp, and Gate.io. The selector and
`TRADING_EXCHANGE` setting choose one exchange account at a time; CCXT is the
common adapter library, not a shared exchange or custodial network. Each
exchange uses its own API endpoint and credentials. Use withdrawal-disabled
API keys and keep
`MRBOT_LIVE_TRADING_ENABLED=false` until the account, limits, and approval flow
have been reviewed. The policy evaluates notional size, portfolio allocation,
daily loss, volatility, spread, liquidity, strategy confidence, expected
return, and asset class. Meme, unknown, or otherwise elevated-risk assets are
not eligible for silent execution.

The Strategy Simulator remains available for agent dry-runs and previews. Its
virtual capital is never portfolio equity, wallet balance, exchange balance, or
verified financial evidence.

## Current Workflow

### Dialogue Control and Evidence

Dialogue supports three operator modes:

- **Step** runs one persona turn.
- **Auto-Step** runs its bounded ten-turn pass.
- **Live** continues without an exchange limit until the operator stops it or
  both personas reach the same terminal block.

Persona narration remains visible so the operator can understand why a model is
proposing a search or action. When a tool actually executes, Dialogue adds a
separate dispatcher-confirmed event with the tool name, arguments, execution
status, source, and a bounded result preview. A narrated statement such as “I
will search” is never treated as proof that a search occurred.

After an Opportunities scan, Dialogue receives a read-only snapshot of stored
candidates. Candidate records help the personas select and research targets,
but do not prove that a listing is active, payable, approved, or completed.

If both personas converge on the same terminal condition, such as a missing
target, missing evidence, or required human approval, Live pauses and waits for
new human direction or new opportunity evidence. Semantic repetition is also
detected when the wording changes but the target or decision remains the same.
After repetition, Dialogue makes up to three bounded recovery attempts: one
permitted read-only inspection, a review of existing local evidence, or a
precise BLOCKED state. It pauses only after those recovery paths fail.

Mutating tool requests never execute directly from Dialogue. When one enters the
approval queue, the tool event is marked `pending_approval`, the active run
pauses, and the operator can open the adjacent Approvals tab to read the full
request before choosing Approve, Deny, or Defer.

The tab bar reserves this alert treatment for actionable queues with a clear
operator response. Other tabs remain neutral until they have an equivalent
pending state and decision workflow.

### Unified Autonomous Planning Loop (24 stages)

The system runs a unified 24-stage autonomous planning loop:

1. **Discover** — scan for opportunities from all configured sources
2. **Deduplicate** — cross-source dedup via normalized identity keys
3. **Classify** — assign canonical category + subcategory + task type
4. **Evaluate** — LLM scores + Opportunity Intelligence Engine verdict (expected value, confidence, skill fit, risk penalty, effort)
5. **Check Memory** — load past decisions, patterns, reputation priors
6. **Check Reputation** — platform win-rate, scam history
7. **Check Skill Fit** — required skills vs agent capabilities
8. **Check Economics** — expected value, net profit, ROI projection
9. **Check Risk** — scam probability, platform risk, financial exposure
10. **Prioritize** — rank by configurable queue policy (expected hourly, confidence, risk, skill fit, deadline urgency, effort, priority override)
11. **Plan** — generate structured execution plan (file, operation, platform, issue, rationale)
12. **Request Approval** — human gate check (identity, payments, contracts, irreversible actions, captchas, etc.)
13. **Execute** — real tool dispatch (file read/write, gig search, proposal generation, fulfillment)
14. **Validate** — deterministic validators (syntax, tests, requirements coverage, schema, formatting)
15. **Submit** — platform submission via validated clients (review gate + human confirm)
16. **Wait** — track external state (pending payment, review, etc.)
17. **Verify** — evidence-gated verification before marking paid (on-chain crypto, manual reference with independent reconciliation)
18. **Account** — Unified Economic Accounting (revenue = verified payment evidence only)
19. **Learn** — feed outcomes back into memory (search strategy outcomes, proposal A/B variants, learning loop with governor bounds)
20. **Re-rank** — update future opportunity prioritization based on learned results

## Running Tests

```bash
# Run all tests
python -m tests --all

# List available tests
python -m tests --list

# Run specific test
python -m tests --test check_syntax

# Run test category
python -m tests --category import
```

### Test Categories

| Category | Tests | Purpose |
|----------|-------|---------|
| `syntax` | `check_syntax` | Validate Python syntax across all files |
| `import` | `test_imports`, `test_httpx_dependency`, `test_analyst_worker`, `test_job_search`, `test_main` | Verify module imports work |
| `health` | `test_analyst_metrics`, `test_job_evaluation` | Check agent functionality |
| `security` | `test_instruction_gate`, `test_trust_boundary` | v2.0.22 instruction provenance + trust boundary |
| `section_c` | `test_section_c` | Platform safety & ToS (rate-limit, ramp, scraper resilience) |
| `section_d` | `test_section_d` | LLM quality & cost (proposal model role, A/B intros, cost-aware routing, circuit breaker) |
| `section_e` | `test_section_e` | GUI/perf — dense/MoE arch detection, per-role GPU offload, steady-stream, per-role memory |
| `evidence` | `test_evidence`, `test_evidence_integration`, `test_evidence_payout_path`, `test_evidence_audit_fixups`, `test_evidence_au` | v2.0.34au Evidence & Verification subsystem |
| `earning_memory` | `test_earning_memory`, `test_earning_memory_au` | v2.0.35 Earning/Opportunity Learning Memory (10 memory types) |
| `learning_loop` | `test_learning_loop` | v2.0.36d Opportunity Learning Loop (prediction accuracy, recency, 11 metrics, governor bounds) |
| `task_capabilities` | `test_task_capabilities` | v2.0.36e Skill/Task capability framework |
| `discovery_scheduler` | `test_discovery_scheduler` | v2.0.36f Dynamic Discovery Scheduler (history-driven, exploration/exploitation) |
| `search_strategy_memory` | `test_search_strategy_memory` | v2.0.36g Search Strategy Memory (economic outcomes, usefulness optimization) |
| `opportunity_portfolio` | `test_opportunity_portfolio` | v2.0.36h Opportunity Portfolio & Work Queue (16-state WorkStatus, capacity gates) |
| `task_execution` | `test_task_execution` | v2.0.36i Generalized Task Execution (14-step pipeline, validators, human gates) |
| `economic_accounting` | `test_economic_accounting` | v2.0.36j Unified Economic Accounting (verified/unverified, USD+crypto, ROI) |
| `autonomous_loop` | `test_autonomous_loop` | v2.0.36k Unified Autonomous Planning Loop (24-stage, provenance, truth-status) |
| `self_audit` | `test_self_audit` | v2.0.36j-T4 Self-Audit Engine (14 finding categories, no security mutations) |
| `discovery` | `test_opportunity_discovery` | v2.0.34as Generalized paid-opportunity discovery (structured model, sources, dedup, validation) |
| `intelligence` | `test_opportunity_intelligence` | v2.0.34at Opportunity Intelligence Engine (24-factor expected-value model) |
| `nvidia` | `test_nvidia_nim` | v2.0.36 NVIDIA NIM support |

Test results are saved to `tests/test_results/test_run_YYYYMMDD_HHMMSS.json`.

## Architecture

For the detailed file-level architecture map, complexity assessment, and
recommended trim sequence, see [ARCHITECTURE_MAP.md](ARCHITECTURE_MAP.md).

- **Big Brain / Edward Hurst**: uses the active provider and available primary GPU — planning, coding, deep research, and review
- **Small Brain / Jacob Stanley**: uses the active provider, a second GPU, CPU/system RAM, or can be disabled — human chat, triage, and lightweight coordination
- **Provider selection**: llama.cpp, Ollama, LM Studio, vLLM, KoboldCpp, and cloud providers are selected explicitly from Settings; provider-specific controls appear only for the active backend
- **Two-persona model runtime**: Edward Hurst (Driver/Big Brain) plans and pushes work forward; Jacob Stanley (Navigator/Small Brain) handles chat, triage, risk checks, and verification
- **Application services**: Management coordinates earning workflows, approvals, payouts, memory, and operational controls; specialized workers handle discovery, analysis, coding, and platform tasks
- **Message routing**: Chat and Dialogue use the configured brain adapters; task and command intents are routed through the Manager and deterministic service boundaries
- **Cross-model communication**: EventBus typed handoffs plus the durable collaboration/message ledger
- **Opportunity lifecycle tracking**: Explicit, auditable stage transitions for discovered, researched, applied, in progress, submitted, paid, and failed opportunities
- **Enforced lifecycle state machine** (v2.1.57): the allowed-transition table is authoritative — a rejected transition is audited (`transition_ok=False`, `last_transition_error`) but never moves the stage or commits `status`; every `paid` flip is routed through `_mark_paid`; terminal stages have no successors, so a `failed` or already-settled opportunity cannot be promoted to `paid`; the crypto/airdrop route uses an explicit `claimed` stage
- **Startup validation**: Checks configuration, provider availability, and safe-mode status before workflows begin
- **Secure execution**: 14-step action pipeline with validation + human gates
- **Instruction provenance gate** (v2.0.22): any external `SKILL.md`/playbook is untrusted data until human-approved; quarantined in a Review Queue
- **Evidence & Verification subsystem** (v2.0.34au): domain-scoped evidence types, EvidenceStore, verification policy (L1 self-reported → L2 platform API → L3 on-chain/crypto → L4 independent audit), reconciliation gates lifecycle transitions
- **Canonical payment evidence vocabulary**: broad monetary observations remain available to accounting, while a strict L3+ transition subset gates lifecycle payment truth; legacy producer labels remain recognized
- **Fail-closed verification** (v2.1.57): a lifecycle/DB error during paid-verification is recorded as NOT verified rather than as a payout, and independent reconciliation (`evidence_policy.reconcile`) escalates only for an explicit allow-list of externally-produced methods — an unknown or manual method is refused, never granted VERIFIED@L4
- **Merge-only settings writes** (v2.1.57): every writer to `settings.json` goes through `device_registry.merge_settings_file` / `save_policy`, which merge-read outside the write try, quarantine an unparseable file, and write atomically — no writer may replace the whole file and destroy the per-device `devices` block
- **Unified Economic Accounting** (v2.0.36j): revenue only from externally verified payment evidence; USD + crypto conversion; expenses by category; verified/unverified split; ROI; net hourly rate; prediction accuracy tracking
- **Read-only state reconciliation**: compares lifecycle, portfolio, evidence, accounting, and durable runs without automatic repair; conflicts are surfaced for human review
- **Runtime Diagnostics tab**: exposes sanitized Big Brain/Small Brain health and current reconciliation conflicts without secrets or evidence payloads
- **Adaptive Small Brain fallback**: if the configured secondary GPU is unavailable, the local Small Brain uses CPU/system RAM with the user-selected or configured model (larger models are allowed but may be slower) and operates as concise decision support for the Big Brain
- **SQLite lifecycle hardening**: persistent AgentDB connections and short-lived run-store connections have explicit close semantics for Windows-safe shutdown and warning-free tests
- **Self-Audit Engine** (v2.0.36j-T4): 14 audit categories, structured findings with confidence + expected benefit/risk, no security mutations
- **Dynamic Discovery Scheduler** (v2.0.36f): history-driven source/category/strategy selection, exploration/exploitation balance, backoff, provenance tagging
- **Opportunity Portfolio** (v2.0.36h): 16-state WorkStatus, persistent sqlite-backed queue, configurable QueuePolicy + CapacityConfig overcommit gates, lifecycle-authoritative transitions
- **Per-brain conversation memory**: the Dialogue/N-device `MemoryDatabase` persists conversation turns across restarts (the legacy chat/CEO `SummarizerDB` role-memory was removed with the Manager/Summarizer cleanup)
- **Submission ramp** (v2.0.34aq): win-rate-gated auto-submission that only unlocks after sufficient verified submissions; cold-start safe
- **Proposal A/B templates** (v2.0.34v): rotated intro variants that learn from outcomes
- **Win-rate guard** (v2.0.34aq): auto-decline platforms below configured success threshold; cold-start safe
- **Cost guard** (v2.0.34y): daily LLM budget cap that skips billable providers when exceeded

## Repository Structure

```
main.py                  Launcher (entry point) — stays at the repo root
app/                     Application layer: database, manager, ui, earning_pipeline,
                         earning_memory, library, provider_models, theme_config, ...
agents/                  Agent layer, grouped by domain:
  brains/                big_brain, small_brain, base_worker, worker_* mixins, brain_got (GoT)
  dialogue/              discussion, conversation_memory, chat_router, chat_completion
  cognition/             personas, speaker_registry, fact_ledger, contradictions,
                         memory_promotion, coordinator, graph, reasoning_modes
  earning/               pipeline steps, opportunity_*, task_executor, capability, economic_*
  evidence/              evidence, evidence_store, provenance, verification
  discovery/             discovery engine, scheduler, sources, port
  knowledge/             proposal_*, program_knowledge, help_catalog, prompting
  core/                  comms, event_logger, alerting, composition_root, persistence, ...
  services/              autonomous_loop, self_audit, workshop, code_patch, ...
  autonomy/ integrations/ polish/   autonomous-loop, external integrations, output polish
  safety/                instructions (gate), trust (boundary), guard, tool safety
  runtime/               dual_brain, device_registry, services registry
  providers/             anthropic, ollama, openai_compatible, context_table
  platforms/             human-gated PlatformAdapter skeleton (fiverr/upwork/github/...)
gui/                     Desktop UI, grouped:
  tabs/ builders/ widgets/ workers/ panels/
tests/                   Grouped by domain:
  dialogue/ earning/ evidence/ safety/ runtime/ gui/ providers/ sections/ cognition/ tools/
tools/ skills/ scripts/  Supporting assets (publish tooling, skill docs, ops scripts)
```

Every package directory carries an `__init__.py`. Modules are imported by their full
dotted path (e.g. `from agents.earning.task_executor import ...`); the old flat
`agents/*.py`, `gui/*.py` and root-module import paths no longer exist.

> **Full per-file codebase map:** see [`docs/codemap/`](docs/codemap/README.md) — an
> index of every tracked file (525 files / 490 Python modules) with a one-line purpose
> and its key classes/functions, split by folder. It is the single source of truth for
> "what is this file" and should be updated as files change.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Application entry point, window setup, lazy tab loading, settings, and version display |
| `agents/runtime/dual_brain.py` | Canonical brain provider, endpoint, device, slot, and model configuration |
| `agents/runtime/device_registry.py` | Device-centric detection + slot assignment (GPU + CPU/RAM pool), per-device policy |
| `agents/cognition/speaker_registry.py` | N-brain speaker roster, per-device names, team brief, ping-pong order |
| `agents/brains/brain_got.py` | Per-turn Graph-of-Thought: branch expansion, evidence-backed scoring, decision |
| `agents/cognition/coordinator.py` | Typed plan → research → review → execute collaboration handoff and run ledger |
| `agents/cognition/personas.py` | Edward Hurst and Jacob Stanley persona contracts and guardrails |
| `agents/brains/base_worker.py` | Shared worker behavior, provider calls, secure file I/O, and research utilities |
| `agents/core/composition_root.py` | Shared process-level pipeline, portfolio, lifecycle, and run-store wiring |
| `agents/earning/payment_evidence.py` | Canonical monetary evidence vocabulary and strict transition subset |
| `agents/core/state_reconciliation.py` | Read-only cross-store contradiction report |
| `app/earning_pipeline.py` | Opportunity discovery, evaluation, filtering, execution, accounting, and audit integration |
| `agents/services/autonomous_loop.py` | Unified 24-stage opportunity planning loop |
| `agents/services/task_executor.py` | Deterministic task execution pipeline with validators and human gates |
| `agents/earning/opportunity_portfolio.py` | Persistent opportunity work queue and capacity controls |
| `agents/earning/opportunity_lifecycle.py` | Evidence-gated opportunity state transitions |
| `agents/earning/economic_accounting.py` | Verified revenue, costs, ROI, and net-hourly accounting |
| `agents/evidence/evidence_store.py` | Evidence storage, verification, reconciliation, and payout truth status |
| `agents/discovery/discovery_scheduler.py` | History-driven source/category/strategy scheduling |
| `agents/services/self_audit.py` | Structured operational findings without security-policy mutation |
| `agents/safety/instructions.py` / `agents/safety/trust.py` | Untrusted-instruction provenance and high-trust action boundaries |
| `gui/builders/tab_builders.py` | Current visible tab construction, lazy-loading orchestration, and Diagnostics view |
| `gui/tabs/dialogue_tab.py` | Goal-driven Edward/Jacob Dialogue, opportunity context, bounded recovery, terminal control, and verified tool-event display |
| `gui/panels/approval_panel.py` | Human approval queue with persistent selection and full request inspection |
| `gui/tabs/management_tab.py` | Operational controls, earning workflows, approvals, payouts, memory, and stream health |
| `gui/widgets/provider_config_widget.py` | Local/cloud provider configuration and role assignment |
| `gui/tabs/model_library_tab.py` | Local model discovery and managed downloads |
| `app/action_pipeline.py` | Proposal validation and controlled execution safeguards |
| `app/database.py` | SQLite persistence for actions, thoughts, evidence, LLM stats, and runtime state |
| `app/theme_config.py` / `ui.py` | Theme presets, custom theme values, widget styling, and optional effects |
| `app/version.py` | Public application version source (`2.1.99`) |
| `Agent.md` / `README.md` / `CHANGELOG.md` | Runtime contract, current system overview, and release history |
| `tests/` | Focused regression and subsystem tests |
| `tools/github_publish/` | Personal publish-mirror tooling (git-ignored; syncs a sanitized copy to GitHub) |

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Key settings:
- `BIG_BRAIN_PROVIDER`, `BIG_BRAIN_URL`, `BIG_BRAIN_PORT` — Big Brain (slot 0) provider and endpoint (default llama-server on 1234)
- `SMALL_BRAIN_PROVIDER`, `SMALL_BRAIN_URL`, `SMALL_BRAIN_PORT` — Small Brain (slot 1) provider and endpoint (default llama-server on 1235)
- `BIG_BRAIN_DEVICE` / `SMALL_BRAIN_DEVICE` — GPU device assignment for the two local brains
- `BIG_BRAIN_MODEL` / `SMALL_BRAIN_MODEL` — optional explicit local model paths
  or provider model IDs; blank means no model is selected and no local launch is
  attempted
- `BIG_BRAIN_NAME` / `SMALL_BRAIN_NAME` / `BRAIN_SLOT{n}_NAME` — per-device display names (slot 2+ uses `BRAIN_SLOT{n}_NAME`); editable in the Management tab
- `BIG_BRAIN_ENABLED` / `SMALL_BRAIN_ENABLED` — per-brain enable/disable (persisted by Providers & GPU)
- `BIG_BRAIN_SHOW_PERF` / `SMALL_BRAIN_SHOW_PERF` — pass `--perf` so a visible console shows token/timing stats (default true)
- `SHOW_BRAIN_CONSOLES` — show the per-brain llama-server console window
- `CLOUD_FAILOVER_ENABLED` — when 1, cloud providers are a backup if local fails; when 0, local-only
- Extra devices (CPU/RAM or another GPU) are managed in Providers & GPU → per-device rows; their enable/role/model/settings persist in `settings.json`, not `.env`
- `SMALL_BRAIN_CPU_MODEL` — optional preferred model path/ID selected for CPU fallback when no secondary GPU is detected; any model is allowed
- `SMALL_BRAIN_GPU_LAYERS=0` — optional CPU/system-RAM mode for the Small Brain when a second GPU is unavailable
- `BIG_BRAIN_CONTEXT` / `SMALL_BRAIN_CONTEXT` — per-role context limits
- `OLLAMA_MAIN_MODEL` / `OLLAMA_CHAT_MODEL` — optional Ollama fallback model names
- `OPENAI_STREAM_TIMEOUT_SECONDS` — bounded streaming timeout for OpenAI-compatible providers
- `DIALOGUE_HISTORY_LIMIT`, `DIALOGUE_CONTEXT_CHAR_LIMIT`, `DIALOGUE_TURN_MAX_TOKENS` — Dialogue resource limits
- SQLite local stores use bounded lock waits and WAL mode for better concurrent
  GUI/backend access; keep databases on a local writable filesystem
- `PIPELINE_ALLOW_SELF_IMPROVE` — Enable/disable auto code updates
- `LLM_DAILY_BUDGET_USD` — Daily cloud-LLM spend cap (0 = off)
- `WINRATE_DECLINE_BELOW` — Auto-decline platform if win-rate below this %
- `MEMORY_ENABLED` — Per-brain conversation memory (Dialogue/N-device MemoryDatabase)
- `THINKING_ENABLED` — Thinking/reasoning block for supported models
- `ALLOW_WEB_DISCOVERY` — Enable web search discovery (human-review gated)
- Per-provider: `<PROVIDER>_API_KEY`, `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODEL`, `<PROVIDER>_MAIN_ENABLED`, `<PROVIDER>_CHAT_ENABLED`

## UI Tabs

1. **Management** — Agent controls, pause/resume, pipeline controls, gig proposals, payout verification
2. **Providers & GPU** — Active-provider routing, N-brain orchestration (one row per detected device), detected hardware, and provider-specific controls
3. **Model Library** — Local model discovery and download management
4. **Safety & Tools** — Tool registry, safety rules, and approval queue
5. **Chat** — Human conversation with the configured Small Brain
6. **Dialogue** — Goal-driven Edward/Jacob conversation with Goals, Tasks, and Progress tracking
7. **Approvals** — Human approval queue beside Dialogue, with full request inspection
8. **Web Browser** — Live view of the agents' web browsing (real page loading via `QWebEngineView`); also accepts a manual URL
9. **Payments** — Balance and payout verification
10. **Earnings** — Income tracking, verified revenue, costs, gas, net profit, ROI
11. **Insights** — Reports and operational summaries
12. **Opportunities** — Opportunity portfolio and work queue
13. **Live Portfolio** — Live trading portfolio
14. **Strategy Simulator** — Risk-contained paper-trading strategy simulation
15. **Analytics** — Performance and economic analytics
16. **Reputation** — Platform and opportunity reputation data
17. **Data Explorer** — Local database and evidence exploration
18. **Settings** — Provider configuration, model settings, themes, and effect toggles
19. **Live Logs** — Debug output with severity filtering
20. **DB Stats** — Database metrics, recent actions, LLM call history, and instruction review queue

Memory and stream-health controls are integrated into **Management**. The
Collaboration coordinator remains a backend capability used by the runtime, but
it is not a separate visible tab.

## Runtime Roles

| Role | Identity | Responsibility |
|------|----------|----------------|
| Big Brain | Edward Hurst, Driver | Planning, opportunity sizing, coding, deep research, negotiation, and review |
| Small Brain | Jacob Stanley, Navigator | Human chat, triage, risk assessment, source verification, and detail checking |
| Specialized workers | Discovery, analysis, coding, platform, and accounting services | Perform bounded tasks through validated tools and human-gated execution |

> **Legacy removed (v2.1.77):** the old central "CEO Manager" (`ManagerThread`) +
> `SummarizerThread` + their worker-dispatch loop have been **fully removed**. The
> N-device peer council in Dialogue + the Chat tab are the decision/chat authority;
> `EarningPipeline`/`AutonomousLoop` drive earning. See
> [`docs/LEGACY_AUDIT.md`](docs/LEGACY_AUDIT.md) for the full removal record.

## Security

- Path traversal prevention (`Path.is_relative_to()`)
- Clipboard validation (10KB limit, domain blocklist)
- Payout limits ($10K max, triple confirmation)
- Credentials in `.env` only, never hardcoded
- Crash logs in user directory
- Protected source files — Coder cannot overwrite import-critical app files
- Evidence-gated payouts — revenue only from VERIFIED payment evidence
- Human gates — hard stops for identity verification, payments, contracts, signatures, captchas, irreversible actions
- Instruction provenance gate — external SKILL.md/playbooks quarantined until human-approved

## Documentation

- **Agent.md** — Runtime contract for any model interacting with the system
- **README.md** (this file) — Current system overview, tab inventory, and configuration guide
- **CHANGELOG.md** — Full change history (current release v2.1.99)
- **docs/codemap/** — Full function-level codebase map (every file, every function)
- **docs/LEGACY_AUDIT.md** — Status of the retired central-Manager / worker-team architecture
- **ARCHITECTURE_MAP.md** — Subsystem map, dependency assessment, consolidation plan

## Requirements

- Python packages from `requirements.txt`:
  - PySide6 for the desktop UI
  - ollama for local LLM integration
  - python-dotenv for .env-based configuration
  - requests for HTTP/network access
  - httpx for async HTTP (evaluation pipeline)
  - Optional cloud-provider SDKs: install `requirements-cloud.txt` for Anthropic/OpenAI
  - feedparser and beautifulsoup4 for feed and HTML-based discovery
  - PyYAML for theme/config
  - sqlite3 (stdlib) for local databases
- **Hardware: runs on ANY setup** — from low-VRAM machines (e.g. 6GB VRAM + Zen3 + DDR4) up to modern RTX with more RAM. Model size is operator-chosen; the app works with whatever Ollama serves. A GPU helps speed but is not required.
- RAM: 16GB minimum, 32GB recommended
- Storage: 5GB+ for models and databases
- Local endpoints and controls come from the enabled provider in Settings; llama.cpp uses the role ports by default, while Ollama, LM Studio, vLLM, and KoboldCpp use their configured endpoints
