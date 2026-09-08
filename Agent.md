# Agent.md — MrBot1000 Runtime Contract

## Overview
MrBot1000 is a real-time AI agent system for **automated earning opportunity discovery, execution, and lifecycle tracking**. This document defines the operating rules, architecture, and capabilities for any model used by the program, including the new lifecycle-aware workflow for tracking opportunities from discovery through payment.

---

## Identity
- **Name**: MrBot1000
- **Mode**: Real operation, not simulation
- **Version**: 2.1
- **Goal**: discover real earning opportunities, execute actionable work, validate outputs, and persist outcomes in local database

---

## v2.1 Dual-Brain Contract (canonical)

MrBot1000 uses two GPU-isolated brains (llama.cpp / llama-server), coordinated deterministically:

| Brain | Role | GPU / CUDA | Port | Typical size |
|-------|------|-----------|------|--------------|
| **Big** | planning, coding, deep research, review/verification | RTX 5060 Ti 16 GB (device 0) | 1234 | 14B–27B |
| **Small** | human chat, triage, summarise, lightweight coordination | GTX 1660 Super 6 GB (device 1) | 1235 | 4B–7B |

- The canonical runtime (`agents/dual_brain_runtime.py`) is the single source of truth for role → endpoint/model/device. A model call never assumes a role/GPU of its own choosing.
- Cross-model collaboration is a **deterministic typed handoff** (plan → research → review → execute) via the EventBus + coordinator (`agents/dual_brain_coordinator.py`), not unconstrained model-to-model chat.
- **The LLM is NOT the source of truth.** Deterministic code controls validation, permissions, execution, financial actions, security, evidence, verification, and accounting.
- Human gates (identity, payments, contracts, signatures, captchas, irreversible actions, sensitive info) are hard stops — never bypassed.
- Revenue is realized ONLY from verified payment evidence. Submission ≠ payment.

---

## Architecture Overview

### Multi-Agent System
The system operates with specialized agents sharing state through `SharedContext` JSON:

| Agent | Role | Model | Color |
|-------|------|-------|-------|
| Manager | Coordinator & intent classifier | Main (gemma-4-E2B) | #bb86fc (purple) |
| Summarizer | Chat & conversation | Chat (LFM2.5-1.2B) | #00b0ff (cyan) |
| Coder | Code modification (actual file writes) | Main | #84cc16 (green) |
| Analyst | Code review & proposal analysis | Main | #3b82f6 (blue) |
| JobSearch | Find gigs (Fiverr, Upwork, web_search) | Main | #f97316 (orange) |

### Model Routing Strategy
- **Chat/Questions** → Summarizer with `chat=True` (fast, ~2s)
- **Tasks/Work** → Main model (accurate but slower)
- **Lifecycle/Status Questions** → Summarizer with runtime context from shared state so replies can reflect recent opportunity progress
- **Cross-talk** → SharedContext JSON (`~/.local/share/mrbot1000/shared_context.json`)

### Communication Flow
```
User Input → ManagerThread → Intent Classification → Route:
  question → Summarizer → Chat Model → Response → agents_tab.display()
  task     → Coder/Analyst → Main Model → Execute → Report
  status   → Summarizer + SharedContext → Lifecycle summary → UI/Chat update
```

### Current Operating Capabilities
- **Opportunity lifecycle tracking** for discovered → researched → applied → in progress → submitted → paid/failed stages
- **Workflow planning** that turns a discovered opportunity into a practical next-action plan
- **Shared-context runtime awareness** so chat can answer status questions using live program state
- **UI notifications** that highlight lifecycle changes and opportunity progress updates

---

## Hard Constraints (Security & Ethics)

### EARNING ACTIONS
- ✅ All earning actions must be **real, executable, and verifiable**
- ❌ Never invent fake earnings, fake payouts, or fake discovery results
- ✅ If source unavailable, report failure plainly
- ✅ Keep credentials local in `.env`; **never** hardcode secrets
- ✅ Respect platform ToS; avoid automation that creates spam/abuse

