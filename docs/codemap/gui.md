<!-- generated 34 files -->

### `gui/tabs/__init__.py` — tabs package. (2L)


### `gui/tabs/analytics_tab.py` — gui/analytics_tab.py — Analytics tab for market data and strategy performance. (217L)

**Classes:**
- `class AnalyticsTab(QWidget)` (L19) — Analytics tab — market data and strategy performance.
  - `__init__(parent: Optional[QWidget]=None)` (L22)
  - `_setup_ui()` (L30)
  - `_auto_refresh()` (L119) — Auto-refresh market data (best-effort, no error popup).
  - `cleanup()` (L126) — Stop periodic refresh before the main window is torn down.
  - `_on_refresh_crypto_price()` (L131) — Refresh crypto price on button click.
  - `_fetch_price(symbol: str)` (L143) — Fetch crypto price from CoinGecko (free, no API key).
  - `_on_run_backtest()` (L172) — Run the built-in strategies against recent public market history.


### `gui/tabs/chat_tab.py` — Chat Tab — Human ↔ Small Brain chat. (424L)
> v2.1.63 teardown: cleanup() disconnects worker/escalation signals.

**Classes:**
- `class ThinkingBox(QFrame)` (L22) — Collapsible thinking box with toggle button.
  - `__init__(thinking_text: str, title: str='🧠 Thinking', color: str='#bb86fc', parent=None)` (L25)
  - `setup_ui(title: str)` (L32)
  - `toggle()` (L88) — Toggle thinking visibility.
- `class ChatTab(QWidget)` (L95) — Full conversation between human and Small Brain.
  - `__init__(small_brain, big_brain, parent=None)` (L103)
  - `setup_ui()` (L112)
  - `_toggle_thinking_global()` (L193) — Toggle thinking display globally.
  - `parse_thinking(response: str) -> tuple` (L203) — Parse thinking content from model response.
  - `on_send()` (L235) — Handle send button.
  - `_on_small_brain_response(response: str)` (L251) — Handle Small Brain response (runs in GUI thread).
  - `_start_escalation(user_msg: str)` (L291) — Run Big Brain escalation + re-summary on a background thread so the GUI
  - `_on_big_brain_answer(bb_clean: str)` (L305) — Show the Edward Hurst answer once it returns (GUI thread).
  - `_on_escalation_summary(summary: str)` (L310) — Append the Jacob Stanley re-summary (GUI thread).
  - `_on_escalation_failed(error: str)` (L314) — Surface an escalation error without freezing (GUI thread).
  - `append_message(sender, message, color)` (L318) — Append a message to the chat display.
  - `cleanup()` (L324) — Stop chat background workers before this tab is destroyed.
- `class InferenceWorker(QThread)` (L363) — Background worker for running LLM inference without blocking GUI.
  - `__init__(small_brain, user_msg, history)` (L368)
  - `run()` (L375) — Run inference in background thread.
- `class EscalationWorker(QThread)` (L384) — Background worker for Big Brain escalation + re-summary.
  - `__init__(small_brain, big_brain, user_msg, history)` (L396)
  - `run()` (L406)


### `gui/tabs/collaboration_tab.py` — gui/collaboration_tab.py — Collaboration / Run Monitor (v2.1). (184L)

**Functions:**
- `_fmt_ms(ms: int) -> str` (L24)

**Classes:**
- `class CollaborationWorker(QThread)` (L28) — Run a collaboration goal off the GUI thread via the coordinator.
  - `__init__(coordinator, goal)` (L32)
  - `run()` (L37)
- `class CollaborationTab(QWidget)` (L45) — Monitor + manual trigger for the dual-brain collaboration coordinator.
  - `__init__(coordinator, parent=None)` (L54)
  - `setup_ui()` (L63)
  - `showEvent(event)` (L119)
  - `hideEvent(event)` (L124)
  - `_run_collaboration()` (L129)
  - `_on_run_done(_payload)` (L140)
  - `refresh()` (L145)
  - `_show_selected_detail()` (L162)


### `gui/tabs/dialogue_tab.py` — gui/dialogue_tab.py — Persona-driven goal dialogue (v2.1). (3300L)
> Phase F rate limit + social autopost; v2.1.63 cleanup().

**Functions:**
- `_decision_signature(text)` (L49) — Compact normalized semantic signature of a persona turn.
- `_is_silent_quirk_persona(speaker)` (L59) — Legacy no-op kept so __new__ stubs built in tests can call

**Classes:**
- `class DialogueTab(QWidget)` (L158) — Goal-driven conversation between the Driver and Navigator personas.
  - `__init__(small_brain, big_brain, parent=None)` (L164)
  - `_build_speakers()` (L238) — Build the N-brain speaker roster from runtime slots (Phase 2).
  - `_speaker_for(name: str)` (L278) — Return the Speaker whose display name matches ``name`` (or None).
  - `_brain_for(speaker: str)` (L294) — Resolve the brain adapter for a speaker NAME (N-brain).
  - `_tier_for_speaker(speaker: str) -> str` (L324) — Return the prompt tier for a speaker NAME: 'full' (big) or 'compact'
  - `_speaker_display(spk) -> str` (L333) — Combo display text for a speaker: name + short device tag.
  - `_populate_speaker_combos()` (L345) — Fill speaker_combo (Human + every enabled brain) and reply_combo
  - `_combo_speaker_name(combo) -> str` (L374) — Resolve a combo's current selection to the actual speaker NAME.
  - `_update_dialogue_header()` (L388) — Header lists every enabled speaker (name · device) instead of the
  - `_next_speaker_after(speaker: str) -> str` (L403) — Return the NAME of the next speaker after ``speaker`` in roster order
  - `_sync_and_check_capabilities()` (L423) — Refresh model labels after construction without blocking first paint.
  - `_clean_model_response(text: str) -> str` (L431) — Strip a glued ' thinking' marker that some local models emit at the start of a reply.
  - `_dialogue_model_blocked(model_name: str)` (L442) — Return (blocked: bool, reason: str) for capacity/tuning gating.
  - `force_forward()` (L452) — Force the conversation forward if stuck in a loop.
  - `_check_model_capabilities()` (L465) — Check if models are capable for dialogue and select appropriate lifecycle.
  - `_show_model_warning(warnings)` (L491) — Render capability status without interrupting dialogue startup.
  - `_estimate_model_size(model_name: str) -> float` (L504) — Estimate model size from name (total params for MoE; word-boundary match).
  - `_brain_gpu_vram_gb(small: bool) -> float | None` (L533) — Return the GPU VRAM (GB) reachable by *small* brain, or None on any failure.
  - `_tier_for_brain(small: bool, model_name: str) -> str` (L551) — Single source of truth for a brain's prompt tier.
  - `_tier_label(tier: str) -> str` (L571)
  - `_model_output_contract(model_name: str, small: bool=False, tier: str | None=None) -> str` (L574) — Return the output contract for *model_name* at the given *tier*.
  - `_context_values(context: str) -> list[str]` (L621) — Return the distinct ``$``-denominated values present in *context*.
  - `_earning_operational_context() -> str` (L628) — Expose bounded, read-only earning state to both dialogue personas.
  - `_log_dialogue_turn(speaker: str, outcome: str, response_text: str) -> None` (L667) — Best-effort JSONL record of one dialogue turn.
  - `_append(sender, message)` (L696)
  - `_create_collapsible_panel(title: str, widget: QListWidget, button_text: str=None, button_callback=None) -> QWidget` (L721) — Create a collapsible panel with a toggle button.
  - `setup_ui()` (L772)
  - `set_goal(goal: str)` (L956) — Set the active goal (used by the Dialogue + Collaboration wiring).
  - `_apply_goal()` (L977)
  - `_next_phase() -> tuple` (L997) — Advance to the next lifecycle phase and return its tuple.
  - `_current_phase_speaker() -> str` (L1004) — The persona that should speak for the next autonomous turn.
  - `_phase_instruction() -> str` (L1030)
  - `on_send()` (L1037)
  - `_persist_dialogue_turn(speaker: str, message: str)` (L1062) — Persist a dialogue turn in the existing shared knowledge database.
  - `_response_rate_gate() -> bool` (L1089) — Enforce a minimum interval between continuous/live responses.
  - `respond(manual=False)` (L1118) — Generate a response from the current speaker on a background thread.
  - `_create_agent_runtime()` (L1246) — Create the authoritative event-driven runtime for the Live session.
  - `_start_live_opportunity()` (L1279) — Give one agent a speaking opportunity selected from runtime state.
  - `_record_live_failure(reason: str) -> bool` (L1324) — Keep Live recoverable after provider failures — but not forever.
  - `_capture_action_proposal(speaker: str, response: str) -> None` (L1363) — Parse a Driver `ACTION: … | PLATFORM: … | EXPECTED: …` line and route it.
  - `_resume_live_if_running()` (L1414) — Restart the Live scheduler if a recovery path left it idle.
  - `_schedule_live_continuation(delay: int, fallback) -> None` (L1429) — Schedule the Live scheduler, keeping manual/step retries unchanged.
  - `_on_response_ready(response: str, speaker: str, generation: int=None)` (L1436)
  - `auto_step()` (L1788) — Run a bounded number of persona turns through the lifecycle.
  - `live()` (L1802) — Run event-driven Edward/Jacob dialogue until stopped.
  - `stop_live()` (L1831) — Stop continuous live mode and return the Live button to idle text.
  - `cleanup()` (L1864) — Stop all dialogue background work before this tab is destroyed.
  - `_on_dialogue_progress(batches)` (L1897) — Throttled GUI update for streamed dialogue progress.
  - `on_model_changed(role: str='')` (L1920) — Stop the active generation before adapters switch model endpoints.
  - `_toggle_live()` (L1930)
  - `_attach_image()` (L1936) — Attach one image to the next persona turn (vision models).
  - `_vision_available() -> bool` (L1952) — Whether the current speaker's model can accept images.
  - `single_step()` (L1964) — Run exactly one persona turn.
  - `reset_dialogue()` (L1973) — Reset the conversation history and phase.
  - `_open_help()` (L1994) — Open the in-app feature help dialog.
  - `_add_task()` (L2003) — Add a task to the tasks list.
  - `_extract_tasks_from_message(message: str)` (L2013) — Extract task items from a message and add them to the tasks list.
  - `get_dialogue_context(silent=False) -> str` (L2026) — Build a bounded dialogue prompt that enforces the read-on...[truncated]
  - `append_system(text: str)` (L2270)
  - `_markdown_to_html(text: str) -> str` (L2276) — Convert markdown to HTML for display in QTextEdit.
  - `_show_thoughts()` (L2295) — Render the latest bounded thought graph for the current session.
  - `_record_dialogue_control_state(speaker: str, raw_response: str) -> bool` (L2376) — Append a control-state ledger entry and return whether the turn is terminal-blocked.
  - `_get_opportunity_context() -> str` (L2417) — Read-only snapshot of the current opportunity portfolio for prompt context.
  - `_build_opportunity_board(max_chars: int) -> str` (L2453) — Return the visible opportunity board, bounded to *max_chars*.
  - `_get_control_context() -> str` (L2517) — Build the control-state context string for the active turn.
  - `_on_tool_activity(speaker: str, tool_event: dict)` (L2538) — Record a verified tool event and render it separately from persona text.
