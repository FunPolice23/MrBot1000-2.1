# Script analysis index

One entry per production script, top of the tree downward. Status is
`pending` until that script has been read in full and its findings
recorded in the area document named beside it.

**Scope:** 287 production Python files (90,830 lines) + 8 PowerShell/batch
launchers. Tests are excluded -- they are covered by asking what they
assert, not by analysing them as program code.

**Findings are recorded, not fixed, until the sweep completes.** That keeps
the analysis separate from repair, so a fix can be batched across
files once the whole picture is visible.

The sweep is complete. The per-file depth sweep's medium tier closed at
ARCH-ENG-249 and its low tier at ARCH-ENG-279. The reconciliation's high tier
closed at ARCH-ENG-287; its medium batches (ARCH-ENG-288..306) are recorded
below, and follow-up maintenance ids (ARCH-ENG-307..) are recorded in
`CHANGELOG.md` as they land. Every fix is recorded in `CHANGELOG.md`
against its finding id, and
each closed finding carries a banner at the top of its area document. The
per-script status below names the ids that touched each file.


## 00-root  --  3 files, 4,442 lines

| Script | Lines | Status |
|---|---:|---|
| `__init__.py` | 19 | **done** (R-01) |
| `main.py` | 3,735 | **done** (11a U-01 fixed 284 — quarantine review moved to Safety tab, dead review methods removed; G-05 live-order approval handler 283; Z-01 evidence reconciliation handler 287; U-03/U-04 removed 250/251; AF-03 wired 272; AB-01 surface retired 275) |
| `run_lead_routine.py` | 688 | **done** (11q, document-shaped, R-02 confirmed; AI-01 fixed 264) |
| **subtotal** | **4,442** | |

## 10-agents-autonomy  --  7 files, 1,539 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/autonomy/__init__.py` | 54 | **done** |
| `agents/autonomy/agent_registry.py` | 394 | **done** |
| `agents/autonomy/cli.py` | 325 | **done** (A-04; G-01 fixed 300 - runs `EarningPipeline`) |
| `agents/autonomy/grants.py` | 42 | **done** (verified sound) |
| `agents/autonomy/heartbeat.py` | 207 | **done** |
| `agents/autonomy/onchain_identity.py` | 229 | **done** |
| `agents/autonomy/self_improvement.py` | 288 | **done** (A-01 fixed 280 — read side wired into `filter()`, strategy weights seeded; A-02/A-03 recorded) |
| **subtotal** | **1,539** | |

## 10-agents-brains  --  14 files, 3,494 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/brains/__init__.py` | 1 | **done** (clean) |
| `agents/brains/base_worker.py` | 345 | **done** (B-01/B-02 fixed 288 — trust-boundary modules added to `PROTECTED_SOURCE_FILES`) |
| `agents/brains/big_brain.py` | 707 | **done** (11o, 0 dead of 17, verified sound; 317 dialogue turns record `direct_dialogue`) |
| `agents/brains/brain_got.py` | 383 | **done** |
| `agents/brains/shared_context.py` | 354 | **done** |
| `agents/brains/small_brain.py` | 605 | **done** (B-04; 317 dialogue turns record `direct_dialogue`) |
| `agents/brains/worker_budget.py` | 48 | **done** |
| `agents/brains/worker_llm_mixin.py` | 241 | **done** |
| `agents/brains/worker_provider.py` | 20 | **done** |
| `agents/brains/worker_provider_calls.py` | 143 | **done** |
| `agents/brains/worker_provider_mixin.py` | 353 | **done** |
| `agents/brains/worker_safety.py` | 170 | **done** (B-03) |
| `agents/brains/worker_thinking.py` | 78 | **done** |
| `agents/brains/worker_workspace.py` | 46 | **done** |
| **subtotal** | **3,494** | |

## 10-agents-cognition  --  11 files, 2,679 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/cognition/__init__.py` | 78 | **done** (C-02) |
| `agents/cognition/coordinator.py` | 326 | **done** (C-03; first live bus publisher + per-run cancellation token and stage-boundary stop at 247) |
| `agents/cognition/dialogue.py` | 147 | **done** |
| `agents/cognition/dialogue_honesty.py` | 266 | **done** (verified live) |
| `agents/cognition/epistemic.py` | 114 | **done** (C-03) |
| `agents/cognition/fact_ledger.py` | 370 | **done** (verified live) |
| `agents/cognition/graph.py` | 310 | **done** (BG-01/BG-02/BG-04 fixed 233 — record cluster deleted) |
| `agents/cognition/operator_override.py` | 199 | **done** (C-03) |
| `agents/cognition/personas.py` | 346 | **done** (C-03) |
| `agents/cognition/reasoning_modes.py` | 238 | **done** |
| `agents/cognition/speaker_registry.py` | 267 | **done** |
| | | *removed by ARCH-ENG-233: `ledger.py` (65), `contradictions.py` (64), `memory_promotion.py` (54), `state.py` (22) — no production consumer* |
| **subtotal** | **2,679** | |

## 10-agents-core  --  14 files, 3,109 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/core/__init__.py` | 1 | **done** (clean) |
| `agents/core/account_profile.py` | 86 | **deleted** (D-02 fixed 302 - no production caller) |
| `agents/core/alerting.py` | 494 | **done** (D-04) |
| `tests/support/architecture_boundaries.py` | 81 | **moved** (D-02 fixed 302 - test-only authority) |
| `agents/core/comms.py` | 623 | **done** (D-04; AN-02 wired at 247 - bus cancellation honoured at delivery, coordinator publishes, Collaboration Stop consumes it) |
| `agents/core/comms_log.py` | 168 | **done** (D-04) |
| `agents/core/composition_root.py` | 180 | **done** |
| `agents/core/configuration.py` | 101 | **done** |
| `agents/core/event_logger.py` | 567 | **done** (D-04 fixed 230, BD-01/BD-02 fixed 243 — emitters live, heartbeat legacy removed) |
| `agents/core/feature_flags.py` | 87 | **done** (D-01 fixed 281 — crypto operations now gated at `RealCryptoOperator`; D-03 fixed 283) |
| `agents/core/notifications.py` | 213 | **done** (D-04) |
| `agents/core/persistence_contract.py` | 279 | **done** |
| `agents/core/recovery.py` | 41 | **deleted** (D-02 fixed 302 - no production caller) |
| `agents/core/state_reconciliation.py` | 188 | **done** |
| **subtotal** | **3,109** | |

## 10-agents-dialogue  --  6 files, 1,948 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/dialogue/__init__.py` | 1 | **done** (clean) |
| `agents/dialogue/chat_completion.py` | 722 | **done** (11n, 0 dead of 5, verified sound; AG-01 split 277) |
| `agents/dialogue/chat_router.py` | 257 | **deleted** (E-01/E-02 fixed 303 - superseded by chat_completion) |
| `agents/dialogue/convergence_plan.py` | 506 | **done** |
| `agents/dialogue/discussion.py` | 102 | **done** (E-01) |
| `agents/dialogue/opportunity_analysis.py` | 360 | **done** (verified sound) |
| **subtotal** | **1,948** | |

