# 11E — `gui/widgets/dual_brain_control.py` depth pass (3804 lines, 105 methods)

Depth-pass #31 of 83. **Zero dead of 105 — no findings.** The largest method count of any
file swept, and nothing wrong in it. This document is short by design.

---

## Structure

```
L  121-194   GPUStatusWorker      (4 methods)   — 2 s background nvidia-smi poll
L  203-212   _WheelEventFilter    (1)
L  214-242   _ModelLabelAdapter   (3)
L  245-275   _NullWidget          (6)           — ARCH-ENG-053 null-object
L  278-3774  DualBrainControl      (91 methods)
```

No module docstring — a small inconsistency against the rest of the codebase, where the
class-level and method-level docstrings are thorough.

Largest: `setup_ui` (393), `_build_llama_flag_group` (259), `_create_gpu_widget` (202),
`_apply_runtime` (173), `__init__` (102), `_build_device_panel` (92),
`_apply_hardware_tensor_options` (79), `cleanup` (75).

---

## Findings

**None.** All 105 methods are live.

---

## The architecture that makes the hardware policy unbypassable

ARCH-ENG-219's one-model-per-device rule (`brain_roster.py:26`) appears **nowhere** in this
3804-line widget. That is not an omission — it is the design, and checking it was the point
of this pass.

**The device panel assigns *roles to devices*, not *models to devices*.**
`_build_device_panel:769-771` — *"Build the Compute Devices panel: one row per detected
device with an enable checkbox and a role selector (Auto/Big/Small)."* One device, one role.
There is no control anywhere in this file for placing a second model on a GPU, so the
capacity rule cannot be overridden from here.

Placement is then **delegated, not decided**:

| step | line |
|---|---|
| compose the roster widget | `:2304-2306` — `BrainRosterPanel(self)` from `gui/widgets/brain_roster_panel.py` |
| persist the roster | `:1704-1719` — `_persist_brain_roster()` → `save_roster_from(panel)` |
| compute placements | `:747` — `placements = dr.brain_placements(assignments)` |
| apply to runtime | `:752` — `self.runtime.sync_slots(placements)` |

The widget's job ends at collecting intent; `device_registry` computes and
`brain_roster` enforces. **This confirms the layering `11j` recorded** — placement is
`brain_roster.py`'s, and the GUI neither owns nor overrides it.

**One distinction worth stating so it is not mistaken for a contradiction.** The panel's hint
text (`:789-791`) says *"≥12 GB = Big Brain, 4–12 GB = Small Brain; CPU/RAM depends on cores
+ RAM."* That looks like a different threshold from ARCH-ENG-219's ≥32 GB, but the two answer
different questions. The hint describes **which role suits a device by default**; the 32 GB
rule governs **how many models a device can host**. A 16 GB card is correctly "Big Brain" by
the first and correctly limited to one model by the second. Both are right, and the file
never needs the second because it never offers the choice the second constrains.

---

## Verified as sound

**`_build_device_panel:796-800` is the GUI half of `11j`'s hardware finding:**

```python
devices = dr.detect_devices(include_cpu=True)
# B1: surface a lost-GPU / detection diagnostic in the device panel
# AND the Live Log, so a dropped GPU is explained (with a reboot
# hint) instead of silently missing from the list.
detect_error = getattr(dr, "_LAST_DETECT_ERROR", "") or ""
```

`11j` recorded that `_LAST_DETECT_ERROR` exists precisely so *"no GPUs"* is never conflated
with *"could not ask."* **Here is where that signal is consumed** — the detection failure is
explained to the operator in the panel where the missing device would have been, rather than
the device simply not appearing. That is ARCH-ENG-115's principle (*"omitting the section is
strictly better than stating a false one"*) reaching the UI: a missing row is worse than a
missing row with a reason.

**ARCH-ENG-183 — per-row tolerance in the nvidia-smi parser (`:182-193`):**

> *"per-row tolerance. `N/A` is routine in nvidia-smi output and must not cost us every OTHER
> gpu."*

The `try/except (ValueError, TypeError): continue` wraps only the per-row parse, so one
malformed row drops one GPU rather than the whole table. Correctly scoped — the fix is at the
row level, not the table level.

**`_NullWidget` (ARCH-ENG-053, `:245-275`) is a null-object done properly**, and its docstring
names the failure it prevents:

> *"when a brain is disabled (single-GPU box, CPU unchecked) its row is not rendered, so the
> legacy `sb_*`/`bb_*` aliases have no real widget. Pointing them here makes every downstream
> `setText` / `setStyleSheet` / `setEnabled` a harmless no-op instead of **an AttributeError
> that aborts the start flow**. Any attribute access that isn't a known setter returns a no-op
> callable, so it tolerates the full range of legacy call patterns."*

The `__getattr__` fallback (`:271-275`) is the important part — it accepts *unknown* legacy
call patterns rather than enumerating them, so the next alias added elsewhere degrades to a
no-op instead of becoming a crash.

**`_snapshot_settings_values:1643` states its threading contract in the docstring:**

> *"MUST run on the GUI thread (reads QWidget `.value()`/`.currentText()`). Returns the plain
> `values` dict; **the caller decides** whether to write it synchronously (`_persist_settings`)
> or off-thread (`_persist_settings_async`). Never raises — returns `{}` on any error."*

Naming the constraint, naming both legitimate call sites, and specifying the failure mode is
the whole contract in three lines.

**`_persist_brain_roster:1710-1719` never raises and says so** — a failed roster write logs
`"⚠️ Brain roster not persisted (save failed)."` rather than propagating, because a persistence
failure must not take down the tab. The *failure is reported*, though, which is the discipline
`11t`'s AM-02 asked for and this file already meets.

**`cleanup` (75 lines) is thorough and its docstrings name their own history** —
ARCH-ENG-153 at `:3667` (*"flush any debounced roster edit before teardown"*) and `:3708`
noting that the extra-device launchers *"had no teardown at all."* A `cleanup` that documents
what it had to add is a cleanup that was written after the leaks were found.

---

## Re-verification

**`11j` confirmed at the consumer.** `_LAST_DETECT_ERROR` is read at `:800` and surfaced to
the operator — closing the loop `11j` opened by recording its existence.

**`11p` consistent.** `dual_brain_control` is one of `provider_manager`'s 15 consumers, and
the provider/GPU surface here is the operator-facing half of that same registry.

**`11d` consistent.** `11d` swept `agents/runtime/dual_brain.py` and verified the runtime's
guards; this file is the GUI that drives it (`sync_slots`, `apply_runtime`). The
architecture split — GUI collects intent, runtime enforces — holds in both.

**ARCH-ENG-219 unbypassable from the GUI — verified.** The rule appears in `brain_roster.py`
and `brain_roster_panel.py`, not here, and this file exposes no control that could contradict
it. The policy is enforced at the layer that owns placement, which is the correct place for a
rule the docstring calls *"a hardware fact, not a UI preference"* (`brain_roster.py:36`).

**`10m` confirmed.** This file is the largest consumer surface for the provider/GPU
registration that area recorded.

---

## Assessment

Zero findings on 105 methods across 3804 lines, and the more useful result is what the
absence of findings demonstrates.

Three things are worth carrying forward from this pass:

1. **The hardware policy is unbypassable by construction, not by discipline.** The device
   panel offers a *role* per device; placement is computed by `device_registry` and enforced
   by `brain_roster`. There is no checkbox an operator could tick to put two models on a 16 GB
   card, which is a stronger guarantee than any validation would give. Compare `11x`'s AQ-01,
   where `ActionPipeline` *could* be given a caller and would then have authorized a file
   write on a boolean — the difference is that here the unsafe state is **unrepresentable in
   the interface**, not merely checked at the boundary.

2. **ARCH-ENG-115's principle reaches the UI.** A dropped GPU is explained in the panel where
   it would have appeared, rather than silently absent. That is the same standard as
   `_hardware_line`'s "no confirmed device → no claim", applied to a widget.

3. **The two failure modes the codebase guards against most often are both handled here
   without ceremony** — a null-object so a disabled brain cannot abort startup, and a
   per-row parse so one bad GPU row cannot cost the others. Neither needed a large mechanism.

The only observation is cosmetic: **no module docstring**, against a codebase where
class-level and method-level documentation is otherwise thorough. On a 3804-line file whose
job is to be the operator's view of the runtime, a short header stating what it owns and what
it delegates would help the next reader find the delegation boundary — which is the single
most important thing to know about this file, and currently something a reader has to
reconstruct from seven call sites.