- `class DialogueWorker(QThread)` (L2579) — Background worker for dialogue inference (persona-driven).
  - `__init__(brain, context, history, speaker, system_prompt=None, anti_, ...)` (L2586)
  - `_resolve_max_tokens(brain) -> int` (L2606) — Return the dialogue reply-token budget for *brain*.
  - `_dialogue_thinking_headroom(is_small: bool) -> int` (L2685) — Adjustable thinking-channel token reserve for a brain.
  - `_safe_fallback_response() -> str` (L2708) — Return a bounded, phase-aware fallback when retries are exhausted.
  - `cancel()` (L2727) — Request cancellation; the provider call remains non-blocking to Qt.
  - `_ensure_model_selected()` (L2731) — Resolve a loaded server model without touching the GUI thread.
  - `run()` (L2743)
  - `_is_repetitive(response: str) -> bool` (L2844) — Check if the response is repetitive or stuck.
  - `_is_bad_dialogue_response(response: str) -> bool` (L2870) — Reject model boilerplate, corruption, and unverified action narratives.


### `gui/tabs/earning_insights.py` — gui/earning_insights.py — Earning Insights dashboard panel (Phase 6). (459L)

**Classes:**
- `class EarningInsightsPanel(QWidget)` (L30) — Dashboard panel for the Earning tab / main window.
  - `__init__(parent: Optional[QWidget]=None)` (L36)
  - `_setup_ui()` (L68)
  - `_kpi_cell(label: str, value: str, color: str) -> QLabel` (L151)
  - `_build_metrics_grid(root: QVBoxLayout)` (L159)
  - `set_earnings(earned: float, pending: float, last30: float)` (L180)
  - `set_spend(spent: float, budget: float)` (L188)
  - `set_tier(tier: str)` (L203)
  - `set_tasks(active: int, pending_approvals: int)` (L213)
  - `set_heartbeat(running: bool)` (L219)
  - `set_outcomes(outcomes: List[Dict[str, Any]])` (L230)
  - `set_events(events: List[Dict[str, Any]])` (L261)
  - `set_safety_incidents(count: int)` (L285)
  - `set_approval_rate(total: int, successful: int)` (L295)
  - `set_reputation(score: float)` (L310)
  - `set_roi(roi: float)` (L322)
  - `set_uptime(hours: float)` (L333)
  - `_refresh()` (L344)
  - `_refresh_events()` (L347)
- `class TabAwareInsightsPanel(EarningInsightsPanel)` (L351) — Insights panel that pulls live data from the EarningTab / MainWindow.
  - `__init__(parent: Optional[QWidget]=None, earning_tab: Optional[Any]=, ...)` (L354)
  - `_refresh()` (L363)
  - `_refresh_events()` (L439)
  - `refresh_now()` (L454)


### `gui/tabs/earning_tab.py` — gui/earning_tab.py — Unified Earning tab integrating Paths 1-4. (561L)

**Classes:**
- `class EarningTab(QWidget)` (L31) — Unified Earning tab for Paths 1-4.
  - `__init__(parent=None)` (L39)
  - `showEvent(event)` (L59)
  - `hideEvent(event)` (L64)
  - `_init_backends()` (L69)
  - `setup_ui()` (L102)
  - `_build_path1_group() -> QGroupBox` (L174)
  - `_build_path2_group() -> QGroupBox` (L215)
  - `_build_path3_group() -> QGroupBox` (L249)
  - `_build_path4_group() -> QGroupBox` (L299)
  - `_on_freelance_search()` (L330)
  - `_on_draft_proposal()` (L356)
  - `_on_submit_proposal()` (L372)
  - `_on_find_gigs()` (L415)
  - `_on_accept_gig()` (L428)
  - `_on_submit_attempt()` (L440)
  - `_on_add_wallet()` (L453)
  - `_on_propose_payment()` (L469)
  - `_get_wallet_manager()` (L490)
  - `_on_run_autonomy()` (L496)
  - `_on_stop_autonomy()` (L503)
  - `_append_log(text: str)` (L508)
  - `refresh()` (L511)
  - `get_summary() -> dict` (L514) — Return summary dict for the Insights panel.
  - `_refresh_crypto_wallets()` (L550)


### `gui/tabs/management_tab.py` — gui/management_tab.py — Management Control Center for the dual-brain architecture. (381L)