## 10-agents-discovery  --  8 files, 1,590 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/discovery/__init__.py` | 1 | **done** (clean) |
| `agents/discovery/discovery_engine.py` | 112 | **done** (live via port) |
| `agents/discovery/discovery_port.py` | 58 | **done** (F-05) |
| `agents/discovery/discovery_scheduler.py` | 388 | **done** (F-01 fixed 282 - `tick()` returns `found`, cycle consumes it; F-02 resolved by the same tick wiring) |
| `agents/discovery/discovery_sources.py` | 473 | **done** (F-04; W-02 fixed 286 — live `is_enabled()` gates on social/airdrop/DeFi sources) |
| `agents/discovery/discovery_strategies.py` | 203 | **done** (F-02) |
| `agents/discovery/scrape_resilience.py` | 179 | **done** (verified sound) |
| `agents/discovery/web_discovery.py` | 176 | **done** (live, opt-in) |
| **subtotal** | **1,590** | |

## 10-agents-earning  --  54 files, 13,719 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/earning/__init__.py` | 79 | **done** (10g, clean facade) |
| `agents/earning/accounting.py` | 36 | **done** (10g-pt1, live) |
| `agents/earning/airdrop_claimer.py` | 236 | **done** (10h, G-06) |
| `agents/earning/airdrop_scanner.py` | 436 | **done** (10h, verified sound) |
| `agents/earning/backtesting.py` | 377 | **done** (10h) |
| `agents/earning/capabilities.py` | 216 | **done** (10g-pt1, live) |
| `agents/earning/capability.py` | 302 | **deleted** (G-01 fixed 300 - dead executor, broken imports removed) |
| `agents/earning/chain_verifier.py` | 157 | **done** (10g-pt1, live) |
| `agents/earning/defi_scanner.py` | 148 | **done** (10h, live) |
| `agents/earning/discoverer.py` | 612 | **done** (10h, verified sound; AP-01 fixed 266) |
| `agents/earning/discovery.py` | 98 | **done** (10g-pt1, live) |
| `agents/earning/economic_accounting.py` | 535 | **done** (10h, verified sound) |
| `agents/earning/economic_policy.py` | 363 | **done** (10h, G-07) |
| `agents/earning/evaluation.py` | 189 | **done** (10g-pt1, live; AX-03 fixed 263) |
| `agents/earning/evidence.py` | 93 | **done** (10g-pt1, live) |
| `agents/earning/execution.py` | 44 | **done** (10g-pt1, live) |
| `agents/earning/executor.py` | 592 | **done** (10h, live) |
| `agents/earning/freelance_finder.py` | 330 | **done** (10h, live; AU-01 fixed 263) |
| `agents/earning/gas_estimator.py` | 61 | **done** (10h, G-06) |
| `agents/earning/goal_system.py` | 526 | **done** (10g-pt1, live; BF-01/BF-02 fixed 244 - GoalTracker wired, guarded credit, Management Goals card) |
| `agents/earning/got.py` | 209 | **done** (10g-pt1, live) |
| `agents/earning/intelligence.py` | 69 | **done** (10g-pt1, live) |
| `agents/earning/live_trading.py` | 615 | **done** (10h; G-05 fixed 283; AO-02 folded in; G-06 fixed 289; G-07 fixed 295 - explicit fraction/percent units) |
| `agents/earning/microtask_earner.py` | 220 | **done** (10h, live) |
| `agents/earning/moltbook_agent.py` | 400 | **done** (10h, live) |
| `agents/earning/opportunity_adapters.py` | 60 | **done** (10g-pt1, live) |
| `agents/earning/opportunity_intelligence.py` | 455 | **done** (10h, live) |
| `agents/earning/opportunity_lifecycle.py` | 1,067 | **done** (11f, 6 dead of 37; Z-01 fixed 287 — `reconcile_evidence` wired to Management tab; Z-03 removed 256) |
| `agents/earning/opportunity_models.py` | 298 | **done** (10g-pt1, live) |
| `agents/earning/opportunity_portfolio.py` | 854 | **done** (11i, 1 dead of 31, verified sound) |
| `agents/earning/paper_trading.py` | 389 | **done** (10h) |
| `agents/earning/payment.py` | 40 | **done** (10g-pt1, live) |
| `agents/earning/payment_evidence.py` | 41 | **done** (10g-pt1, live) |
| `agents/earning/payout_verifier.py` | 139 | **done** (10h, verified sound) |
| `agents/earning/platform_skill_urls.py` | 46 | **done** (10g-pt1, live) |
| `agents/earning/platform_submitter.py` | 319 | **done** (10h, live) |
| `agents/earning/platform_throttle.py` | 121 | **done** (10g-pt1, live) |
| `agents/earning/portfolio.py` | 85 | **done** (10g-pt1, live) |
| `agents/earning/proposal.py` | 181 | **done** (10g-pt1, live) |
| `agents/earning/ranking.py` | 82 | **done** (10g-pt1, live) |
| `agents/earning/real_crypto_operator.py` | 194 | **done** (10h, live; D-01 fixed 281 — crypto gate on propose/send) |
| `agents/earning/reputation.py` | 318 | **done** (10h, live) |
| `agents/earning/router.py` | 122 | **done** (10g-pt1, live; N-01 fixed 292 - duplicate `get_all_tools` removed) |
| `agents/earning/rug_screen.py` | 129 | **done** (10g-pt1, live) |
| `agents/earning/social_earning_platform.py` | 379 | **done** (10h, live) |
| `agents/earning/social_writer_factory.py` | 82 | **done** (10g-pt1, live) |
| `agents/earning/spec.py` | 194 | **done** (10g-pt1, live) |
| `agents/earning/strategy_feedback.py` | 154 | **done** (10h, live) |
| `agents/earning/submission.py` | 20 | **done** (10g-pt1, live) |
| `agents/earning/submission_ramp.py` | 193 | **done** (10h, live) |
| `agents/earning/tasks.py` | 145 | **done** (10g-pt1, live) |
| `agents/earning/validator.py` | 155 | **done** (10g-pt1, live) |
| `agents/earning/validators.py` | 440 | **done** (10g-pt1, live) |
| `agents/earning/win_rate_guard.py` | 74 | **done** (10h, live) |
| **subtotal** | **13,719** | |

## 10-agents-evidence  --  8 files, 1,620 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/evidence/__init__.py` | 1 | **done** (clean) |
| `agents/evidence/document_scanner.py` | 407 | **done** (H-01 fixed 299 - live second gate; H-02..H-04) |
| `agents/evidence/evidence.py` | 431 | **done** (verified sound) |
| `agents/evidence/evidence_factory.py` | 162 | **done** (verified sound) |
| `agents/evidence/evidence_policy.py` | 207 | **done** (11f, `reconcile` dead) |
| `agents/evidence/evidence_store.py` | 153 | **done** (verified sound) |
| `agents/evidence/numeric_evidence.py` | 90 | **done** (verified sound; 308 — zero exempted from the evidence check) |
| `agents/evidence/provenance.py` | 169 | **done** |
| **subtotal** | **1,620** | |

