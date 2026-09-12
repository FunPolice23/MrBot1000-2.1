## [Unreleased] - 2026-09-11

### Fixed
- The canonical persona names are now Edward Hurst for Big Brain/Driver and
  Jacob Stanley for Small Brain/Navigator. Stable `big_brain` and `small_brain`
  role keys are unchanged.
- LM Studio model IDs with namespaces, such as `qwen/qwen3.5-9b`, are now
  preserved when Dialogue synchronizes adapter models instead of being reduced
  to a basename that LM Studio cannot resolve.
- Providers & GPU now displays external-provider model IDs on GPU cards while
  continuing to display filenames for local `.gguf` selections. The actual
  `nvidia-smi` bar remains documented as total GPU-memory usage; it cannot
  identify which model owns that memory.
- Dialogue no longer records its malformed-output diagnostic as a persona turn,
  preventing the diagnostic from being detected as a repeated answer and
  causing a false non-progress loop.
- Dialogue capability gating now permits the loaded 3B Ministral chat model;
  sub-2B models and base/embedding models remain blocked as unsuitable for
  persona dialogue.
- Autonomous-loop payment verification now consults the central evidence
  transition policy instead of treating a single L3 payment record as sufficient.
- `payment_gross` is recognized as a payment evidence type for policy-gated
  transitions.
- L1 self-reported submission evidence cannot establish a paid outcome.
- The test runner now auto-discovers `test_*.py` unittest modules so new suites
  cannot be silently omitted from the default run.
- Startup validation now reports whether wallet key files are protected by
  `.gitignore`; missing protection produces a warning without blocking startup.
- Big Brain and Small Brain now have editable, persisted display names in
  Provider Configuration. Custom names are used in runtime metadata and persona
  prompts without changing stable internal role identifiers.
- Dialogue web research now marks search results as discovery evidence, includes
  retrieval/backend metadata, and directs personas to read source pages before
  treating current or consequential claims as verified.
- Web search now falls back from `ddgs` to `duckduckgo_search` when the primary
  backend is unavailable instead of silently presenting the failure as no evidence.

### Verification
- Live LM Studio probes confirmed that `qwen/qwen3.5-9b` and
  `mistralai/ministral-3-3b` were loaded through `/api/v1/models`; both exact
  namespaced IDs were accepted by `/v1/chat/completions` when given a suitable
  dialogue token budget.
- Provider and dialogue regression suites pass (`36 passed`), with no
  diagnostics in the touched modules.
- Focused autonomous-loop regression suite passes (`27 passed`).
- Full test runner passes (`62 passed`, including auto-discovered modules).
- Startup validation tests pass (`4 passed`).
- Runtime, dialogue, and startup regression tests pass (`51 passed` after the
  configurable-name coverage was added).
- Web evidence and dialogue self-check regression tests pass (`37 passed`).

## [2.1.1] - 2026-09-11 - Security, Dialogue, and Publishing Maintenance

### Added
- Added centralized read-only SQL enforcement for both model-facing database tools.
- Added malformed, mutating, multi-statement, and connection-cleanup SQL tests.
- Added explicit timeouts for OpenAI-compatible streaming requests through
  `OPENAI_STREAM_TIMEOUT_SECONDS`.
- Added Hugging Face download tests for untrusted redirects, oversized responses,
  and partial-download cleanup.
- Added `scripts/github_upload.py` with CLI and Tkinter workflows for sync, status,
  diff, pull, commit, push, and confirmed publish operations.
- Added `version.py` as the public release-version source of truth.

### Changed
- Provider and model lifecycle handling now supports Ollama, LM Studio, vLLM,
  KoboldCpp, and llama.cpp without routing external providers through llama.cpp
  ports or treating provider model IDs as GGUF file paths.
- LM Studio and Ollama now use their native load/unload APIs. Providers & GPU
  checks loaded model state instead of considering a reachable provider server
  to be a running brain.
- Big Brain and Small Brain can use different local models. Settings now expose
  independent Main model and Chat model selectors, persisting to
  `BIG_BRAIN_MODEL` and `SMALL_BRAIN_MODEL` without overwriting the other role.
- Dialogue adapters now follow the canonical runtime endpoint for external
  providers, preventing stale llama.cpp role URLs from breaking LM Studio
  dialogue requests.
- Dialogue persona turns now use a dialogue-only protocol that prevents small
  local models from leaking SQL or tool-call syntax into the conversation while
  preserving tool support for normal agent chat and analysis.
- External model load/unload completion now returns to the Qt GUI thread through
  a queued signal, preventing Providers & GPU from remaining stuck on
  `Loading...` after LM Studio finishes a request.
- Provider registry and runtime state are invalidated or rebuilt after live
  Settings changes so model and endpoint changes take effect without an
  application restart.

### Provider, Model Lifecycle, and Dialogue Fixes
- Added provider-aware model discovery and endpoint normalization for Ollama,
  LM Studio, vLLM, and KoboldCpp, including LM Studio native model status.
- Fixed LM Studio URL precedence so stale `BIG_BRAIN_URL` and `SMALL_BRAIN_URL`
  values cannot override the shared external-provider endpoint.
- Added role-specific external start and stop behavior for shared providers;
  Start Small Brain and Start Big Brain now load their configured model instead
  of attempting to launch an unnecessary llama-server.
- Fixed the public `DualBrainControl` handler bridge so external lifecycle
  helpers and completion callbacks are available to the active GUI class.
- Fixed status refresh so each brain is marked running only when its own
  configured model is loaded, even when both roles share one provider.
- Fixed dialogue model routing for LM Studio by using the canonical provider
  endpoint in both Big Brain and Small Brain adapters.
- Added bounded dialogue-mode prompts and disabled tool parsing for persona
  turns to prevent malformed outputs such as partial `query_db` SQL from being
  inserted into the shared dialogue transcript.

### Provider Verification
- Provider and runtime regression tests pass (`27 passed`).
- Modified provider, adapter, and GUI modules compile cleanly and report no
  diagnostics.
- Live LM Studio validation confirmed separate loaded instances, successful
  model generation, and successful direct Jacob Stanley dialogue generation.

### Existing Maintenance Changes
- Dialogue now populates and shares Goals, Tasks, and Progress state with Edward
  and Jacob instead of leaving those panels disconnected.
- Removed the redundant Collaboration and Memory & Stream tabs; useful telemetry
  now lives in Management while the coordinator backend remains available.
- Added explicit SQLite shutdown handling for JobSearchWorker and exception-safe
  self-audit queries.
- Expanded the GitHub mirror sync to include GUI, prompts, scripts, and all safe
  agent/test files while excluding local databases, credentials, model caches,
  and operator-specific configuration.
- Removed the obsolete `prep_github_upload.py` compatibility script; the
  non-destructive synchronizer and GitHub workflow now have one canonical path.
- Refreshed `.env.example` with current provider, Dialogue, timeout, and runtime
  settings while keeping secrets blank.

### Security
- `query_database` now fails closed unless its SQL compiles as a read-only query.
- Hugging Face model downloads reject redirects outside trusted Hugging Face hosts
  and remove partial files when declared size limits are exceeded.

### Verification
- Focused security/provider/download tests pass: 23 tests plus 9 subtests.
- Additional SQL/tool safety checks pass: 8 tests plus 5 subtests.
- Modified modules compile cleanly and report no diagnostics.

## [2.1.0] - 2026-09-10 - Stability and Provider Routing Maintenance

### Development History for This Maintenance Cycle
This section records the work completed from the initial provider/GPU report through the current Dialogue and discovery fixes.

1. **Provider and GPU configuration**
  - Investigated why Provider/GPU settings for GPU layers, KV cache, and batch size appeared to have no effect.
  - Connected the persisted settings to the dual-brain runtime and llama-server launch configuration.
  - Added role-specific GPU routing: Big Brain on the RTX 5060 Ti and Small Brain on the GTX 1660 Super.
  - Added context, threads, split mode, KV-cache type, batch size, and GPU-layer handling for each brain.

2. **Unified provider support**
  - Enabled llama.cpp alongside Ollama, LM Studio, vLLM, KoboldCpp, and cloud providers.
  - Added provider selection, enable/disable state, active local/cloud routing, API-key persistence, model selection, and cloud pricing information.
  - Added role-aware provider registration so Big Brain and Small Brain can use different local endpoints and models.
  - Added live registry invalidation so provider and model changes can take effect without restarting the whole application.