**Classes:**
- `class ManagementTab(QWidget)` (L28) — Management Control Center — administrative-only edition.
  - `__init__(parent=None)` (L49)
  - `setup_ui()` (L56)
  - `_persist_persona_name(key: str, widget: QLineEdit)` (L296) — Persist a display name while retaining stable internal role keys.
  - `set_pipeline_status(status: str)` (L314) — Update the pipeline status label.
  - `add_outcome(text: str)` (L319) — Add an entry to the recent outcomes list.
  - `set_research_folder(folder: str)` (L326) — Update the research folder display.
  - `set_proposal_status(text: str)` (L331) — Update the proposal status label.
  - `add_proposal(text: str)` (L335) — Add an entry to the proposals list.
  - `set_pay_status(text: str)` (L339) — Update the payout status label.
  - `_on_review_proposal()` (L345)
  - `_on_submit_proposal()` (L354)
  - `_on_verify_paid()` (L363)
  - `_on_clear_cache()` (L373)


### `gui/tabs/model_library_tab.py` — Hugging Face GGUF model browser and installer. (507L)

**Functions:**
- `_format_rate(bytes_per_second: float) -> str` (L40)
- `_format_eta(seconds: float) -> str` (L48)

**Classes:**
- `class ModelSearchWorker(QThread)` (L61)
  - `__init__(query: str, page: int, limit: int, task: str='', library: str='', parent=None)` (L65)
  - `run()` (L69)
- `class ModelDetailWorker(QThread)` (L77)
  - `__init__(repo_id: str, parent=None)` (L81)
  - `run()` (L85)
- `class ModelDownloadWorker(QThread)` (L92)
  - `__init__(artifact: GGUFArtifact, destination: Path, pause_event, cancel_event, parent=None)` (L99)
  - `run()` (L106)
- `class ModelLibraryTab(QWidget)` (L120) — Search, inspect, filter, and install GGUF models without blocking Qt.
  - `__init__(parent=None)` (L125)
  - `_build_ui()` (L138)
  - `_set_status(text: str)` (L275)
  - `_search()` (L278)
  - `_list_models()` (L284) — Browse the Hugging Face catalog without requiring a text query.
  - `_run_search()` (L289)
  - `_search_finished(models)` (L302)
  - `_search_failed(message: str)` (L307)
  - `_apply_filters()` (L310)
  - `_show_model(row: int)` (L340)
  - `_detail_loaded(model)` (L354)
  - `_render_model(model)` (L364)
  - `_update_artifact_status()` (L390)
  - `_choose_location()` (L395)
  - `_provider_target_changed(index: int)` (L400)
  - `_download()` (L411)
  - `_download_progress(completed: int, total: int, speed: float=0.0)` (L446)
  - `_toggle_pause()` (L462)
  - `_cancel_download()` (L472)
  - `_finish_download()` (L476)
  - `_download_completed(path: str)` (L482)
  - `_download_failed(message: str)` (L490)
  - `_change_page(delta: int)` (L494)
  - `closeEvent(event)` (L500)


### `gui/tabs/payments_tab.py` — (no module docstring) (236L)

**Classes:**
- `class PaymentsTab(QWidget)` (L20) — Tab for managing wallets, payments, and escrow.
  - `__init__(parent=None)` (L26)
  - `showEvent(event)` (L37)
  - `hideEvent(event)` (L42)
  - `setup_ui()` (L46)
  - `refresh()` (L175) — Refresh displays.
  - `_refresh_wallets()` (L180) — Refresh wallets display.
  - `_refresh_transactions()` (L202) — Refresh transactions display.
  - `_on_add_wallet()` (L218) — Add a new wallet.


### `gui/tabs/safety_tools_tab.py` — (no module docstring) (606L)

**Classes:**
- `class SafetyTab(QWidget)` (L52) — Tab for viewing safety status, approvals, and configuration.
  - `__init__(parent=None)` (L58)
  - `showEvent(event)` (L76)
  - `hideEvent(event)` (L82)
  - `setup_ui()` (L87)
  - `_create_status_tab()` (L116)
  - `_create_approvals_tab()` (L216)
  - `_create_config_tab()` (L280)
  - `refresh()` (L384) — Refresh all displays.
  - `_refresh_layers()` (L389) — Refresh safety layers display.
  - `_refresh_approvals()` (L409) — Refresh pending approvals display.
  - `_on_approve()` (L482) — Approve selected action.
  - `_on_reject()` (L522) — Reject selected action.
  - `_route_decision(approval_id)` (L543) — Hand a freshly recorded approval to the app's decision handler.
  - `_on_save_config()` (L565) — Save safety configuration.
  - `_load_config()` (L588) — Load persisted safety settings without making startup fragile.
  - `cleanup()` (L602) — Stop the tab-owned refresh timer during application shutdown.


### `gui/builders/__init__.py` — builders package. (2L)


### `gui/builders/refresh_coordinator.py` — Shared refresh scheduling for GUI tabs. (79L)

**Functions:**
- `refresh_coordinator() -> RefreshCoordinator` (L70) — Return the GUI-thread coordinator singleton.

**Classes:**
- `class _Entry` (L18)
- `class RefreshCoordinator(QObject)` (L25) — One process-local timer with visibility-aware callback registration.
  - `__init__(parent: QObject | None=None) -> None` (L28)
  - `register(key: str, callback: Callable[[], None], interval_ms: int) -> None` (L35)
  - `unregister(key: str) -> None` (L42)
  - `set_visible(key: str, visible: bool) -> None` (L47)
  - `_refresh_due() -> None` (L56)
  - `_refresh_entry(key: str, entry: _Entry) -> None` (L62)


### `gui/builders/tab_builders.py` — (no module docstring) (58L)

**Classes:**
- `class TabBuildersMixin(TabLifecycleMixin, FeatureTabBuildersMixin)` (L54) — Compose tab lifecycle and feature-specific builders.


### `gui/builders/tab_feature_builders.py` — Feature-specific Qt tab builders. (3656L)

