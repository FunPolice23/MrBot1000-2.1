# 10q — `app/`

> **P-02 RESOLVED in v2.1.125 (ARCH-ENG-306).** `EarningMemory` now exposes
> `learning_dashboard()`, which calls every read-only aggregation (search
> strategies, platform/task/category performance, failure causes, templates,
> prediction accuracy and memory summary). The Self-Improvement tab renders that
> snapshot, so the analytics are no longer dead methods.
>
> **P-01 RESOLVED in v2.1.125 (ARCH-ENG-293).** The `__main__` entrypoint now
> calls `validate_startup_environment()` before constructing `MainWindow`,
> prints its warnings/errors, attaches the report to the window as
> `startup_validation_report`, and reports degraded mode when validation errors
> are present. The module is no longer protected, published and unreachable.

15 scripts, 7,098 lines. The application layer: the earning pipeline and its
memory system, the SQLite database, the action pipeline, provider model discovery,
and the small shared utilities.

---

## Structure and reachability

| File | Lines | Reached from |
|---|---:|---|
| `__init__.py` | 1 | — |
| `version.py` | 4 | `main`, `agents/__init__`, `program_knowledge`, `evidence` |
| `failure_log.py` | 44 | `big_brain`, `small_brain`, `chat_completion`, `dialogue_tab` |
| `text_utils.py` | 53 | `library.py` |
| `startup_validation.py` | 93 | **nothing** |
| `theme_config.py` | 212 | `main.py` |
| `earning_learning_loop.py` | 237 | `earning_pipeline.py:139-140` |
| `effects.py` | 255 | `feature_flags`, `main`, `tab_feature_builders`, `theme_ui_state` |
| `environment.py` | 196 | 6 sites incl. `approval.py`, `configuration.py` |
| `library.py` | 138 | 6 sites incl. `coder`, `analyst_worker`, `dialogue_tab` |
| `earning_pipeline.py` | 1566 | `main`, `composition_root`, `autonomous_loop` |
| `database.py` | 733 | `calling`, `comms_log`, `prompting_engine`, `main` |
| `provider_models.py` | 636 | 7 sites incl. `cost.py`, `llm.py`, `huggingface_models` |
| `action_pipeline.py` | 649 | `main.py`, `feature_flags.py` |
| `earning_memory.py` | 2281 | `earning_pipeline`, `discovery_scheduler` |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| P-01 | med | **`startup_validation.py` (93 lines) is dead — while being protected and published.** `StartupValidationReport` and `validate_startup_environment(env, log_fn)` appear only inside their own module; `validate_startup` has zero references anywhere. The file has **no module docstring**, and it is simultaneously listed in `PROTECTED_SOURCE_FILES` (`agents/brains/base_worker.py:109`) and in the public publish list (`tools/github_publish/sync_github_upload.py:137`). So a startup validator that would return `status` / `warnings` / `errors` about the operator's environment is protected from modification, shipped to the mirror, and never called. Combined with `__init__.py`'s stale `2.1.31` fallback (R-01), the project has two startup-time checks it built and does not run. |
| P-02 | med | **15 of `EarningMemory`'s 74 methods are dead, and every one has zero tests.** Unlike `Workshop` (J-02), where dead methods carried tests and read as live, these are invisible from both directions — no caller and no test. Thirteen of the fifteen are **analytical read-outs**: `get_search_strategy_stats`, `top_search_strategies`, `best_performing_task_types`, `most_reliable_platforms`, `highest_net_hourly_categories`, `time_wasting_categories`, `best_proposal_templates`, `platforms_poor_acceptance`, `task_types_high_completion`, `profitable_but_often_fail`, `recurring_failure_causes`, `strategies_to_avoid`, `category_outcome_summary`. The other two are `apply_decay` and `find_similar_opportunities`. **The memory system records comprehensively and analyses almost none of it.** The 59 live methods are dominated by writes — `record_outcome`, `record_outcome_v2`, `record_attempt`, `record_win`, `record_loss`, `record_category_outcome`, `record_task_type_outcome`, `record_strategy_result`, `record_search_strategy`, `remember_opportunity`, `remember_success`, `link_outcome_evidence`, `store_learning` — feeding twenty tables including `strategy_memory`, `failure_memory`, `success_memory`, `prediction_accuracy`, `search_strategy`, `source_memory` and `decay_log`. Every one of those tables is written and read back by nothing that an operator would see. |
| P-03 | info | **`earning_memory.py` is 2,281 lines with a single 2,046-line class.** `EarningMemory` has 74 methods over 20 `CREATE TABLE` statements plus a migration routine (`_migrate_schema`, with the `PRAGMA table_info` / `ALTER TABLE ADD COLUMN` pattern for `outcome_memory_v2` at `:570-578`). A maintainability observation rather than a defect, but it is the largest file in the repository by a wide margin and the natural home for P-02's dead analysis layer. |