## 10-agents-integrations  --  12 files, 3,078 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/integrations/__init__.py` | 2 | **done** (clean) |
| `agents/integrations/browser.py` | 414 | **done** (I-01 fixed 290 — SSRF guard on `read_page`/`scrape`) |
| `agents/integrations/crypto.py` | 257 | **done** (I-04) |
| `agents/integrations/fiverr.py` | 238 | **done** |
| `agents/integrations/microtask.py` | 156 | **done** |
| `agents/integrations/scraper.py` | 290 | **done** |
| `agents/integrations/upwork.py` | 218 | **done** |
| `agents/integrations/wallet.py` | 205 | **done** |
| `agents/integrations/wallet_crypto.py` | 287 | **done** |
| `agents/integrations/wallet_manager.py` | 345 | **done** |
| `agents/integrations/web.py` | 192 | **done** |
| `agents/integrations/web_eyes.py` | 474 | **done** (I-01 fixed 290 — SSRF guard on `read_page`; I-05) |
| **subtotal** | **3,078** | |

## 10-agents-knowledge  --  14 files, 3,808 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/knowledge/__init__.py` | 1 | **done** (clean) |
| `agents/knowledge/help_catalog.py` | 575 | **done** (BC-01 fixed 241 — catalog tracks tab_specs) |
| `agents/knowledge/layered_memory.py` | 144 | **done** (J-01, DEAD) |
| `agents/knowledge/llama_setting_help.py` | 70 | **done** |
| `agents/knowledge/program_knowledge.py` | 442 | **done** (verified sound; J-01 fixed 297 - layered retrieval) |
| `agents/knowledge/prompt_assembly.py` | 25 | **done** |
| `agents/knowledge/prompt_sanitize.py` | 109 | **done** (J-04 fixed 296 - regression tests; J-06, J-07) |
| `agents/knowledge/prompt_utils.py` | 171 | **done** |
| `agents/knowledge/prompting_engine.py` | 484 | **done** |
| `agents/knowledge/proposal_reviewer.py` | 207 | **done** (J-05 fixed 296 - gate tests; O-02 fixed 294 - live analyst) |
| `agents/knowledge/proposal_templates.py` | 128 | **done** |
| `agents/knowledge/proposal_writer.py` | 120 | **done** |
| `agents/knowledge/skill_index.py` | 335 | **done** (AT-01 fixed 240 — dropped skills now named) |
| `agents/knowledge/workshop.py` | 997 | **done** (J-02, J-03, K-01; AY-02 fixed 245 - dead template subsystem deleted; AY-01 fixed 248 - full typed tool surface wired) |
| **subtotal** | **3,808** | |

## 10-agents-platforms  --  3 files, 468 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/platforms/__init__.py` | 41 | **done** (K-02) |
| `agents/platforms/credential_vault.py` | 154 | **done** (verified sound) |
| `agents/platforms/registration.py` | 273 | **done** (verified sound) |
| **subtotal** | **468** | |

## 10-agents-providers  --  13 files, 3,647 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/providers/__init__.py` | 29 | **done** (clean) |
| `agents/providers/anthropic_adapter.py` | 55 | **done** (L-02, live) |
| `agents/providers/context_table.py` | 62 | **done** (L-02, verified sound) |
| `agents/providers/gguf_meta.py` | 473 | **done** (verified sound) |
| `agents/providers/huggingface_models.py` | 557 | **done** |
| `agents/providers/model_capabilities.py` | 90 | **done** |
| `agents/providers/model_profile.py` | 558 | **done** (BE-01 fixed 239 — canonical think matcher shared; BE-02 removed 262) |
| `agents/providers/model_recommendations.py` | 153 | **done** (L-01, DEAD) |
| `agents/providers/ollama_adapter.py` | 131 | **done** |
| `agents/providers/openai_compatible.py` | 374 | **done** (verified sound) |
| `agents/providers/provider_hot_reload.py` | 189 | **done** |
| `agents/providers/provider_lifecycle.py` | 279 | **done** |
| `agents/providers/provider_manager.py` | 697 | **done** (11p, 4 dead of 28, verified sound) |
| **subtotal** | **3,647** | |

