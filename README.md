# MrBot1000 v2.1.1 — Dual-Brain AI-Powered Earning Agent

A real-time AI agent system for automated earning opportunity discovery, execution, and lifecycle tracking. It is local-first: the default dual-brain runtime runs on your machine, while optional cloud providers are explicitly configured by the operator.

## v2.1.1 Highlights (2026-09-11)

- **Canonical dual-brain runtime** (`agents/dual_brain_runtime.py`): one source of truth for role→endpoint/model/device. Big Brain → RTX 5060 Ti (CUDA 0, port 1234); Small Brain → GTX 1660 Super (CUDA 1, port 1235). llama.cpp/llama-server default; Ollama/LM Studio are explicit opt-ins.
- **Canonical cross-model collaboration** (`agents/dual_brain_coordinator.py`): deterministic plan→research→review→execute handoff on the EventBus with a durable MessageLog ledger; model_fn injected (mock-first, cycle-safe).
- **Durable autonomous runs** (`agents/autonomous_run_store.py`): SQLite run/stage/idempotency ledger with restart recovery; autonomous-loop results now survive restarts.
- **Unified composition root** (`agents/composition_root.py`): one shared pipeline/portfolio/run_store/lifecycle per process.
- **First real paper/human-gated earning capability** (`agents/earning_capability.py`): produces a real TaskWorkspace deliverable, validates it deterministically, stops on human gates, packages locally, and records submission evidence — never fabricates payment or success.
- **Dialogue and Management consolidation**: Dialogue now tracks goals, tasks,
  and progress; redundant Collaboration and Memory & Stream tabs are removed.

## Quick Start

```bash
python main.py
```

To exercise the workflow without making real changes, run in safe mode:

```bash
python main.py -sm
# or
python main.py --safe-mode
```

This is equivalent to setting `MRBOT_SAFE_MODE=true` for the session.

Requires: Python 3.11+, the packages listed in `requirements.txt`, and either
the default local llama.cpp servers or another configured provider. The default
dual-brain contract uses llama-server on ports 1234 and 1235.

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

- Scans Reddit, Fiverr, Upwork, airdrop feeds, DeFi protocols, microtask platforms, and web search for earning opportunities
- Evaluates and ranks opportunities using the configured Big Brain/Small Brain runtime **plus** a deterministic Opportunity Intelligence Engine (LLM scores feed it as semantic estimates only — never the sole decision-maker)
- Executes safe, repeatable actions with full validation through a 14-step Task Execution pipeline with deterministic validators + human gates
- Tracks opportunities through discovery → researched → applied → in_progress → submitted → paid/failed with explicit, auditable stage transitions
- Surfaces startup warnings and runtime issues so configuration gaps are visible early
- Supports a safe mode that validates actions and skips real file changes while the workflow is being exercised
- Shares research snapshots across the manager and chat-side runtime context so both models can benefit from the same knowledge base
- Tracks earnings and payouts locally in SQLite with **Unified Economic Accounting** (verified vs unverified revenue, LLM cost, gas, net profit, ROI, net hourly rate)
- Runs a self-audit engine that identifies improvement opportunities across 14 categories without mutating safety constraints
- Supports the local llama.cpp dual-brain runtime by default, with optional Ollama, OpenAI, Anthropic, OpenRouter, Gemini, Groq, DeepSeek, Mistral, Together, NVIDIA NIM, vLLM, LM Studio, and KoboldCpp providers through the Settings and Providers & GPU surfaces
- Maintains per-role memory (chat + CEO) that survives restarts
- Dynamically schedules discovery sources based on historical performance (exploration/exploitation balance)

## Current Workflow

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

