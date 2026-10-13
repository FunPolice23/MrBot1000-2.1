<!-- generated 46 files -->

### `tests/safety/__init__.py` — Safety tests. (2L)


### `tests/safety/test_approval_queue.py` — tests/test_approval_queue.py — Human-approval queue integrity tests. (245L)

**Classes:**
- `class TestApprovalQueueIntegrity` (L18) — Test human approval queue persistence, transitions, and recovery.
  - `setUp()` (L21) — Create a temporary log file and fresh queue instance.
  - `tearDown()` (L28) — Clean up temporary files.
  - `test_persistence_on_enqueue()` (L35) — Items are persisted to JSON when enqueued.
  - `test_persistence_on_decision()` (L52) — Decisions are persisted to JSON.
  - `test_restart_recovery()` (L71) — Queue recovers state after restart.
  - `test_duplicate_id_handling()` (L99) — Duplicate IDs are handled gracefully (new ID generated).
  - `test_transition_validation()` (L121) — Invalid status transitions are rejected.
  - `test_payload_redaction_on_approve()` (L138) — Sensitive payload is preserved but not exposed in notifications.
  - `test_callback_persistence()` (L164) — On-change callbacks are called on state changes.
  - `test_clear_all_persists()` (L183) — Clearing all items persists the empty state.
  - `test_missing_log_path_no_error()` (L204) — Queue works without log path (in-memory only).
  - `test_concurrent_access_safety()` (L218) — Queue operations are thread-safe.


### `tests/safety/test_authorized_actions.py` — (no module docstring) (39L)

**Classes:**
- `class TestAuthorizedActionDispatcher` (L7)
  - `test_read_only_dispatch_runs_handler()` (L8)
  - `test_mutation_requires_explicit_approval()` (L14)
  - `test_approved_mutation_runs_handler()` (L23)
  - `test_unknown_action_is_blocked()` (L31)


### `tests/safety/test_instruction_gate.py` — (no module docstring) (107L)

**Classes:**
- `class _FakeFetcher` (L13)
  - `__init__(content_map)` (L14)
- `class TestInstructionGate` (L25)
  - `setUp()` (L26)
  - `tearDown()` (L41)
  - `test_blacklisted_url_never_fetched()` (L48)
  - `test_unknown_instruction_quarantined_pending_untrusted()` (L62)
  - `test_approve_moves_to_allowlist()` (L68)
  - `test_hash_reuse_mirrors_prior_review()` (L80)
  - `test_dns_resolution_failure_is_rejected()` (L92)
  - `test_ipv6_loopback_is_rejected()` (L98)


### `tests/safety/test_provider_rate_limiter.py` — Phase F3 — per-provider rate limit + daily budget (ARCH-ENG-091). (123L)

**Classes:**
- `class TestProviderClassification` (L16)
  - `test_local_providers()` (L17)
  - `test_cloud_providers()` (L22)
- `class TestProviderRateLimiter` (L28)
  - `setUp()` (L29)
  - `_set_db(limiter)` (L41)
  - `test_provider_aware_defaults()` (L44)
  - `test_rate_limit_blocks_burst()` (L51)
  - `test_daily_cap_refuses_after_n()` (L61)
  - `test_local_never_dollar_capped()` (L72)
  - `test_counter_survives_reinit()` (L85)
  - `test_check_does_not_consume()` (L95)
- `class TestTokenBucketTryAcquire` (L106)
  - `test_nonblocking()` (L107)
  - `test_blocking_with_timeout_waits()` (L113)


### `tests/safety/test_query_db_multidb.py` — Phase D1 — query_db multi-DB read access (ARCH-ENG-083). (63L)

**Classes:**
- `class TestResolveDbPath` (L21)
  - `test_known_stores_resolve()` (L22)
  - `test_default_is_agent_db()` (L29)
  - `test_unknown_and_traversal_rejected()` (L33)
- `class TestQueryDbTool` (L39)
  - `test_reads_named_store()` (L40)
  - `test_unknown_db_reported_not_crashed()` (L47)
  - `test_write_still_refused()` (L51)
  - `test_default_db_back_compat()` (L55)


### `tests/safety/test_record_payment_gate.py` — Phase D2 — record_payment tool: HIGH-TRUST, approval-gated (ARCH-ENG-084). (94L)

**Functions:**
- `_enqueue_and_approve(queue, approve=...) -> str` (L37)

**Classes:**
- `class _StubState` (L23)
  - `__init__()` (L24)
- `class _StubTracker` (L28)
  - `__init__()` (L29)
  - `mark_paid_verified(opp_id, amount=..., evidence=...)` (L32)
- `class TestRecordPaymentGate` (L44)
  - `setUp()` (L45)
  - `tearDown()` (L50)
  - `_call(args)` (L53)
  - `test_requires_dispatcher_capability()` (L56)
  - `test_rejects_nonpositive_amount()` (L63)
  - `test_rejects_missing_approval_id()` (L69)
  - `test_rejects_pending_approval()` (L74)
  - `test_records_behind_approved_approval()` (L80)


### `tests/safety/test_safe_mode_pipeline.py` — (no module docstring) (111L)

**Classes:**
- `class TestSafeModePipeline` (L12)
  - `test_safe_mode_skips_writing_files()` (L13)
  - `test_safe_path_blocks_parent_traversal()` (L30)
  - `test_safe_path_blocks_prefix_collision_sibling()` (L45)
  - `test_safe_path_allows_in_root_file()` (L69)
  - `test_validator_failure_blocks_execution()` (L84)


### `tests/safety/test_safety_gate_registry_alignment.py` — Alignment tests between SafetyGate and the real tool registry. (112L)

**Classes:**
- `class TestSafetyGateRegistryAlignment` (L29)
  - `_dispatched_names() -> set` (L30)
  - `test_every_dispatched_tool_is_classified()` (L33)
  - `test_every_schema_tool_is_classified()` (L38)
  - `test_mutating_denylist_matches_safety_gate()` (L44)
  - `test_readonly_and_mutating_sets_are_disjoint()` (L47)
  - `test_gate_allows_readonly_and_gates_state_changing_tools()` (L50)
  - `test_unknown_tool_is_blocked()` (L63)
  - `test_legacy_aliases_still_resolve_to_real_tools()` (L68)
  - `test_execute_tool_does_not_run_an_unknown_tool()` (L74)
- `class TestAutoApproveReadonlyFlag` (L79) — ``auto_approve_readonly`` must actually change behaviour, not just sit
  - `test_default_still_auto_approves_readonly()` (L84)
  - `test_disabling_forces_readonly_through_approval()` (L92)
  - `test_disabling_does_not_weaken_mutating_gate()` (L101)


### `tests/safety/test_social_post_gate.py` — Phase D3 — social_post tool: HIGH-TRUST, approval-gated, no fabrication (ARCH-ENG-085). (81L)

**Classes:**
- `class TestSocialPostGate` (L22)
  - `setUp()` (L23)
  - `tearDown()` (L27)
  - `_approval(approve=...)` (L30)
  - `_call(args)` (L36)
  - `test_requires_dispatcher_capability()` (L39)
  - `test_requires_approval_id()` (L45)
  - `test_rejects_pending_approval()` (L49)
  - `test_refuses_without_confirmed_writer_no_fabrication()` (L54)
  - `test_posts_behind_approved_approval_with_writer()` (L62)


### `tests/safety/test_sql_tool_safety.py` — (no module docstring) (61L)

**Classes:**
- `class TestSqlToolSafety` (L12)
  - `setUp()` (L13)
  - `tearDown()` (L21)
  - `test_select_returns_rows()` (L24)
  - `test_malformed_and_mutating_sql_are_rejected()` (L29)
  - `test_connection_is_closed_after_success_and_failure()` (L41)
  - `test_safety_gate_blocks_invalid_query_before_allowing_it()` (L49)


### `tests/safety/test_tool_calling_safety.py` — Regression tests for ordinary chat tool execution boundaries. (196L)