**Classes:**
- `class FeatureTabBuildersMixin` (L24)
  - `create_agents_tab()` (L25)
  - `create_chat_tab()` (L31) — Create the Chat tab (Human ↔ Small Brain).
  - `_bridge_chat_to_dialogue(user_msg: str, small_reply: str)` (L57) — Route a completed Chat-tab exchange into the Dialogue tab so it continues
  - `create_dialogue_tab()` (L70) — Create the Dialogue tab (Big Brain ↔ Small Brain).
  - `_bridge_goal_to_collaboration(goal: str)` (L114) — Mirror the Dialogue tab's goal into the Collaboration tab's goal box.
  - `_bridge_goal_to_dialogue(goal: str)` (L123) — Mirror the Collaboration tab's goal into the Dialogue tab.
  - `create_providers_gpu_tab()` (L132) — Create the unified Providers & GPU tab — single DualBrainControl interface
  - `create_model_library_tab()` (L184) — Create the HTTPS Hugging Face GGUF browser and installer.
  - `_refresh_installed_models(_path: str='')` (L192) — Refresh both local model selectors after a library download.
  - `create_safety_tools_tab()` (L215) — Create the Safety & Tools tab.
  - `create_collaboration_tab()` (L232) — Create the Collaboration / Run Monitor tab.
  - `create_agents_tab_original()` (L274)
  - `create_management_tab()` (L311) — Management Control Center — administrative-only edition.
  - `_attach_memory_stream_panel(management_tab)` (L333) — Keep useful legacy telemetry in Management without a separate tab.
  - `_on_management_review_proposal(job_id: str, job_desc: str, draft: str)` (L376) — Handle review proposal request from Management tab.
  - `_on_management_submit_proposal(job_id: str, job_desc: str, draft: str)` (L383) — Handle submit proposal request from Management tab.
  - `_on_management_verify_paid(opp_id: str, amount: str, wallet: str, ref: str)` (L390) — Handle verify paid request from Management tab.
  - `create_memory_stream_tab()` (L399) — v2.0.34ag (A3): 'Memory & Stream' tab — relocated from Management so the
  - `create_file_browser_tab()` (L468)
  - `create_payments_tab()` (L481) — Create the Payments tab — wallet management, transactions, and payouts.
  - `create_earnings_tab()` (L510) — Earnings dashboard + unified earning center (Paths 1-4).
  - `create_insights_tab()` (L523) — Earning Insights dashboard panel (Phase 6).
  - `create_approval_tab()` (L546) — Human-approval queue panel (Phase 6).
  - `create_registration_tab()` (L572) — Gated platform sign-up panel (Phase B).
  - `create_logs_tab()` (L590) — Live Logs tab with full information display including tokens/sec and trigger info.
  - `create_db_stats_tab()` (L686)
  - `create_diagnostics_tab()` (L832) — Backward-compat shim: build only the diagnostics sections.
  - `_create_feature_monitor(title: str, columns: list[str], refresh_fn)` (L892) — Build a read-only feature monitor with visibility-aware refresh.
  - `create_social_activity_tab()` (L930) — Show social activity and provide a gated discovery action.
  - `create_self_improvement_tab()` (L1100) — Show self-improvement learning history and pending code-patch proposals.
  - `create_autonomous_learning_tab()` (L1258) — Show autonomous run and stage progress from the durable run store.
  - `refresh_diagnostics()` (L1372) — Refresh sanitized health and reconciliation data without mutations.
  - `_stat_cell(label: str, value: str, color: str) -> QFrame` (L1468) — Build a bordered KPI card (QFrame) with a label and a value label.
  - `create_settings_tab()` (L1496)
  - `create_opportunities_tab()` (L2442) — Create the Opportunities tab — browse, search, and manage discovered opportunities.
  - `create_live_portfolio_tab()` (L2658) — Create the live portfolio status surface; no fake balance is shown.
  - `_configure_live_exchange(exchange: str)` (L2725)
  - `_on_live_exchange_changed(exchange: str)` (L2740)
  - `_refresh_live_portfolio()` (L2752)
  - `_on_live_portfolio_result(result: dict)` (L2769)
  - `create_paper_trading_tab()` (L2780) — Create the Strategy Simulator tab — virtual portfolio testing only.
  - `_on_scan_opportunities()` (L2973) — Scan for opportunities now.
  - `_drain_opportunity_scan()` (L3009) — Persist a bounded batch of discoveries and refresh progressively.
  - `_append_scanned_opportunity(entry)` (L3061) — Add one newly discovered row without rebuilding the whole table.
  - `_configure_opportunity_auto_scan(enabled: bool)` (L3099) — Start or stop the user-configured opportunity scan timer.
  - `_refresh_opportunities()` (L3112) — Refresh opportunities table.
  - `_is_hiring_request(ref)` (L3165) — Exclude posts where someone is seeking a worker rather than work.
  - `_portfolio_contains_duplicate(ref)` (L3174) — Catch the same listing when a source changes its external ID.
  - `_on_web_discovery_toggled(checked: bool)` (L3191) — Persist the web-discovery toggle to .env and update the gate label.
  - `_reset_opportunity_page(*_args)` (L3207)
  - `_previous_opportunity_page()` (L3211)
  - `_next_opportunity_page()` (L3215)
  - `_clear_opportunities()` (L3219)
  - `_on_research_opportunity()` (L3233) — Research selected opportunity.
  - `_on_apply_opportunity()` (L3249) — Apply to selected opportunity.
  - `_on_reject_opportunity()` (L3274) — Reject selected opportunity.
  - `_selected_opportunity_entry()` (L3294) — Return the portfolio entry represented by the selected table row.
  - `_selected_opportunity_entries()` (L3299) — Return portfolio entries represented by all selected table rows.
  - `_on_paper_order_type_changed(order_type: str)` (L3323) — Enable/disable price field based on order type.
  - `_on_place_paper_order()` (L3332) — Place a paper order.
  - `_on_generate_paper_report()` (L3354) — Generate paper trading report.
  - `_refresh_paper_trading()` (L3365) — Refresh paper trading display.
  - `create_analytics_tab()` (L3406) — Create the Analytics tab — market data and strategy performance.
  - `create_reputation_tab()` (L3414) — Create the Reputation tab — track agent reputation across platforms.
  - `create_data_explorer_tab()` (L3478) — Create the Data Explorer tab — web scraping and data extraction.
  - `_on_refresh_reputation()` (L3523) — Refresh reputation display.
  - `_on_scrape_url()` (L3564) — Scrape the entered URL.
  - `_on_scrape_finished(result: dict)` (L3580) — Render a completed scrape in the Data Explorer results pane.
  - `_on_provider_widget_changed(provider_name: str, action: str)` (L3606) — Handle provider configuration changes from the widget.


### `gui/builders/tab_lifecycle.py` — Reusable tab lifecycle and visibility-aware refresh behavior. (139L)

**Classes:**
- `class TabLifecycleMixin` (L6)
  - `_scroll_wrap(widget)` (L7) — v2.0.34ag (A1): ensure a tab's content is always scrollable so group
  - `_ensure_tab_built(index: int)` (L19) — v2.0.34ag (A5): build a tab's real content on first show, replacing the
  - `_on_tab_changed(index: int)` (L77)
  - `_find_bg_aware(w)` (L93)
  - `_sync_background_tabs(new_index: int)` (L111)


### `gui/builders/tab_workers.py` — Background workers used by feature tabs. (133L)

**Classes:**
- `class DataExplorerWorker(QThread)` (L6) — Run web scraping away from the GUI thread.
  - `__init__(url: str)` (L11)
  - `run()` (L15)
- `class LivePortfolioWorker(QThread)` (L24) — Read a live exchange account without blocking the Qt GUI thread.
  - `__init__(service)` (L29)
  - `run()` (L33)
- `class SocialDiscoveryWorker(QThread)` (L46) — Run the gated social discovery path without blocking the GUI.
  - `__init__(pipeline)` (L51)
  - `run()` (L55)
- `class MoltbookFeedWorker(QThread)` (L77) — Read the Moltbook feed off the GUI thread (Phase E, ARCH-ENG-088).
  - `__init__(sort: str='hot', limit: int=25)` (L88)
  - `run()` (L93)


### `gui/widgets/__init__.py` — widgets package. (2L)


### `gui/widgets/brain_control_row.py` — gui/widgets/brain_control_row.py — one brain's one-click-launch controls. (269L)
> Phase G: MTP checkbox greyed when model lacks MTP head (ARCH-ENG-093).

**Functions:**
- `_norm(p: str) -> str` (L263) — Normalize a path for comparison (backslashes, case).

**Classes:**
- `class BrainControlRow(QWidget)` (L48) — One brain's launch controls. Emits slot-keyed start/stop/model signals.
  - `__init__(slot: int, role: str, device_label: str='', parent: Optional[QWidget]=None)` (L57)
  - `set_models(paths, selected: str='')` (L138) — Fill the model dropdown with discovered .gguf paths.
  - `current_model() -> str` (L161) — Full path behind the dropdown's current item ("" if unselected).
  - `_emit_model_changed(_index)` (L166)
  - `_refresh_mtp_availability() -> None` (L171) — Enable the MTP checkbox only when the selected model supports it.
  - `_emit_mtp_changed(_state)` (L199)
  - `mtp_enabled() -> bool` (L202) — True only if the box is both enabled (model supports MTP) and checked.
  - `set_mtp(enabled: bool) -> None` (L206) — Programmatically set the MTP checkbox (after availability is known).
  - `set_device_label(label: str) -> None` (L215) — Update the header to show which device this brain runs on.
  - `set_status(text: str, color: str='#ffb300') -> None` (L223)
  - `set_model(model_name: str) -> None` (L227) — Select ``model_name`` (full path or basename) in the dropdown if
  - `set_running(running: bool) -> None` (L248) — Toggle button availability for the running/stopped state.
  - `bind(config) -> None` (L253) — Seed the row from a ``BrainConfig`` (role, device label, model).


### `gui/widgets/brain_settings_row.py` — gui/widgets/brain_settings_row.py — editable llama.cpp settings for one brain. (238L)
> Phase G tooltips on every advanced control (ARCH-ENG-094).

**Functions:**
- `_help(key: str) -> str` (L31)

