## [2.1.46] - 2026-10-11 - .env.example reframed for the N-brain flow + synced with live keys

### Changed
`.env.example` was stale: it framed everything as a fixed "Dual Brain" (Big/Small)
and was missing keys the current program and the live `.env` actually use. A fresh
copy of `.env.example` → `.env` was no longer a valid, complete config.

- **Reframed the brain section as device-centric N-brain** (v2.1): documents that
  the runtime detects every GPU + the CPU/RAM pool and assigns ordered slots —
  slot 0/1 = Big/Small (`BIG_BRAIN_*`/`SMALL_BRAIN_*`, back-compat), slots 2+ =
  extra devices (`BRAIN_SLOT{n}_NAME`, per-device settings in settings.json).
- Added the missing keys the code reads and the live `.env` already has:
  `BIG_BRAIN_NAME`/`SMALL_BRAIN_NAME` (moved into the brain section),
  `BIG_BRAIN_SHOW_PERF`/`SMALL_BRAIN_SHOW_PERF`, `BRAIN_SLOT2_NAME` (documented),
  `SHOW_BRAIN_CONSOLES`, `CLOUD_FAILOVER_ENABLED`, `ACTIVE_CLOUD_PROVIDER`,
  `ALLOW_WEB_DISCOVERY`, `MRBOT_ENABLE_*` feature flags +
  `MRBOT_SELF_IMPROVE_MONITOR_MINUTES`, `OPENAI_BASE_URL`, `NOUS_CHAT_MODEL`,
  and the NOUS role block (`DISABLE_NOUS`/`NOUS_MAIN_ENABLED`/`NOUS_CHAT_ENABLED`/
  `NOUS_HIDE`).
- Removed the now-duplicate `BIG_BRAIN_NAME`/`SMALL_BRAIN_NAME` lines that lived
  lower in the file.

### Verified
- `.env.example` parses as a valid dotenv: 229 keys, no duplicates, no malformed
  lines; loads via `dotenv_values`.
- Cross-checked `.env.example` vs the live `.env`: every key the operator's `.env`
  carries is now either present or explicitly documented (commented) in the
  template. The live `.env` is structurally clean (231 keys, no dupes/malformed)
  and already N-brain-ready (`BRAIN_SLOT2_NAME=Chris Borrows`,
  `CLOUD_FAILOVER_ENABLED`, `SHOW_BRAIN_CONSOLES`); its values were left untouched
  (secrets + working config).

### Changed (docs)
- **README refreshed to match v2.1.46.** It was 7 versions stale (titled v2.1.39)
  and still framed entirely as "Dual-Brain". Updated to the device-centric
  **Multi-Brain** framing; added the N-brain runtime, shared-skills peer-council
  Dialogue, GoT branch expansion, cloud-failover control, conversational-awareness
  prompts, and per-brain settings/`--perf` console timings to Highlights; added
  `agents/autonomy`, `agents/integrations`, `agents/polish` and the new key files
  (`device_registry.py`, `speaker_registry.py`, `brain_got.py`) to the structure;
  and expanded the Configuration section with the N-brain keys. All three version
  authorities (README, `app/version.py`, CHANGELOG) now agree on v2.1.46.

## [2.1.45] - 2026-10-11 - Publish mirror: stop leaking tools/, test artifacts, bytecode, routine script

### Fixed
The public GitHub mirror had been polluted with files that are NOT part of the
MrBot1000 program. The sync's exclusion list had drifted from the source
`.gitignore`:

- **`tools/`** (this mirror's own publish scripts) was in `INCLUDE` and
  `RECURSE_FOLDERS` — removed from both and added to `SKIP_DIRS`. The publish
  tooling must never publish itself.
- **`run_lead_routine.py`** (a Hermes-agent scheduled-routine driver, not program
  code) was in `INCLUDE` — removed and added to `SKIP_FILES`.
- **`.pytest_cache/`** and **`tests/test_results/*.json`** (pytest run cache +
  historical test-run output) were not excluded — added to `SKIP_DIRS` (matching
  `.gitignore`).
- **`__pycache__/` + `*.pyc`** — the per-file skip already covered these for new
  copies, but the copy engine only ever ADDS/OVERWRITES and never deletes, so
  stale bytecode from older syncs persisted in the mirror.

### Changed
- Added a **cleanup pass** (`STALE_DESTINATION_PATHS` + a `__pycache__`/`.pyc`
  sweep) that actively REMOVES these from the mirror on every run, so re-running
  the sync purges existing pollution instead of leaving it. Never touches `.git`.

### Verified
- Ran the sync against the live mirror: copied count 519 → 487; all five
  pollution types now absent (`tools/`, `run_lead_routine.py`, `.pytest_cache`,
  `test_results/*.json`, 0 `__pycache__` dirs, 0 `.pyc`).
- Completeness intact: the only source `.py` files absent from the mirror are the
  intended exclusions (`_migrate_*.py`, `run_lead_routine.py`); zero extra files;
  mirror still imports as a complete program (v2.1.45). No secret/state leaks.
- Tests grew to 9 in `tests/tools/test_github_publish_sync.py`: publish-tooling +
  routine-script excluded, test artifacts excluded, bytecode excluded, stale-path
  purge configured.

## [2.1.44] - 2026-10-11 - Publish-mirror sync: include the new public docs, harden exclusions

### Fixed
The GitHub publish mirror (`tools/github_publish/sync_github_upload.py`) was
silently dropping the public docs added with the v2.1 restructure —
`ARCHITECTURE_MAP.md`, `OPERATIONS.md`, `RELEASE_CHECKLIST.md` — because the root
recursive fallback only globs `*.py` (README was special-cased, the rest were
not). They are now listed explicitly in `INCLUDE`.

### Changed
- Hardened `EXCLUDE_PATTERNS` so internal ops/cron artifacts that sit next to the
  public docs at the repo root can never be published: `DEADCODE_REPORT.md`,
  `cron_report_*.md`, `routine_prompt.txt`, `schedule_prompt.md`, and `*.bak_*`
  (e.g. `.env.bak_*`). Defense-in-depth against a future broadened fallback.

### Verified
- Ran the sync against the live mirror: 519 files copied, `.env.example`
  sanitized, README refreshed. The mirror is a complete, importable program
  (`import main` OK from the mirror, version 2.1.44).
- Completeness: the only source `.py` files absent from the mirror are the
  intended exclusions (`.hermes/`, `_migrate_*.py`); the mirror has zero extra
  files. New agent subpackages (autonomy/dialogue/integrations/polish/services/
  evidence/runtime) and gui/panels are all present via the recursive fallback.
- Safety: no `.env`, `settings.json`, `models_cache.json`, or `.env.bak_*` in the
  mirror; `.env.example` carries only `your-*` placeholders.
- New test `tests/tools/test_github_publish_sync.py` (5 tests): public docs
  included, internal ops/cron excluded, secrets/state excluded, no stale INCLUDE
  entries, core program surface covered.

## [2.1.43] - 2026-10-11 - Persona prompts: conversational awareness, not a script

### Changed
Tuned the earning (DRIVER) and helper (NAVIGATOR) system prompts so the agents
read as real participants instead of following a template. The full-tier prompt
was a dense block of tool-format rules + a rigid ROLE CONTRACT + phase
instruction, with nothing encouraging the agent to react to what was just said —
which produced the robotic, same-analysis-every-turn replies.

Added a **"BE A REAL PARTICIPANT, NOT A SCRIPT"** section to the full tier and a
compact version to the compact tier (small brains). It instructs the agent to:
- **Answer the human** when they speak — react to their actual words (agree,
  push back, ask one sharp question, acknowledge), not ignore them and keep
  narrating the opportunity.
- **Engage a teammate's last point** — build on it, disagree with a reason, or
  correct a specific claim; don't restate your own position as if they never spoke.
- **Vary the opening** — don't begin every turn the same way or re-run an analysis
  already given; if you have nothing new, say so or ask what would move this forward.
- **Hold a genuine opinion** — a flat fact-recap reads robotic; a real stance
  ("worth it" / "I'd skip it" / "not convinced yet") reads like a person. The agent
  may still push the goal in the same reply.

This is prompt-layer tuning only — no duplication of the dynamically-injected
team brief or anti-hallucination rules.

### Verification
- New test `test_prompt_teams_conversational_awareness_not_a_script`: awareness
  block present in both tiers; full tier carries "ANSWER THEM" + "genuine
  opinion"; both warn against restating / same-way openings.
- Persona + dialogue + cognition suites: 302 passed, 3 skipped.

## [2.1.42] - 2026-10-11 - Dialogue awareness: real roster in the header + live human-message tracking

### Fixed
The Dialogue agents felt "robotic / script-following" with "no awareness." Two
concrete context defects were the root cause (the human's message was technically
in history but the framing made agents ignore it):

- **The context header hardcoded a 2-person pair.** It always said
  "Talking with Edward Hurst and Jacob Stanley" regardless of the actual roster,
  so a 3rd brain (Chris Borrows) or any renamed persona had no accurate sense of
  who was in the room. The header now names THIS speaker and lists the ACTUAL
  peers from the roster, and frames each agent as an independent participant that
  sees the same messages and decides for itself whether to answer the human,
  react to a teammate, or push the goal — not waiting for a turn.
- **The human's latest message was tracked by a sticky `_operator_directive`
  that was never recomputed.** Once set it stuck, so after the human moved on the
  agents kept being fed a stale instruction. The directive line is now recomputed
  from history every call (latest human message wins), relabeled
  "HUMAN SAID (most recent — you may respond to this and/or continue the goal)",
  and still placed ahead of the re-injected opportunity board so it is never
  outranked.

### Behavior (per operator's call)
- The Live/auto loop does **not** pause for human input. Each agent independently
  sees all messages (human + teammates + goal) and may acknowledge the human in
  passing while continuing toward the goal — no forced stop, no turn-waiting.

### Verification
- New test `test_header_names_the_actual_roster_not_a_hardcoded_pair` (3-brain
  roster: speaker named, both peers listed, hardcoded "Talking with" gone,
  independent framing present).
- Updated `test_operator_directive_precedes_board` to the new "HUMAN SAID" label;
  existing `test_directive_tracks_the_most_recent_human_message` still passes.
- Full dialogue suite: 288 passed, 3 skipped.

## [2.1.41] - 2026-10-11 - GoT branch expansion: multi-candidate thoughts + evidence-backed scoring

### Added
- **The per-turn thought graph now BRANCHES (Tree/Graph-of-Thoughts).** When the
  selected reasoning pattern allows `max_branches > 1` (tree_of_thoughts,
  graph_of_thoughts, lats), `BrainTurnGraph.expand_branches(candidates)` turns
  each candidate thought into an OPTION node that (a) derives from the goal,
  (b) depends on the evidence check, and (c) is supported by a HYPOTHESIS child
  carrying its rationale + evidence. `score_branches(evidence)` ranks them via
  the existing deterministic `ThoughtGraph.rank_options` (action_eligible >
  supported > uncontradicted > evidence-backed score); `select_branch()` records
  a scored DECISION naming the winner and marks the rest rejected. The OUTCOME
  node then derives from the decision, so the chain reflects the chosen branch.
- New `BranchCandidate` dataclass (text, rationale, evidence_ids, expected_payout,
  effort, risk). Qualitative fields are recorded for transparency; the numeric
  score comes only from deterministic evidence-backed support — narration never
  becomes verification.
- `chat(..., branch_candidates=, evidence_by_id=)` on both brain adapters: when
  the caller supplies candidates and the pattern allows branching, the turn
  expands/scores/selects. Direct (max_branches=1) patterns and single-candidate
  calls are a **no-op** — existing linear behavior is byte-for-byte preserved.
- The Dialogue "Thoughts" view now shows the branch ranking (score, recommendation,
  → SELECTED marker, candidate text) so the operator sees which thought won and why.

### Safety
- Branching is advisory: it never grants authority, never captures private
  chain-of-thought (candidates are concise public summaries), and is wrapped so a
  scoring error can never break a turn.

### Verification
- 8 new tests in `tests/earning/test_brain_got.py`: branch node creation, goal-
  derivation + hypothesis support, max_branches bound, direct/single-candidate
  no-op, evidence-backed ranking + selection + rejection, finish() branching flag
  + outcome-follows-decision, and the `_finish_got_turn` wiring.
- A branching turn records ~11 nodes / ~15 edges vs. the old fixed 4/3.
- Dialogue + brain_got + sections: 347 passed, 32 subtests.

## [2.1.40] - 2026-10-11 - Render the thought graph (fix permanent "0 nodes, 0 edges")

### Fixed
- **The Dialogue "Thoughts" view always showed "0 node(s), 0 edge(s)."** The
  renderer (`DialogueTab._show_thoughts`) did `graph.to_dict() if
  hasattr(graph, "to_dict") else {}` — but `brain.last_thought_graph` is the plain
  **dict** returned by `BrainTurnGraph.finish()`
  (`{"turn_id":…, "pattern":…, "graph": {"nodes":[…], "edges":[…]}}`), which has no
  `.to_dict()`. So `hasattr` was False, `data` became `{}`, and every turn rendered
  as empty no matter how many nodes/edges the turn actually recorded (the graph
  really carries goal/option/check/outcome + tool-observation nodes). The renderer
  now reads the dict shape (unwrapping the inner `"graph"` payload) and still
  supports the object/graph-dict forms defensively.

### Changed
- **The "Thoughts" view now surfaces the selected reasoning pattern** (name,
  max_branches, max_tool_calls, rationale). This explains *why* a turn is a linear
  skeleton vs. a branching one: `select_reasoning_pattern` resolves a plain "earn
  money" goal to `direct_dialogue` (max_branches=1), so the per-turn
  `BrainTurnGraph` records a fixed coordination skeleton + tool observations and
  legitimately shows no branch nodes. Previously this looked like a broken/empty
  graph; now it reads e.g. `pattern: direct_dialogue (max_branches=1,
  max_tool_calls=0) — small conversational work does not warrant branching`.

### Note (not a bug, by design)
The per-turn `BrainTurnGraph` is a **coordination trace**, not a multi-branch
reasoner: it records goal → option ⇄ evidence-check → outcome plus one node per
tool call. The reasoning pattern only sets orchestration limits (branches/tool
calls/approval); it does not expand the graph into Tree-of-Thoughts /
Graph-of-Thoughts branch nodes. True branching expansion is a separate,
unimplemented feature — surfaced here so the operator can see which pattern ran.

### Verification
- New test `test_show_thoughts_renders_the_finish_dict_graph`: builds a real
  `BrainTurnGraph`, finishes it, renders via `_show_thoughts`, asserts the real
  node/edge counts (never "0 node(s)") and the pattern line appear.
- Dialogue + brain_got suites: 292 passed, 32 subtests.

## [2.1.39] - 2026-10-11 - Low-trust payout can no longer reach "paid" or credit a ramp win

### Security — Financial integrity (finding ARCH-ENG-043)
- **An operator-attested (L1) payout no longer flips a lifecycle to `paid` or
  credits a submission-ramp win.** `OpportunityLifecycleTracker.mark_paid_verified`'s
  "No store + Evidence" branch trusted an *affirmative status alone*: it set
  `state.status = "paid"` for any `VERIFIED`/`PARTIALLY_VERIFIED` Evidence, with no
  trust-level check. Because `evidence_factory.from_verification_evidence` maps a
  `manual_reference` payout (an operator-typed bank/transaction id) to
  `VERIFIED @ L1_SELF_REPORTED`, and `agents/earning/evidence.is_affirmative_verification`
  also keyed on status alone, both ramp-credit call sites credited a **win** from
  self-reported money.
  - Why that matters: `SubmissionRamp.requires_human` is the gate that unlocks
    **auto-submission of real platform proposals**. It opens when a platform reaches
    `RAMP_MIN_SUBMISSIONS` (5) *and* a `success_rate >= RAMP_WIN_RATE` (0.60). A
    phantom L1 win pushes that win-rate up, so unverified money could have talked
    the system into submitting real proposals with no human in the loop — the same
    "self-report becomes truth" failure mode v2.1.36's F4 fix closed on the revenue
    side.
  - Reproduced by execution **before** the fix (store-less tracker, L1 manual
    attestation): `status='paid'`, `last_amount=250.0`,
    `is_affirmative_verification=True` → ramp win credited.
  - Both gates now apply the same L3 external-source floor the policy gate
    (`is_transition_eligible`) already enforced on the with-store path:
    `is_affirmative_verification` requires `verification_level >= L3` and fails
    closed when a record carries no level at all; the no-store branch requires
    affirmative status **and** `>= L3`, plus a positive amount. Fails closed: no
    `paid`, no booked amount, no ramp accept.
- **`is_affirmative_verification` now compares an `EvidenceStatus` enum on its
  `.value`.** `str(EvidenceStatus.VERIFIED)` is `'EvidenceStatus.VERIFIED'` on
  Python 3.14, so the object branch of that helper silently returned `False` for
  every real `Evidence` while working on `to_dict()` mappings.
- **The operator GUI payout path (`main.py`) no longer credits a ramp accept on
  `status == "paid"` alone** — it now applies the same trust floor as the pipeline
  path, and logs when a payout is marked paid below the floor.

### Verification
- New `tests/earning/test_low_trust_payout_gate.py` (19 tests).
  **Negative control:** reverting `agents/earning/evidence.py` to its pre-fix
  state fails **5** of them, including the core regression
  (`test_l1_manual_attestation_no_store_is_not_paid`) and the new
  `test_affirmative_accepts_an_evidence_object_not_just_a_dict`; reverting
  `opportunity_lifecycle.py` too fails **8**. Controls confirm genuine L3
  (`api_statement`) and L5 (`onchain_balance_delta`) payouts still reach `paid`
  with the correct amount and still credit a ramp win — the fix does not
  over-block externally proven revenue.
- Independent Reviewer re-derived the defect against pre-fix sources loaded from
  `git show` (repo never written to): **APPROVED**, no blocking issues. It
  confirmed `mark_final_outcome`, `reconcile_evidence`, the with-store policy
  path and the real GUI operator payout are byte-identical pre/post, and that
  `get_state()`'s key set is unchanged (only audit-note prose differs, which
  nothing asserts).