**Classes:**
- `class TestToolCallingSafety` (L13)
  - `test_web_search_result_contract_marks_discovery_and_backend()` (L14)
  - `test_web_search_falls_back_when_primary_backend_fails()` (L28)
  - `test_account_profile_rejects_raw_secrets()` (L54)
  - `test_account_and_profile_actions_require_human_gates()` (L65)
  - `test_mutating_tools_are_refused_without_human_approval()` (L76)
  - `test_mutation_implementations_require_dispatch_capability()` (L86)
  - `test_skill_documents_are_quarantined()` (L97)
  - `test_function_tool_execution_populates_verified_trace()` (L117)
  - `test_pending_approval_is_not_reported_as_completed()` (L149)
  - `test_streamed_reasoning_channel_is_used_when_content_is_empty()` (L175)


### `tests/safety/test_tool_safety.py` — (no module docstring) (32L)

**Classes:**
- `class TestToolSafety` (L7)
  - `test_relative_paths_stay_inside_project()` (L8)
  - `test_parent_traversal_is_rejected()` (L13)
  - `test_command_is_parsed_without_shell_operators()` (L17)
  - `test_command_cwd_is_project_bound()` (L25)


### `tests/safety/test_tool_syntax_strip_registry.py` — The persona-facing tool-name stripper must derive its names from the registry. (117L)

**Classes:**
- `class TestToolSyntaxStripIsRegistryDerived` (L22)
  - `test_pattern_covers_every_registered_tool()` (L23) — No registered tool may be missing from the strip alternation.
  - `test_pattern_contains_no_unregistered_name()` (L29) — The stripper must not invent tool names the registry does not have.
  - `test_stripper_does_not_duplicate_the_registry_literal()` (L35) — Guard against re-introducing a hand-typed copy of the registry.
  - `test_every_registered_tool_is_stripped_as_a_bare_leak()` (L86) — Each registered tool's bare name leaks nothing when it stands alone.
  - `test_real_prose_mentioning_a_tool_is_preserved()` (L100) — Deriving the list must not start mangling legitimate answers.


### `tests/safety/test_trust_boundary.py` — (no module docstring) (85L)

**Classes:**
- `class TestTrustBoundary` (L13)
  - `test_high_trust_always_requires_human()` (L14)
  - `test_low_trust_ai_allowed_with_untrusted_instruction_blocked()` (L23)
  - `test_ai_disallowed_forces_human_for_all()` (L29)
- `class TestPlatformAdapters` (L36)
  - `_gate()` (L37)
  - `test_fiverr_lists_actions()` (L47)
  - `test_fiverr_submit_requires_human()` (L52)
  - `test_reddit_post_blocked_without_human()` (L62)
  - `test_adapter_fetch_routes_through_gate()` (L68)


### `tests/evidence/__init__.py` — Evidence tests. (2L)


### `tests/evidence/test_crypto_payout_snapshot_gate.py` — A wallet balance is not a payout: crypto verification needs both snapshots. (152L)

**Functions:**
- `_evidence(ve, subject='opp')` (L52)

**Classes:**
- `class _Wallet` (L42) — A wallet whose absolute balance is whatever the test says.
  - `__init__(usd)` (L45)
  - `get_balance(_name)` (L48)
- `class TestCryptoPayoutNeedsBothSnapshots` (L56)
  - `setUp()` (L57)
  - `test_pre_existing_balance_is_not_a_payout()` (L60) — The F4 regression: a $500 wallet and a $5 payout must book $0.
  - `test_every_partial_snapshot_combination_is_unverified()` (L68) — No snapshot pair may ever produce a verified crypto payout.
  - `test_real_delta_verifies_and_books_only_the_delta()` (L77) — A genuine payout is still verified — and books the delta, not the total.
  - `test_small_delta_does_not_satisfy_a_larger_expectation()` (L86) — A $5 gain cannot verify a $100 expectation.
  - `test_unverified_evidence_never_counts_as_revenue()` (L93) — The accounting gate, asserted end-to-end rather than assumed.
  - `test_missing_wallet_still_fails_closed()` (L103)
- `class TestAccountingAccessorsMatchGetProfile` (L108) — F6: the quick accessors used a weaker rule than get_profile.
  - `_acct(store)` (L111)
  - `test_l1_attestation_is_not_verified_revenue()` (L115) — An L1 manual_attestation must count 0 in BOTH accessors.
  - `test_l3_verified_payment_counts()` (L133)


### `tests/evidence/test_evidence.py` — tests/test_evidence.py — Evidence subsystem domain + store + policy (v2.0.34aq). unittest style. (125L)

**Classes:**
- `class TestEvidence` (L13)
  - `test_evidence_immutable_verify_appends_history()` (L14)
  - `test_status_enum_has_six_values()` (L27)
  - `test_conflicted_on_api_error()` (L32)
  - `test_verification_levels_ordering()` (L43)
  - `test_is_verified_respects_min_level()` (L47)
  - `test_store_append_only_and_query()` (L55)
  - `test_policy_submitted_to_paid_requires_evidence()` (L72)
  - `test_unknown_transition_is_not_eligible()` (L90)
  - `test_revenue_eligibility_split()` (L93)
  - `test_manual_attestation_stays_pending_not_hard()` (L106)
  - `test_claim_is_not_trusted_evidence()` (L116)


### `tests/evidence/test_evidence_au.py` — tests/test_evidence_au.py — Extensive Evidence & Verification subsystem tests (v2.0.34au). (439L)

**Functions:**
- `_store()` (L52)

**Classes:**
- `class _FakeReport` (L46) — Minimal duck-typed report for factory tests.
  - `__init__(**kw)` (L48)
- `class TestEvidenceModel` (L57)
  - `test_status_enum_has_all_six()` (L58)
  - `test_methods_include_spec_set()` (L63)
  - `test_immutable_verify_returns_new()` (L70)
  - `test_confidence_is_deterministic_not_llm()` (L81)
  - `test_dup_key_stable_and_content_based()` (L92)
  - `test_llm_claim_cannot_be_verified()` (L108)
- `class TestConflictingEvidence` (L116)
  - `test_two_sources_disagree_is_conflicted()` (L117)
  - `test_conflicted_record_blocks_transition()` (L148)
- `class TestDuplicateEvidence` (L160)
  - `test_store_flags_duplicate_content()` (L161)
  - `test_same_id_append_only_history()` (L180)
- `class TestUnverifiableEvidence` (L199)
  - `test_no_source_observation_stays_unverified()` (L200)
  - `test_unverifiable_blocks_revenue()` (L210)
- `class TestEvidenceFromDifferentSources` (L220)
  - `test_multiple_producers_recorded()` (L221)
- `class TestUnverifiedToVerified` (L238)
  - `test_transition_via_mark_verified()` (L239)
  - `test_reconcile_promotes_conflicted()` (L250)
  - `test_reconcile_refuses_manual_escalation()` (L258)
- `class TestPaymentEvidence` (L268)
  - `test_make_money_set_and_revenue_split()` (L269)
  - `test_manual_payment_stays_pending()` (L279)
- `class TestCryptoEvidence` (L297)
  - `test_balance_delta_is_cryptographic()` (L298)
  - `test_blockchain_receipt_factory()` (L308) — A blockchain receipt maps to VERIFIED evidence when the report says so.
  - `test_receipt_report_verified_promotes_transition()` (L322)
- `class TestPlatformEvidence` (L331)
  - `test_upwork_submission_verified_l3()` (L332)
  - `test_submission_gates_transition()` (L339)
- `class TestManualEvidence` (L344)
  - `test_manual_attestation_lower_confidence_than_crypto()` (L345)
  - `test_payout_verifier_manual_attestation()` (L360)
- `class TestPersistenceAcrossRestart` (L371)
  - `test_evidence_survives_db_reopen()` (L372)
- `class TestLifecycleIntegration` (L397)
  - `test_reconcile_hook_promotes_payment()` (L398)
  - `test_mark_paid_verified_gated_by_policy()` (L417)
- `class _OppLike` (L429)
  - `__init__(oid)` (L430)