**Classes:**
- `class BrainSettingsRow(QWidget)` (L60) — Editable llama.cpp settings for one brain slot. Emits slot-keyed changes.
  - `__init__(slot: int, role: str, device_label: str='', is_cpu: bool=Fa, ...)` (L65)
  - `_lbl(text: str) -> QLabel` (L172)
  - `bind(config) -> None` (L178) — Seed the controls from a ``BrainConfig`` (blocks signals during fill).
  - `apply_to(config) -> None` (L206) — Write the current control values back into a ``BrainConfig``.
  - `values() -> dict` (L222) — Current control values as a plain dict (for persistence).


### `gui/widgets/dual_brain_control.py` — (no module docstring) (3645L)
> Providers_GPU panel; Phase G '?' help button; v2.1.60 status liveness poller.

**Classes:**
- `class GPUStatusWorker(QThread)` (L121) — Background worker that polls GPU status.
  - `__init__(interval_ms=2000)` (L125)
  - `run()` (L130) — Poll GPU status every interval.
  - `stop()` (L141) — Request the polling loop to exit so shutdown can join the thread.
  - `_get_gpu_status()` (L146) — Get GPU status via nvidia-smi.
  - `stop()` (L171) — Stop the polling loop.
- `class _WheelEventFilter(QObject)` (L183) — Event filter that blocks wheel scroll on QComboBox while dropdown is closed.
  - `__init__(combo, parent=None)` (L190)
  - `eventFilter(obj, event)` (L194)
- `class _ModelLabelAdapter` (L201) — Legacy shim: lets the backend call ``sb_model_label.setText(name)``.
  - `__init__(row)` (L210)
  - `setText(name: str)` (L213)
  - `text() -> str` (L224)
- `class _NullWidget` (L232) — Null-object standing in for a disabled brain's legacy alias widgets.
  - `setText(*a, **k)` (L243)
  - `setStyleSheet(*a, **k)` (L246)
  - `setEnabled(*a, **k)` (L249)
  - `text(*a, **k)` (L252)
  - `isEnabled(*a, **k)` (L255)
- `class DualBrainControl(ProviderLifecycleBackend, QWidget)` (L265) — Control panel for dual-brain GPU orchestration.
  - `__init__(parent=None, runtime=None)` (L295)
  - `_start_provider_detection()` (L396) — Detect providers without blocking construction or tab painting.
  - `_on_provider_detection_ready(_providers)` (L421) — Apply background provider discovery results on the Qt thread.
  - `_update_gpu_subtitle()` (L434) — Render the GPU-count subtitle from the current detection cache.
  - `_build_provider_panels()` (L451) — Build provider-specific configuration panels with failover support.
  - `_create_provider_panel(name, provider, gpus)` (L474) — Create a configuration panel for a specific provider.
  - `_on_gpu_assignment_changed(provider_name, gpu_index)` (L546) — Handle GPU assignment change.
  - `_on_model_changed(provider_name, model_name)` (L551) — Handle model selection change.
  - `_on_context_changed(provider_name, context_size)` (L568) — Handle context size change.
  - `_wire_start_stop_buttons()` (L574) — Wire up start/stop buttons after class body is fully defined.
  - `_wire_refresh_buttons()` (L600) — Wire up refresh/model buttons after class body is fully defined.
  - `_apply_hardware_preset()` (L607) — Apply the selected preset to the chosen hardware target.
  - `_adapt_preset_for_hardware(values, gpu=None, cpu_only=False)` (L634) — Adapt a shared preset to device memory and supported KV types.
  - `_build_gpu_hardware_settings(parent_layout)` (L649) — Show hardware-specific options for every detected GPU.
  - `_apply_hardware_tensor_options()` (L726) — Limit KV choices to the assigned GPU's supported tensor profile.
  - `_sync_gpu_hardware_controls()` (L770) — Mirror live brain KV values in the detected-GPU summary rows.
  - `_wire_settings_signals()` (L785) — Wire up settings spinbox/combo signals after class body is fully defined.
  - `_wire_all_signals()` (L825) — Wire all deferred signals in one shot — called once via QTimer after
  - `_get_fallback_provider(exclude_provider=None)` (L832) — Get a fallback provider for failover.
  - `_failover_to_cloud(failed_provider)` (L854) — Failover from failed local provider to cloud.
  - `_apply_plan_device_assignment(small, big)` (L867) — Assign role→device from the device registry (detection + policy).
  - `_build_device_panel(parent_layout)` (L922) — Build the Compute Devices panel: one row per detected device with an
  - `_on_device_toggled(dev)` (L1001) — Persist a device enable/disable change and re-apply the assignment.
  - `_sync_role_enabled_to_env(dev, now_enabled: bool) -> None` (L1031) — Write <ROLE>_ENABLED for the role bound to `dev` (never raises).
  - `_stop_brain_on_disabled_device(device_id: str)` (L1070) — Stop any brain bound to a now-disabled device (never raises).
  - `_on_device_role_changed(dev)` (L1088) — Persist a device role override (Auto/Big/Small) and re-apply.
  - `_reapply_device_assignment()` (L1104) — Re-run device→role assignment and refresh the labels/subtitle so the
  - `_build_provider_rows(provider_layout)` (L1124) — Build one BrainControlRow per runtime slot into ``provider_layout``.
  - `_alias_legacy_provider_attrs()` (L1195) — Point sb_*/bb_* at the sub-widgets of provider rows 0/1.
  - `_on_provider_row_start(slot: int)` (L1242) — Route a row's Start click to the right brain handler by slot.
  - `_on_provider_row_stop(slot: int)` (L1252) — Route a row's Stop click to the right brain handler by slot.
  - `_on_provider_row_model_changed(slot: int, model_path: str)` (L1261) — A row's model dropdown changed: set the slot config's model.
  - `_on_provider_row_mtp_changed(slot: int, enabled: bool)` (L1310) — A row's MTP toggle changed: set the slot config's spec_type (Phase G).
  - `_show_advanced_settings_help()` (L1350) — Show a concise reference for the advanced llama.cpp settings (Phase G).
  - `_rebuild_provider_rows()` (L1382) — Rebuild the Provider Control rows after a device-policy change.
  - `_build_detected_brains_summary(settings_layout)` (L1389) — Build the per-device editable settings section into the Settings grid.
  - `_update_detected_brains_summary()` (L1416) — Rebuild the per-device editable settings rows from the slot list.
  - `_alias_legacy_settings_attrs()` (L1476) — Point sb_*/bb_* settings attributes at slots 1/0's BrainSettingsRow
  - `_on_brain_settings_changed(slot: int)` (L1500) — A per-device settings control changed: apply to the slot config +
  - `_apply_runtime()` (L1539) — Seed ctx spins + endpoint labels from the canonical runtime (if any).
  - `_snapshot_settings_values() -> dict` (L1706) — Build the llama.cpp settings dict from the current widget state.
  - `_persist_settings()` (L1765) — Persist the llama.cpp customization values to `.env` (v2.1).
  - `_build_llama_flag_group(parent_layout, brain_label, prefix, spin_qss)` (L1819) — Build one brain's advanced llama-server flag group.
  - `_open_llama_flags_help(brain_label: str='') -> None` (L2079) — Open the in-app help dialog filtered to the advanced llama.cpp flags.
  - `_mmproj_core(stem: str) -> str` (L2091) — Reduce a model or projector filename to its shared 'core' identity.
  - `_auto_detect_mmproj(prefix: str, edit) -> None` (L2114) — Fill the mmproj field with the projector that matches the model.
  - `_token_prefix(a: list, b: list) -> bool` (L2173) — True if one token list is a prefix of the other (token-wise).
  - `_token_suffix(a: list, b: list) -> bool` (L2181) — True if one token list is a suffix of the other (token-wise).
  - `_token_related(a: list, b: list) -> bool` (L2189) — Model↔projector cores are related if one is a prefix or suffix of
  - `_llama_flag_values(prefix: str, controls: dict) -> dict` (L2195) — Convert one group's controls into env key/value pairs.
  - `setup_ui()` (L2248) — Build the control panel UI with dynamic provider and GPU detection.
  - `_create_gpu_widget(index, name, color)` (L2611) — Create a GPU status display widget with estimated + actual bars,
  - `pause_background()` (L2817) — Reduce nvidia-smi polling while the tab is hidden.
  - `resume_background()` (L2826) — Restore fast nvidia-smi polling when the tab is shown again.
  - `_on_gpu_status_updated(gpus)` (L2837) — Handle GPU status update from background worker. Updates estimated
  - `_set_gpu_bar(idx, bar_type, pct, color)` (L2911) — Set a GPU bar value and color.
  - `_set_gpu_detail(idx, detail_type, text)` (L2924) — Set a GPU detail label. detail_type: 'est', 'act', 'kv'.
  - `_set_gpu_model(idx, text)` (L2930) — Set the model name label.
  - `_set_gpu_ctx(idx, text)` (L2936) — Set the context label.
  - `_set_gpu_status(idx, text)` (L2942) — Set the status line with color.
  - `clear_gpu_progress(speaker: str)` (L2950) — Reset the generation progress bar after generation completes.
  - `update_gpu_progress(speaker: str, tok_count: int, elapsed_s: float)` (L2962) — Update the live generation progress bar from the dialogue.
  - `_get_context_for_gpu(idx)` (L2975) — Get the configured context size for a GPU.
  - `_get_model_name_for_gpu(idx)` (L2985) — Get the model name for a GPU.
  - `_get_model_vram_for_gpu(gpu_index: int) -> dict` (L3004) — Get VRAM estimate for the model assigned to a GPU.
  - `_estimate_vram_background(gpu_index, key, model_path, context, kv_name)` (L3028) — Estimate GGUF memory without reading model metadata on the GUI thread.
  - `_on_vram_estimate_ready(gpu_index, key, estimate)` (L3041)
  - `_render_vram_estimate(gpu_index, estimate)` (L3047) — Update VRAM widgets from an already-computed background result.
  - `_on_context_changed(is_big: bool)` (L3077) — Queue VRAM estimation without blocking the Qt thread.
  - `_brain_port(small: bool) -> int` (L3094) — Resolve the ACTUAL configured port for a brain from the runtime
  - `_resolve_model_path(small: bool, combo_text: str) -> str` (L3109) — Return a real .gguf path to launch for a brain, or '' if none.
  - `_norm_path(p: str) -> str` (L3139)
  - `_discover_gguf_models() -> list` (L3142) — Scan the local model dirs for standalone .gguf files (skip mmproj).
  - `_model_combo(small: bool)` (L3171) — The Settings model combo for a role, or None when it doesn't exist.
  - `_current_model_path(small: bool) -> str` (L3180) — Full .gguf path behind the dropdown's current item (UserRole).
  - `_set_settings_combo_model(small: bool, model_path: str)` (L3200) — Select ``model_path`` in the hidden Settings model combo (slots 0/1).
  - `_repopulate_model_combo(small: bool, loaded_path: str='', models=None)` (L3231) — Fill a brain's dropdown with ALL local .gguf (display name, full path
  - `_restart_brain_with(small: bool, model_path: str)` (L3281) — Stop a running brain (force) and relaunch it with the given model.
  - `_do_restart(small: bool, model_path: str, port: int, label: str)` (L3307) — Background restart logic.
  - `_continue_model_restart(small: bool)` (L3328) — Continue a model restart on the Qt GUI thread.
  - `_row_for_slot(slot: int)` (L3335) — Return the BrainControlRow for *slot*, or None if not rendered.
  - `_set_loading(small: bool, loading: bool, model_path: str)` (L3350) — Show/hide loading indicator for a brain.
  - `_force_stop_brain(small: bool)` (L3383) — Terminate a brain's server process regardless of who started it.
  - `_pid_on_port(port: int)` (L3414) — Return the PID bound to 127.0.0.1:<port> (listening), or None.
  - `_pids_on_port(port: int)` (L3433) — Return ALL PIDs bound (LISTENING) to 127.0.0.1:<port>.
  - `_kill_llama_on_port(port: int)` (L3458) — Kill EVERY process listening on 127.0.0.1:<port>.
  - `_brain_models_url(small: bool) -> str` (L3478) — Full /v1/models URL for a brain, from the configured endpoint.
  - `_launch_and_wait(role_name: str, cmd, port: int)` (L3490) — Launch a server, then prove its endpoint is ready before reporting success.
  - `_log(message)` (L3531) — Append a timestamped message to the provider event log.
  - `_append_log_line(message)` (L3544) — GUI-thread slot: append one line and keep the view scrolled to the end.
  - `_record_start_failure(phase: str, error: Exception)` (L3551) — Persist start failures when Qt cannot deliver the visible log entry.
  - `cleanup()` (L3561) — Stop and join provider workers before this control is destroyed.
  - `_all_gpu_workers()` (L3600) — Return every live GPUStatusWorker this control has ever started.