---

## Why P-02 matters more than its line count

The write side being complete and the read side being absent is the exact shape of
`Workshop` (J-02) and `capability.py` (G-01), but with a sharper consequence here,
because this is the system's own learning substrate.

`outcome_memory_v2` — the append-only raw event table that ARCH-ENG-229 optimised
— is **empty**. Not because writes are broken: `record_outcome_v2` at `:808` is
live and called. It is empty because no outcome has ever completed. The
analytical methods that would explain *why* nothing completes —
`time_wasting_categories`, `strategies_to_avoid`, `profitable_but_often_fail`,
`recurring_failure_causes` — are all dead, so even with data there would be
nothing presenting it.

`find_similar_opportunities` being dead is the most consequential single omission
in that list. It is the retrieval function that would let a successful approach be
reused, and it is the difference between a memory that records and a memory that
learns. Its absence is consistent with the broader finding across this sweep: the
feedback loops that *collect* are wired (F-01's `record_outcome`, this file's 59
writers), and the loops that *consume* are not.

This is the eleventh instance of the recurring pattern, and the first where the
write side is provably healthy. `record_outcome_v2` is called, `_migrate_schema`
runs, the tables exist, the ARCH-ENG-229 aggregation is correct and live via
`earning_learning_loop.py:212` — and the question "what have we learned?" has no
implemented answer.

---

## Verified as sound

**`earning_learning_loop.py` is genuinely live and is the consumer that makes
ARCH-ENG-229's fix count.** `earning_pipeline.py:139-140` constructs
`LearningLoop(self.memory)`, and `earning_learning_loop.py:212` calls
`self.memory.compute_opportunity_metrics(...)`. This corrects a reading in `10h`:
a reachability scan presented this module as having no consumer outside `app/`,
which is true but misleading — `earning_pipeline.py` *is* in `app/`, and it is the
hub. Intra-package reachability from the hub is full production reachability.

`autonomous_loop.py:1080` independently confirms the wiring, commenting on the
real `LearningLoop` feeding *"FUTURE DISCOVERY"*.

**`environment.py` is well-guarded.** `EnvWriteRefused` is its own exception type,
and the module is *"Guarded environment-file persistence"* reached from six sites
including `approval.py` and `configuration.py` — the two places where a careless
env write would be most damaging (the approval gate's configuration, and provider
settings).

**`version.py` has the right shape for a single source of truth.** Four lines,
four consumers, and it is the module `agents/__init__.py:16` imports to avoid the
hand-maintained duplicate that caused the ~30-release drift recorded at
`__init__.py:13-14`.

**`failure_log.py` is the ARCH-ENG-109 capture helper** and is reached from all
four model-calling entry points — `big_brain`, `small_brain`, `chat_completion`,
`dialogue_tab` — so a failure is captured wherever it originates.

---

## Assessment

`app/` is the best-wired area after `agents/safety/`. Thirteen of fifteen modules
have consumers outside their own package, and the two hub files
(`earning_pipeline.py`, `earning_memory.py`) are reached from `main.py`,
`composition_root.py` and `agents/services/`.

P-02 is the finding that carries the most weight, and it should be read as a
product observation rather than a defect list. The memory system has been built
out as a *substrate* — twenty tables, append-only raw events, prediction accuracy
tracking, decay, migration — with the write path complete and correct. The read
path was never built. That is a reasonable thing to have happened (it is the
natural order of work), but it means the system currently accumulates a detailed
record of its own behaviour and cannot answer a single question about it, and the
operator has no view of that record beyond whatever individual panels render.

P-01 is a straightforward loose end with an odd combination of properties: a
startup validator that is protected against modification, published to the public
mirror, and never executed.

P-03 is recorded for completeness. `earning_memory.py` is where P-02 lives, and
if the analysis layer is ever built out, a 2,046-line class is where it will be
added — which makes the file's structure relevant to that future work rather than
just a size observation today.