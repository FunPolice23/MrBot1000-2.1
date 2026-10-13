<!-- generated 63 files -->

### `tests/runtime/__init__.py` — Runtime tests. (2L)


### `tests/runtime/test_agent_delegation.py` — (no module docstring) (50L)

**Functions:**
- `_agent(registry, name, capabilities)` (L8)
- `test_delegation_selects_idle_agent_with_all_capabilities()` (L12)
- `test_delegation_refuses_missing_capability_without_fabricating_assignment()` (L31)
- `test_delegation_excludes_busy_agents()` (L43)


### `tests/runtime/test_agent_registry_leases.py` — (no module docstring) (46L)

**Functions:**
- `_registry()` (L6)
- `_agent(registry)` (L10)
- `test_lease_must_be_owned_to_complete_and_can_be_renewed()` (L14)
- `test_expired_lease_is_reclaimed_and_late_completion_rejected()` (L26)
- `test_cancellation_is_cooperative_and_scoped_to_lease()` (L38)


### `tests/runtime/test_agent_runtime.py` — (no module docstring) (67L)

**Functions:**
- `_runtime()` (L9)
- `test_runtime_selects_an_opportunity_without_a_snapshot_round()` (L19)
- `test_runtime_tracks_questions_and_high_priority_interrupts()` (L36)
- `test_runtime_updates_goal_and_exposes_state_snapshot()` (L48)
- `test_runtime_publishes_state_events_to_shared_bus()` (L57)


### `tests/runtime/test_architecture_boundaries.py` — (no module docstring) (55L)

**Classes:**
- `class TestArchitectureBoundaries` (L22)
  - `test_core_domain_has_no_gui_or_provider_sdk_imports()` (L23)
  - `test_application_bootstrap_does_not_eagerly_import_optional_adapters()` (L27)
  - `test_usage_ledger_requires_observed_use_before_removal()` (L43)


### `tests/runtime/test_brain_prompt_hardware.py` — Tests that brain prompts reflect the ACTUAL detected hardware (N-brain). (54L)

**Classes:**
- `class TestBrainPromptHardwareAwareness` (L12)
  - `_small_prompt()` (L13)
  - `_big_prompt()` (L17)
  - `test_small_prompt_has_hardware_section()` (L21)
  - `test_big_prompt_has_hardware_section()` (L24)
  - `test_prompts_reflect_detected_device_not_hardcoded()` (L27)
  - `test_hardware_line_never_raises()` (L44)


### `tests/runtime/test_collaboration_failures.py` — (no module docstring) (25L)

**Functions:**
- `test_discussion_budget_ends_without_unbounded_autonomy()` (L6)
- `test_canonical_state_rejects_false_completed_action()` (L13)


### `tests/runtime/test_comms.py` — test_comms.py — Proof tests for the Chat↔Main communication redesign. (347L)

**Functions:**
- `fresh_bus() -> EventBus` (L36)

**Classes:**
- `class Collector` (L40) — Thread-safe message sink standing in for Manager / Chat / GUI.
  - `__init__(bus: EventBus, dest: str=None, src: str=None, types=None)` (L42)
  - `handler(msg: Message)` (L55)
  - `texts()` (L59)
  - `count()` (L63)
- `class TestChatResponsiveDuringLongMainCall` (L69)
  - `test_chat_responsive()` (L70)
- `class TestTaskReachesManager` (L113)
  - `test_task_reaches_manager()` (L114)
- `class TestResultReachesManager` (L127)
  - `test_result_with_correlation()` (L128)
- `class TestManagerResultReachesChat` (L142)
  - `test_manager_result_reaches_chat()` (L143)
- `class TestGuiReceivesUpdates` (L154)
  - `test_gui_gets_opportunity_update()` (L155)
- `class TestCorrelationIntact` (L165)
  - `test_correlation_survives_fanout()` (L166)
- `class TestErrorPropagation` (L196)
  - `test_error_carries_correlation()` (L197)
  - `test_handler_exception_publishes_error()` (L208)
- `class TestCancellation` (L225)
  - `test_cancel_sets_status_and_token()` (L226)
  - `test_cancelled_handler_stops()` (L238)
- `class TestNoDuplicateExecution` (L257)
  - `test_same_message_id_delivered_once()` (L258)
- `class TestNoCircularLoop` (L276)
  - `test_self_loop_rejected()` (L277)
  - `test_edge_replay_rejected()` (L285)
- `class TestRestartSafety` (L304)
  - `test_in_flight_marked_cancelled_on_restart()` (L305)


### `tests/runtime/test_comms_integration.py` — test_comms_integration.py — Real Manager/Summarizer/EarningPipeline bus wiring. (159L)

**Classes:**
- `class FakeWorker` (L25)
  - `llm(*a, **k)` (L27)
  - `research_all()` (L29)
- `class TestGuiToChatWiring` (L33)
  - `setUp()` (L34)
  - `test_user_request_reaches_chat_queue_with_correlation()` (L38)
- `class TestChatRoutesTaskToManager` (L47)
  - `setUp()` (L48)
  - `test_task_intent_publishes_structured_task_request()` (L55)
- `class TestManagerBusReplyCorrelated` (L71)
  - `setUp()` (L72)
  - `test_manager_replies_with_correlation()` (L85)
- `class TestOpportunityUpdateReachesGui` (L98)
  - `test_earning_pipeline_emits_update()` (L99)
- `class TestNoCircularLoopEndToEnd` (L117)
  - `test_chat_manager_chat_bounce_rejected()` (L118)
- `class TestQtEventBridge` (L135) — P4: the Qt delivery bridge must re-emit every bus Message as a Qt signal
  - `test_bridge_reemits_bus_messages()` (L138)


### `tests/runtime/test_configuration.py` — (no module docstring) (79L)

**Classes:**
- `class TestConfiguration` (L11)
  - `test_normalizes_provider_settings()` (L12)
  - `test_disabled_provider_is_normalized()` (L24)
  - `test_lmstudio_legacy_disable_key_is_normalized()` (L29)
  - `test_unknown_provider_is_rejected()` (L33)
  - `test_diagnostics_never_include_secret_value()` (L37)
  - `test_all_supported_providers_are_available()` (L45)
  - `test_empty_injected_environment_is_not_global_environment()` (L50)
  - `test_worker_registry_uses_normalized_provider_values()` (L55)


### `tests/runtime/test_device_policy_write_guard.py` — Tests for the device-policy write guard (ARCH-ENG-057). (185L)