### `gui/widgets/performance.py` — Performance optimization for MrBot1000 GUI. (306L)

**Functions:**
- `schedule_deferred(key: str, fn: Callable, *args, **kwargs)` (L266) — Schedule a deferred initialization task.
- `coalesce_request(key: str, compute_fn: Callable, *args, **kwargs) -> Any` (L273) — Coalesce identical concurrent requests.
- `cache_get(key: str) -> Optional[Any]` (L278) — Get from bounded cache.
- `cache_put(key: str, value: Any)` (L283) — Put into bounded cache.
- `cache_invalidate(key: str=None)` (L288) — Invalidate cache entries.
- `track_worker(obj)` (L293) — Track a background worker with weak ref.
- `prune_workers() -> int` (L298) — Prune dead workers. Returns count pruned.
- `make_throttler(flush_ms: int=50) -> _SignalThrottler` (L303) — Create a new signal throttler.

**Classes:**
- `class _DeferredQueue` (L20) — Run non-critical initialization after the event loop is pumping.
  - `__init__()` (L28)
  - `schedule(key: str, fn: Callable, *args, delay_ms=..., **kwargs)` (L33) — Schedule a task. If key already done, skip. If already scheduled, replace.
  - `run_next()` (L41) — Run the next queued task. Called via QTimer.singleShot.
- `class _RequestCoalescer` (L62) — Coalesce identical concurrent requests (e.g. tab rebuild storms).
  - `__init__()` (L69)
  - `get_or_compute(key: str, compute_fn: Callable, *args, **kwargs) -> Any` (L74) — Return cached result if in-flight; else compute and cache.
- `class _SignalThrottler` (L95) — Batch rapid signal emissions into a single GUI update.
  - `__init__(flush_ms: int=50)` (L109)
  - `connect(callback: Callable)` (L117) — Set the flush callback (receives list of buffered items).
  - `disconnect()` (L121) — Detach the callback and cancel any pending GUI flush.
  - `emit(*args)` (L135) — Buffer an emission. Flushes automatically after flush_ms.
  - `_arm_timer()` (L148) — Create/start the flush timer on the GUI thread.
  - `_start_timer()` (L165)
  - `_flush()` (L176) — Flush buffered emissions to the callback (GUI thread).
- `class _BoundedCache` (L193) — Memory-bounded LRU cache for expensive computations.
  - `__init__(max_size: int=64, ttl_seconds: float=30.0)` (L200)
  - `get(key: str) -> Optional[Any]` (L205) — Get cached value if present and not expired.
  - `put(key: str, value: Any)` (L217) — Cache a value, evicting oldest if at capacity.
  - `invalidate(key: str=None)` (L225) — Invalidate a specific key, or all if None.
- `class _WeakRefPool` (L233) — Track background workers with weak references so GC can reclaim them.
  - `__init__()` (L239)
  - `add(obj)` (L242) — Add a weakly-referenced object to the pool.
  - `alive_count() -> int` (L248) — Count still-alive objects.
  - `prune() -> int` (L252) — Remove dead refs. Returns count pruned.


### `gui/widgets/persona_naming.py` — Persona-aware naming for dialogue. (60L)

**Functions:**
- `big_brain_name() -> str` (L11)
- `small_brain_name() -> str` (L15)
- `_persona_name(speaker: str) -> str` (L19) — Map legacy/alias speaker keys to canonical persona display names.
- `_emoji(speaker: str) -> str` (L48)
- `_color(speaker: str) -> str` (L55)