- **Big Brain / Marcus Rivera**: llama-server on port 1234, normally GPU device 0 — planning, coding, deep research, and review
- **Small Brain / Alex Vega**: llama-server on port 1235, normally GPU device 1 — human chat, triage, and lightweight coordination
- **Optional providers**: Ollama, LM Studio, vLLM, and supported cloud providers can be selected explicitly; they are not silent defaults
- **Two-persona model runtime**: Marcus Rivera (Driver/Big Brain) plans and pushes work forward; Alex Vega (Navigator/Small Brain) handles chat, triage, risk checks, and verification
- **Application services**: Management coordinates earning workflows, approvals, payouts, memory, and operational controls; specialized workers handle discovery, analysis, coding, and platform tasks
- **Message routing**: Chat and Dialogue use the configured brain adapters; task and command intents are routed through the Manager and deterministic service boundaries
- **Cross-model communication**: EventBus typed handoffs plus the durable collaboration/message ledger
- **Opportunity lifecycle tracking**: Explicit, auditable stage transitions for discovered, researched, applied, in progress, submitted, paid, and failed opportunities
- **Startup validation**: Checks configuration, provider availability, and safe-mode status before workflows begin
- **Secure execution**: 14-step action pipeline with validation + human gates
- **Instruction provenance gate** (v2.0.22): any external `SKILL.md`/playbook is untrusted data until human-approved; quarantined in a Review Queue
- **Evidence & Verification subsystem** (v2.0.34au): domain-scoped evidence types, EvidenceStore, verification policy (L1 self-reported → L2 platform API → L3 on-chain/crypto → L4 independent audit), reconciliation gates lifecycle transitions
- **Unified Economic Accounting** (v2.0.36j): revenue only from VERIFIED payment evidence; USD + crypto conversion; expenses by category; verified/unverified split; ROI; net hourly rate; prediction accuracy tracking
- **Self-Audit Engine** (v2.0.36j-T4): 14 audit categories, structured findings with confidence + expected benefit/risk, no security mutations
- **Dynamic Discovery Scheduler** (v2.0.36f): history-driven source/category/strategy selection, exploration/exploitation balance, backoff, provenance tagging
- **Opportunity Portfolio** (v2.0.36h): 16-state WorkStatus, persistent sqlite-backed queue, configurable QueuePolicy + CapacityConfig overcommit gates, lifecycle-authoritative transitions
- **Per-role memory** (v2.0.34ad): chat + CEO memory stores that persist across restarts, with compact-on-write to stay bounded
- **Submission ramp** (v2.0.34aq): win-rate-gated auto-submission that only unlocks after sufficient verified submissions; cold-start safe
- **Proposal A/B templates** (v2.0.34v): rotated intro variants that learn from outcomes
- **Win-rate guard** (v2.0.34aq): auto-decline platforms below configured success threshold; cold-start safe
- **Cost guard** (v2.0.34y): daily LLM budget cap that skips billable providers when exceeded

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Application entry point, window setup, lazy tab loading, settings, and version display |
| `manager.py` | Manager orchestration, intent routing, heartbeat, approvals, memory, and service coordination |
| `agents/dual_brain_runtime.py` | Canonical Big Brain/Small Brain provider, endpoint, device, and model configuration |
| `agents/dual_brain_coordinator.py` | Typed plan → research → review → execute collaboration handoff and run ledger |
| `agents/personas.py` | Marcus Rivera and Alex Vega persona contracts and guardrails |
| `agents/base_worker.py` | Shared worker behavior, provider calls, secure file I/O, and research utilities |
| `agents/composition_root.py` | Shared process-level pipeline, portfolio, lifecycle, and run-store wiring |
| `earning_pipeline.py` | Opportunity discovery, evaluation, filtering, execution, accounting, and audit integration |
| `agents/autonomous_loop.py` | Unified 24-stage opportunity planning loop |
| `agents/task_executor.py` | Deterministic task execution pipeline with validators and human gates |
| `agents/opportunity_portfolio.py` | Persistent opportunity work queue and capacity controls |
| `agents/opportunity_lifecycle.py` | Evidence-gated opportunity state transitions |
| `agents/economic_accounting.py` | Verified revenue, costs, ROI, and net-hourly accounting |
| `agents/evidence_store.py` | Evidence storage, verification, reconciliation, and payout truth status |
| `agents/discovery_scheduler.py` | History-driven source/category/strategy scheduling |
| `agents/self_audit.py` | Structured operational findings without security-policy mutation |
| `agents/instruction_gate.py` / `agents/trust_boundary.py` | Untrusted-instruction provenance and high-trust action boundaries |
| `gui/tab_builders.py` | Current visible tab construction and lazy-loading orchestration |
| `gui/dialogue_tab.py` | Goal-driven Marcus/Alex Dialogue with bounded history and progress tracking |
| `gui/management_tab.py` | Operational controls, earning workflows, approvals, payouts, memory, and stream health |
| `gui/provider_config_widget.py` | Local/cloud provider configuration and role assignment |
| `gui/model_library_tab.py` | Local model discovery and managed downloads |
| `action_pipeline.py` | Proposal validation and controlled execution safeguards |
| `database.py` | SQLite persistence for actions, thoughts, evidence, LLM stats, and runtime state |
| `theme_config.py` / `ui.py` | Theme presets, custom theme values, widget styling, and optional effects |
| `version.py` | Public application version source (`2.1.1`) |
| `Agent.md` / `ARCHITECTURE.md` / `CHANGELOG.md` | Runtime contract, system design, and release history |
| `tests/` | Focused regression and subsystem tests |

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Key settings:
- `BIG_BRAIN_PROVIDER`, `BIG_BRAIN_URL`, `BIG_BRAIN_PORT` — Big Brain provider and endpoint (default llama-server on 1234)
- `SMALL_BRAIN_PROVIDER`, `SMALL_BRAIN_URL`, `SMALL_BRAIN_PORT` — Small Brain provider and endpoint (default llama-server on 1235)
- `BIG_BRAIN_DEVICE` / `SMALL_BRAIN_DEVICE` — GPU device assignment for the two local brains
- `BIG_BRAIN_CONTEXT` / `SMALL_BRAIN_CONTEXT` — per-role context limits
- `OLLAMA_MAIN_MODEL` / `OLLAMA_CHAT_MODEL` — optional Ollama fallback model names
- `OPENAI_STREAM_TIMEOUT_SECONDS` — bounded streaming timeout for OpenAI-compatible providers
- `DIALOGUE_HISTORY_LIMIT`, `DIALOGUE_CONTEXT_CHAR_LIMIT`, `DIALOGUE_TURN_MAX_TOKENS` — Dialogue resource limits
- `PIPELINE_ALLOW_SELF_IMPROVE` — Enable/disable auto code updates
- `LLM_DAILY_BUDGET_USD` — Daily cloud-LLM spend cap (0 = off)
- `WINRATE_DECLINE_BELOW` — Auto-decline platform if win-rate below this %
- `MEMORY_ENABLED` — Per-role memory (chat + CEO)
- `THINKING_ENABLED` — Thinking/reasoning block for supported models
- `ALLOW_WEB_DISCOVERY` — Enable web search discovery (human-review gated)
- Per-provider: `<PROVIDER>_API_KEY`, `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODEL`, `<PROVIDER>_MAIN_ENABLED`, `<PROVIDER>_CHAT_ENABLED`

