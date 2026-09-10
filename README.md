# MrBot1000 v2.1 — Dual-Brain AI-Powered Earning Agent

A real-time AI agent system for automated earning opportunity discovery, execution, and lifecycle tracking. Runs entirely locally — no cloud dependencies, no data sharing.

## v2.1 Highlights (2026-09-06)

- **Canonical dual-brain runtime** (`agents/dual_brain_runtime.py`): one source of truth for role→endpoint/model/device. Big Brain → RTX 5060 Ti (CUDA 0, port 1234); Small Brain → GTX 1660 Super (CUDA 1, port 1235). llama.cpp/llama-server default; Ollama/LM Studio are explicit opt-ins.
- **Canonical cross-model collaboration** (`agents/dual_brain_coordinator.py`): deterministic plan→research→review→execute handoff on the EventBus with a durable MessageLog ledger; model_fn injected (mock-first, cycle-safe).
- **Durable autonomous runs** (`agents/autonomous_run_store.py`): SQLite run/stage/idempotency ledger with restart recovery; autonomous-loop results now survive restarts.
- **Unified composition root** (`agents/composition_root.py`): one shared pipeline/portfolio/run_store/lifecycle per process.
- **First real paper/human-gated earning capability** (`agents/earning_capability.py`): produces a real TaskWorkspace deliverable, validates it deterministically, stops on human gates, packages locally, and records submission evidence — never fabricates payment or success.
- **Collaboration / Run Monitor tab** added (now 15 tabs).

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

Requires: Python 3.11+, llama.cpp (`llama.exe` / llama-server) or Ollama (local LLM server), and the packages listed in `requirements.txt`.

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
- Evaluates and ranks opportunities using a local Ollama model **plus** a deterministic Opportunity Intelligence Engine (LLM scores feed it as semantic estimates only — never the sole decision-maker)
- Executes safe, repeatable actions with full validation through a 14-step Task Execution pipeline with deterministic validators + human gates
- Tracks opportunities through discovery → researched → applied → in_progress → submitted → paid/failed with explicit, auditable stage transitions
- Surfaces startup warnings and runtime issues so configuration gaps are visible early
- Supports a safe mode that validates actions and skips real file changes while the workflow is being exercised
- Shares research snapshots across the manager and chat-side runtime context so both models can benefit from the same knowledge base
- Tracks earnings and payouts locally in SQLite with **Unified Economic Accounting** (verified vs unverified revenue, LLM cost, gas, net profit, ROI, net hourly rate)
- Runs a self-audit engine that identifies improvement opportunities across 14 categories without mutating safety constraints
- Supports multiple LLM providers (Ollama local, OpenAI, Anthropic, OpenRouter, Gemini, Groq, DeepSeek, Mistral, Together, NVIDIA NIM, vLLM, LM Studio, KoboldCpp) with cost-aware routing, per-provider main/chat role control, and circuit breakers
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

### Discovery Pipeline (legacy 4-stage, still supported)

1. Discover opportunities from supported sources
2. Evaluate and filter them by value, risk, and fit
3. Create a concrete next-action plan for the best options
4. Execute approved steps safely and record the result

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

- **Main model** (any model Ollama serves — e.g. gemma-4-E2B, ornith, llama3, or any size): GPU/CPU — Heavy analysis, code work, decisions
- **Chat model** (any model Ollama serves — e.g. gemma-3-1b, gemma-4-E2B, or any size): Fast conversation
- **Multi-agent system**: Manager (CEO), Coder, Analyst, JobSearch, Summarizer
- **Message routing**: Agents-tab chat is answered by the **Summarizer thread** (independent QThread, chat model) so replies are never blocked by the Manager's main-model work; task/command intents are forwarded to the Manager.
- **Cross-model communication**: EventBus (structured messages) + legacy SharedContext JSON (read-only fallback)
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

## UI Layout

The Agents tab contains:

1. **Chat Window** (center) — Conversational interface with main model
2. **Agent Roster** (right side) — Live agent status indicators
3. **Notifications Panel** (collapsible) — Agent actions, heartbeat logs, system events