### `tests/evidence/test_evidence_audit_fixups.py` — tests/test_evidence_audit_fixups.py — regression tests for the v2.0.34aq audit fixes. (64L)

**Classes:**
- `class FakeWallet` (L21)
  - `__init__(usd)` (L22)
  - `get_balance(name=None)` (L23)
- `class TestAuditFixups` (L26)
  - `_life()` (L27)
  - `test_crypto_only_l5_marks_paid_without_submission()` (L31)
  - `test_unverified_crypto_does_not_mark_paid()` (L42)
  - `test_factory_maps_crypto_to_opportunity_and_l5()` (L52)


### `tests/evidence/test_evidence_integration.py` — tests/test_evidence_integration.py — full Evidence loop through the lifecycle (v2.0.34aq). unittest style. (87L)

**Classes:**
- `class TestEvidenceIntegration` (L14)
  - `test_submission_evidence_gates_paid_transition()` (L15)
  - `test_conflicted_submission_does_not_verify()` (L48)
  - `test_chain_receipt_becomes_evidence()` (L57)
  - `test_revenue_split_verified_vs_pending()` (L67)


### `tests/evidence/test_evidence_payout_path.py` — tests/test_evidence_payout_path.py — reproduces the main.py payout verification path (100L)

**Classes:**
- `class FakeWallet` (L16)
  - `__init__(usd)` (L17)
  - `get_balance(name=None)` (L18)
- `class TestPayoutPath` (L21)
  - `test_verification_evidence_is_plain_dataclass_not_evidence()` (L22)
  - `test_mark_paid_verified_accepts_verification_evidence_no_crash()` (L30)
  - `test_unverified_crypto_does_not_mark_paid()` (L65)
  - `test_factory_from_verification_evidence_maps_fields()` (L88)


### `tests/evidence/test_live_trading.py` — (no module docstring) (198L)

**Functions:**
- `_intent(asset_class='major', amount=1.0)` (L30)
- `_live(service)` (L40) — Assess against the same live state execute_order re-reads.

**Classes:**
- `class FakeAdapter` (L10)
  - `__init__()` (L13)
  - `fetch_balance()` (L16)
  - `fetch_ticker(symbol)` (L19)
  - `fetch_order_book(symbol)` (L22)
  - `create_order(*args)` (L25)
- `class TestLiveTrading` (L53)
  - `test_portfolio_reads_adapter_state()` (L54)
  - `test_portfolio_fails_when_crypto_cannot_be_valued()` (L60)
  - `test_status_is_disabled_without_adapter_even_when_flagged()` (L66)
  - `test_coinbase_adapter_can_be_constructed_without_sandbox()` (L70)
  - `test_market_snapshot_uses_ticker_and_order_book()` (L75)
  - `test_market_snapshot_rejects_incomplete_order_book()` (L82)
  - `test_market_snapshot_rejects_crossed_order_book()` (L88)
  - `test_exchange_mismatch_is_rejected()` (L96)
  - `test_stale_market_data_is_rejected()` (L105)
  - `test_disabled_service_never_submits()` (L114)
  - `test_high_risk_meme_requires_approval()` (L123)
  - `test_policy_can_preapprove_low_risk_order()` (L131)
  - `test_daily_loss_blocks_orders()` (L150)
  - `test_buy_above_free_cash_is_blocked()` (L159)
  - `test_sell_above_holdings_is_blocked()` (L169)
  - `test_order_proposal_uses_approval_queue()` (L181)


### `tests/evidence/test_numeric_evidence.py` — Tests for the deterministic monetary-evidence check. (102L)

**Classes:**
- `class TestNumericEvidence` (L26)
  - `test_value_quoted_from_context_is_supported()` (L27)
  - `test_scientific_notation_from_context_is_supported()` (L31)
  - `test_comma_form_is_normalised_against_plain_form()` (L35)
  - `test_invented_value_is_flagged()` (L40)
  - `test_mixed_response_flags_only_the_invented_value()` (L44)
  - `test_empty_context_flags_every_cited_value()` (L49)
  - `test_no_monetary_values_produces_no_findings()` (L53)
  - `test_zero_is_handled()` (L56)
  - `test_duplicate_citations_reported_once()` (L60)
  - `test_has_unsupported_values_helper()` (L64)
  - `test_extract_deduplicates_and_keeps_order()` (L68)
  - `test_values_beyond_context_precision_do_not_collapse()` (L72) — Regression: normalize() rounded to 28 sig digits and merged distinct values.
  - `test_scientific_values_beyond_precision_stay_distinct()` (L84)
  - `test_equal_values_in_different_forms_still_match()` (L90) — Exact comparison must still treat 1.0 and 1.00 as the same value.
  - `test_unparseable_tokens_are_ignored()` (L96)


### `tests/evidence/test_paper_trading.py` — (no module docstring) (69L)

**Classes:**
- `class TestPaperTradingEngine` (L9)
  - `test_rejects_zero_price_and_excessive_notional()` (L10)
  - `test_zero_starting_balance_has_safe_performance_metrics()` (L16)
  - `test_closed_position_keeps_realized_pnl_in_performance()` (L21)
  - `test_performance_is_explicitly_virtual_and_orders_are_audited()` (L31)
  - `test_invalid_finite_inputs_are_rejected_or_raise()` (L42)
  - `test_audit_log_survives_engine_restart()` (L50)
  - `test_paper_engine_has_no_external_execution_path()` (L60)


### `tests/evidence/test_payment_evidence.py` — Tests for the shared payment-evidence vocabulary. (32L)

**Classes:**
- `class TestPaymentEvidenceVocabulary` (L10)
  - `test_accounting_uses_shared_broad_vocabulary()` (L11)
  - `test_transition_vocabulary_is_explicit_subset()` (L17)
  - `test_legacy_payment_labels_remain_accounting_observations()` (L24)


### `tests/engineering/test_cycle_071_075.py` — ARCH-ENG-081..087 — the findings left unresolved at the end of v2.1.57. (767L)

**Functions:**
- `test_guard_flags_action_when_verb_is_in_action_type()` (L22) — platform_submitter puts 'submit_proposal' in action_type, not name.
- `test_guard_flags_payment_when_verb_is_in_action_type()` (L45) — real_crypto_operator uses the same action_type/name convention.
- `test_guard_still_flags_when_verb_is_in_name()` (L62) — The original matching path must not regress.
- `test_guard_still_allows_ordinary_reads()` (L72) — The widened match must not start flagging read-only traffic.
- `test_submitter_end_to_end_reaches_awaiting_approval()` (L83) — The whole request_approval path now yields a real pending approval.
- `test_submitter_submit_rejects_the_kwarg_the_gui_used()` (L101) — Locks in the API shape the GUI must call (record, not proposal_text).
- `test_earning_tab_submit_handler_uses_the_gated_flow()` (L110) — The GUI handler must prepare -> request approval -> submit.
- `test_dispatch_passes_the_capability_so_mutating_tools_can_run()` (L130) — Handlers refuse without the dispatch capability.
- `test_dispatch_source_passes_the_capability()` (L144)
- `test_every_read_only_tool_still_dispatches()` (L152) — Passing authorization= to a handler that does not declare it is a TypeError.
- `test_accepts_authorization_only_for_mutating_handlers()` (L170)
- `test_approved_execute_tool_can_run_an_approved_mutating_tool(tmp_path)` (L191) — approved=True is the human's decision and must reach the handler.
- `test_approved_does_not_unblock_a_blocked_tool()` (L211) — The human's approval must not be bypass a BLOCKED tool.
- `test_alias_behaves_exactly_like_its_canonical_target()` (L255) — ARCH-ENG-090: an alias must not be a separate, stricter classification.
- `test_unapproved_mutating_tool_is_still_pending()` (L294) — Without approval the action must not execute.
- `_action_item(target)` (L302)
- `test_approved_gui_decision_ignores_a_forged_signal_status()` (L317) — The queue's recorded decision is authoritative, not the signal argument.
- `_load_main_handler_source()` (L362)
- `test_approved_gui_decision_executes_the_queued_payload()` (L371) — An approved ACTION item must actually run, not sit in the queue.
- `_loop_with_stub()` (L422)
- `_new_result()` (L431) — Build the AutonomousResult the loop would create for its opportunity.
- `test_begin_run_writes_the_ledger_before_stage_one()` (L437)
- `test_begin_run_does_not_mark_the_idempotency_key()` (L444) — A paused/rejected run must stay re-entry-able.
- `test_replay_of_an_irreversible_opportunity_is_refused()` (L457)
- `test_rejected_opportunity_can_re_enter()` (L467) — A prior failure/rejection is re-entry-able (recurring gig / transient fail).
- `test_mark_irreversible_blocks_the_next_run()` (L477) — After a submission goes out, a restart must not re-submit.
- `test_replay_guard_fails_closed_on_a_ledger_read_error()` (L487) — A locked/unreadable ledger must not permit a second irreversible action.
- `test_finalized_run_is_terminal_so_recovery_does_not_refail_it()` (L500)
- `test_run_status_field_round_trips_through_the_store()` (L508) — A real AutonomousRunStore must persist the in-flight status.
- `_load_persist_base()` (L540)
- `_run_gui_until(host, predicate, timeout_s=8.0)` (L583) — Drive a REAL Qt event loop on the main thread until predicate() holds.
- `test_persist_re_arms_instead_of_dropping_the_last_edit()` (L603) — A newer edit arriving mid-write must not be silently dropped.
- `test_persist_does_not_re_arm_when_nothing_new_arrived()` (L630) — The re-arm must not turn one edit into a write loop.
- `test_persist_confirmation_is_delivered_to_the_log()` (L650) — The .env save confirmation must reach _log() on the GUI thread.
- `test_worker_never_arms_the_drain_timer()` (L667) — _emit_persist_saved runs on the worker thread and must not touch Qt.
- `test_drain_survives_a_fast_writer_winning_the_race()` (L711) — A zero-cost writer must not be able to kill the re-arm permanently.
- `test_persist_worker_never_calls_log_from_the_background_thread()` (L739) — _log() appends to a QTextEdit; calling it off-thread corrupts the GUI.

