<!-- generated 91 files -->

### `tests/earning/__init__.py` — Earning tests. (2L)


### `tests/earning/test_application_services.py` — (no module docstring) (26L)

**Classes:**
- `class TestApplicationServices` (L9)
  - `test_builds_non_qt_earning_services()` (L10)


### `tests/earning/test_autonomous_loop.py` — tests/test_autonomous_loop.py — Unified Autonomous Planning Loop (v2.0.36k). (578L)

**Classes:**
- `class FakeOpp` (L16)
  - `__init__(opp_id='opp-1', title='Test opp', source='test', platform=', ...)` (L17)
- `class FakePortfolio` (L59)
  - `__init__(entries=None)` (L60)
  - `load_all()` (L62)
- `class FakeMemory` (L66)
  - `__init__(db_path=':memory:', platform_reputations=None)` (L67)
  - `get_opportunity_history(opp_id)` (L70)
  - `get_outcome_history(opp_id)` (L72)
  - `get_platform_reputation(platform)` (L74)
- `class FakeLifecycle` (L78)
- `class FakeEvidenceStore` (L82)
- `class SubjectEvidenceStore` (L86)
  - `__init__(evidence)` (L87)
  - `for_subject(subject_type, subject_id)` (L90)
- `class FakeAccounting` (L95)
  - `get_profile(opp_id)` (L96)
- `class FakeTaskExecutor` (L100)
  - `run(task)` (L101)
- `class FakePipeline` (L116)
  - `__init__(db_path=':memory:', platform_reputations=None)` (L117)
- `class TestProvenance` (L128)
  - `test_truth_status_ranking()` (L129)
  - `test_info_atom_is_at_least()` (L135)
  - `test_fact_store_add_and_get()` (L141)
  - `test_fact_store_most_reliable_wins()` (L148)
  - `test_fact_store_has_fact()` (L157)
  - `test_fact_store_has_verified()` (L164)
  - `test_fact_store_explain()` (L169)
  - `test_fact_store_explain_missing()` (L176)
  - `test_fact_store_to_dict()` (L180)
  - `test_provenance_chain()` (L187)
- `class TestAutonomousLoop` (L198)
  - `setUp()` (L199)
  - `test_full_loop_completes()` (L203) — Full 24-stage loop should complete for a valid opportunity (terminal non-failure).
  - `test_advertised_amount_never_becomes_payment_amount()` (L215)
  - `test_missing_executor_fails_without_claiming_completion()` (L243)
  - `test_loop_stages_recorded()` (L252) — Each stage should be recorded.
  - `test_loop_detects_duplicate()` (L264) — A prior terminal-success outcome should be blocked as a duplicate (state-aware dedup).
  - `test_loop_requests_approval_for_high_value()` (L273) — High-value opportunities should require approval.
  - `test_loop_preserves_provenance()` (L279) — Provenance should be preserved throughout the loop.
  - `test_loop_explanation_for_rejection()` (L286) — Rejection should include explanation.
  - `test_loop_explanation_for_approval()` (L293) — Await approval should include explanation.
  - `test_loop_duration_recorded()` (L299) — Loop duration should be recorded.
  - `test_loop_to_dict()` (L305) — Result should be serializable to dict.
  - `test_loop_with_no_duplicates()` (L315) — Non-duplicate should proceed past deduplicate stage.
  - `test_lifecycle_sync_failure_is_reported()` (L323)
  - `test_portfolio_sync_failure_is_reported()` (L334)
  - `test_run_persistence_failure_is_reported()` (L345)
- `class TestGroup1DeadStages` (L358) — Verifies C-3 / H-1 / H-2 fixes: learn + rerank + portfolio-sync must persist.
  - `setUp()` (L361)
  - `tearDown()` (L398)
  - `_opp(advertised_amount=50)` (L402)
  - `test_stage_learn_writes_outcome()` (L405) — C-3: LEARN stage must persist an outcome via LearningLoop.process_outcome.
  - `test_stage_rerank_persists_priority()` (L425) — H-1: RERANK stage must persist priority via portfolio.update().
  - `test_sync_final_state_updates_portfolio()` (L438) — H-2: _sync_final_state must update the portfolio via update() (not save()).
- `class _MemEvidenceStore` (L450) — Minimal in-memory EvidenceStore stand-in for Group 2 tests (no real AgentDB).
  - `__init__()` (L452)
  - `record(ev)` (L454)
  - `for_subject(subject_type, subject_id)` (L457)
- `class TestGroup2NoFabricatedPayment` (L461) — Verifies C-1/C-2: the loop must NOT report paid/success without verified L3+ payment.
  - `setUp()` (L464)
  - `tearDown()` (L498)
  - `_opp(advertised_amount=50)` (L502)
  - `test_no_payment_without_verified_evidence()` (L505) — C-1/C-2: running the loop over an opp with NO payment evidence must NOT report paid.
  - `test_submission_only_is_not_payment()` (L514) — C-2: a self-reported L1 platform_submission must NOT be treated as paid.
  - `test_payment_only_does_not_pass_real_lifecycle_policy()` (L529) — Payment evidence alone must not bypass the lifecycle transition contract.
  - `test_verified_l3_payment_reports_paid()` (L551) — Positive control: the complete externally verified payment chain flips the loop to paid.


### `tests/earning/test_autonomous_run_store.py` — tests/test_autonomous_run_store.py — Durable autonomous-run ledger (v2.1 Phase 3). (234L)

**Functions:**
- `_sample_result(opportunity_id='opp-1', decision='completed_unpaid', success=True, paid=False)` (L19)
- `_submitting_stub(opp, draft)` (L124) — A pipeline whose submit_gig_proposal succeeds (irreversible).

**Classes:**
- `class _FakeFacts` (L15)
- `class TestRunStorePersistence` (L42)
  - `setUp()` (L43)
  - `tearDown()` (L47)
  - `test_save_and_load_run()` (L51)
  - `test_survives_reopen()` (L62)
  - `test_stages_persisted_separately()` (L69)
- `class TestIdempotency` (L80)
  - `setUp()` (L81)
  - `tearDown()` (L85)
  - `test_mark_and_check()` (L89)
- `class TestRestartRecovery` (L103)
  - `setUp()` (L104)
  - `tearDown()` (L108)
  - `test_incomplete_run_marked_failed()` (L112)
- `class TestLoopPersistence` (L132) — A real AutonomousLoop run must persist when a run_store is injected.
  - `setUp()` (L135)
  - `tearDown()` (L139)
  - `test_loop_persists_run_to_store()` (L143)
  - `test_loop_marks_idempotent_after_an_irreversible_submission()` (L162) — A real submission must block a replay across a restart.
- `class TestCompositionRoot` (L174)
  - `test_close_reports_pipeline_shutdown_failure()` (L175)
  - `test_builds_shared_instances()` (L195)
  - `test_recover_incomplete_on_build()` (L214)


### `tests/earning/test_autonomy.py` — (no module docstring) (37L)

**Functions:**
- `test_grant_requires_level_capability_and_expiry()` (L6)
- `test_dispatcher_blocks_action_outside_grant()` (L19)


### `tests/earning/test_autonomy_limits.py` — (no module docstring) (63L)

**Classes:**
- `class TestAutonomyLimits` (L10)
  - `test_concurrency_limit_blocks_second_run()` (L11)
  - `test_cancelled_run_is_terminal_failure()` (L22)
  - `test_run_duration_limit_is_enforced_between_stages()` (L29)
  - `test_portfolio_less_pipeline_does_not_crash_prioritize()` (L47)


### `tests/earning/test_brain_got.py` — Tests for bounded GoT records around Big/Small Brain turns. (197L)

**Functions:**
- `test_brain_turn_graph_records_tool_status_without_private_reasoning()` (L6)
- `test_big_and_small_adapters_store_last_got_record()` (L23)
- `_tree_pattern()` (L56)
- `_direct_pattern()` (L61)
- `_evidence()` (L65)
- `_candidates()` (L80)
- `test_expand_branches_creates_scored_option_nodes()` (L91)
- `test_expand_branches_respects_max_branches_bound()` (L110)
- `test_direct_pattern_expand_is_a_noop()` (L120)
- `test_single_candidate_does_not_branch()` (L126)
- `test_score_and_select_prefers_evidence_backed_branch()` (L132)
- `test_finish_reports_branching_and_outcome_follows_decision()` (L153)
- `test_non_branching_finish_has_no_branch_summary()` (L177)
- `test_finish_got_turn_wires_branch_candidates()` (L184)


### `tests/earning/test_code_patch_postapply.py` — Task 10 — post-apply monitoring / self-healing. (120L)

**Functions:**
- `svc(tmp_path)` (L20)
- `_good_patch(target, value=2)` (L30)
- `test_apply_records_verified_outcome(svc)` (L38) — A successful apply must record verified_at + status in the ledger.
- `test_monitor_no_regression_emits_nothing(svc)` (L57) — If the applied patch file still verifies, monitor returns [] and status stays verified.
- `test_monitor_flags_regression_and_proposes_but_does_not_reverse(svc)` (L70) — If the target later stops compiling, monitor emits a new gated proposal
- `test_monitor_proposal_reverts_to_backup_on_approval(svc)` (L98) — The self-heal proposal's patch_text reverts to the original backup, so a


### `tests/earning/test_code_patch_queue.py` — Regression tests for CodePatchService in-use queueing. (165L)

**Functions:**
- `svc()` (L21)
- `code_patch()` (L35)
- `test_approved_patch_is_queued_when_in_use(svc, code_patch)` (L47)
- `test_drain_applies_queued_patch_on_free(svc, code_patch)` (L73)
- `test_unapproved_patch_never_queued_or_applied(svc, code_patch)` (L96)
- `test_mark_in_use_accepts_module_names(svc, code_patch)` (L114)
- `test_drain_keeps_patch_that_gets_requeued_mid_apply(svc, code_patch)` (L125) — If a target becomes in-use between drain's check and the write, the


### `tests/earning/test_code_patch_service.py` — Regression tests for the approval-gated CodePatchService. (217L)

**Functions:**
- `service_root()` (L32)
- `_make_patch(target_path, new_text="print('patched')\n", **kw)` (L38)
- `test_rejects_disallowed_extension(service_root)` (L51)
- `test_unapproved_patch_not_applied(service_root)` (L61)
- `test_rejects_path_escape(service_root)` (L78)
- `test_rejects_absolute_path_outside_root(service_root)` (L87)
- `test_apply_creates_backup_and_writes(service_root)` (L96)
- `test_failed_verify_rolls_back_to_original_bytes(service_root)` (L112)
- `test_rejects_symlink_escape(service_root)` (L130)
- `test_propose_then_approve_applies(service_root)` (L147)
- `test_propose_then_deny_never_applies(service_root)` (L173)
- `test_propose_then_approve_bad_patch_rolls_back(service_root)` (L194)


### `tests/earning/test_discovery_port.py` — (no module docstring) (38L)

**Functions:**
- `test_discovery_service_selects_sources_without_evaluation()` (L24)

**Classes:**
- `class _Source` (L5)
  - `is_enabled()` (L8)
  - `discover(page=1)` (L11)
- `class _Engine` (L15)
  - `__init__(sources, throttle)` (L16)
  - `discover_all(page=1)` (L20)


### `tests/earning/test_discovery_scheduler.py` — tests/test_discovery_scheduler.py — Dynamic Discovery Scheduler (v2.0.36f). (280L)

**Functions:**
- `_opp(title, source='web', cat='other', prov='')` (L65)

**Classes:**
- `class _Mem` (L32) — Minimal memory stub implementing the reads/writes the scheduler uses.
  - `__init__()` (L34)
  - `get_platform_reputation(src)` (L42)
  - `get_category_history(c)` (L45)
  - `get_successful_search_terms(n)` (L49)
  - `get_failed_search_terms(n)` (L52)
  - `compute_all_metrics(dim)` (L55)
  - `record_strategy_outcome(sid, success, reward=0.0)` (L58)
  - `record_search_strategy(sid, origin, query, cats, source)` (L61)
- `class TestStrategyGeneration` (L71)
  - `test_all_origins_present()` (L72)
  - `test_failed_terms_excluded()` (L82)
  - `test_llm_suggester_fails_safe()` (L87)
  - `test_llm_suggestions_folded()` (L93)
- `class TestSchedulerDecisions` (L100)
  - `setUp()` (L101)
  - `test_winner_shorter_interval_higher_priority()` (L111)
  - `test_tasks_generated()` (L116)
  - `test_exploration_floor_present()` (L120)
  - `test_not_pure_exploitation()` (L124)
  - `test_error_backoff_suspends()` (L129)
  - `test_one_bad_result_does_not_permanently_kill()` (L135)
  - `test_working_hours_skip()` (L144)
  - `test_freshness_skips_recent_category()` (L151)
  - `test_model_unavailable_uses_curated_exploration()` (L156)
  - `test_resource_constraint_max_tasks()` (L164)
- `class TestProvenanceAndLearning` (L172)
  - `setUp()` (L173)
  - `test_tick_tags_provenance_and_records_strategy()` (L179)
  - `test_run_task_tags_strategy_provenance()` (L189)
  - `test_run_task_isolates_source_error()` (L200)
  - `test_llm_never_called_in_tick()` (L210)
