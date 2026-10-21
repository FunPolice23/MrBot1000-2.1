# 11b — `gui/workers/provider_lifecycle_backend.py` depth pass (1,771 lines, 63 methods)

> **LOW TIER CLOSED in v2.1.125.** V-01 + V-02 (ARCH-ENG-252/253): the
> unreachable temperature-preset table (`_on_temp_preset`) and the duplicate
> llama model probe (`_get_llama_model`) are deleted. Both were the only dead
> members this pass recorded; the live provider lifecycle is untouched.
>

Depth-pass #2 of 83. **61 of 63 methods live** — one of the best-wired large
classes in the repository. Two dead methods, both small, neither on a safety path.

---

## Structure

```
L   57-113   class ProviderLifecycleHost (Protocol)   -- 48 declared members
L  162-1768  class ProviderLifecycleBackend            -- 63 methods
```

Composed as `DualBrainControl(ProviderLifecycleBackend, QWidget)`
(`dual_brain_control.py:278`) — the backend is a **base class**, not a delegation,
so its 63 methods are directly on the widget. The comment at
`dual_brain_control.py:3722-3723` records the consequence: *"`DualBrainControl`
mixes the backend in as a base class, and `ProviderLifecycleBackend.cleanup` holds
the…"* — so the teardown contract spans both classes.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| V-01 | low | **`_on_temp_preset` (`:1150`) is dead — a six-entry temperature-preset table with no UI.** The handler maps `{"0.0 (Precise)", "0.3 (Low)", "0.5 (Default)", "0.7 (Medium)", "1.0 (Creative)", "1.5 (Wild)"}` onto a `QDoubleSpinBox` and calls `_persist_settings()`. It has **exactly one reference in the entire codebase — its own definition**. No combo box is wired to it. This is a mild instance of the sweep's recurring pattern: the *mechanism* below it is live (`main.py:3035` reads `temperature_spin`, `main.py:3143` passes `self.worker._temperature`, and `base_worker.py:313` / `big_brain.py:77` / `small_brain.py:56` all read the env var), so the operator can still set temperature numerically. Only the named-preset convenience layer is unwired. Worth recording mainly because it is the fourth *operator-facing control that exists but does nothing* (D-01, R-01, and the earlier two), and because a reader would reasonably assume "Wild" and "Precise" are available in the UI. |
| V-02 | low | **`_get_llama_model` (`:235`, 14 lines) is dead.** Queries `http://127.0.0.1:{port}/v1/models` via `urllib.request` with a 10 s timeout, prefers a named model if present, else the first. Fails soft with a documented reason: `except Exception: pass  # best-effort model fallback`, returning `""`. A diagnostic helper for reading a brain's served model name back. Note it targets `127.0.0.1` explicitly, so it is not an I-01 SSRF concern. |

---

## Verified as sound — the mixin contract is the best structural work in `gui/`

**`ProviderLifecycleHost` (`:57-113`) is a `Protocol` with 48 explicitly declared
members**, each typed as a `Callable[...]` or `Any`, documented as *"What
`ProviderLifecycleBackend` requires of the object it is mixed into."*

This is the right way to write a mixin that reaches into its host. Every one of the
48 names — `_set_loading`, `_resolve_model_path`, `_snapshot_settings_values`,
`_kill_llama_on_port`, `_restart_brain_with`, `_persist_settings`, the
`provider_manager` / `provider_checker` / `runtime` handles, and the 22 Qt widget
attributes (`bb_status`, `sb_gpu_layers_spin`, `start_all_btn`, …) — is declared up
front rather than discovered at runtime.

The module also maintains the contract twice over. `:43` states *"Every name below
is something `ProviderLifecycleBackend` reads off `self` and…"* and `:116` adds
`#: Every member ProviderLifecycleHost requires, as plain strings` — a second,
runtime-checkable representation of the same list. `dialogue_tab.py:527` makes a
matching observation from the other side: *"real implementation is singular and
lives on `ProviderLifecycleBackend`."* Three files independently agree on where the
implementation lives.

`dual_brain_control.py:3786` closes the loop with
`getattr(ProviderLifecycleBackend, _compat_name)` — a compatibility shim that
resolves legacy attribute names back onto the backend, rather than leaving aliases
to drift.

**I attempted to check whether the concrete host implements all 48 members and the
check was not meaningful** — my probe looked for `self.<name>` or a bare assignment,
which misses members provided elsewhere in the MRO and Qt widgets constructed at
runtime. I am not reporting a result from it. The correct check is a runtime
instantiation of `DualBrainControl` against the Protocol, which the test suite would
already do if it mattered.

---

## Re-verification

No earlier finding touches this file. It is the Qt-side counterpart of
`agents/providers/provider_lifecycle.py` (`ProviderStatusChecker`, assessed in `10m`
as live from `dual_brain_control.py` and this file), and that finding is unaffected.

---

## Assessment

`provider_lifecycle_backend.py` is a strong result: 61 of 63 methods live, the two
that are not are a UI convenience layer and a diagnostic helper, and the
`Protocol`-based mixin contract is the most disciplined structural work in `gui/`.

V-01 is worth recording mainly as a data point rather than a defect. The
temperature *preset* names are the kind of thing a reader of the code — or an
operator reading the help catalog — would reasonably assume is available. It is not,
but nothing is broken by its absence: the spinbox path is live end to end.

This file continues the depth pass's pattern of the opposite result to `main.py`:
where `main.py` had 4 dead methods including a dead island around a trust
mechanism, this one has 2 dead methods and an explicitly enforced interface.