**Classes:**
- `class _StubStore` (L399)
  - `__init__()` (L400)
  - `save_run(run, opp_id, *a, **k)` (L404)
  - `mark_idempotent(key, run_id, opp_id)` (L408)
  - `is_idempotent(key)` (L411)
- `class _Opp` (L415)
- `class _FakeWidget` (L528)
  - `__init__()` (L529)
  - `append(text)` (L532)
- `class _PersistBase` (L536) — Import shim so the test file does not hard-fail without PySide6.
- `class _PersistHost(_PersistBase)` (L554) — Minimal stand-in exercising the REAL coalescing/re-arm logic.
  - `__init__()` (L562)
  - `_log(message)` (L569)
  - `_snapshot_settings_values()` (L572)
  - `_write_env_values(values)` (L576) — Stand in for the real .env writer, including its save confirmation.


### `tests/engineering/test_cycle_088_091.py` — ARCH-ENG-088..091 — the findings left unresolved at the end of v2.1.61. (551L)

**Functions:**
- `_submission_action(record_id: str='r1', name: str='upwork:Write a post)` (L26)
- `clean_queue()` (L39) — A HumanApprovalQueue with no leftover items, restored after the test.
- `test_flagged_action_reaches_the_operator_visible_queue(clean_queue)` (L60) — The Approvals panel reads HumanApprovalQueue, not the guard's list.
- `test_queued_submission_carries_the_record_id(clean_queue)` (L79) — Without the record id the approval cannot be routed back to a submit.
- `test_payment_is_queued_as_a_payment(clean_queue)` (L89) — A fund-moving action must not be filed as a generic ACTION.
- `test_decision_in_queue_is_visible_to_the_guard(clean_queue)` (L103) — Approving in the GUI must retire the guard's copy of the request.
- `test_guard_cannot_approve_twice(clean_queue)` (L116) — A second approve() must not re-run the same irreversible action.
- `test_guard_reject_propagates_to_the_queue(clean_queue)` (L130)
- `test_pending_approvals_property_still_works(clean_queue)` (L143) — The attribute existed as a list; callers must not break on the change.
- `test_many_sequential_actions_are_not_a_recursion_loop()` (L156) — Reproduced: the 11th distinct submission returned
- `test_recursion_stack_is_empty_after_a_check()` (L171) — check() must leave the detector balanced, or depth only ever grows.
- `test_genuine_nesting_is_still_detected()` (L182) — The detector must keep working for the case it exists for.
- `test_repeated_identical_calls_are_still_detected()` (L195) — The repeat rule must survive the depth pop.
- `test_sequential_loop_is_blocked_but_distinct_work_is_not()` (L215) — The two rules must not bleed into each other.
- `test_approved_alias_executes(clean_queue)` (L242) — Reproduced: execute_tool("write_file", ..., approved=True) returned
- `test_unapproved_alias_still_does_not_execute(clean_queue)` (L273) — The fix must not turn the alias into an approval bypass.
- `test_read_only_alias_resolves(clean_queue)` (L288) — read_file / query_database are BLOCKED-by-classification aliases; the
- `test_truly_unknown_tool_is_still_refused()` (L299) — Canonicalisation must not widen the accepted name set.
- `_prepared_record(submitter, record_id_url='https://x/1')` (L308)
- `test_approved_submission_is_actually_submitted(clean_queue, tmp_path)` (L317) — Reproduced: request_approval queued the request and nothing ever read
- `test_denied_submission_is_never_sent(clean_queue, tmp_path)` (L339)
- `test_deferred_submission_is_never_sent(clean_queue, tmp_path)` (L354) — Defer is a decision, and it is not an approval.
- `test_submission_without_a_queued_approval_is_refused(clean_queue, tmp_path)` (L369) — Fail closed: no queue entry means no provable human decision.
- `test_submit_still_refuses_an_unapproved_record(tmp_path)` (L381) — The pre-existing gate must not be weakened by the new entry point.
- `test_earning_tab_injects_a_real_guard()` (L393) — The guard-injection consequence recorded at the end of v2.1.61.
- `test_approved_submission_is_not_sent_twice(clean_queue, tmp_path)` (L440) — An irreversible submission must not be re-executable.
- `test_real_adapter_submission_is_sent_once_after_approval(clean_queue, tmp_path)` (L467) — The live-adapter branch must actually reach the adapter, exactly once.
- `test_failed_queue_decision_does_not_mark_the_record_approved(clean_queue)` (L490) — approve() must not report success when the queue did not record it.
- `test_owned_map_is_bounded_on_a_long_lived_guard(clean_queue)` (L516) — A process-lifetime guard must not accumulate DECIDED records forever.

**Classes:**
- `class _RecordingAdapter` (L429) — A real platform adapter, so submit() takes the live-adapter branch.
  - `__init__()` (L432)
  - `submit_proposal(payload, confirmed_by_human=False)` (L435)


### `tests/engineering/test_cycle_092_accounting.py` — ARCH-ENG-092 — financial-integrity regressions, cycle 092. (369L)

**Functions:**
- `_evidence(subject_id, amount, evidence_type, currency='usd', method=', ...)` (L74)
- `_paid_tracker(tmpdir, amount=750.0, currency='usd', opp_id='opp1')` (L87) — A tracker on a real state file, with a verified L3 payout recorded.

**Classes:**
- `class _EvidenceStoreStub` (L53) — Minimal EvidenceStore surface the lifecycle and accounting layers use.
  - `__init__(items=None)` (L56)
  - `record(ev)` (L59)
  - `get(evidence_id)` (L63)
  - `for_subject(subject_type, subject_id)` (L69)
- `class TestPaidSurvivesRestart` (L114) — The JSON snapshot must be written AFTER the paid fields are set.
  - `test_disk_snapshot_carries_status_and_verification()` (L117) — Before the fix the on-disk record held status='active', verification=None.
  - `test_verified_revenue_survives_a_second_tracker_on_same_path()` (L136) — The exact regression: build a tracker, mark paid, re-open the file.
  - `test_paid_state_from_every_live_stage_survives_restart()` (L166) — `_mark_paid` routes through intermediate stages; the final persist
  - `test_a_refused_paid_transition_does_not_persist_paid()` (L203) — Fail-safe direction: a terminal `failed` opportunity can never be