3. **Startup and crash repair**
  - Fixed duplicate Start/Stop signal wiring that caused full application crashes when launching either brain.
  - Added safer worker and QThread cleanup, interruption-aware GPU polling, and queued VRAM warning updates.
  - Moved the loading state ahead of model and VRAM checks so the UI reports progress immediately.
  - Verified that the Start action reaches the Running state in the focused GUI smoke test.

4. **GUI persistence and responsiveness**
  - Restored Appearance and Action Pipeline setting persistence.
  - Added lazy tab construction to reduce startup work and peak memory use.
  - Fixed stale Qt widget reads when provider controls have already been deleted or rebuilt.
  - Fixed the Settings provider configuration surface appearing as a separate Python window by assigning its Qt parent during construction.

5. **Dialogue routing and rendering**
  - Fixed blank first responses and removed synchronous endpoint probes from Dialogue tab construction.
  - Added inline capability notes instead of a misleading modal model-capability warning.
  - Preserved full llama.cpp model IDs while using provider-appropriate model names for other APIs.
  - Added response filtering and retry handling for boilerplate, severe repetition, and malformed local-model output.
  - Added visible generation status so an in-flight response is not mistaken for a blank or frozen tab.
  - Scaled Dialogue output budgets from each model's configured context instead of imposing a fixed 2k/4k limit.
  - Kept long-running Live conversations unlimited by default, with optional `DIALOGUE_MAX_EXCHANGES` and explicit Stop control.

6. **Long-running recovery and model stability**
  - Prevented Dialogue from replacing an already-loaded llama.cpp model with a stale or reordered combo-box entry.
  - Prefer the model reported by each live `/v1/models` endpoint during initial synchronization.
  - Added retry behavior for transient connection failures without passing transport errors to the other persona or stopping Live mode.
  - Changed duplicate-response handling so one repeated answer does not terminate a running conversation.

7. **Discovery and earning workflow**
  - Fixed the Twitter/X scanner's missing `os` import.
  - Added a read-only uGig source using its public hiring-listings API; uGig and the opt-in web source are now included in normal and scheduled discovery defaults.
  - Added uGig-specific scheduler search terms so scheduled discovery assigns tasks directly to uGig instead of routing generic strategies to the first source.
  - Preserved the existing human-gated action and earning workflow while improving the social opportunity scan path.

### Provider and Model Runtime
- Fixed llama.cpp provider registration for the dual-brain runtime, including role-specific Big Brain and Small Brain endpoints.
- Fixed the Settings llama.cpp Enable action being immediately reversed by a second toggle in the main-window bridge.
- Added separate Big Brain and Small Brain URL fields, defaulting to ports 1234 and 1235, and persist both role enable flags together.
- Fixed the Providers & GPU status remaining at `Loading...` after llama-server had already loaded and begun listening, by moving the completion refresh back onto the Qt event loop.
- Applied the selected KV-cache precision to launch commands and VRAM estimates; `q8_0` and `q4_0` now reduce the estimated KV allocation, while `auto` normalizes to `f16`.
- Clarified that the `Actual (nvidia-smi)` bar measures total GPU memory only; the KV breakdown remains a metadata-based estimate because nvidia-smi cannot separate weights from KV cache.
- Added unified local/cloud provider configuration with API-key fields, model selection, active-provider routing, and cloud model pricing display.
- Enabled llama.cpp as a selectable local provider and connected the GPU, KV-cache, batch-size, context, thread, and GPU-layer settings to the runtime configuration.
- Preserved the model actually loaded by each llama-server during Dialogue initialization instead of replacing it with a stale or reordered GUI combo selection.
- Kept explicit model changes from the Providers & GPU tab working while preventing per-turn Dialogue model overwrites.
- Improved Dialogue generation budgets so output scales with each model's configured context window, with `DIALOGUE_MAX_TOKENS` available as an override.

### Dialogue and Long-Running Operation
- Fixed blank Dialogue responses by adding visible generation status and improving local-model response handling.
- Added retry handling for transient llama.cpp connection failures without stopping Live mode or passing transport errors to the other persona.
- Changed repeated-response handling so one duplicate does not terminate a long-running conversation.
- Removed the implicit 100-exchange Live limit; Live mode now runs until stopped or until the optional `DIALOGUE_MAX_EXCHANGES` limit is reached.
- Preserved bounded Auto-Step behavior for manually controlled runs.

### GUI Stability
- Fixed Settings-tab provider configuration ownership so it remains embedded instead of appearing as a separate Python window.
- Hardened stale Qt widget reads during settings persistence.
- Improved lazy tab construction, provider status handling, GPU polling, and QThread cleanup around the Providers & GPU surface.
- Added resolution-aware window sizing and View > Window Mode options for Normal, Maximized, Fullscreen, and Borderless presentation.
- Fixed the Start/Stop crash path caused by duplicate signal wiring and unsafe running-QThread cleanup.
- Restored the visible Start All Brains and Stop All Brains controls in the active Providers & GPU tab; Start All now launches both non-blocking brain probes together instead of delaying the second brain by two seconds.
- Fixed the Providers & GPU layout omission that constructed the Quick Actions group but never added it to the rendered layout, so Start All Brains and Stop All Brains are now visible after a clean launch.

### Agent Collaboration and Trust Boundaries
- Fixed the ordinary Edward/Jacob chat tool loop so shell commands, file writes, account/payment changes, and proposal creation are refused unless an approval-capable workflow handles them.
- Routed remote `skill.md` reads through the instruction provenance gate; fetched documents are labeled untrusted and require human review before any action is based on them.
- Updated typed dual-brain collaboration handoffs so research, review, and execution receive labeled results from preceding stages instead of only the original goal.
- Routed refused Dialogue actions into the visible approval queue, strengthened receipt-based rules against fabricated credentials or completed actions, and stopped duplicate/empty model output from feeding endless Live-mode loops.
- Clarified the platform-playbook workflow: agents may read and discuss a remote `skill.md`, summarize its requirements and risks, and draft next steps; credentials, installations, shell commands, account creation, and external submissions remain separate approval-gated actions.
- Fixed Dialogue cancellation when Live is stopped or a brain model changes: active generations are cancelled cooperatively, stale completions are discarded, and cancelled QThreads remain referenced while they unwind instead of leaving the UI stuck on Loading or risking premature thread destruction.
- Moved VRAM warnings and model-loading feedback onto the GUI-safe signal path so startup does not freeze or update widgets from worker threads.
- Restored persistence for Appearance and Action Pipeline settings.

### Social Discovery
- Fixed the Twitter/X social scanner `name 'os' is not defined` failure.
- Added live read-only uGig discovery and source-level parsing coverage so public hiring listings are no longer omitted from discovery cycles.

### Verification
- Updated modules compile cleanly.
- Provider and tab regression tests pass (`6 passed`).

### Known Limitation
- Some llama.cpp model/template combinations can still return malformed repeated thought-token output (for example repeated `4096` fragments). This is handled as invalid/retryable Dialogue output but requires matching the server chat template to eliminate at the source.

---

## [2.1.0] - 2026-09-07 — Phase 2.5: Unified Web Controller

### Web Controller (`agents/web_controller.py`)
- **`WebController`** unified interface for search, browsing, scraping.
- `search(query)` via `ddgs` with `ddgr_fallback()` to `duckduckgo_search`.
- `read_page(url)` via `requests` + `BeautifulSoup`.
- `scrape(url)` structured extraction: headings, links, emails, phones, prices, socials.
- `browse(url)` Playwright async browser automation.
- `screenshot(url)` full-page capture.
- `check_site(url)` online status and response metrics.
- `format_search()` / `format_page()` human-readable output.

### WebEyes Maintained (`agents/web_eyes.py`)
- Existing `WebEyes`, `search_web()`, `read_url()`, `browse_to()` retained.
- New controller is the preferred backend for GUI/tools.

### Playwright
- Chromium installed and verified working.

---

## [2.1.0] - 2026-09-07 — Phase 3: Safety (Multi-layer guard, recursion, firewall, approvals, rate limiting)

### Safety Guard (`agents/safety_guard.py`)
- **`SafetyGuard`** orchestrator coordinating all safety layers.
- **`CostGuardLayer`** — daily/weekly LLM spend limits.
- **`RecursionDetectorLayer`** — infinite loop detection with depth, timeout, and pattern detection.
- **`ToolFirewallLayer`** — tool allow/deny lists.
- **`HumanApprovalLayer`** — human sign-off for high-value actions (>$50, high-trust actions).
- **`RateLimiterLayer`** — per-tool/per-provider rate limiting.
- **`SafetyViolation`** exception for blocked actions.
- Integrates existing `CostGuard` and `ProviderCircuitBreaker`.