- Full suite: **1304 passed, 3 skipped, 77 subtests** (+19 new).
  Two failures in `tests/gui/test_provider_control_nrows.py`
  (`test_row_start_signal_routes_to_{big,small}_handler`) are **pre-existing** —
  proven by `git stash`-ing this change and reproducing both at clean HEAD
  (v2.1.38). Unrelated to this work; left for the next cycle.

### Known limits (recorded, not fixed here)
- Live blast radius today is limited: `EarningPipeline` always constructs the
  lifecycle **with** an EvidenceStore, so the operator GUI path is blocked one
  layer up by the policy gate. The vulnerable no-store branch is reachable from
  tests and from `get_lifecycle_tracker()` (used only for scheduler/ranking
  reads). This change is correct defence-in-depth for that branch and for any
  future store-less wiring.
- Two latent over-strictness cases found by the Reviewer, both unreachable today
  (no in-repo producer writes `completion_confirmation`/`payment_confirmation`,
  and every `platform_submission` producer emits L1): (a) a genuine L3 chain in
  the store followed by an L1 attestation for the same subject loses its ramp
  credit because `state.verification` is overwritten; (b) `reconcile_evidence`
  sets `status='paid'` from L4 evidence without refreshing `state.verification`,
  so status and `is_affirmative_verification` can disagree.

## [2.1.38] - 2026-10-11 - Persist + re-seed temperature so it stops reverting to 0.50

### Fixed
- **Temperature reverted to 0.50 after "Save Local Provider Settings."** The
  `BrainSettingsRow` temperature spin was hardcoded `setValue(0.5)` at creation
  and `_apply_runtime` seeded every other control (context/threads/batch/split/
  kv/gpu_layers) from the runtime config but **not temperature** — so on any
  rebuild/re-apply the widget snapped back to 0.5 even though the save itself
  wrote `BIG/SMALL_BRAIN_TEMPERATURE` correctly and the brains already read
  those keys for inference. Two fixes: (1) `_apply_runtime` now seeds the temp
  spins from `BIG/SMALL_BRAIN_TEMPERATURE` (signals blocked so seeding doesn't
  re-trigger a save), and (2) `_persist_settings` now mirrors the just-saved
  temperature into `os.environ` (like it already did for MODEL) so the in-process
  env stays consistent until the next full reload.

### Verification
- New test `test_temperature_seeds_from_persisted_env`: set env temps, call
  `_apply_runtime`, assert the spins reflect them.

## [2.1.37] - 2026-10-11 - Wire the cloud-failover toggle, per-brain enable save, console token timings

### Fixed
Three Settings/Providers-GPU defects reported from live use:

- **"Auto-failover to cloud when local fails" was a dead control.** It was
  hardcoded `setChecked(True)`, never seeded from env, never persisted, and
  never read by the failover path — so unchecking it did nothing and cloud
  providers were always contacted as a backup. Now backed by
  `CLOUD_FAILOVER_ENABLED` (default on): seeded from env, persisted on toggle,
  and actually gates `WorkerProviderMixin._build_providers` — when off, cloud
  providers are excluded and only local providers serve requests. A provider
  whose Role is "Disabled" is still hard-excluded regardless (via `_role_allows`).
- **Providers & GPU "Save Local Provider Settings" didn't persist brain
  enable/disable.** `_snapshot_settings_values` wrote hardware flags + models but
  omitted `BIG_BRAIN_ENABLED`/`SMALL_BRAIN_ENABLED`, so toggling a brain off and
  saving didn't stick. Now both are captured (read defensively, fall back to the
  current env value).
- **CPU/RAM console showed no per-request token/usage output.** llama-server was
  launched without `--perf`, so a visible console showed only the load banner.
  `build_llama_command` now passes `--perf` by default (new `show_perf` field,
  env-controllable via `<ROLE>_SHOW_PERF`) so the console prints live prompt-eval
  + token-generation timings. Applies to all slots including CPU/RAM.

### Verification
- New tests: `test_cloud_failover_off_excludes_cloud_providers`,
  `test_cloud_failover_on_keeps_cloud_providers`,
  `test_perf_flag_prints_token_timings_by_default`,
  `test_perf_flag_is_configurable_off`.
- TestCostAwareRouting + TestRoleDefaults: 24 passed.

## [2.1.35] - 2026-10-11 - Reviewer-driven hardening of the registry-derived tool strip

### Fixed
Follow-up to 2.1.33, driven by the independent Reviewer's findings on that
change:

- **The duplication guard had no power.** `test_module_source_has_no_
  duplicated_tool_literal_list` scanned for a single string literal of >=80
  chars holding 4+ tool names. The Reviewer proved it **passed against the
  exact pre-change code it existed to reject**: the old list was four
  implicit-concatenation fragments of 60/66/47/51 chars, so no fragment ever
  reached the threshold. It was also false-positive-prone — `[^"]` matches
  newlines, so it inspected arbitrary spans of code, and the real hit count sat
  at 3 against an `assertLess(hits, 4)` threshold: a margin of 1, so a routine
  docstring naming four real tools would have broken the build.
  Replaced with `test_stripper_does_not_duplicate_the_registry_literal`, a
  **differential** check: an unregistered sentinel name is not stripped, then is
  registered live, and must then be stripped — which only a derived stripper
  can do. It also asserts the pattern is deterministic across calls.
- **The generated pattern was hash-seed dependent.** Sorting on length alone
  left equal-length names in `frozenset` (hash) order, so the pattern string
  genuinely differed between interpreter runs (verified under
  `PYTHONHASHSEED` 1/42/999) — semantically harmless, since no name is a prefix
  of another and every use site is `\b(?:…)\b`, but surprising for a
  "single source of truth" derivation and it would have broken any future
  snapshot or diff. The sort key is now `(-len(n), n)`.
- **The pattern was rebuilt on every call** (~33 µs of `_remove_tool_syntax`'s
  171 µs, ~20%). It is now memoised on the registry pair, so a registry change
  still yields a fresh pattern (verified by mutating the registry at runtime)
  while steady-state cost drops to a dict hit.

### Verification
- **Guard power proven by negative control.** Running the new tests against the
  TRUE pre-change implementation (`git show HEAD~2:agents/safety/response.py`,
  the hand-typed literal) now fails **3 of 5** tests, including the duplication
  guard, with
  `AssertionError: 'zz_unregistered_tool_qq | web_read' != '' — a newly
  registered tool is not stripped`. Previously the guard passed against that
  same code. (An earlier attempt at this control was invalid — `HEAD~1` was
  this change's own commit, which already contains the derivation — so it was
  re-run against `HEAD~2` after confirming that blob contains zero occurrences
  of `_tool_name_pattern`.)
- Pattern is byte-identical under `PYTHONHASHSEED` 1 / 42 / 999.
- `_remove_tool_syntax` per-call cost 171 µs → ~69 µs (2.5x), with identical
  output on all 14 leak forms and all 6 prose controls.
- Cache invalidation verified: mutating `gate.READONLY_TOOL_NAMES` at runtime
  makes the stripper pick up the new tool immediately.
- Safety + dialogue suites: 353 passed, 2 skipped, 77 subtests.
- Full suite: **1272 passed, 2 skipped, 77 subtests**.

## [2.1.36] - 2026-10-11 - Financial-integrity + fail-closed approval fixes (delegation findings)

### Security — Financial truth
- **A wallet balance is no longer bookable as payout revenue (finding F4, HIGH).**
  `PayoutVerifier.verify_crypto` had a "best-effort" branch for when only the
  current balance was available: `verified = current >= expected` with
  `observed_usd = current`. That is a solvency check reported as a payment
  measurement, and it booked the wallet's **entire balance** as revenue.
  Reproduced by execution before the fix: a wallet already holding **$500** and
  a **$5** expected payout produced
  `VERIFIED / L5_CRYPTOGRAPHIC / amount = 500.0` — **$495 of invented revenue at
  the highest trust level**. `evidence_factory` maps `onchain_balance_delta`
  straight to L5, so nothing downstream could catch it; `main.py:1711` (the
  operator payout path) calls it with no snapshots, and the inflated accept fed
  `submission_ramp.record_accept` — the counter that unlocks auto-submission.
  - Both `before_bal_usd` and `after_bal_usd` are now **required**. A missing
    snapshot returns an explicit unverified result; the booked amount is always
    the true `after - before` delta, never the absolute balance. Fails closed:
    the lifecycle will not flip to `paid` and the ramp gets no accept.
- **`get_verified_revenue` / `get_total_expenses` now use `get_profile`'s rule
  (F6, LOW-latent).** They accepted any affirmative status at any level, so an
  L1 `manual_attestation` counted as verified revenue there while `get_profile`
  reported 0 for the same record — two authorities disagreeing. Both now require
  `status == VERIFIED and verification_level >= L3`. Neither had a caller, so
  this was a trap rather than a live leak.

### Security — Fail closed on missing dependencies
- **`EarningCapabilityExecutor` no longer skips human gates (F2, MEDIUM).**
  The gate block was wrapped in `if gate_manager is not None:` and
  `human_gates=None` is the **constructor default**, so any caller that forgot
  to wire a gate manager got a silently ungated submission. Now blocks with
  `await_approval` — an unassessable task is not an approved task.
- **`PlatformSubmitter.request_approval` no longer auto-approves (F3, MEDIUM).**
  With no `safety_guard` it set `status="approved"` / `mode="auto"`, and
  `gui/tabs/earning_tab.py` constructs `PlatformSubmitter()` with no guard — so
  the default configuration turned "approval" into a no-op. Now returns
  `blocked` / `mode: "no_guard"`.

### Fixed — persona text
- **A stripped tool name no longer leaves a dangling `,` or `:` (QA finding).**
  Rule 5a removed the name but not its separator, so `"web_read, then I will
  assess"` rendered as `"I need data. , then I will assess"`. The separator that
  belonged to the stripped token is now consumed with it.

### Tests — silent passes replaced with real assertions
- `test_live_end_to_end_toggle` used a bare `return` when llama-server was
  unreachable — it reported **green while asserting nothing**. Now a real
  `pytest.skip`, so the suite honestly shows it did not run (visible as the
  2→3 skip-count change).
- `test_blockchain_receipt_factory` was `pass  # covered structurally below`.
  Now asserts the receipt→evidence mapping, including that an UNVERIFIED report
  cannot produce VERIFIED evidence.
- `test_apply_slot_statuses_ignores_out_of_range` called two methods with
  `# Must not raise` and no assertion. Now also asserts the out-of-range row
  created no state and that an in-range status still applies.
- `test_burst_capacity_instant` did five bare `acquire()` calls — it passed even
  if every acquire blocked for a second. Now asserts the fake clock did not
  advance during the burst. Verified the assertion has teeth: the 6th acquire
  blocks for a real 1.00s.

### Verification
- New `tests/evidence/test_crypto_payout_snapshot_gate.py` (8 tests).
  **Negative control:** restoring the original best-effort branch fails 3 of 8,
  including `"unverifiable crypto must not reach verified_revenue"`.
- F4 reproduction probe before/after: booked **$500 → $0**. Genuine-delta probe:
  a $5 payout on a $1005 wallet still verifies and books exactly $5.00; a $5
  gain does not verify a $100 expectation; all four partial-snapshot
  combinations book $0.
- Full suite: **1279 passed, 3 skipped, 77 subtests**.

## [2.1.34] - 2026-10-11 - Bound Live transport retries + document the real submission gate