- `class TestUnknownCurrencyIsNotFaceValueUSD` (L234) — `to_usd` must never invent a 1.0 rate for a currency it does not know.
  - `test_known_currencies_still_convert()` (L237)
  - `test_unmapped_currency_is_not_valued_at_one()` (L246)
  - `test_empty_or_blank_currency_is_not_valued_at_one()` (L253) — `Evidence.currency` defaults to `""`; that is an unknown denomination.
  - `test_is_convertible_distinguishes_unknown_from_worthless()` (L261)
  - `test_jpy_payout_is_not_booked_as_verified_revenue()` (L269) — The reproduced defect: 250,000 JPY booked as $250,000 verified revenue.
  - `test_unconvertible_amount_is_visible_for_operator_review()` (L286)
  - `test_empty_currency_evidence_is_not_booked_at_face_value()` (L296)
  - `test_convertible_currency_still_books_normally()` (L309) — Fail-safe must not over-correct: known currencies are unaffected.
  - `test_unconvertible_expense_does_not_distort_net()` (L320) — An unconvertible fee must not be dropped into `other` at face value.
  - `test_helper_accessors_fail_safe_too()` (L334)
  - `test_to_dict_exposes_unconvertible_amounts()` (L346)
  - `test_custom_rates_make_a_currency_convertible()` (L353) — Adding a JPY rate is the supported remedy, and it books correctly.


### `tests/engineering/test_cycle_092_approval_routing.py` — Cycle 092 — human-approval routing integrity (two GUI surfaces, one approval). (406L)

**Functions:**
- `queue()` (L88) — A fresh, isolated approval queue per test (singleton is process-wide).
- `executed_tools(monkeypatch)` (L97) — Count ``execute_tool`` calls instead of running any irreversible tool.
- `_enqueue_action(queue, tool, arguments, requested_by='dialogue')` (L110)
- `test_one_approval_executes_irreversible_action_once(queue, executed_tools)` (L123) — The reproduction: two surfaces deliver the same approval -> ONE run.
- `test_duplicate_decision_is_logged_for_the_operator(queue, executed_tools)` (L142) — A re-emission must not look like a silently dead click.
- `test_second_distinct_approval_still_executes(queue, executed_tools)` (L158) — The guard is per approval id — it must not suppress a NEW approval.
- `test_rejected_or_pending_item_never_executes(queue, executed_tools)` (L177) — The guard must not weaken the queue re-read: nothing runs unless the
- `test_unknown_approval_id_is_ignored(queue, executed_tools)` (L193)
- `test_submission_path_is_consumed_once_by_the_submitter(queue)` (L199) — ``PlatformSubmitter.submit_if_approved`` already refuses to send twice,
- `safety_tab(queue)` (L236) — A real SafetyTab (conftest guarantees the offscreen QApplication).
- `_select_row(tab, approval_id)` (L245)
- `test_refresh_lists_every_pending_item_not_only_guard_owned(safety_tab, queue)` (L253) — The reproduction: dispatch-origin items were invisible in the table.
- `test_guard_owned_and_dispatch_items_are_both_selectable(safety_tab, queue)` (L281) — The id column must carry the real queue id for the approve path.
- `test_approve_records_decision_when_guard_does_not_own_the_id(safety_tab, queue)` (L300) — The reproduction: the click was silently dropped.
- `test_approve_routes_to_the_app_decision_handler(safety_tab, queue)` (L318) — A recorded approval must reach ``_on_approval_decided``.
- `test_guard_owned_approval_still_goes_through_the_guard(safety_tab, queue)` (L341) — The guard remains the first choice — the queue is only the fallback.
- `test_reject_records_decision_when_guard_does_not_own_the_id(safety_tab, queue)` (L358) — A rejection must not be swallowed either.
- `test_rejected_item_is_not_executed_by_the_decision_handler(safety_tab, queue, executed_tools)` (L374) — Deny must stay authoritative even after a rejected item is listed.
- `test_missing_requested_at_does_not_break_the_table(safety_tab, queue)` (L389) — A row without ``requested_at`` must blank the panel silently.

**Classes:**
- `class _Signal` (L52) — Stands in for a Qt signal's ``emit`` so handlers can run headless.
  - `__init__()` (L55)
  - `emit(message)` (L58)
- `class _HandlerHost` (L62) — Minimal host for the REAL MainWindow approval handlers.
  - `__init__(queue)` (L70)
  - `_refresh_approval_alert()` (L83)


### `tests/engineering/test_cycle_092_expense_side.py` — ARCH-ENG-092 F5 — the expense side of the unmapped-currency fail safe. (353L)

**Functions:**
- `_evidence(subject_id, amount, evidence_type, currency='usd', method=', ...)` (L84)
- `_profile(items, **kwargs)` (L98)

**Classes:**
- `class _EvidenceStoreStub` (L63) — Minimal EvidenceStore surface the accounting layer uses.
  - `__init__(items=None)` (L66)
  - `record(ev)` (L69)
  - `get(evidence_id)` (L73)
  - `for_subject(subject_type, subject_id)` (L79)
- `class TestUnconvertibleExpenseIsNotPresentedAsFreeMargin` (L105) — A cost that cannot be valued must not be reported as zero cost.
  - `test_reproduced_case_is_flagged_as_having_an_unvalued_cost()` (L108) — The exact reproduction: [1000 usd payment, 400 usd fee, 50000 XXX fee].
  - `test_roi_is_not_published_for_a_profile_with_an_unvalued_cost()` (L127) — ROI is a ratio whose denominator is known to be too small.
  - `test_net_hourly_rate_is_not_published_for_a_profile_with_an_unvalued_cost()` (L139)
  - `test_expense_only_unconvertible_cost_is_flagged()` (L149) — No revenue at all, and the whole cost is unvalued: still a cost.
  - `test_blank_currency_expense_is_flagged_as_unspecified()` (L158) — `Evidence.currency` defaults to `""` — an unknown denomination.
  - `test_unvalued_fee_stored_on_payment_evidence_is_flagged()` (L166) — Fees/gas carried on payment evidence take the same expense path.
- `class TestUnconvertiblePaymentStillExcludedFromRevenue` (L179) — 092b's fail-safe direction is NOT weakened by the F5 fix.
  - `test_unmapped_payment_is_not_verified_revenue()` (L182)
  - `test_blank_currency_payment_is_not_verified_revenue()` (L195)
  - `test_to_usd_still_returns_zero_for_an_unmapped_currency()` (L205) — The fix must not change `to_usd`'s return value (0.0, not None).
  - `test_helper_accessors_still_fail_safe()` (L216)
- `class TestMappedCurrenciesAreUnaffected` (L232) — No over-correction: fully convertible profiles compute exactly as before.
  - `test_usd_fee_still_produces_net_and_roi()` (L235)
  - `test_mapped_crypto_fee_still_produces_net_and_roi()` (L248)
  - `test_custom_rates_clear_the_flag()` (L258) — The supported remedy: add a rate and the annotation clears itself.
  - `test_mixed_mapped_and_unmapped_expense_keeps_the_mapped_part()` (L272) — Only the unvalued part is withheld; the booked cost is still real.
- `class TestAnnotationIsSurfacedToConsumers` (L287) — The data must reach every surface a consumer reads.
  - `test_to_dict_exposes_the_flag()` (L290)
  - `test_clean_profile_to_dict_reports_false()` (L301)
  - `test_default_profile_reports_false()` (L309) — A hand-built EconomicProfile must not claim an unvalued cost.
  - `test_aggregate_withholds_roi_and_names_the_currencies()` (L315)
  - `test_aggregate_of_clean_profiles_still_computes_roi()` (L334)
  - `test_aggregate_empty_carries_the_flag_keys()` (L345)


