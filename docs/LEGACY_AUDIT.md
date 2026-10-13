# Legacy code audit — Manager / Coder / Analyst / Reviewer worker path

Date: 2026-10-13. Scope: the pre-N-brain "central CEO Manager + worker team"
architecture vs the current N-brain peer-council + EarningPipeline/AutonomousLoop.

## Summary — REMOVAL COMPLETE

The legacy central-Manager + Summarizer worker path has been **fully removed**
across Phases 1-3 of `.hermes/plans/2026-10-13_legacy-worker-manager-removal.md`,
plus a follow-up orphan sweep. The N-device peer council (Dialogue) + Chat tab +
EarningPipeline are the live system; they already covered everything the legacy
layer did.

## What was removed (commits)

| Commit | Removed |
|--------|---------|
| `a0ad872` (Phase 1) | Dead `WORKER_REGISTRY`, `WorkerRegistry` loader, compat shims (`services/agent_runtime.py`, `safety/tool_safety.py`) |
| `7803091` (Phase 2) | Memory & Stream tab + SummarizerDB panels (`_attach_memory_stream_panel`, `create_memory_stream_tab`, `_refresh_stream_health`/`_memory_db`/`_refresh_memory_panel`/`_clear_memory`) |
| `557bbee` (Phase 3a-d) | All ManagerThread/SummarizerThread/HeartbeatSystem **wiring** in main.py + GUI; dead operator hooks (task box, pause, type-to-chat, heartbeat spinner, research re-scan / self-improve buttons) |
| `b3771a0` (Phase 3e) | **Deleted** `app/manager.py`, `agents/services/summarizer.py`, `agents/dialogue/conversation_memory.py` |
| `388b6f4` (Phase 4 sweep) | Orphaned `manager_*` runtime helpers (metrics/queues/routing/scheduler/shutdown/workers) + dead EventBus chat publish in `_human_send` |

## What was KEPT (verified live, not duplicate)

- **EarningPipeline** (`app/earning_pipeline.py`) — constructed in main.py + `earning_services`, used by Social/Earning tabs; publishes `OPPORTUNITY_UPDATE` events that `QtEventBridge` delivers to the GUI. The real event backbone.
- **EventBus** (`agents/core/comms.py`) — still carries OPPORTUNITY/EVIDENCE/NOTIFICATION events to the dashboard. Only the chat/manager message routing (USER_REQUEST/TASK_REQUEST→manager) was orphaned and removed.
- **AgentRuntime** (`agents/runtime/agent.py`) — live via the Dialogue tab.
- **WorkerAgent** (`agents/brains/base_worker.py`) — GUI needs `_ollama_model_names_static()`, main.py needs `shutdown_ollama_executor()`.
- **JobSearchWorker** (`agents/earning/job_search_worker.py`) — **removed** (superseded
  by the EarningPipeline/discoverer/social_earning_platform discovery path; had no live
  importer, only its own test). Orphaned `job_search.db` deleted; dropped from the
  `query_db` allowlist (`STORE_AUTHORITIES` + tool schema) and `PROTECTED_SOURCE_FILES`.
- **Legacy 2D-office UI + ThoughtPanel** (`app/ui.py`) — **removed** (1431L → 88L, theme
  helpers only). `QuadThoughtPanel`/`ThoughtChannel`/`ManagerWindow`/`AgentWindow`/
  `CommsWindow`/`SummaryWindow`/`AgentsTab`/`AgentSprite`/`Particle` all deleted. The
  Chat tab (`ThinkingBox`) + Dialogue thought-graph already show reasoning; the thought
  panel's channels were fed only by orphaned handlers. `AgentCollaboration` classifier
  (JobSearch/Manager/Coder/Analyst buckets) removed too — zero callers.
- **CoderWorker / AnalystWorker** — reachable via approval-gated `self_improvement_commands` (coder) and `ProposalReviewer` (analyst, optional inject).
- **RuntimeStats** — lives in `agents/runtime/stats.py` (distinct from the deleted `manager_metrics`).

## No "Reviewer" class ever existed

The "review" role is served by `ProposalReviewer` (`agents/knowledge/proposal_reviewer.py`,
pre-submission gate) and the small-brain Navigator persona — not legacy dead code.

## SpeechPatternBank / ConversationMemory — removed

These were the only legacy pieces that *could* have served the N-device system
(learning each persona's observed voice), but personas are contract-defined
(`personas.py`) and nothing wired them in. Removed per user decision. If per-persona
learned voice is wanted later, re-introduce as a **fresh Dialogue-fed feature** —
do not resurrect the summarizer path.

## Residual cleanup (optional, not done)

- `ChatRouter.classify()` `route_to` labels ("manager"/"summarizer") — live routing
  tiers (big-brain vs small-brain), only consumed by `test_chat_router.py`; kept as
  internal semantics, not dangling legacy-module references. Nothing to purge.
