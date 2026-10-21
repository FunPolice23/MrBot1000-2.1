# 11p — `agents/providers/provider_manager.py` depth pass (697 lines, 28 methods)

Depth-pass #16 of 83. **24 of 28 live.** The provider detection and management layer —
the most-consumed module in `agents/providers/` at 15 outside consumers.

---

## Structure

```
L   24-36    ProviderType       L   87-103  ProviderInfo
L   39-43    ProviderStatus     L  106-688  ProviderManager (27 methods)
L   47-63    GPUInfo            +  module-level: _detect_gpus, normalize_provider_name
```

Largest methods: `detect_providers` (74), `_detect_gpus` (63), `_detect_cloud_providers`
(48), `refresh_provider_models` (38), `_detect_llamacpp` (34), `_detect_lm_studio` (32).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AH-01 | info | **Four small accessors dead, clustered at the class end** — `get_local_providers` (`:631`, 3 lines), `get_cloud_providers` (`:635`, 3), `set_provider_status` (`:639`, 7), `get_gpu` (`:651`, 6). 19 lines total, zero tests, no callers. All four sit in the final 27 lines of a 27-method class, which reads as a trailing convenience block rather than capability that was abandoned mid-use. |

---

## Verified as sound — two `_detect_gpus` that are layered, not duplicated

This looked at first like the same shape as W-01 (the parallel discovery layer in
`earning_pipeline.py`). It is the opposite, and worth recording as the contrast.

`device_registry._detect_gpus` (`:586-588`) states the relationship explicitly:

> *"Detect GPUs with stable UUIDs via nvidia-smi; **fall back to the provider manager's
> probe (index-only) when the UUID query is unavailable**."*

So the newer, identity-stable implementation is primary, and `provider_manager`'s
index-only probe is the **retained degradation path** — not a second implementation
competing with the first. Both are live in their intended roles
(`device_registry.py:726` and `provider_manager.py:185`).

That is the correct shape for this problem, and it is the mirror image of W-01: there,
a new path was built and the old one was left beside it with no relationship. Here, the
relationship is the first thing the newer module's docstring says.

**Two distinct detection entry points, with the difference documented.**
`_detect_once` (`:589-594`): *"Run the initial detection exactly once, even under
concurrent callers. Blocks only until any in-flight detection finishes, then returns
the cache. **Distinct from `detect_providers()` which always performs a fresh (forced)
re-detect for config-change hot-reload.**"* The warm-up thread (`:586`) and
`_init_lock` (`:595`) implement the once-only guarantee.

**`resolve_enabled_provider` (`:610-615`) encodes a real safety distinction:**

> *"Environment role settings are authoritative because they are shared by the GUI,
> adapters, and workers. Provider detection alone is not enough: **a stopped or merely
> installed backend must not become the active route.**"*

That is the same discipline as `AE-02` (the tool firewall's permissive default) applied
in the correct direction: *installed* is not *running* is not *enabled*. Each is checked
separately, and detection — which only proves installation — is explicitly insufficient.

**`device_registry.py:702` documents a deliberate cache boundary:** *"`_detect_gpus`
itself is deliberately left UNCACHED, because tests patch it."* That explains the
architecture `11j` verified: the TTL cache sits in `detect_devices` *above* the probe
rather than inside it, so patching the probe still works.

---

## Re-verification

**`10m` confirmed.** `provider_manager` has 15 outside consumers including
`device_registry`, `hardware_plan`, `tab_feature_builders` and `dual_brain_control`, as
recorded. `normalize_provider_name` (`:600-608`) is called from
`tab_feature_builders.py:3853` per `11h`, and handles the alias spellings
(`lm_studio`/`lm studio` → `lmstudio`, `llama.cpp` → `llamacpp`) that the alias
resolution in `dispatch.py` also cares about.

**`11h` consistent.** `_on_provider_widget_changed` calls `ProviderManager.instance()`,
`normalize_provider_name`, `get_provider` and `assign_provider_to_gpu` — all live here.

**M-03 / ARCH-ENG-219 unaffected.** This module detects providers and GPUs; it does not
allocate brain placements, which `brain_roster.py:26` owns, per `11j`'s layering
confirmation.

---

## Assessment

24 of 28 live, with four 19-line accessors dead. No functional finding.

The substantive observation is the layering between this module's `_detect_gpus` and
`device_registry`'s. Two functions with the same name in two modules is the exact shape
that produced W-01, and checking it here was worth the call: one is a documented
fallback for the other, the newer one is preferred, and both remain live in their
intended roles. That is what a migration looks like when it is completed rather than
abandoned — and it is worth holding up against W-01 as the contrast case when the fix
list is assembled.

`resolve_enabled_provider` is the other piece worth carrying forward. The distinction it
draws — *a stopped or merely installed backend must not become the active route* — is a
third instance of the "installed ≠ running ≠ enabled" pattern this sweep has now seen in
three places: the tool firewall's list default (`AE-02`), the VRAM clamp's
model-path-vs-tier fallback (`M-03`), and here. Each is a case where a weaker signal
could plausibly have been mistaken for a stronger one, and each is checked explicitly.