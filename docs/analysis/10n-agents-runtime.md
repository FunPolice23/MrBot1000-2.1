# 10n — `agents/runtime/`

> **M-01 RESOLVED in v2.1.125 (ARCH-ENG-301).** The superseded
> `hardware_plan.py` and its test are deleted; `device_registry.py` plus
> `brain_roster.py` remain the live hardware path.
>
> **M-03 RESOLVED in v2.1.125 (ARCH-ENG-291).** The no-model fallback in
> `_vram_safe_context()` now scales each VRAM tier's f16-calibrated allowance by
> the `kv_type_bytes` it is handed. A q8_0 KV operator gets a larger allowance
> than f16 (still capped by the configured default), and the reason string names
> the KV width so the difference is visible. The measured path was already
> correct.

13 scripts, 4,347 lines. Device detection, brain roster, hardware planning, the
dual-brain runtime, and the VRAM clamp (ARCH-ENG-222).

---

## Structure and reachability

| File | Lines | Reached from |
|---|---:|---|
| `__init__.py` | 43 | facade |
| `stats.py` | 61 | **nothing** |
| `provider_keys.py` | 137 | `big_brain`, `small_brain`, `cost`, `provider_lifecycle` |
| `llm.py` | 138 | `base_worker`, `worker_provider_calls` |
| `performance.py` | 131 | `main`, `prompting_engine`, `tab_feature_builders`, `worker_llm_mixin` |
| `hardware_plan.py` | 238 | **nothing** |
| `context.py` | 226 | 10 sites incl. `chat_router`, `program_knowledge` |
| `services.py` | 226 | `library.py` |
| `agent.py` | 208 | `dialogue_tab.py` |
| `hardware_plan.py` | 238 | **DEAD** |
| `brain_roster.py` | 354 | `brain_roster_panel.py` + intra |
| `brain_contention.py` | 356 | `brain_launch_worker.py:188` |
| `device_registry.py` | 848 | 9 sites incl. `main.py`, `dual_brain_control` |
| `dual_brain.py` | 1381 | **37 sites** — the most-used module in the repository |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| M-01 | med | **`hardware_plan.py` (238 lines) is dead, and its docstring claims to be authoritative while being superseded.** The module opens: *"This module is the single source of truth for 'what hardware do we have, and which brain should run where'."* `HardwareTarget`, `PlannedBrain`, `BrainPlan`, `detect_cpu_target`, `_gpu_targets_from_manager`, `build_brain_plan` and `format_brain_plan` have **zero production references of any form**. That work is now done by `device_registry.py` (848 lines, 9 production consumers including `main.py`) and `brain_roster.py` (354 lines, live via `brain_roster_panel.py`). This is the same failure as F-02 (`earning_memory.py:1952`) and `discovery_scheduler.py:21`: a docstring asserting authority over a subsystem that has since been rebuilt underneath it. Here the claim is stronger — it is the *only* assertion of single-source-of-truth in the area, and it is false. |
| M-02 | low | **`stats.py` (61 lines) is dead.** `RuntimeStats` — *"Thread-safe telemetry for the manager heartbeat loop"* — appears in its own module at `:8` and in the `agents/runtime/__init__.py` facade at `:3` and `:19`, and nowhere else. Checked by class name across every production file, so this is not the facade blind spot: no consumer imports it through any path. Note the docstring's premise too — the "manager heartbeat loop" it serves does not appear to exist as a distinct loop. |
| M-03 | med | **The VRAM tier fallback ignores the KV-quantisation parameter it is handed.** `_vram_safe_context` takes `kv_type_bytes: int = 2` and uses it correctly on the *measured* path (`:804`, `:808`). On the *fallback* path (`:831-836`) the loop is `for ceiling, ctx in _VRAM_TIER_CONTEXT: if vram_bytes < ceiling * 1e9: return ctx` — `kv_type_bytes`, `role`, `gpu_layers` and model size are all ignored. A q8-KV operator therefore receives an f16-sized context allowance. This matters **today**, not hypothetically: `*_MODEL_PATH` is not set in `.env`, so the measured path never runs and the fallback is the active path on both of the operator's cards. Verified against the real tiers: 6 GB → 8192, 16 GB → 32768 — sensible for the models currently installed, but on a 16 GB card a 30B-class q4 model (≈18 GB of weights against a 12.0 GB budget) would still be told 32768, when the measured path would have caught it at `:812-815`. The fix is cheap and the trigger is a larger model, which is the direction the operator is already moving. |
| M-04 | info | **Redundant clamp.** `:818` computes `fits = max(4096, min(fits, default_context))` and `:819` immediately repeats `fits = min(fits, default_context)`. Harmless, and the 4096 floor is a deliberate guard, but the second line is a leftover. |

