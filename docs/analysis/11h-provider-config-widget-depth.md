# 11h — `gui/widgets/provider_config_widget.py` depth pass (972 lines, 33 methods)

> **AB-01 RESOLVED in v2.1.125 (ARCH-ENG-275).** The hidden `ollama_box` and its
> hidden combos/role selector/hide toggle are deleted. `ProviderConfigWidget`
> (persisting each model as the operator changes it) and `.env` are the single
> writer of `OLLAMA_MAIN_MODEL`/`OLLAMA_CHAT_MODEL`, and `MainWindow` reads them
> through `_active_ollama_models()` with the first-run `OLLAMA_MODEL` fallback.
> No hidden widget can overwrite a visible choice because there is none.
>

Depth-pass #8 of 83. **Zero dead of 33.** A provider configuration surface that does
runtime switching correctly, wrapping a hidden-widget residue documented by
ARCH-ENG-196.

---

## Structure

```
L   60-789   class ProviderConfigWidget    (25 methods)
L  792-870   class CloudProviderPanel      (3 methods)
L  873-965   class LocalProviderPanel      (5 methods)
```

Docstring: *"Allows switching cloud/local providers at runtime without restart."*

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AB-01 | low | **A hidden, never-visible widget still participates in the save path — guarded, not retired.** ARCH-ENG-196 documented a double-writer defect precisely, at `main.py:2785-2801`: two writers, same keys. `ProviderConfigWidget._on_action_clicked` writes `OLLAMA_MAIN_MODEL` / `OLLAMA_CHAT_MODEL` from the **visible** widget the moment the operator picks a model; `save_settings` then writes **the same keys** from `ollama_model_combo`, which lives inside `ollama_box` — *"a QGroupBox that is `hide()`n at `tab_feature_builders.py:2055` and never added to any layout."* The documented consequence: *"the operator picks a model in Providers & GPU, it persists, and then the next 'Save All' in Settings writes the hidden combo's build-time seed over it. **The choice silently reverts, and the revert is invisible: both writers report success.**"* The guard exists — *"ARCH-ENG-196: DO NOT LET A HIDDEN WIDGET OVERWRITE THE VISIBLE ONE"* — and `main.py:2800` states the principle: *"The hidden widget cannot express operator intent -- it is not visible, so nobody has changed it since the tab was built."* But the widget itself remains, is still named by `_save_provider(...)` at `:2779`, and still holds the same keys. **The defect is prevented rather than eliminated**, so the next writer to be added to this path has to know about the rule rather than merely be unable to break it. |

---

## Verified as sound

**The runtime switch is genuinely live end to end.** `ProviderConfigWidget` is
constructed at `tab_feature_builders.py:1749` and its `provider_changed` signal is
connected at `:1750` to `_on_provider_widget_changed` (`:3849`). That handler does
real work: on a local-route change (`:3858`) it rebuilds the shared runtime via
`DualBrainRuntime.from_env()` and refreshes the Providers & GPU panel
(`panel._apply_runtime()`, `_repopulate_model_combo()` ×2, `_refresh_provider_status()`);
it applies `model:` selections to `ProviderManager` (`:3875-3879`); it assigns GPUs via
`assign_provider_to_gpu` (`:3880-3882`); and it invalidates the worker's provider
registry (`:3890-3894`) so the change takes effect for subsequent LLM calls.

**Two real bugs are documented as avoided, with the mechanism named.** `:3884-3886`:
*"ProviderConfigWidget has already applied the new state. Do not toggle it a second
time here or an Enable click becomes Disabled."* And `:3888-3889`: *"Keep the user's
toggle/model state; probing is performed by the provider widget's refresh path and
must not overwrite an enable click."* Both are the kind of ordering hazard that
regresses silently, and both are recorded rather than merely fixed.

**`tab_feature_builders.py:2151/2159` records the consolidation rationale** — that
`ProviderConfigWidget` is *"the visible Settings"* surface and that legacy provider
combo sections remain only for compatibility.

---

## Re-verification

**No earlier finding is contradicted.** The `10s` observation that `dual_brain_control.py:457`
points at *"the path is ProviderConfigWidget (tab_feature_builders.py:1910)"* is
consistent with what is wired here.

**M-03 unaffected.** This widget configures *which* provider and model runs; it does
not set context windows, so the VRAM-clamp fallback finding is untouched.

---

## Assessment

Zero dead of 33 in a widget whose whole job is runtime reconfiguration, and the
handler it drives does four distinct kinds of real work. The provider surface is the
best-evidenced "runs without restart" claim in the codebase — and notably it does so
by *rebuilding the runtime object* (`DualBrainRuntime.from_env()`) rather than
mutating shared state in place, which is the harder and safer of the two approaches.

AB-01 is a residue rather than a defect. ARCH-ENG-196 diagnosed the double-write
exactly, with the reasoning and the failure narrated; the guard prevents it; the hidden
widget remains. That is a defensible stopping point — removing a widget that other
save paths still reference is a larger change than the bug warranted — but it should
be recorded, because the protection is a rule in a comment rather than a structure,
and AB-01 is what a future second writer would have to discover the hard way.

Together with `11g` (0 dead of 30 in the safety handlers) this file is the second
consecutive perfect result, and both are in the operator-facing control plane. That is
consistent with the overall shape of the depth pass: the deeply-wired code is the
safety-critical and control-critical code, and the dead code clusters in the
earning-memory and parallel-implementation layers (`10q`, `11c`, `11f`).