### Fixed
- **Live mode could no longer spin forever on an unreachable model.**
  `_record_live_failure()` returned `True` unconditionally, so a transport
  failure ("could not reach its model") made Live re-schedule itself every 3 s
  *indefinitely* — no cap, no exit, one identical system line appended per
  attempt. A dead llama-server, an unloaded model, or a wrong port therefore
  produced an endless retry loop that only a manual Stop could end. Every
  sibling recovery path in the same handler is budgeted (the semantic-duplicate
  path uses `budget = 3` and pauses); this one was the outlier.
  - New `_LIVE_TRANSPORT_FAILURE_BUDGET = 8`: Live still tolerates a generous
    run of consecutive failures, because it IS a recovery session and a
    transient llama-server restart must not end it. Past the budget it pauses
    itself via `stop_live()` with an actionable message ("check that the
    selected provider is running and a model is loaded") instead of rescheduling.
  - The counter already resets on any accepted turn, so a flapping provider
    that eventually answers keeps the session alive — the budget only trips on
    *consecutive* failures.
  - Non-Live (goal-driven) mode keeps its original single-retry contract and
    never calls `stop_live()`.

### Documentation
- **`AutonomousLoop._stage_request_approval` no longer reads like the only
  human gate.** A security review read its `advertised_amount > 100.0` check
  and concluded sub-$100 opportunities execute and submit with no human
  decision. That conclusion is wrong, and the reason it was reachable is that
  the boundary was undocumented. The stage's docstring now states its real
  scope (a financial-exposure pause) and names the gate that actually protects
  a submission: `agents/earning/proposal.py` → `SubmissionRamp.requires_human`,
  which fails closed on cold-start, on a low win-rate, and whenever the
  platform's AI policy is not `ai_allowed`. The stage's `data` payload now
  carries `scope` and `submission_gate` so the audit trail says the same thing.

### Verification
- New `tests/dialogue/test_live_transport_budget.py` (6 tests): budget is
  finite and generous; Live survives in-budget failures; Live pauses once the
  budget is spent; the over-budget failure returns `False` so the caller's
  `if retry:` gate never re-arms; a successful turn resets the counter;
  non-Live mode is unchanged.
  - **Negative control:** emulating the old unconditional `return True` makes
    2 of the 6 tests fail (`True is not false : the over-budget failure must
    not ask for another retry`).
- New `tests/earning/test_submission_gate_boundary.py` (5 tests), each verified
  by execution against the real proposal path: a $25 Upwork opportunity routed
  through the loop's submit path with **no** `confirm_cb` never reaches the
  platform client on cold-start; a low win-rate blocks even with 10
  submissions; `ai_disallowed`/`human_only` override a warm ramp; and the one
  auto-submit path is reachable only through reputation + policy, never through
  the dollar threshold.
  - These tests force a fresh ramp singleton per test: `get_ramp` memoizes one
    instance and only adopts a memory while `_memory is None`, so
    `test_group3_honesty`'s temp DB (deleted in its tearDown) otherwise leaked
    into this module and made results order-dependent.
- Regression check `tests/dialogue tests/gui`: 391 passed, 2 skipped.
- Full suite: **1272 passed, 2 skipped, 77 subtests**.

## [2.1.33] - 2026-10-11 - Derive the persona tool-strip list from the canonical registry

### Changed
- **`_remove_tool_syntax` no longer carries a hand-typed copy of the tool
  registry.** `agents/safety/response.py` decided which bare tool names leak
  into persona bubbles using its own string literal of 17 names, while
  `agents/safety/gate.py` is documented as the single source of truth for which
  tools exist. The two lists **did agree at the time of this change** (verified:
  17 literal names, 0 missing from the registry, 0 extra), so this is a **latent
  duplication hazard, not a live defect** — the same hazard `safety_gate`
  explicitly warns about, and the class of drift that produced five consecutive
  releases of tool-name-leak fixes (v2.1.27–v2.1.31).
  - New `_tool_name_pattern()` derives the alternation from
    `READONLY_TOOL_NAMES | MUTATING_TOOL_NAMES`, longest-first so a prefix
    cannot shadow a longer name. A tool added to the registry is now stripped
    the moment it is registered.

### Verification
- New `tests/safety/test_tool_syntax_strip_registry.py` (5 tests): the pattern
  covers every registered tool; it invents no unregistered name; the module
  source contains no duplicated literal list of 4+ tool names; every registered
  tool strips as bare/`[]`/trailing; real prose mentioning a tool is preserved.
- Behaviour is byte-identical on every known case: 14 leak forms
  (`|`/`;`/`,`/blockquote/`.`/`()`/`**`/`->`/`and`-joined/`:`/run/`[]`/`()`/
  bare/trailing) all strip to `""`, and 6 prose controls
  ("I'll use web_read.", "The web_read tool returned…", the multi-line
  `$80.\nweb_search would not have helped here.` case, …) are unchanged.
- **Negative control:** injecting a hypothetical `brand_new_tool` into the
  registry makes `_remove_tool_syntax("brand_new_tool | web_read")` strip it
  (`""`), where the pre-change build returned it verbatim — proving the
  derivation is live, not decorative. A second control shows the old
  hand-typed-list approach fails to strip a name it omits.
- Safety + dialogue suites: 342 passed, 2 skipped, 77 subtests.

## [2.1.32] - 2026-10-11 - Single-source the release version (kill the v2.1.1 prompt drift)

### Fixed
- **The brains were told they were running v2.1.1 while the app was at v2.1.31.**
  `ProgramKnowledge.PROGRAM_VERSION` was a hand-maintained string literal that
  had not been touched since v2.1.1 — roughly 30 releases. Because
  `KnowledgeContext.build_context()` prepends
  `# MrBot1000 v{PROGRAM_VERSION}` to the injected context, and both
  `driver`/`navigator` personas feed that into their system prompt, **every
  Dialogue turn prompted both models with a false self-version**. Verified
  before the fix: `persona.build_system_prompt()` and
  `persona.memory_context()` both returned `# MrBot1000 v2.1.1` while
  `app/version.py` (the authority, and the value in the window title) was
  `2.1.31`. A model mis-reporting its own build to the operator is a
  self-consistency defect, not just cosmetic.
  - `PROGRAM_VERSION` now imports `VERSION` from `app/version.py` (with a
    static last-resort literal in the `except` branch).
  - The root `__init__.py` `__version__` duplicate — also stale at `2.1.1` —
    now re-exports `app.version.__version__`.
  - The unreachable fallback literals in `main.py` (window title) and
    `agents/evidence/evidence.py` (evidence `producer_version`) were refreshed
    from `2.1.1` to the current release so a future fallback cannot silently
    stamp stale lineage onto exported financial evidence.
- **Documentation drift corrected.** `README.md` (title, `app/version.py` table
  row, CHANGELOG pointer) and `Agent.md` (`Version:` identity field) still
  advertised **v2.1.5** — 26 releases behind. Now `2.1.32`. The README
  "Highlights" heading no longer pins itself to one old release.

### Verification
- New test `tests/runtime/test_version_single_source.py` (5 tests) asserts
  `ProgramKnowledge.PROGRAM_VERSION`, the root package `__version__`, the
  persona system-prompt header, and the memory-context header all equal
  `app.version.__version__`.
- **Negative control:** reverting `program_knowledge.py` to the committed
  `"2.1.1"` literal makes 3 of the 5 tests fail
  (`'2.1.1' != '2.1.32'`), proving the tests detect the real defect and not
  just the unreachable fallback.
- Post-fix probe: both personas and `memory_context()` emit `# MrBot1000
  v2.1.32`; import sweep of `big_brain`, `small_brain`, `program_knowledge`,
  `cognition.personas` clean.
- Targeted suite `tests/runtime/test_version_single_source.py`: 5 passed.

## [2.1.31] - 2026-10-11 - Strip decorated tool-only lines + fix newline-crossing over-strip

### Fixed
- **Every tool-only line now strips; no leak form remains.** A probe of
  `_remove_tool_syntax` (22 leak forms x 6 prose controls) found that v2.1.30
  still let nine leak shapes reach the persona bubble, because the strip only
  recognised whitespace-separated runs of bare tool names:
  | leaked form | previously | now |
  |---|---|---|
  | `web_read \| web_search` | leaked | stripped |
  | `web_read; web_search` / `,` | leaked | stripped |
  | `> web_read` (blockquote) | leaked | stripped |
  | `web_read.` / `!` / `?` | leaked | stripped |
  | `(web_read)` / `**web_read**` | leaked | stripped |
  | `web_read ->` | leaked | stripped |
  | `web_read and web_search` | leaked | stripped |
  A line whose only words are tool names is never a real sentence, so rule 5d
  now strips any line that consists solely of tool names plus decoration or
  join words (`and`/`then`/`or`/`also`/`plus`/`now`/`next`). A line that still
  holds any other letter is real prose and is left intact.
- **Rule 5b accepts punctuation separators.** A run of 2+ bare tool names is
  now matched when separated by `|`, `;` or `,` as well as whitespace.
- **Over-strip defect fixed (pre-existing, shipped in 2.1.30).** Rule 5c's
  separator was `\s+`, which crosses a newline — so a tool name legitimately
  opening the NEXT line of a real answer was deleted: `"I read the page with
  web_read and the payout was $80.\nweb_search would not have helped here."`
  lost its `web_search`. The separator is now `[ \t]+`. A leaked bare name
  always trails its punctuation on the same line, so nothing was lost.

### Deliberately preserved
- Verb-object prose is NOT stripped: `"I'll use web_read."`,
  `"Using web_read and web_check."`, `"I used web_search to find…"`,
  `"The web_read tool returned…"`, `"The web_read results show…"`. The 2.1.30
  design decision stands — mangling a real answer is worse than the rare
  ambiguous leak, which the narrated-intent rejection still catches.

- **False-rejection retry loop fixed (pre-existing, found by the second-pass
  probe).** `_is_bad_dialogue_response`'s external-claim tuple held the bare
  phrases `"confirmed the"` / `"confirmed that"`, so it rejected **every**
  first-person confirmation — including the tool-grounded report the tool-first
  rule *requires* (`"Using web_read and web_check, I confirmed the $80
  bounty."`). Because each rejection re-prompts, a persona that did the right
  thing (call the tool, then report what it found) was trapped in exactly the
  infinite human-step / retry loop the operator previously reported. The bare
  phrases are removed and replaced by an **external-subject** regex
  (`they/the platform/the client/the listing … confirmed that|the|…`), which
  keeps the real protection — an unverifiable third-party confirmation is still
  rejected — while letting the persona state its own verified finding.

### Verification
- New `test_decorated_tool_only_lines_are_stripped`: 12 leak shapes → `""`.
- New `test_tool_only_strip_does_not_mangle_real_prose`: 7 prose controls
  (incl. the multi-line newline case) survive byte-identical.
- New `test_first_person_tool_grounded_confirmation_is_not_rejected`: 4
  first-person confirmations kept, 9 unverifiable external confirmations still
  rejected (all 9 verified individually before the test was written).
- Second-pass probe: parser still fires on all 7 real call shapes (incl. one
  wrapped in `**...**` and one after an arrow); all 7 tool-only turns still
  rejected; a tool-only line inside a real multi-line answer is removed in
  place without touching the surrounding text.
- Full suite: **1251 passed, 2 skipped, 77 subtests** (was 1248 before this
  change).

## [2.1.30] - 2026-10-11 - Strip bare tool names in remaining leak positions

### Fixed
- **Bare tool names in colon/comma-suffixed, run-of-tools, and post-sentence
  positions no longer leak into persona text.** A probe of `_remove_tool_syntax`
  found three forms still escaping: `web_read:` (colon), `web_search web_read
  web_check` (several bare names inline), and a bare name right after
  sentence-ending punctuation. The strip now removes a tool name in these
  unambiguous leak positions. It deliberately does NOT strip a tool name that is
  the object of a verb ("use web_search to…") or the noun in "the web_read tool
  returned" — those are legitimate prose and mangling them is worse than the rare
  ambiguous mid-sentence leak (which the narrated-intent rejection still catches).

### Verification
- New test `test_bare_tool_name_in_leak_positions_is_stripped`: colon/run/post-
  sentence forms stripped; "use web_search to…" and "the web_read tool returned"
  preserved.
- Second-pass probe: no leak form remains. Dialogue + cognition + safety +
  runtime: 530 passed, 2 skipped.

## [2.1.29] - 2026-10-11 - Fix small-brain tool channel: explicit call format + budget ordering

### Fixed
- **Small brains now call tools instead of narrating them.** Root cause: the small
  brain budgets its system prompt to the 4000-char "fast" mode with a naive HEAD
  truncation, which cut off the tool-format examples (`web_read("url")`) that sat
  at the tail of the persona contract. So the small model only heard "you MAY call
  web_read" with no syntax and emitted bare `web_read` / `web_read[]` — which
  `_parse_tool_call_from_text` couldn't parse, so the call never executed and the
  tool name leaked as prose.
  - The dialogue-mode block now carries an **exact call-format example**
    (`web_read("https://…")` / `web_search("query")`, "put the URL/query inside the
    quotes; a bare tool name does nothing") in both brains.
  - `enforce_prompt_budget` is applied to the **base** prompt (identity + memory)
    **before** the dialogue tool instructions are appended, so the format is never
    truncated away.
- **Parser recovery for degenerate calls.** `_parse_tool_call_from_text` now also
  recognizes a bare tool name followed by the URL/query on the same or next line
  (`web_read\nhttps://…`, `web_search\nthe query`) as a real call, so a compact
  model that still omits quotes still gets its tool executed. Narrated intent with
  no URL/query still does not parse (and is rejected upstream).

### Verification
- New test `test_bare_tool_name_with_url_is_parsed_as_a_call`: bare-name+URL parses
  (same/next line, read + search); narrated intent without URL does not parse.
- Dialogue + cognition + safety: 352 passed, 2 skipped.

## [2.1.28] - 2026-10-11 - Strip empty-bracket tool artifacts + reject narrated read-intent turns

### Fixed
- **Empty-bracket tool artifacts (`[]`, `web_read[]`, `web_read()`) no longer
  leak into persona bubbles.** Local models emit a tool name with empty/no args
  (e.g. `web_read[]`) as their whole turn or trailing token. `_remove_tool_syntax`
  now also strips `tool()`, `tool[]`, and orphaned `[]` / `()` left after a
  stripped call, in addition to the bare-name and `tool(...)` forms.
- **Narrated read/search intent that never calls the tool is rejected.** Turns
  like "I'll read the opportunity page before proceeding.[]", "Let me try reading
  the page using the web_read tool…[]", or "Let me read the uGig page directly.[]"
  announce a read/search but carry no tool result — they tried to emit the call
  as prose. `_is_bad_dialogue_response` now flags a future/present read/search
  intent ("I'll/let me/I will … read/search/check", incl. gerunds and up to two
  intervening words like "try reading") that ALSO leaks a tool artifact
  (`web_read tool` / `[]` / bare trailing tool name), so the retry path forces a
  real answer or a real tool call. Legitimate past-tense findings ("I read the
  page and found…") and prose merely mentioning a tool are preserved.

### Verification
- All 6 narrated-intent leak forms from the live run rejected; all 5 legitimate
  answers kept; empty-bracket forms stripped cleanly.
- Dialogue + cognition + safety + GUI smoke: 363 passed, 2 skipped. (`.env` md5
  shift is the pre-existing `test_settings_round_trip_through_sync_slots` writing
  operator config — unrelated to this change.)

## [2.1.27] - 2026-10-11 - Strip bare tool-name leaks from Dialogue persona text

### Fixed
- **Bare tool names no longer leak into persona bubbles.** Local models were
  emitting a bare tool name (`web_search`, `web_read`) with no parentheses as
  their whole turn or as a trailing token — `_remove_tool_syntax` only stripped
  `tool(...)` calls, so Edward's entire "response" could be just `web_search`
  and several replies ended with a dangling `web_read`. `_remove_tool_syntax`
  now also strips a tool name that stands alone on its own line or as a trailing
  token, while preserving prose that merely mentions a tool name mid-sentence.
- **An all-tool-syntax turn is rejected, not shown as an empty bubble.**
  `_is_bad_dialogue_response` strips tool syntax first; if nothing
  persona-visible remains, the turn is rejected so the retry path re-prompts for
  a real answer instead of displaying an empty response.

### Verification
- New regression test `test_bare_tool_name_response_is_stripped_and_rejected`
  (standalone + trailing stripped; mid-sentence prose preserved; all-tool turn
  rejected; real answer kept).
- Dialogue + cognition + safety + GUI smoke: 363 passed, 2 skipped; `.env`
  unchanged.

## [2.1.26] - 2026-10-11 - Keep visible llama-server consoles open for every brain

### Fixed
- **Visible server consoles no longer close after the model finishes loading.**
  On Windows a `CREATE_NEW_CONSOLE` child's console window is tied to the
  `Popen` handle. The launch worker held that handle and was later
  `deleteLater`'d on `finished`, which closed the handle and tore down the
  visible console even though the llama-server kept running (seen on the CPU/RAM
  slot, and latent for slots 0/1). `BrainLaunchWorker` now **hands the spawned
  `Popen` to the backend and drops its own reference** on every success path
  (ready / probe-confirmed / slow-start). The backend retains `proc` for
  stop/terminate, so the console stays visible through loading and token
  generation for ALL brains and still closes when you press Stop.
- `stop()` on a finished worker is now a safe no-op after the handoff (the
  backend owns the process), so stopping never double-terminates or closes a
  console the operator is watching.

### Verification
- Handoff contract unit-checked: worker releases `_proc` on success; the emitted
  proc is the spawned Popen; `stop()` after handoff does not terminate.
- Slot-lifecycle suite 22 passed; broader gate 325 passed; `.env` md5 unchanged.

## [2.1.25] - 2026-10-11 - N-brain lifecycle + dialogue-loop fixes (live-test findings)

### Fixed
- **"Start All Brains" now launches every enabled device.** `_on_start_all` iterates
  all runtime slots (0/1 via the Big/Small handlers, 2+ via `_start_slot`) instead of
  only the two primary llama servers, so the CPU/RAM brain (and any extra GPU) starts
  with the button. Falls back to the legacy 2-brain fast path when ≤2 slots.
- **Extra-slot status no longer stuck "Stopped" after a manual start.**
  `_on_slot_launched` now schedules `_schedule_slot_reprobe` — a bounded ~3-min
  re-probe that flips the row Stopped → Running once the just-launched server answers
  /v1/models (mirrors the existing slots 0/1 reprobe contract).
- **Reasoning-about-the-prompt loops are rejected.** A model stuck re-verifying its own
  reply against the phase contract ("I will output it. Wait, the prompt says…") varies
  a trailing clause each cycle and slipped past the old exact-duplicate checks.
  `_is_bad_dialogue_response` now flags: a sentence recurring 3+ times, a near-duplicate
  sentence core recurring 4+ times, and meta-reasoning cues ("wait, the prompt says" /
  "i will output it" / "one minor adjustment" …) recurring 3+ times. Clean multi-
  sentence replies are NOT flagged.

### Verification
- 2 new slot-lifecycle tests (start-all starts every enabled slot; slot launch
  schedules a reprobe) + 2 new corruption tests (prompt-reasoning loop rejected; clean
  reply not flagged).
- Loop detector checked against the real Edward loop (flagged) and two clean replies
  (not flagged).
- Dialogue + cognition suite: 288 passed.

### Note
- Pre-existing, unrelated: building a `DualBrainControl` in tests writes the real `.env`,
  which the conftest teardown flags (affects every widget-building test in
  `test_slot_lifecycle.py`, not just the new ones). Left as-is — out of scope here.

## [2.1.24] - 2026-10-11 - N-brain Dialogue migration COMPLETE (Phase 6: cleanup + gate)

### Summary
The Dialogue layer is fully migrated from the fixed Edward(DRIVER)/Jacob(NAVIGATOR)
ping-pong to a **shared-skills peer council** that scales to N detected devices:

- **Shared skillsets, distinct names.** Every big-tier device runs the SAME earning-agent
  skillset (Edward's skills), differing only by name; every small-tier device runs the
  SAME helper/support skillset (Jacob's skills), differing only by name. Names are
  data-driven (non-famous-person pools) and customizable per device in the Management
  tab (`BRAIN_SLOT{n}_NAME`).
- **Peer deliberation.** Each brain gets a team brief listing its peers (name · tier ·
  device) and the rule to read teammates' thoughts + tool-calls and add its own
  perspective. Big brains are peers (propose/plan/verify/challenge); small brains are
  support (verify/challenge/propose) — not a driver/navigator hierarchy.
- **N-device UI.** The speaker/reply selectors, header, and agent-runtime descriptors
  all list every enabled device with its device label; turn advancement is round-robin.
- **Back-compat preserved end-to-end.** With 1 big + 1 small the roster is exactly
  Edward + Jacob and every path reduces to the legacy big/small behavior; the 243
  pre-existing dialogue tests stayed green throughout.

### Verification
- Full gate: 476 passed, 2 skipped (runtime + dialogue + cognition + GUI smoke +
  personas); N-brain GUI suite 52 passed.
- Fresh-clone verification at HEAD: dialogue + cognition 286 passed, 2 skipped.
- Remaining hardcoded edward/jacob/Driver/Navigator references are intentional legacy
  fallbacks for the no-roster case only.

## [2.1.23] - 2026-10-11 - N-brain Dialogue Phase 5: team brief + shared-skills personas + generalized LIFECYCLE

### Added
- **Team brief** (`speaker_registry.build_team_brief`): a compact peer-council block
  injected into each brain's system prompt listing the other enabled participants
  (name · tier · device) + the peer-deliberation rule ("read teammates' latest
  thoughts + tool-call results, then add YOUR OWN perspective — agree, refine, push
  back, or call your own tool; converge on ONE action; say UNKNOWN/BLOCKED instead of
  inventing agreement"). Empty for the single-brain case (no behavior change).
- **`build_system_prompt(team_brief=…, name_override=…)`**: the team brief is injected
  into the full-tier prompt; `name_override` lets a shared-skills peer speak as its own
  name (e.g. big-tier "Rowan Vale" gets Edward's earning skillset but its own IDENTITY).

### Changed
- **Shared-skills persona resolution** in the Dialogue respond path: an extra big-tier
  brain resolves to the DRIVER (earning-agent) skillset and a small-tier brain to the
  NAVIGATOR (helper/support) skillset — differing only by name. Falls back to name
  lookup for the primary Edward/Jacob pair.
- **Generalized LIFECYCLE** (`_current_phase_speaker`): each phase is owned by a TIER
  (big proposes / small gates) resolved to the next speaker of that tier via a per-tier
  cursor (so multiple big brains rotate). With 1 big + 1 small it's exactly the classic
  Edward⇄Jacob alternation; no roster → legacy Driver/Navigator names.

### Verification
- 11 new tests (team brief single/multi/2-brain; shared-skills persona identity + own
  name; team brief injected; tier resolution; 2-brain alternation; legacy fallback;
  multi-big rotation within tier).
- Full dialogue + cognition suite: 286 passed, 2 skipped.

## [2.1.22] - 2026-10-11 - N-brain Dialogue Phase 4: multi-party routing

### Changed
- **Turn advancement is round-robin over the roster.** The auto-run turn hand-off
  (`_on_response_ready`) and manual persona hand-off (`on_send`) now call
  `_next_speaker_after(speaker)` instead of the fixed `_SMALL if speaker == _BIG else
  _BIG`. With N brains the turn cycles through every enabled device (wraps); with 1
  big + 1 small it's the classic Edward⇄Jacob alternation.
- **Agent runtime builds one descriptor per enabled device** (`_create_agent_runtime`):
  uses each speaker's registry key + display name. Roles follow the shared-skills
  peer-council model — big = "peer" (propose/plan/verify/challenge), small = "support"
  (verify/challenge/propose) — replacing the driver/navigator hierarchy. Falls back to
  the classic edward(driver)/jacob(navigator) pair when the roster is unavailable.
- **Dialogue persistence is per-speaker key** (`_persist_dialogue_turn`): a persona turn
  logs to that speaker's registry brain key; a Human turn logs + evolves every enabled
  brain. Reduces to the legacy big/small behavior for 2 brains.

### Verification
- 6 new routing tests (one descriptor per speaker + peer/support roles; legacy
  driver/navigator fallback; 4-speaker round-robin + wrap; 2-brain alternation;
  persona persistence uses registry key; Human persistence hits all brains).
- Full dialogue + agent-runtime suite: 265 passed, 2 skipped.

## [2.1.21] - 2026-10-11 - N-brain Dialogue Phase 3: speaker/reply selectors reflect every enabled device

### Changed
- **Dialogue speaker + reply selectors now list every enabled brain** (not just
  Edward/Jacob). `speaker_combo` = Human + one entry per enabled device; `reply_combo`
  = one entry per enabled device. Each item shows `name · device` (e.g. "Edward Hurst ·
  NVIDIA GeForce RTX 5060 Ti") while storing the exact NAME in UserRole so name
  resolution stays exact (`_combo_speaker_name`). The header lists all enabled
  speakers with their devices.
- **Round-robin turn hand-off** (`_next_speaker_after`): when a persona speaks
  manually, the turn passes to the next enabled speaker in roster order (wraps). The
  2-brain case is the classic Edward⇄Jacob alternation.

### Verification
- 6 new selector tests (Human + every brain; device labels in combo text; exact name
  resolution; header lists all; round-robin + wrap).
- Headless: 3-device box → speaker_combo has 4 items (Human + 3 brains), reply_combo
  3, each with device label; header lists all three.
- Full dialogue suite: 255 passed, 2 skipped.

## [2.1.20] - 2026-10-11 - N-brain Dialogue Phase 2: brain/tier resolution via speaker registry

### Changed
- **DialogueTab resolves brains + tiers through the speaker registry.** The 7
  hardcoded `brain = self.big_brain if speaker == _BIG else self.small_brain`
  sites (and the `_tier_for_brain(speaker == _SMALL, …)` tier sites) now call
  `_brain_for(speaker)` / `_tier_for_speaker(speaker)`, backed by a per-device
  speaker roster built from the runtime slots. Slots 0/1 map to the big/small
  adapters; a 3rd+ speaker resolves its adapter lazily (big→BigBrainAdapter,
  small→SmallBrainAdapter). The agent-runtime turn key uses the speaker's registry
  key (`big_brain`/`small_brain`/`brain_slot{n}`) instead of the hardcoded
  "edward"/"jacob".
- **Back-compat preserved:** with 1 big + 1 small the roster yields exactly Edward +
  Jacob and every lookup reduces to the legacy big/small behavior. Helpers are
  defensive against `__new__`-constructed test objects (missing `_speakers` /
  adapters) so they fall back to the legacy adapters.

### Verification
- 6 new resolution tests (primary names → correct adapter/tier; 3rd speaker
  resolves lazily + correct tier; unknown name falls back; roster-absent is safe;
  registry key for 3rd speaker).
- Full dialogue suite: 249 passed, 2 skipped (unchanged back-compat).

## [2.1.19] - 2026-10-11 - N-brain Dialogue Phase 1: speaker registry + per-device name editing

### Added
- **Speaker registry** (`agents/cognition/speaker_registry.py`): maps each enabled
  runtime slot to a `Speaker` (distinct NAME + TIER "big"/"small" selecting the shared
  skillset/prompt). Slots 0/1 keep Edward (big) + Jacob (small); each additional big
  device gets the next big-tier name, each additional small/CPU device the next
  small-tier name, from data-driven pools (Rowan Vale, Sienna Cross, … / Pip Marlowe,
  Juno Reyes, …). Names overridable via `BRAIN_SLOT{n}_NAME` (and legacy
  `BIG_BRAIN_NAME`/`SMALL_BRAIN_NAME`); uniqueness enforced. This is the N-brain
  foundation for the shared-skills peer-council Dialogue model (see
  `.hermes/plans/2026-10-11_n-brain-dialogue-migration.md`).
- **Per-device name editing in the Management tab.** The "Persona Names" section now
  shows one name field per enabled device (device label + tier in the label), built
  from the speaker registry, instead of the fixed two Edward/Jacob fields. Slots 0/1
  persist to the legacy keys; slots 2+ persist to `BRAIN_SLOT{n}_NAME`.

### Verification
- 14 new speaker-registry tests (Edward/Jacob defaults, per-tier name pools, no
  famous-person names, env override, legacy keys, uniqueness, lookups, ping-pong order).
- Headless: Management tab renders 3 name fields (Edward/Jacob/CPU) with correct env
  keys + device labels.
- Dialogue suite unchanged: 243 passed, 2 skipped. GUI smoke + cognition: 27 passed.

## [2.1.18] - 2026-10-11 - Consolidated llamacpp Settings: removed duplicate top editors, unified per-device rows

### Changed
- **Removed the duplicate hardcoded two-brain Settings editors.** The llamacpp
  Settings panel previously showed a per-brain grid for Big + Small at the top
  AND the per-device rows at the bottom — duplicated context/gpu-layers/threads/
  batch/KV/split/temperature controls. The top grid is gone; the bottom
  "Per-Device Settings" rows (one per enabled device, incl. CPU/extra GPUs) are
  now the single source of truth.
- **Legacy wiring preserved via aliasing.** The launch snapshot,
  `_snapshot_settings_values`, temperature presets, and hardware presets all read
  the `sb_*`/`bb_*` widget attributes. Those attributes are now aliased to the
  bottom rows' controls (Small=slot1, Big=slot0) in `_alias_legacy_settings_attrs`,
  re-applied on every rebuild, so all existing persistence/launch/preset behavior
  is unchanged. Model selection stays in Provider Control; `_current_model_path`
  falls back to the runtime config when the (now-removed) Settings model combo is
  absent.
- The hardware-preset row (preset + target + Apply) is kept at the top of the
  Settings group and drives the unified per-device rows.

### Verification
- Headless: top block gone; 3 per-device settings rows render; legacy `sb_*`/`bb_*`
  aliases resolve to the bottom rows; `_snapshot_settings_values` (18 keys),
  `_current_model_path` fallback, and per-device context edit all work.
- Runtime + N-brain GUI + worker: 231 passed. Remaining GUI: 48 passed. Dialogue:
  243 passed. compileall clean.

## [2.1.17] - 2026-10-11 - Editable per-device llama.cpp settings for every enabled device

### Fixed
- **Every enabled device now has editable llama.cpp settings (was only the two
  role brains).** The llamacpp Settings panel showed full controls only for the
  Big/Small GPU brains; the CPU/RAM and any extra-GPU device had no way to change
  context, threads, batch, KV, split, etc. New reusable `BrainSettingsRow` widget
  (`gui/widgets/brain_settings_row.py`) renders one editable row per runtime slot
  in the "Per-Device Settings" section — context, GPU layers, threads, batch, KV
  cache, split mode, temperature — for ALL devices. CPU/RAM rows lock GPU layers
  to 0 (system-RAM only) and disable that control.
- **Per-device settings persist and round-trip.** Slots 2+ (no .env keys) persist
  their settings to the device policy (`settings.json` → `devices.settings`, keyed
  by stable device id); `sync_slots` re-adopts them on load via
  `_apply_saved_settings`. Changes apply off-thread so the GUI never blocks.

### Verification
- 11 new `BrainSettingsRow` tests + 4 new per-device-settings tests (every slot
  has a row; CPU locks GPU layers; context change applies + persists; settings
  round-trip through `sync_slots`).
- Runtime + N-brain GUI + worker: 231 passed. Remaining GUI: 48 passed. Dialogue:
  243 passed. compileall clean.
- Headless: 3 settings rows render (5060 Ti, 1660 Super, CPU); CPU gpu_layers
  locked/disabled; context edit on CPU applies to slot config + persists +
  round-trips.

## [2.1.16] - 2026-10-11 - Per-device status fix, single model picker, hardware-aware prompts

### Fixed
- **CPU/extra-device row no longer stuck at "Checking...".** The provider-status
  probe only updated slots 0/1 (Big/Small), so a 3rd enabled device (CPU/RAM)
  stayed at its initial "Checking..." forever. The probe now emits per-slot
  results for EVERY slot and `_apply_slot_statuses` updates all Provider Control
  rows. Rows also initialize to "● Stopped" (the correct resting state when
  auto-start is off) instead of "● Checking...".
- **Model selection consolidated into Provider Control.** The llamacpp Settings
  panel no longer shows a second model dropdown per brain — it shows a
  "Model: set in Provider Control ↑" note. Provider Control's per-device
  dropdown is now the single place to pick a model for any device. The hidden
  Settings combo is kept as the slots 0/1 persistence backing store and stays in
  sync (`_set_settings_combo_model`) so `.env` round-trips unchanged.
- **llamacpp Settings shows all detected devices.** The "Detected Brains" summary
  lists every enabled slot (device, role, port, context, model), matching the
  Compute Devices panel.

### Changed
- **Brain prompts now reflect the ACTUAL detected hardware.** Both brains inject
  a "# YOUR HARDWARE" section resolved live from the device registry (e.g.
  "You run on NVIDIA GeForce GTX 1660 SUPER (6 GB · SM 7.5)"), so a brain knows
  its real card and can reason about its own capacity. Never hardcoded; falls
  back gracefully when detection is unavailable.

### Verification
- 4 new status tests (initial Stopped not Checking; per-slot probe updates all
  rows; running-state buttons; out-of-range slots ignored).
- 4 new hardware-prompt tests (section present; reflects detected device names).
- Dialogue 243 passed; runtime + N-brain GUI + worker 209 passed; remaining GUI
  48 passed. compileall clean.

## [2.1.15] - 2026-10-11 - Per-device model selection + full settings save + off-thread tab DB reads

### Fixed
- **Model selection now works for EVERY device (was only the two role brains).**
  Each Provider Control row's static "Model: —" label is replaced by a real
  model dropdown (`BrainControlRow.model_combo`) populated with discovered local
  .gguf files, so the CPU/slot-2+ brain can pick a model just like the GPUs.
  Picking a model sets that slot's `BrainConfig.model` and persists to the
  device policy (`settings.json` → `devices.models`, keyed by stable device id)
  so it round-trips across restarts; slots 0/1 also keep their .env
  BIG/SMALL_BRAIN_MODEL. `sync_slots` re-adopts a device's saved model on load.
- **Save settings fully wired per device.** The per-device model choice is
  persisted (off-thread) on change and on "Save Local Provider Settings", not
  just for slots 0/1. A legacy `_ModelLabelAdapter` keeps the backend's
  `sb_model_label.setText()` calls working by selecting the model in the row's
  dropdown.

### Changed
- **GUI responsiveness: polled tab DB reads moved off the GUI thread.** The
  Self-Improvement, Autonomous Learning, and Social Activity tabs poll a SQLite
  table every 5s via the RefreshCoordinator, doing `sqlite3.connect` + query
  synchronously on the GUI thread — a recurring micro-freeze on those tabs. New
  `gui/workers/db_query_worker.py` (`DbQueryWorker` / `run_db_query`) runs the
  read-only SELECT on a background QThread and delivers rows back through a
  signal, so the GUI thread only touches widgets. All three tabs converted.

### Verification
- 3 new per-slot model-selection tests (every row has a dropdown; slot-2 pick
  sets config + persists to policy; dropdown signal routes to the handler).
- 5 new `DbQueryWorker` tests (rows, missing-db error, bad-SQL error, bound
  params, async GUI-thread delivery).
- Headless: all 3 Provider Control rows show a 32-option model dropdown.
- Runtime + N-brain GUI + worker suites: 209 passed. Remaining GUI: 48 passed.

## [2.1.14] - 2026-10-10 - N-brain architecture Phase 1-6: slot store, control row, N-row panels + slot lifecycle + live rebuild

### Added
- **N-brain runtime slot store.** `DualBrainRuntime` now keeps an ordered list of
  brain slots (`slots()`, `slot_config(i)`, `slot_for_device(id)`,
  `sync_slots(placements)`) in addition to the canonical BIG/SMALL role configs.
  Slots 0/1 are the SAME objects as `config(BIG)`/`config(SMALL)` so the dialogue
  layer never sees a swap; slots 2+ are built automatically for every extra
  enabled device. This is the data-model foundation for rendering one brain row
  per detected GPU + optional CPU/RAM (Phases 2–7 will drive the GUI from it).
- **`build_slot_config(placement, slot, role)`** — builds a `BrainConfig` for one
  device placement (GPU ⇒ auto offload; CPU pool ⇒ `gpu_layers=0` system-RAM
  only). Carries `slot` + `device_id` (stable registry id) for N-brain identity.
- **`sync_slots` wired into the GUI.** `_apply_plan_device_assignment` now feeds
  the detected placements to `runtime.sync_slots`, so the runtime grows/shrinks
  with the operator's enable/disable choices in the Compute Devices panel.
- **Reusable `BrainControlRow` widget** (`gui/widgets/brain_control_row.py`) —
  one brain's one-click-launch controls (header with role + device, status dot,
  running-model label, Start/Stop) emitting **slot-keyed** `start_clicked(int)` /
  `stop_clicked(int)` signals. The building block for the N-brain Provider
  Control panel (Phase 3). Nothing assumes exactly two brains; `bind(config)`
  seeds it from a `BrainConfig`.
- **Provider Control renders N rows (Phase 3).** The panel now builds one
  `BrainControlRow` per runtime slot — slots 2+ appear automatically when more
  devices are enabled in the Compute Devices panel. Legacy `sb_*`/`bb_*`
  attributes are aliased to slots 0/1's sub-widgets so the entire existing
  backend wiring (start/stop/status/model) keeps working unchanged. Row Start/
  Stop route via slot-keyed signals to the existing per-role handlers (slots
  2+ log a clear "Phase 5" message until the backend is generalized).
- **Detected Brains summary in Settings (Phase 4).** The llama.cpp Settings
  group now lists every runtime slot — device, role, port, context, model — so
  all detected hardware is visible in Settings, matching the Compute Devices
  panel. Slots 0/1 keep their full per-brain editors; slots 2+ are summarized
  here until those editors are generalized (Phase 5). Refreshed live from the
  runtime slot list.
- **Slot-keyed launch/stop for extra brains (Phase 5).** `_start_slot(n)` builds
  the llama-server command from slot n's `BrainConfig` (correct device/port/
  context/gpu-layers) and spawns the generic `BrainLaunchWorker`; `_stop_slot(n)`
  terminates the spawned child or falls back to `_kill_llama_on_port`. Row
  Start/Stop now route slots 2+ to these real handlers (previously a log
  message). `_on_stop_all` also stops every extra slot. Fully additive — the
  Big/Small per-role paths are untouched.
- **Live rebuild on device-policy change (Phase 6).** Disabling a device in the
  Compute Devices panel now stops any brain bound to it (routed by slot via
  `_stop_brain_on_disabled_device`) so no server is orphaned on hardware taken
  out of use, then rebuilds the Provider Control rows + Detected Brains summary
  to match. Re-enabling restores the row. No app restart needed.

### Changed
- **`brain_placements()` ordering** now follows the 2-role→slot convention the
  runtime depends on: slot 0 = the Big Brain (first big-class GPU), slot 1 = the
  Small Brain (first small-class device), slot 2+ = remaining devices (extra big
  GPUs / small GPUs / CPU pool). Previously a big-class CPU pool could sort ahead
  of a small-class GPU, mis-seating the Small Brain. Ports still assign
  sequentially from 1234.

### Verification
- 10 new N-brain tests (`TestNBrainSlots`, `TestBuildSlotConfig`): slot identity
  with role configs, growth to 4 placements, shrink on disable, GUI-field
  preservation on slots 0/1, bad-placement resilience, CPU/GPU slot config.
- 8 new `BrainControlRow` tests: slot-keyed signals, live device/status/model
  updates, running-state button toggling, `bind(config)`, bad-config resilience.
- 7 new Provider Control N-row tests: one row per slot, slot0=big/slot1=small,
  legacy aliases point at row sub-widgets, device-aware headers, no needless
  rebuild on refresh, slot-keyed start routing to the right handler.
- 2 new Detected Brains summary tests: summary lists all slots; shows port+ctx.
- 6 new slot-lifecycle tests: `_slot_config` accessor, slot2 CPU config forces
  system-RAM, slot launch command targets the slot port + `--n-gpu-layers`, safe
  stop when not running, row Start/Stop route slots 2+ to `_start_slot`/`_stop_slot`.
- 3 new device-policy rebuild tests: disabling a device stops its brain + shrinks
  rows + persists policy; re-enabling restores rows; disable routing by slot.
- Full runtime + GUI suite: **221 passed**. Device-registry suite: 15 passed.
- Headless GUI: `_apply_runtime` grows the runtime to 3 slots (5060 Ti = slot0
  Big, 1660 Super = slot1 Small, CPU pool = slot2) with correct labels/ports.

## [2.1.11] - 2026-10-10 - Merge Diagnostics tab into DB Stats

### Changed
- **Diagnostics tab merged into DB Stats.** The three diagnostics groups (Brain
  Provider Health, Backend Performance Baseline, State Reconciliation) now live
  inside the DB Stats tab, below the Event Log. The Diagnostics tab is removed
  from the tab bar. A separate "🔍 Refresh Diagnostics" button refreshes just
  those sections; the existing "🔄 Refresh Stats" button refreshes everything.
- `create_diagnostics_tab()` is kept as a backward-compat shim that builds a
  standalone widget with just the diagnostics sections, so existing tests and
  external callers keep working.

### Verification
- Headless GUI: Diagnostics tab removed from tab bar; DB Stats tab contains all
  7 group boxes (4 stats + 3 diagnostics), 6 tables, and 2 refresh buttons.
- `create_diagnostics_tab()` shim still builds correctly with all expected
  attributes.
- `pytest tests/` on the GLOBAL interpreter (Python 3.14): 1104 passed, 2 skipped,
  0 failed.

## [2.1.10] - 2026-10-10 - Help for the advanced llama.cpp flags

### Added
- **Help button on each Advanced llama.cpp Flags group** (Providers & GPU). Opens the
  same in-app feature help dialog the Dialogue tab uses, pre-filtered to the flag
  entries (`keyword="Flag:"`), so the operator can read what a control does without
  leaving the app.
- **19 new help-catalog entries** (`agents/knowledge/help_catalog.py`, 33 -> 53):
  one overview entry for the panel plus one per control — Flash Attention, Cache
  Reuse, Context Checkpoints, KV-cache-in-RAM, the three MoE/CPU-offload flags, the
  six sampling flags, DRY, XTC, both reasoning flags, and the two vision flags. Each
  entry states what the flag does, its default, and a concrete usage example, and
  notes that an unset control adds no flag.

### Verification
- `help_catalog.lookup("Flag:")` returns 19 entries; `lookup("moe")` returns the
  panel plus the three MoE flags; `lookup("dry")` / `lookup("mmproj")` resolve.
- Headless GUI: both flag groups build with 23 controls each and each carries a
  "❓ Help" button; `HelpDialog(keyword="Flag:")` loads 53 entries, shows 19 rows,
  renders the selected entry, and the search box narrows to 4 rows for "moe".
- `pytest tests/` on the GLOBAL interpreter (Python 3.14): 1104 passed, 2 skipped,
  0 failed.

## [2.1.9] - 2026-10-10 - Advanced llama.cpp flags panel (performance, MoE offload, samplers, mmproj)

### Added
- **Per-brain "Advanced llama.cpp Flags" panel** (`gui/widgets/dual_brain_control.py`,
  Providers & GPU tab) — 23 controls, one per llama-server flag, for each brain:
  - **Performance**: `--flash-attn` (default/auto/on/off), `--cache-reuse`,
    `--ctx-checkpoints`, and "keep KV cache in system RAM" (`--no-kv-offload`).
  - **MoE / CPU offload** — the levers that fit a large MoE model on a 16GB card:
    `--n-cpu-moe N`, `--n-cpu-ffn N`, and `--cpu-moe`.
  - **Sampling / anti-repetition**: `--top-k`, `--top-p`, `--min-p`,
    `--repeat-penalty`, `--presence-penalty`, `--frequency-penalty`, and the two
    purpose-built loop killers — the **DRY** family (`--dry-multiplier`,
    `--dry-base`, `--dry-allowed-length`, `--dry-penalty-last-n`) and **XTC**
    (`--xtc-probability`, `--xtc-threshold`).
  - **Reasoning**: `--reasoning-budget`, `--reasoning-format`.
  - **Vision**: an mmproj field (`--mmproj`) with an **Auto** button that finds an
    `mmproj-*.gguf` beside the selected model, plus `--no-mmproj-offload`.
- **`BrainConfig` carries the new fields** (`agents/runtime/dual_brain.py`) and
  `build_llama_command()` emits each flag. `build_config()` parses them from
  `<BIG|SMALL>_BRAIN_*` env keys.
- **`.env.example`** documents every key (all optional).

### Design — backward compatible by construction
Each control has a "not set" sentinel (`(default)` in combos, `-1`/`-2` or `0` in
spins, unchecked boxes). A control at its sentinel writes **no env key**, so
`build_llama_command` omits the flag and llama-server keeps its own default.
Verified: an untouched config produces a **byte-identical** launch command to
v2.1.8 — nothing changes unless the operator opts in.

### Fixed during the work
- **Unchecked boxes inverted their meaning.** Writing `KEY=false` for an unchecked
  "keep KV cache in system RAM" box made `kv_offload=False`, which *emitted*
  `--no-kv-offload` — the opposite of the label. Only a checked box now writes a key.
- `DRY_BASE` allowed a `0.0` minimum that collided with the "not set" sentinel.
- Documented that llama.cpp ignores `--cache-reuse` on multimodal models (its own
  startup warning: "cache_reuse is not supported by multimodal, it will be disabled").

### Verification
- Command-builder matrix: unset config emits **none** of the 23 flags; MoE/perf,
  sampler, reasoning and mmproj groups each emit their flags; env -> config
  round-trip works.
- UI test: both groups build (23 controls each); defaults write **0 keys**; setting
  FLASH_ATTN/CACHE_REUSE/N_CPU_MOE/MIN_P/DRY_MULTIPLIER/MMPROJ writes exactly those
  6 keys and produces a real command containing all 6 flags.
- **Live binary proof**: every one of the 23 flags is present in `llama-server
  --help`, and a real launch with 14 of them plus a gemma-4 mmproj loaded the model
  and logged `loaded multimodal model` — no argument errors.
- `pytest tests/` on the GLOBAL interpreter (Python 3.14): **1104 passed, 2 skipped,
  0 failed**.

## [2.1.8] - 2026-10-10 - Fix the nous retry loop: comment-as-value corruption + missing provider

### Fixed
- **Comment parsed as a value corrupted 7 settings, including the Nous API key.**
  python-dotenv strips an inline comment only when a non-empty value precedes it, so a
  line like `NOUS_API_KEY=   # Optional: Your Nous Research API key` yields the COMMENT
  as the value. The Nous key therefore became the literal string
  `# Optional: Your Nous Research API key` (38 chars, starting `# Op`) and every request
  returned **401 — invalid, blocked or out of funds**. Six other keys were corrupted the
  same way: `CASHAPP_TAG`, `ATOMIC_SOLANA_ADDRESS`, `TAVILY_API_KEY`, `BRAVE_API_KEY`,
  `VLLM_BASE_URL`, `KOBOLDCPP_BASE_URL` (each holding its own comment text).
  - `app/environment.py`: new `clean_env_value()` treats a value that is entirely a
    comment as empty, strips a trailing inline comment from an unquoted value, and keeps
    a quoted value verbatim (so a `#` inside a real secret is never truncated).
    `set_env_values()` now refuses to persist a comment as a value.
  - Read paths hardened: `agents/core/configuration.py::_value`,
    `agents/providers/openai_compatible.py::os_getenv` (covers the whole adapter),
    `agents/providers/anthropic_adapter.py::available`, and `main.py::_safe_widget_text`.
  - `.env.example` fixed at the source: the two lines that used
    `VLLM_BASE_URL=# e.g. ...` / `KOBOLDCPP_BASE_URL=# e.g. ...` now put the example on
    its own comment line and leave the value empty.
  - The live `.env` was repaired (7 values neutralised, backup taken).
- **NOUS could not be disabled, causing an endless retry loop.** `main.py::save_settings()`
  wrote `DISABLE_<X>` for 14 providers but omitted NOUS, and the Settings UI had no NOUS
  row at all (no role combo, model field, key field, or enable checkbox). The provider was
  registered by the adapter registry, so every LLM call fell through to it:
  `big-brain failed -> trying nous -> 404 -> trying big-brain -> ...` until
  "ERROR: LLM unavailable". DB Stats showed **nous: 181 calls / 181 errors (100%)**.
  - Added the NOUS row to the cloud provider panel (`gui/builders/tab_feature_builders.py`).
  - Added the NOUS `_save_provider(...)` call so `DISABLE_NOUS`, `NOUS_MAIN_ENABLED` and
    `NOUS_CHAT_ENABLED` are actually persisted.
  - `.env` now carries `DISABLE_NOUS=True`.
- **Stale model ids.** The Nous portal no longer serves any `hermes-*` model — its catalog
  is a 421-model third-party aggregator with zero hermes/nous ids, so `hermes-4.3-36b`,
  `hermes-4-70b` and `hermes-4-405b` all 404. Replaced the hardcoded lists in
  `provider_manager.py` and the `default_model` fallback in `worker_provider_mixin.py`
  with live ids, and documented the change in the UI note.

### Verification
- `clean_env_value` unit matrix: comment-as-value -> empty; empty -> empty; quoted value
  with `#` preserved; inline comment stripped; plain value unchanged. 0 mismatches.
- `provider_settings("nous").enabled` is now `False`; `save_settings()` writes
  `DISABLE_NOUS=True` / `NOUS_MAIN_ENABLED=False` / `NOUS_CHAT_ENABLED=False`.
- Live provider chain after the fix: `chat=False -> ['big-brain']`,
  `chat=True -> ['small-brain']` — **nous is gone**, so the retry loop cannot occur.
- `pytest tests/` on the GLOBAL interpreter (Python 3.14, the one `python main.py` uses):
  **1104 passed, 2 skipped, 0 failed**.

## [2.1.7] - 2026-10-09 - Discovery: real variety instead of the same fixed finds

### Fixed
- **Repeat scans returned the same items forever.** Three independent causes, all
  confirmed by measurement:
  1. **Airdrop source ignored `page`.** `scan_feeds()` took no arguments and always
     returned the first entries of each feed, so every scan re-reported the same
     rows. It now accepts `query` and `page` and rotates a wrap-around window
     (`PAGE_SIZE = 12`) over each feed's entries — `AirdropSource` forwards both.
  2. **Social (Reddit) source ignored `page`.** `discover_all()` hard-sliced
     `feed.entries[:20]`. It now takes `page`/`query`, rotates a wrap-around window
     (`PAGE_SIZE = 20`), and filters by the search term. `SocialSource` forwards both.
  3. **Dead feed.** `dropzone.io/feed` no longer resolves (connection error), so it
     contributed a failed request and nothing else on every scan. Replaced with two
     verified-live listing feeds (`airdropalert.com/feed/`, `thedefiant.io/api/feed`).
- **Editorial articles were reported as claimable airdrops.** The airdrop source
  matched any entry containing "airdrop", so evergreen explainers and roundups
  ("Crypto airdrops explained: types, qualifying and safety", "Best crypto airdrops
  to farm right now", "The 15 biggest airdrops ever") appeared on every scan and
  looked hardcoded. `GUIDE_TITLE_MARKERS` now filters them out.
- **Unstable ids defeated dedup.** `AirdropScanner` used `str(hash(link))` and the
  social scanner `hash(title) % 10000`. Python salts `hash()` per process, so the
  same listing got a different id after every restart and could never be recognised
  as already-seen. Both now use a SHA-1 of the URL (stable across runs).
- **`content` removed from the scheduler's default source list** (`app/earning_pipeline.py`),
  matching the earlier fix in `EarningSources` — it is not a registered source.

### Measured before/after (live network)
- Airdrop feed entries: `dropzone.io` 0 (dead) -> replaced; thedefiant adds 100 entries.
- Airdrop results: 10 rows, all guide articles -> 7 rows, 0 guide articles.
- Feed rotation proven on a 100-entry feed: page 1/2/3 each return a different
  12-entry window (previously identical).
- Honest ceiling: only ~9-12 airdrop-relevant entries exist across all six feeds at
  any time, so the airdrop source cannot produce dozens of distinct finds per scan —
  this is a property of the public feeds, not of the code.

### Notes
- The `.env` guard in `tests/conftest.py` intermittently reports a modification
  during the suite. Verified NOT to be caused by tests: an instrumented run traced
  zero in-process writes to `.env`, and the file content was byte-identical before
  and after while its mtime advanced — an external process (the running app) rewrites
  it. Unrelated to this change.

### Verification
- Compile sweep: 420 files, 0 failures. Import sweep: 272 modules, 0 failures.
- `pytest tests/`: 1106 passed, 0 failed, 0 access violations.
- Ad-hoc, live: guide-article filter 10 -> 0; page rotation returns distinct windows;
  ids stable across two scans.

## [2.1.6] - 2026-10-09 - Fix runtime crashes, GUI freezes, and discovery noise

### Fixed
- **`ProviderProbeWorker` crash on model change** (`gui/workers/provider_lifecycle_backend.py`).
  A finished probe is `deleteLater()`'d, so its Python wrapper outlived the C++ object;
  the next model change called `old.isRunning()` on that dead wrapper and raised
  `RuntimeError: libshiboken: Internal C++ object (ProviderProbeWorker) already deleted`
  (three tracebacks per model switch). The probe cache now validity-checks the wrapper
  (`shiboken6.isValid`), evicts stale entries, and drops the reference in a
  `finished` handler that runs *before* `deleteLater`.
- **GUI freeze / hang on close** (`agents/brains/big_brain.py`, `agents/brains/small_brain.py`,
  `agents/providers/openai_compatible.py`). The provider client applied the long
  *generation* budget (600s) to **TCP connect** as well. With a stopped or wrong
  llama-server the manager thread sat in `socket.create_connection` for up to ten
  minutes, which is why the app appeared to hang and why shutdown could not join the
  thread. Timeouts are now split: connect/pool = `OPENAI_CONNECT_TIMEOUT_SECONDS`
  (default 10s) / `LOCAL_LLM_CONNECT_TIMEOUT_SECONDS` (default 8s); read/write keep the
  existing long budget so slow local generation is unaffected.
- **Process abort (access violation, exit 139) at window teardown** (`main.py`).
  `shutdown()` called `QThread.terminate()` on the manager/summarizer threads, which
  were frequently blocked inside `socket.read`. Terminating a thread mid-syscall
  corrupts the process. Shutdown now stops, **disconnects the worker's signals first**
  (so queued cross-thread emissions cannot land on widgets that are being destroyed),
  then waits gracefully and logs if a worker outlives the wait — never `terminate()`.
  Tab teardown also sweeps the widget tree for any QThread still running (a model
  restart can leave a replaced GPU poller alive).
- **Cross-thread QWidget access** (`gui/widgets/dual_brain_control.py`,
  `gui/widgets/performance.py`). `_log()` was called from model-restart threads and
  wrote directly to `log_display`; `_SignalThrottler.emit` ran on the worker thread and
  created its `QTimer` there, so the timer died with the thread and the next emit
  faulted inside Qt. Both now marshal to the GUI thread (queued signal / timer owned by
  the QApplication thread) and the throttler's buffer is lock-guarded.

### Changed
- **Discovery no longer reports a non-existent source** (`agents/earning/discovery.py`).
  `content` was still in the default source list, but `ContentSource` was retired from
  the registry, so every scan logged `[Discover] Invalid source 'content' blocked`.
- **Discovery noise filtered** (`agents/discovery/discovery_sources.py`,
  `agents/earning/discoverer.py`). The broad GitHub bounty search was dominated by a
  few "bounty farm" repos seeding near-identical placeholder issues ("[Bounty] Seed a
  paid MCP child bounty" x3, "$239398281948585883* bounty", "[Bounty] Bounty") — 18 of
  26 results from one repository. Now: titles are collapsed case/whitespace-insensitively,
  a per-repo cap (`MAX_PER_REPO = 3`) applies, implausible amounts
  (> `MAX_BOUNTY_USD`) fall back to unknown, and placeholder titles with no real content
  are dropped. Listing sources also drop SEO spam via a shared `is_junk_listing_title`
  filter ("Virtual Card … 4AM" ad farms), which removed ~36 of 40 junk ugig listings.

### Verification
- Compile sweep: 420 files, 0 failures.
- `pytest tests/`: 1104 passed, 2 skipped, 45 subtests, **0 failed and 0 access
  violations** (previously the run aborted at 71% with exit 139).
- Ad-hoc, against the live network: probe-wrapper crash reproduced then survived;
  `Invalid source` gone; GitHub bounties 18 -> 7 with 0 duplicate titles; ugig
  40 -> 4 with 0 spam; provider connect timeout 600s -> 10s; `shutdown()` 8.9s.

## [2.1.5] - 2026-10-09 - Repository restructure: domain packages for agents/, gui/, root modules, tests/

### Changed
- **`agents/` flattened to domain packages.** 107 real modules moved out of the flat
  `agents/*.py` layer into `brains/ dialogue/ providers/ earning/ evidence/ discovery/
  knowledge/ core/ services/ safety/` (joining the existing `cognition/ autonomy/
  integrations/ platforms/ polish/ runtime/`). 36 transitional shims deleted and every
  caller repointed to the real module. `agents/` now holds only `__init__.py`.
- **`gui/` flattened to domain packages.** 25 modules moved into `tabs/ builders/
  widgets/ workers/ panels/`. `gui/` now holds only `__init__.py`.
- **Root modules moved to `app/`.** 14 top-level modules (`database`, `manager`, `ui`,
  `earning_memory`, `earning_pipeline`, `library`, `provider_models`, `theme_config`,
  `text_utils`, `effects`, `action_pipeline`, `startup_validation`, `version`,
  `earning_learning_loop`) moved into `app/`, joining `app/environment.py`. `main.py`
  stays at the repo root as the launcher and imports from `app.*`.
- **`tests/` grouped by domain.** 128 `test_*.py` files moved into `dialogue/ earning/
  evidence/ safety/ runtime/ gui/ providers/ sections/`. `tests/__main__.py` now
  discovers recursively and resolves test filenames anywhere under `tests/`; `conftest.py`
  stays at the root so its session fixtures still apply to every subpackage.

### Fixed
- **`.gitignore` silently untracked every `__init__.py`.** The `_*.py` ignore rule also
  matches `__init__.py`, so 26 of 34 package inits were never committed (only 8 had been
  force-added). A fresh clone could not import the packages. Added `!__init__.py` so
  package structure is always committed.
- **Leaked `MainWindow` threads made the suite order-dependent.** `MainWindow.__init__`
  starts `ManagerThread` + `SummarizerThread` (real socket I/O); a test that built a
  window without `shutdown()` left those threads running, and a later Qt teardown could
  abort mid-`create_connection` with an access violation (exit 139), losing the whole run.
  `tests/conftest.py` now tracks MainWindow instances (weakly, via a session-scoped
  `__init__` patch) and shuts down any still-live window after each test.
- **Depth-sensitive `__file__` paths repaired after each move.** ~50 modules and test
  files computed the repo root, DB paths, `.env`, `settings.json` or prompt paths from
  `__file__`; every one was corrected for its new depth (verified: DB files still land at
  the repo root, `test_root_scope` passes).

### Verification
- Compile sweep: 420 files, 0 failures. Import sweep: 272 modules, 0 failures.
- Headless GUI smoke: 22 tabs build; Dialogue, Settings, Opportunities, Providers & GPU
  all construct.
- `pytest tests/`: 1104 passed, 2 skipped, 45 subtests, 0 failed — confirmed in both the
  new grouped collection order and the original flat order.
- Legacy runner self-tests: `python -m tests --test check_syntax|test_imports|test_main`
  pass; recursive discovery resolves grouped test names.

## [2.1.4] - 2026-10-09 - Dialogue token limits: per-brain, context-scaled, Settings-adjustable

### Added
- **Per-brain dialogue token limits** (`gui/tab_feature_builders.py` Settings → LLM Parameters; `gui/dialogue_tab.py`): two new controls — **Dialogue tokens — Big Brain** (default 1024) and **Dialogue tokens — Small Brain** (default 512) — plus an **Auto-scale dialogue tokens with model context length** checkbox (default on). These govern the reply-length budget for the Dialogue tab only, independently of the generic `MAX_TOKENS`. Set them higher for long, detailed exchanges (deep planning, document analysis) or lower for short banter. Persisted to `.env` (`DIALOGUE_MAX_TOKENS_BIG` / `DIALOGUE_MAX_TOKENS_SMALL` / `DIALOGUE_AUTO_TOKENS`) and applied live via `os.environ`, so a new turn picks up changes without a restart.
- **`DialogueWorker._resolve_max_tokens(brain)`** (`gui/dialogue_tab.py`): single source of truth for the dialogue reply budget with clear precedence — (1) `DIALOGUE_MAX_TOKENS` explicit global override wins outright; (2) per-brain `DIALOGUE_MAX_TOKENS_BIG/_SMALL` value, which in auto mode is the **floor**; (3) auto-scaling to `min(8192, context_length // 8)` when the model's context is known, else the model-size heuristic; thinking models get a 2048 floor when `DIALOGUE_ENABLE_THINKING` is set. A large-context model now writes longer turns; a small one stays tight.

### Changed
- **`tests/test_dialogue_response_corruption.py`** — the two worker-budget tests asserted the old hardcoded size heuristic (and set a `DIALOGUE_TURN_MAX_TOKENS` env var that the code never read, so they were already not testing what they claimed). Updated to drive the new `DIALOGUE_AUTO_TOKENS=false` + per-brain keys, which is the real contract now. Also hardened the resolver's context coercion so a non-numeric `context_length` (e.g. a Mock brain) falls through to the heuristic instead of raising.
- **`.env.example`**: documented the three new dialogue-token keys.

### Verification
- Resolver matrix (ad-hoc): auto ON → big/32k ctx = 4096, small/8k = 1024, no-ctx 27B = 1024, no-ctx 1B = 512; auto OFF → fixed 1024/512; manual raised → 4096/2048; `DIALOGUE_MAX_TOKENS` override → both 1536; auto ON + 131072 ctx → capped 8192.
- Compile sweep: 434 files, 0 failures. Import sweep: 297 modules, 0 failures.
- Headless GUI smoke: Settings exposes `dialogue_tokens_big_spin` (1024), `dialogue_tokens_small_spin` (512), `dialogue_auto_tokens_cb` (checked).
- `pytest tests/`: 1104 passed, 2 skipped, 45 subtests, 0 failed.

## [2.1.3] - 2026-10-09 - Dialogue: real opportunities, live tools/SQL/vision, 24/7 guard, action handoff

### Added
- **Opportunity board in the dialogue prompt** (`gui/dialogue_tab.py`, `gui/tab_feature_builders.py`): `get_dialogue_context()` now injects a bounded `## OPPORTUNITY BOARD` of real discovered candidates, sourced from the main window's `_visible_opportunity_entries()` (the exact rows the Opportunities tab is showing) with a portfolio-snapshot fallback. Previously `_get_opportunity_context()` existed but was **called from nowhere** and `_visible_opportunity_entries` was a `(None, [])` stub, so the personas planned around opportunities they could not see. The board is the ONLY elastic block: it is budgeted to the space left after the body and the mandatory tail and yields whole candidate lines, so the untrusted-pages guard, DIALOGUE CONTROL and WORK TRACKER always survive (existing guard tests still pass).
- **Read-only tools + SQL in dialogue, both brains** (`agents/small_brain.py`, `agents/big_brain.py`): dialogue mode previously appended `"DIALOGUE-ONLY MODE: … Do not call tools, write SQL, emit function names"` — directly contradicting the context's "CALL A READ-ONLY TOOL NOW". Both brains now permit and encourage read-only research (`web_search`/`web_read`/`web_check`/`query_db` read-only SQL/`file_read`/`workshop_*`), keep create/register/sign/pay/submit behind human approval, and raise dialogue `max_iterations` 1 → 2 so a tool call can actually execute and return evidence.
- **Live tool-activity rendering** (`gui/dialogue_tab.py`, `agents/chat_completion.py`): `DialogueWorker` gains a `tool_activity` signal and `chat_with_tools` gains `on_tool_trace`, emitted the moment a tool executes (both text-call and function-call paths). `_on_tool_activity` — previously dead (no signal existed) — is now connected, so real tool calls render separately from persona narration and reset the progress guard.
- **Vision (image) input** (`agents/model_profile.py`, `gui/dialogue_tab.py`, `agents/chat_completion.py`): new `supports_vision()` detects vision-capable families (Qwen-VL, LLaVA, Gemma-3, Pixtral, InternVL, mllama, …). The Dialogue tab gains a 🖼 Image button; attached images are sent as multimodal content (local files auto-encoded to data URLs) for the next turn.
- **Action handoff to approval** (`gui/dialogue_tab.py`): a Driver `ACTION: … | PLATFORM: … | EXPECTED: …` proposal was emitted but never consumed. It is now parsed, recorded, surfaced in later context as `## ACTIVE ACTION PROPOSAL`, and enqueued as a human `ApprovalKind.ACTION` item (deduped by signature) so a dialogue decision becomes a gated approval instead of dying in chat.
- **Live progress guard (no hard limit)** (`gui/dialogue_tab.py`): Live remains uncapped for 24/7 operation. A turn counter since the last verified tool evidence (`DIALOGUE_EVIDENCE_NUDGE_LIMIT`, default 6) injects a one-shot PROGRESS GUARD instruction telling the pair to call a tool or state a concrete blocker, instead of looping.
- **🧠 Thoughts button** (`gui/dialogue_tab.py`): `_show_thoughts()` was a `pass` placeholder; it now renders the latest bounded thought graph (decisions/tool status — never private chain-of-thought).
- **Web discovery in the Opportunities tab** (`gui/tab_feature_builders.py`, `agents/discovery_engine.py`, `agents/discovery_port.py`, `agents/earning/discovery.py`, `earning_pipeline.py`): new "Web query" field drives the generic web source's real provider search; a status line surfaces the `ALLOW_WEB_DISCOVERY` gate so an empty "web" source is explained rather than silent. The `query` now threads engine → port → service → pipeline → scan (with backward-compatible fallbacks for injected engines/sources).

### Changed
- **Live recovery no longer silently ends the session** (`gui/dialogue_tab.py`): the duplicate-text/semantic branches previously called `stop_live()` on repeated non-progress; they now resume the Live scheduler via `_resume_live_if_running()`, and `live()` clears stale `_pending_tool_blocked`/progress state. Live is intended to keep the pair working and self-recovering.
- **`_get_control_context()` wired into the prompt** and made stub-safe: pending-approval / blocked-persona state is now live in the context tail, not only the sidebar.
- **Removed a duplicate `_append` definition** (byte-identical; the second silently shadowed the first).
- **`_is_repetitive()` wired** into `DialogueWorker`'s anti-repetition gate (was defined but never called).

### Verification
- Compile sweep: 434 files, 0 failures. Import sweep: 297 modules, 0 failures.
- `pytest tests/` (QT_QPA_PLATFORM=offscreen): **1104 passed, 2 skipped, 45 subtests passed, 0 failed, 0 errors** (exit 0).
- Headless GUI smoke: `MainWindow` builds with 22 tabs; Dialogue tab exposes `image_btn`, `thoughts_btn`, board provider, `_vision_available`.
- Ad-hoc: vision detection returns True for Qwen-VL/LLaVA/Gemma-3 and False for text-only Qwen3.5/Llama-3; `_capture_action_proposal` enqueues exactly one approval (dedup verified) and surfaces it in context; discovery engine returns fixtures for a query with a mock web source.

## [2.1.2] - 2026-10-09 - Dead-code cleanup: 55 unreachable modules removed

### Removed
- **Dead-code sweep — 55 unreachable files deleted** (`agents/`, `gui/`, root): a full-repo AST reachability audit (BFS from `main.py` + the `tests/` tree, with relative-import and dynamic `__import__`/`importlib` resolution, island analysis, and a 542-file string-reference scan) classified every module. 55 files with **no live importer, no test reference, and no dynamic load** were removed:
  - **Compat shims re-exporting live modules** (7): `agents/manager_{metrics,queues,routing,scheduler,shutdown,workers}.py`, `agents/text_utils.py`, `agents/tools.py`, `agents/wallet_crypto.py` — all pure `from <real module> import …` re-exports; the real modules in `agents/runtime/` and `agents/safety/` are untouched.
  - **Superseded earning service layer** (13): `agents/earning_*_service.py` (accounting, discovery, evaluation, evidence, execution, intelligence, opportunity_adapters, payment, portfolio, proposal, ranking, submission, task_adapters).
  - **Superseded singletons** (~24): `agents/safety_guard.py`, `agents/tool_registry.py`, `agents/tool_dispatch.py`, `agents/tool_handlers.py`, `agents/tool_response.py`, `agents/task_workspace.py`, `agents/worker_filesystem.py`, `agents/web_scraper.py`, `agents/web_provider.py`, `agents/web_controller.py`, `agents/payments.py`, `agents/crypto_payments.py`, `agents/llm_runtime.py`, `agents/runtime_services.py`, `agents/runtime_utils.py`, `agents/task_router.py`, `agents/cost_guard.py`, `agents/data_providers.py`, `agents/content_generator.py`, `agents/microtask_client.py`, `agents/opportunity_scanner.py`, `agents/opportunity_commands.py`, `agents/opportunity_dialogue_bridge.py`, `agents/providers/context_table.py`-class orphans — each superseded by a live module in `agents/safety/`, `agents/integrations/`, or `agents/runtime/`.
  - **Shadowed / scratch / orphan** (3): `agents/cognition.py` (shadowed by the `agents/cognition/` package — Python always imported the package, so this file was dead and a silent bug source), `agents/tmp_small_brain_new.py`, `agents/polish/web_dashboard.py`.
  - **Unused GUI panels** (4): `gui/goal_tracker.py`, `gui/logging_tab.py`, `gui/notifications_tab.py`, `gui/model_switcher.py` — confirmed unreferenced by `main.py` and `tab_feature_builders.py`.
  - **One-off root scripts** (3): `_compile_sweep.py`, `test_earning_pipeline.py` (legacy; superseded by `tests/`), `verify_all_fixes.py`.
- **`tests/test_tool_safety.py`**: `test_relative_paths_stay_inside_project` used the now-deleted `agents/tools.py` as its arbitrary existing-path fixture; repointed to `agents/tool_safety.py` (the module the test already imports, so it always exists). Behavior asserted is unchanged.

### Kept (verified NOT dead despite "no importer")
- `agents/platforms/` (whole package) — imported by `tests/test_trust_boundary.py` (`PlatformAdapter`/`FiverrAdapter`/`RedditAdapter`); test-imported code cannot be deleted.
- `agents/cli_interface.py`, `agents/polish/cli_interface.py`, `agents/polish/comprehensive_logging.py` — headless CLI surface (dynamically loads the autonomy modules; planned for future implementation).
- `agents/autonomy/*`, `agents/earning_capability|discoverer|got`, `agents/cognition/graph.py` — real subsystems exercised by the test suite.
- `agents/providers/context_table.py` — restored after an import sweep caught the provider adapters' relative import of it.
- `tools/github_publish/*`, `run_lead_routine.py` — personal/ops scripts.

### Fixed
- **`tests/test_prompt_budget.py` — 2 pre-existing failures** (`test_invalid_tier_falls_back_to_compact`, `test_tiers_are_ordered_and_bounded`): the test builds `SmallBrainAdapter` via `__new__` (bypassing `__init__`) and set only `base_system_prompt`/`personality`/`knowledge`/`model`, but `_build_system_prompt` also reads `self.decision_support_only` (a real adapter sets it from the canonical runtime config in `__init__`), so it raised `AttributeError`. The harness now sets `decision_support_only = False`. Production code was correct — the test fixture was incomplete.
- **`tests/test_section_e.py::TestGuiTabs::test_new_tabs_present` — 1 pre-existing failure**: it asserted `"Live Portfolio"` / `"Strategy Simulator"` unconditionally and hardcoded `count() == 21`. Those two tabs are deliberately gated behind the fail-closed `live_trading` feature flag (off by default), so they are *correctly* absent — the GUI registers 22 ungated tabs. The test now asserts the ungated surfaces unconditionally, asserts each gated tab is present **iff** its `feature_enabled(flag)` is true, and computes the expected count from the enabled flags. Verified passing with the flags both off (default) and on.

### Verification
- Compile sweep: 434 files, 0 failures. Import sweep: 297 modules, 0 failures.
- `pytest tests/` (QT_QPA_PLATFORM=offscreen): **1104 passed, 2 skipped, 45 subtests passed, 0 failed, 0 errors** (exit 0). The 3 previously-red tests were pre-existing failures (confirmed by re-running against the un-deleted tree) and are now fixed.
- Headless GUI smoke: `MainWindow` builds with 22 tabs, Dialogue present.
- All 55 deleted files backed up outside the repo at `D:\MrBot1000_2.0_deadcode_backup_20261009_082244\` (+ `.zip`) for one-command restore.
- Note: a `.env` write observed mid-suite (`SMALL_BRAIN_KV_CACHE` f16→q8_0) was traced to the **out-of-process `hermes --profile lead` routine agent** running concurrently, not the test suite — the in-process write watcher saw nothing, and a clean re-run passed. `.env` restored to `f16`.

## [Unreleased] - 2026-09-13 - Comprehensive revamp: providers, performance, dialogue, UI, logs

### Added
- **Readable dialogue session log** (`gui/dialogue_tab.py`): the Dialogue tab now appends one JSONL record per turn to `logs/dialogue_YYYYMMDD.log` so a session can be diagnosed without seeing the GUI. Each record carries: timestamp, persona, outcome (`accepted`/`transport_error`/`empty`/`empty_final`/`duplicate`/`session_start`), the **model actually used**, its capability **tier**, phase, goal, mode (`live`/`auto`/`idle`), the transport/empty/duplicate retry counters, the displayed token/latency stats, and the response text. The writer is best-effort and never raises. (The per-turn `model=… tok/s` line previously existed only on screen — `_on_stats` displayed it but persisted nothing.)
- **Auto-start llama-server on launch** (`main.py`, `gui/dual_brain_control.py`, `.env.example`): New `AUTO_START_SERVERS` setting (default 1) plus a "Start both servers automatically at launch" checkbox in Providers & GPU → Quick Actions. When enabled, both llama-server instances launch automatically ~700ms after the window shows (deferred + non-blocking, idempotent via the existing probe path; already-running/disabled/non-local brains are left alone). The checkbox persists its choice to `.env`.
- **Nous Research provider** (`agents/provider_manager.py`, `agents/base_worker.py`, `.env.example`): Added as cloud provider with `NOUS_API_KEY`, `NOUS_MODEL=hermes-4.3-36b`, `NOUS_BASE_URL=https://inference-api.nousresearch.com/v1`. Supports Hermes-4.3-36B, Hermes-4-70B, Hermes-4-405B (128k context).
- **Prompting engine** (`agents/prompting_engine.py`): Adaptive prompt construction. Selects best technique per task type: ToT (research/planning), CoT (dialogue), ReAct+CoT+tools (dynamic decisions), Skeleton of Thought (proposals), Agentic (complex goals), Prompt Chaining (pipelines), Meta Prompting (high-stakes), Few-Shot (structured). Remembers successful patterns in `prompt_memory` table.
- **Model-agnostic brain recommendations** (`agents/prompting_engine.py`): Detects param size from model name/metadata, not brain slot. Heavy (14B+) → ToT/agentic/meta; Medium (7-14B) → balanced CoT/ReAct; Small (<7B) → fast CoT/few-shot/chaining.
- **Opportunity dialogue bridge** (`agents/opportunity_dialogue_bridge.py`): Edward and Jacob see all opportunities in dialogue context. Can evaluate, compare, choose which to pursue, reject/scam-mark. Blacklist persists across restarts.
- **Opportunity commands** (`agents/opportunity_commands.py`): Parse EVALUATE/APPROVE/REJECT commands from dialogue (e.g. "EVALUATE 3", "REJECT 2, 5, 8").
- **Performance toolkit** (`gui/performance.py`): Deferred initialization queue, request coalescing, signal throttling, memory-bounded LRU cache, weak-ref worker pool.
- **Per-brain temperature controls** (`gui/dual_brain_control.py`): QDoubleSpinBox + preset combo (0.0 Precise / 0.3 Low / 0.5 Default / 0.7 Medium / 1.0 Creative / 1.5 Wild) for both brains. Persists to `.env`.
- **DB Stats revamp** (`gui/tab_builders.py`, `database.py`, `main.py`): Added Prompt Tokens and Completion Tokens stat cards. Fixed avg latency SQL to exclude error/null entries (was showing 10k+ ms).
- **Live Logs revamp** (`gui/tab_builders.py`, `main.py`): 6-column table with Message column stretch. Export button to save logs. Entry Details panel with resizable vertical splitter (3:1 ratio). Auto-categorization (LLM, Safety, Earning, GPU, System). Word-wrap enabled, rows auto-resize to content. Details column interactive-resizable.
- **Settings tab revamp** (`gui/tab_builders.py`, `main.py`): Performance & Cache statistics display. LLM Parameters: Temperature (0.0-2.0) and Top-P (0.0-1.0) spin boxes, max_tokens range to 16384. Model Info: larger display, Copy to Clipboard button. Save persists MAX_TOKENS, LLM_TEMPERATURE, LLM_TOP_P to .env.
- **LLM runtime parameters** (`agents/base_worker.py`, `agents/providers/ollama_adapter.py`, `agents/providers/anthropic_adapter.py`): WorkerAgent initializes _max_tokens, _temperature, _top_p from env vars. Call chain propagates through to adapters.
- **Dialogue progress bar** (`gui/dialogue_tab.py`): QProgressBar below chat display shows "Generating {persona}'s response..." with color-coded bars.
- **Prompt memory table** (`database.py`): New `prompt_memory` table for long-term prompt pattern memory.
- **Settings payout persistence** (`main.py` save_settings): Now persists CASHAPP_TAG and ATOMIC_SOLANA_ADDRESS from Payout Destinations widgets.

### Fixed

- **Duplicate llama-server stacking on one port** (`gui/dual_brain_control.py`): `BrainLaunchWorker` always spawned a fresh `Popen`, even when a server was already listening — and a second instance can bind the same port (`SO_REUSEADDR`), giving two PIDs per port and nondeterministic routing (a request could land on a server with a different model loaded). `run()` now does an **adopt-existing-listener pre-flight**: if something already answers `/v1/models` on the port, it adopts it (reports success with `_proc=None`, marks `adopted=True`) and only `Popen`s when the port is free. `stop()` is now strictly conditional: it terminates only a process the worker itself spawned; adopted servers are never touched (the app must not kill a server it didn't launch or one shared with another manager). The launch completion handlers set `we_started_small/big = proc is not None`, so an adopted server is never claimed as self-launched and auto-teardown won't manage it. Covered by `tests/test_launch_adopt.py` (adopt-no-spawn + stop-is-noop-for-adopted).
- **Deprecated Qt 6.11 attributes removed** (`effects.py`): `apply_antialiasing` referenced `Qt.AA_UseHighDpiPixmaps` and `Qt.AA_EnableHighDpiScaling`, which are removed in Qt 6.10 — redundant no-ops that only emitted 12 deprecation warnings per run. Replaced with a harmless high-DPI rounding policy; the `-W error::DeprecationWarning` check passes and the test-suite warning count drops to zero.
- **Disabling a provider wrongly prompted a restart** (`main.py`): `_settings_require_restart` treated any non-model env change as restart-requiring, including `DISABLE_*` and `*_ENABLED` toggles. But those gates are read from env **at call time** (`base_worker.py:513`) and the Settings save already invalidates the provider registry (`main.py:2888-2893`), so a toggled provider is excluded on the next `llm()` call with no relaunch. The enable/disable keys are now skipped in the restart diff, so the false "the program needs to restart" popup no longer appears for enable/disable; only key/base-url changes still prompt.
- **Settings tab had no Save button near the top** (`gui/tab_builders.py`): the only "Save All Settings" button sat deep inside the scroll area, so a user changing one toggle had to scroll to the very end to apply it. A second quick-save button (same handler, same values) is now added at the top of the tab.
- **GUI lag during generation** (`gui/dialogue_tab.py`): the dialogue progress signal was emitted **per streamed token**, and the handler did `setRange`/`setFormat` plus a Providers & GPU tab update for every one — at 100–1000 tok/s that is hundreds of Qt-thread widget updates per second, the stall felt while a model generates. The `worker.progress` connection is now routed through the existing `gui/performance.make_throttler(flush_ms=80)`, coalescing per-token emissions into timed flushes (all tokens preserved, GUI updates bounded). The throttler is cleaned up when the worker finishes.

- **The first-turn context omitted the WORK TRACKER** (`gui/dialogue_tab.py`): `get_dialogue_context()` has two assemblers — the early-return branch used when `conversation_history` is empty built its own prompt and skipped the `WORK TRACKER` that every later turn includes, so turn 1 had no goal-continuity line. The tracker is now built before the branch and included in both first-turn returns (with its length reserved in the first-turn board budget), so turn 1 matches every other turn. Covered by `tests/test_dialogue_turn1_parity.py` (its strict-xfail marker was removed once the fold landed).
- **A large board could evict the evidence-integrity guard blocks** (`gui/dialogue_tab.py`): the context is truncated at `_context_char_limit` from the **tail**, and `DIALOGUE CONTROL` (the "narrated tool calls are visible intent only — not evidence" framing plus the pending-approval stop) and the `WORK TRACKER` sit *after* the board. With the board unbounded, a full board pushed those guards out — anti-correlated with need, since more board content made it more likely the model lost the rule that narrated calls aren't evidence. The board is now the **only elastic block**: `_get_opportunity_context(max_chars=…)` drops trailing candidate lines until the survey fits the budget left after the fixed prefix and the mandatory tail, and the first-turn path is budgeted and bounded the same way. Covered by `tests/test_dialogue_context_guards.py`, which asserts the untrusted-pages guard, the DIALOGUE CONTROL framing, the CONTROL STOP, and the WORK TRACKER all survive a 200-entry board — **including the small-limit boundary case** (empty board / 500-turn history / 4000-char limit) where a non-zero budget floor previously let history or the board push the mandatory tail past the limit and the final slice cut it. Both budgets now floor at 0, `history_block` is budgeted like the board, and the `_last_context_values` cache is read from the string actually sent.
- **The opportunity board was capped at 4000 chars, hiding most candidates** (`gui/dialogue_tab.py`): the cap (added alongside the contract reorder) showed only ~16 of 60 candidates — the personas reported being "stuck on the first page". Removed; survey lines are compacted (board 22 KB → 14 KB for 60 candidates) and `DIALOGUE_CONTEXT_CHAR_LIMIT` default raised 12000 → 16000 so the full survey fits.
- **Start All Brains needed a second click to show "reachable"** (`gui/dual_brain_control.py`): `BrainLaunchWorker` reports success as soon as the llama-server **process is alive**, but a server loading a large model into VRAM does not answer `/v1/models` for many seconds afterwards. The launch-success handler ran a single immediate status probe, which therefore left the status at "● Stopped" — the operator had to click Start again to see it go reachable. A successful launch now re-probes every 2s (bounded to ~3 min) until the just-launched brain reports reachable, then stops.
- **Two `cleanup()` methods, and the live one was the less defensive** (`gui/dual_brain_control.py`): the class body defined `cleanup()` twice, so the earlier (safer) definition was dead code and the surviving one lacked the `try/except RuntimeError` guard and the provider-probe-thread join. The two are consolidated into one implementation that sets `_closing` first, joins the probe thread, and guards each worker stop — an unguarded `RuntimeError` there aborts teardown and leaves threads running (the "QThread: Destroyed while thread is still running" failure).
- **The per-turn log now records the context's monetary values** (`gui/dialogue_tab.py`): `get_dialogue_context()` caches the set of `$` values present in the context actually sent, and `_log_dialogue_turn()` writes them as a `context_values` field. This makes the numeric-evidence check (`agents/numeric_evidence.py`) measurable retrospectively — the log previously had no prompt/context field, so a cited value could not be classified as supported vs. invented from the log alone. Covered by the dialogue suite.
- **The per-turn log reported the wrong tier** (`gui/dialogue_tab.py`): `_log_dialogue_turn()` computed its `"tier"` field inline from model size only, bypassing `_tier_for_brain` and the <10GB VRAM cap — so a 14B on a 6GB card ran `compact` but the log recorded `"tier": "full"`, actively misleading any diagnosis that reads the log. The log now routes its tier through `_tier_for_brain` (same source as the prompt path). Covered by `tests/test_dialogue_vram_tier.py`.
- **Jacob's thinking block was shown as his reply** (`gui/dialogue_tab.py`): live inference against port 1235 showed LFM2.5-2.6B emits a bare ` thinking` marker glued to the text (` thinkingThe user...`) with no number/colon and no  thinking tags. `_clean_model_response()` only stripped numbered/colon-prefixed markers, so the reasoning block leaked into the persona's reply — a strong contributor to Jacob's "no usable response" turns. The cleaner now also strips a leading `thinking`/`thought` marker whether followed by a word boundary or an uppercase letter (the start of the actual reply). Covered by `tests/test_dialogue_response_corruption.py`.
- **Prompt tier now follows GPU VRAM, not just the model filename** (`gui/dialogue_tab.py`): the big/small hardware split (< 10 GB card → small-model prompting, ≥ 10 GB → enhanced prompting) is now enforced. `_tier_for_brain()` is the single source of truth for a brain's tier, used by the system prompt (`respond()`), the dialogue context (`get_dialogue_context()`), and the output contract (`_model_output_contract()`) — all three previously computed the tier independently and could disagree. It caps at `compact` when the brain's assigned GPU is under 10 GB, so a large model on a 6 GB card gets the lighter prompt instead of the full one. VRAM is resolved from the canonical runtime's role→device mapping plus the Providers & GPU tab's nvidia-smi data. **Unknown VRAM never demotes or promotes** — it falls back to the deterministic model-size tier, so prompt quality cannot flip run-to-run on a transient telemetry failure. Covered by `tests/test_dialogue_vram_tier.py` (including a cross-site agreement test for every small/model/VRAM combination).
- **Retired the missing `ARCHITECTURE_CURRENT.md` / `ARCHITECTURE.md` references** (`README.md`, `Skill.md`, `.hermes/routines/*`, `.hermes/plans/*`): both documents are absent from the tree, yet `README.md` listed them as the "current system design" reference and the standing `.hermes` routine prompts (the basis for the scheduled architect job) told the agent to read `ARCHITECTURE_CURRENT.md` as a source of truth — which is why the same "missing architecture doc" finding recurred every cycle. All 15 references across 10 files are removed; the current published record is now `Agent.md` (runtime contract) + `README.md` (system overview) + `CHANGELOG.md` (release history). Historical mentions in past `CHANGELOG.md` entries and generated logs are left untouched.
- **Stale `ARCHITECTURE_CURRENT.md` reference removed from the runnable lead-routine prompt** (`run_lead_routine.py`, `_lead_prompt.txt`, `_cron_prompt_run.txt`): after the prior retirement pass, the in-repo copies of the scheduled routine still listed `ARCHITECTURE_CURRENT.md` under "Inspect as appropriate" and "Project Synchronization." Removed from all three so the routine text the scheduled job actually reads matches the current published record. The authoritative architecture/source-of-truth references are now `Agent.md`, `README.md`, and `CHANGELOG.md`; `ARCHITECTURE_CURRENT.md`/`ARCHITECTURE.md` are still absent and are no longer cited anywhere as a current source.
- **Human steering was outranked by the re-injected opportunity board** (`gui/dialogue_tab.py`): `get_dialogue_context()` re-injected the full board every turn *below* the history, so a human instruction ("ignore airdrops") that lived only as one history row was bracketed by the phase instruction in front and the whole board behind — the model re-anchored on the board and kept re-proposing vetoed categories. The context now surfaces the operator's most recent directive as its own `OPERATOR DIRECTIVE` line, ahead of the board and phase, marked as outranking both. Covered by `tests/test_dialogue_context_ordering.py`.
- **A long board could evict the response contract** (`gui/dialogue_tab.py`): `get_dialogue_context()` returns `context[:limit]`, which cuts the **tail** — and the response contract ("Respond AS …, call a tool, NEVER make up data") was emitted last, after the board. It is now assembled *before* the board, so truncation can never drop the instruction to respond or call a tool. The board is additionally bounded to 4000 chars.
- **`SafetyGate(auto_approve_readonly=False)` was not enforced** (`agents/safety_gate.py`): the flag was stored on the instance but never read by `check()`, so read-only tools were always auto-approved regardless — a public, safety-adjacent constructor flag advertising a policy the gate did not implement. `check()` now routes read-only tools to `NEEDS_APPROVAL` when the flag is disabled; the default (`True`) is unchanged, so no existing caller's behaviour moves. Covered by new `TestAutoApproveReadonlyFlag` in `tests/test_safety_gate_registry_alignment.py`.
- **MoE models were mis-tiered as "tiny" and stripped of their persona** (`gui/dialogue_tab.py`): `_estimate_model_size()` returned the *active* parameter count, so `Qwen3.6-14B-A3B-…` scored `3.0` and fell under the `< 4` tiny boundary. Tiny tier selects a deliberately minimal prompt (`personas.py:137`) with no tagline, identity, personality, strengths, guardrails, or memory — so a capable 14B MoE was instructed as a 3B model and produced generic/off-goal replies. Tiering now uses *total* parameters (a 14B-A3B is a 14B-class model). Also unified the tier boundary in `get_dialogue_context` (`< 14` → `< 9`) so the system prompt, output contract, and the model's own "MODEL TIER" line all agree.
- **Dialogue stopped after a few turns** (`gui/dialogue_tab.py`): the terminal-stop gate tested for the bare substring `"blocked"` anywhere in a persona's reply, but the lifecycle explicitly *instructs* the personas to answer `"BLOCKED: <reason>"`. Two personas doing what the prompt asked were therefore treated as a terminal dead-end and `stop_live()` fired. The gate is now intent-aware: only an explicit terminal marker (e.g. "awaiting human", "cannot proceed", "no further action") closes the run, while a normal phase veto is just a veto. Regression test `test_both_personas_terminal_block_stops_control_state` still passes.
- **Dialogue could not recover once paused** (`gui/dialogue_tab.py`): `_blocked_personas`/`_blocked_states` were cleared only by a full Reset, so restarting Live immediately re-tripped the gate. They are now cleared on `stop_live()`, on Live start, and on Auto-Step start.
- **Dialogue paused permanently after one approval-gated tool call** (`gui/dialogue_tab.py`): `_pending_tool_blocked` was set when a tool routed to the approval queue and cleared only by Reset. It is now also cleared when the human sends new direction and when a run (Live/Auto-Step) starts.
- **Safe-fallback text killed the run** (`gui/dialogue_tab.py`): `_safe_fallback_response()` returns text beginning `"BLOCKED:"`, which fed the terminal gate and marked the persona blocked. With the intent-aware gate this no longer happens (verified: gate returns False and no blocked state is set).
- **Human input was misrouted during Live/Auto** (`gui/dialogue_tab.py`): a human message was overwritten by `_current_phase_speaker()`, which also silently advanced the lifecycle phase — discarding the chosen "Next reply" persona and desyncing the phase. `respond()` now takes `manual=True` for human/manual turns, which keeps them phase-neutral and honours the selected responder; a human message also clears any paused gate.
- **Dialogue read the wrong (empty) opportunity store** (`agents/opportunity_portfolio.py`, `gui/tab_builders.py`, `agents/workspace_context.py`, `main.py`): the composition root opened `<repo>/opportunity_portfolio.db` (0 rows) while the Opportunities tab opened `~/.mrbot1000/opportunities.db` (122 rows), so the Dialogue tab could be handed an empty portfolio while the tab showed dozens. All three now use one `canonical_portfolio_path()`, and the Opportunities tab reuses the shared instance instead of replacing it.
- **Personas could not see the whole opportunity board** (`gui/dialogue_tab.py`): `_get_opportunity_context()` returned only `entries[:12]` as terse one-line rows, and the lifecycle began by demanding ONE concrete action, so the personas fixated on a single candidate. It now emits a full survey — every open candidate, numbered for reference, with per-platform and per-category counts — and the lifecycle opens with a **survey** phase plus a **select** phase so the personas give each an overview and then pick one or more to research.
- **Opportunity decisions never reached the portfolio** (`gui/dialogue_tab.py`): `opportunity_commands` (EVALUATE/APPROVE/REJECT) existed but was never called from dialogue. It is now applied to each accepted turn, sharing the survey's numbering so a referenced number maps to the same candidate.
- **Implausible payouts shown as fact** (`gui/dialogue_tab.py`): a scanner-emitted value of `9.9e101` was rendered as a literal dollar amount, inviting the personas to chase a fabricated bounty. Survey values are now formatted defensively: non-finite/negative → invalid, `>= $1e9` → flagged `IMPLAUSIBLE — treat as unverified`. (The upstream parse is still to be fixed; tracked separately.)
- **Honesty ledger grew unbounded and bloated every prompt** (`agents/dialogue_honesty.py`, `agents/fact_ledger.py`): `record_claims()` re-recorded restated sentences every turn and `epistemic_context_note()` was appended to the system prompt on every turn. Claims are now deduplicated across turns, the ledger is pruned to a bound (verified and operator-superseded entries are never pruned), and the note is capped at 5 claims and skipped entirely for tiny models.
- **Operator overrides never applied** (`gui/dialogue_tab.py`, `agents/dialogue_honesty.py`): `DialogueHonestyService.apply_overrides()` was dead code — defined but never called. It now runs before each prompt build.
- **Live mode**: No longer stops on errors. Transport errors recover silently, duplicates skip turn and force next speaker, blocked states are part of dialogue. Added "no model selected" / "no model loaded" to transport-error detection (live mode retries instead of stopping). Duplicate threshold raised 0.92 → 0.95. Max duplicate retries 2 → 3 before pausing.
- **Token limits**: Default 512 → 4096. Per-brain env vars: `BIG_BRAIN_MAX_TOKENS=8192`, `SMALL_BRAIN_MAX_TOKENS=4096`.
- **Qwen model families**: 3.8 vs 3.6 vs 3 now distinct families (different thinking extraction: 3.8 uses `reasoning_content` field, 3.6/3 use inline `<think>` tags).
- **Model detection**: Word-boundary regex prevents "26B" from matching "2B" in compact model check.
- **Startup performance**: Lazy imports in `personas.py` — `build_system_prompt()` no longer eagerly imports `program_knowledge` at module load time.
- **DB Stats latency**: Fixed avg latency calculation to exclude error/null entries and zero-latency rows.
- **Semantic duplicate threshold**: 0.78 → 0.85 to avoid false positives on "no verified evidence" vs "no evidence".
- **Retry limits**: Hard limit of 5 total retries across all types to prevent infinite loops.
- **Naming**: All references to the prior placeholder personas replaced with the canonical
  "Edward Hurst"/"Jacob Stanley" (or custom names from env vars) across dialogue_tab.py,
  persona_naming.py, dual_brain_control.py.
- **Settings duplicate fields**: Removed duplicate wallet/cashApp from Agent Registration group (now identity only). Payout Destinations keeps the fields with distinct widget names (`cashapp_payout_edit`, `solana_payout_edit`).
- **Live Logs table**: Message column now uses Stretch mode (was too narrow). Details column interactive-resizable with 120px default. Row height auto-resizes to wrapped content. Details no longer truncated to 80 chars.
- **Live Logs Entry Details**: Max height increased from 100px → 250px. Min height 60px → 80px.
- **Live Logs splitter**: Replaced fixed layout with QSplitter (vertical, 3:1 stretch) so user can drag the divider to resize.
- **Log spam**: Fixed `UnboundLocalError` in `_append_log` — `import re` was inside conditional but used unconditionally for latency extraction. Moved to top of function.
- **DB Stats NoneType format**: Fixed `TypeError` in `refresh_db_stats` — `avg_ms` and `avg_tok_s` SQL aggregates return `None` when no data. Added `or 0` to format strings.
- **Approval queue crash on construction** (`agents/approval_queue.py`): `HumanApprovalQueue.__init__` called `self._load()`, but `_load` was never defined — any `HumanApprovalQueue(log_path=...)` raised `AttributeError`. Added the best-effort JSON restore method (a corrupt/missing log can no longer break startup).
- **Approval decisions did not notify the GUI** (`agents/approval_queue.py`): `decide()` never fired the `on_change` callback, so the Approvals panel did not refresh after approve/deny/defer. Callback now fires on every decision, matching `enqueue()`.
- **Approval queue integrity** (`agents/approval_queue.py`): `enqueue()` now assigns a fresh UUID when an item id is empty or duplicated, and `enqueue`/`decide`/`clear_all` are lock-protected so concurrent enqueues cannot corrupt the queue.
- **Dual-brain settings panel did not compile** (`gui/dual_brain_control.py`): a nested `def _on_temp_preset(...)` had been pasted inside `_build_small_brain_settings` with a mis-indented body, causing `IndentationError`. Removed the stray block; the real method already existed.
- **Tool-call response shape** (`agents/tool_calling.py`): the streaming loop assumed `choices[0].delta` and the non-streaming fallback assumed a response with `.choices`, so non-streaming response objects and edge SDK shapes raised `AttributeError: 'list_iterator' object has no attribute 'choices'`. Now handles both `message` and `delta` shapes and only accepts `str` content (non-string content previously broke `"".join`).
- **Test suite hard-crashed** (`tests/conftest.py`, new): with no `conftest.py`, any test building a Qt widget without a `QApplication` aborted the whole interpreter (exit 127, no output), so a full `pytest tests/` run died at ~9%. Added a session-scoped offscreen `QApplication` fixture; the full suite now completes end-to-end.
- **Safety-gate / dispatcher registry alignment** (`agents/safety_gate.py`, `agents/tool_calling.py`): the gate's rule table named tools that do not exist (`read_file`, `list_directory`, `query_database`, `write_file`), so every real read tool resolved to "Unknown tool" → blocked, and the SQL-validation branch was unreachable. The gate now classifies the actual dispatch registry (10 read-only + 7 mutating = all 17 tools), keeps documented legacy names as canonicalised aliases, and stays fail-closed (unknown → `BLOCKED`). `tool_calling._MUTATING_TOOLS` is now derived from `safety_gate.MUTATING_TOOL_NAMES` so the two lists cannot drift again; alignment is enforced by `tests/test_safety_gate_registry_alignment.py`.
- **Incomplete test fakes** (`tests/test_prompt_budget.py`, `tests/test_nvidia_nim.py`): objects built via `__new__` omitted attributes the production code now requires (`SmallBrainAdapter.model`; `WorkerAgent._temperature`/`_top_p`). Assertions unchanged.
- **Dialogue safety/validation regression restored** (`gui/dialogue_tab.py`): commit `1e81475` had deleted 1,144 lines of safety/validation logic — registration/account-approval gating (registration is always an external commitment), bounded prompt context (`_context_char_limit`), model-identity/publisher self-description and training-continuation rejection, failed-research fallbacks, and the tiny-model safe fallback response (`_safe_fallback_response`), plus `_on_tool_activity`, `_record_dialogue_control_state`, `_dialogue_model_blocked`, `_get_opportunity_context`. Restored on top of the newer work (persona naming, model-size estimation, UI). `tests/test_dialogue_response_corruption.py` (45 tests) passes.
- **Parallel-mode circuit breaker** (`gui/dialogue_tab.py`): added `_parallel_empty_rounds` and `_on_parallel_response_ready` so Live mode stops after two consecutive transport-error or "[<Name>: No response generated.]" rounds, with a single `live_btn` and no `parallel_btn`. `tests/test_dialogue_circuit_breaker.py` passes.
- **Test order-dependence** (`tests/test_dialogue_response_corruption.py`): the dialogue turn-budget tests assumed `DIALOGUE_TURN_MAX_TOKENS` governs, but a loaded `.env` sets `SMALL_BRAIN_MAX_TOKENS`, which overrides it by design — so the suite passed or failed depending on which test loaded `.env` first. The tests now clear the per-brain overrides so they are deterministic.
|- **Version identity reconciled** (`__init__.py`, `agents/program_knowledge.py`, `agents/evidence.py`): three version identifiers disagreed with the authoritative `version.py` (`2.1.1`). `__init__.py` `__version__` was stale at `2.0.36k`; `ProgramKnowledge.PROGRAM_VERSION` — injected into both brains' prompt context — read `2.1`; and `Evidence.create()` stamped exported evidence with a default producer version of `2.0.34aq`, a pre-2.1 lineage identifier. Evidence provenance now single-sources `version.VERSION` (with `MRBOT_VERSION` still overriding when set), so exported evidence can never carry a producer lineage older than the running application.
|- **GoalTracker in-memory SQLite** (`agents/goal_system.py`): `:memory:` databases are per-connection in SQLite, so the singleton GoalTracker lost data whenever a new connection opened. Fixed with `file::memory:?cache=shared` URI + `_connect()` helper; `_ensure_dir()` also guards `:memory:` paths.
|- **Dialogue response corruption test update** (`tests/test_dialogue_response_corruption.py`): removed 5 stale tests referencing methods deleted in the 2.1.1 refactor (`_on_tool_activity`, `_get_control_context`, `_get_opportunity_context`); added `test_stall_phrases_and_narrated_tool_calls_are_rejected` verifying `DialogueWorker._is_bad_dialogue_response` rejects stall phrases and narrated tool calls while allowing concrete evidence-grounded decisions.
|- **GitHub publish scripts restored** (`scripts/github_upload.py`, `scripts/sync_github_upload.py`): republished the previously-removed publish helpers; both are tracked and referenced by `.gitignore`.

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
- Fixed the ordinary chat tool loop so shell commands, file writes, account/payment changes, and proposal creation are refused unless an approval-capable workflow handles them.
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