# MrBot1000 architecture map

> **History note.** The previous `ARCHITECTURE_MAP.md` was 80 KB and was mostly a
> record of superseded Phase 1-9 restructuring work. It had drifted far enough
> that its complexity table listed **five modules that no longer exist at those
> paths** (`gui/dual_brain_control.py`, `gui/tab_builders.py`, `manager.py`,
> `agents/base_worker.py`, `agents/tool_calling.py`), and its executive
> assessment counted 158 modules under `agents/` (there are 227) and 23 under
> `gui/` (there are 37). A map of a codebase that no longer has that shape is
> worse than no map: it is confidently wrong. The historical detail is
> preserved in git history; this document describes the code as it is.
>
> Superseded phases are listed at the end under [Retired architecture](#retired-architecture).

## Executive assessment

MrBot1000 is a local-first desktop application: a PySide6 GUI over a
deterministic earning pipeline, with one or more local LLM "brains" (llama.cpp
by default) that propose and discuss but never authorize.

It is not unusually large for what it does — ~76k lines of production Python
across 284 modules, plus ~37k lines of tests. The complexity is **concentrated
rather than diffuse**: three GUI modules and two orchestration modules account for
roughly a fifth of the production code, and the safety/earning subsystems carry
the invariants that matter most.

The codebase's distinguishing characteristic is its **audit culture**: 157
numbered engineering tickets (`ARCH-ENG-nnn`), each with a regression test, each
recorded in a 460 KB CHANGELOG. It has genuinely caught a series of
financial-integrity defects — fabricated revenue, approval-scope laundering,
evidence laundering — by reading the code against its own stated invariants.

The recurring weakness is that **documented invariants did not always reach the
module in question**. ARCH-ENG-158 was a 14-step pipeline that hardcoded
`{"verified": True}` while two other modules in the same repository had been
hardened to refuse exactly that shape. ARCH-ENG-159 was the same laundering path
still open one level down. The pattern is not carelessness; it is that a
convention ("keep this consistent") has no mechanism behind it. The fixes in
2.1.113 replace several such conventions with checks.

## Scale

| Area | Modules | Lines | Role |
|---|---:|---:|---|
`agents/` | 227 | 49,028 | domain logic — the deterministic core |
`gui/` | 37 | 18,280 | PySide6 tab widgets (no top-level window) |
`app/` | 16 | 6,014 | application/service layer (intended Qt-free) |
`main.py` | 1 | 3,274 | launcher, `MainWindow`, composition |
**Production total** | **~284** | **~76.6k** | |
`tests/` | 270 | 36,746 | 2,437 tests, 265 subtests |
`tools/` | 4 | 825 | developer tooling (codemap generator, profiler) |

## Runtime topology

```text
main.py                                  QApplication + MainWindow (24 lazy tabs)
  │
  ├─ gui/                                tab widgets; backends only, no logic ownership
  │   ├─ builders/tab_feature_builders   40+ create_*_tab methods (3,439 lines)
  │   ├─ tabs/dialogue_tab               the peer-council surface (3,582 lines)
  │   └─ widgets/dual_brain_control      Providers & GPU (3,192 lines)
  │
  ├─ app/                                service layer
  │   ├─ earning_pipeline.py             composition root for the earning domain
  │   ├─ earning_memory.py               5-tier SQLite memory (1,836 lines)
  │   └─ database.py                     AgentDB / agent.db
  │
  ├─ agents/core/composition_root.py     one shared pipeline/portfolio/run_store
  │
  └─ N-device peer council               slot 0 = Big, slot 1 = Small, slots 2+ = extra
      agents/runtime/device_registry.py  device → slot → role → endpoint  (SINGLE SOURCE OF TRUTH)
      agents/runtime/dual_brain.py       llama.cpp lifecycle, ~40 flag fields
      agents/cognition/speaker_registry  slot → display name
```

## Package map

| Package | Files | Lines | Responsibility |
|---|---:|---:|---|
`agents/earning` | 54 | 11,975 | discovery → validation → lifecycle → execution → accounting |
`agents/safety` | 22 | 4,912 | the authorization boundary; 19 tool handlers |
`agents/services` | 14 | 3,866 | autonomous loop, run store, self-audit, code patches |
`agents/runtime` | 13 | 3,241 | device registry, dual-brain runtime, provider keys |
`agents/providers` | 13 | 3,116 | provider probing, model profiles, GGUF parsing |
`agents/knowledge` | 13 | 3,043 | prompting engine, workshop, help catalog |
`agents/brains` | 14 | 3,135 | big/small brain personas, graph-of-thought |
`agents/core` | 15 | 2,898 | EventBus, event log, cost tracker, persistence contract |
`agents/integrations` | 12 | 2,756 | web_eyes, browser, wallet, crypto |
`agents/cognition` | 15 | 2,658 | ThoughtGraph, FactLedger, coordinator, personas |
`agents/dialogue` | 6 | 1,583 | tool-calling loop, convergence plans |
`agents/discovery` | 8 | 1,388 | 10 discovery sources, scheduler, throttling |
`agents/evidence` | 8 | 1,418 | Evidence model, policy, store, provenance |
`agents/platforms` | 10 | 1,437 | platform adapters, credential vault |
`agents/autonomy` | 7 | 1,293 | registry, grants, onchain identity, heartbeat |
`agents/polish` | 2 | 246 | CLI interface |

## The earning pipeline

This is the subsystem where correctness matters most, so its stages are spelled
out. Note that **revenue is realized only from independently verified payment
evidence** — submission is not payment.

```text
DISCOVERY   discovery/discovery_engine.py    10 sources, per-source throttle,
                                             dedup, failure isolation
VALIDATION  opportunity_models              title/ref/amount/currency checks
            earning/validator.py            capability verdict (never LLM)
ECONOMIC    services/autonomous_loop.py     economic_policy gate (ARCH-ENG-155)
GATES       safety/gates.py                 10 human-gate types
EXECUTE     earning/executor.py             14 steps, steps 12-14 evidence-gated
                   (ARCH-ENG-158)
SUBMIT      earning/platform_submitter.py   SubmissionRamp + throttle
VERIFY      autonomous_loop._stage_verify   SUBMITTED->PAID needs L3+ external
RECORD      evidence/evidence_store.py      append-only, 25 columns
BOOK        earning/economic_accounting.py  verified vs pending vs unverified
```

## Persistence

Seven declared authorities (`agents/core/persistence_contract.py`):

| Store | Authority | Classification |
|---|---|---|
`earning.db` | earning lifecycle, evidence, accounting | authoritative |
`earning_memory.db` | opportunity learning memory | authoritative |
`autonomous_runs.db` | durable run + idempotency ledger | authoritative |
`agent.db` | thoughts, events, settings, evidence | authoritative |
`goals.db` | goal subsystem state | subsystem |
`opportunity_portfolio.db` | queue projection, work status | projection |
`dual_brain.db` | runtime state, conversation cache | projection |

Since ARCH-ENG-163 the contract is asserted against the filesystem, not just
against its own inputs. **One known operator decision remains open:**
`agent.db` holds a VERIFIED L5 `onchain_balance_delta` evidence row that the
earning path cannot see, because the earning path reads `evidence` from
`earning.db` (0 rows). It is baselined in the audit and deliberately not
auto-migrated — operator data should not move as a side effect of a lint fix.

## Complexity concentration

Largest production modules:

| Module | Lines | Concern |
|---|---:|---|
`gui/tabs/dialogue_tab.py` | 3,582 | dialogue surface + `DialogueWorker` QThread |
`gui/builders/tab_feature_builders.py` | 3,439 | all 40+ `create_*_tab` methods |
`gui/widgets/dual_brain_control.py` | 3,192 | providers, subprocesses, GPU panels |
`app/earning_memory.py` | 1,836 | 5-tier memory domain |
`gui/workers/provider_lifecycle_backend.py` | 1,448 | brain start/stop/probe |
`app/earning_pipeline.py` | 1,350 | earning orchestration |
`agents/services/autonomous_loop.py` | 1,169 | the 10-stage autonomous loop |
`agents/runtime/dual_brain.py` | 1,112 | llama.cpp lifecycle |
`agents/earning/opportunity_lifecycle.py` | 952 | lifecycle state machine |
`gui/widgets/provider_config_widget.py` | 931 | cloud/local provider forms |

Largest single functions (AST-measured):

| Function | Lines |
|---|---:|
`tab_feature_builders.create_settings_tab` | 895 |
`chat_completion.chat_with_tools` | 496 |
`dialogue_tab._is_bad_dialogue_response` | 484 |
`dialogue_tab._on_response_ready` | 398 |
`dual_brain_control.setup_ui` | 393 |
`small_brain.chat` | 307 |
`earning_memory._init_db` | 278 (DDL) |

## An AST dead-code sweep reported mostly false positives. Do not re-run one blind.

A reachability sweep (AST import graph, 1334 edges, 579 modules) reported ~2,600
lines of dead code. A second, trap-aware pass overturned most of it. Recorded
here because the failure mode is expensive and the correct answers look wrong at
first glance.

**Reported dead, actually live ? deleting these would have broken running code:**

* `agents/earning/executor.py` `_step1`..`_step13` ? all 14 are called from
  `execute()` at `executor.py:169-202`. Zero dead symbols in the file. This was
  the single worst error, and it would have hit `app/earning_pipeline.py`.
* `agents/platforms/*` (6 files, ~960 lines) ? `agents/platforms/__init__.py:5-17`
  eagerly re-exports them, and Python runs `__init__` before *any*
  `agents.platforms.X`. `registration_panel.py:59` imports `credential_vault` from
  the package, so all six load on every panel build. Deleting them as the report
  instructed gives `ModuleNotFoundError` on first panel construction.
* `agents/runtime/stats.py` ? `agents/runtime/__init__.py:3` imports it eagerly.
  Deleting breaks `management_tab.py` at startup.

**Reported dead in bulk, actually mostly live:** `app/earning_memory.py`
("26 of 81" ? really **5 of 78**), `app/database.py` (23/35 ? **12/38**),
`app/earning_pipeline.py` (25/56 ? **12/53**), `shared_context.py` (14/26 ?
**6/24**), `management_tab.py` (10/13 ? **6 of 13**).

**Genuinely dead, and removed:** `agents/services/workflow_engine.py` (229,
superseded by the live `workflow_planner.py`), `agents/core/cost_tracker.py`
(315, superseded by `agents/safety/cost.py`), `agents/polish/` (294 ? its
`cli_interface.py` has a `main()` but **no `__name__` guard**, so the
`python -m` command its own docstring advertises silently no-ops), and seven
`workshop.py` module-level shims.

### Traps. Each of these reports as dead, and every one is live.

1. **Qt slots connected by name.** Four `_on_*` handlers in `management_tab.py`
   are `.connect()`ed at `:213,217,261,289`. A token count sees `def` + `connect`
   and calls it two references.
2. **Eager package `__init__` re-exports.** Python executes `__init__.py`
   before any submodule, so an eagerly-exported module is live whenever the
   package is touched at all.
3. **Methods called from sibling methods.** `validators._check_*` and
   `gates._has_*` are all live ? every one is invoked internally. Name-based
   reachability sees a private method with no external caller and calls it dead.
4. **`PROTECTED_SOURCE_FILES` in `base_worker.py` is a basename denylist for
   `safe_write_file`, not an import list.** `"coder.py"` appearing there does not
   make `agents/services/coder.py` live ? it is live for an unrelated reason
   (ARCH-ENG-204), and the two must not be confused.
5. **`agents/__init__.py:37-44` lazy `__getattr__` / `import_module`.**
6. **`main.py` builds tabs by method name**, never by direct call.
7. **Constructor-only registration** ? a class never instantiated in production
   may still be selected by a config/JSON key or a registry dict.
8. **`__del__` and `@dataclass` hooks** are called by CPython with zero name
   references. `Event.__post_init__` is live; any name-based tool flags it.

The rule that follows: **"no importers" is necessary but never sufficient.**
Absence of an importer must be checked against all eight before a deletion.

## `DEADCODE_REPORT.md` was deleted ? it recommended deletions that break things

It sat at the repository root claiming "61 files (4816 lines) ? verified dead:
no live importer, no test, no dynamic ref". Two of its verdicts were checked and
both are wrong in a way that would have cost real functionality:

* **"delete `agents/platforms/` (whole pkg)"** ? `base.py` is live:
  `tests/safety/test_trust_boundary.py:8` does
  `from agents.platforms.base import PlatformAdapter`. The package is also live in
  the GUI (`gui/panels/registration_panel.py` imports `credential_vault`). Deleting
  it as instructed breaks a safety test and the registration panel.
* **"`agents/earning/` is LIVE via `gui/earning_tab.py`"** ? that file no longer
  exists, so the stated justification is void. The conclusion happens to be right:
  114 files import `agents.earning.*`. Right answer, unverifiable reasoning.

It also named files that do not exist at all (`agents/tool_registry.py`,
`agents/payments.py`, `agents/cost_guard.py`, `agents/cognition.py`), so it was
written against a tree that has since been restructured.

It was deleted rather than corrected because a stale deletion list is worse than
none: someone acting on it removes live code, and the resulting test failure
points at the safety suite rather than at the document. Current dead-code
findings live in the CHANGELOG for the release that established them.

**If a dead-code sweep is repeated, these are the traps in this codebase.** A
grep for importers reports all of the following as dead, and every one is live:

1. Qt slots connected by name ? `wc` counts miss `.connect(self._on_x)`.
2. `agents/__init__.py:37-44` lazy `__getattr__` / `import_module`.
3. `main.py` builds tabs by method name, never by direct call.
4. `PROTECTED_SOURCE_FILES` in `base_worker.py` is a **basename denylist for
   `safe_write_file`**, not an import list. `"coder.py"` appearing there does not
   make `agents/services/coder.py` live.
5. Agent tools reach modules through `get_workshop().method()` ? the module-level
   shims in `workshop.py:811-842` are genuinely dead, the class behind them is not.
6. `scripts/` and `tools/` are operator-facing utilities, not library code.

## The workshop and the skill library

`D:\ai_workshop` (configurable via `MRBOT_WORKSHOP_ROOT`) is the personas'
shared workspace. `agents/knowledge/workshop.py` is 889 lines covering
proposals, research, scripts, applications, accounts, payment methods,
deliverables, templates, notes and search.

**Two things were complete and invisible, both fixed in v2.1.114.**
`get_workspace_summary()` had zero callers, so the personas could not learn the
workshop existed. `agents/knowledge/skill_index.py` is new, because 25 skill
documents across both the workshop (17) and the repository (8) sat on disk
unreadable by the application.

Three design decisions worth keeping:

* **Index, not payload.** The skill bodies total 183 KB (mean 10.7 KB); the
  name-plus-when-to-use lines total ~5.7 KB. The prompt gets the index and
  `read_skill` fetches a body on demand -- the same shape as the opportunity
  board, for the same reason.
* **Two schemas, one index.** Workshop skills carry `description` in frontmatter;
  repository skills carry a `Trigger:` line instead. Handling only the first would
  have found the document skills and missed the eight the earning pipeline needs.
* **Skill text is untrusted.** Some skills are fetched from remote platforms
  (`workshop/skill_md_cache/`), so the framing states that a skill document is
  instruction text that grants no permissions, and `read_skill` resolves by name
  rather than by path.

**Open:** `D:\ai_workshop\Data\agent.db` is a *second* `agent.db`, separate from
the repository's. Which is authoritative should be decided before anything indexes
across both.

## Known layering violations

These are real and worth naming; none is currently a live defect.

- `gui/builders/tab_feature_builders.py` constructs a bespoke `_Store` shim
  reimplementing the run-store interface, and does `import sqlite3` inside a
  nested closure.
- `gui/widgets/dual_brain_control.py` enumerates and kills processes by port
  from inside a widget.

Resolved in v2.1.114: `app/` **is** Qt-free. `app/ui.py` had imported 39 PySide6
names at module level while declaring zero classes and instantiating zero
widgets — every one of them unused — so it was not architecturally leaking so
much as misfiled. It is now `gui/theme_ui_state.py`, and a test asserts no
module under `app/` imports PySide6 at module scope. (`app/effects.py` was
audited at the same time and is already compliant: its Qt imports are
function-local and guarded.)

### `create_settings_tab` builds ~340 lines of widgets that are never displayed

`gui/builders/tab_feature_builders.py:create_settings_tab` (895 lines) constructs
four `QGroupBox`es — `cloudg`, `localg`, `llamacppg`, `ollama_box` — and adds
**none** of them to a layout. `ollama_box` is additionally `hide()`n explicitly.
They survive because `save_settings` and `populate_ollama_model_combos` read
attributes off the widgets inside them.

**The risk is higher than a line count suggests.** An audit initially rated this
"delete 140 lines, low-medium risk". Ground truth: `main.py` reads five of those
attributes across fourteen call sites —

| attribute | read at |
|---|---|
| `self.ollama_model_combo` | main.py:2379, 2503, 2566-2580, 2621-2627, 2717, 2723, 2919 |
| `self.ollama_chat_model_combo` | main.py:2504, 2567-2581, 2622-2629, 2718, 2724, 2918 |
| `self.ollama_role` | main.py:2717 |
| `self.ollama_hide` | main.py:2718 |
| `self.refresh_ollama_btn` | main.py:2546 |

So the region cannot simply be deleted; the widgets must first be re-homed onto
hidden containers that are never laid out, and the Save button, the model
dropdown and its refresh path must be covered by tests first. That is a real
refactor, not a cleanup.

Also duplicated inside the same method: `MRBOT_FX_*` parsing exists in three
places (`app/effects.py`, `_env_bool`/`_seed_fx` here, and inline
`.lower() == "true"`), `ALLOW_WEB_DISCOVERY` is triplicated, the
`FILENAME_BLOCKLIST`/`BLOCKED_MIME_TYPES` defaults duplicate
`agents/brains/base_worker.py`, and the four-line "caption note" idiom repeats
30 times. Duplicated *logic* is the defect; a smaller function is only tidiness.

### `DualBrainControl(ProviderLifecycleBackend, QWidget)` — documented as a mixin, left alone

Measured: the backend has 64 methods and the widget 104, with only **two**
overlapping names (`_log`, `cleanup`). No method is duplicated — this is a clean
horizontal split, not a fork.

But it is not really a base class. The backend references 115 distinct
`self.<attr>`; only 48 are defined in the backend. The other 67 live on the
widget: 12 widget *methods* (`_set_loading` ×19, `_record_start_failure` ×6,
`_repopulate_model_combo` ×6, …) and 55 data attributes.

Converting to composition would be a **rename, not a refactor**: passing the
widget as `self` is semantically identical to the mixin. It would mean rewriting
~180 `self.` sites inside the backend for zero architectural gain, against a
large test surface that already subclasses and monkey-patches it. Real
decoupling needs a `Protocol` view object covering 55 attributes and 12 methods,
which is a rewrite.

The honest recommendation is to make the coupling **explicit** rather than
accidental, and leave the structure alone until someone can own the rewrite.

Resolved in v2.1.114: `gui/tabs/dialogue_tab.py` opened three operator SQLite
databases **on the GUI thread** every turn (with `with sqlite3.connect(...)`,
which does not close the handle, and the 5-second default busy timeout — up to
~15 s of frozen window), and forked `nvidia-smi` from the Qt event loop on the
same path. Both now use a bounded timeout with explicit closes plus a short TTL
cache, so the worst case is bounded once per cache window rather than every turn.
That file remains the largest module in the tree at 3,600+ lines.

## Error handling

141 `except Exception` sites in production code, 200+ in `gui/` alone. The
dangerous subset is not the count but where the swallow **changes a safety
outcome**:

- `provider_rate_limiter._calls_today` **fails open** — a DB error lifts the
  daily provider cap.
- `comms.py:441,454` silently hides EventBus handler failures.
- `personas.py:136` swallows the knowledge-engine import, producing a silently
  degraded system prompt.

There are **no `TODO`/`FIXME`/`XXX` markers** anywhere. Work is documented as
dense `ARCH-ENG-nnn` comments inside function bodies, which inflates function
length without adding structure — a real contributor to the table above.

## What is genuinely healthy

- `agents/evidence/evidence_policy.py` — the verification policy is
  allow-list based (`ARCH-ENG-065` replaced a deny-list that let
  `method="heuristic"` reach VERIFIED@L4).
- `agents/safety/handlers.py::_is_approved` — accepts only a real `Evidence`,
  never a dict, with the reasoning written down at the call site.
- `tests/conftest.py` — redirects `.env`/`settings.json`/DBs to temp and
  byte-compares at session end, born from a real incident where 120 fabricated
  `"I earned $9,999.00"` rows landed in the live database.
- `agents/runtime/device_registry.py::_run_nvidia_smi` — the hardened
  subprocess invocation (ARCH-ENG-116); now the single nvidia-smi call site.

## Test suite

2,437 tests / 265 subtests / 11 skipped, ~6 min. Heavily unit-level with real
mocks; the GUI has smoke plus narrow behavioural coverage only. `dialogue_tab.py`
(3,582 lines) and `tab_feature_builders.py` (3,439) are exercised only
indirectly. No coverage tooling is configured.

## Conventions now enforced by tests

Each of these was a convention; each is now a check.

| Property | Enforced by |
|---|---|
every third-party import is in a manifest | `test_arch_eng_160_dependency_manifests.py` |
no undeclared / shadow SQLite stores | `test_arch_eng_163_persistence_authority.py` |
a recorded CHANGELOG fix is present in HEAD | `test_arch_eng_150_recorded_fix_present.py` |
version authority is single-sourced | `test_arch_eng_117_version_authority.py` |
a PAID transition needs L3+ evidence | `test_arch_eng_158_executor_payment_gate.py` |
mutating tools require the dispatch capability | `test_arch_eng_164_legacy_tool_dispatcher.py` |
an approval id is verified, not asserted | `test_arch_eng_165_verified_approval_scope.py` |
shared queues are locked; one nvidia-smi call | `test_arch_eng_166_shared_state_concurrency.py` |
the source root carries no one-shot debris | `test_arch_eng_167_root_hygiene.py` |
a worker never shadows an inherited Qt signal | `test_arch_eng_168_qt_worker_lifecycle.py` |
stop only kills processes we launched | `test_arch_eng_171_port_kill_and_settings_atomicity.py` |
a tool that did not run is not shown as run | `test_arch_eng_173_tool_status_honesty.py` |
reset invalidates in-flight turns; no GUI stalls | `test_arch_eng_174_gui_thread_and_reset.py` |
every GPU index gets its own panel | `test_arch_eng_177_gpu_panel_and_provider_truth.py` |
provider status is not monotone | `test_arch_eng_177_gpu_panel_and_provider_truth.py` |
a start guard is released on every path | `test_arch_eng_177_gpu_panel_and_provider_truth.py` |
reasoning is never returned as the answer | `test_arch_eng_180_cot_leak_and_teardown.py` |
cleanup reaches the mixin's worker teardown | `test_arch_eng_180_cot_leak_and_teardown.py` |
no `QTimer` from a raw thread | `test_arch_eng_180_cot_leak_and_teardown.py` |
the Progress panel can actually show phases | `test_arch_eng_189_progress_and_decision_history.py` |
a repeated decision is detected, not just repeated text | `test_arch_eng_189_progress_and_decision_history.py` |
`app/` imports no PySide6 at module scope | `test_arch_eng_191_arch_invariants.py` |
a sort key over operator-written data never raises | `test_arch_eng_191_arch_invariants.py` |
no call to a method that does not exist, behind a bare `except` | `test_arch_eng_191_arch_invariants.py` |
a backend mixin declares what its host must provide | `test_arch_eng_194_mixin_contract.py` |
every settings key is populated before the .env write | `test_arch_eng_195_settings_persistence.py` |
a hidden control cannot overwrite a visible one | `test_arch_eng_195_settings_persistence.py` |
an early settings edit is deferred, not dropped | `test_arch_eng_195_settings_persistence.py` |
the workshop is announced to the personas | `test_arch_eng_198_workshop_awareness.py` |
the skill index carries no bodies; both formats parse | `test_arch_eng_199_skill_index.py` |
skill text grants no permissions | `test_arch_eng_199_skill_index.py` |

### A recurring failure mode worth naming

Five of the defects in the GUI audit (v2.1.114) were the *same* mistake in
different clothes: a dispatch that assumed only two values existed.

```python
getattr(self, f"gpu0_{suffix}", None) if idx == 0 else getattr(self, f"gpu1_{suffix}", None)
```

Every GPU panel setter, every widget-creation branch, and every provider-status
merge assumed a two-element world in an application built explicitly for an
N-device roster. The result was a panel that silently showed two GPUs' data on
a three-GPU box, and a provider status that could never report "stopped".

When a subsystem is N-way by design, every branch on an index is a place to
enumerate the cases that exist and refuse the ones that do not. The guards above
now assert the third case rather than trusting the second.

## Retired architecture

Removed in v2.1.78-79 — see `docs/LEGACY_AUDIT.md`:

- the central "CEO Manager" (`ManagerThread`, `SummarizerThread`)
- specialized worker teams (`JobSearchWorker`, `AnalystWorker`, `CoderWorker`)

Superseded by the N-device peer council plus `EarningPipeline`. Nine stale
SQLite files from that era were quarantined under
`.mrbot_backups/arch_eng_163_orphan_stores/` (ARCH-ENG-163).

## Prior restructuring phases (record, not current architecture)

Phase 1 compatibility contracts · Phase 2 provider/app-service extraction ·
Phase 3 tab construction · Phase 4 tool-calling boundary · Phase 5 legacy worker
runtime · Phase 6 library decomposition · Phase 9 manager orchestration.
All are complete; their detail lives in git history rather than here.

## Suggested next work

In rough dependency order — each step makes the next one safer.

1. **`app/` Qt leaks** (`ui.py`, `effects.py`) — small, unblocks headless
   service-layer testing.
2. **GUI-thread SQLite in `dialogue_tab.py`** — route through
   `db_query_worker.py`; removes the last raw DB access on the UI thread.
3. **Split the three largest functions** (`create_settings_tab` 895,
   `chat_with_tools` 496, `_is_bad_dialogue_response` 484). Each is a
   mechanical extraction with tests already in place.
4. **Decide the `agent.db` → `earning.db` evidence migration** — the one open
   data-authority question, needing an operator decision.
5. **Fail-closed sweep** — `provider_rate_limiter` and the two silent swallows
   in `comms.py` / `personas.py`.
6. **Coverage tooling** — there is currently no way to see the untested
   20% of the GUI from a number.