# MrBot1000 v2.1.1 — Dual-Brain AI-Powered Earning Agent

A real-time AI agent system for automated earning opportunity discovery, execution, and lifecycle tracking. Runs entirely locally — no cloud dependencies, no data sharing.

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
| `CHANGELOG.md` | Change history through the current 2.1.1 release |
| `tests/__main__.py` | Test suite runner |

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
- Default local llama-server endpoints at `127.0.0.1:1234/v1` and `127.0.0.1:1235/v1`; Ollama is optional and uses its own configured endpoint when selected