**Functions:**
- `test_seeding_settings_guard_exists_and_defaults_off()` (L31) — The guard counter must exist on every instance and start at 0.
- `test_settings_changed_is_a_noop_while_seeding()` (L39) — With the guard held, `_on_brain_settings_changed` must not touch disk.
- `test_apply_runtime_holds_the_guard_across_the_whole_seeding_block(monkeypatch)` (L55) — `_apply_runtime` must bracket EVERY control seeding in the guard, and
- `test_guard_released_after_seeding_so_real_edits_still_persist(_qt_app_session, monkeypatch, tmp_path)` (L82) — End-to-end: a genuine operator edit after seeding MUST still persist.
- `test_policy_path_defaults_to_cwd_settings_json(monkeypatch)` (L122) — Without an override the production path is unchanged.
- `test_policy_path_honours_the_override(monkeypatch, tmp_path)` (L130) — `MRBOT_DEVICE_SETTINGS_PATH` redirects reads AND writes.
- `test_explicit_root_still_wins_over_the_override(monkeypatch, tmp_path)` (L139) — Tests that deliberately pass `root=` must not be redirected.
- `test_save_and_load_round_trip_through_the_override(monkeypatch, tmp_path)` (L150) — The override is honoured by BOTH ends, not just the writer.
- `test_a_rootless_save_cannot_reach_the_operators_file(monkeypatch, tmp_path)` (L164) — The exact call shape the GUI makes (`save_policy(policy)`, no root) must
- `test_conftest_installs_the_isolation_override()` (L179) — The suite-wide override must actually be set (otherwise every GUI test


### `tests/runtime/test_device_registry.py` — Tests for the device registry (detection, policy, allocation). (193L)

**Functions:**
- `_dev(dev_id, kind, mem, idx=0, name='Card', cores=0, cap='')` (L13)

**Classes:**
- `class TestCapability` (L18)
  - `test_gpu_classes_by_vram()` (L19)
  - `test_cpu_classes_by_ram_and_cores()` (L26)
- `class TestResolveAssignments` (L37)
  - `setUp()` (L38)
  - `test_default_all_enabled_auto()` (L44)
  - `test_disable_device()` (L51)
  - `test_cannot_promote_small_gpu_to_big()` (L59)
  - `test_can_downgrade_cpu_to_small()` (L67)
- `class TestBrainPlacements` (L75)
  - `setUp()` (L76)
  - `test_gpus_preferred_over_cpu_within_class()` (L82)
  - `test_ports_sequential_unique()` (L89)
  - `test_single_gpu_plus_cpu()` (L97)
  - `test_only_one_device_enabled()` (L107)
- `class TestPersistence` (L115)
  - `test_policy_round_trip()` (L116)
  - `test_save_preserves_other_keys()` (L127)
  - `test_missing_file_gives_defaults()` (L139)
  - `test_corrupt_settings_json_does_not_block_future_saves()` (L145)
  - `test_truncated_json_is_quarantined()` (L163)
  - `test_save_is_atomic_no_partial_file_left()` (L172)
- `class TestDetection` (L179)
  - `test_detect_devices_never_raises()` (L180)
  - `test_detect_without_cpu()` (L186)


### `tests/runtime/test_dual_brain_coordinator.py` — tests/test_dual_brain_coordinator.py — Canonical cross-model collaboration (v2.1). (208L)

**Functions:**
- `_fresh_coordinator(model_fn=None, stages=None)` (L23)

**Classes:**
- `class TestProtocol` (L35)
  - `test_message_types_registered()` (L36)
  - `test_stage_role_routing()` (L48)
- `class TestCollaborate` (L55)
  - `test_full_handoff_succeeds()` (L56)
  - `test_stage_failure_fails_run_and_stops()` (L90)
  - `test_later_stages_receive_prior_results()` (L108)
- `class TestDurableLedger` (L129)
  - `test_each_stage_persists_request_and_result()` (L130)
  - `test_run_ledger_retrievable()` (L151)
- `class TestLoopSafety` (L161)
  - `test_requests_are_cycle_safe_on_bus()` (L162)
- `class TestCustomRouting` (L188)
  - `test_stage_roles_override()` (L189)
  - `test_subset_of_stages()` (L199)


### `tests/runtime/test_dual_brain_runtime.py` — tests/test_dual_brain_runtime.py — Canonical dual-brain runtime (v2.1). (511L)

**Functions:**
- `_placement(role, device_id, index, name, mem_gb, port, is_cpu=False, label='')` (L377)

**Classes:**
- `class _FakeModelsHandler` (L31)
  - `do_GET()` (L32)
  - `log_message(*args)` (L40)
- `class _Server` (L44)
  - `__init__()` (L45)
  - `close()` (L51)
- `class TestRoleDefaults` (L57)
  - `test_tensor_types_are_conservative_for_old_cuda()` (L58)
  - `test_tensor_types_include_bf16_for_ampere_and_newer()` (L62)
  - `test_cpu_tensor_types_do_not_require_cuda()` (L65)
  - `test_custom_display_names_are_role_specific()` (L68)
  - `test_big_brain_defaults_device0_port1234()` (L75)
  - `test_small_brain_defaults_device1_port1235()` (L81)
  - `test_small_brain_cpu_only_command_avoids_missing_cuda_device()` (L86)
  - `test_perf_flag_prints_token_timings_by_default()` (L95)
  - `test_perf_flag_is_configurable_off()` (L103)
  - `test_context_shift_enabled_emits_flag()` (L108)
  - `test_context_shift_disabled_emits_negative_flag()` (L118)
  - `test_context_shift_unset_omits_flag()` (L124)
  - `test_context_shift_applies_to_small_brain()` (L132)
  - `test_cpu_decision_model_policy_prefers_configured_small_model()` (L137)
  - `test_cpu_decision_model_policy_selects_smallest_discovered_model()` (L149)
  - `test_decision_support_flag_is_configurable()` (L158)
  - `test_small_brain_falls_back_to_cpu_without_second_gpu()` (L162)
  - `test_missing_gpu_overrides_stale_positive_gpu_layers()` (L169)
  - `test_small_brain_keeps_auto_gpu_when_second_gpu_exists()` (L174)
  - `test_small_brain_recovers_gpu_after_cpu_fallback()` (L180)
  - `test_small_brain_stays_cpu_when_gpu_still_missing()` (L190)
  - `test_default_contract_has_both_roles()` (L197)
- `class TestIsolation` (L205)
  - `test_default_isolation_is_isolated()` (L206)
  - `test_broken_isolation_detected_when_small_uses_device0()` (L214)
  - `test_cpu_only_small_brain_is_valid_without_gpu1()` (L222)
  - `test_shared_port_breaks_isolation()` (L229)
- `class TestConfigFromEnv` (L236)
  - `test_kv_cache_and_batch_are_independent_per_brain()` (L237)
  - `test_env_overrides_endpoint_and_model()` (L249)
  - `test_unknown_provider_falls_back_to_llamacpp()` (L260)
  - `test_ollama_provider_uses_api_tags_path()` (L264)
  - `test_vllm_provider_normalizes_shared_base_url()` (L272)
  - `test_koboldcpp_provider_uses_native_model_path()` (L281)
- `class TestOfflineHealth` (L291)
  - `test_offline_is_reachable_false_no_raise()` (L292)
  - `test_disabled_role_returns_no_models()` (L301)
- `class TestLiveHealth` (L307) — Uses a real localhost HTTP server (no external network).
  - `setUpClass()` (L311)
  - `tearDownClass()` (L315)
  - `test_health_lists_models_from_server()` (L318)
  - `test_health_marks_selected_model_available_without_changing_selection()` (L329)
  - `test_health_marks_stale_selected_model_without_silent_fallback()` (L339)
  - `test_snapshot_contains_isolation_and_both_roles()` (L350)
- `class TestModelSwitching` (L359)
  - `test_set_model_persists_per_role()` (L360)
  - `test_set_model_invalidates_health_cache()` (L370)
- `class TestNBrainSlots` (L385) — N-brain slot store (Phase 1). Slots 0/1 are the BIG/SMALL role configs;
  - `test_default_slots_are_the_two_role_configs()` (L389)
  - `test_slot_config_out_of_range_returns_none()` (L395)
  - `test_sync_slots_grows_to_four_placements()` (L400)
  - `test_sync_slots_preserves_gui_fields_on_slots_0_1()` (L429)
  - `test_sync_slots_never_drops_below_two()` (L445)
  - `test_sync_slots_shrinks_when_devices_disabled()` (L453)
  - `test_slot_for_device_lookup()` (L466)
  - `test_sync_slots_is_resilient_to_bad_placements()` (L479)
- `class TestBuildSlotConfig` (L486)
  - `test_gpu_placement_uses_auto_offload_and_big_context()` (L487)
  - `test_cpu_placement_forces_system_ram()` (L499)


### `tests/runtime/test_end_to_end_recovery.py` — (no module docstring) (58L)

**Classes:**
- `class TestEndToEndRecovery` (L13)
  - `tearDown()` (L14)
  - `test_mutation_stops_at_approval_boundary()` (L17)
  - `test_interrupted_run_is_recovered_as_failed()` (L22)
  - `test_concurrency_limit_is_bounded_and_cancellation_is_observed()` (L47)


### `tests/runtime/test_env_write_guard.py` — Tests for the `.env` write guard (test isolation + protected keys). (107L)

**Functions:**
- `test_set_env_values_refuses_to_write_under_pytest(monkeypatch)` (L22) — Without an explicit override, a test must not be able to write .env.
- `test_mrbot_env_path_redirects_the_write(monkeypatch, tmp_path)` (L31) — With MRBOT_ENV_PATH set, the write lands in the temp file, atomically.
- `test_empty_model_value_never_blanks_a_saved_selection(monkeypatch, tmp_path)` (L47) — A settings save with an unselected dropdown must not erase the key.
- `test_persist_role_model_defaults_to_not_writing()` (L70) — The default must be opt-in; production callers pass it explicitly.
- `test_persist_role_model_without_persist_does_not_write(monkeypatch, tmp_path)` (L89) — Calling with the default must leave the filesystem alone.


### `tests/runtime/test_feature_flags.py` — (no module docstring) (36L)

**Classes:**
- `class TestFeatureFlags` (L6)
  - `test_optional_features_fail_closed()` (L7)
  - `test_new_flag_takes_precedence_over_legacy_alias()` (L12)
  - `test_legacy_alias_is_supported()` (L19)
  - `test_status_is_non_secret()` (L22)
  - `test_canonical_environment_key_is_exposed()` (L27)


### `tests/runtime/test_hardware_plan.py` — Tests for the hardware→brain allocation planner. (122L)

**Functions:**
- `_fake_gpus(manager, specs)` (L12) — Install fake GPUInfo objects on a ProviderManager without probing.

**Classes:**
- `class TestClassify` (L23)
  - `test_big_small_none_thresholds()` (L24)
- `class TestBrainPlan` (L32)
  - `setUp()` (L33)
  - `tearDown()` (L40)
  - `test_two_gpus_assign_by_vram()` (L44)
  - `test_single_gpu_falls_back_to_cpu_when_enabled()` (L64)
  - `test_no_gpu_yields_no_brains()` (L74)
  - `test_ports_are_sequential_and_unique()` (L80)
  - `test_low_vram_gpu_skipped()` (L93)
  - `test_format_is_readable()` (L103)
- `class TestCpuDetection` (L112)
  - `test_cpu_target_never_raises()` (L113)


### `tests/runtime/test_manager_queue_limits.py` — (no module docstring) (77L)

**Classes:**
- `class TestManagerQueueLimits` (L10)
  - `setUp()` (L11)
  - `tearDown()` (L15)
  - `test_human_queue_drops_oldest_when_full()` (L21)
  - `test_task_queue_drops_oldest_when_full()` (L29)
- `class TestManagerRetirement` (L38) — v2.1.47 (ARCH-ENG-046): the legacy CEO-Manager heartbeat loop is retired.
  - `_run_captures_retirement()` (L47)
  - `test_run_is_retired_by_default()` (L55)
  - `test_run_active_when_explicitly_enabled_returns_before_loop()` (L61)


### `tests/runtime/test_mrbot_cli.py` — Tests for agents.mrbot_cli — read-only runtime inspection CLI. (161L)

**Functions:**
- `test_read_env_only_allows_whitelisted_keys()` (L22) — Only ENV_READ_ALLOWLIST keys appear in the result.
- `test_read_env_missing_file_returns_empty()` (L42) — A missing .env is not an error; returns {}.
- `test_pretty_env_redacts_sensitive_keys()` (L58) — Keys matching the redaction regex show [REDACTED], never the value.
- `test_pretty_env_never_prints_secret_values()` (L67) — No value containing 'secret'/'key'/'token' etc. is ever visible.
- `test_probe_models_unreachable_returns_false()` (L82) — Nothing listening → (False, '', []) never raises.
- `_fake_args(command)` (L94)
- `test_cmd_health_prints_degraded_when_servers_down(monkeypatch, capsys)` (L98) — Both brains unreachable → DEGRADED (expected in CI / headless).
- `test_cmd_health_shows_ok_when_all_present(monkeypatch, tmp_path, capsys)` (L116) — All checks pass → OK.
- `test_main_unknown_subcommand_returns_2(capsys)` (L138)
- `test_main_no_args_prints_help(capsys)` (L144)
- `test_no_secret_value_ever_printed(monkeypatch)` (L154) — Even with a real .env containing credentials, stdout must


### `tests/runtime/test_mtp_capability.py` — Phase G1 — MTP capability detection + launch-flag wiring (ARCH-ENG-092). (78L)

**Classes:**
- `class TestDetectMtp` (L19)
  - `test_capable_model_detected()` (L20)
  - `test_noncapable_model_not_detected()` (L28)
  - `test_missing_path_fails_safe()` (L36)
  - `test_tooltip_mentions_availability()` (L41)
- `class TestCommandWiring` (L50)
  - `_cfg(**kw)` (L51)
  - `test_flag_omitted_by_default()` (L58)
  - `test_flag_present_when_enabled()` (L62)
  - `test_flag_present_without_nmax()` (L70)


### `tests/runtime/test_performance_telemetry.py` — (no module docstring) (37L)

**Classes:**
- `class TestPerformanceTelemetry` (L6)
  - `test_snapshot_is_provider_independent()` (L7)
  - `test_negative_values_do_not_corrupt_counters()` (L25)


### `tests/runtime/test_persistence_classification.py` — (no module docstring) (16L)

**Classes:**
- `class TestPersistenceClassification` (L6)
  - `test_projection_and_subsystem_boundaries_are_explicit()` (L7)


### `tests/runtime/test_persistence_contract.py` — (no module docstring) (42L)

**Classes:**
- `class TestPersistenceContract` (L11)
  - `test_rejects_unknown_store()` (L12)
  - `test_rejects_shared_store_path()` (L16)
  - `test_accepts_distinct_store_paths()` (L25)
  - `test_authority_metadata_is_available()` (L34)


### `tests/runtime/test_recovery.py` — (no module docstring) (11L)

**Functions:**
- `test_recovery_requires_state_change_or_new_evidence()` (L4)


### `tests/runtime/test_refresh_coordinator.py` — (no module docstring) (33L)

**Classes:**
- `class TestRefreshCoordinator` (L8)
  - `setUpClass()` (L10)
  - `test_hidden_entries_do_not_refresh()` (L13)
  - `test_invalid_interval_is_rejected()` (L25)


### `tests/runtime/test_root_scope.py` — (no module docstring) (19L)

**Classes:**
- `class TestRootScope` (L11)
  - `test_base_worker_root_points_to_repo_root()` (L12)


### `tests/runtime/test_runtime_shutdown.py` — (no module docstring) (47L)

**Classes:**
- `class TestMainWindowShutdown` (L13)
  - `setUp()` (L14)
  - `test_shutdown_stops_threads_and_closes_db()` (L17)


### `tests/runtime/test_runtime_warnings.py` — (no module docstring) (28L)

**Classes:**
- `class TestRuntimeWarnings` (L10)
  - `test_manager_emits_warning_for_logging_failure()` (L11)


### `tests/runtime/test_self_improvement_commands.py` — Regression tests for self_improvement_commands (approval-gated patch actions). (140L)

**Functions:**
- `_enable_feature(monkeypatch)` (L16) — Self-improvement is fail-closed; enable it for the happy-path tests.
- `service()` (L23)
- `_write_target(root, name='demo.py', content='original = 1\n')` (L36)
- `test_propose_enqueues_and_applies_nothing(service)` (L43)
- `test_approve_and_apply_patches_file(service)` (L60)
- `test_approve_and_apply_bad_patch_rolls_back(service)` (L77)
- `test_decline_never_applies(service)` (L92)
- `test_propose_blocked_when_feature_disabled(service, monkeypatch)` (L107)
- `test_propose_rejects_path_escape(service)` (L124)


### `tests/runtime/test_startup_validation.py` — (no module docstring) (74L)

**Classes:**
- `class StartupValidationTests` (L6)
  - `test_wallet_key_files_are_gitignored()` (L7)
  - `test_default_dual_brain_counts_as_local_provider()` (L17)
  - `test_disabled_local_brains_without_cloud_provider_errors()` (L27)
- `class TestStartupValidation` (L51)
  - `test_safe_mode_and_missing_provider_are_reported()` (L52)


### `tests/runtime/test_state_reconciliation.py` — Focused tests for read-only cross-store reconciliation. (82L)

**Classes:**
- `class TestStateReconciliation` (L10)
  - `test_paid_without_verified_payment_is_high_conflict()` (L11)
  - `test_verified_payment_without_paid_lifecycle_is_high_conflict()` (L21)
  - `test_currency_conversion_matches_accounting_revenue()` (L36)
  - `test_failed_run_and_paid_lifecycle_are_conflicting()` (L57)
  - `test_clean_unpaid_state_has_no_conflicts()` (L69)


### `tests/runtime/test_version_single_source.py` — Single-source of truth for the release version. (68L)

**Classes:**
- `class TestReleaseVersionIsSingleSourced` (L26)
  - `test_app_version_is_the_authoritative_release()` (L27) — The authority itself must look like a release version.
  - `test_program_knowledge_tracks_the_release()` (L31) — The version both brains are prompted with must equal the release.
  - `test_persona_prompt_carries_the_real_release()` (L36) — A persona system prompt must advertise the true build, not a stale one.
  - `test_memory_context_header_tracks_the_release()` (L49) — The injected memory-context header must not advertise a stale build.
  - `test_root_package_version_tracks_the_release()` (L57) — The root package must re-export the release, not a duplicate literal.


### `tests/gui/__init__.py` — Gui tests. (2L)


### `tests/gui/test_brain_control_row.py` — Tests for the reusable BrainControlRow widget (N-brain Phase 2). (103L)

**Classes:**
- `class TestBrainControlRow` (L16)
  - `_row(slot=0, role='big', label='')` (L17)
  - `test_renders_role_and_slot()` (L20)
  - `test_start_signal_carries_slot()` (L26)
  - `test_stop_signal_carries_slot()` (L33)
  - `test_device_label_updates_header()` (L41)
  - `test_set_running_toggles_buttons()` (L47)
  - `test_set_model_and_status()` (L59)
  - `test_set_models_fills_dropdown_and_preselects()` (L68)
  - `test_model_changed_signal_carries_slot_and_path()` (L74)
  - `test_bind_from_config()` (L82)
  - `test_bind_is_resilient_to_bad_config()` (L95)


### `tests/gui/test_brain_settings_row.py` — Tests for the reusable BrainSettingsRow widget (N-brain per-device settings). (97L)

**Classes:**
- `class TestBrainSettingsRow` (L16)
  - `_row(slot=0, role='big', is_cpu=False)` (L17)
  - `test_renders_all_controls()` (L21)
  - `test_changed_signal_carries_slot()` (L27)
  - `test_cpu_row_locks_gpu_layers_to_zero_disabled()` (L34)
  - `test_gpu_row_allows_auto_gpu_layers()` (L39)
  - `test_bind_from_config()` (L44)
  - `test_apply_to_config()` (L56)
  - `test_apply_to_cpu_config_forces_gpu_layers_zero()` (L70)
  - `test_values_dict()` (L77)
  - `test_values_dict_cpu_forces_zero()` (L86)
  - `test_bind_is_resilient_to_bad_config()` (L90)


### `tests/gui/test_db_query_worker.py` — Tests for the off-thread DbQueryWorker (GUI responsiveness fix). (87L)

**Classes:**
- `class TestDbQueryWorker` (L19)
  - `_make_db()` (L20)
  - `test_returns_rows()` (L32)
  - `test_missing_db_reports_error_not_crash()` (L42)
  - `test_bad_sql_reports_error()` (L51)
  - `test_params_are_bound()` (L60)
  - `test_run_db_query_async_delivers_on_gui_thread()` (L68)


### `tests/gui/test_earning_gui.py` — tests/test_earning_gui.py — GUI smoke test for EarningTab. (42L)

**Functions:**
- `qt_app()` (L10)
- `test_earning_tab_builds(qt_app)` (L15)
- `test_tab_builder_delegates_earning_tab()` (L27)
- `test_insights_renders_structured_events(qt_app)` (L34)


### `tests/gui/test_exit_disconnect_and_arch.py` — Phase G follow-ups — exit-time disconnect warnings + unknown-arch precheck (89L)

**Functions:**
- `_app()` (L18)

**Classes:**
- `class TestArchDetection` (L23)
  - `test_unknown_arch_flagged()` (L24)
  - `test_known_arch_passes()` (L32)
  - `test_known_set_contains_common_archs()` (L39)
- `class TestDisconnectNoWarning` (L45)
  - `setUpClass()` (L47)
  - `test_disconnect_on_dead_object_is_silent()` (L50) — Disconnecting a worker whose C++ object is gone must not warn.
  - `test_disconnect_on_live_worker_is_silent()` (L70)


### `tests/gui/test_gui_smoke.py` — tests/test_gui_smoke.py — GUI smoke tests for tabs not covered by test_earning_gui.py. (310L)

**Functions:**
- `qt_app()` (L26) — Provide a QApplication instance for GUI tests (session-scoped).
- `_make_brain_mock(model: str='test-model', base_url: str='http://127.0.0.1:12)` (L36) — Return a minimal mock that satisfies DialogueTab/ChatTab constructor needs.
- `test_approval_panel_builds(qt_app)` (L48)
- `test_approval_panel_refresh_clears_after_init(qt_app)` (L63)
- `test_dialogue_tab_builds(qt_app)` (L75)
- `test_dialogue_tab_set_goal(qt_app)` (L96)
- `test_chat_tab_builds(qt_app)` (L112)
- `test_provider_config_widget_builds(qt_app)` (L128)
- `test_provider_config_widget_cloud_local_tabs(qt_app)` (L143)
- `test_collaboration_tab_builds(qt_app)` (L155)
- `test_management_tab_builds(qt_app)` (L187)
- `test_analytics_tab_builds(qt_app)` (L221)
- `test_dual_brain_control_import(qt_app)` (L236) — DualBrainControl is large and has heavy dependencies; verify it imports cleanly.
- `test_diagnostics_tab_is_read_only_and_refreshes_health(qt_app)` (L242)
- `test_tab_builders_mixin_has_create_methods(qt_app)` (L296)


### `tests/gui/test_launch_adopt.py` — Launch-lifecycle regression tests. (115L)

**Functions:**
- `app()` (L45)
- `live_server(app)` (L51)
- `_pump(worker, timeout_ms=8000, slots=None)` (L60)
- `test_adopts_existing_listener_instead_of_spawning(app, live_server)` (L69)
- `test_stop_is_noop_for_adopted_server(app, live_server)` (L89)

**Classes:**
- `class _FakeServer(BaseHTTPRequestHandler)` (L27)
  - `do_GET()` (L28)
  - `log_message(*a)` (L40)


### `tests/gui/test_llama_setting_help.py` — Phase G3 — advanced llama.cpp settings have mouse-hover help (ARCH-ENG-094). (57L)

**Functions:**
- `_app()` (L13)

**Classes:**
- `class TestHelpCatalog` (L18)
  - `test_catalog_covers_all_keys()` (L19)
  - `test_tooltip_unknown_returns_default()` (L27)
- `class TestSettingsRowTooltips` (L33)
  - `setUpClass()` (L35)
  - `test_every_control_has_tooltip()` (L38)


### `tests/gui/test_mmproj_auto_detect.py` — mmproj auto-detect must match the projector to the SELECTED model. (72L)

**Classes:**
- `class TestMmprojCore` (L23)
  - `test_strips_mmproj_prefix_and_quant()` (L24)
  - `test_model_and_projector_collapse_to_same_core()` (L28)
  - `test_strips_various_quant_tokens()` (L32)
- `class TestMmprojMatching` (L39)
  - `_match(model, proj)` (L40)
  - `test_non_matching_pairs_reject(model, proj)` (L56)
  - `test_matching_pairs_accept(model, proj)` (L66)


### `tests/gui/test_mtp_toggle.py` — Phase G2 — Provider Control MTP toggle greys out for unsupported models (ARCH-ENG-093). (76L)

**Functions:**
- `_app()` (L16)

**Classes:**
- `class TestMtpToggle` (L21)
  - `setUpClass()` (L23)
  - `_row()` (L26)
  - `test_capable_model_enables_checkbox()` (L30)
  - `test_noncapable_model_greys_checkbox()` (L39)
  - `test_no_model_greys_checkbox()` (L48)
  - `test_switching_model_reevaluates()` (L53)
  - `test_mtp_changed_signal_emits()` (L63)


### `tests/gui/test_payout_widget_namespace.py` — tests/gui/test_payout_widget_namespace.py (60L)

**Functions:**
- `qt_app()` (L27)
- `test_earning_tab_payment_spinbox_does_not_shadow_pay_amount(qt_app)` (L32) — The Earnings crypto-payment spinbox must not be named `pay_amount`.
- `test_management_and_earnings_tabs_share_parent_without_collision(qt_app)` (L44) — Building both tabs on one parent must leave `pay_amount` as the


### `tests/gui/test_provider_control_nrows.py` — Tests for the N-brain Provider Control panel rendering (Phase 3). (145L)

**Functions:**
- `_wait_detected(app, timeout=12)` (L19)

**Classes:**
- `class TestProviderControlNRows` (L26)
  - `setUpClass()` (L28)
  - `_widget()` (L31)
  - `test_renders_one_row_per_slot()` (L39)
  - `test_slot0_is_big_slot1_is_small()` (L48)
  - `test_legacy_aliases_point_at_rows()` (L56)
  - `test_row_headers_show_detected_device()` (L66)
  - `test_refresh_does_not_rebuild_when_count_unchanged()` (L76)
  - `test_row_start_signal_routes_to_big_handler()` (L86)
  - `test_row_start_signal_routes_to_small_handler()` (L102)
  - `test_detected_brains_summary_lists_all_slots()` (L116)
  - `test_detected_brains_summary_shows_ctx_control()` (L130)


### `tests/gui/test_provider_rate_settings.py` — Phase F3 — Settings-tab provider rate/cap fields seed + persist (ARCH-ENG-091). (69L)

**Functions:**
- `_seed_default(prov, cur)` (L19)

**Classes:**
- `class TestProviderFieldSeeds` (L23)
  - `setUp()` (L24)
  - `test_cloud_defaults_when_unset()` (L29)
  - `test_local_defaults_when_unset()` (L33)
  - `test_env_override_wins()` (L36)
- `class TestProviderFieldPersists` (L42)
  - `test_set_values_round_trip()` (L43)
  - `test_runtime_reads_persisted_key()` (L56)


### `tests/gui/test_provider_status_mapping.py` — Provider-status slot→legacy-key mapping + VRAM-risk guard (v2.1.52, ARCH-ENG-052). (216L)

**Classes:**
- `class TestSlotToLegacyKeyMapping` (L25) — slot_results[i] must map to the correct legacy key.
  - `_legacy_map(slot_results)` (L33) — Mirror the fixed mapping in _apply_provider_status.
  - `test_big_running_small_stopped()` (L50)
  - `test_small_running_big_stopped()` (L61)
  - `test_both_running()` (L74)
  - `test_single_slot_does_not_swap()` (L85)
- `class TestVramRiskWarning` (L96) — The VRAM over-allocation guard must warn (not silently proceed).
  - `test_warns_when_model_exceeds_free_vram()` (L99)
  - `test_no_warn_when_model_fits()` (L144)
- `class TestNullWidgetAliases` (L157) — v2.1.53 (ARCH-ENG-053): a disabled brain's legacy aliases must be no-ops.
  - `test_nullwidget_swallows_all_legacy_calls()` (L166)
  - `test_set_loading_does_not_raise_with_one_row()` (L179) — _set_loading must no-op for a brain whose row isn't rendered.


### `tests/gui/test_section_e.py` — Canonical tests for Section E (GUI/perf/dense-MoE/memory) — phases 1-2 & G5/G6. (390L)

**Classes:**
- `class TestArchDetection` (L26)
  - `test_moe_family_detected()` (L27)
  - `test_dense_family_detected()` (L35)
  - `test_unknown_model_safe_defaults()` (L41)
- `class TestProviderProbeCache` (L49)
  - `test_cached_probe_and_forced_refresh()` (L50)
  - `test_is_moe_convenience()` (L64)
  - `test_missing_model_empty()` (L69)
  - `test_modelinfo_labels()` (L75)
- `class TestNumGpuFor` (L95)
  - `_clear()` (L96)
  - `test_explicit_override_wins()` (L100)
  - `test_negative_means_auto()` (L108)
  - `test_unset_defaults_auto()` (L117)
  - `test_nonnumeric_env_defaults_auto()` (L125)
  - `test_zero_forces_cpu()` (L133)
- `class TestRuntimeStats` (L142) — Section E G5: steady-stream telemetry + adaptive cadence (pure logic).
  - `test_record_and_snapshot()` (L145)
  - `test_adaptive_sleep()` (L158)
- `class TestRoleMemory` (L182) — Section E G6: per-role memory + long-term notes (SummarizerDB).
  - `setUp()` (L185)
  - `tearDown()` (L193)
  - `test_role_isolation()` (L201)
  - `test_summary_compaction()` (L208)
  - `test_clear_and_notes()` (L222)
- `class TestGuiTabs` (L236) — Section E GUI (A1/A2/A3/A5): scroll-wrap, new tabs, lazy-build.
  - `setUp()` (L241)
  - `tearDown()` (L253)
  - `test_new_tabs_present()` (L285)
  - `test_lazy_then_scroll_on_open()` (L320)
  - `test_post_move_widgets_exist()` (L335)
  - `test_refresh_db_stats_guarded_when_lazy()` (L349)
  - `test_db_stats_tab_starts_auto_refresh()` (L354)
  - `test_provider_status_override_persists_after_redetect()` (L359)


### `tests/gui/test_self_improve_monitor_timer.py` — Task 10b — background self-improvement post-apply monitor timer. (86L)

**Functions:**
- `qt_app()` (L18)
- `_harness()` (L25) — A minimal QObject exposing the two monitor methods + needed attrs.
- `test_monitor_not_started_when_feature_disabled(qt_app, monkeypatch)` (L42)
- `test_monitor_started_when_feature_enabled(qt_app, monkeypatch)` (L51)
- `test_monitor_interval_clamped(qt_app, monkeypatch)` (L61)
- `test_monitor_run_calls_service_and_logs_regressions(qt_app, monkeypatch)` (L69)
- `test_monitor_run_noop_without_service(qt_app, monkeypatch)` (L80)


### `tests/gui/test_self_improvement_tab.py` — Headless smoke test for the Self-Improvement tab's code-patch section. (122L)

**Functions:**
- `app()` (L23)
- `_make_tab(app)` (L28)
- `test_tab_builds_and_shows_pending_patch(app)` (L56)
- `test_tab_approve_applies_patch(app)` (L103)


### `tests/gui/test_settings_web_discovery_toggle.py` — Phase E — Settings-tab web-discovery toggle is a LIVE control (ARCH-ENG-087). (77L)

**Functions:**
- `_env_bool(name, default=False)` (L17)
- `_env_bool_from_text(text, name)` (L67)

**Classes:**
- `class TestWebDiscoveryToggleSeed` (L26)
  - `setUp()` (L27)
  - `tearDown()` (L30)
  - `test_seed_defaults_off()` (L35)
  - `test_seed_reflects_env_true()` (L39)
  - `test_seed_reflects_env_false()` (L43)
- `class TestWebDiscoveryTogglePersists` (L48) — A checked toggle must write ALLOW_WEB_DISCOVERY the runtime consumes.
  - `test_checked_round_trips_to_env()` (L51)


### `tests/gui/test_slot_lifecycle.py` — Tests for the N-brain lifecycle backend slot handlers (Phase 5). (616L)

**Functions:**
- `_wait_detected(app, timeout=12)` (L19)
- `_cpu_slot_index(w)` (L36) — Return the runtime slot index bound to the CPU/RAM pool, or None.
- `_row_for_slot(w, slot)` (L49) — Return the provider row whose .slot == slot (index != slot when a
- `_settings_row_for_slot(w, slot)` (L58)

**Classes:**
- `class TestSlotLifecycle` (L65)
  - `setUpClass()` (L67)
  - `_widget()` (L70)
  - `test_slot_config_accessor()` (L78)
  - `test_slot2_cpu_config_forces_system_ram()` (L93)
  - `test_slot_launch_command_targets_slot_port()` (L106)
  - `test_stop_slot_is_safe_when_not_running()` (L120)
  - `test_row_start_routes_slot2_to_start_slot()` (L129)
  - `test_row_stop_routes_slot2_to_stop_slot()` (L145)
  - `test_start_all_starts_every_enabled_slot()` (L162) — 'Start All Brains' must launch every enabled slot (0/1 via the Big/
  - `test_slot_launch_schedules_status_reprobe()` (L188) — After a slot 2+ launch succeeds, a bounded re-probe is scheduled so the
- `class TestDevicePolicyLiveRebuild` (L205) — Phase 6: toggling a device rebuilds rows and stops its brain.
  - `setUpClass()` (L209)
  - `_widget()` (L212)
  - `_cpu_device()` (L220)
  - `test_disable_device_stops_its_brain_and_shrinks_rows()` (L224)
  - `test_reenable_device_restores_rows()` (L269)
  - `test_stop_brain_on_disabled_device_routes_by_slot()` (L301)
- `class TestPerSlotModelSelection` (L327) — Every provider row has a model dropdown (issue: only 2 devices could
  - `setUpClass()` (L332)
  - `_widget()` (L335)
  - `_cpu_device()` (L343)
  - `test_every_row_has_a_model_dropdown()` (L347)
  - `test_selecting_model_on_slot2_sets_config_and_policy()` (L358)
  - `test_model_dropdown_signal_routes_to_handler()` (L385)
- `class TestRowStatusNotStuckChecking` (L403) — Every row shows Stopped (not a stuck 'Checking...') at startup when
  - `setUpClass()` (L408)
  - `_widget()` (L411)
  - `test_initial_status_is_stopped_not_checking()` (L419) — A freshly built widget rests at '● Stopped' (never the stuck
  - `test_per_slot_probe_updates_all_rows()` (L432) — The status refresh must deliver a probe entry for EVERY enabled slot
  - `test_apply_slot_statuses_marks_running()` (L458)
  - `test_apply_slot_statuses_ignores_out_of_range()` (L479)
- `class TestPerDeviceSettings` (L496) — Every enabled device (incl CPU/slot 2+) has editable llama.cpp settings
  - `setUpClass()` (L501)
  - `_widget()` (L504)
  - `_cpu_device()` (L512)
  - `test_every_slot_has_a_settings_row()` (L516)
  - `test_cpu_settings_row_locks_gpu_layers()` (L529)
  - `test_temperature_seeds_from_persisted_env()` (L542)
  - `test_changing_cpu_context_applies_and_persists()` (L565)
  - `test_settings_round_trip_through_sync_slots()` (L586)


### `tests/gui/test_social_activity_moltbook.py` — Phase E — Moltbook feed worker + gated Social-Activity posting (ARCH-ENG-088). (76L)

**Classes:**
- `class TestMoltbookFeedWorkerRows` (L15) — Exercise the worker's normalization logic directly (no Qt event loop).
  - `_normalize(feed)` (L18)
  - `test_normalizes_posts()` (L37)
  - `test_handles_empty_and_junk()` (L50)
  - `test_worker_importable()` (L55)
- `class TestSocialPostQueuesApproval` (L60)
  - `test_post_action_enqueues_pending_approval()` (L61) — The GUI action must enqueue a PENDING approval, not post directly.


### `tests/gui/test_status_liveness_poller.py` — Periodic provider-status liveness poller (v2.1.60, ARCH-ENG-073). (120L)

**Functions:**
- `_wait_detected(app, timeout=12)` (L35)

**Classes:**
- `class TestStatusLivenessPoller` (L42)
  - `setUpClass()` (L44)
  - `_widget()` (L47)
  - `test_status_timer_exists_and_is_running()` (L55) — A periodic QTimer drives the provider probe while the panel is open.
  - `test_timer_is_wired_to_refresh()` (L71) — The timer's timeout is connected to _refresh_provider_status.
  - `test_cleanup_stops_the_timer()` (L83) — cleanup() stops the poller so it can't fire on a destroyed widget.
  - `test_refresh_skips_when_previous_probe_alive()` (L94) — _refresh_provider_status must not pile up threads when a prior probe


### `tests/gui/test_system_ram_contention_guard.py` — System-RAM contention guard for brain launch (v2.1.55, ARCH-ENG-055). (125L)

**Functions:**
- `_worker(model=SMALL_MODEL, port=1235, cfg=None)` (L35)

**Classes:**
- `class _FakeCfg` (L29)
  - `__init__(context=32768, kv_cache='f16')` (L30)
- `class TestSystemRamContentionGuard` (L45)
  - `test_warns_when_combined_footprint_exceeds_headroom(monkeypatch)` (L46) — Crash-time inputs (19 GB free, big brain resident 8.2 GB) must warn.
  - `test_no_warn_when_plenty_of_ram(monkeypatch)` (L59) — Negative control: abundant RAM + nothing else running -> silent.
  - `test_lowering_context_removes_warning(monkeypatch)` (L68) — The named fix (lower context) actually resolves the risk.
  - `test_headroom_threshold_respected(monkeypatch)` (L78) — Above the 4 GB floor -> silent; clearly below -> warns.
  - `test_guard_never_raises_on_bad_inputs(monkeypatch)` (L99) — A probe failure must degrade to no-warning, never crash the launch.
- `class TestRamProbes` (L110)
  - `test_available_ram_reader_returns_positive()` (L111) — The ctypes GlobalMemoryStatusEx reader works on this host.
  - `test_other_servers_reader_is_safe_with_no_servers()` (L116) — No llama-servers running -> (0.0, []), never an exception.


### `tests/gui/test_teardown_signal_disconnect.py` — Teardown signal-disconnect safety (v2.1.61, ARCH-ENG-074). (169L)

**Functions:**
- `_disconnect_worker_signals(worker)` (L63) — Delegate to the REAL MainWindow._disconnect_worker_signals.

**Classes:**
- `class _FakeWorker(QThread)` (L46) — A worker with cross-thread signals, like the real chat/dialogue workers.
  - `__init__()` (L53)
  - `run()` (L57)
- `class TestTeardownSignalDisconnect` (L76)
  - `setUpClass()` (L78)
  - `test_disconnect_worker_signals_detaches_receiver()` (L81) — After disconnecting, a late emission cannot reach the receiver.
  - `test_connected_worker_would_deliver()` (L96) — Control: without disconnecting, the emission IS delivered — proving
  - `test_disconnect_is_idempotent()` (L107) — Disconnecting an already-disconnected (or unconnected) worker never
  - `test_isSignal_absent_methodType_is_the_detector()` (L115) — Regression guard for ARCH-ENG-074: this PySide6 (6.11) has NO
- `class TestTabCleanupExists` (L146)
  - `setUpClass()` (L148)
  - `test_chat_and_dialogue_tabs_expose_cleanup()` (L151) — main.py's _stop_tab_background_threads calls cleanup() on tabs that


### `tests/providers/__init__.py` — Providers tests. (2L)


### `tests/providers/test_model_bands.py` — Model-size bands use explicit runtime parameter semantics. (125L)

**Classes:**
- `class TestModelBands` (L10)
  - `test_dense_boundaries()` (L11)
  - `test_moe_uses_active_parameters_only_when_explicit()` (L20)
  - `test_model_info_displays_total_and_active_sizes()` (L27)
  - `test_unknown_size_is_explicit()` (L40)
  - `test_parameter_inference_requires_explicit_notation()` (L44)
  - `test_huggingface_model_uses_same_band_contract()` (L49)
  - `test_cpu_only_small_brain_gets_conservative_context_defaults()` (L60)
  - `test_explicit_cpu_context_override_wins()` (L68)
- `class TestCpuDecisionModelSelection` (L76) — v2.1.50 (ARCH-ENG-050): CPU/RAM mode must never launch an oversized model.
  - `test_oversized_model_is_rejected_for_cpu()` (L85)
  - `test_small_model_is_accepted_for_cpu()` (L96)
  - `test_choose_prefers_smallest_eligible_over_big()` (L101)
  - `test_configured_cpu_model_wins_when_eligible()` (L115)


### `tests/providers/test_model_recommendations.py` — Phase G4 — per-model recommended settings resolver (ARCH-ENG-095). (64L)

**Classes:**
- `class TestRecommend` (L18)
  - `test_unknown_path_safe_defaults()` (L19)
  - `test_mtp_reported_only_when_head_present()` (L29)
  - `test_dense_gemma_mtp_off()` (L41)
  - `test_all_families_have_required_keys()` (L48)
  - `test_summary_is_readable()` (L55)


### `tests/providers/test_nvidia_nim.py` — Tests for NVIDIA NIM support + OpenAI-compatible streaming/reasoning (v2.0.36). (303L)

**Classes:**
- `class TestNvidiaProviderRegistration` (L25)
  - `test_nvidia_registered()` (L26)
  - `test_nvidia_is_fetchable()` (L34)
- `class TestNvidiaFreeFallback` (L39)
  - `test_currated_free_list_all_free_and_contains_lightning()` (L40)
  - `test_fetch_fallback_used_when_live_empty()` (L51) — When NVIDIA live fetch returns nothing, the curated FREE list is returned.
- `class TestNvidiaLiveFetchReachable` (L66)
  - `test_live_fetch_returns_models()` (L67) — Network-dependent: NVIDIA /v1/models is public. Skips if offline/blocked.
- `class TestNvidiaLiveNotFalselyFree` (L85)
  - `test_live_models_not_flagged_free()` (L86) — Live NVIDIA models with unknown pricing show n/a, never FREE.
- `class TestOpenAICompatibleStreaming` (L100)
  - `_install_fake_openai(stream_chunks)` (L101) — Install a fake `openai` module that yields `stream_chunks` and records
  - `test_streams_and_captures_reasoning_and_enable_thinking()` (L148)
  - `test_temperature_and_top_p_forwarded()` (L181)
  - `test_non_streaming_fallback_on_typeerror()` (L197) — If create(**kwargs) raises TypeError (stream/extra_body unsupported),
- `class TestOtherAdaptersUnaffected` (L239)
  - `test_ollama_ignores_think_kwarg()` (L240)
  - `test_anthropic_ignores_think_kwarg()` (L247)
- `class TestBaseWorkerForwardsThink` (L254)
  - `test_llm_passes_think_flag()` (L255) — base_worker.llm() forwards `think` to the provider function.


### `tests/providers/test_openai_stream_timeout.py` — (no module docstring) (47L)

**Classes:**
- `class _FakeCompletions` (L11)
  - `create(**_kwargs)` (L12)
- `class _FakeOpenAIClient` (L18)
  - `__init__(**kwargs)` (L21)
- `class TestOpenAIStreamTimeout` (L27)
  - `test_streaming_client_receives_timeout()` (L28)
  - `test_timeout_is_bounded_and_invalid_values_use_default()` (L38)


### `tests/providers/test_provider_selection.py` — Provider selection must follow enabled configuration, not detection order. (159L)

**Classes:**
- `class TestProviderSelection` (L13)
  - `test_normalizes_lm_studio_name()` (L14)
  - `test_resolves_enabled_local_provider()` (L20)
  - `test_returns_none_when_all_roles_are_disabled()` (L31)
  - `test_lm_studio_is_configurable_when_server_is_stopped()` (L42)
  - `test_lm_studio_model_refresh_uses_openai_models_endpoint()` (L55)
  - `test_role_model_selection_is_read_from_runtime_environment()` (L71)
  - `test_role_model_is_empty_without_explicit_selection()` (L84)
  - `test_local_launch_requires_selected_or_saved_model()` (L91)
  - `test_local_model_selection_updates_runtime_and_environment()` (L98)
  - `test_lm_studio_loaded_instances_are_detected()` (L111)
  - `test_model_selection_does_not_persist_without_explicit_save()` (L124)
  - `test_external_model_lifecycle_uses_native_endpoints()` (L137)
  - `test_model_matching_accepts_full_gguf_path_and_server_basename()` (L149)