### CODE MODIFICATIONS
- ✅ All self-modifications require **validation pipeline approval**
- ✅ Self-improvement requires `PIPELINE_ALLOW_SELF_IMPROVE=true` in `.env`
- ✅ Changes pass: Syntax → Security → API → NullSafety → Spelling validation
- ✅ Score threshold ≥ 0.85 for self-improve actions

---

## Provider & Model Configuration

### Default Provider Priority (can be overridden)
1. OpenAI when `OPENAI_API_KEY` is set and provider enabled
2. Anthropic when `ANTHROPIC_API_KEY` is set and provider enabled  
3. Ollama when local server reachable (default)

### Current Model Configuration (.env)
```
OLLAMA_MAIN_MODEL=hf.co/llmfan46/gemma-4-E2B-it-ultra-uncensored-heretic-GGUF:Q4_K_M
OLLAMA_CHAT_MODEL=hf.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF:Q5_K_M
```

### Hardware Requirements
- **GPU**: 6GB VRAM minimum (GTX 1660 Super or better)
- **RAM**: 32GB recommended
- **Storage**: 5GB+ for models and databases

---

## Required Skills & Actions

### Skill Files Location
`skills/*.md` - Each skill defines:
- Skill name
- Requirements
- Steps
- Pitfalls
- Verification

### Current Skills
1. **social-discovery.md** - Find gigs on Reddit/Fiverr/Upwork
2. **opportunity-evaluation.md** - Score opportunities
3. **opportunity-filtering.md** - Filter by risk/reward
4. **opportunity-execution.md** - Execute approved tasks
5. **opportunity-lifecycle.md** - Track and report opportunity status through the lifecycle
6. **document-qa.md** - Answer questions about documents

### Safety-First Defaults (when no skill exists)

| Action Type | Default Behavior |
|-------------|------------------|
| discovery | Return empty/limited results |
| execution | Do nothing until validated |
| submission | Do not submit without user confirmation |
| self-improve | Only if checkbox enabled + score ≥ 0.85 |

---

## Memory System (5-Tier)

| Tier | Location | Purpose | Persistence |
|------|----------|---------|-------------|
| 0 - Transient | _conversation (Summarizer) | Recent chat context | Session only |
| 1 - Short-term | conversation.db | Last 30 messages | Session |
| 2 - Operational | agent.db | Actions, heartbeats | Persistent |
| 3 - Learning | summarizer.db | Patterns, improvements | Persistent |
| 4 - Historical | action logs | Full audit trail | Persistent |

---

## Agent Roster & State

### Agent States
- **ready** - Ready for work
- **thinking** - Processing request
- **researching** - Scanning files/context
- **writing** - Generating code/content
- **working** - Executing task
- **success** - Task completed
- **error** - Failed with error report

### Communication Protocol
Agents emit state changes via signals:
- `agent_status(status, task)` → Main thread → UI
- `chat_reply(label, text)` → Chat display
- `summary_ready(text)` → Summary window

---

## Data Flow & Storage

### Database Architecture
```
agent.db                      # SQLite, shared state
├── actions                   # All actions taken
├── heartbeats                # Agent status history
├── llm_calls                 # Model usage statistics
└── opportunities             # Earning opportunities found

summarizer.db                 # SQLite, chat history
├── chat_history              # User ↔ AI conversation
├── summaries                 # Task summaries
└── speech_patterns           # Style adaptation

earnings.db                   # SQLite, financial tracking
├── earnings                  # Income records
├── expenses                  # Costs/fees
└── payouts                   # Completed payments
```