- `class TestHistoryDrivenBoosts` (L222)
  - `setUp()` (L223)
  - `test_recently_profitable_category_boosted()` (L235)
  - `test_low_yield_high_listing_source_reduced()` (L241)
  - `test_profitable_source_priority_high()` (L250)
  - `test_exploration_maintained_with_winners()` (L257)
- `class TestSchedulerStatePersistence` (L263)
  - `test_source_state_defaults()` (L264)
  - `test_backoff_grows_exponentially()` (L269)


### `tests/earning/test_earning_capability.py` — tests/test_earning_capability.py — First real earning capability (v2.1 Phase 4). (207L)

**Functions:**
- `_opp(opp_id='opp-1', platform='TestPlatform', task_type='writing, ...)` (L17)
- `_producer(opp, requirements)` (L31)

**Classes:**
- `class TestFulfillApproved` (L49)
  - `setUp()` (L50)
  - `tearDown()` (L70)
  - `test_simple_writing_task_approved_no_payment()` (L74)
  - `test_portfolio_entry_moved_to_waiting_external()` (L91)
  - `test_evidence_is_submission_not_payment()` (L97)
- `class TestHumanGateBlocksSubmission` (L107)
  - `setUp()` (L108)
  - `tearDown()` (L121)
  - `test_payment_task_requires_approval()` (L125)
  - `test_portfolio_entry_awaiting_approval_when_gated()` (L137)
  - `test_explicit_clear_gate_allows_submission()` (L145)
- `class TestValidationFailure` (L155)
  - `setUp()` (L156)
  - `tearDown()` (L169)
  - `test_empty_producer_fails()` (L173)
- `class TestNoFabricatedPayment` (L179)
  - `setUp()` (L180)
  - `tearDown()` (L191)
  - `test_never_records_payment()` (L195)


### `tests/earning/test_earning_discoverer.py` — (no module docstring) (48L)

**Classes:**
- `class TestEarningDiscoverer` (L7)
  - `test_reddit_json_falls_back_to_atom_rss()` (L8)
  - `test_github_search_parses_live_reward_issue()` (L24)


### `tests/earning/test_earning_got.py` — (no module docstring) (54L)

**Functions:**
- `_evidence(evidence_id)` (L22)
- `test_planner_ranks_utility_but_marks_unverified_options_for_investigation()` (L33)
- `test_verified_check_can_make_an_option_candidate_for_existing_gates()` (L47)

**Classes:**
- `class _Evaluation` (L5)
  - `__init__(expected_value, hourly, confidence, risk_penalty=0.0)` (L6)
- `class _Opportunity` (L13)
  - `__init__(opportunity_id, title, evaluation, evidence_ids=())` (L14)


### `tests/earning/test_earning_got_budget.py` — (no module docstring) (43L)

**Functions:**
- `test_candidate_budget_preserves_rejected_alternatives()` (L21)
- `test_node_budget_is_enforced_before_graph_expansion()` (L35)

**Classes:**
- `class _Evaluation` (L4)
- `class _Opportunity` (L11)
  - `__init__(opportunity_id)` (L16)


### `tests/earning/test_earning_memory.py` — (no module docstring) (36L)

**Classes:**
- `class TestEarningMemory` (L8)
  - `setUp()` (L9)
  - `tearDown()` (L13)
  - `test_remember_success_tracks_unique_platforms()` (L17)


### `tests/earning/test_earning_memory_au.py` — tests/test_earning_memory_au.py — Earning/Opportunity Learning Memory expansion (v2.0.35). (276L)

**Classes:**
- `class _MemoryTestBase` (L24)
  - `setUp()` (L25)
  - `tearDown()` (L29)
  - `_opp(category='writing', task_type='article', platform='Upwork',, ...)` (L33)
- `class TestMemoryTypesAndEnums(_MemoryTestBase)` (L44)
  - `test_outcome_states_all_accepted()` (L45)
  - `test_unknown_outcome_state_rejected()` (L50)
  - `test_failure_cause_structured()` (L55)
  - `test_failure_cause_unknown_ignored()` (L66)
  - `test_success_cause_structured()` (L75)
  - `test_all_failure_causes_enumerable()` (L85)
  - `test_all_success_causes_enumerable()` (L91)
  - `test_opportunity_timeline_records_events()` (L96)
  - `test_record_outcome_fans_out()` (L107)
- `class TestAnalyticsAndColdStart(_MemoryTestBase)` (L123)
  - `_seed(n_accept, n_fail, category='writing', platform='Upwork')` (L124)
  - `test_confidence_low_at_n1()` (L137)
  - `test_cold_start_neutral_when_empty()` (L144)
  - `test_confidence_rises_after_min_samples()` (L149)
  - `test_most_reliable_platforms()` (L155)
  - `test_platforms_poor_acceptance()` (L164)
  - `test_best_performing_task_types()` (L170)
  - `test_net_hourly_category()` (L176)
  - `test_best_proposal_templates()` (L187)
  - `test_recurring_failure_causes()` (L193)
  - `test_reusable_and_avoid_strategies()` (L201)
  - `test_profitable_but_often_fail()` (L221)
  - `test_task_types_high_completion()` (L229)
- `class TestOutcomesFlowIntoDecisions(_MemoryTestBase)` (L236) — T5: recorded outcomes must change the engine's verdict/priors.
  - `test_cold_start_then_history_changes_engine()` (L239)
  - `test_failures_lower_engine_ev()` (L259)


### `tests/earning/test_economic_accounting.py` — tests/test_economic_accounting.py — Unified Economic Accounting Layer (v2.0.36j). (392L)

**Functions:**
- `_payment(subject_id: str, amount: float, currency: str='usd', status, ...) -> Evidence` (L37) — Create a payment evidence with given status.
- `_expense(subject_id: str, amount: float, evidence_type: str, currenc, ...) -> Evidence` (L54) — Create an expense evidence.

**Classes:**
- `class FakeEvidenceStore` (L20) — In-memory evidence store for testing.
  - `__init__(evidence_list: Optional[List[Evidence]]=None)` (L22)
  - `for_subject(subject_type: str, subject_id: str) -> List[Evidence]` (L25)
  - `record(ev: Evidence) -> Evidence` (L29)
  - `add(ev: Evidence) -> None` (L33)
- `class TestCurrencyConversion` (L72)
  - `test_usd_identity()` (L73)
  - `test_eth_conversion()` (L76)
  - `test_btc_conversion()` (L79)
  - `test_usdc_stable()` (L82)
  - `test_case_insensitive()` (L85)
  - `test_custom_rates()` (L88)
- `class TestUSD` (L95)
  - `test_simple_usd_payment()` (L96)
  - `test_multiple_usd_payments()` (L105)
- `class TestCrypto` (L117)
  - `test_eth_payment()` (L118)
  - `test_btc_payment()` (L125)
  - `test_mixed_usd_crypto()` (L132)
- `class TestPlatformFees` (L143)
  - `test_platform_fee_deducted()` (L144)
  - `test_fee_stored_on_payment_evidence()` (L155) — Fees stored directly on payment evidence are counted.
- `class TestGas` (L167)
  - `test_gas_expense()` (L168)
  - `test_gas_on_payment()` (L176)
- `class TestLLMCosts` (L186)
  - `test_llm_cost()` (L187)
- `class TestZeroRevenue` (L199)
  - `test_no_evidence()` (L200)
  - `test_advertised_not_revenue()` (L209) — Advertised amount is tracked but NOT counted as revenue.
- `class TestPartialPayments` (L227)
  - `test_partial_then_full()` (L228)
  - `test_unverified_partial()` (L236)
- `class TestFailedPayments` (L248)
  - `test_rejected_payment_not_revenue()` (L249)
- `class TestDisputedPayments` (L260)
  - `test_disputed_not_verified()` (L261)