> **Change in v2.0**: Notifications and agent actions are now separated from the chat window into a collapsible side panel. The chat window remains clean for conversational flow with the main AI model.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Application entry point, UI setup, theme system, settings persistence |
| `manager.py` | CEO ManagerThread — agent orchestration, intent routing, chat handling, heartbeat loop, per-role memory |
| `earning_pipeline.py` | Earning pipeline engine — discovery, evaluation, filtering, execution, economic accounting, self-audit, autonomous loop |
| `agents/base_worker.py` | Shared worker base: LLM calling with multi-provider fallback, secure file I/O, research utilities, provider registry |
| `agents/opportunity_models.py` | Canonical structured Opportunity model, flexible taxonomy, pluggable source interface, dedup, validation |
| `agents/discovery_sources.py` | Existing platform integrations as pluggable sources (Upwork, Fiverr, Social, Airdrop, DeFi, Microtask, Dynamic, WebDiscovery) |
| `agents/opportunity_lifecycle.py` | Opportunity lifecycle state machine with evidence-gated transitions |
| `agents/economic_accounting.py` | Unified Economic Accounting Layer (v2.0.36j) |
| `agents/self_audit.py` | Self-Audit Engine (v2.0.36j-T4) |
| `agents/autonomous_loop.py` | Unified 24-stage autonomous planning loop (v2.0.36k) |
| `agents/task_executor.py` | Generalized Task Executor — 14-step pipeline with validators + human gates (v2.0.36i) |
| `agents/opportunity_portfolio.py` | Opportunity Portfolio & Work Queue (v2.0.36h) |
| `agents/discovery_scheduler.py` | Dynamic Discovery Scheduler (v2.0.36f) |
| `agents/earning_discoverer.py` | Dynamic earning opportunity discovery (Reddit, GitHub bounties, referral programs) |
| `agents/airdrop_scanner.py` | Crypto airdrop monitoring from RSS feeds |
| `agents/social_earning_platform.py` | Social layer — Reddit, Twitter, LinkedIn, forum job discovery |
| `agents/evidence_store.py` | Evidence & Verification subsystem (v2.0.34au) |
| `agents/instruction_gate.py` | v2.0.22 provenance gate (untrusted SKILL.md) |
| `agents/trust_boundary.py` | v2.0.22 high-trust action boundary |
| `agents/platforms/` | v2.0.22 platform adapter skeleton (Fiverr/Reddit) |
| `action_pipeline.py` | Secure code execution with validation |
| `database.py` | AgentDB — SQLite database for thoughts, actions, LLM stats, evidence |
| `theme_config.py` | Theme system — presets + env-driven Custom theme |
| `gui/tab_builders.py` | GUI tab builders (extracted from main.py) |
| `ui.py` | Animated agent sprites, theme-aware widget styling |
| `Agent.md` | Agent runtime contract & rules |
| `ARCHITECTURE.md` | Full system architecture documentation |
| `CHANGELOG.md` | Change history (currently v2.0.36m) |
| `tests/__main__.py` | Test suite runner |

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Key settings:
- `OLLAMA_MAIN_MODEL` — Main model for heavy work
- `OLLAMA_CHAT_MODEL` — Chat model (smaller, faster)
- `OLLAMA_CHAT_GPU=0` — Chat model runs on CPU (offload from GPU)
- `PIPELINE_ALLOW_SELF_IMPROVE` — Enable/disable auto code updates
- `LLM_DAILY_BUDGET_USD` — Daily cloud-LLM spend cap (0 = off)
- `WINRATE_DECLINE_BELOW` — Auto-decline platform if win-rate below this %
- `MEMORY_ENABLED` — Per-role memory (chat + CEO)
- `THINKING_ENABLED` — Thinking/reasoning block for supported models
- `ALLOW_WEB_DISCOVERY` — Enable web search discovery (human-review gated)
- Per-provider: `<PROVIDER>_API_KEY`, `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODEL`, `<PROVIDER>_MAIN_ENABLED`, `<PROVIDER>_CHAT_ENABLED`

## UI Tabs

1. **Management** — Agent controls, pause/resume, pipeline controls, gig proposals, payout verification
2. **Agents** — Agent roster, chat interface, live status
3. **Providers & GPU** — Dual-brain orchestrator: llama-server start/stop, GPU isolation (5060 Ti / 1660 Super), model dropdowns, ctx/threads/n-gpu-layers (seeded from the canonical runtime)
4. **Safety & Tools** — Tool registry, safety rules, approval queue
5. **Chat** — Human ↔ Small Brain (1660 Super)
6. **Dialogue** — Big Brain ↔ Small Brain inter-brain chat
7. **Collaboration** — Collaboration / Run Monitor: run ledger, stage detail, "Run Collaboration" (drives the DualBrainCoordinator)
8. **Model & GPU** — Per-role GPU offload, LLM parameters, model info (dense/MoE, params, context, price)
9. **Memory & Stream** — Stream health telemetry, per-role memory (chat + CEO), long-term notes
10. **Browse Root** — File explorer
11. **Payments** — Balance, payouts
12. **Earnings** — Income tracking, revenue report (verified/unverified, LLM cost, gas, net profit, ROI)
13. **Settings** — Model selection, provider configuration (15+ providers), effect toggles
14. **Live Logs** — Debug output with severity filtering
15. **DB Stats** — Database metrics, recent actions, LLM call history, instruction review queue

## Agent Roster

| Agent | Role | Model | Purpose |
|-------|------|-------|---------|
| Manager (CEO) | Coordinator | Main | Primary chat/task ingress, orchestrates tasks, routes to workers, runs heartbeat strategy |
| Coder | Coding | Main | Code refactoring, bug fixes, implementation |
| Summarizer | Chat | Chat | Summarizes thought streams, maintains chat memory, provides contextual reply support |
| JobSearch | Job Discovery | Main | Finds gigs on Reddit, Fiverr, Upwork |
| Analyst | Analysis | Main | Proposal metrics, job evaluation |

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
- Ollama server running locally at `127.0.0.1:11434`