## 10-agents-runtime  --  13 files, 4,347 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/runtime/__init__.py` | 43 | **done** (clean) |
| `agents/runtime/agent.py` | 208 | **done** |
| `agents/runtime/brain_contention.py` | 356 | **done** (verified sound) |
| `agents/runtime/brain_roster.py` | 354 | **done** (verified sound) |
| `agents/runtime/context.py` | 226 | **done** |
| `agents/runtime/device_registry.py` | 848 | **done** (11j, 2 dead of 29, verified sound) |
| `agents/runtime/dual_brain.py` | 1,381 | **done** (11d, 2 dead of 39, verified sound; X-01 fixed 270; M-03 fixed 291 — fallback honours KV width; 307 — clamp note only when it lands, once, with the why; 311 — raise_exception fallback is opt-in, jinja keeps the model's tool-call rendering; 315 — keep-in-RAM checkboxes invert at parse, the flag finally fires) |
| `agents/runtime/hardware_plan.py` | 238 | **deleted** (M-01 fixed 301 - superseded by device_registry/brain_roster) |
| `agents/runtime/llm.py` | 138 | **done** |
| `agents/runtime/performance.py` | 131 | **done** |
| `agents/runtime/provider_keys.py` | 137 | **done** |
| `agents/runtime/services.py` | 226 | **done** |
| `agents/runtime/stats.py` | 61 | **done** (M-02, DEAD) |
| **subtotal** | **4,347** | |

## 10-agents-safety  --  22 files, 5,920 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/safety/__init__.py` | 86 | **done** (clean) |
| `agents/safety/approval.py` | 636 | **done** (verified sound; AM-02 fixed 265) |
| `agents/safety/authorization.py` | 154 | **done** |
| `agents/safety/calling.py` | 237 | **done** (N-01) |
| `agents/safety/circuit.py` | 112 | **done** |
| `agents/safety/cost.py` | 168 | **done** |
| `agents/safety/dispatch.py` | 133 | **done** (11g, verified sound) |
| `agents/safety/filesystem.py` | 355 | **done** (AF-02/AF-03 cache + snapshot wired 271/272) |
| `agents/safety/gate.py` | 168 | **done** |
| `agents/safety/gates.py` | 257 | **done** |
| `agents/safety/guard.py` | 782 | **done** (11k, 7 dead of 43, AE-02; AE-01/AE-03/AE-04 removed 257-259) |
| `agents/safety/handlers.py` | 992 | **done** (11g, 0 dead of 30, verified sound; AA-01 convention pinned 268) |
| `agents/safety/instructions.py` | 214 | **done** (verified sound) |
| `agents/safety/learning.py` | 21 | **done** (N-02, DEAD) |
| `agents/safety/legacy_tools.py` | 336 | **done** (N-01) |
| `agents/safety/policy.py` | 46 | **done** (N-04) |
| `agents/safety/provider_rate_limiter.py` | 207 | **done** |
| `agents/safety/response.py` | 289 | **done** |
| `agents/safety/sql.py` | 53 | **done** |
| `agents/safety/tools.py` | 301 | **done** (N-01 fixed 292 — sole public `get_all_tools` registry) |
| `agents/safety/trust.py` | 89 | **done** |
| `agents/safety/workspace.py` | 284 | **done** (H-01 fixed 299 - QualityController gate) |
| **subtotal** | **5,920** | |

## 10-agents-services  --  14 files, 4,612 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/services/__init__.py` | 1 | **done** (clean) |
| `agents/services/analyst_worker.py` | 338 | **done** (O-02 fixed 294 - wired into ProposalReviewer) |
| `agents/services/application_services.py` | 54 | **done** |
| `agents/services/autonomous_loop.py` | 1,309 | **done** (11e, 1 dead of 41, Y-01; Y-02 removed 255) |
| `agents/services/autonomous_run_store.py` | 263 | **done** |
| `agents/services/cli_interface.py` | 213 | **done** (O-04, DEAD) |
| `agents/services/code_patch_service.py` | 488 | **done** (verified sound; B-01/B-02 fixed 288 — protected-source and filename-blocklist checks) |
| `agents/services/coder.py` | 318 | **done** (O-01 fixed 304 - live via propose_code_patch; amended by 11g) |
| `agents/services/mrbot_cli.py` | 501 | **done** (O-03; AR-01 fixed 267; W-03 opportunities command 274) |
| `agents/services/patch_sandbox.py` | 220 | **done** |
| `agents/services/self_audit.py` | 691 | **done** (11r, AJ-01/AJ-02 fixed 236 — engine live + basis-honest) |
| `agents/services/self_improvement_commands.py` | 137 | **done** |
| `agents/services/task_executor.py` | 19 | **done** (compat shim) |
| `agents/services/workflow_planner.py` | 60 | **done** (W-04, transitively DEAD) |
| **subtotal** | **4,612** | |

## 40-gui  --  38 files, 21,772 lines

| Script | Lines | Status |
|---|---:|---|
| `gui/__init__.py` | 0 | **done** (clean) |
| `gui/builders/__init__.py` | 1 | **done** (clean) |
| `gui/builders/refresh_coordinator.py` | 78 | **done** (10r-pt1) |
| `gui/builders/tab_builders.py` | 53 | **done** (facade) |
| `gui/builders/tab_feature_builders.py` | 3,898 | **done** (10r/10s, R-01, R-03, AW-02 fixed 238, AW-01 fixed 242; AW-03 split 278; AB-01 retired 275; G-05 order form 283; D-01 crypto surface 281; Z-01 reconcile signal 287; U-01 quarantine gate 284; R-02 error collector 305; P-02 dashboard 306) |
| `gui/builders/tab_lifecycle.py` | 138 | **done** (10r-pt1) |
| `gui/builders/tab_workers.py` | 132 | **done** (10r-pt1; G-05 `LiveOrderProposalWorker` 283) |
| `gui/panels/__init__.py` | 1 | **done** (clean) |
| `gui/panels/approval_panel.py` | 285 | **done** (10r-pt1) |
| `gui/panels/dialogue_log.py` | 25 | **done** (Q-03) |
| `gui/panels/help_dialog.py` | 121 | **done** (10r-pt1) |
| `gui/panels/registration_panel.py` | 271 | **done** (10r-pt1) |
| `gui/tabs/__init__.py` | 1 | **done** (clean) |
| `gui/tabs/analytics_tab.py` | 299 | **done** (10r-pt1) |
| `gui/tabs/chat_tab.py` | 492 | **done** (10r-pt1) |
| `gui/tabs/collaboration_tab.py` | 183 | **done** (R-01, tab never shown; Stop control added at 247) |
| `gui/tabs/dialogue_tab.py` | 4,398 | **done** (10r/10s, Q-02, verified sound; AV-02 wired 273; AV-03 gate 279 — advisory, never refuses, 313; 316 — one tier for speaker and contract, VRAM read is MiB→GB correct) |
| `gui/tabs/earning_insights.py` | 503 | **done** (10r-pt1) |
| `gui/tabs/earning_tab.py` | 590 | **done** (10r-pt1, BB-01 fixed 237 — real recipient only) |
| `gui/tabs/management_tab.py` | 380 | **done** (10r-pt1; Z-01 Reconcile Evidence action/signal 287) |
| `gui/tabs/model_library_tab.py` | 506 | **done** (10r-pt1) |
| `gui/tabs/payments_tab.py` | 240 | **done** (10r-pt1) |
| `gui/tabs/safety_tools_tab.py` | 623 | **done** (10r-pt1; AZ-01 fixed 269; U-01 fixed 284 — quarantine review sub-tab) |
| `gui/theme_ui_state.py` | 109 | **done** (Q-01, live) |
| `gui/widgets/__init__.py` | 1 | **done** (clean) |
| `gui/widgets/brain_control_row.py` | 270 | **done** (10r-pt1) |
| `gui/widgets/brain_roster_panel.py` | 244 | **done** (10r-pt1) |
| `gui/widgets/brain_settings_row.py` | 237 | **done** (10r-pt1; L-01 fixed 298 - recommendation tooltip) |
| `gui/widgets/dual_brain_control.py` | 3,804 | **done** (10r/10s, R-04, verified sound; 309 — N-Brain roster panel removed, Provider Control is the single model-selection surface; 314 — un-setting an advanced flag removes its stale `.env` line, sentinel spinboxes carry per-control unset metadata) |
| `gui/widgets/performance.py` | 121 | **done** (10r-pt1) |
| `gui/widgets/persona_naming.py` | 59 | **done** (10r-pt1) |
| `gui/widgets/provider_config_widget.py` | 972 | **done** (11h, 0 dead of 33, AB-01; sole writer since 275) |
| `gui/widgets/web_nav_bus.py` | 96 | **done** (10r-pt1) |
| `gui/workers/__init__.py` | 1 | **done** (clean) |
| `gui/workers/brain_launch_worker.py` | 744 | **done** (11l, 0 dead of 16, verified sound; 310 — VRAM contention gate is warn-only, never a refusal) |
| `gui/workers/db_query_worker.py` | 68 | **done** (10r-pt1) |
| `gui/workers/provider_lifecycle_backend.py` | 1,771 | **done** (11b, 2 dead of 63; V-01/V-02 removed 252/253; 314 — the launch persist writer passes remove_keys through) |
| `gui/workers/provider_workers.py` | 57 | **done** (10r-pt1) |
| **subtotal** | **21,772** | |

## 50-app  --  15 files, 7,098 lines

| Script | Lines | Status |
|---|---:|---|
| `app/__init__.py` | 1 | **done** (clean) |
| `app/action_pipeline.py` | 649 | **done** (AQ-02 modify path hardened 276) |
| `app/database.py` | 733 | **done** (11m, 10 dead of 39; AF-01 wired at 249 - proposal write + dedup guard live, stale submission copy deleted) |
| `app/earning_learning_loop.py` | 237 | **done** (verified sound) |
| `app/earning_memory.py` | 2,281 | **done** (P-02 fixed 306 - learning_dashboard wired; P-03) |
| `app/earning_pipeline.py` | 1,566 | **done** (11c, 8 dead of 52; W-01 fixed 285 — 262-line parallel discovery island deleted; W-02 fixed 286 — live source gates; F-01 fixed 282 — scheduler read side; A-01 fixed 280 — learning read side; AF-01 persist hook + 121-line unreachable copy deleted at 249; W-04 removed 254; W-03 capability now in the CLI 274) |
| `app/effects.py` | 255 | **done** |
| `app/environment.py` | 196 | **done** (verified sound; 314 — set_env_values(remove_keys) drops stale keys, comments preserved) |
| `app/failure_log.py` | 44 | **done** (verified sound) |
| `app/library.py` | 138 | **done** |
| `app/provider_models.py` | 636 | **done** |
| `app/startup_validation.py` | 93 | **done** (P-01 fixed 293 — called from the `__main__` entrypoint) |
| `app/text_utils.py` | 53 | **done** |
| `app/theme_config.py` | 212 | **done** |
| `app/version.py` | 4 | **done** (verified sound) |
| **subtotal** | **7,098** | |

## 60-agents  --  1 files, 70 lines

| Script | Lines | Status |
|---|---:|---|
| `agents/__init__.py` | 70 | **done** (clean) |
| **subtotal** | **70** | |

## 80-tools  --  4 files, 925 lines

| Script | Lines | Status |
|---|---:|---|
| `tools/gen_codemap.py` | 186 | **done** (10t, untracked dev tooling) |
| `tools/github_publish/github_upload.py` | 396 | **done** (10t, untracked) |
| `tools/github_publish/sync_github_upload.py` | 285 | **done** (10t, untracked) |
| `tools/profile_lag.py` | 58 | **done** (10t) |
| **subtotal** | **925** | |

## 85-tmp  --  6 files, 363 lines

| Script | Lines | Status |
|---|---:|---|
| `tmp/ae151_sweep.py` | 156 | **done** (10t, N-03 debris) |
| `tmp/probe_concurrency.py` | 27 | **done** (10t, N-03 debris) |
| `tmp/probe_concurrency2.py` | 34 | **done** (10t, N-03 debris) |
| `tmp/probe_concurrency3.py` | 33 | **done** (10t, N-03 debris) |
| `tmp/probe_repeat.py` | 10 | **done** (10t, N-03 debris) |
| `tmp/probe_review.py` | 103 | **done** (10t, N-03 debris) |
| **subtotal** | **363** | |

## 90-docs  --  1 files, 37 lines

| Script | Lines | Status |
|---|---:|---|
| `docs/codemap/_scan.py` | 37 | **done** (10t, untracked scratch) |
| **subtotal** | **37** | |

## 90-logs  --  1 files, 116 lines

| Script | Lines | Status |
|---|---:|---|
| `logs/crash_watchdog.py` | 116 | **done** (10t, untracked, sound) |
| **subtotal** | **116** | |

## 90-skills  --  1 files, 11 lines

| Script | Lines | Status |
|---|---:|---|
| `skills/__init__.py` | 11 | **done** (10t, clean) |
| **subtotal** | **11** | |

## scripts/ (launchers)  --  8 files, 155 lines

| Script | Lines | Status |
|---|---:|---|
| `scripts/launch_llamacpp_brain.ps1` | 64 | **done** (10t, verified sound) |
| `scripts/launch_lm_studio.bat` | 6 | **done** (10t) |
| `scripts/launch_lm_studio.ps1` | 27 | **done** (10t, T-01) |
| `scripts/start_big_brain_llamacpp.ps1` | 3 | **done** (10t, 3-line shim) |
| `scripts/start_dual_brain.ps1` | 26 | **done** (10t, T-01) |
| `scripts/start_small_brain_llamacpp.ps1` | 3 | **done** (10t, 3-line shim) |
| `scripts/start_small_brain_ollama.bat` | 4 | **done** (10t) |
| `scripts/start_small_brain_ollama.ps1` | 22 | **done** (10t, verified sound) |

---

**295 scripts, 90,985 lines.** (Through v2.1.125: 291 scripts, 90,567 lines —
ARCH-ENG-233 deleted four `agents/cognition/` satellite modules (205 lines) and
shrank `graph.py` by 213.)

---

## Depth-pass backlog (largest-first)

| # | Lines | File | Status |
|---:|---:|---|---|
| 1 | 4398 | `gui/tabs/dialogue_tab.py` | **done** - 11C-dialogue-tab-depth |
| 2 | 3898 | `gui/builders/tab_feature_builders.py` | **done** - 11D-tab-builders-depth |
| 3 | 3804 | `gui/widgets/dual_brain_control.py` | **done** - 11E-dual-brain-control-depth |
| 4 | 3735 | `main.py` | **done** - 11a-main-py-depth |
| 5 | 2281 | `app/earning_memory.py` | **done** - 11F-earning-memory-depth |
| 6 | 1771 | `gui/workers/provider_lifecycle_backend.py` | **done** - 11b-provider-lifecycle-backend-depth |
| 7 | 1566 | `app/earning_pipeline.py` | **done** - 11c-earning-pipeline-depth |
| 8 | 1381 | `agents/runtime/dual_brain.py` | **done** - 11d-dual-brain-depth |
| 9 | 1309 | `agents/services/autonomous_loop.py` | **done** - 11e-autonomous-loop-depth |
| 10 | 1067 | `agents/earning/opportunity_lifecycle.py` | **done** - 11f-opportunity-lifecycle-depth |
| 11 | 997 | `agents/knowledge/workshop.py` | **done** - 11G-workshop-depth |
| 12 | 992 | `agents/safety/handlers.py` | **done** - 11g-safety-handlers-depth |
| 13 | 972 | `gui/widgets/provider_config_widget.py` | **done** - 11h-provider-config-widget-depth |
| 14 | 854 | `agents/earning/opportunity_portfolio.py` | **done** - 11i-opportunity-portfolio-depth |
| 15 | 848 | `agents/runtime/device_registry.py` | **done** - 11j-device-registry-depth |
| 16 | 782 | `agents/safety/guard.py` | **done** - 11k-safety-guard-depth |
| 17 | 744 | `gui/workers/brain_launch_worker.py` | **done** - 11l-brain-launch-worker-depth |
| 18 | 733 | `app/database.py` | **done** - 11m-agentdb-depth |
| 19 | 722 | `agents/dialogue/chat_completion.py` | **done** - 11n-chat-completion-depth |
| 20 | 707 | `agents/brains/big_brain.py` | **done** - 11o-big-brain-depth |
| 21 | 697 | `agents/providers/provider_manager.py` | **done** - 11p-provider-manager-depth |
| 22 | 691 | `agents/services/self_audit.py` | **done** - 11r-self-audit-depth |
| 23 | 688 | `run_lead_routine.py` | **done** - 11q-run-lead-routine-depth |
| 24 | 649 | `app/action_pipeline.py` | **done** - 11x-action-pipeline-depth |
| 25 | 636 | `app/provider_models.py` | **done** - 11s-provider-models-depth |
| 26 | 636 | `agents/safety/approval.py` | **done** - 11t-approval-depth |
| 27 | 623 | `gui/tabs/safety_tools_tab.py` | **done** - 11H-safety-tools-tab-depth |
| 28 | 623 | `agents/core/comms.py` | **done** - 11u-comms-depth |
| 29 | 615 | `agents/earning/live_trading.py` | **done** - 11v-live-trading-depth |
| 30 | 612 | `agents/earning/discoverer.py` | **done** - 11w-discoverer-depth |
| 31 | 605 | `agents/brains/small_brain.py` | **done** - 11I-small-brain-depth |
| 32 | 592 | `agents/earning/executor.py` | **done** - 11J-executor-depth |
| 33 | 590 | `gui/tabs/earning_tab.py` | **done** - 11K-earning-tab-depth |
| 34 | 575 | `agents/knowledge/help_catalog.py` | **done** - 11L-help-catalog-depth |
| 35 | 567 | `agents/core/event_logger.py` | **done** - 11M-event-logger-depth |
| 36 | 558 | `agents/providers/model_profile.py` | **done** - 11N-model-profile-depth |
| 37 | 557 | `agents/providers/huggingface_models.py` | **done** - 11O-huggingface-depth |
| 38 | 535 | `agents/earning/economic_accounting.py` | **done** - 11P-economic-accounting-depth |
| 39 | 526 | `agents/earning/goal_system.py` | **done** - 11Q-goal-system-depth |
| 40 | 310 | `agents/cognition/graph.py` | **done** - 11R-cognition-graph-depth |
| 41 | 501 | `agents/services/mrbot_cli.py` | **done** - 11y-mrbot-cli-depth |
| 42 | 336 | `agents/safety/legacy_tools.py` | **done** - 11z-legacy-tools-depth |
| 43 | 335 | `agents/knowledge/skill_index.py` | **done** - 11A-skill-index-depth |
| 44 | 330 | `agents/earning/freelance_finder.py` | **done** - 11B-freelance-finder-depth |
| | | *4 rows removed by ARCH-ENG-233 (ledger/state/memory_promotion/contradictions — deleted with the CognitionRecord island)* | |

**Pending: 238 files, 43427 lines** (largest-first):

| # | Lines | File | Status |
|---:|---:|---|---|
| p1 | 506 | `gui/tabs/model_library_tab.py` | pending |
| p2 | 506 | `agents/dialogue/convergence_plan.py` | pending |
| p3 | 503 | `gui/tabs/earning_insights.py` | pending |
| p4 | 494 | `agents/core/alerting.py` | pending |
| p5 | 492 | `gui/tabs/chat_tab.py` | pending |
| p6 | 488 | `agents/services/code_patch_service.py` | **done** - 288 |
| p7 | 484 | `agents/knowledge/prompting_engine.py` | pending |
| p8 | 474 | `agents/integrations/web_eyes.py` | **done** - 290 |
| p9 | 473 | `agents/providers/gguf_meta.py` | pending |
| p10 | 473 | `agents/discovery/discovery_sources.py` | pending |
| p11 | 455 | `agents/earning/opportunity_intelligence.py` | pending |
| p12 | 442 | `agents/knowledge/program_knowledge.py` | **done** - 297 |
| p13 | 440 | `agents/earning/validators.py` | pending |
| p14 | 436 | `agents/earning/airdrop_scanner.py` | pending |
| p15 | 431 | `agents/evidence/evidence.py` | pending |
| p16 | 414 | `agents/integrations/browser.py` | **done** - 290 |
| p17 | 407 | `agents/evidence/document_scanner.py` | **done** - 299 |
| p18 | 400 | `agents/earning/moltbook_agent.py` | pending |
| p19 | 396 | `tools/github_publish/github_upload.py` | pending |
| p20 | 394 | `agents/autonomy/agent_registry.py` | pending |
| p21 | 389 | `agents/earning/paper_trading.py` | pending |
| p22 | 388 | `agents/discovery/discovery_scheduler.py` | **done** - 282 |
| p23 | 383 | `agents/brains/brain_got.py` | pending |
| p24 | 380 | `gui/tabs/management_tab.py` | pending |
| p25 | 379 | `agents/earning/social_earning_platform.py` | pending |
| p26 | 377 | `agents/earning/backtesting.py` | pending |
| p27 | 374 | `agents/providers/openai_compatible.py` | pending |
| p28 | 370 | `agents/cognition/fact_ledger.py` | pending |
| p29 | 363 | `agents/earning/economic_policy.py` | pending |
| p30 | 360 | `agents/dialogue/opportunity_analysis.py` | pending |
| p31 | 356 | `agents/runtime/brain_contention.py` | pending |
| p32 | 355 | `agents/safety/filesystem.py` | pending |
| p33 | 354 | `agents/runtime/brain_roster.py` | pending |
| p34 | 354 | `agents/brains/shared_context.py` | pending |
| p35 | 353 | `agents/brains/worker_provider_mixin.py` | pending |
| p36 | 346 | `agents/cognition/personas.py` | pending |
| p37 | 345 | `agents/integrations/wallet_manager.py` | pending |
| p38 | 345 | `agents/brains/base_worker.py` | **done** - 288 |
| p39 | 338 | `agents/services/analyst_worker.py` | **done** - 294 |
| p40 | 326 | `agents/cognition/coordinator.py` | pending |
| p41 | 325 | `agents/autonomy/cli.py` | **done** - 300 |
| p42 | 319 | `agents/earning/platform_submitter.py` | pending |
| p43 | 318 | `agents/services/coder.py` | **done** - 304 |
| p44 | 318 | `agents/earning/reputation.py` | pending |
| p45 | 302 | `agents/earning/capability.py` | **deleted** - 300 |
| p46 | 301 | `agents/safety/tools.py` | **done** - 292 |
| p47 | 299 | `gui/tabs/analytics_tab.py` | pending |
| p48 | 298 | `agents/earning/opportunity_models.py` | pending |
| p49 | 290 | `agents/integrations/scraper.py` | pending |
| p50 | 289 | `agents/safety/response.py` | pending |
| p51 | 288 | `agents/autonomy/self_improvement.py` | pending |
| p52 | 287 | `agents/integrations/wallet_crypto.py` | pending |
| p53 | 285 | `tools/github_publish/sync_github_upload.py` | pending |
| p54 | 285 | `gui/panels/approval_panel.py` | pending |
| p55 | 284 | `agents/safety/workspace.py` | **done** - 299 |
| p56 | 279 | `agents/providers/provider_lifecycle.py` | pending |
| p57 | 279 | `agents/core/persistence_contract.py` | pending |
| p58 | 273 | `agents/platforms/registration.py` | pending |
| p59 | 271 | `gui/panels/registration_panel.py` | pending |
| p60 | 270 | `gui/widgets/brain_control_row.py` | pending |
| p61 | 267 | `agents/cognition/speaker_registry.py` | pending |
| p62 | 266 | `agents/cognition/dialogue_honesty.py` | pending |
| p63 | 263 | `agents/services/autonomous_run_store.py` | pending |
| p64 | 257 | `agents/safety/gates.py` | pending |
| p65 | 257 | `agents/integrations/crypto.py` | pending |
| p66 | 257 | `agents/dialogue/chat_router.py` | **deleted** - 303 |
| p67 | 255 | `app/effects.py` | pending |
| p68 | 244 | `gui/widgets/brain_roster_panel.py` | pending |
| p69 | 241 | `agents/brains/worker_llm_mixin.py` | pending |
| p70 | 240 | `gui/tabs/payments_tab.py` | pending |
| p71 | 238 | `agents/runtime/hardware_plan.py` | **deleted** - 301 |
| p72 | 238 | `agents/integrations/fiverr.py` | pending |
| p73 | 238 | `agents/cognition/reasoning_modes.py` | pending |
| p74 | 237 | `gui/widgets/brain_settings_row.py` | **done** - 298 |
| p75 | 237 | `app/earning_learning_loop.py` | pending |
| p76 | 237 | `agents/safety/calling.py` | pending |
| p77 | 236 | `agents/earning/airdrop_claimer.py` | pending |
| p78 | 229 | `agents/autonomy/onchain_identity.py` | pending |
| p79 | 226 | `agents/runtime/services.py` | pending |
| p80 | 226 | `agents/runtime/context.py` | pending |
| p81 | 220 | `agents/services/patch_sandbox.py` | pending |
| p82 | 220 | `agents/earning/microtask_earner.py` | pending |
| p83 | 218 | `agents/integrations/upwork.py` | pending |
| p84 | 216 | `agents/earning/capabilities.py` | pending |
| p85 | 214 | `agents/safety/instructions.py` | pending |
| p86 | 213 | `agents/services/cli_interface.py` | pending |
| p87 | 213 | `agents/core/notifications.py` | pending |
| p88 | 212 | `app/theme_config.py` | pending |
| p89 | 209 | `agents/earning/got.py` | pending |
| p90 | 208 | `agents/runtime/agent.py` | pending |
| p91 | 207 | `agents/safety/provider_rate_limiter.py` | pending |
| p92 | 207 | `agents/knowledge/proposal_reviewer.py` | **done** - 294/296 |
| p93 | 207 | `agents/evidence/evidence_policy.py` | pending |
| p94 | 207 | `agents/autonomy/heartbeat.py` | pending |
| p95 | 205 | `agents/integrations/wallet.py` | pending |
| p96 | 203 | `agents/discovery/discovery_strategies.py` | pending |
| p97 | 199 | `agents/cognition/operator_override.py` | pending |
| p98 | 196 | `app/environment.py` | pending |
| p99 | 194 | `agents/earning/spec.py` | pending |
| p100 | 194 | `agents/earning/real_crypto_operator.py` | pending |
| p101 | 193 | `agents/earning/submission_ramp.py` | pending |
| p102 | 192 | `agents/integrations/web.py` | pending |
| p103 | 189 | `agents/providers/provider_hot_reload.py` | pending |
| p104 | 189 | `agents/earning/evaluation.py` | pending |
| p105 | 188 | `agents/core/state_reconciliation.py` | pending |
| p106 | 186 | `tools/gen_codemap.py` | pending |
| p107 | 183 | `gui/tabs/collaboration_tab.py` | pending |
| p108 | 181 | `agents/earning/proposal.py` | pending |
| p109 | 180 | `agents/core/composition_root.py` | pending |
| p110 | 179 | `agents/discovery/scrape_resilience.py` | pending |
| p111 | 176 | `agents/discovery/web_discovery.py` | pending |
| p112 | 171 | `agents/knowledge/prompt_utils.py` | pending |
| p113 | 170 | `agents/brains/worker_safety.py` | pending |
| p114 | 169 | `agents/evidence/provenance.py` | pending |
| p115 | 168 | `agents/safety/gate.py` | pending |
| p116 | 168 | `agents/safety/cost.py` | pending |
| p117 | 168 | `agents/core/comms_log.py` | pending |
| p118 | 162 | `agents/evidence/evidence_factory.py` | pending |
| p119 | 157 | `agents/earning/chain_verifier.py` | pending |
| p120 | 156 | `tmp/ae151_sweep.py` | pending |
| p121 | 156 | `agents/integrations/microtask.py` | pending |
| p122 | 155 | `agents/earning/validator.py` | pending |
| p123 | 154 | `agents/safety/authorization.py` | pending |
| p124 | 154 | `agents/platforms/credential_vault.py` | pending |
| p125 | 154 | `agents/earning/strategy_feedback.py` | pending |
| p126 | 153 | `agents/providers/model_recommendations.py` | pending |
| p127 | 153 | `agents/evidence/evidence_store.py` | pending |
| p128 | 148 | `agents/earning/defi_scanner.py` | pending |
| p129 | 147 | `agents/cognition/dialogue.py` | pending |
| p130 | 145 | `agents/earning/tasks.py` | pending |
| p131 | 144 | `agents/knowledge/layered_memory.py` | pending |
| p132 | 143 | `agents/brains/worker_provider_calls.py` | pending |
| p133 | 139 | `agents/earning/payout_verifier.py` | pending |
| p134 | 138 | `gui/builders/tab_lifecycle.py` | pending |
| p135 | 138 | `app/library.py` | pending |
| p136 | 138 | `agents/runtime/llm.py` | pending |
| p137 | 137 | `agents/services/self_improvement_commands.py` | pending |
| p138 | 137 | `agents/runtime/provider_keys.py` | pending |
| p139 | 133 | `agents/safety/dispatch.py` | pending |
| p140 | 132 | `gui/builders/tab_workers.py` | pending |
| p141 | 131 | `agents/runtime/performance.py` | pending |
| p142 | 131 | `agents/providers/ollama_adapter.py` | pending |
| p143 | 129 | `agents/earning/rug_screen.py` | pending |
| p144 | 128 | `agents/knowledge/proposal_templates.py` | pending |
| p145 | 122 | `agents/earning/router.py` | **done** - 292 |
| p146 | 121 | `gui/widgets/performance.py` | pending |
| p147 | 121 | `gui/panels/help_dialog.py` | pending |
| p148 | 121 | `agents/earning/platform_throttle.py` | pending |
| p149 | 120 | `agents/knowledge/proposal_writer.py` | pending |
| p150 | 116 | `logs/crash_watchdog.py` | pending |
| p151 | 114 | `agents/cognition/epistemic.py` | pending |
| p152 | 112 | `agents/safety/circuit.py` | pending |
| p153 | 112 | `agents/discovery/discovery_engine.py` | pending |
| p154 | 109 | `gui/theme_ui_state.py` | pending |
| p155 | 109 | `agents/knowledge/prompt_sanitize.py` | **done** - 296 |
| p156 | 103 | `tmp/probe_review.py` | pending |
| p157 | 102 | `agents/dialogue/discussion.py` | pending |
| p158 | 101 | `agents/core/configuration.py` | pending |
| p159 | 98 | `agents/earning/discovery.py` | pending |
| p160 | 96 | `gui/widgets/web_nav_bus.py` | pending |
| p161 | 96 | `agents/cognition/__init__.py` | pending |
| p162 | 93 | `app/startup_validation.py` | **done** - 293 |
| p163 | 93 | `agents/earning/evidence.py` | pending |
| p164 | 90 | `agents/providers/model_capabilities.py` | pending |
| p165 | 90 | `agents/evidence/numeric_evidence.py` | pending |
| p166 | 89 | `agents/safety/trust.py` | pending |
| p167 | 87 | `agents/core/feature_flags.py` | pending |
| p168 | 86 | `agents/safety/__init__.py` | pending |
| p169 | 86 | `agents/core/account_profile.py` | **deleted** - 302 |
| p170 | 85 | `agents/earning/portfolio.py` | pending |
| p171 | 82 | `agents/earning/social_writer_factory.py` | pending |
| p172 | 82 | `agents/earning/ranking.py` | pending |
| p173 | 81 | `agents/core/architecture_boundaries.py` | **moved** - 302 |
| p174 | 79 | `agents/earning/__init__.py` | pending |
| p175 | 78 | `gui/builders/refresh_coordinator.py` | pending |
| p176 | 78 | `agents/brains/worker_thinking.py` | pending |
| p177 | 74 | `agents/earning/win_rate_guard.py` | pending |
| p178 | 70 | `agents/knowledge/llama_setting_help.py` | pending |
| p179 | 70 | `agents/__init__.py` | pending |
| p180 | 69 | `agents/earning/intelligence.py` | pending |
| p181 | 68 | `gui/workers/db_query_worker.py` | pending |
| p182 | 65 | `agents/cognition/ledger.py` | **removed** (ARCH-ENG-233) |
| p183 | 64 | `agents/cognition/contradictions.py` | **removed** (ARCH-ENG-233) |
| p184 | 62 | `agents/providers/context_table.py` | pending |
| p185 | 61 | `agents/runtime/stats.py` | pending |
| p186 | 61 | `agents/earning/gas_estimator.py` | pending |
| p187 | 60 | `agents/services/workflow_planner.py` | pending |
| p188 | 60 | `agents/earning/opportunity_adapters.py` | pending |
| p189 | 59 | `gui/widgets/persona_naming.py` | pending |
| p190 | 58 | `tools/profile_lag.py` | pending |
| p191 | 58 | `agents/discovery/discovery_port.py` | pending |
| p192 | 57 | `gui/workers/provider_workers.py` | pending |
| p193 | 55 | `agents/providers/anthropic_adapter.py` | pending |
| p194 | 54 | `agents/services/application_services.py` | pending |
| p195 | 54 | `agents/cognition/memory_promotion.py` | **removed** (ARCH-ENG-233) |
| p196 | 54 | `agents/autonomy/__init__.py` | pending |
| p197 | 53 | `gui/builders/tab_builders.py` | pending |
| p198 | 53 | `app/text_utils.py` | pending |
| p199 | 53 | `agents/safety/sql.py` | pending |
| p200 | 48 | `agents/brains/worker_budget.py` | pending |
| p201 | 46 | `agents/safety/policy.py` | pending |
| p202 | 46 | `agents/earning/platform_skill_urls.py` | pending |
| p203 | 46 | `agents/brains/worker_workspace.py` | pending |
| p204 | 44 | `app/failure_log.py` | pending |
| p205 | 44 | `agents/earning/execution.py` | pending |
| p206 | 43 | `agents/runtime/__init__.py` | pending |
| p207 | 42 | `agents/autonomy/grants.py` | pending |
| p208 | 41 | `agents/platforms/__init__.py` | pending |
| p209 | 41 | `agents/earning/payment_evidence.py` | pending |
| p210 | 41 | `agents/core/recovery.py` | **deleted** - 302 |
| p211 | 40 | `agents/earning/payment.py` | pending |
| p212 | 36 | `agents/earning/accounting.py` | pending |
| p213 | 34 | `tmp/probe_concurrency2.py` | pending |
| p214 | 33 | `tmp/probe_concurrency3.py` | pending |
| p215 | 29 | `agents/providers/__init__.py` | pending |
| p216 | 27 | `tmp/probe_concurrency.py` | pending |
| p217 | 25 | `gui/panels/dialogue_log.py` | pending |
| p218 | 25 | `agents/knowledge/prompt_assembly.py` | pending |
| p219 | 22 | `agents/cognition/state.py` | **removed** (ARCH-ENG-233) |
| p220 | 21 | `agents/safety/learning.py` | pending |
| p221 | 20 | `agents/earning/submission.py` | pending |
| p222 | 20 | `agents/brains/worker_provider.py` | pending |
| p223 | 19 | `agents/services/task_executor.py` | pending |
| p224 | 19 | `__init__.py` | pending |
| p225 | 11 | `skills/__init__.py` | pending |
| p226 | 10 | `tmp/probe_repeat.py` | pending |
| p227 | 4 | `app/version.py` | pending |
| p228 | 2 | `agents/integrations/__init__.py` | pending |
| p229 | 1 | `gui/workers/__init__.py` | pending |
| p230 | 1 | `gui/widgets/__init__.py` | pending |
| p231 | 1 | `gui/tabs/__init__.py` | pending |
| p232 | 1 | `gui/panels/__init__.py` | pending |
| p233 | 1 | `gui/builders/__init__.py` | pending |
| p234 | 1 | `app/__init__.py` | pending |
| p235 | 1 | `agents/services/__init__.py` | pending |
| p236 | 1 | `agents/knowledge/__init__.py` | pending |
| p237 | 1 | `agents/evidence/__init__.py` | pending |
| p238 | 1 | `agents/discovery/__init__.py` | pending |
| p239 | 1 | `agents/dialogue/__init__.py` | pending |
| p240 | 1 | `agents/core/__init__.py` | pending |
| p241 | 1 | `agents/brains/__init__.py` | pending |
| p242 | 0 | `gui/__init__.py` | pending |