### `gui/widgets/provider_config_widget.py` — gui/provider_config_widget.py — Dynamic provider configuration widget. (949L)

**Functions:**
- `_cloud_failover_enabled() -> bool` (L23) — Whether cloud providers may be used as a backup when local fails.

**Classes:**
- `class ProviderConfigWidget(QWidget)` (L33) — Dynamic provider configuration widget with hot-reload support.
  - `__init__(parent=None)` (L41)
  - `pause_background()` (L48) — Reduce provider polling while the Settings tab is hidden.
  - `resume_background()` (L52) — Restore active polling and refresh once after the tab is shown.
  - `_setup_ui()` (L57)
  - `_on_cloud_changed(text)` (L168) — Handle cloud provider change.
  - `_on_local_changed(text)` (L175) — Handle local provider change.
  - `_persist_fallback()` (L182) — v2.1.37 (ARCH-ENG-044): persist the cloud-failover toggle so the
  - `_persist_quick_selection(kind: str, text: str)` (L204) — Persist the quick route and refresh the process environment.
  - `_persist_brain_name(key: str, widget: QLineEdit)` (L247) — Persist a custom role name without altering the stable brain key.
  - `_build_provider_list(provider_type: str)` (L266) — Build provider list for cloud or local.
  - `_on_model_changed(provider_name: str, model: str)` (L478) — Handle model change.
  - `_role_model_combo(provider, env_key: str, models)` (L519)
  - `_on_role_model_changed(provider_name: str, env_key: str, model: str)` (L532) — Persist and load one brain role without changing the other role.
  - `_load_selected_local_model(provider_name, provider, model, role)` (L565) — Load a selected model through providers that expose lifecycle APIs.
  - `_load_local_model_worker(checker, provider, endpoint, model)` (L583)
  - `_on_gpu_changed(provider_name: str, gpu_index: int)` (L586) — Handle GPU change.
  - `_provider_prefix(provider_name: str) -> str` (L596)
  - `_role_from_env(prefix: str) -> str` (L605)
  - `_persist_provider_field(prefix: str, field: str, value: str)` (L612)
  - `_persist_provider_field_value(key: str, value: str)` (L615)
  - `_persist_provider_role(prefix: str, role: str)` (L623)
  - `_on_action_clicked(provider_name: str)` (L644) — Handle enable/disable action.
  - `_refresh_local_provider_card(provider_name: str)` (L713) — Refresh a local card after rebuilding the provider list.
  - `_refresh_provider_models(provider_name: str, combo: QComboBox)` (L724) — Fetch current local models and update the provider card in place.
  - `refresh()` (L750) — Refresh the provider list.
- `class CloudProviderPanel(QWidget)` (L768) — Cloud provider selection and configuration.
  - `__init__(parent=None)` (L773)
  - `_setup_ui()` (L777)
  - `_on_connect()` (L822) — Handle connect button click.
- `class LocalProviderPanel(QWidget)` (L849) — Local provider management.
  - `__init__(parent=None)` (L854)
  - `_setup_ui()` (L858)
  - `_build_llama_config(layout)` (L885) — Build llama.cpp configuration.
  - `_build_ollama_config(layout)` (L911) — Build Ollama configuration.
  - `_build_vllm_config(layout)` (L927) — Build vLLM configuration.


### `gui/workers/__init__.py` — workers package. (2L)


### `gui/workers/brain_launch_worker.py` — Background llama-server process worker. (565L)
> v2.1.77: surfaces unknown-arch warning before launch.

**Classes:**
- `class BrainLaunchPrepWorker(QThread)` (L13) — Run the slow, widget-free parts of a brain launch OFF the GUI thread.
  - `__init__(small: bool, model_path: str, cfg, port: int, gpu_device_index: int, parent=None)` (L29)
  - `run()` (L38)
  - `_gpu_free_vram_gb(device_index: int)` (L132)
  - `_available_ram_gb() -> float` (L168) — Currently-available physical RAM in GB (Windows perf counters).
  - `_other_servers_ram_gb(exclude_port: int) -> tuple` (L194) — (total_gb, [(role, ram_gb), ...]) for every OTHER running llama-server.
  - `_system_ram_contention_warn(label: str, model: str) -> str` (L238) — Return a loud warning string when launching ``model`` as ``label``
- `class BrainLaunchWorker(QThread)` (L288) — Background worker for launching llama-server - prevents GUI freeze.
  - `__init__(role_name: str, cmd: list, port: int, check_fn=None, visible_console: bool=True)` (L293)
  - `stop()` (L305) — Request cancellation; terminate ONLY a process this worker itself spawned.
  - `_default_check(port)` (L322)
  - `_proc_alive()` (L333) — True if the child process is still running (even if not answering probes).
  - `_port_is_bound() -> bool` (L337) — True if any process is LISTENING on 127.0.0.1:<port> right now.
  - `_wait_then_adopt(max_wait_s: float=20.0) -> bool` (L360) — Poll /v1/models for up to ``max_wait_s``; return True once it answers.
  - `run()` (L379) — Launch server and wait for it to be ready.
  - `_record_failure(message: str)` (L554)


### `gui/workers/db_query_worker.py` — gui/workers/db_query_worker.py — run a read-only SQLite query off the GUI thread. (69L)

**Functions:**
- `run_db_query(db_path: str, query: str, on_done: Callable[[List[Tuple], s, ...) -> DbQueryWorker` (L52) — Convenience: start a DbQueryWorker and wire ``on_done(rows, error)``.

**Classes:**
- `class DbQueryWorker(QThread)` (L21) — Run ``query`` against ``db_path`` off-thread; emit rows (or an error).
  - `__init__(db_path: str, query: str, params: Tuple=(), parent=None)` (L27)
  - `run() -> None` (L34)


### `gui/workers/provider_lifecycle_backend.py` — Provider lifecycle operations used by the Dual Brain Qt facade. (1478L)

**Functions:**
- `_qt_object_alive(obj) -> bool` (L21) — True when a Qt wrapper still has a live C++ object behind it.