### Safety Tab GUI (`gui/safety_tools_tab.py`)
- **Status sub-tab** — safety layers status, circuit breaker, rate limits.
- **Approvals sub-tab** — pending approvals with approve/reject buttons.
- **Config sub-tab** — cost guard, recursion detector, firewall configuration.

### Verification
- All safety layers compile clean.
- Safety tab renders correctly.

---

## [2.1.0] - 2026-09-07 — Phase 2: Intelligence (Data Providers, Scraping, Reputation, Backtesting, Analytics)

### Data Providers (`agents/data_providers.py`)
- **`DataProvider`** ABC with rate limiting, HTTP GET/POST, error handling.
- **`CoinGeckoProvider`** — crypto prices, trending, market chart, global data, search.
- **`AlpacaProvider`** — stock prices, bars, options chain, news (paper/live).
- **`NewsAPIProvider`** — news search, top headlines, sources.
- **`TavilyProvider`** — AI-powered web search and URL extraction.
- **`FREDProvider`** — Federal Reserve economic data, interest rates.
- **`DataFetcher`** — unified multi-provider fetcher with fallback.

### Web Scraping (`agents/web_scraper.py`)
- **`RateLimiter`** — per-domain rate limiting.
- **`RobotsChecker`** — robots.txt compliance.
- **`HTMLExtractor`** — parse HTML, extract text, links, tables.
- **`WebScraper`** — ethical scraping with user-agent rotation, email/phone/price extraction, JSON-LD, Open Graph, meta tags.

### Reputation System (`agents/reputation.py`)
- **`ReputationTracker`** — per-platform metrics, overall score, badges.
- **`Badge`** system with tiers (Bronze → Diamond).
- **`WorkRecord`** — completed task tracking.
- Auto-badge earning based on milestones.
- Persistent state to disk.

### Backtesting Engine (`agents/backtesting.py`)
- **`Strategy`** ABC with `generate_signal()`.
- **`MovingAverageCrossover`** — fast/slow MA crossover.
- **`RSIStrategy`** — RSI overbought/oversold.
- **`BacktestEngine`** — run strategies, calculate metrics (Sharpe, drawdown, win rate, profit factor).
- Strategy comparison and reporting.

### GUI Tabs (Phase 2)
- **Analytics** (`create_analytics_tab`) — crypto price display, strategy performance table, backtest runner.
- **Reputation** (`create_reputation_tab`) — overall score, badges, platform breakdown.
- **Data Explorer** (`create_data_explorer_tab`) — URL scraping with results display.

### Verification
- All new modules compile clean.
- All new tab builders compile clean.
- All new main.py tab registrations compile clean.

---

## [2.1.0] - 2026-09-07 — Phase 1: Foundation (Platform APIs, Cost Tracking, Scanning, Workflows, Paper Trading)

### New Platform Adapters (`agents/platforms/`)
- **`upwork.py`** — Full Upwork API adapter with OAuth 2.0, job search, job details, proposal drafting, proposal submission (human-gated), profile/categories. Rate-limit tracking.
- **`prolific.py`** — Prolific API adapter with API key auth, study search, study details, eligibility check, profile. `ai_disallowed` policy (human participants required).
- **`github.py`** — GitHub API adapter with PAT auth, issue search (with labels/filters), issue details, repo search, repo details, PR creation (human-gated), issue creation (human-gated), rate limit tracking.
- **`registry.py`** — Central adapter registry with `create_adapter()`, `create_all_adapters()`, `list_adapters()`.
- **`__init__.py`** — Updated exports for all adapters.

### Cost Tracking (`agents/cost_tracker.py`)
- **`CostTracker`** class with daily/weekly/monthly spend caps.
- Per-model, per-provider, per-platform spend breakdown.
- Budget alerts at 80% threshold.
- Spend forecasting (daily avg → weekly/monthly projection).
- Persistent state to disk.
- `should_allow_call()` for pre-flight budget checks.

### Opportunity Scanner (`agents/opportunity_scanner.py`)
- **`OpportunityScanner`** background daemon thread.
- Polls all configured platforms at configurable intervals.
- Scores opportunities using `OpportunityIntelligence`.
- Stores results in database.
- Callback system for new opportunity alerts.
- `scan_now()` for immediate scans.

### Workflow Engine (`agents/workflow_engine.py`)
- **`WorkflowEngine`** with structured phases: Discovery → Vetting → Proposal → Execution → Review → Completed/Failed/Rejected.
- Phase transition validation.
- Cost budget checks before expensive phases.
- Full audit trail with `PhaseEntry` history.
- Aggregate metrics (success rate, ROI, earnings, costs).
- Callback system for workflow events.

### Paper Trading (`agents/paper_trading.py`)
- **`PaperTradingEngine`** with virtual portfolio.
- Market/Limit/Stop orders with slippage and fee simulation.
- Position tracking with unrealized/realized PnL.
- Performance metrics (Sharpe ratio, max drawdown, total return).
- Equity curve tracking.
- Text-based performance report generation.

### Safety & Cost Controls
- **`CostGuard`** (existing) now integrated with new `CostTracker`.
- All HIGH_TRUST actions (proposal submission, PR creation) require `confirmed_by_human=True`.
- Rate limit tracking on all platform adapters.

### Verification
- All new modules compile clean (`python -m compileall -q agents/`).
- Platform adapters follow existing `PlatformAdapter` ABC pattern.
- Human approval gates enforced on all mutating actions.

---

### Phase 4 — Payments & Wallets
- **Wallet Manager** (`agents/wallet.py`) — SOL/ETH/USDC support, multi-chain, address validation, balance tracking.
- **x402 Payments** (`agents/payments.py`) — `X402Payment` create/verify/settle flow.
- **Escrow System** (`agents/payments.py`) — milestone-based escrow with release/refund.
- **Automated Payouts** (`agents/payments.py`) — threshold-based auto-payout scheduling.
- **Payments GUI** (`gui/payments_tab.py`) — full Payments tab with wallets/transactions tables.

### Path 1 — Real Freelance Research + Human Submit
- **`FreelanceFinder`** — live web search for real gigs across Upwork, Fiverr, Reddit, Prolific.
- **`ProposalWriter`** — generates tailored proposals/cover letters for found gigs.
- **`PlatformSubmitter`** — packages proposals with human approval gates and evidence trails.
Revenue path: human submits, real money; agent does research + drafting only.

## [2.0.37e] - 2026-09-10 — DB column migration + DualBrainControl deferred signal wiring

### Bug fix: `sqlite3.OperationalError: near "EXISTS": syntax error` on startup (database.py)
- `_create_tables()` ran `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` batches that failed on existing databases that already had some (but not all) of the new columns — e.g. a DB created before `cost_usd` was added would hit the column-level `IF NOT EXISTS` edge case on `ALTER TABLE`.
- Fix: split the schema init into per-column `ALTER TABLE llm_costs ADD COLUMN ...` migration steps guarded by `try/except OperationalError`, so legacy databases get `prompt_tokens`, `completion_tokens`, `tokens_per_second`, and `cost_usd` columns on startup without error. The `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` DDL stays intact for brand-new databases.
- Verified: `AgentDB()` + `get_llm_stats()` succeed on an existing DB; the returned stats dict includes `total_cost`.

### Bug fix: `DualBrainControl` construction — `AttributeError` / `AttributeError: '_on_start_small_brain'` on tab switch (gui/dual_brain_control.py)
- Root cause: `setup_ui()` runs during `__init__` and called `.connect()` on handlers that are defined later in the class body (56 methods appear after `setup_ui` in source order). The first tab switch triggered `_ensure_tab_built` → builder → `DualBrainControl(...)` → `setup_ui` → `.connect(self._on_start_small_brain)` where `_on_start_small_brain` did not yet exist on the instance → `AttributeError`.
- Fix: introduced a deferred-wiring pattern. All `_wire_*` helpers (`_wire_all_signals`, `_wire_start_stop_buttons`, `_wire_refresh_buttons`, `_wire_settings_signals`) are defined in the class body BEFORE `setup_ui` and only touch methods that exist at class-definition time. A single `QTimer.singleShot(0, self._wire_all_signals)` in `__init__` fires after `setup_ui()` completes and the full class body is loaded, so every handler is present when the connections are made. Each `_wire_*` uses `hasattr` guards so it is safe to call multiple times.
- Additionally restored two missing `QLabel.addWidget()` calls for the per-brain advanced llama.cpp settings labels (`sb_adv_label` at settings row 2, `bb_adv_label` at row 5) that had been dropped by an earlier patch.
- Verified: `DualBrainControl` imports cleanly; AST audit confirms zero `.connect()` calls inside `setup_ui` targeting methods defined after `setup_ui`; all `_wire_*` and all target handler methods exist on the class.