---

## Verified as sound — the VRAM clamp, checked against the real hardware

`_vram_safe_context` (`dual_brain.py:758-837`) is the best-specified piece of
numeric reasoning in the codebase, and its central claim reproduces exactly:

```
2 × 36 layers × 8 KV heads × 128 head_dim × 2 bytes × 64768 tokens = 9.55 GB
```

which matches the docstring's stated figure. For an 8B-class model at the shipped
`ROLE_DEFAULTS` of `context: 64768` with `kv_cache: "f16"`, that is 9.55 GB of KV
cache *"before a single weight is loaded."* The docstring names the failure mode
precisely rather than gesturing at it: on the operator's GTX 1660 Super that is
*"not a slow context, it is a hard allocation failure: CUDA OOM -> Windows TDR ->
display-driver reset or reboot."*

Verified behaviours, each by reading the implementation rather than the docstring:

- **An explicit operator setting still wins.** `:774-776` — *"The configured
  value is still what the operator ASKED for… An explicit `BIG_BRAIN_CONTEXT` in
  `.env` still wins untouched — a deliberate setting is not second-guessed."*
- **It can only narrow.** `:780-781` — *"Never returns MORE than `default_context`:
  this narrows a risky default, it does not expand one."* Confirmed: every return
  path is either `default_context` or a value already passed through
  `min(..., default_context)`.
- **Every detection failure fails open with an honest reason.** Four distinct
  paths (`:787`, `:792`, `:795`, `:810`) each return the configured default
  accompanied by a specific explanation rather than a silent default — so when the
  operator asks why their context did not change, the answer is already in the log.
- **The measured path is measured, not estimated.** It reads `n_layer`,
  `kv_head`, `head_dim` from the real GGUF via the cached
  `gguf_meta.estimate_vram_gb`, computes `kv_bytes` from actual geometry
  (`:807-808`), rounds **down** to a 256 multiple (`:817`), and keeps a 4096 floor.
- **Weights-exceed-budget is handled explicitly.** `:812-815` clamps to the
  lowest tier with the message *"weights (X GB) already exceed the Y GB budget"*,
  rather than computing a negative token count.

**`brain_contention` is live — and this is the sweep nearly misreporting its own
fix.** A reachability scan flagged it as dead. It is not: `gui/workers/
brain_launch_worker.py:188` does `from agents.runtime import brain_contention as
bc` and calls `can_add_brain` — the ARCH-ENG-231 wiring. My pattern required the
module name adjacent to `runtime`; the real text has `import` in between. That is
the **fourth** import-form blind spot in this sweep.

---

## Assessment

This area carries the operator's hardware constraints, and it carries them
properly. `brain_roster.py:26` encodes the one-model-per-device rule as a
constant with the ≥32 GB VRAM exception; `brain_contention.py` resolves the
conflict at launch time; `brain_contention.py:43` records that system-RAM KV
accounting was corrected for GPUs that also use system RAM; and the VRAM clamp is
the most carefully reasoned numeric code in the repository.

M-03 is the finding worth acting on, and its severity comes from the same place
F-01's did: the safe path is not the active path. The clamp's careful,
GGUF-measured logic is bypassed on this machine because no model path is
configured, leaving the crude tier table — which is the one part of the function
that ignores its own parameters. Setting `*_MODEL_PATH` would activate the good
path immediately; hardening the tier table would make the fallback safe in its own
right. Both are worth doing, and they are independent.

M-01 and M-02 together are 299 lines of dead code, and M-01 carries a claim that
actively misleads: a module asserting it is the single source of truth for
hardware planning, in an area where `device_registry` has 9 live consumers. A
reader arriving at `hardware_plan.py` first would have no way to know it is
obsolete.

The methodological note is the recurring one, and it is now four for four:
**every import form this codebase actually uses has defeated a reachability scan at
some point.** Direct absolute import, dict-valued dispatch, attribute-access
return types, relative import, facade re-export, and `from pkg import module as
alias`. The scans are still useful as a *first pass* — every one of these blind
spots produced a candidate that then needed checking, and the checks caught them.
They are simply not usable as a verdict.