### File Structure (ACTUAL - 2026-08-06)
```
MrBot1000/
├── main.py                   # Desktop app entry point
├── manager.py                # Agent orchestration (v4 - Opportunity Lifecycle Edition)
├── action_pipeline.py        # Secure code execution with validation
├── earning_pipeline.py       # Income tracking (real client: Fiverr/Upwork web search)
├── earning_memory.py         # Multi-tier memory system (5 tiers)
├── database.py               # SQLite wrappers
├── library.py                # Utility functions (web_search, safe_write_file)
├── ui.py                     # PySide6 UI components
├── Agent.md                  # This file - Agent runtime specifications
├── Skill.md                  # Skill specification format
├── .env.example              # Environment template
├── .gitignore                # Git ignore template
└── agents/                   # Agent implementations
    ├── base_worker.py        # Base worker with path validation and safe_write_file()
    ├── coder.py              # NEW (v2.0.3): Code agent with actual file execution
    ├── summarizer.py         # Chat agent (handles SummarizerThread)
    ├── job_search_worker.py  # Job discovery (REAL client: FiverrClient, UpworkClient)
    ├── analyst_worker.py     # Proposal analysis (IMPLEMENTED)
    ├── web_provider.py       # v2.0.23d configurable web search provider
    ├── shared_context.py     # Shared state JSON file
    ├── opportunity_lifecycle.py  # Lifecycle state machine
    ├── fiverr_client.py      # Fiverr RSS-based gig discovery
    ├── upwork_client.py      # Upwork API client
    └── [other workers...]    # airdrop_claimer, airdrop_scanner, etc.
└── tests/                    # Test suite
    ├── __init__.py
    ├── __main__.py
    └── test_results/         # Generated test JSON reports
```

⚠️ **IMPORTANT**: Do NOT reference `source.py` or `_argcomplete.py` - these files do NOT exist in this project. The model may hallucinate non-existent files; always verify against the actual agent implementations above.

---

## Execution Discipline

### Preferred Patterns
1. **Direct execution over meta-orchestration** - Do the work, don't plan to do the work
2. **Limit retries; fail fast and report** - Don't spin on failures
3. **Use tool outputs as evidence, not narration** - "Found 3 Reddit posts" vs "I see 3 posts"

### Output Reporting
```
✅ Success formats:
   - Action completed: file.py (no changes needed)  
   - Found 3 gigs matching criteria
   - Earned $45.50 from [platform]

❌ Failure format:
   - Reddit search failed: rate limited (2m wait)
   - File scan found no issues to fix
```

---

## Settings & Configuration

### Key Environment Variables
```
PIPELINE_ALLOW_SELF_IMPROVE=true   # Allow self-modification
MAX_TOKENS=1024                    # Response length limit
HEARTBEAT_INTERVAL=60              # Status update frequency
STARTUP_DELAY_SECS=2               # Startup wait time
```

### UI Settings Panel
- **Allow self-improvement** - Enable automatic code updates
- **Max tokens** - Response length control
- **Heartbeat interval** - Status update speed
- **Research cache TTL** - File cache expiration

---

## Debugging & Monitoring

### Live Logs Tab Fields
- **Timestamp** - When event occurred
- **Agent** - Which worker (Manager, Summarizer, Coder, etc.)
- **Thought** - Internal reasoning
- **LLM** - Provider, model, latency, response size
- **Status** - Ready/Working/Success/Error

### Common Log Patterns
```
[MANAGER] agent status: Ready — Waiting for work
[MANAGER] thought: Intent classified: question
[OLLAMA] LLM response model=... latency=16s chars=376
[Agent] thought: [Summarizer] Result: ...
```

---

## Development Notes

### Chat Architecture Decision
Chat responses route through **SummarizerThread** (QThread) but:
- Uses chat model with `chat=True` for speed
- Does NOT use `_execute_workflow` (that's for tasks)
- Calls `self.worker.llm(chat=True)` internally

### Why Two Models?
- **Main (gemma-4-E2B)**: Heavy analysis, accurate decisions, 15-30s responses
- **Chat (LFM2.5-1.2B)**: Fast conversation, 1-3s responses, 512-1024 tokens

Cross-model communication happens via `SharedContext` JSON file, allowing:
- Chat to check what the main model is working on
- Main model to pick up human requests without conflict

---

## Contact & Maintenance

- **Repository**: Local only (no GitHub)
- **Version**: Tracked in CHANGELOG.md
- **Support**: Self-hosted agent community
- **Last Updated**: 2026-08-06