### CHANGELOG catch-up
- This entry retroactively documents the database column migration and the `DualBrainControl` deferred-wiring fix that were applied above. Subsequent entries will follow the same format.

---

### Personas (agents/personas.py) — replace generic Big/Small "robot" framing
- Two named personas the user can relate to, each with a real identity, personality
  type, strengths, abilities, memory, rules/guardrails, and history:
  - **Driver** (ambitious, action-biased big-picture STRATEGIST) → Big model (5060 Ti,
    GPU0, :1234). Pushes goals forward, plans, drives action.
  - **Navigator** (cautious, risk-averse quick-CHECKER) → Small model (1660 Super,
    GPU1, :1235). Double-checks before anyone acts, flags scams/red flags, gates approval.
- Mapping is user-chosen and binding (persona is a prompt/identity layer; the
  model→GPU assignment underneath is unchanged). Verified: `persona_for_brain_role`.
- Memory/history/guardrails are REAL: `Persona.memory_context()` /
  `.personality_addon()` / `.recent_history()` read the existing MemoryDatabase,
  PersonalityEngine, and KnowledgeContext singletons.
- `Persona.build_system_prompt(goal)` produces a complete persona system prompt,
  decoupled from the legacy prompts/*.txt role files.
- Both adapters (`agents/small_brain.py`, `agents/big_brain.py`) now accept an
  optional `system_prompt=` in `chat()` so dialogue can inject the persona framing.

### Goal-driven fluid lifecycle (gui/dialogue_tab.py, rewritten)
- The Dialogue tab is now Driver ⇄ Navigator working an ACTIVE GOAL through a fluid
  lifecycle: discuss → discover → discuss → plan → discuss → action → discuss →
  monitor (repeats). No more asking a non-existent human for profile details.
- Every autonomous turn picks the lifecycle phase, builds that persona's system
  prompt, and injects it. Verified headless: Driver→big, Navigator→small, persona
  system prompts reach the model, and phases alternate correctly.
- Kept: **▶ Auto-Step** (bounded, default 10 turns) and **🔁 Live** (continuous until
  Stop), plus ⏭ Step / 🧹 Reset, a 🎯 Goal field, and a ❓ Help button.
- `system_prompt` is threaded from the tab → DialogueWorker → brain.chat so the
  persona framing (not the old role file) governs dialogue.

### Collaboration ⇄ Dialogue goal connection (gui/tab_builders.py, collaboration_tab.py)
- Setting a goal in the Dialogue tab mirrors into the Collaboration tab's goal box,
  and submitting a goal in Collaboration sets the Dialogue tab's goal — both tabs
  share the active objective. Verified in a real headless MainWindow (5/5).

### In-app Help (gui/help_dialog.py + agents/help_catalog.py)
- New searchable ❓ Help dialog listing features with a short description + a concrete
  example each. Data comes from `agents/help_catalog.py` (36 grounded entries, built
  by reading the real code). A `? / Help` button on the Dialogue tab opens it;
  `show_help_dialog()` can be called from any surface.
- `agents/help_catalog.py`: `FEATURES` list, `lookup(keyword)`, `catalog_text()`.

### Verification (headless, clean PYTHONPATH, os._exit for Qt teardown)
- personas module imports/maps/hooks real memory ✓
- dialogue lifecycle: personas alternate Driver/Navigator, correct model per persona,
  persona system prompts injected ✓
- goal bridge Dialogue↔Collaboration works in a real MainWindow (5/5) ✓
- Help dialog renders 36 features, search filters, detail pane ✓
- all changed files compile ✓

## [2.0.37c] - 2026-09-06 - GPU VRAM-affinity guard (warn-but-allow) + no-auto-model-switch enforcement

### Rule 1 — No automatic model/.gguf switching (binding, re-confirmed)
Verified enforced end-to-end in `gui/dual_brain_control.py`:
- The model combos are **non-editable** and only a genuine user selection change fires
  `_on_{small,big}_brain_model_changed`.
- The only programmatic writers are `_repopulate_model_combo` calls, which run under
  `blockSignals(True)` and, since v2.0.37b, **preserve the user's current selection** when it
  still maps to a real .gguf. No periodic timer, probe, or tab refresh can change the running
  model behind the user's back.

### Rule 2 — GPU/VRAM affinity (binding, warn-but-allow)
Policy: 5060 Ti (Big Brain) never overflows to the 1660 Super; the 1660 Super (Small Brain,
6 GB) is only for tiny (<1B-param) models; overflow beyond a GPU's VRAM goes to SYSTEM RAM,
never across PCIe to the other card. Cross-GPU spill is already structurally impossible (each
brain is its own llama-server pinned to ONE device with `--split-mode none`).

New `agents/gguf_meta.py` — dependency-light GGUF reader that estimates a model's total VRAM
need (weights file size + KV cache at the configured context) across all architectures (dense +
MoE, verified on every local .gguf).

`gui/dual_brain_control.py` — before launching either brain, `_check_vram_affinity()` queries
the target GPU's free VRAM (`nvidia-smi`); if the model's estimated need exceeds it, a warning
dialog asks the user to confirm an overflow-to-system-RAM spill is intended (Start cancels
unless confirmed). Verifies the correct device is consulted per brain (0 = 5060 Ti / Big,
1 = 1660 Super / Small). No cross-GPU routing is ever offered.

## [2.0.37b] - 2026-09-06 - Fix auto model flip-flopping in Providers & GPU tab

### Bug (user report)
The Providers & GPU tab kept auto-switching brains to models the user did NOT select:
a brain would be on the user's chosen model, then automatically restart with a different
model ("♻️ Switching ... model to X" with no user action), and this repeated over time.
Worse, the wrong models ended up on the wrong GPU (e.g. Small Brain launching the 27B on the
1660 Super).

### Root cause (reproduced deterministically)
`_apply_provider_status` runs on every status probe and called
`_repopulate_model_combo(small, loaded_model)`, which FORCE re-selected the combo to whatever
the server currently reported as loaded. When the user picked a new model, a stale/transitional
probe still reporting the OLD loaded model yanked the combo back to the old model → fired
`currentTextChanged` → `_on_*_brain_model_changed` saw loaded!=selection → restarted the brain →
endless flip-flop that kept auto-switching models.

### Fix (gui/dual_brain_control.py)
- `_repopulate_model_combo` now treats the combo as the USER'S INTENDED model. It preserves the
  current valid selection whenever it still maps to a real .gguf in the list, and only auto-selects
  the loaded model when there is NO existing valid selection yet (fresh panel / external server).
  A stale probe can no longer override the user's choice.
- Verified headless: (a) user picks Qwen3-4B, a stale gemma probe arrives → combo STAYS Qwen3-4B;
  (b) model_changed fires no restart when the selection already matches the loaded model, and one
  restart only on a genuine user change.

## [2.0.36z] - 2026-09-06 - Dialogue tab: bridge from Chat + continuous Live mode; interpreter isolation

### v2.0.36x: Runtime interpreter isolation
- `main.py`: added `_sanitize_sys_path()` at the very top (before third-party imports) that
  drops foreign venv/site-packages entries from `PYTHONPATH`, keeping only this interpreter's own
  site-packages (`sys.prefix`/`sys.base_prefix`) + the repo root. A parent process (desktop app /
  agent shell) sets PYTHONPATH to its own venv; launched via the project `.venv`, the app inherited
  it and imported `openai`/`pydantic_core` from the foreign venv (ABI-incompatible
  `pydantic_core._pydantic_core` crash) → `LlamaCppAdapter.available()` False → llama.cpp brains
  disabled + bogus "[Startup] missing deps". Verified under polluted PYTHONPATH: openai+pydantic_core
  resolve to the project `.venv`; full MainWindow builds.

### v2.0.36y: Fix Chat tab GUI freeze on escalation
- `gui/chat_tab.py`: Chat's escalation path (Small Brain decides a message needs Big Brain, then
  re-summarises) called the slow 27B `big_brain.analyze()` and `small_brain.chat()` synchronously on
  the GUI thread → froze the UI. Moved to a new `EscalationWorker` QThread emitting
  big_done/small_summary/failed signals.
- `agents/small_brain.py`: `should_escalate()` is now keyword-only (was doing a blocking Small Brain
  round-trip on the GUI thread to decide).

### v2.0.36z: Dialogue tab — bridge from Chat (A) + continuous Live (B)
- `gui/chat_tab.py`: new `exchange_complete(user_msg, small_reply)` signal emitted after each
  completed exchange.
- `gui/tab_builders.py`: when a Chat exchange completes and the Dialogue tab has been opened, the
  bridge calls `DialogueTab.ingest_exchange()` which records Human→Small then kicks off a Big Brain
  follow-up — so you SEE the conversation continue between the two brains (option A).
- `gui/dialogue_tab.py`: new continuous **Live** mode (option B) — a `🔄 Live` button runs an
  unbounded Big↔Small dialogue (chained one response at a time, never overlapping, 200-message
  safety ceiling) until paused; Step/Pause/Reset all stop Live cleanly.

## [2.0.36w] - 2026-09-06 - Remove "Model & GPU" tab (fold useful controls into Settings); llama.cpp-default bug-fix batch

### v2.0.36w: Remove the redundant "Model & GPU" tab
- `main.py`: dropped "Model & GPU" from tab_specs. The Providers & GPU tab already exposes
  per-brain llama.cpp ctx/threads/gpu-layers/split/batch, so the separate Ollama-GPU-offload tab
  was redundant (and Ollama is disabled).
- `gui/tab_builders.py::create_settings_tab`: relocated the still-useful generic controls
  (Max Tokens, Daily LLM budget, Auto-decline win-rate, Model Info panel + Refresh) into a new
  "LLM Parameters" / "Model Info" group at the end of the Settings tab. Widget names kept
  identical (`self.max_tokens_spin`, `self.llm_budget_edit`, `self.winrate_edit`,
  `self.model_info_browser`) so `save_settings` / `_refresh_model_info` work unmodified.
- Removed the now-dead `create_model_gpu_tab` Ollama GPU-spin code.
- Verification (headless): "Model & GPU" gone from tab list; Settings builds with all four
  relocated controls; `save_settings()` runs clean.

### Bug-fix batch (v2.0.36t/u/v) — see commits
- **36t** `base_worker._build_provider_registry`: dual-brain llama.cpp adapters auto-detect the
  loaded model from the live server (list_models) when BIG/SMALL_BRAIN_MODEL isn't preset. Fixes
  `providers=[]` → "LLM unavailable" whenever Ollama is disabled: main→big-brain, chat→small-brain.
  Also `dual_brain_control._launch_and_wait` startup deadline 15s→120s (big models like a 26B load
  in 60s+; Phi-4 ~5s).
- **36u** `gui/dialogue_tab.py`: Auto-Step fired 10 concurrent inference threads that raced on
  shared history → crash/freeze. Rewrote to sequential chaining (one worker at a time);
  respond() no-ops if a worker is in flight; fixed current_speaker init; Reset stops in-flight work.
- **36v** `base_worker` model-context resolver: `ollama show` subprocess now uses
  CREATE_NO_WINDOW (was flashing a console window + blocking ~8s on dead Ollama → the settings
  freeze).

### Verification
- With both llama-server up, provider registry = [..., big-brain, small-brain]; chat→small-brain,
  main→big-brain; a live small-brain complete() returned "OK."
- Headless: Dialogue Auto-Step advances Small→Big sequentially with one worker in flight, no crash.

## [2.0.36s] - 2026-09-06 - Fix: cannot stop/change externally-running llama-server models

### Bug (user report)
In the Providers & GPU tab, the two brains' servers showed as Running but had been
started OUTSIDE the current panel (leftover from a prior run / start scripts). Because
`we_started_small/big` were False, two guards blocked every action:
- **Stop buttons** logged `⚠️ ... was not started by this panel — not stopping` and did nothing.
- **Model change / restart** could not free the port, so Start short-circuited with
  `... already running` — making it impossible to change or stop models.

### Root cause
Stopping relied on (a) a `we_started_*` ownership flag and (b) `taskkill /FI
"WINDOWTITLE eq llama-server*{port}*"`. Servers launched with `CREATE_NO_WINDOW` have no
matching window title, so even the "fallback" kill never worked.

### Fix (gui/dual_brain_control.py)
- The panel OWNS its configured brain ports. Stop now always acts on whatever is listening
  there, regardless of who spawned it.
- New `_pid_on_port(port)` finds the LISTENING PID on 127.0.0.1:<port> via netstat, and
  `_kill_llama_on_port(port)` taskkills that PID — reliable for CREATE_NO_WINDOW servers.
- `_force_stop_brain(small)` stops the exact child we spawned if a handle is alive, else
  kills by port PID; it no longer depends on window-title matching or an ownership flag.
- `_on_stop_small_brain` / `_on_stop_big_brain` delegate to `_force_stop_brain` and no longer
  refuse externally-started servers. `_on_stop_all` then stops both reliably.

### Verification (REAL end-to-end, not just unit)
- Killed the two externally-running servers (PIDs on :1234/:1235) via `_kill_llama_on_port`;
  ports confirmed free.
- Started the Small Brain through the panel with Qwen3-4B (no "already running" refusal),
  then switched it to gemma-3-1B via the model dropdown handler — it auto-stopped the old
  server and relaunched with the new model (confirmed serving gemma-3-1B). Restored both
  brains to their Qwen defaults afterward.
- `py_compile` clean.

## [2.0.36r] - 2026-09-06 - Remove legacy "Agents" tab; Chat is the single chat surface

### Change
- `main.py`: removed the legacy "Agents" tab from `tab_specs`. The "Chat" tab (Human ↔ Small
  Brain) is now the single chat surface.
- The removed Agents tab (`AgentsTab` from `ui.py`) drove the legacy Manager/worker swarm
  (roster/heartbeats/pause/manager chat). That swarm is superseded by the dual-brain Chat.
- All `main.py` references to `agents_tab` / sprites were already behind `hasattr` guards, so they
  inertly no-op now; the summarizer-sprite handler only connects inside the (now uncalled) Agents
  builder; the "switch to Agents index 1" line is nested inside the `hasattr(agents_tab)` guard and
  no longer fires. No other code eagerly built or defaulted to the Agents tab.

### Verification
- `py_compile` main.py + gui/tab_builders.py clean.
- Headless MainWindow build: tab list is now Management, Providers & GPU, Safety & Tools, **Chat**,
  Dialogue, Collaboration, Model & GPU, Memory & Stream, Browse Root, Payments, Earnings, Settings,
  Live Logs, DB Stats. No "Agents"; Chat builds and selects; Management (index 0) builds fine.

## [2.0.36q] - 2026-09-06 - Model dropdowns list ALL local .gguf + auto-restart on model change

### Fix: brains could only ever show the model already loaded
The Small/Big Brain model dropdowns were populated ONLY from the running llama-server's
`/v1/models`, which in single-model mode returns just the ONE model currently loaded. So each
dropdown could never display (or let you pick) the other `.gguf` models on disk.

### Change (gui/dual_brain_control.py)
- New `_discover_gguf_models()` scans `D:\LMStudio\models` + `D:\llama.cpp` (env-overridable
  `GGUF_MODELS_DIR`) for every standalone `.gguf` (skips `mmproj-*` vision-projector files).
- `_repopulate_model_combo(small, loaded_path)` fills a brain's dropdown with ALL discovered
  models — display text = model filename, full `.gguf` path stored per-item (Qt UserRole) — and
  auto-selects the currently-loaded model when the server is up (keeps prior selection otherwise).
- Refresh handlers + the periodic provider-status probe now use it, so both dropdowns list every
  local model whether the brain is running or stopped.
- New `_force_stop_brain(small)` and `_restart_brain_with(small, path)`; the model-changed
  handlers now AUTO-RESTART a running brain with the newly selected model (stop + wait for port
  free + relaunch), instead of only logging.
- Start handlers resolve the model via `_current_model_path()` (full path from item data) since
  the combo text is now a friendly filename, not a raw path.

### Verification
- Headless: discovery returns 11 standalone `.gguf` on D: (16 files minus 5 mmproj); both
  dropdowns list 11 models; filename shown with full path stored; loaded path auto-selected.
- Live: with both servers up, Small dropdown selects `Qwen3-4B...Q6_K.gguf`, Big selects
  `Qwen3.8-27B...Q4_K_M.gguf`, while all 11 local models are visible in each.

## [2.0.36p] - 2026-09-06 - Fix llama.cpp not working: wrong binary + numeric --device flag

### Root cause (why "llama.cpp not working" persisted after 2.0.36o)
Two independent faults in the dual-brain Start path, both now fixed:

1. **Wrong binary.** The app launched `llama.exe` (WindowsApps, MSVC 0.3.0 build) which has
   **NO CUDA kernel for sm_75 (GTX 1660 Super)** → `--device CUDA1` crashed with
   `CUDA error: no kernel image is available for execution on the device`. Only the RTX 5060 Ti
   (sm_120) worked. The Clang 0.4.0 build at `D:\llama.cpp\llama-server.exe` ships kernels for
   **both** GPUs and is verified working on the 1660 Super.
2. **Numeric `--device` flag.** This llama.cpp line rejects numeric indices
   (`--device 1` → `invalid device: 1`; even `--device 0` failed). It requires device NAMES
   (`CUDA0`/`CUDA1`). So even the 5060 Ti would have failed with the app's `--device 0`.

### Fix
- `agents/dual_brain_runtime.py::build_llama_command`: launch `D:\llama.cpp\llama-server.exe`
  (overridable via `BIG/SMALL_BRAIN_SERVER` or global `LLAMA_SERVER_BIN`) and pass the device by
  NAME `CUDA{device}` (`CUDA0` big / `CUDA1` small). `BrainConfig` gains `_env_prefix`.
- `scripts/start_big_brain.ps1` / `start_small_brain.ps1`: same — use the Clang build, `--device
  CUDA0/CUDA1`, `--n-gpu-layers all` (they used `llama.exe ... --device 1/0` before).

### Verification (REAL end-to-end)
- `llama-server.exe --device CUDA1 :1235` with Qwen3-4B loads, listens, and pins **GPU 1 (1660 S)
  at 4.1 GB / 20% util** with GPU 0 (5060 Ti) idle → correct GPU isolation.
- `llama-server.exe --device CUDA0 :1234` loads + listens on the 5060 Ti.
- App-generated command strings verified: `D:\llama.cpp\llama-server.exe ... --device CUDA1 ...`.

## [2.0.36o] - 2026-09-06 - Fix llama.cpp Start launching placeholder as --model + runtime-driven port wiring

### Fix (v2.0.36o): Start buttons passed the offline placeholder as `--model`
- `gui/dual_brain_control.py`: when a llama-server refresh failed, the model combo held
  `"⚠️ llama-server offline — press ▶ Start"`. Pressing Start read `combo.currentText()` and passed
  that placeholder string as `--model` → the launched llama-server failed to load and never listened,
  so status stayed "offline" even though the operator's own llama.cpp was loaded. Now Start resolves a
  REAL model path via new `_resolve_model_path()`: combo text (if a real model) → `BIG/SMALL_BRAIN_MODEL`
  env → the start-script `.gguf` default. If none exists it aborts with a clear log instead of launching
  garbage. Launch log now includes the resolved model path.
- `_resolve_model_path` guards against placeholder markers (`⚠️`, `Error`, `No models found`).

### Fix (v2.0.36o): port/endpoint wiring is runtime-driven (not hardcoded 1234/1235)
- The refresh / status-probe / start / stop handlers now resolve the brain's port and `/v1/models`
  URL from `DualBrainRuntime` / `.env` (`_brain_port`, `_brain_models_url`) instead of hardcoding
  1234/1235. If the operator points `.env` at a different endpoint (e.g. an existing llama.cpp on
  8080), the panel probes and launches against the configured port.

### Note: restart required
The `NameError: name 'os' is not defined` traceback is from a STALE process running pre-fix code —
the current file has `import os` and different line numbers. Fully quit and relaunch the app.

Verification: 5/5 model-resolution ad-hoc PASS (placeholder→real .gguf for both brains, real-combo
preference, build_llama_command uses resolved path, no placeholder leaked); compile clean.

## [2.0.36n] - 2026-09-06 - WorkerAgent fully restored, llama.cpp offline-refresh fix, per-brain llama.cpp customization

### Fix (v2.0.36n): WorkerAgent fully restored + verified
- `agents/base_worker.py` — `WorkerAgent` confirmed complete: 23 methods + all module-level
  symbols (`WORKER_REGISTRY`, `project_file_tree`, `PROTECTED_SOURCE_FILES`, `_normalize_keep_alive`,
  `num_gpu_for`, `context_tokens`, `_active_worker`). Whole-repo import sweep clean (1 benign
  `providers.base` namespace false-positive); 15 `test_dual_brain_runtime` pass; `LlamaCppAdapter` present.

### Fix (v2.0.36n): llama.cpp connection-error log spam (WinError 10061)
- `gui/dual_brain_control.py::_refresh_small/big_brain_models`: when a llama-server is down,
  the old code added `"Error: <urlopen error [WinError 10061]…>"` as a combo item → `currentTextChanged`
  fired the model-changed handler with that junk, producing the "🔄 Small Brain model changed to:
  Error: …" spam. Now combo mutations are wrapped in `blockSignals`, and a down server shows a
  friendly `⚠️ llama-server offline — press ▶ Start` placeholder and logs only `type(e).__name__`.
- `_on_small/big_brain_model_changed` guard against `⚠️`/`Error` placeholder items (never treated as a model).

### Feature (v2.0.36n): per-brain llama.cpp customization on the Providers & GPU tab
- `agents/dual_brain_runtime.py`: `BrainConfig` + `build_config` + `ROLE_DEFAULTS` extended with
  `kv_cache` (f16/f32/q8_0/q4_0/auto), `split_mode` (none/layer/row), `threads`, `batch`. New
  `BrainConfig.build_llama_command(model_path)` is the single source of truth for llama-server
  launch args. Env keys: `BIG/SMALL_BRAIN_KV_CACHE`, `*_SPLIT_MODE`, `*_THREADS`, `*_BATCH`, `*_GPU_LAYERS`.
- `gui/dual_brain_control.py`: new per-brain `*_gpu_layers_spin`, `*_split_combo`, `*_threads_spin`,
  `*_kv_combo`, `*_batch_spin` seeded from runtime/env; Start handlers now call
  `build_llama_command` (also fixes a latent `AttributeError`: `sb/bb_threads_spin` were referenced
  but never defined). New **💾 Save llama.cpp Settings** button → `_persist_settings()` writes to `.env`.
- `main.py::save_settings`: persists the dual-brain llama.cpp keys defensively via `getattr` from the
  (lazily-built) Providers & GPU tab, so the Settings Save captures them without crashing.

Verification: compile clean; 6/6 dual-brain ad-hoc PASS (build_llama_command BIG/SMALL, construct +
all widgets, runtime seeding, offline refresh friendly placeholder, _persist_settings writes all keys).

## [2.0.36m] - 2026-09-06 - Tab-switch freeze fix, Settings provider layout, role-aware provider routing (llama.cpp)

### Perf (v2.0.36m): tab-switch freeze fixed
- `gui/tab_builders.py`: the Settings builder called `self.worker._ollama_model_names()` twice -
  a LIVE HTTP call to Ollama on the GUI thread. Removed; the dropdowns seed from static
  names and are live-populated by the existing `populate_ollama_model_combos` autorefresh.
- `gui/dual_brain_control.py`: provider-status refresh (`check_llama_server`) now runs on a
  background thread and applies via a `provider_probed` Qt signal, so the Providers & GPU
  tab no longer blocks on HTTP to the llama-server ports.

### Fix (v2.0.36m): Settings Cloud Providers layout + OpenAI/Anthropic collapsible
- The Cloud/Local provider sections switched from QFormLayout to QVBoxLayout (the previous
  QFormLayout pushed the collapsible boxes right / left whitespace next to OpenAI/Anthropic).
- OpenAI and Anthropic now use the same collapsible `_prov_row` box as every other provider:
  they can be Hidden-when-disabled and collapsed. Their self.* attribute names are unchanged
  so save_settings/test_api_connection still work.
- `main.py save_settings`: persists `OPENAI_HIDE` / `ANTHROPIC_HIDE` (and seeds them on load).

### Feature (v2.0.36m): provider routing is enabled-only and role-aware (llama.cpp primary)
The backend now only attempts providers that are ENABLED for the requested role, and treats
the dual-brain llama.cpp servers as the local provider instead of always falling to Ollama.
- `agents/providers/openai_compatible.py`: new `LlamaCppAdapter` (no API key required;
  honors `<PREFIX>_ENABLED` and `DISABLE_<PREFIX>`). `_is_safe_base_url` now allows
  loopback/private RFC1918 addresses (local llama.cpp/LM Studio/vLLM/KoboldCpp) while still
  blocking link-local metadata (169.254.169.254). Previously the SSRF guard rejected 127.0.0.1,
  so the only local provider that ever worked was Ollama - the root of "ollama is still called".
- `agents/base_worker.py`: `_build_provider_registry` registers `big-brain` (llama-server :1234)
  and `small-brain` (:1235) from `DualBrainRuntime.from_env()` when enabled+endpoint+model.
  `_role_allows` defaults big-brain→main, small-brain→chat. `_build_providers` treats them as
  free-local so they sort before Ollama. Disabled / no-key / missing-model providers are skipped.
- `gui/dual_brain_control.py`: new "Route" label shows which provider serves main vs chat and
  flags broken GPU isolation (via `DualBrainRuntime.validate_isolation`) so the operator can
  disable a provider or split main/chat across GPUs.

### Note (v2.0.36m): agents/base_worker.py restored from last commit
An over-broad scripted edit corrupted `base_worker.py` (removed the WorkerAgent class). It was
restored from `git HEAD` and the three intended routing changes above were re-applied cleanly.

Verification: compile clean; 94/94 modules import; 15 tabs build headless; routing ad-hoc 10/10
(big-brain→main first, small-brain→chat first, ollama excluded when disabled, llama.cpp before
Ollama when both enabled, no-key/disabled cloud excluded, loopback allowed/metadata blocked);
100 tests pass (section_c/d/e, nvidia_nim, dual_brain_runtime, safe_mode, runtime_shutdown/
warnings, manager_queue).

## [2.0.36l] - 2026-09-06 - Settings overhaul, GUI performance, 2.5D/2D button styles

### Fix (v2.0.36l): "Hide when disabled" no longer traps a provider
Collapsing a disabled provider used to hide the whole QGroupBox, including the very
"Hide when disabled" checkbox that controlled it - once collapsed, the provider was
unreachable. Each provider box now has an ALWAYS-visible header (title + hide checkbox +
collapse button) and only the body collapses. The provider can always be brought back.
- `gui/tab_builders.py`: `_prov_row` and the Ollama box restructured to header/body;
  `_refresh`/`_ollama_refresh` keep the header reachable, body collapses on disabled+hide.

### Fix (v2.0.36l): selections are remembered across restarts
- `gui/tab_builders.py`: theme combo seeded from `MRBOT_THEME`; FX toggles seeded from
  `MRBOT_FX_*`; per-provider "Hide when disabled" seeded from `{PREFIX}_HIDE`.
- `main.py save_settings`: persists `MRBOT_THEME`, `MRBOT_FX_BUTTON_STYLE`, and
  `{PREFIX}_HIDE` for every collapsible provider (Ollama, OpenRouter, Gemini, Groq,
  DeepSeek, Mistral, Together, NVIDIA, vLLM, LM Studio, KoboldCpp).

### Feature (v2.0.36l): 2.5D vs 2D button visual style
- `effects.py`: new `EffectSettings.button_style` (`2.5D (beveled)` | `2D (flat)`),
  read/written via `MRBOT_FX_BUTTON_STYLE`. 2.5D emits a vertical gradient + accent
  bottom edge for a raised/beveled look; 2D is flat. Pairs with the existing Soft shadows
  toggle for depth. Performance mode forces 2D flat.
- `gui/tab_builders.py`: "Button style" combo added to the Appearance group.

### Fix (v2.0.36l): python console windows no longer pop on tool calls / restart
- `agents/tools.py`: Big Brain `run_command` subprocess now passes
  `creationflags=CREATE_NO_WINDOW` (was shell=True with no flags -> cmd.exe console flash).
- `main.py restart_app`: replaced `os.execv` (which relaunched under a visible console)
  with a detached, no-console `Popen` + quit.

### Fix (v2.0.36l): empty Agents tab
- `gui/tab_builders.py`: `create_agents_tab` was only the sprite stub and returned None,
  so the Agents tab rendered blank. It now delegates to the full
  `create_agents_tab_original` (chat + roster).

### Perf (v2.0.36l): background polling pauses on hidden tabs
- `gui/tab_builders.py`: `_on_tab_changed` now calls `_sync_background_tabs`, pausing the
  previous tab's pollers and resuming the shown one.
- `gui/safety_tools_tab.py`: `pause_background`/`resume_background` stop/start the 2s
  refresh timer.
- `gui/dual_brain_control.py`: `pause_background`/`resume_background` stop/start the
  2s nvidia-smi GPU worker.

Verification: `python -m compileall` clean; 94/94 modules import; all 15 tabs build
headless; 73 passed (section_c/d/e, safe_mode, runtime_shutdown/warnings, manager_queue);
GUI smoke EFFECTS + SETTINGS + SAVE_SETTINGS pass.



## [2.1.0] - 2026-09-06 - Dual-Brain Runtime, Cross-Model Collaboration, Durable Autonomous Runs & Paper-Gated Earning

MrBot1000 v2.1 consolidates the dual-brain architecture into one authoritative, deterministic core. Phase 0–5 delivered (all verified: full `pytest` green, 580 passed, exit 0).

### Phase 1 — Canonical dual-brain runtime (`agents/dual_brain_runtime.py` NEW)
- `BrainRole` (`BIG`/`SMALL`), `BrainConfig`, `DualBrainRuntime`: single source of truth for role→endpoint/model/device/port/context.
- Canonical contract: Big Brain → RTX 5060 Ti (CUDA 0, port 1234), Small Brain → GTX 1660 Super (CUDA 1, port 1235), llama.cpp/llama-server default (Ollama/LM Studio explicit opt-in).
- `validate_isolation()`, bounded health probes (never raise → offline), `list_models`, `set_model` (per-role, thread-safe), `snapshot()`.
- Wired into `BigBrainAdapter` / `SmallBrainAdapter` defaults.
- Tests: `tests/test_dual_brain_runtime.py` (15).

### Phase 2 — Canonical cross-model collaboration
- `agents/comms.py`: added `PLAN_/RESEARCH_/REVIEW_/EXECUTION_REQUEST|RESULT` + `AUTONOMOUS_RUN_UPDATE` message types (request/result typed → bus loop-prevention/dedup applies).
- `agents/dual_brain_coordinator.py` (NEW): deterministic typed plan→research→review→execute handoff on the EventBus, durable MessageLog ledger, `model_fn` injected (mock-first, cycle-safe); failed stage stops the run.
- `gui/collaboration_tab.py` (NEW): Collaboration / Run Monitor tab (now 15 tabs), background-thread "Run Collaboration", shared coordinator/runtime.
- Tests: `tests/test_dual_brain_coordinator.py` (9).

### Phase 3 — Durable autonomous runs + unified composition root
- `agents/autonomous_run_store.py` (NEW): SQLite `autonomous_runs` / `autonomous_stage_runs` / `idempotency_keys`, restart-safe `recover_incomplete()`.
- `AutonomousLoop` now persists every finished run + stages + an `opportunity:<id>` idempotency key.
- `agents/composition_root.py` (NEW): `build_composition_root()` builds ONE shared pipeline/portfolio/run_store/lifecycle per process; `main.py` uses it.
- Tests: `tests/test_autonomous_run_store.py` (8).

### Phase 4 — First real paper/human-gated earning capability
- `agents/earning_capability.py` (NEW): `EarningCapabilityExecutor` — research→evaluate→TaskWorkspace deliverable→deterministic validation→human gates→local submission package→submission evidence (L1, NOT payment). Revenue never fabricated; payment/contract/identity/etc. tasks stop at AWAITING_APPROVAL.
- `agents/task_workspace.py`: fixed latent custom-`root_folder` "escapes root" bug (validated against its own root).
- Tests: `tests/test_earning_capability.py` (8).

### Phase 5 — GUI consolidation + config/docs
- `gui/dual_brain_control.py` / `gui/tab_builders.py`: Providers & GPU panel now shares the canonical `DualBrainRuntime` (ctx spins + port labels seeded from it).
- Resolved config contradiction: `.env` / `.env.example` aligned to canonical ports (Small 1235, Big 1234) with explicit `BIG_BRAIN_*`/`SMALL_BRAIN_*` keys.
- Documentation rewritten: `CURRENT_STATE.md`, `README.md`, `ARCHITECTURE.md`, `Agent.md`.

Verified: full `pytest` suite green (580 passed, 8 warnings, exit 0). Compile/import sweeps clean; headless GUI smoke passes (15 tabs). Each phase's ad-hoc verification recorded under `.hermes/test-results/phaseN-2026-09-06.md`.

## [2.0.36j] - 2026-08-18 - Unified Economic Accounting & Self-Audit Layer

A single, honest accounting layer for all opportunity types, plus a self-audit engine that identifies improvement opportunities without modifying safety constraints.

- `agents/economic_accounting.py` (NEW): `ExpenseCategory` enum (PLATFORM_FEE, TRANSACTION_FEE, GAS, LLM_COST, API_COST, TOOL_COST, OTHER). `EconomicProfile` dataclass (advertised/expected/realized/verified/unverified/pending revenue, expenses by category, realized_net, roi, net_hourly_rate, prediction accuracy). `EconomicAccounting` class (pure compute over EvidenceStore; revenue only from VERIFIED payment evidence; USD + crypto conversion; aggregate portfolio metrics).
- `agents/self_audit.py` (NEW): `AuditCategory` enum (14 categories: repeated_failures, prediction_errors, bad_strategies, poor_platforms, poor_categories, poor_task_types, low_performing_variants, high_cost_workflows, human_intervention, execution_failures, stale_providers, stale_categories, security_problems, documentation_drift). `Severity` enum. `AuditFinding` dataclass (observation/evidence/confidence/recommended_change/expected_benefit/expected_risk/affected_components/test_requirements). `AuditReport`. `SelfAuditEngine` (analyzes memory+evidence_store+accounting; produces structured findings; no mutations to security policy).
- `earning_pipeline.py`: `EarningPipeline` creates both `EconomicAccounting` and `SelfAuditEngine`. The pipeline report uses the accounting layer for verified/unverified revenue, expenses, net profit, ROI, net hourly rate, and expenses by category.
- `tests/test_economic_accounting.py` (NEW, 31 tests): USD, crypto (ETH/BTC), platform fees, gas, LLM costs, zero revenue, partial payments, failed payments, disputed payments, duplicate payments, verified/unverified revenue, negative-profit opportunities, ROI, net hourly rate, prediction accuracy, aggregate metrics.
- `tests/test_self_audit.py` (NEW, 16 tests): all 14 audit categories, empty memory, below-threshold negative case.
- `tests/__main__.py`: registered `economic_accounting` and `self_audit` categories.

Verified: 31 + 16 new + 150 prior = 197-test canonical subset green.
Security: Revenue is realized ONLY when appropriate VERIFIED payment evidence exists. Advertised payment, successful submission, and generated deliverables are NOT revenue. Self-audit engine does NOT modify security policies, approval requirements, TrustBoundary, or execute code changes. Human GUI refactor untouched.

## [2.0.36j] - 2026-08-18 - Unified Economic Accounting Layer

A single, honest accounting layer for all opportunity types. Distinguishes advertised value, expected value, realized gross revenue, realized expenses, realized net profit, verified revenue, and unverified revenue.

- `agents/economic_accounting.py` (NEW): `ExpenseCategory` enum (PLATFORM_FEE, TRANSACTION_FEE, GAS, LLM_COST, API_COST, TOOL_COST, OTHER). `EconomicProfile` dataclass (advertised/expected/realized/verified/unverified/pending revenue, expenses by category, realized_net, roi, net_hourly_rate, prediction accuracy). `EconomicAccounting` class (pure compute over EvidenceStore; revenue only from VERIFIED payment evidence; USD + crypto conversion; aggregate portfolio metrics).
- `earning_pipeline.py`: `EarningPipeline` creates an `EconomicAccounting` wired to the EvidenceStore. The pipeline report uses the accounting layer for verified/unverified revenue, expenses, net profit, ROI, net hourly rate, and expenses by category.
- `agents/opportunity_lifecycle.py`: `mark_final_outcome` passes revenue/cost/effort_hours through to the learning loop.
- `tests/test_economic_accounting.py` (NEW, 31 tests): USD, crypto (ETH/BTC), platform fees, gas, LLM costs, zero revenue, partial payments, failed payments, disputed payments, duplicate payments, verified/unverified revenue, negative-profit opportunities, ROI, net hourly rate, prediction accuracy, aggregate metrics.
- `tests/__main__.py`: registered `economic_accounting` category.

Verified: 31 new + 150 prior = 181-test canonical subset green.
Security: Revenue is realized ONLY when appropriate VERIFIED payment evidence exists. Advertised payment, successful submission, and generated deliverables are NOT revenue. Human GUI refactor untouched.

## [2.0.36i] - 2026-08-18 - Generalized Task Execution Framework

MrBot1000 expands from "coding worker" toward generalized task execution with a 14-step pipeline, task-specific deterministic validators, and human-in-the-loop gates.

- `agents/task_validators.py` (NEW): deterministic validators per the user's spec. `CodingValidator` (syntax/tests/diff), `WritingValidator` (length/requirements coverage/formatting), `ResearchValidator` (source count/citations/quality), `DataValidator` (schema/row counts/duplicates), `TranscriptionValidator` (format/timestamp integrity/completeness), `DocumentValidator` (required fields/formatting/coverage). `ValidationReport` records each check. `VALIDATOR_REGISTRY` maps task types → validators; `get_validator()` falls back to WritingValidator.
- `agents/human_gates.py` (NEW): `HumanGateManager` determines when human input is REQUIRED (never bypasses). Eight gate categories: identity verification, sensitive information, contracts, payments, signatures, captchas, irreversible actions, platform-specific manual interaction. `clear_gate` records human clearance; `get_pending_gates` lists uncleared gates.
- `agents/task_executor.py` (NEW): `TaskExecutor` drives the 14-step pipeline: inspect requirements → identify capabilities/tools → determine feasibility → create plan → identify human actions → execute → validate → prepare deliverables → submit → wait → verify → record evidence → learn. `ExecutionContext` tracks state; `ExecutionPlan`/`ExecutionResult` dataclasses. Pipeline stops at human gates (AWAITING_APPROVAL), fails on validation failure.
- `earning_pipeline.py`: `EarningPipeline` creates a `TaskExecutor` wired to the portfolio, capability validator, and human gate manager.
- `tests/test_task_execution.py` (NEW, 34 tests): validators (all 6 pass + fail cases), human gates (all 8 categories + clearance flow), executor (full 14-step pipeline, human gate stop, validation failure, not executable, context audit).
- `tests/__main__.py`: registered `task_execution` category.

Verified: 34 new + 116 prior = 150-test canonical subset green.
Security: deterministic validators only — the LLM never decides completion. Human gates are hard stops that cannot be bypassed. User GUI refactor untouched.

## [2.0.36h] - 2026-08-17 - Opportunity Portfolio & Work Queue

MrBot1000 can now discover many opportunities simultaneously but only act on a sensible subset — prioritized by a configurable policy and bounded by hard overcommit limits.

- `agents/opportunity_portfolio.py` (NEW): `WorkStatus` enum (16 states: NEW, EVALUATING, QUALIFIED, RECOMMENDED, AWAITING_APPROVAL, READY, IN_PROGRESS, BLOCKED, WAITING_EXTERNAL, COMPLETED, PAYMENT_PENDING, PAID, FAILED, REJECTED, EXPIRED, ABANDONED), `PortfolioEntry` dataclass (priority, expected_value, expected_hourly_value, deadline, confidence, risk, effort, next_action, waiting_reason, evidence_status, payment_status, skill_fit, policy_score, lifecycle_stage mirror), `OpportunityPortfolio` (sqlite-backed persistence, add/get/update/remove/list_work/count_by_status/load_all, transition_work_status validating against VALID_WORK_TRANSITIONS then delegating lifecycle-affecting moves to the lifecycle tracker via BFS path-walk over _ALLOWED_TRANSITIONS), `WorkStatusConfig` (WORK_TO_LIFECYCLE map + valid transitions), `QueuePolicy` (configurable weights: w_expected_hourly, w_confidence, w_risk, w_skill_fit, w_deadline_urgency, w_effort, w_priority_override + pluggable scorer callable so the formula is NOT hardcoded), `CapacityConfig` (max_active_tasks, max_pending_applications, max_simultaneous, max_high_risk, max_financial_exposure, per-platform limits), `WorkQueue` (prioritized selection with select_next walking the queue and skipping entries exceeding capacity — only as many as capacity allows), resolve_next_action (deterministic action/reason per status), apply_next (advances through the chain NEW to PAID).
- `earning_pipeline.py`: EarningPipeline.__init__ gains optional portfolio= kwarg (back-compat: works with None); evaluate() syncs EV, confidence, skill_fit, risk, effort from the intelligence verdict to the portfolio via _sync_to_portfolio.
- `tests/test_opportunity_portfolio.py` (NEW, 25 tests): persistence + restart recovery, state machine (lifecycle authoritative, blocked preserves stage, full valid chain), policy (user example winner>r loser, configurable weights, custom scorer), capacity (active tasks, high risk, financial exposure), next_action (all statuses, blocked/waiting reasons, apply_next chain), pipeline sync.
- `tests/__main__.py`: registered opportunity_portfolio category.

Verified: 116-test canonical subset green (25 portfolio + 91 prior).
Security: deterministic; the LLM never performs an external action. Recording/sync is from deterministic verdict fields. User GUI refactor untouched.