## UI Tabs

1. **Management** — Agent controls, pause/resume, pipeline controls, gig proposals, payout verification
2. **Providers & GPU** — Dual-brain orchestration, llama-server controls, GPU isolation, model selection, context, threads, and GPU layers
3. **Model Library** — Local model discovery and download management
4. **Safety & Tools** — Tool registry, safety rules, and approval queue
5. **Chat** — Human conversation with the configured Small Brain
6. **Dialogue** — Goal-driven Marcus/Alex conversation with Goals, Tasks, and Progress tracking
7. **Browse Root** — File explorer
8. **Payments** — Balance and payout verification
9. **Earnings** — Income tracking, verified revenue, costs, gas, net profit, ROI
10. **Insights** — Reports and operational summaries
11. **Approvals** — Human approval queue
12. **Opportunities** — Opportunity portfolio and work queue
13. **Paper Trading** — Risk-contained trading simulation tools
14. **Analytics** — Performance and economic analytics
15. **Reputation** — Platform and opportunity reputation data
16. **Data Explorer** — Local database and evidence exploration
17. **Settings** — Provider configuration, model settings, themes, and effect toggles
18. **Live Logs** — Debug output with severity filtering
19. **DB Stats** — Database metrics, recent actions, LLM call history, and instruction review queue

Memory and stream-health controls are integrated into **Management**. The
Collaboration coordinator remains a backend capability used by the runtime, but
it is not a separate visible tab.

## Runtime Roles

| Role | Identity | Responsibility |
|------|----------|----------------|
| Big Brain | Marcus Rivera, Driver | Planning, opportunity sizing, coding, deep research, negotiation, and review |
| Small Brain | Alex Vega, Navigator | Human chat, triage, risk assessment, source verification, and detail checking |
| Manager services | Deterministic application layer | Routes intents, coordinates workers, enforces approvals, persists state, and runs heartbeat workflows |
| Specialized workers | Discovery, analysis, coding, platform, and accounting services | Perform bounded tasks through validated tools and human-gated execution |

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
- **ARCHITECTURE.md** — Full system design and component reference
- **CHANGELOG.md** — Full change history through v2.0.36m

## Requirements

- Python packages from `requirements.txt`:
  - PySide6 for the desktop UI
  - ollama for local LLM integration
  - python-dotenv for .env-based configuration
  - requests for HTTP/network access
  - httpx for async HTTP (evaluation pipeline)
  - anthropic and openai for optional cloud-provider integrations
  - feedparser and beautifulsoup4 for feed and HTML-based discovery
  - PyYAML for theme/config
  - sqlite3 (stdlib) for local databases
- **Hardware: runs on ANY setup** — from low-VRAM machines (e.g. 6GB VRAM + Zen3 + DDR4) up to modern RTX with more RAM. Model size is operator-chosen; the app works with whatever Ollama serves. A GPU helps speed but is not required.
- RAM: 16GB minimum, 32GB recommended
- Storage: 5GB+ for models and databases
- Default local llama-server endpoints at `127.0.0.1:1234/v1` and `127.0.0.1:1235/v1`; Ollama is optional and uses its own configured endpoint when selected