### `tests/engineering/test_cycle_092_live_trading.py` — ARCH-ENG-092: the live-trading approval must authorize the order it names. (329L)

**Functions:**
- `_intent(asset_class='major', quantity=1.0, side='buy', symbol='BTC/USD')` (L59)
- `_live(service)` (L65) — Assess against the same live state execute_order re-reads.
- `_intent_assessment()` (L317) — A throwaway needs_approval verdict for hand-built queue items.

**Classes:**
- `class FakeAdapter` (L30) — Records every order that reaches the exchange, and serves live state.
  - `__init__()` (L40)
  - `fetch_balance()` (L43)
  - `fetch_ticker(symbol)` (L47)
  - `fetch_order_book(symbol)` (L51)
  - `create_order(*args)` (L54)
- `class TestLiveTradingApprovalBinding` (L78)
  - `setUp()` (L79)
  - `tearDown()` (L88)
  - `_assessed(intent=None)` (L92)
  - `test_approved_order_cannot_be_swapped_for_another()` (L100) — THE core defect: approve a small buy, execute a huge sell.
  - `test_approval_for_one_symbol_does_not_authorize_another()` (L116)
  - `test_approval_quantity_must_match_exactly()` (L126)
  - `test_approved_side_cannot_be_flipped()` (L136) — A sell approval must not be replayable as a buy.
  - `test_approval_payload_without_an_intent_authorizes_nothing()` (L149) — An item that does not name its order cannot be shown to cover one.
  - `test_missing_order_shaping_field_makes_the_approval_unusable()` (L162)
  - `test_denied_approval_never_executes()` (L178)
  - `test_unknown_approval_id_never_executes()` (L188)
  - `test_empty_approval_id_never_executes()` (L195)
  - `test_pending_approval_never_executes()` (L201)
  - `test_fabricated_preapproved_assessment_is_refused()` (L212) — A hand-built 'preapproved' verdict must not bypass the human.
  - `test_fabricated_assessment_cannot_lower_a_real_verdict()` (L222)
  - `test_assessment_factors_carry_the_reviewed_market_data()` (L229) — Re-derivation needs the numbers the human actually reviewed.
  - `test_the_approved_order_executes_exactly_once()` (L240)
  - `test_advisory_fields_do_not_invalidate_a_real_approval()` (L253) — A refreshed confidence estimate must not block an approved order.
  - `test_preapproved_low_risk_order_still_runs_without_a_human()` (L274) — The fix must not turn every order into a manual approval.
  - `test_disabled_service_still_refuses_everything()` (L297)
  - `test_blocked_order_is_refused_before_any_approval_is_consulted()` (L306)


### `tests/engineering/test_cycle_092_review_fixes.py` — Verify the ARCH-ENG-092 review findings are closed. (286L)

**Functions:**
- `_intent(asset_class='major', quantity=1.0, side='buy', symbol='BTC/USD')` (L67)
- `_live(adapter)` (L268) — Assess against the same live state execute_order will re-read.
- `_assessment_for(intent)` (L274)

**Classes:**
- `class FakeAdapter` (L36) — Records every order that reaches the exchange, and serves live state.
  - `__init__(total_usd=1000.0, free_usd=900.0, last_price=100.0, balance, ...)` (L41)
  - `fetch_balance()` (L50)
  - `fetch_ticker(symbol)` (L54)
  - `fetch_order_book(symbol)` (L58)
  - `create_order(*args)` (L62)
- `class TestReviewFindingsClosed` (L73)
  - `setUp()` (L74)
  - `tearDown()` (L83)
  - `test_forged_plausible_factors_do_not_reach_the_exchange()` (L89) — THE F1 attack, verbatim: plausible forged market data.
  - `test_forged_factors_cannot_claim_a_verdict_the_live_data_refuses()` (L111) — The verdict comes from live state, not from the caller's numbers.
  - `test_unreadable_live_state_fails_closed()` (L124) — If the account cannot be read, the order does not go out.
  - `test_approval_is_refused_when_the_market_moves_underneath_it()` (L140)
  - `test_stable_market_does_not_invalidate_a_genuine_approval()` (L154) — The staleness check must not refuse a legitimate approval.
  - `test_one_approval_submits_at_most_one_live_order()` (L167) — THE F2 attack, verbatim: replay the same approval five times.
  - `test_a_second_distinct_approval_still_submits()` (L186) — The consumed-once ledger must not block a genuinely new approval.
  - `test_case_differences_do_not_invalidate_an_approval()` (L207) — An approval recorded 'BTC/USD' authorizes an order written 'btc/usd'.
  - `test_a_real_quantity_change_is_still_detected()` (L218)
  - `test_a_meaningful_price_change_is_still_detected()` (L223)
  - `test_legitimate_approved_order_executes()` (L233)
  - `test_preapproved_low_risk_order_still_runs_without_a_human()` (L243) — The guards must not turn every order into a manual approval.


### `tests/engineering/test_cycle_092_review_minors.py` — Cycle 092 adversarial review — the two MINOR findings, closed. (363L)

**Functions:**
- `disk_queue(tmp_path)` (L72) — A queue that really persists, so the history bound actually runs.
- `_flood(queue, count, prefix='noise')` (L83) — Enqueue ``count`` PENDING ACTION items — the eviction trigger.
- `test_an_approval_decided_in_this_process_is_never_evicted(disk_queue, tmp_path)` (L91) — THE F4 REPRODUCTION: a live $5000 approval must survive the bound.
- `test_a_denial_decided_in_this_process_is_never_evicted(disk_queue)` (L118) — The guarantee is for any human decision, not only approvals.
- `test_pending_items_are_still_never_evicted(disk_queue)` (L132) — The original invariant this file exists for must not regress.
- `test_an_old_decision_still_gets_pruned(disk_queue)` (L147) — The bound must still cap decided history — the fix is not "keep all".
- `test_a_decision_restored_from_a_previous_process_is_still_refused(tmp_path)` (L165) — PRESERVED: stale authorization must still fail CLOSED across a restart.
- `test_the_tracking_sets_do_not_outgrow_the_queue(tmp_path)` (L197) — PRESERVED against drift: both decided-sets track surviving items only.
- `queue()` (L240) — A fresh, isolated approval queue per test (singleton is process-wide).
- `safety_tab(queue)` (L249) — A real SafetyTab (conftest guarantees the offscreen QApplication).
- `_listed_ids(tab)` (L260)
- `_select_row(tab, approval_id)` (L265)
- `_guard_payment(queue, amount=5000.0)` (L273) — A guard-enqueued PAYMENT request, exactly as guard.py builds one.
- `test_a_payment_request_is_not_offered_for_approval_here(safety_tab, queue)` (L286) — THE F7 REPRODUCTION: an approval nothing can execute was offered.
- `test_a_gate_request_is_not_offered_for_approval_here(safety_tab, queue)` (L304) — GATE has no routing branch either — same rule, same reason.
- `test_routable_kinds_are_still_listed_and_approvable_here(safety_tab, queue)` (L312) — The filter must not re-hide what this tab CAN act on.
- `test_the_payment_request_is_still_listed_in_the_approvals_panel(queue)` (L338) — Where a payment request lives instead: the Approvals panel lists all.


### `tests/engineering/test_cycle_092_trust_boundary.py` — ARCH-ENG-092 — trust-boundary and persistence defects in the dual-brain path. (364L)

