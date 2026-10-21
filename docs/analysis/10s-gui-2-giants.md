# 10s — `gui/` (part 2: substance of the three giants)

> **R-02 RESOLVED in v2.1.125 (ARCH-ENG-305).** The ten silent `save_settings`
> handlers now call `gui.error_collector.record_gui_error()` with a stable
> section name. A failed control still does not abort the rest of the save, but
> it is logged and visible in `gui_error_snapshot()` instead of disappearing.
>
> 12,100 lines across `tab_feature_builders.py` (3,898), `dual_brain_control.py`
> (3,804) and `dialogue_tab.py` (4,398). Reviewed at method level, which is where
> the findings are.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| R-01 | med | **Two complete tabs are built and never appear.** `main.py:1515-1538` lists exactly 24 tabs in `tab_specs`. Neither *Collaboration* nor *Diagnostics* is among them, and `create_collaboration_tab` (`:226`, 41 lines) and `create_diagnostics_tab` (`:937`, 59 lines) appear **nowhere else in the codebase** — verified by exhaustive occurrence of both names. So `gui/tabs/collaboration_tab.py` (183 lines, `CollaborationTab`) is built by a builder the app never calls, and the diagnostics tab likewise. Two independent signals that these were once wired and have since been dropped: `_bridge_goal_to_collaboration` (`:108`, 8 lines) and `_bridge_goal_to_dialogue` (`:117`, 8 lines) are now dead stubs, and `help_catalog.py:13` still documents the collaboration tab as a feature. **The Diagnostics tab is the more consequential of the two**, because `refresh_diagnostics` (`:1524`, 116 lines) is still live and wired to `main.py:2155` — diagnostics data is computed on a timer and displayed nowhere. |
| R-02 | med | **`save_settings` is 467 lines with 10 silently-swallowing handlers.** `main.py:2697-3163`. Of its 16 `except Exception` blocks, **10 swallow** — `pass` at `:2894`, `:2909`, `:2917`, `:2923`, `:2996`, `:3075`, `:3085`, `:3114`, `:3145`, and `continue` at `:3028`. Six log (`[FX]`, `[llama.cpp]`, `[Settings] provider list merge failed`), and `:3063` is explicit: *"Never let one malformed control abort…"*. **This corrects R-03**, which recorded "13 silent excepts": the accurate figure is 10 of 16, and there are zero bare `except:` — every handler is at least typed. The audit's substance stands; its count was wrong. |
| R-03 | med | **`create_settings_tab` is a 997-line method.** `tab_feature_builders.py:1669-2665` — the largest single method in the repository, in a 3,898-line mixin, in a package with no other file over 1,000 lines except `dialogue_tab.py`. It builds every operator control: provider lists, feature toggles, theme, llama.cpp flags, device settings. It has **zero** exception handlers (verified) and therefore no internal error isolation — a failure in one control's construction aborts the rest of the Settings tab. The next-largest methods in the same mixin are `create_opportunities_tab` (229), `create_file_browser_tab` (225), `create_social_activity_tab` (216) and `create_db_stats_tab` (176), so this is an outlier rather than a house style. |
| R-04 | low | **`dual_brain_control.py` has no module docstring** — 3,804 lines, 95 methods across five classes, and the largest single method in the file is `setup_ui` at **393 lines**. Given that this is the operator's primary hardware control surface and that `DualBrainControl` implements the device-assignment logic your hardware policy depends on, the absence of any description of its responsibilities is a real gap in navigability. (`gui/widgets/dual_brain_control.py` is the only one of the three giants without a docstring.) |
| R-05 | info | **Two small dead methods inside `FeatureTabBuildersMixin`**, both with zero tests: `_portfolio_contains_duplicate` (`:3417`, 16 lines — a dedup helper for the Opportunities tab, with `_portfolio_contains_duplicate` superseded by `_selected_opportunity_entries` at `:3542`) and `_selected_opportunity_entry` (`:3537`, 4 lines). |

---

## Verified as sound

**`DualBrainControl` has zero dead methods — all 90 are wired.** This is the
best-wired large class in the repository, and it is the one that carries the
operator's hardware constraints: `_apply_plan_device_assignment` (`:713`),
`_apply_hardware_preset` (`:529`), `_adapt_preset_for_hardware` (`:556`),
`_apply_hardware_tensor_options` (`:571`), `_sync_gpu_hardware_controls` (`:651`),
`_stop_brain_on_disabled_device` (`:930`) and `_sync_role_enabled_to_env` (`:891`).
It also pairs each change with a re-apply and a snapshot
(`_snapshot_settings_values` `:1640`, `_persist_brain_roster` `:1704`,
`_replay_pending_slot_applies` `:1434`), and tears down cleanly (`cleanup` `:3664`).

**Its GPU telemetry is properly off the GUI thread.** `GPUStatusWorker` (`:121`)
with `_get_gpu_status` (`:146`) runs the probe in `run()`; the UI receives results
through `_on_gpu_status_updated` (`:2861`, 73 lines). `pause_background` (`:2804`)
and `resume_background` (`:2841`) exist for ARCH-ENG-230's timer-gating work.

**VRAM estimation is surfaced to the operator rather than hidden.**
`_estimate_vram_background` (`:3105`) → `_on_vram_estimate_ready` (`:3118`) →
`_render_vram_estimate` (`:3124`), with per-slot accessors `_get_context_for_gpu`
(`:3052`), `_get_model_name_for_gpu` (`:3062`) and `_get_model_vram_for_gpu`
(`:3081`). So the clamp from `agents/runtime/dual_brain.py` (M-03) has a UI surface
even though the operator's `*_MODEL_PATH` is unset and the fallback tier path is
what actually runs.

**`FeatureTabBuildersMixin` is 63 of 67 methods live**, and its dead set is
disproportionately small for a 3,898-line file.

**`dialogue_tab.py` separates its honesty checks into module-level predicates** —
`_is_empty_model_response`, `_is_transport_error_text`,
`_is_empty_response_text`, `_decision_signature` — rather than burying them in the
tab class. That is the same discipline visible in
`agents/dialogue/chat_completion.py` (10e).

---

## Assessment

`gui/` holds up under method-level review considerably better than `agents/earning/`
or `agents/knowledge/` did. `DualBrainControl` is flawless on reachability,
`FeatureTabBuildersMixin` is 94% live, and `dialogue_tab.py` is 95% live.

R-01 is the finding worth acting on, and it is a different failure mode from
everything else in this sweep. Nothing here is mis-wired or half-wired in the
mechanical sense: two tabs were built correctly, and then removed from the list
that creates tabs. The leftovers are the tell — two 8-line bridge methods now
calling nothing, a `refresh_diagnostics` still on a timer, and a help catalog
still documenting a tab that no longer appears. **The operator's view of the
product is out of sync with the product**, in the same class as D-01's inert
crypto toggle and I-02's unwired registration URL.

R-02 is a correction to a finding already recorded, which is worth doing explicitly:
the audit's substance was right and its number was wrong (10 silent of 16, not 13),
and `create_settings_tab` — which one might reasonably have assumed held those
handlers — has none at all.

R-03 and R-04 are structural. A 997-line method and a 3,804-line undocumented
module are both defensible at this scale in a GUI layer, but the Settings tab is
the operator's control surface for everything in this report, and it is the least
navigable and least fault-isolated file in the application.