**Classes:**
- `class ProviderLifecycleBackend` (L41) — Provider-control implementations used by the Qt facade.
  - `_refresh_small_brain_models()` (L50) — Populate the Small Brain dropdown with ALL local .gguf, selecting the
  - `_refresh_big_brain_models()` (L65) — Populate the Big Brain dropdown with ALL local .gguf, selecting the
  - `_get_llama_model(port: int, prefer: str='') -> str` (L80) — Get model name from llama-server API. Returns prefer if available, else first model.
  - `_gpu_free_vram_gb(device_index: int) -> Optional[float]` (L105) — Free VRAM (GB) for a CUDA device via nvidia-smi; None if unavailable.
  - `_model_vram_need_gb(small: bool, model_path: str, context: Optional[int]=None, kv_name: Optional[str]=None) -> Dict[str, Any]` (L130) — Estimate a model's total VRAM need (weights + KV @ configured ctx).
  - `_check_vram_affinity(small: bool, model_path: str) -> bool` (L164) — Warn-but-allow VRAM check before starting a brain.
  - `_validate_model_before_launch(small: bool, model_path: str) -> bool` (L216) — Reject malformed GGUFs before spawning llama-server.
  - `_show_vram_warning(small: bool, model_path: str, need: float, free: float, result: dict)` (L233) — Show VRAM warning dialog on GUI thread.
  - `_on_stop_small_brain(*_args)` (L257) — Stop the Small Brain server on its configured port.
  - `_begin_stop_brain(small: bool)` (L266)
  - `_on_brain_stopped(small: bool)` (L287)
  - `_start_in_progress(small: bool) -> bool` (L296) — True while a start (probe/prep/launch) is in flight for this brain.
  - `_set_start_in_progress(small: bool, value: bool)` (L300)
  - `_clear_start_in_progress(small: bool)` (L303) — Release the start guard on any terminal outcome (done/failed/cancelled).
  - `_on_start_small_brain(*_args)` (L307)
  - `_probe_before_start(small: bool)` (L310)
  - `_on_provider_probe_done(small: bool, running: bool, models)` (L345)
  - `_start_small_brain_after_probe()` (L360) — Start Small Brain on its configured local hardware/provider.
  - `_on_small_brain_launched(success: bool, message: str, proc)` (L459) — Handle small brain launch completion.
  - `_persist_settings_async()` (L477) — Persist llama.cpp settings to .env without blocking the GUI thread.
  - `_start_persist_write(values: dict)` (L502) — Spawn the background .env writer. Called on the GUI thread only.
  - `_arm_persist_drain()` (L510) — Poll for a pending re-write FROM THE GUI THREAD.
  - `_drain_persist_dirty()` (L538) — GUI-thread slot: deliver queued messages and re-write if dirty.
  - `_stop_persist_drain()` (L572)
  - `_persist_settings_worker(values: dict)` (L582) — Background .env writer — pure file I/O, never touches Qt.
  - `_write_env_values(values: dict)` (L586) — Background .env writer — pure file I/O, no Qt/widget access.
  - `_emit_persist_saved()` (L613) — Queue the .env save confirmation for the GUI-thread drain.
  - `_dispatch_launch_prep(small: bool, model: str, cfg)` (L630) — Run the slow launch-prep (GGUF preflight, VRAM estimate, command
  - `_on_launch_prep_finished(small: bool, ok: bool, message: str, cmd)` (L643) — GUI-thread slot: apply prep results and spawn the launcher.
  - `_on_start_big_brain(*_args)` (L670)
  - `_start_big_brain_after_probe()` (L673) — Start Big Brain (llama-server on 5060 Ti, port 1234).
  - `_start_external_brain(small: bool, cfg)` (L718) — Load the configured role model for a shared external provider.
  - `_on_big_brain_launched(success: bool, message: str, proc)` (L734) — Handle big brain launch completion.
  - `_on_stop_big_brain(*_args)` (L754) — Stop the Big Brain server on its configured port.
  - `_on_stop_all(*_args)` (L766) — Stop both Small Brain and Big Brain using port-specific filters.
  - `_slot_config(slot: int)` (L781) — Return the BrainConfig for ``slot`` from the runtime (or None).
  - `_start_slot(slot: int)` (L790) — Launch the llama-server for an extra brain slot (2+).
  - `_on_slot_launched(slot: int, ok: bool, message: str, proc)` (L844)
  - `_schedule_slot_reprobe(slot: int, attempts: int=90)` (L860) — Re-probe provider status until the just-launched slot server answers
  - `_stop_slot(slot: int)` (L882) — Stop an extra brain slot (2+) by terminating its child or its port.
  - `_on_temp_preset(text: str, spin: QDoubleSpinBox, env_key: str)` (L914) — Apply a temperature preset to the spinbox and persist.
  - `_unload_external_model(small, provider, endpoint, model, label)` (L922)
  - `_load_external_model(small, provider, endpoint, model, label)` (L928)
  - `_finish_external_lifecycle(small, ok, message)` (L934)
  - `_sync_adapter_model(small: bool)` (L943) — Sync the selected model to the corresponding adapter.
  - `_probe_model_selection(small: bool, path: str)` (L962) — Check the loaded model off the Qt thread after a combo selection.
  - `_on_probe_worker_finished(small: bool, worker)` (L996) — Drop the probe reference when its thread ends.
  - `_on_model_selection_probe_done(small: bool, path: str, running: bool, models)` (L1010) — Apply a background model probe result on the Qt thread.
  - `_persist_role_model(small: bool, model_name: str, runtime, cfg, persist=...)` (L1030) — Apply a model selection, optionally saving it as the next default.
  - `_on_small_brain_model_changed(model_name: str)` (L1054) — Handle Small Brain model change — restart the brain with the new
  - `_on_big_brain_model_changed(model_name: str)` (L1086) — Handle Big Brain model change — restart the brain with the new
  - `_select_external_model(small: bool, model_name: str, runtime, cfg)` (L1117) — Persist an external model ID without treating it as a GGUF path.
  - `_on_start_all(*_args)` (L1139) — Start every enabled brain slot through its per-slot start path.
  - `maybe_auto_start()` (L1164) — Auto-start both llama-server instances if the user opted in.
  - `_refresh_provider_status(*_args)` (L1182) — Refresh the status of both providers on a background thread so the
  - `_probe_providers(*_args)` (L1200)
  - `_on_launch_success_reprobe(small: bool, attempts: int=90)` (L1271) — Re-probe until a just-launched server actually answers.
  - `_apply_provider_status(data)` (L1291) — Apply probe results on the GUI thread.
  - `_apply_slot_statuses(slot_results)` (L1387) — Push per-slot probe results into the Provider Control rows.
  - `_safe_apply_provider_status(data)` (L1417) — Keep late provider probes from escaping through a Qt signal slot.
  - `_log(message)` (L1427) — Add a message to the event log.
  - `append_log(message)` (L1436)
  - `cleanup()` (L1442) — Stop background threads before the widget is destroyed.


### `gui/workers/provider_workers.py` — Qt workers for provider probing and stop operations. (55L)

**Classes:**
- `class ProviderProbeWorker(QThread)` (L6) — Check one provider endpoint without blocking the GUI thread.
  - `__init__(checker, target, endpoint=False, provider='', model='')` (L11)
  - `run()` (L19)
- `class ProviderStopWorker(QThread)` (L39) — Stop one provider process without blocking the GUI thread.
  - `__init__(control, small: bool)` (L44)
  - `run()` (L49)


### `gui/panels/__init__.py` — panels package. (2L)


### `gui/panels/approval_panel.py` — gui/approval_panel.py — In-app human-approval queue panel (Phase 6). (286L)

**Classes:**
- `class ApprovalPanel(QWidget)` (L28) — In-app panel listing pending approvals with Approve / Deny / Defer.
  - `__init__(parent: Optional[QWidget]=None, approval_queue: Optional[HumanApprovalQueue]=None)` (L36)
  - `showEvent(event)` (L47)
  - `hideEvent(event)` (L52)
  - `_setup_ui()` (L58)
  - `_refresh()` (L144)
  - `cleanup()` (L187) — Stop periodic queue polling before the main window is torn down.
  - `_on_selection_changed()` (L192)
  - `_clear_detail()` (L221)
  - `_on_approve()` (L235)
  - `_on_deny()` (L247)
  - `_on_defer()` (L261)
  - `refresh_now()` (L277)


### `gui/panels/dialogue_log.py` — Module-level best-effort JSONL writer for per-turn dialogue records. (26L)

**Functions:**
- `_append_dialogue_log(record: dict) -> None` (L11)


### `gui/panels/help_dialog.py` — gui/help_dialog.py — In-app feature help (v2.1). (122L)

**Functions:**
- `show_help_dialog(parent=None, keyword: str='')` (L112) — Open a modal help dialog. Safe to call from anywhere (never raises).

**Classes:**
- `class HelpDialog(QDialog)` (L20)
  - `__init__(parent=None, keyword: str='')` (L21)
  - `_load_entries()` (L32)
  - `_setup_ui()` (L44)
  - `_filtered()` (L77)
  - `_refresh()` (L88)
  - `_on_select(cur, _prev)` (L97)


### `gui/panels/registration_panel.py` — gui/panels/registration_panel.py — Gated platform sign-up (Phase B). (276L)

**Classes:**
- `class RegistrationPanel(QWidget)` (L37) — Operator-driven, approval-gated platform registration.
  - `__init__(parent: Optional[QWidget]=None, service=None, vault=None, approval_queue=None)` (L43)
  - `_svc()` (L54)
  - `_vlt()` (L60)
  - `_setup_ui()` (L67)
  - `_platform() -> str` (L134)
  - `_on_propose()` (L137)
  - `_format_plan(plan) -> str` (L160)
  - `_enqueue_approval(platform: str, signup: str)` (L179)
  - `_on_save_vault()` (L198)
  - `_refresh_vault_status()` (L226)
  - `_on_register()` (L240)
  - `_fail(message: str)` (L273)