**Functions:**
- `_markers_present(text: str) -> list[str]` (L49)
- `portfolio_with_injected_title()` (L55) — A real OpportunityPortfolio on disk holding one attacker-crafted listing.
- `test_injected_opportunity_title_is_neutralized(portfolio_with_injected_title)` (L89) — The emitted snapshot must contain none of the injected directives.
- `test_injected_opportunity_title_is_marked_untrusted(portfolio_with_injected_title)` (L100) — The same text must be explicitly framed as data, not instructions.
- `test_sanitizer_envelope_is_never_cut_by_truncation(portfolio_with_injected_title)` (L120) — Truncation must happen BEFORE the envelope is built.
- `test_internal_snapshot_fields_survive_unsanitized(portfolio_with_injected_title)` (L143) — Sanitizing must not swallow the bookkeeping the brains rely on.
- `persisted_queue(tmp_path)` (L162) — A HumanApprovalQueue whose singleton writes to a throwaway file.
- `test_instance_resolves_a_real_log_path(persisted_queue)` (L186) — instance() must not return a queue whose log_path is None.
- `test_pending_approval_survives_a_restart(persisted_queue)` (L198) — Enqueue → reset_singleton → instance(): the item is still there, PENDING.
- `test_decided_item_restores_with_its_status_intact(persisted_queue)` (L233) — A DENIED item must come back DENIED, never as a fresh PENDING request.
- `test_restored_decision_is_not_an_executable_authorization(persisted_queue)` (L273) — A stale APPROVED item must not authorize an irreversible action.
- `test_a_decision_made_in_this_process_is_still_executable(persisted_queue)` (L317) — The fail-closed rule must not block approvals the human gives NOW.
- `test_pytest_runs_never_write_the_operators_live_queue()` (L339) — Without the env override, a test run stays in memory.


### `tests/sections/__init__.py` — Sections tests. (2L)


### `tests/sections/test_section_c.py` — Canonical tests for Section C (platform safety & ToS). (372L)

**Classes:**
- `class FakeClock` (L19) — Deterministic clock so TokenBucket tests never really sleep.
  - `__init__()` (L21)
  - `monotonic()` (L24)
  - `advance(d)` (L27)
- `class TestPlatformThrottle` (L31)
  - `setUp()` (L32)
  - `tearDown()` (L43)
  - `test_burst_capacity_instant()` (L47) — A burst up to capacity is immediate; the next token waits for refill.
  - `test_env_rate_override()` (L66)
  - `test_source_to_platform_mapping()` (L77)
  - `test_singleton_shared()` (L87)
  - `test_unknown_platform_defaults()` (L92)
  - `test_find_gigs_throttled()` (L98) — Client find_gigs calls the throttle (mocked) without error.
- `class FakeRepMemory` (L120) — Minimal EarningMemory stand-in for ramp tests.
  - `__init__()` (L122)
  - `get_platform_reputation(p)` (L125)
  - `record_win(p, revenue=0.0)` (L129)
  - `record_loss(p)` (L136)
  - `record_attempt(p)` (L143)
- `class TestSubmissionRamp` (L150)
  - `setUp()` (L151)
  - `test_cold_start_requires_human()` (L155)
  - `test_low_win_rate_stays_human()` (L161)
  - `test_unlocked_after_wins()` (L170)
  - `test_ai_disallowed_forces_human()` (L179)
  - `test_env_overrides()` (L189)
  - `test_record_outcome_persists()` (L201)
  - `test_h39_submission_is_not_a_win()` (L213) — H39 fix: record_submission bumps total but NOT success_rate.
  - `test_h39_real_accept_unlocks()` (L226) — H39 fix: a real accept (not a submission) is what unlocks auto.
  - `test_h39_real_reject_counts_loss()` (L239)
  - `test_no_memory_is_safe()` (L250)
- `class TestScrapeResilience` (L256)
  - `setUp()` (L257)
  - `test_ua_rotation_differs()` (L263)
  - `test_captcha_detection()` (L269)
  - `_fake_resp(status, headers=None, text='')` (L275)
  - `test_429_then_success()` (L283)
  - `test_429_exhaustion_raises()` (L295)
  - `test_captcha_body_raises()` (L302)
  - `test_network_error_reraised()` (L310)
  - `test_retry_after_capped()` (L319)
  - `test_fiverr_captcha_empty()` (L325)
- `class TestThrottleDrawCount` (L337) — H41 regression: one client discovery must draw at most 2 throttle tokens
  - `test_upwork_max_two_draws()` (L341)


### `tests/sections/test_section_d.py` — Canonical tests for Section D (LLM quality & cost). (401L)

**Classes:**
- `class FakeWorker` (L18) — Captures the chat= kwarg passed to worker.llm.
  - `__init__()` (L20)
  - `llm(system='', user='', max_tokens=350, chat=True, think=False, **kw)` (L24)
- `class TestProposalModelRole` (L30) — D1: proposal drafting model role follows PROPOSAL_MODEL_ROLE env.
  - `_make_manager()` (L33)
  - `test_default_role_is_chat()` (L40)
  - `test_role_main_routes_to_main()` (L50)
  - `test_role_chat_explicit()` (L62)
  - `test_unknown_role_falls_back_to_chat()` (L73)
- `class FakeLearningMemory` (L85) — Minimal EarningMemory stand-in for proposal-intro A/B tracking.
  - `__init__()` (L87)
  - `store_learning(learning_type, insight, confidence=0.5)` (L90)
  - `get_recent_learned(learning_type=None, limit=10)` (L93)
- `class TestProposalTemplates` (L103)
  - `test_intro_rotation_distinct()` (L104)
  - `test_best_intro_none_before_samples()` (L110)
  - `test_best_intro_picks_winner()` (L118)
  - `test_pick_intro_uses_best_when_available()` (L130)
  - `test_record_is_safe_without_memory()` (L141)
- `class FakeAdapter` (L148) — Minimal provider adapter stand-in for D3 routing tests.
  - `__init__(name, order, default_model='', chat_model='', available=True)` (L150)
  - `available()` (L158)
  - `complete(model, system, user, max_tokens, chat=False)` (L161)
- `class TestCostAwareRouting` (L165)
  - `_make_worker(adapters, chat=False)` (L166)
  - `_adapters()` (L178)
  - `test_cost_aware_orders_cheapest_first()` (L187)
  - `test_disabled_cost_aware_keeps_adapter_order()` (L200)
  - `test_local_always_first()` (L212)
  - `test_no_providers_safe()` (L219)
  - `test_llm_with_no_providers_fails_fast()` (L225)
  - `test_disabled_big_brain_excluded_from_providers()` (L243)
  - `test_cloud_failover_off_excludes_cloud_providers()` (L265)
  - `test_cloud_failover_on_keeps_cloud_providers()` (L280)
- `class TestCircuitBreaker` (L294)
  - `_breaker()` (L295)
  - `test_opens_after_threshold()` (L299)
  - `test_success_resets()` (L309)
  - `test_cooldown_expiry_half_open()` (L319)
  - `test_disabled_never_opens()` (L333)
  - `test_isolated_per_provider()` (L344)
- `class TestProposalVariantPlumbing` (L355) — D2 re-audit (v2.0.34z): the intro variant must reach the opp so the
  - `test_record_ramp_real_outcome_credits_variant()` (L359)
  - `test_no_variant_no_credit()` (L381)


### `tests/tools/__init__.py` — (no module docstring) (1L)


### `tests/tools/test_github_publish_sync.py` — Tests for the GitHub publish-mirror sync (tools/github_publish). (105L)