- `class TestDuplicatePayments` (L272)
  - `test_duplicate_evidence_both_counted_by_amount()` (L273) — Duplicate payment evidence (same tx) — amounts are summed (dedup is
- `class TestVerifiedUnverified` (L288)
  - `test_separates_verified_unverified()` (L289)
- `class TestNegativeProfit` (L302)
  - `test_expenses_exceed_revenue()` (L303)
- `class TestROIHourly` (L315)
  - `test_roi()` (L316)
  - `test_net_hourly_rate()` (L324)
- `class TestPredictionAccuracy` (L335)
  - `test_revenue_error()` (L336)
  - `test_effort_error()` (L352)
- `class TestAggregate` (L369)
  - `test_aggregate_multiple()` (L370)
  - `test_aggregate_empty()` (L384)


### `tests/earning/test_economic_policy.py` — (no module docstring) (122L)

**Classes:**
- `class TestEconomicPrediction` (L11)
  - `test_expected_net_value_keeps_costs_and_waiting_time_separate()` (L12)
  - `test_invalid_probability_is_rejected()` (L36)
- `class TestDecisionPolicy` (L44)
  - `setUp()` (L45)
  - `test_selects_when_policy_gates_pass()` (L56)
  - `test_defers_when_economic_threshold_fails()` (L69)
  - `test_requests_research_for_low_confidence_only()` (L78)
  - `test_rejects_stale_or_unsafe_prediction()` (L95)
  - `test_rejects_insufficient_autonomy()` (L109)


### `tests/earning/test_financial_integrity_060.py` — ARCH-ENG-060..069 — financial-integrity regression tests. (552L)

**Functions:**
- `_payment_evidence(subject_id, amount=4000.0, level=VerificationLevel.L3, meth, ...)` (L53)
- `_eligible_chain(subject_id, amount=4000.0)` (L62) — A full SUBMITTED->PAID chain: submission + completion + payment.
- `_tracker(store=None)` (L104) — A tracker that never touches disk.
- `_real_store()` (L117) — A real EvidenceStore backed by a throwaway sqlite DB.

**Classes:**
- `class _StoreStub` (L83) — Minimal EvidenceStore surface the lifecycle uses.
  - `__init__(items=None)` (L86)
  - `record(ev)` (L89)
  - `get(evidence_id)` (L93)
  - `for_subject(subject_type, subject_id)` (L99)
- `class TestStageVerifyFailsClosed` (L123) — ARCH-ENG-060 — an exception during paid-verification is NOT a payout.
  - `_loop()` (L126)
  - `test_lifecycle_exception_leaves_paid_false()` (L133)
  - `test_lifecycle_returning_none_leaves_paid_false()` (L157)
- `class TestRejectedTransitionDoesNotMoveStage` (L180) — ARCH-ENG-061 — the allowed-transition table must actually gate.
  - `test_in_progress_cannot_go_back_to_queued()` (L183)
  - `test_paid_opportunity_cannot_be_demoted_to_failed()` (L194)
  - `test_failed_opportunity_is_not_resurrected_to_paid()` (L210)
  - `test_completed_is_not_reachable_from_discovered()` (L219) — `completed` IS a legal terminal stage from `discovered` (an abandoned
- `class TestPaidMustPassThroughStateMachine` (L234) — ARCH-ENG-062 — no direct `_append(state, 'paid')` bypass.
  - `test_l5_onchain_payout_routes_through_claimed()` (L237)
  - `test_payout_reaches_paid_from_every_live_stage()` (L249) — ARCH-ENG-062 regression: a verified payout must not be BLOCKED because
  - `test_terminal_stages_can_never_reach_paid()` (L276)
  - `test_freelance_route_still_reaches_paid_from_submitted()` (L281)
- `class TestReconcileMethodAllowList` (L292) — ARCH-ENG-065 — only independent methods may escalate to VERIFIED.
  - `_unverified()` (L295)
  - `test_arbitrary_method_cannot_escalate()` (L303)
  - `test_independent_method_still_escalates()` (L309)
- `class TestReconcileBooksSettledAmount` (L316) — ARCH-ENG-065 — book the reconciled amount, not the operator's claim.
  - `test_reconciled_amount_wins_over_claim()` (L319)
- `class TestVerifiedRevenueReadsRealEvidence` (L366) — ARCH-ENG-064 — trust must not be inverted.
  - `test_genuine_l5_payout_counts_as_verified()` (L369)
  - `test_self_reported_dict_without_status_is_not_trusted_by_default()` (L383)
  - `test_low_level_evidence_is_not_verified_revenue()` (L393)
- `class TestExpenseVocabulary` (L403) — ARCH-ENG-067 — `payment_*` expense evidence must be counted.
  - `test_payment_expenses_are_recognised()` (L406)
- `class TestPendingRevenueBucket` (L425) — ARCH-ENG-069 — UNVERIFIED money belongs in pending, not lost.
  - `test_unverified_payment_lands_in_pending()` (L428)
- `class TestMarkFinalOutcomeZeroesUnverifiedRevenue` (L439) — ARCH-ENG-068 — a downgraded outcome must not keep its revenue.
  - `test_unverified_paid_records_no_revenue_to_learning()` (L442)
  - `test_verified_paid_keeps_its_revenue()` (L472)
- `class TestTerminalStatusIsNotCommittedOnRefusal` (L514) — ARCH-ENG-061 — a refused transition must not change `status` either.
  - `test_mark_rejected_cannot_demote_a_paid_opportunity()` (L517)
  - `test_mark_final_outcome_generic_branch_only_commits_on_success()` (L534)


### `tests/earning/test_freelance_finder.py` — (no module docstring) (41L)

**Classes:**
- `class FakeWeb` (L6)
  - `__init__()` (L7)
  - `search(query, max_results=10)` (L10)
- `class TestFreelanceFinder` (L22)
  - `test_default_targets_include_agent_and_crypto_work()` (L23)
  - `test_targeted_marketplace_results_are_normalized()` (L29)


### `tests/earning/test_goal_system.py` — tests/test_goal_system.py — Unit tests for GoalTracker SQLite persistence. (236L)

**Classes:**
- `class TestGoalTrackerCRUD` (L11)
  - `setUp()` (L12)
  - `tearDown()` (L16)
  - `test_create_and_get()` (L22)
  - `test_get_missing_returns_none()` (L31)
  - `test_list_active()` (L34)
  - `test_list_all()` (L42)
  - `test_update()` (L50)
  - `test_delete()` (L58)
- `class TestGoalTrackerEvidence` (L66)
  - `setUp()` (L67)
  - `tearDown()` (L73)
  - `test_add_evidence_verified_updates_current_usd()` (L79)
  - `test_add_evidence_unverified_does_not_update()` (L85)
  - `test_list_evidence()` (L91)
- `class TestGoalTrackerProgress` (L100)
  - `setUp()` (L101)
  - `tearDown()` (L107)
  - `test_add_earnings()` (L113)
  - `test_check_completion_partial_stays_active()` (L118)
  - `test_check_completion_complete()` (L124)
  - `test_summary()` (L131)
- `class TestGoalTrackerEvents` (L146)
  - `setUp()` (L147)
  - `tearDown()` (L151)
  - `test_process_event_with_goal_id()` (L157)
  - `test_process_event_auto_match()` (L171)
  - `test_process_event_unknown_ignored()` (L185)
- `class TestGoalModel` (L198)
  - `test_goal_progress_pct()` (L199)
  - `test_goal_progress_pct_zero_target()` (L203)
  - `test_goal_progress_pct_capped()` (L207)
  - `test_goal_to_dict_roundtrip()` (L211)
  - `test_evidence_to_dict_roundtrip()` (L223)


### `tests/earning/test_huggingface_models.py` — (no module docstring) (185L)

**Functions:**
- `test_list_name_classification_handles_dense_and_moe_variants()` (L14)
- `test_embedding_gguf_is_discoverable()` (L32)
- `test_inspect_keeps_chat_gguf_and_excludes_mmproj()` (L44)
- `test_api_redirect_to_http_is_rejected()` (L68)
- `test_api_redirect_to_untrusted_https_host_is_rejected()` (L82)
- `test_search_uses_full_paginated_list_without_n_plus_one_inspection()` (L96)
- `test_download_verifies_checksum_and_renames_atomically(tmp_path: Path)` (L130)
- `test_download_removes_partial_file_when_response_is_oversized(tmp_path: Path)` (L154)
- `test_response_total_uses_absolute_content_range_for_resume()` (L176)
- `test_response_total_does_not_add_existing_to_full_content_length()` (L182)


### `tests/earning/test_learning_history_writes.py` — Regression test: processing an outcome populates learning_history so the (53L)

**Functions:**
- `loop()` (L15)
- `test_process_outcome_writes_learning_history(loop)` (L27)
- `test_rejected_outcome_does_not_write_learning_history(loop)` (L44)


### `tests/earning/test_learning_loop.py` — tests/test_learning_loop.py — Opportunity Learning Loop (v2.0.36d) extensive tests. (326L)

**Functions:**
- `_mem()` (L23)
- `_loop(mem)` (L28)

**Classes:**
- `class TestPredictionCaptureAndAccuracy` (L33)
  - `setUp()` (L34)
  - `test_predicted_vs_actual_effort_error()` (L38)
  - `test_predicted_vs_actual_revenue_error()` (L49)
  - `test_success_probability_wrong_when_actual_fails()` (L57)
  - `test_success_probability_correct_when_actual_paid()` (L64)
  - `test_no_prediction_recorded_when_not_supplied()` (L70)
  - `test_accuracy_confidence_low_at_n1_rises_with_samples()` (L77)
- `class TestRecencyWeighting` (L87)
  - `setUp()` (L88)
  - `_seed(recent_rev, old_rev, old_age_days=365)` (L93)
  - `test_recent_outcome_dominates_average()` (L107)
  - `test_history_retained_for_audit()` (L114)
  - `test_recency_weight_function_monotonic()` (L123)
- `class TestElevenMetrics` (L131)
  - `setUp()` (L132)
  - `_seed_funnel()` (L136)
  - `test_all_eleven_metrics_present()` (L145)
  - `test_funnel_rates_correct()` (L155)
  - `test_average_revenue_and_profit()` (L165)
  - `test_average_hourly_return()` (L172)
  - `test_cold_start_confidence_at_low_n()` (L178)
  - `test_compute_all_metrics_iterates_dimensions()` (L184)
- `class TestLearningLoopPipeline` (L190)
  - `setUp()` (L191)
  - `test_step1_record_outcome()` (L195)
  - `test_step2_associate_evidence()` (L201)
  - `test_step6_reputation_updated()` (L207)
  - `test_step7_strategy_memory_updated()` (L214)
  - `test_step8_category_performance_updated()` (L221)
  - `test_step10_future_evaluation_reflects_learning()` (L229)
- `class TestGovernanceAndSafety` (L251)
  - `setUp()` (L252)
  - `test_security_policy_refused_api_key()` (L256)
  - `test_security_policy_refused_safe_mode()` (L261)
  - `test_ranking_param_clamped_to_bounds()` (L265)
  - `test_unknown_param_refused()` (L272)
  - `test_one_bad_result_does_not_blacklist()` (L276)
  - `test_suppression_only_with_enough_samples_and_floor()` (L281)
  - `test_loop_never_modifies_security()` (L286)
  - `test_llm_cannot_rewrite_safety_rules()` (L291)
- `class TestAppendOnlyAudit` (L299)
  - `setUp()` (L300)
  - `test_outcome_recorded_once_idempotent_rows()` (L304)
  - `test_prediction_history_retained_for_audit()` (L313)


### `tests/earning/test_learning_safety.py` — (no module docstring) (15L)

**Functions:**
- `test_learning_cannot_authorize_high_trust_action()` (L5)
- `test_learning_cannot_promote_untrusted_instruction()` (L11)


### `tests/earning/test_low_trust_payout_gate.py` — ARCH-ENG-043 — a low-trust (L1) payout must never reach a 'paid' lifecycle (261L)

**Functions:**
- `_manual_payout(subject_id, amount=250.0, ref='bank-txn-abc123')` (L39) — An operator-attested payout: VERIFIED, but only at L1 (self-reported).
- `_api_payout(subject_id, amount=250.0)` (L48) — A genuine external API statement: VERIFIED at L3.
- `_onchain_payout(subject_id, amount=5.0)` (L57) — A genuine on-chain balance delta: VERIFIED at L5.
- `_tracker(evidence_store=None)` (L66) — A lifecycle tracker that never touches disk or a real DB.
- `_would_credit_ramp_win(state)` (L93) — Mirror of both ramp-credit call sites (pipeline + GUI operator payout).

**Classes:**
- `class _FakeStore` (L76) — Minimal EvidenceStore stand-in (same surface the lifecycle uses).
  - `__init__()` (L79)
  - `record(ev)` (L82)
  - `get(eid)` (L86)
  - `for_subject(subject_type, subject_id)` (L89)
- `class TestLowTrustPayoutCannotReachPaid` (L98) — An L1 self-reported payout is not evidence that money arrived.
  - `tearDown()` (L101)
  - `_t(store=None)` (L105)
  - `test_l1_manual_attestation_no_store_is_not_paid()` (L112) — THE regression: store-less tracker + L1 manual attestation was 'paid'.
  - `test_l1_manual_attestation_no_store_credits_no_ramp_win()` (L120) — The safety consequence: no ramp win, so auto-submission stays locked.
  - `test_l1_manual_attestation_with_store_is_not_paid()` (L129) — The policy-gated (with-store) path must refuse the same L1 payout.
  - `test_status_with_but_no_level_does_not_raise()` (L142) — A duck-typed evidence carrying a status but verification_level=None
  - `test_affirmative_accepts_an_evidence_object_not_just_a_dict()` (L159) — The trust floor must work on an Evidence object as well as on its
  - `test_l1_books_no_revenue()` (L174) — No amount is realised from an unproven payout.
  - `test_none_evidence_no_store_is_not_paid()` (L183) — `evidence=None` reached this branch and must not raise.
  - `test_l3_api_statement_still_verifies()` (L192)
  - `test_l5_onchain_delta_still_verifies()` (L200)
  - `test_l3_with_zero_amount_is_refused()` (L206) — The amount gate the with-store path enforces applies here too.
- `class TestAffirmativeVerificationTrustFloor` (L214) — `is_affirmative_verification` must consider trust LEVEL, not just status.
  - `_state(status, level)` (L217)
  - `test_l1_verified_is_not_affirmative_for_money()` (L224)
  - `test_l2_verified_is_not_affirmative_for_money()` (L227)
  - `test_l3_verified_is_affirmative()` (L230)
  - `test_l5_verified_is_affirmative()` (L233)
  - `test_partially_verified_l1_is_not_affirmative()` (L236)
  - `test_unverified_status_never_affirmative()` (L240)
  - `test_missing_level_fails_closed()` (L243)
  - `test_none_state_is_not_affirmative()` (L251)
  - `test_floor_matches_the_policy_constant()` (L254) — The floor must equal the policy's L3 external-source level.


### `tests/earning/test_moltbook_agent.py` — (no module docstring) (70L)

**Classes:**
- `class _InstructionGate` (L11)
  - `__init__(status='allowed')` (L12)
  - `fetch_instruction(url, **kwargs)` (L15)
- `class TestMoltbookAgentCapability` (L20)
  - `test_reads_official_skill_before_planning()` (L21)
  - `test_registration_waits_for_capability_approval()` (L28)
  - `test_registration_returns_claim_details_without_api_key()` (L36)
  - `test_incomplete_plan_is_blocked()` (L61)


### `tests/earning/test_moltbook_poster.py` — Phase E — MoltbookPoster real read+write client (ARCH-ENG-086). (164L)

**Classes:**
- `class _Resp` (L16)
  - `__init__(payload=None, status=200)` (L17)
  - `raise_for_status()` (L21)
  - `json()` (L25)
- `class _Client` (L29) — Records calls; returns a queued response per call.
  - `__init__(payload=None, status=200)` (L32)
  - `_record(method, url, **kw)` (L37)
  - `get(url, **kw)` (L41)
  - `post(url, **kw)` (L44)
- `class TestMoltbookPosterGates` (L48)
  - `setUp()` (L49)
  - `tearDown()` (L52)
  - `test_create_post_requires_approval()` (L55)
  - `test_reply_requires_approval()` (L61)
  - `test_upvote_requires_approval()` (L66)
  - `test_missing_key_blocks()` (L71)
  - `test_offline_blocks_cleanly()` (L78)
- `class TestMoltbookPosterCalls` (L85)
  - `setUp()` (L86)
  - `tearDown()` (L89)
  - `test_create_post_endpoint_and_auth()` (L92)
  - `test_link_post_sets_type()` (L108)
  - `test_verification_challenge_surfaced_not_faked()` (L115)
  - `test_reply_endpoint_and_parent()` (L125)
  - `test_upvote_endpoints()` (L136)
  - `test_feed_parse()` (L143)
  - `test_feed_needs_no_approval_but_needs_key()` (L155)


### `tests/earning/test_moltbook_registration.py` — Phase F1 — agent-driven Moltbook registration + human-claim handoff (ARCH-ENG-089). (150L)

**Classes:**
- `class _Resp` (L17)
  - `__init__(payload)` (L18)
  - `raise_for_status()` (L22)
  - `json()` (L25)
- `class _Client` (L29)
  - `__init__(payload)` (L30)
  - `post(url, **kw)` (L34)
  - `get(url, **kw)` (L38)
- `class _NullGate` (L43)
  - `fetch_instruction(*a, **k)` (L44)
- `class TestAgentDrivenRegistration` (L52)
  - `setUp()` (L53)
  - `tearDown()` (L61)
  - `_register()` (L65)
  - `test_register_returns_claim_and_instructions()` (L75)
  - `test_register_stores_key_in_vault_not_logged()` (L84)
  - `test_register_requires_approval()` (L103)
  - `test_claim_status_maps_states()` (L111)
  - `test_claim_status_no_key()` (L124)
  - `test_request_human_claim_enqueues_pending()` (L131)


### `tests/earning/test_opportunity_discovery.py` — tests/test_opportunity_discovery.py — Generalized paid-opportunity discovery. (530L)

**Functions:**
- `_mk(url='https://x.com/1', src='s', **kw)` (L36)

**Classes:**
- `class TestOpportunityModel` (L46)
  - `test_required_fields_present()` (L57)
  - `test_unknown_category_preserved()` (L62)
  - `test_multiple_categories_classify()` (L66)
  - `test_taxonomy_is_not_closed()` (L72)
  - `test_identity_key_normalizes_for_dedup()` (L78)
- `class TestSourceInterfaceAndDedup` (L86)
  - `test_dedup_same_url_diff_source()` (L87)
  - `test_dedup_allows_different()` (L95)
  - `test_registry_runs_source_and_isolates_failure()` (L101)
  - `test_base_source_coerces_provenance()` (L123)
- `class FakeGig` (L136)
- `class FakeUpworkClient` (L141)
  - `__init__(*a, **k)` (L142)
  - `find_gigs(q, limit)` (L144)
- `class TestExistingIntegrationsAsSources` (L148)
  - `test_ugig_source_parses_public_hiring_listings()` (L149)
  - `test_upwork_source_sets_provenance_and_category()` (L175)
  - `test_upwork_source_empty_without_credentials()` (L187)
  - `test_content_source_is_deprecated_and_emits_nothing()` (L193)
  - `test_all_builtin_sources_are_registry_compatible()` (L202)
  - `test_moltbook_source_requires_explicit_api_key()` (L208)
  - `test_moltbook_source_filters_posts_and_preserves_provenance()` (L212)
  - `test_source_failure_isolated_by_registry()` (L241)
- `class _S(BaseOpportunitySource)` (L254)
  - `__init__(name, opps)` (L255)
  - `_discover(query=None, categories=None)` (L258)
- `class TestDiscoveryEngine` (L262)
  - `_opp(url, src)` (L263)
  - `test_engine_dedups_across_sources()` (L268)
  - `test_engine_isolates_source_failure()` (L279)
  - `test_engine_reports_by_category_stats()` (L292)
  - `test_engine_add_source_without_core_change()` (L304)
- `class TestPipelineWiring` (L320)
  - `test_discover_uses_discovery_engine_and_adapts()` (L321)
- `class TestWebDiscoverySource` (L348)
  - `test_web_source_disabled_by_default()` (L349)
  - `test_web_source_mock_returns_opps_with_provenance()` (L355)
  - `test_web_source_real_mode_without_flag_is_empty()` (L364)
  - `test_web_source_can_be_enabled_explicitly()` (L370)
- `class TestValidationVsEvaluation` (L377) — DISCOVERY != VALIDATION != EVALUATION. Validation is deterministic structure
  - `_opp(**kw)` (L381)
  - `test_usd_payment_is_valid()` (L387)
  - `test_crypto_payment_known_currency_is_valid()` (L394)
  - `test_missing_payment_info_invalid()` (L400)
  - `test_unknown_currency_flagged()` (L406)
  - `test_malformed_listing_no_title_invalid()` (L414)
  - `test_validation_never_returns_verified()` (L418)
  - `test_llm_positive_classification_does_not_verify()` (L425)
- `class TestRequiredScenarios` (L438) — The 13 required audit scenarios, enumerated explicitly.
  - `_opp(**kw)` (L441)
  - `test_1_multiple_opportunity_categories()` (L447)
  - `test_2_duplicate_detection()` (L454)
  - `test_3_malformed_listings()` (L460)
  - `test_4_missing_payment_information()` (L464)
  - `test_5_usd_payments()` (L468)
  - `test_6_crypto_payments()` (L473)
  - `test_7_unknown_currencies()` (L478)
  - `test_8_unknown_categories()` (L483)
  - `test_9_source_failures()` (L487)
  - `test_10_empty_source_results()` (L497)
  - `test_11_source_provenance()` (L507)
  - `test_12_duplicate_sources_same_opportunity()` (L513)
  - `test_13_llm_not_trusted_as_verified()` (L520)


### `tests/earning/test_opportunity_intelligence.py` — tests/test_opportunity_intelligence.py — Opportunity Intelligence Engine. (309L)

**Functions:**
- `_opp(**kw)` (L23)

**Classes:**
- `class TestFactorModel` (L33)
  - `setUp()` (L34)
  - `test_expected_value_formula()` (L37)
  - `test_expected_hourly_value()` (L48)
  - `test_p_success_is_acceptance_times_completion()` (L55)
  - `test_structured_reasons_present()` (L60)
  - `test_configurable_policy()` (L68)
- `class TestColdStart` (L77)
  - `setUp()` (L78)
  - `test_neutral_prior_used_without_memory()` (L81)
  - `test_cold_start_does_not_reject_category()` (L92)
  - `test_confidence_low_at_cold_start()` (L100)
- `class TestWithMemory` (L105)
  - `setUp()` (L106)
  - `_seed(platform=None, category=None, task_type=None, wins=0, losses=0, rev=0.0)` (L111)
  - `test_strong_history_boosts_verdict()` (L121)
  - `test_poor_history_lowers_success_prob()` (L134)
  - `test_history_helpers_zero_at_start()` (L147)
- `class TestVerdictClasses` (L152)
  - `setUp()` (L153)
  - `test_attractive_profitable()` (L156)
  - `test_marginal()` (L162)
  - `test_poor_low_value()` (L168)
  - `test_unsafe_high_scam()` (L174)
  - `test_unsafe_high_risk_level()` (L180)
  - `test_insufficient_information_missing_data()` (L186)
  - `test_blocked_structurally_invalid()` (L193)
- `class TestLLMNotAuthoritative` (L201)
  - `setUp()` (L202)
  - `test_llm_estimate_never_directly_sets_verdict()` (L205)
  - `test_missing_llm_estimate_uses_neutral_defaults()` (L214)
- `class TestScenariosSummary` (L221) — The 7 explicitly-required scenarios, named for auditability.
  - `setUp()` (L224)
  - `test_1_cold_start()` (L227)
  - `test_2_strong_history()` (L230)
  - `test_3_poor_history()` (L245)
  - `test_4_missing_data()` (L257)
  - `test_5_high_risk()` (L262)
  - `test_6_highly_profitable()` (L266)
- `class TestPipelineWiring` (L274) — Integration: EarningPipeline.evaluate() attaches the intelligence verdict.
  - `test_evaluate_attaches_intelligence()` (L277)


### `tests/earning/test_opportunity_lifecycle.py` — (no module docstring) (98L)

**Classes:**
- `class TestOpportunityLifecycle` (L12)
  - `test_chat_router_includes_lifecycle_snapshot()` (L13)
  - `test_tracker_moves_opportunity_through_stages()` (L44)
  - `test_tracker_marks_failed_state()` (L84)


### `tests/earning/test_opportunity_portfolio.py` — tests/test_opportunity_portfolio.py — Opportunity Portfolio & Work Queue (v2.0.36h). (442L)

**Functions:**
- `_sample_entry(opportunity_id='opp-1', work_status=WorkStatus.NEW, **overrides)` (L23)

**Classes:**
- `class TestPersistenceAndRecovery` (L54)
  - `setUp()` (L55)
  - `test_add_get_list()` (L58)
  - `test_transition_updates_status_and_timestamp()` (L70)
  - `test_restart_recovery()` (L81)
  - `test_remove()` (L98)
- `class FakeLifecycle` (L107) — Minimal lifecycle stub that exposes _ALLOWED_TRANSITIONS and mark_final_outcome.
  - `__init__()` (L121)
  - `get_state(opportunity_id)` (L124)
  - `mark_final_outcome(opportunity_id, outcome_state=..., **kwargs)` (L127)
  - `mark_paid_verified(opportunity_id, amount=0.0)` (L134)
  - `mark_failed(opportunity_id, note='')` (L137)
  - `mark_rejected(opportunity_id, reason='')` (L140)
- `class TestWorkStatusMachine` (L144)
  - `setUp()` (L145)
  - `test_valid_transition_allowed()` (L148)
  - `test_invalid_transition_rejected()` (L154)
  - `test_lifecycle_authoritative()` (L160) — Lifecycle is still authority: an illegal lifecycle transition is rejected.
  - `test_blocked_preserves_lifecycle_stage()` (L172)
  - `test_terminal_states_immutable()` (L182)
  - `test_full_valid_chain()` (L189) — A full NEW→PAY path works through the chain.
- `class TestQueueAndPolicy` (L207)
  - `setUp()` (L208)
  - `_make_entry(opportunity_id, work_status=WorkStatus.READY, **overrides)` (L219)
  - `test_prioritizes_high_ehv_low_risk_over_low_ehv_high_risk()` (L222) — User's example: high-EV-hourly + high-confidence + low-risk + good-skill-fit + near-deadline
  - `test_capacity_limits_active_tasks()` (L244) — With max_active_tasks=2 and 5 READY opps, select_next returns ≤ 2.
  - `test_high_risk_limit()` (L256) — With max_high_risk=1, a 2nd high-risk opp is skipped.
  - `test_financial_exposure_limit()` (L268) — Entries pushing exposure over max are skipped.
  - `test_custom_scorer_plugged()` (L283) — Inject a custom scorer; queue respects it (formula NOT hardcoded).
  - `test_configurable_weights_change_order()` (L296) — Flipping weights changes ranking.
  - `test_no_deadline_lowers_urgency()` (L314)
  - `test_summary()` (L328)
- `class TestNextAction` (L342)
  - `setUp()` (L343)
  - `test_resolve_next_action_each_status()` (L346) — Every status maps to a sensible action/reason.
  - `test_blocked_entry_action_reflects_reason()` (L359)
  - `test_waiting_external_action_reflects_reason()` (L365)
  - `test_apply_next_advances_through_chain()` (L372) — apply_next walks NEW → EVALUATING → QUALIFIED → RECOMMENDED → READY → IN_PROGRESS.
  - `test_apply_next_terminal_noop()` (L385)
- `class TestPipelineSync` (L392)
  - `setUp()` (L393)
  - `_make_legacy(opp_id, title='Test opp')` (L396) — Use the pipeline's legacy Opportunity model (has .id).
  - `test_evaluate_syncs_to_portfolio()` (L412) — After evaluate(), portfolio has entries with policy fields from intelligence verdict.
  - `test_pipeline_works_without_portfolio()` (L428) — Back-compat: evaluate() runs with portfolio=None.


### `tests/earning/test_opportunity_state_machine.py` — (no module docstring) (60L)

**Classes:**
- `class TestOpportunityStateMachine` (L11)
  - `test_invalid_transition_is_recorded()` (L12)
  - `test_valid_transition_updates_stage()` (L28)


### `tests/earning/test_persistence_dataloss_066.py` — ARCH-ENG-066/070 — persistence data-loss regression tests. (216L)

**Functions:**
- `_workshop(tmpdir)` (L39) — A Workshop rooted in a throwaway directory (never D:\ai_workshop).

**Classes:**
- `class TestCorruptStoreDoesNotEraseData` (L44) — ARCH-ENG-066 — an unreadable store must refuse to write, not wipe.
  - `setUp()` (L47)
  - `test_corrupt_accounts_file_is_not_overwritten()` (L51)
  - `test_corrupt_payments_file_is_not_overwritten()` (L64)
  - `test_healthy_store_still_accumulates()` (L75)
  - `test_non_dict_json_is_treated_as_unreadable()` (L86)
  - `test_write_is_atomic_no_temp_left_behind()` (L92)
  - `test_interrupted_write_leaves_original_file_intact()` (L97) — ARCH-ENG-066 crash-safety: an `os.replace` that fails mid-write must
- `class TestProviderListSavePreservesDevicePolicy` (L125) — ARCH-ENG-070 — the Settings Save button must not erase per-device config.
  - `setUp()` (L128)
  - `test_merge_preserves_devices_block()` (L131)
  - `test_merge_preserves_unrelated_sibling_keys()` (L148)
  - `test_corrupt_settings_is_quarantined_not_overwritten_silently()` (L161)
- `class TestSaveProviderListCallSitePreservesDevicePolicy` (L175) — ARCH-ENG-070 — the ACTUAL buggy call site, not just the helper.
  - `test_save_provider_list_preserves_devices_block()` (L183)


### `tests/earning/test_reputation.py` — Reputation must distinguish recorded work from verified earnings. (54L)

**Functions:**
- `_record(task_id, platform, payout, verified=False, costs=0.0)` (L9)

**Classes:**
- `class TestReputationVerification` (L23)
  - `test_unverified_completion_is_not_verified_earnings()` (L24)
  - `test_verified_platform_metrics_are_separate()` (L34)
  - `test_unverified_platform_does_not_win_verified_ranking()` (L44)


### `tests/earning/test_search_strategy_memory.py` — tests/test_search_strategy_memory.py — Search Strategy Memory (v2.0.36g). (207L)

**Functions:**
- `_run(m: EarningMemory, sid, origin, q, src, plat, catt, tt, res)` (L27) — Simulate 3 discovery runs so strategies exit cold-start (used_count >= MIN_SAMPLES).

**Classes:**
- `class TestSchemaAndTracking` (L35)
  - `setUp()` (L36)
  - `test_all_tracked_fields()` (L39)
- `class TestSemanticallyRelatedDifferentOutcomes` (L68)
  - `setUp()` (L69)
  - `test_three_example_strategies()` (L72)
- `class TestNotOptimizingForVolume` (L104)
  - `setUp()` (L105)
  - `test_volume_useless_ranks_below_low_volume_profitable()` (L108)
- `class TestExplorationPreserved` (L122)
  - `setUp()` (L123)
  - `test_novel_strategy_not_suppressed()` (L126)
  - `test_failed_terms_require_min_samples_cold_start_safe()` (L137)
- `class TestSchedulerAvailability` (L150)
  - `setUp()` (L151)
  - `test_successful_terms_ranked_by_usefulness()` (L154)
  - `test_top_by_usefulness_default()` (L164)
  - `test_normalize_groups_related_queries()` (L173)
- `class TestMigration` (L181)
  - `test_old_schema_gets_new_columns()` (L182)


### `tests/earning/test_self_audit.py` — tests/test_self_audit.py — Self-Audit & Continuous-Improvement Layer (v2.0.36j-T4). (457L)

**Functions:**
- `_make_db(db_path, platforms=None, strategies=None, outcomes=None)` (L137) — Create a minimal DB with required tables and optional data.

**Classes:**
- `class FakeMemory` (L14) — Memory backed by a real temp SQLite DB so audit queries work.
  - `__init__(db_path: str, portfolio=None, wallet_manager=None)` (L16)
  - `get_platform_reputation(platform: str) -> Optional[Dict]` (L21)
  - `get_prediction_accuracy(dim: str='global', value: str='global') -> Dict` (L40)
  - `compute_all_metrics(dim: str='category') -> List[Any]` (L58) — Compute simple metrics directly from outcome_memory_v2.
  - `get_successful_patterns(pattern_type: str, min_confidence: float=0.0) -> List[Dict]` (L106)
- `class FakePortfolio` (L123)
  - `__init__(entries=None)` (L124)
  - `load_all()` (L127)
- `class FakeEntry` (L131)
  - `__init__(opportunity_id, work_status_val)` (L132)
- `class TestSelfAuditEngine` (L236)
  - `test_no_findings_on_empty_memory()` (L238) — Empty memory should produce no findings.
  - `test_detects_poor_platform()` (L247) — Platform with 0% acceptance should be flagged.
  - `test_detects_repeated_failures()` (L258) — Platform with >= 70% failure rate should be flagged.
  - `test_detects_prediction_error()` (L268) — Large revenue prediction error should be flagged.
  - `test_detects_bad_strategy()` (L287) — Strategy with usefulness < 0.2 should be flagged.
  - `test_detects_poor_category()` (L301) — Category with < 10% acceptance should be flagged.
  - `test_detects_poor_task_type()` (L317) — Task type with good acceptance but poor hourly return should be flagged.
  - `test_detects_low_performing_variant()` (L333) — Proposal variant with < 15% acceptance should be flagged.
  - `test_detects_human_intervention()` (L351) — High rate of AWAITING_APPROVAL should be flagged.
  - `test_detects_execution_failures()` (L364) — Blocked/failed entries should be flagged.
  - `test_detects_stale_providers()` (L379) — Provider with no activity in 60 days should be flagged.
  - `test_detects_stale_categories()` (L391) — Category with no recent activity should be flagged.
  - `test_detects_security_problems()` (L405) — Wallet validation failures should be flagged.
  - `test_no_findings_below_threshold()` (L417) — Platforms with acceptable performance should not be flagged.
- `class TestAuditReport` (L428)
  - `test_to_dict()` (L429)
  - `test_by_category()` (L441)


### `tests/earning/test_self_improvement_wiring.py` — Self-improvement outcome wiring (Phase C, v2.1.72, ARCH-ENG-082). (81L)

**Functions:**
- `_pipeline(tmp)` (L24) — Build a minimal EarningPipeline-like object with just the pieces

**Classes:**
- `class TestSelfImprovementWiring` (L36)
  - `setUp()` (L37)
  - `test_verified_outcome_feeds_engine()` (L40)
  - `test_unverified_outcome_does_not_learn()` (L51)
  - `test_engine_state_persists_across_instances()` (L60)
  - `test_feed_never_raises_on_engine_error()` (L70)


### `tests/earning/test_shared_research_context.py` — (no module docstring) (68L)

**Classes:**
- `class TestSharedResearchContext` (L14)
  - `test_chat_router_includes_shared_research_snapshot()` (L15)
  - `test_shared_context_concurrent_writes_preserve_json()` (L36)


### `tests/earning/test_social_writer_factory.py` — Phase E — social_writer_factory wires social_post to a real MoltbookPoster (106L)

**Functions:**
- `_make_requests(payload)` (L30)

**Classes:**
- `class _Resp` (L18)
  - `__init__(payload)` (L19)
  - `raise_for_status()` (L23)
  - `json()` (L26)
- `class TestFactoryNoKey` (L44)
  - `test_no_writer_without_key()` (L45)
- `class TestFactoryWithKey` (L51)
  - `setUp()` (L52)
  - `tearDown()` (L57)
  - `_writer(payload=None)` (L61)
  - `test_new_post_uses_title_and_body()` (L67)
  - `test_reply_uses_comment_endpoint()` (L80)
  - `test_verification_surfaced_not_faked()` (L88)
  - `test_unsupported_network()` (L98)


### `tests/earning/test_strategy_feedback.py` — Strategy feedback + ranking integration (Phase C, ARCH-ENG-081). (123L)

**Functions:**
- `_run(opp_id, success=..., paid=..., amount=..., decision=...)` (L26)

**Classes:**
- `class _FakeStore` (L18) — Minimal stand-in for AutonomousRunStore.list_runs().
  - `__init__(rows)` (L20)
  - `list_runs(limit=50)` (L22)
- `class TestAggregation` (L31)
  - `test_per_platform_rates_and_totals()` (L32)
  - `test_financial_truth_only_paid_runs_count()` (L52) — An unpaid run with a nonzero payment_amount must NOT inflate totals.
  - `test_unresolved_platform_bucketed_not_dropped()` (L63)
  - `test_summary_lines_exclude_unresolved()` (L70)
- `class TestRankingAdjustment` (L80)
  - `_stats(rows, resolver)` (L81)
  - `test_cold_start_no_adjustment()` (L84) — Fewer than min_runs -> adjustment is exactly 1.0 (no distortion).
  - `test_paying_platform_bonus()` (L90)
  - `test_never_paid_penalty()` (L95)
  - `test_unknown_platform_no_adjustment()` (L100)
  - `test_adjustment_clamped()` (L104)
- `class TestStoreReadSafety` (L112)
  - `test_unreadable_store_yields_no_feedback()` (L113)


### `tests/earning/test_submission_gate_boundary.py` — The real human gate for autonomous submissions is the submission ramp. (160L)

**Functions:**
- `_opp(amount=25.0, platform='upwork', task_type='writing')` (L60)
- `_submit(opp, memory=None, trust_boundary=None)` (L82) — Call the proposal path exactly as the autonomous loop does: no confirm_cb.

**Classes:**
- `class _RampIsolation` (L36) — Reset the process-wide ramp singleton around every test.
  - `setUp()` (L46)
  - `tearDown()` (L56)
- `class _RecordingClient` (L68) — Stands in for a real platform client; records whether it was reached.
  - `__init__()` (L71)
  - `can_submit()` (L74)
  - `submit_proposal(**kwargs)` (L77)
- `class TestAutonomousSubmissionIsGatedDownstream(_RampIsolation)` (L95)
  - `test_cold_start_blocks_submission_and_never_calls_the_client()` (L96) — The default (no history) state must fail closed.
  - `test_low_win_rate_blocks_even_with_enough_submissions()` (L104) — Many submissions but a weak win-rate must still require a human.
  - `test_ai_disallowed_policy_overrides_a_warm_ramp()` (L112) — Platform policy wins: the ramp may only ever relax, never override.
  - `test_relaxed_ramp_is_the_documented_and_only_auto_path()` (L131) — Pins the one path that auto-submits, so it stays deliberate.
- `class TestApprovalStageScopeIsDocumented` (L147)
  - `test_request_approval_stage_declares_its_real_scope()` (L148) — The stage must not look like the only human gate when it is not one.


### `tests/earning/test_task_capabilities.py` — tests/test_task_capabilities.py — reusable Skill/Task capability framework (v2.0.36e). (239L)

**Classes:**
- `class TestTaxonomyExtensible` (L28)
  - `test_seed_categories_present()` (L29)
  - `test_registry_seeded_with_system_caps()` (L35)
  - `test_taxonomy_extensible_via_register()` (L41)
  - `test_by_category_groups_coding_cluster()` (L49)
  - `test_skill_file_reuse_pointer()` (L55)
- `class TestTaskSpecFields` (L62)
  - `test_task_carries_ten_required_fields()` (L63)
  - `test_normalized_requirements_are_upper_and_unique()` (L76)
- `class TestSemanticInference` (L81)
  - `test_proofread_maps_to_reading_editing_document_qa()` (L82)
  - `test_fix_python_bug_maps_to_coding_debugging_testing()` (L88)
  - `test_research_companies_maps_to_web_data_analysis()` (L94)
  - `test_transcribe_maps_to_transcription()` (L100)
  - `test_build_task_infers_and_stores()` (L103)
  - `test_llm_inferrer_is_optional_and_fails_safe()` (L108)
- `class TestValidatorVerdicts` (L118)
  - `setUp()` (L119)
  - `test_proofread_fully_automatable()` (L122)
  - `test_fix_python_fully_automatable()` (L128)
  - `test_research_fully_automatable()` (L133)
  - `test_transcribe_human_required()` (L138)
  - `test_transcribe_without_human_is_unsupported()` (L144)
  - `test_partially_automatable_mix()` (L150)
  - `test_unsupported_capability_is_not_executable()` (L159)
  - `test_missing_capability_with_human_is_human_required()` (L169)
  - `test_no_requirements_is_unsupported_not_executable()` (L175)
  - `test_validator_writes_execution_mode_back()` (L180)
  - `test_classify_single_capability()` (L190)
- `class TestOpportunityIntegration` (L196)
  - `test_task_from_opportunity_maps_skills()` (L197)
  - `test_opportunity_task_validates_against_registry()` (L207)
- `class TestUnsupportedNeverExecutable` (L217) — Explicit guard: the framework must never present an unsupported task as runnable.
  - `test_any_unsupported_verdict_has_false_executable()` (L220)


### `tests/earning/test_task_execution.py` — tests/test_task_execution.py — Generalized Task Execution Framework (v2.0.36i). (353L)

**Classes:**
- `class TestValidators` (L30) — Task-specific deterministic validators.
  - `test_coding_validator_pass()` (L35)
  - `test_coding_validator_fail_no_tests()` (L47)
  - `test_writing_validator_pass()` (L54)
  - `test_writing_validator_fail_too_short()` (L62)
  - `test_research_validator_pass()` (L69)
  - `test_research_validator_fail_no_sources()` (L84)
  - `test_data_validator_pass()` (L91)
  - `test_data_validator_fail_empty()` (L99)
  - `test_transcription_validator_pass()` (L106)
  - `test_transcription_validator_fail_overlap()` (L117)
  - `test_document_validator_pass()` (L130)
  - `test_document_validator_fail_missing_field()` (L139)
  - `test_get_validator_coding()` (L149)
  - `test_get_validator_writing()` (L153)
  - `test_get_validator_unknown_fallback()` (L157)
  - `test_validator_registry_has_all_types()` (L161)
- `class TestHumanGates` (L166) — Human-in-the-loop gate manager.
  - `test_detects_payment_gate()` (L169)
  - `test_detects_contracts_gate()` (L175)
  - `test_detects_signatures_gate()` (L181)
  - `test_detects_identity_gate()` (L187)
  - `test_detects_sensitive_gate()` (L193)
  - `test_detects_irreversible_gate()` (L199)
  - `test_detects_captcha_gate()` (L205)
  - `test_detects_platform_manual_gate()` (L211)
  - `test_requires_human_true()` (L217)
  - `test_requires_human_false()` (L222)
  - `test_clear_gate()` (L227)
  - `test_pending_gates()` (L234)
  - `test_no_gates_for_simple_task()` (L243)
- `class TestExecutor` (L250) — 14-step execution pipeline.
  - `setUp()` (L253)
  - `_make_entry(opp_id='opp-1')` (L263)
  - `test_full_pipeline_pass()` (L268) — Full 14-step pipeline for a coding task with valid output.
  - `test_pipeline_stops_at_human_gate()` (L288) — Pipeline stops at step 6 when human gate detected.
  - `test_pipeline_validation_failure()` (L301) — Pipeline fails at step 8 when validation fails.
  - `test_pipeline_not_executable()` (L316) — Pipeline fails when capability validator says unsupported.
  - `test_execution_context_audit()` (L329) — ExecutionContext records all steps.


### `tests/earning/test_verified_learning.py` — (no module docstring) (16L)

**Functions:**
- `test_learning_ignores_unverified_outcomes()` (L4)
- `test_learning_accepts_evidence_backed_outcomes()` (L10)


### `tests/earning/test_workflow_invariants.py` — (no module docstring) (19L)

**Functions:**
- `test_workflow_requires_proof_at_phase_boundaries()` (L4)


### `tests/earning/test_workflow_planner.py` — (no module docstring) (53L)

**Classes:**
- `class TestWorkflowPlanner` (L12)
  - `test_upwork_plan_includes_application_delivery_and_submission_steps()` (L13)
  - `test_unknown_platform_falls_back_to_manual_research_plan()` (L32)


### `tests/earning/test_workshop.py` — (no module docstring) (39L)

**Classes:**
- `class TestWorkshop` (L8)
  - `test_custom_root_creates_shared_structure()` (L9)
  - `test_paths_cannot_escape_workshop()` (L19)
  - `test_quota_rejects_new_bytes_but_allows_same_size_overwrite()` (L26)


### `tests/dialogue/__init__.py` — Dialogue tests. (2L)


### `tests/dialogue/test_chat_router.py` — (no module docstring) (47L)

**Classes:**
- `class TestChatRouter` (L12)
  - `test_general_chat_stays_on_chat_model()` (L13)
  - `test_analysis_queries_use_main_model_context()` (L19)
  - `test_task_requests_route_to_manager()` (L25)
  - `test_context_builder_includes_json_files()` (L31)


### `tests/dialogue/test_cognition.py` — (no module docstring) (83L)

**Functions:**
- `test_verified_information_requires_evidence()` (L19)
- `test_completed_action_requires_matching_execution_proof()` (L28)
- `test_verified_outcome_can_update_learning_only_with_evidence()` (L41)
- `test_claim_and_record_are_bus_serializable()` (L48)
- `test_supported_claim_without_evidence_is_rejected()` (L64)
- `test_cognition_ledger_publishes_and_persists_record()` (L73)


### `tests/dialogue/test_cognition_observability.py` — (no module docstring) (16L)

**Functions:**
- `test_ledger_exposes_summary_without_private_reasoning()` (L5)


### `tests/dialogue/test_contradictions.py` — (no module docstring) (20L)

**Functions:**
- `test_contradiction_requires_evidence_to_resolve()` (L5)
- `test_blocked_contradiction_cannot_be_reopened_implicitly()` (L16)


### `tests/dialogue/test_cross_turn_reread_guard.py` — Cross-turn tool re-read guard (Phase A, chat_completion._seed_executed_calls_from_history). (87L)

**Classes:**
- `class TestSeedExecutedCalls` (L29)
  - `test_seeds_web_read_url_from_history()` (L30)
  - `test_seeds_web_search_query()` (L41)
  - `test_key_matches_live_parser()` (L50) — The seeded key MUST equal the key the within-turn guard builds, or the
  - `test_no_calls_no_seed()` (L62)
  - `test_empty_and_malformed_history_safe()` (L68)
  - `test_multiple_calls_in_one_message()` (L77)


### `tests/dialogue/test_dialogue_circuit_breaker.py` — Regression test for the event-driven Live failure circuit breaker. (190L)

**Functions:**
- `_servers_up()` (L21) — Check whether both llama-server instances are reachable.
- `test_live_response_handler_keeps_running_after_provider_failures()` (L49) — Live must keep retrying after consecutive provider failures.
- `test_live_failure_handler_keeps_running_after_no_response_failures()` (L90) — The event-driven failure counter must support ongoing recovery.
- `test_live_mode_button()` (L126) — The event-driven runtime uses one Live button.
- `test_live_end_to_end_toggle()` (L150) — Full end-to-end: start and stop the event-driven Live runtime.


### `tests/dialogue/test_dialogue_context_guards.py` — Regression test: a maximal opportunity board must not evict the guard blocks. (137L)

**Functions:**
- `_maximal_board_tab(n: int=200, with_history: bool=True) -> DialogueTab` (L39)
- `test_main_path_keeps_all_guard_blocks_under_a_maximal_board()` (L63) — untested-pages, DIALOGUE CONTROL, and WORK TRACKER all survive.
- `test_first_turn_path_keeps_guard_blocks_and_stays_bounded()` (L76) — The first-turn path is bounded too and keeps its guard text.
- `test_board_is_bounded_not_truncated_mid_line()` (L90) — The board yields whole candidate lines, never a half-cut line.
- `_tab_with(n_board: int, n_hist: int, limit: int) -> DialogueTab` (L102)
- `test_tail_survives_when_history_alone_exceeds_a_small_limit()` (L119) — Boundary case: empty board + long history + small limit.

**Classes:**
- `class _StubBrain` (L16)
- `class _Ent` (L22) — A worst-case board entry (long title + long url).
  - `__init__(i: int)` (L25)


### `tests/dialogue/test_dialogue_context_ordering.py` — Regression test for dialogue context ordering (convergence + truncation). (118L)

**Functions:**
- `_make_tab() -> DialogueTab` (L26)
- `test_operator_directive_precedes_board()` (L41) — The human's latest instruction must be surfaced ahead of the board.
- `test_response_contract_survives_truncation()` (L57) — The response contract must sit before the board so it is never cut.
- `test_directive_tracks_the_most_recent_human_message()` (L74) — A newer human message must supersede an older one in the directive line.
- `test_header_names_the_actual_roster_not_a_hardcoded_pair()` (L90) — The context header must name THIS speaker and the ACTUAL peers on the

**Classes:**
- `class _StubBrain` (L20)


### `tests/dialogue/test_dialogue_context_tail_integrity.py` — Tail-integrity tests for the dialogue context assembly. (106L)

**Functions:**
- `_entry(i: int)` (L36)
- `_tab(entries: int, history_turns: int) -> DialogueTab` (L52)
- `_assert_mandatory_present(context: str, label: str)` (L76)
- `test_mandatory_framing_survives_a_full_board()` (L83)
- `test_mandatory_framing_survives_a_long_conversation()` (L88) — Worst case: elastic history AND a board both large at once.
- `test_mandatory_framing_survives_a_small_limit()` (L101) — The guarantee must hold for any configured limit, not just the default.

**Classes:**
- `class _StubBrain` (L30)


### `tests/dialogue/test_dialogue_conversation.py` — (no module docstring) (42L)

**Functions:**
- `test_preserves_natural_turn_and_extracts_non_authoritative_cues()` (L6)
- `test_decision_markers_do_not_authorize_execution()` (L27)
- `test_dialogue_is_bounded_without_silent_truncation()` (L36)


### `tests/dialogue/test_dialogue_duplicate_budgets.py` — Regression: the two duplicate paths must not share one retry budget. (95L)

**Functions:**
- `_tab(stop_recorder)` (L39)
- `test_repeated_text_uses_only_the_text_budget()` (L48)
- `test_semantic_duplicate_uses_only_the_semantic_budget()` (L63)
- `test_spent_text_budget_does_not_block_a_semantic_recovery()` (L78) — The behavioural proof of independence.

**Classes:**
- `class _StubBrain` (L29)


### `tests/dialogue/test_dialogue_honesty.py` — tests/test_dialogue_honesty.py — bounding + dedupe of the claim ledger. (73L)

**Classes:**
- `class TestDialogueHonestyBounding` (L16)
  - `test_repeated_claims_are_recorded_once()` (L18)
  - `test_ledger_is_bounded()` (L27)
  - `test_prune_never_drops_verified_claims()` (L35)
  - `test_prune_keeps_operator_superseded_audit_trail()` (L48)
  - `test_epistemic_note_is_bounded()` (L59)
  - `test_empty_ledger_produces_no_note()` (L66)


### `tests/dialogue/test_dialogue_live_mode_issues.py` — Regression tests for two live-mode defects reported by @user. (369L)

**Functions:**
- `_make_dialogue_fixture(monkeypatch)` (L43) — Return a DialogueTab whose __init__ does no Qt work.

**Classes:**
- `class TestHumanInputDroppedMidGeneration` (L184) — A manual turn issued while a worker is running must not be discarded.
  - `test_manual_turn_while_worker_running_is_not_consumed_as_an_autonomous_turn(monkeypatch)` (L196) — When a worker is mid-generation, respond(manual=True) must NOT proceed
  - `test_manual_persona_preserved_after_worker_returns(monkeypatch)` (L223) — The persona the human selected in the 'Next reply' combo must survive
  - `test_goal_update_restarts_in_flight_turn_with_new_context(monkeypatch)` (L248) — A goal entered during generation must replace the stale turn.
  - `test_queued_manual_turn_fires_even_in_live_mode(monkeypatch)` (L264) — A human message sent while a worker is mid-generation must be
- `class TestProgressSignalThrottled` (L298) — During generation the progress signal must not scale with token count.
  - `test_progress_emit_count_is_bounded_independent_of_token_count()` (L311) — Emitting 1000 chunks must NOT produce 1000 GUI update batches.
  - `test_throttler_reuses_existing_make_throttler_api()` (L340) — The fix must use gui.performance.make_throttler, not a new ad-hoc throttle.
  - `test_throttler_can_disconnect_pending_flush()` (L357) — Live-mode cleanup must be safe while a progress flush is pending.


### `tests/dialogue/test_dialogue_multiparty_routing.py` — Phase 4: multi-party routing — persistence keys + agent descriptors generalize (133L)

**Classes:**
- `class _FakeBrain` (L15)
  - `__init__(name)` (L16)
- `class TestMultiPartyRouting` (L20)
  - `_speakers()` (L21)
  - `_tab()` (L34)
  - `test_create_agent_runtime_builds_one_descriptor_per_speaker()` (L42)
  - `test_create_agent_runtime_legacy_fallback_two_brains()` (L58)
  - `test_round_robin_over_four_speakers()` (L70)
  - `test_round_robin_two_brains_is_alternation()` (L84)
  - `test_persist_dialogue_turn_persona_uses_registry_key()` (L90)
  - `test_persist_dialogue_turn_human_logs_all_brains()` (L108)


### `tests/dialogue/test_dialogue_nbrain_resolution.py` — Phase 2: DialogueTab resolves brains/tiers via the speaker registry. (90L)

**Classes:**
- `class _FakeBrain` (L18)
  - `__init__(name)` (L19)
- `class TestDialogueSpeakerResolution` (L23) — Build a DialogueTab-like object and exercise _brain_for/_tier_for_speaker
  - `_make_tab(speakers)` (L27)
  - `_speakers()` (L35)
  - `test_brain_for_primary_names()` (L48)
  - `test_tier_for_primary_names()` (L53)
  - `test_brain_for_third_speaker_resolves_lazily()` (L58)
  - `test_brain_for_unknown_falls_back_to_legacy()` (L68)
  - `test_speaker_for_returns_none_when_roster_absent()` (L73)
  - `test_runtime_key_for_third_speaker()` (L82)


### `tests/dialogue/test_dialogue_parallel_round.py` — (no module docstring) (28L)

**Functions:**
- `_tab()` (L6)
- `test_live_selects_one_agent_opportunity_and_then_the_other()` (L17)


### `tests/dialogue/test_dialogue_rate_limit_social.py` — Phase F2 — Dialogue per-response rate limit + opt-in social decision (ARCH-ENG-090). (95L)

**Functions:**
- `_bind_rate_gate()` (L26)

**Classes:**
- `class _FakeTab` (L15) — Minimal stand-in exposing just what _response_rate_gate touches.
  - `__init__()` (L18)
  - `respond(manual=False)` (L22)
- `class TestResponseRateGate` (L31)
  - `setUp()` (L32)
  - `tearDown()` (L43)
  - `test_first_turn_allowed_second_throttled()` (L46)
  - `test_disabled_when_zero()` (L52)
  - `test_invalid_env_falls_back()` (L58)
- `class TestSocialDecisionOptIn` (L66) — The social-decision block is appended only when the flag is on.
  - `_block()` (L69)
  - `setUp()` (L80)
  - `test_default_off()` (L83)
  - `test_enabled_appends_block()` (L86)


### `tests/dialogue/test_dialogue_response_corruption.py` — Regression tests for malformed local-model Dialogue output. (1090L)

**Classes:**
- `class TestDialogueResponseCorruption` (L20)
  - `test_glued_thinking_marker_is_stripped()` (L21) — LFM2.5 emits a bare ' thinking' marker glued to the reply
  - `test_normal_reply_is_untouched()` (L33) — A legitimate reply must not be mangled by the thinking-strip.
  - `test_corrupted_payload_is_rejected()` (L38)
  - `test_reasoning_about_prompt_loop_is_rejected()` (L51) — A model stuck re-verifying its own reply against the phase contract
  - `test_normal_first_person_reply_not_flagged_as_loop()` (L68) — A clean multi-sentence persona reply must NOT be mistaken for a loop
  - `test_training_continuations_and_code_are_rejected()` (L80)
  - `test_account_creation_cannot_be_declared_approved_by_research()` (L93)
  - `test_tiny_model_identity_and_failed_research_fallbacks_are_rejected()` (L104)
  - `test_tiny_model_gets_safe_progress_response_after_failed_retries()` (L114)
  - `test_tiny_fallback_responds_to_current_phase()` (L122)
  - `test_worker_forwards_streaming_dialogue_contract()` (L131)
  - `test_worker_bootstraps_loaded_model_when_adapter_is_unselected()` (L158)
  - `test_truncated_inline_reasoning_gets_larger_recovery_budget()` (L179)
  - `test_malformed_fallback_is_not_added_as_persona_turn()` (L219)
  - `test_empty_response_retries_same_speaker_without_transcript_turn(single_shot)` (L242)
  - `test_repeated_empty_response_retries_without_fake_persona_turn()` (L260)
  - `test_live_never_stops_on_repeated_empty_response(single_shot)` (L279)
  - `_make_accept_stub()` (L296) — DialogueTab stub with the attributes the accepted-turn path needs.
  - `test_valid_response_is_accepted_not_discarded_or_retried()` (L324) — A valid non-empty persona reply must reach the accept path — never
  - `test_two_empties_then_valid_response_resets_budget(single_shot)` (L345) — After the empty-retry budget is exhausted, an accepted valid turn
  - `test_valid_response_clears_placeholder_path()` (L354) — A non-empty reply must not have `response` overwritten by the
  - `test_still_empty_when_worker_marker_used()` (L368) — The worker's '(empty)' marker must still count as an empty reply.
  - `test_repeated_empty_still_gets_recovery_prompt(single_shot)` (L378) — Truly empty replies must keep the recovery behavior unchanged (only
  - `test_idle_empty_falls_back_to_placeholder()` (L390) — When no session is active, an exhausted empty reply falls back to
  - `test_live_retries_malformed_fallback_without_stopping(single_shot)` (L402)
  - `test_non_progress_and_unrequested_image_continuations_are_rejected()` (L424)
  - `test_pseudo_tool_requests_and_unverified_external_claims_are_rejected()` (L435)
  - `test_narrated_tool_calls_and_unreturned_evidence_are_rejected()` (L448)
  - `test_bare_tool_name_response_is_stripped_and_rejected()` (L457) — A local model emitting a BARE tool name as its whole turn (or a
  - `test_empty_bracket_and_narrated_read_intent_are_rejected()` (L479) — Local models emit a tool call with empty/no args as `web_read[]` /
  - `test_promised_external_completion_without_tool_result_is_rejected()` (L516)
  - `test_bare_tool_name_in_leak_positions_is_stripped()` (L522) — A bare tool name in an unambiguous leak position — colon/comma
  - `test_bare_tool_name_with_url_is_parsed_as_a_call()` (L560) — A compact model that emits a BARE tool name followed by the URL/query
  - `test_failed_full_model_retry_returns_safe_transcript_response()` (L586)
  - `test_repeated_tool_intent_across_personas_is_rejected()` (L594)
  - `test_text_tool_calls_execute_with_single_dialogue_iteration()` (L604)
  - `test_registration_research_never_grants_account_approval()` (L629)
  - `test_gemma_model_size_and_prompt_tier()` (L639)
  - `test_persona_prompts_have_distinct_parameter_tiers()` (L654)
  - `test_persona_names_default_when_custom_settings_are_blank()` (L664)
  - `test_persona_names_use_nonblank_custom_settings()` (L672)
  - `test_dialogue_capability_gate_rejects_tiny_and_base_models()` (L680)
  - `test_model_contracts_scale_output_without_inviting_topic_drift()` (L695)
  - `test_gemma_request_does_not_use_system_role_or_tools()` (L706)
  - `test_gemma4_is_not_forced_onto_legacy_template()` (L729)
  - `test_protocol_uses_live_template_capabilities()` (L737)
  - `test_dialogue_worker_uses_bounded_turn_budget()` (L760)
  - `test_dialogue_worker_keeps_normal_budget_for_larger_models()` (L773)
  - `test_local_client_timeout_is_bounded()` (L787)
  - `test_dialogue_token_override_reaches_provider_request()` (L801)
  - `test_dialogue_disables_reasoning_only_for_dialogue_request()` (L819)
  - `test_channel_reasoning_is_removed_from_visible_answer()` (L847)
  - `test_qwen_closed_thought_channel_preserves_following_answer()` (L854)
  - `test_lfm_think_block_is_not_visible()` (L863)
  - `test_reasoning_only_message_returns_empty_visible_content()` (L871)
  - `test_empty_provider_response_becomes_model_diagnostic()` (L877)
  - `test_qwen_dialogue_disables_reasoning_budget_exhaustion()` (L886)
  - `test_glm_and_lfm_models_get_explicit_family_profiles()` (L900)
  - `test_stall_phrases_and_narrated_tool_calls_are_rejected()` (L910) — Stall phrases and narrated tool calls must be rejected by
  - `test_natural_dialogue_can_include_multiple_questions()` (L925)
  - `test_dialogue_context_has_a_bounded_prompt()` (L944)
  - `test_dialogue_context_requires_immediate_read_only_research()` (L958)
  - `test_dialogue_context_requires_self_check_and_recovery()` (L972)
  - `test_decorated_tool_only_lines_are_stripped()` (L987) — A line whose only words are tool names is never a real sentence, but
  - `test_tool_only_strip_does_not_mangle_real_prose()` (L1013) — The tool-only-line rule must not eat legitimate sentences. Two
  - `test_first_person_tool_grounded_confirmation_is_not_rejected()` (L1038) — A persona that verified with a tool and reports its finding is doing
  - `test_reasoning_mode_router_matches_task_shape()` (L1071)


### `tests/dialogue/test_dialogue_speaker_selectors.py` — Phase 3: Dialogue speaker/reply selectors reflect every enabled device. (66L)

**Classes:**
- `class _Stub` (L14)
- `class TestSpeakerSelectors` (L18)
  - `_tab()` (L19)
  - `test_speaker_combo_has_human_plus_every_brain()` (L25)
  - `test_reply_combo_has_every_brain()` (L30)
  - `test_combo_items_carry_device_labels()` (L34)
  - `test_combo_name_resolution_exact()` (L42)
  - `test_header_lists_all_speakers()` (L49)
  - `test_next_speaker_round_robin()` (L55)


### `tests/dialogue/test_dialogue_team_brief.py` — Phase 5: team brief + shared-skills persona resolution + generalized LIFECYCLE. (166L)

**Functions:**
- `_speakers()` (L19)

**Classes:**
- `class _FakeBrain` (L14)
  - `__init__(name)` (L15)
- `class TestTeamBrief` (L35)
  - `test_empty_for_single_brain()` (L36)
  - `test_brief_lists_peers_not_self()` (L42)
  - `test_brief_reduces_to_two_brains()` (L60)
- `class TestSharedSkillsPersona` (L69)
  - `test_big_tier_uses_driver_skillset_with_own_name()` (L70)
  - `test_small_tier_uses_navigator_skillset_with_own_name()` (L82)
  - `test_name_override_empty_keeps_current_name()` (L91)
  - `test_team_brief_injected_into_full_prompt()` (L97)
  - `test_dialogue_resolves_extra_big_brain_to_driver_skillset()` (L107)
- `class TestGeneralizedLifecycle` (L119)
  - `_tab()` (L120)
  - `test_two_brains_alternate_big_small()` (L130)
  - `test_legacy_fallback_without_roster()` (L141)
  - `test_multi_big_brains_rotate_within_tier()` (L151)


### `tests/dialogue/test_dialogue_thinking_budget.py` — Adjustable dialogue thinking-budget + reasoning detection (v2.1.51, ARCH-ENG-051). (158L)

**Classes:**
- `class SmallBrainFake` (L15)
  - `__init__(model, context_length=32768)` (L16)
- `class BigBrainFake` (L21)
  - `__init__(model, context_length=32768)` (L22)
- `class _EnvPatch` (L34) — Context manager: clear the dialogue token keys, apply overrides, restore.
  - `__init__(**overrides)` (L37)
- `class TestReasoningDetection` (L54) — model_emits_reasoning must recognize reasoning models generically.
  - `test_bonsai_is_reasoning()` (L57)
  - `test_common_reasoning_families()` (L62)
  - `test_plain_model_is_not_reasoning()` (L68)
  - `test_runtime_latch_learns_unknown_reasoning_model()` (L74)
- `class TestDialogueThinkingHeadroom` (L84) — The adjustable per-class thinking reserve.
  - `_headroom(is_small, env)` (L87)
  - `test_default_is_2048()` (L92)
  - `test_per_class_override()` (L96)
  - `test_global_override_wins()` (L102)
  - `test_invalid_falls_back_to_default()` (L107)
- `class TestResolveMaxTokensThinking` (L112) — _resolve_max_tokens must give reasoning models the adjustable headroom.
  - `_resolve(brain, env)` (L115)
  - `test_reasoning_small_brain_gets_headroom()` (L120)
  - `test_non_reasoning_small_brain_not_inflated()` (L129)
  - `test_reasoning_small_brain_default_headroom()` (L139)
  - `test_big_reasoning_brain_gets_headroom()` (L148)


### `tests/dialogue/test_dialogue_turn1_parity.py` — Turn-1 context parity: the first-turn assembler must match the main path. (66L)

**Functions:**
- `_turn1_tab(limit: int) -> DialogueTab` (L42)
- `test_turn1_context_includes_work_tracker()` (L51) — Turn 1 must carry the same goal-continuity tracker as every other turn.
- `test_turn1_approval_guard_survives_minimum_limit()` (L57) — The approval guard must survive at the minimum context limit (4000).

**Classes:**
- `class _StubBrain` (L36)


### `tests/dialogue/test_dialogue_vram_tier.py` — Regression tests for VRAM-gated prompt tiering. (137L)

**Functions:**
- `_tab() -> DialogueTab` (L26)
- `test_unknown_vram_falls_back_to_model_size_tier()` (L30) — No readable VRAM must not demote or promote — use the model-size tier.
- `test_small_card_caps_full_model_at_compact()` (L40) — A >= 9B model on a < 10 GB card gets small-model (compact) prompting.
- `test_small_card_does_not_demote_below_model_tier()` (L49) — The VRAM cap must not push a tiny model further down.
- `test_large_card_allows_full_tier()` (L57) — >= 10 GB lets the model-size tier stand (enhanced prompting allowed).
- `test_threshold_boundary_is_ten_gb()` (L66) — 9.9 GB caps; 10.0 GB does not.
- `_contract_tier(tab: DialogueTab, model: str, small: bool) -> str` (L76) — Extract the tier the output contract actually reports.
- `test_all_tier_sites_agree_for_every_small_model_pair()` (L85) — The system prompt, the contract, and the context must report one tier.
- `test_full_model_on_small_card_reports_compact_everywhere()` (L109) — The specific regression: 14B on a 6GB card must be compact at all sites.
- `test_log_record_reports_the_same_tier_as_the_prompt_path()` (L119) — The per-turn log's 'tier' field must match _tier_for_brain (VRAM-capped).

**Classes:**
- `class _StubBrain` (L20)


### `tests/dialogue/test_discussion.py` — (no module docstring) (42L)

**Functions:**
- `test_discussion_requires_new_evidence_for_challenge()` (L9)
- `test_discussion_resolves_only_with_explicit_conclusion()` (L22)
- `test_discussion_exhausts_budget_without_fabricating_consensus()` (L35)


### `tests/dialogue/test_epistemic_calibration.py` — tests/test_epistemic_calibration.py — deterministic confidence classification. (115L)

**Functions:**
- `_claim(text='client accepted the, subject_id='opp_1')` (L16)

**Classes:**
- `class TestEpistemicCalibration` (L21)
  - `setUp()` (L23)
  - `_entry(source_kind=SourceKind.LLM)` (L26)
  - `test_none_is_unknown()` (L31)
  - `test_proposed_is_speculative()` (L35)
  - `test_supported_is_plausible_and_capped()` (L40)
  - `test_verified_l3_is_corroborated()` (L50)
  - `test_verified_l5_is_confirmed()` (L58)
  - `test_refuted_and_overridden_have_zero_confidence()` (L66)
  - `test_disclaimers_are_honest_and_distinct()` (L80)
  - `test_context_note_excludes_closed_claims_and_is_bounded()` (L91)
  - `test_context_note_empty_when_nothing_standing()` (L102)
  - `test_context_note_respects_max_claims()` (L107)


### `tests/dialogue/test_fact_ledger.py` — tests/test_fact_ledger.py — invariants of the append-only claim register. (191L)

**Functions:**
- `_claim(text='Upwork paid the inv, **kw)` (L22)

**Classes:**
- `class TestFactLedgerInvariants` (L29)
  - `setUp()` (L31)
  - `test_llm_claim_starts_proposed_never_verified()` (L36)
  - `test_no_api_lets_a_caller_hand_in_a_status()` (L43)
  - `test_llm_claim_is_not_verified_by_repeating_it()` (L51)
  - `test_evidence_at_required_level_verifies()` (L59)
  - `test_evidence_below_required_level_only_supports()` (L71)
  - `test_operator_attestation_alone_cannot_satisfy_L3()` (L80)
  - `test_verification_without_an_evidence_ref_is_refused()` (L92)
  - `test_history_is_append_only_and_monotonic()` (L102)
  - `test_entries_are_immutable()` (L117)
  - `test_refuted_claim_cannot_become_verified()` (L125)
  - `test_superseded_claim_is_closed()` (L132)
  - `test_supersede_requires_a_known_claim()` (L141)
  - `test_double_verification_is_refused()` (L146)
  - `test_operator_outranks_model_deterministically()` (L161)
  - `test_blank_assertion_is_refused()` (L172)
  - `test_non_claim_input_is_refused()` (L176)
  - `test_to_dict_is_serialisable()` (L180)


### `tests/dialogue/test_group3_honesty.py` — Group 3 regression tests: stop false learning signals from unverified / advertised (151L)

**Functions:**
- `_tmp_db()` (L22)
- `_opp_ramp(platform='RampPlat')` (L39)

**Classes:**
- `class _Opp` (L27) — Minimal opportunity stub for the pipeline's simple-execute path.
  - `__init__(platform='FaucetX', source='faucet', min_amount=5.0, status, ...)` (L29)
- `class H5SimpleExecuteNoFabricatedSuccess` (L47) — H-5: _execute_simple must not record success/revenue for a mere discovery.
  - `setUp()` (L50)
  - `tearDown()` (L61)
  - `test_no_success_revenue_recorded()` (L64)
- `class H4PaidWithoutEvidenceNoReputation` (L76) — H-4: mark_final_outcome('paid') without verified evidence must not update
  - `setUp()` (L80)
  - `tearDown()` (L89)
  - `test_paid_without_evidence_does_not_update_reputation()` (L92)
- `class H3RampAcceptRequiresVerifiedPayment` (L110) — H-3: the submission ramp must only credit an accept (win) when a verified
  - `setUp()` (L114)
  - `tearDown()` (L127)
  - `test_unverified_paid_records_no_ramp_win()` (L130)
  - `test_verified_paid_records_ramp_win()` (L139)


### `tests/dialogue/test_group4_medium.py` — Group 4 regression tests: medium-severity correctness fixes (M-1 .. M-7). (273L)

**Functions:**
- `_tmp_db_dir()` (L31)

**Classes:**
- `class M1LifecyclePersistsAcrossRestart` (L36)
  - `setUp()` (L37)
  - `tearDown()` (L41)
  - `test_state_survives_restart()` (L44)
- `class M2DedupStateAware` (L84)
  - `_make_loop(history)` (L85)
  - `_facts(oid)` (L96)
  - `_opp(oid)` (L101)
  - `test_failed_opp_reenters()` (L106)
  - `test_paid_opp_blocked()` (L114)
  - `test_no_history_not_blocked()` (L122)
- `class M3ContentDiscoveryStableIds` (L130)
  - `test_ids_are_platform_keyed_not_positional()` (L131)
- `class M4ManualReferenceNeverVerifies` (L143)
  - `setUp()` (L144)
  - `tearDown()` (L148)
  - `test_manual_reference_does_not_flip_paid()` (L151)
- `class M5LLMDoesNotUnilaterallyReject` (L169)
  - `setUp()` (L170)
  - `tearDown()` (L174)
  - `test_high_scam_prob_sets_risk_not_rejected()` (L177)
- `class M6EvalFailureNotEvaluated` (L201)
  - `setUp()` (L202)
  - `tearDown()` (L206)
  - `test_eval_exception_marks_eval_error_and_skips()` (L209)
- `class M7RevenueReportSingleSource` (L225)
  - `setUp()` (L226)
  - `tearDown()` (L230)
  - `_make_evidence(verified)` (L233)
  - `test_verified_payment_counts_as_verified_revenue()` (L243)
  - `test_unverified_payment_not_counted_as_verified()` (L251)
  - `test_report_delegates_to_accounting()` (L259)


### `tests/dialogue/test_honesty_stack.py` — Integration tests for the v2.1.1 honesty / epistemic stack. (488L)

**Classes:**
- `class TestMonetaryEvidencePureFunctions` (L41) — Pure-string checks must be deterministic and not depend on model judgment.
  - `test_extracts_simple_dollars()` (L44)
  - `test_extracts_scientific_notation_too()` (L49)
  - `test_deduplicates_identical_values()` (L54)
  - `test_spans_preserve_raw_text()` (L58)
  - `test_unsupported_detects_fabricated_values()` (L62)
  - `test_supported_values_are_not_flagged()` (L68)
  - `test_has_unsupported_is_short_cut()` (L73)
  - `test_derivable_arithmetic_is_still_reported()` (L78)
  - `test_empty_and_non_money_text()` (L85)
- `class TestClaimExtractionHeuristics` (L91) — Best-effort claim extraction must be conservative and deterministic.
  - `test_explicit_markers_capture_claims()` (L94)
  - `test_heuristic_claim_verbs_capture_from_verb_onward()` (L110)
  - `test_short_lines_are_not_claims()` (L117)
  - `test_short_predicates_after_verb_are_not_claims()` (L122)
  - `test_longer_predicates_after_verb_are_claims()` (L128)
  - `test_consecutive_identical_short_lines_produce_one_claim_each()` (L137)
- `class TestFactLedgerBasics` (L150) — The ledger must be append-only and transition-guarded.
  - `test_proposed_only_recordable_via_record_claim()` (L153)
  - `test_record_claim_rejects_non_claim()` (L161)
  - `test_record_claim_rejects_empty_assertion()` (L166)
  - `test_illegal_transition_raises()` (L172)
  - `test_verification_requires_evidence_meeting_level()` (L180)
  - `test_ledger_is_append_only_in_practice()` (L193)
- `class TestOperatorOverrideRegistry` (L203) — Human overrides are append-only and scoped.
  - `test_issue_and_revoke()` (L206)
  - `test_amend_keeps_history()` (L214)
  - `test_cannot_amend_or_revoke_revoked()` (L222)
  - `test_global_override_has_empty_subject()` (L231)
- `class TestEpistemicCalibrationPureFunctions` (L237) — Confidence classification is deterministic policy.
  - `test_none_is_unknown_and_low_confidence()` (L240)
  - `test_proposed_is_speculative_low_confidence()` (L247)
  - `test_supported_is_plausible_capped()` (L256)
  - `test_verified_at_or_above_l5_is_confirmed()` (L265)
  - `test_verified_below_l5_is_corroborated()` (L276)
  - `test_refuted_and_superseded_are_negative()` (L287)
- `class TestContextNoteFormatting` (L300) — The prompt-injected epistemic note must be bounded and honest.
  - `test_empty_when_nothing_standing()` (L303)
  - `test_bounded_to_max_claims()` (L316)
  - `test_includes_confidence_and_level()` (L327)
- `class TestDialogueHonestyServiceComposition` (L339) — The service must compose ledger + overrides + epistemic note correctly.
  - `test_record_claims_makes_proposed_entries()` (L342)
  - `test_global_override_supersedes_proposed_model_claims()` (L354)
  - `test_superseded_claim_drops_out_of_standing_and_note()` (L366)
  - `test_note_is_bounded_and_readable()` (L379)
  - `test_standing_claims_excludes_refuted_and_superseded()` (L387)
  - `test_to_dict_is_observability_counts()` (L394)
- `class TestHonestyStackIntegrationWithDialogueShapedText` (L404) — End-to-end composition against realistic dialogue responder text.
  - `test_records_model_claims_and_flags_unsupported_money()` (L407)
  - `test_operator_can_supersede_a_model_claim_before_prompt_build()` (L426)
  - `test_epochidemic_note_does_not_blow_prompt_budget()` (L443)
  - `test_unsupported_money_is_detected_in_presence_of_supported_money()` (L450)
- `class TestHonestyStackDoesNotChangeExistingDialogueInvariants` (L463) — Sanity check that composing the stack does not mutate public API we test
  - `test_dialogue_honesty_service_has_no_required_positional_io()` (L468)
  - `test_new_stack_is_importable_from_agents_package()` (L477)


### `tests/dialogue/test_layered_memory.py` — (no module docstring) (36L)

**Functions:**
- `test_retrieval_classifies_layers_and_filters_expired_entries(tmp_path)` (L7)
- `test_retrieval_respects_confidence_and_unknown_categories(tmp_path)` (L21)
- `test_retrieval_can_reject_non_expiring_stale_memory(tmp_path)` (L32)


### `tests/dialogue/test_layered_memory_provenance.py` — (no module docstring) (45L)

**Functions:**
- `test_retrieval_preserves_provenance_and_excludes_quarantine()` (L37)

**Classes:**
- `class _Database` (L6)
  - `get_memories(limit=20)` (L7)


### `tests/dialogue/test_live_transport_budget.py` — Live-mode transport-failure circuit breaker. (127L)

**Functions:**
- `_app()` (L39)
- `_make_tab()` (L46) — A DialogueTab with the recovery handler exercised without live servers.

**Classes:**
- `class TestLiveTransportFailureBudget` (L62)
  - `test_budget_is_finite_and_generous()` (L63) — The cap must exist and leave room for real recovery.
  - `test_live_survives_failures_within_budget()` (L69) — A recovery session must not end on the first few failures.
  - `test_live_pauses_once_budget_is_spent()` (L79) — Past the budget Live stops itself instead of looping forever.
  - `test_failure_does_not_reschedule_after_pause()` (L94) — The caller's `if retry:` gate must see False, so nothing re-arms.
  - `test_successful_turn_resets_the_counter()` (L101) — A flapping provider that eventually answers keeps the session alive.
  - `test_non_live_failure_still_retries()` (L115) — Goal-driven (non-Live) mode keeps its original single-retry contract.


### `tests/dialogue/test_memory_promotion.py` — (no module docstring) (41L)

**Functions:**
- `_verified_outcome(outcome_id)` (L6)
- `test_unverified_or_unlinked_lessons_are_not_promoted()` (L10)
- `test_verified_outcome_lesson_is_persisted_with_provenance(tmp_path)` (L19)
- `test_unverified_outcome_cannot_update_memory(tmp_path)` (L33)


### `tests/dialogue/test_operator_override.py` — tests/test_operator_override.py — human authority over model claims. (155L)

**Functions:**
- `_claim(text, subject_id='', source='llm:edward')` (L18)

**Classes:**
- `class TestOperatorOverride` (L23)
  - `setUp()` (L25)
  - `test_issue_creates_active_operator_authority()` (L31)
  - `test_blank_statement_is_refused()` (L40)
  - `test_revoke_is_append_only_and_deactivates()` (L46)
  - `test_revoking_twice_is_refused()` (L55)
  - `test_amend_keeps_history()` (L61)
  - `test_records_are_immutable_and_serialisable()` (L69)
  - `test_subject_specific_override_beats_global()` (L78)
  - `test_no_override_resolves_to_none()` (L87)
  - `test_override_supersedes_conflicting_model_claim()` (L93)
  - `test_override_does_not_erase_tool_evidence()` (L102)
  - `test_override_never_creates_verified_evidence()` (L111)
  - `test_override_does_not_silently_erase_evidence_verified_claim()` (L120)
  - `test_override_leaves_other_subjects_alone()` (L135)
  - `test_revoked_override_stops_applying()` (L144)


### `tests/dialogue/test_persona_contracts.py` — (no module docstring) (42L)

**Functions:**
- `test_driver_contract_prioritizes_progress_without_authority()` (L4)
- `test_navigator_contract_prioritizes_verification_without_authority()` (L13)
- `test_prompt_contains_role_contract()` (L22)
- `test_prompt_teams_conversational_awareness_not_a_script()` (L28) — Both tiers must instruct the agent to react to the human and teammates


### `tests/dialogue/test_prompt_budget.py` — Prompt tier and shared assembly budget checks. (90L)

**Classes:**
- `class _Personality` (L12)
  - `get_system_prompt_addon(role)` (L13)
- `class _Knowledge` (L17)
  - `build_context(role, query)` (L18)
- `class TestPromptBudget` (L22)
  - `setUp()` (L23)
  - `_prompt(tier)` (L36)
  - `test_tiers_are_ordered_and_bounded()` (L40)
  - `test_invalid_tier_falls_back_to_compact()` (L51)
  - `test_shared_assembly_has_stable_order_and_limit()` (L54)
  - `test_adaptive_prompt_modes_are_bounded()` (L63)
  - `test_adaptive_prompt_invalid_mode_uses_standard()` (L71)
  - `test_prompt_telemetry_records_mode_and_technique()` (L76)
  - `test_external_prompts_are_bounded()` (L84)


### `tests/dialogue/test_reasoning_patterns.py` — (no module docstring) (33L)

**Functions:**
- `test_pattern_selection_scales_with_task_shape()` (L8)
- `test_brain_graph_records_decision_action_and_dispatcher_result()` (L21)


### `tests/dialogue/test_thought_graph.py` — (no module docstring) (126L)

**Functions:**
- `_verified_evidence(evidence_id='ev-1')` (L14)
- `test_graph_requires_real_affirmative_evidence_for_support()` (L25)
- `test_graph_propagates_support_but_contradiction_wins()` (L38)
- `test_graph_dependency_blocks_until_dependency_is_supported()` (L53)
- `test_graph_rejects_dependency_cycles_and_serializes_on_record()` (L67)
- `test_graph_wide_measurement_is_available_for_diagnostics()` (L81)
- `test_show_thoughts_renders_the_finish_dict_graph()` (L88) — The Dialogue 'Thoughts' button must render the dict that


### `tests/dialogue/test_tier_agreement.py` — Cross-site tier-agreement regression tests. (88L)

**Functions:**
- `_tab()` (L31)
- `_point_turn_at(tab, small, model)` (L35) — Point the active turn at (small, model) with unknown (deterministic) VRAM.
- `_contract_tier(tab, small, model, tier=None)` (L42)
- `_context_tier(tab)` (L48)
- `test_all_three_sites_agree_for_every_pair()` (L53)
- `test_sites_do_not_reprobe_vram_mid_turn()` (L74) — A flapping _tier_for_brain (simulated VRAM race) must not split a turn.

**Classes:**
- `class _StubBrain` (L25)