**Functions:**
- `_load_sync()` (L22)
- `sync()` (L30)
- `test_public_restructure_docs_are_included(sync)` (L34) — The root recursive fallback only globs *.py, so public root docs must be
- `test_internal_ops_and_cron_artifacts_are_excluded(sync)` (L42) — Internal reports/prompts sit next to the public docs at the repo root;
- `test_secrets_and_operator_state_are_excluded(sync)` (L50)
- `test_publish_tooling_and_routine_script_are_excluded(sync)` (L56) — tools/ (this mirror's own upload scripts) and run_lead_routine.py (a
- `test_test_artifacts_are_excluded(sync)` (L69) — pytest caches and historical test-run JSON must never be published.
- `test_bytecode_is_excluded(sync)` (L77)
- `test_stale_destination_paths_purge_pollution(sync)` (L82) — The sync must actively remove retired/polluted paths from the mirror (the
- `test_no_listed_include_entry_is_missing_from_source(sync)` (L91) — Every explicit INCLUDE entry must still exist (a stale entry means the
- `test_core_program_surface_is_covered(sync)` (L98) — The mirror must carry the runnable program: entrypoints, the app package,


### `tests/platforms/test_credential_vault.py` — Credential vault (Phase B) — encrypted-at-rest, never leaks cleartext. (77L)

**Functions:**
- `_vault()` (L17)

**Classes:**
- `class TestVaultEncryption` (L22)
  - `test_roundtrip_and_no_cleartext_at_rest()` (L23)
  - `test_metadata_apis_never_expose_values()` (L34)
  - `test_empty_secret_not_stored()` (L43)
  - `test_delete_field_and_platform()` (L48)
  - `test_missing_returns_empty()` (L56)
- `class TestVaultKeySafety` (L62)
  - `test_malformed_env_key_raises_not_cleartext()` (L63) — A malformed PLATFORM_VAULT_KEY must RAISE, never fall back to


### `tests/platforms/test_registration_gate.py` — Gated registration service (Phase B, agents/platforms/registration.py). (148L)

**Functions:**
- `_fake_gate(content='STEP 1: go to signu)` (L21)
- `_fake_queue(status='approved', item_id='appr_1')` (L31)

**Classes:**
- `class TestPropose` (L41)
  - `test_propose_quarantines_playbook_and_executes_nothing()` (L42)
- `class TestRegisterRefusals` (L63)
  - `_svc(queue=None)` (L64)
  - `test_refused_without_approval_id()` (L68)
  - `test_refused_when_approval_not_approved()` (L75)
  - `test_refused_when_approval_unknown()` (L83)
  - `test_refuses_to_invent_missing_value()` (L93) — A field with no supplied value is never fabricated.
  - `test_approved_registration_forwards_to_fill_form()` (L104)
  - `test_register_with_vault_refuses_without_stored_creds()` (L119) — register_with_vault fails closed when the vault has nothing for the
  - `test_register_with_vault_uses_stored_secret()` (L131) — With creds in the vault, register_with_vault reads them and fills.


### `tests/cognition/__init__.py` — (no module docstring) (1L)


### `tests/cognition/test_speaker_registry.py` — Tests for the N-brain speaker registry (Phase 1). (169L)

**Functions:**
- `_placement(role, device_id, name, port, is_cpu=False, label='')` (L16)
- `_clear_name_env()` (L24)

**Classes:**
- `class TestBuildSpeakers` (L30)
  - `setUp()` (L31)
  - `tearDown()` (L34)
  - `test_two_placements_edward_and_jacob()` (L37)
  - `test_four_placements_distinct_names_per_tier()` (L52)
  - `test_no_famous_person_names_in_pool()` (L74)
  - `test_env_override_wins()` (L81)
  - `test_legacy_big_small_name_env()` (L90)
  - `test_slot_key_naming_wins_over_legacy()` (L100)
  - `test_device_label_carried()` (L106)
  - `test_brains_mapped_by_slot()` (L112)
  - `test_duplicate_names_disambiguated()` (L121)
  - `test_empty_placements()` (L133)
- `class TestSpeakerLookups` (L137)
  - `setUp()` (L138)
  - `tearDown()` (L146)
  - `test_speaker_for_slot()` (L149)
  - `test_speaker_for_key()` (L153)
  - `test_speaker_for_name()` (L158)
  - `test_default_pingpong_order()` (L162)


### `tests/integrations/test_webcontroller_escalation.py` — WebController.read_page escalation (Phase A web robustness). (138L)

**Functions:**
- `_fake_response(status_code=200, text='', headers=None, url='https://example.com)` (L22)

**Classes:**
- `class TestReadPageEscalation` (L31)
  - `setUp()` (L32)
  - `test_rich_page_no_escalation()` (L41) — A normal page with real content is returned as-is, browser NOT called.
  - `test_non_200_escalates_to_browser()` (L56) — A 403/503 triggers exactly one Playwright attempt.
  - `test_non_200_browser_also_fails_marks_human_open()` (L69) — When the browser can't get it either, mark human-open-only, not a stub.
  - `test_thin_js_shell_escalates()` (L82) — A 200 with a near-empty JS shell escalates to the browser.
  - `test_thin_and_playwright_unavailable_falls_back_to_stub()` (L95) — If Playwright is missing ({}), don't crash — return the thin result.
  - `test_playwright_import_error_returns_empty()` (L105) — _read_with_playwright returns {} (not a crash) when Playwright is absent.
  - `test_robots_disallow_blocks_before_fetch()` (L111) — A host whose robots.txt disallows the path is NOT fetched at all —
  - `test_robots_allow_proceeds()` (L123) — When robots.txt allows, the fetch proceeds normally.


### `tests/discovery/test_web_discovery_feeds_and_linkedin.py` — Web-discovery feeds + LinkedIn no-fabrication (v2.1.68, Phase A polish). (120L)

**Classes:**
- `class TestWebDiscoveryFeeds` (L23)
  - `test_default_feeds_are_gig_oriented_not_crypto_news()` (L24)
  - `test_opportunity_id_is_stable_sha1_not_salted_hash()` (L35) — The same link must produce the same id in two processes. hash() is
  - `test_real_discover_parses_feed_items_with_stable_ids()` (L46) — _real_discover maps real RSS items to Opportunities with amount 0
- `class TestLinkedInNoFabrication` (L73)
  - `_entry(title, desc, link)` (L74)
  - `test_no_pay_signal_skipped()` (L82)
  - `test_pay_parsed_not_fabricated()` (L90)
  - `test_pay_mentioned_but_no_number_is_zero()` (L106)


---

## Root test files (tests/__main__.py, tests/conftest.py)

### `tests/__main__.py` — MrBot1000 Test Suite Runner (583L)

**Functions:**
- `ensure_results_dir()` (L184)
- `list_tests()` (L188)
- `get_all_test_names()` (L211) — Get all runnable test names (excluding bundle tests)
- `run_test(test_name: str) -> tuple` (L216) — Run a single test by name. Returns (success, message).
- `test_syntax() -> tuple` (L304) — Validate Python syntax for all modified files
- `test_imports() -> tuple` (L329) — Verify core modules can be imported
- `test_httpx_dependency() -> tuple` (L340) — Verify httpx and dependent modules import in a cold environment.
- `test_main() -> tuple` (L352) — Verify main.py can be imported and ManagerThread has required methods
- `run_unittest_file(filename: str) -> tuple` (L378) — Run a unittest-style test file from anywhere under tests/.
- `test_instruction_gate() -> tuple` (L410) — v2.0.22: instruction provenance gate (quarantine/allow/block).
- `test_trust_boundary() -> tuple` (L415) — v2.0.22: high-trust action boundary + platform adapter shape.
- `test_analyst_worker() -> tuple` (L420) — Verify AnalystWorker can be instantiated
- `test_job_search() -> tuple` (L430) — Verify JobSearchWorker can be instantiated
- `test_analyst_metrics() -> tuple` (L440) — Test AnalystWorker proposal analysis functionality
- `test_job_evaluation() -> tuple` (L458) — Test job listing evaluation
- `run_tests(test_list: list) -> tuple` (L482) — Run multiple tests and collect results
- `run_category(category: str) -> tuple` (L518) — Run all tests in a category
- `save_results()` (L527) — Save test results to JSON file
- `main()` (L541)


### `tests/conftest.py` — Shared pytest configuration for the MrBot1000 test suite. (255L)

**Functions:**
- `_qt_app_session()` (L91) — Create a single session-wide QApplication for Qt widget tests.
- `_track_mainwindow_instances()` (L107) — Register every MainWindow instance so leaks can be closed cheaply.
- `_no_leaked_mainwindow_threads(request, _track_mainwindow_instances)` (L139) — Stop any MainWindow-owned QThreads a test forgot to shut down.
- `_cleanup_leaked_windows(live)` (L161) — Shut down and close every still-live MainWindow (never raises).
- `_stop_running_qt_threads(limit: int=40)` (L180) — Best-effort stop of every live QThread (bounded, never raises).
- `_live_qt_threads()` (L206) — WeakSet of every QThread instance created this session.
- `_operator_env_is_untouched()` (L212) — Fail the session if any test rewrites the operator's `.env` or

