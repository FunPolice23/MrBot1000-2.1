# 11j — `agents/runtime/device_registry.py` depth pass (848 lines, 29 functions)

Depth-pass #10 of 83. **27 of 29 live** — the two dead are 2-line accessors. The
detection layer under the hardware policy, and the second-best-wired module in the
depth pass.

---

## Structure

21 module-level functions and 3 dataclasses (`ComputeDevice`, `DevicePolicy`,
`DeviceAssignment`) with 8 methods. My first pass undercounted this file at "8
methods" because it only counted class methods — worth recording as another counting
trap, though a mild one compared to the seven import-form blind spots.

Line budget: 607 lines of function bodies. Largest are `_detect_gpus` (83),
`_run_nvidia_smi` (77), `brain_placements` (47), `merge_settings_file` (46),
`detect_devices` (43), `save_policy` (42).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AD-01 | info | **`DevicePolicy.model_for` (`:128`) and `DevicePolicy.settings_for` (`:131`) are dead** — 2 lines each, zero tests. Trivial accessors on the policy dataclass. |

---

## Verified as sound — the hardware policy, checked against the operator's actual machines

**The policy constants classify both of the operator's GPUs correctly.**

| Constant | Value | Effect on the stated hardware |
|---|---:|---|
| `BIG_VRAM_GB` | 12.0 | RTX 5060 Ti (16 GB) → `capability_class() == 'big'` |
| `SMALL_VRAM_GB` | 4.0 | GTX 1660 Super (6 GB) → `'small'`, **not** `'big'` |
| `CPU_MIN_RAM_GB` | 12.0 | 32 GB system → CPU pool eligible |
| `CPU_MIN_CORES` | 4 | Ryzen 5 3600 (6 cores) → eligible, and ≥ `CPU_MIN_CORES * 2` for the CPU `'big'` tier |

`ComputeDevice.capability_class()` (`:83-97`) reads `memory_gb` as *"VRAM for GPUs;
total system RAM for the CPU pool"* (`:70`) — so the CPU/RAM accounting requirement is
built into the data model rather than bolted on, and `label()` (`:99`) renders it as
`CPU / System RAM (32 GB, 6 cores)`, making the distinction visible to the operator
rather than implicit.

**The 1-model-per-device rule is correctly in the *allocation* layer, not this one.**
An exhaustive search for the rule finds it **only** in `agents/runtime/brain_roster.py` —
which is the right place, since this module is pure detection and `brain_roster` does
allocation. No duplication and no gap. The rule is documented there with its edge
already closed:

- `:26` — *"ARCH-ENG-219: ONE MODEL PER DEVICE, UNLESS THE DEVICE HAS >= 32 GB VRAM"*
- `:36` — *"The rule is a hardware fact, not a UI preference"*
- `:235-237` — *"Capacity, not a boolean: a >=32 GB device hosts TWO models, not
  [unlimited]… which let a THIRD model onto a 32 GB card — the predicate was true"*

That last line records a **fixed over-permissive predicate** — an earlier draft would
have admitted a third model to a 32 GB card. The constraint is bounded at exactly two,
and the reason is written down.

**Two honest failure-mode distinctions, both documented as deliberate.**

`ARCH-ENG-116` at `:50-53`: `_LAST_DETECT_ERROR` exists so a caller can distinguish
*"this box has no GPUs"* from *"we could not ask" — *"the two must never be
conflated."* That is the correct treatment of a probe that can fail for reasons
other than its answer.

`_GPU_LOST_SIGNALS` at `:55-59` records `("gpu is lost", "unable to determine the
device handle")` — TDR-reset and driver-crash strings — with the reasoning: *"A lost
GPU is NOT 'no GPUs': the healthy card(s) are still detected and usable, so this
records a reboot hint rather than swallowing the GPU (B1)."* Failing *open* on a
partial probe rather than dropping a working card.

**The settings-merge path is atomic and locked.** `_SETTINGS_WRITE_LOCK` (`:151`),
`_atomic_write_settings` (`:274`, 26L), `_merge_and_write_settings` (`:302`) and the
`main.py:3200-3203` caller comment (*"Merge instead, so sibling keys survive"*) form
a coherent read-merge-write sequence with a backup path, rather than a blind overwrite.

---

## Re-verification

**ARCH-ENG-221's detection cache is present and structurally correct.**
`_DEVICE_CACHE_TTL_S` (`:676`) with `invalidate_device_cache` (`:679`) and
`detect_devices` (`:690`, 43L) — the 10-second TTL keyed on `include_cpu` that
ARCH-ENG-221 introduced, reducing the call from 192 ms to 0.005 ms. This is the
sixth file where M-03's surrounding conditions have been re-checked unchanged.

**M-03 unaffected.** `detect_devices` supplies the device list `_vram_safe_context`
consumes; the clamp's fallback-path gap is in `dual_brain.py` and is not touched here.

---

## Assessment

27 of 29 live, with the dead set being two trivial accessors. Together with `11d`
(this package's `dual_brain.py`, 37 of 39) and `11b` (`provider_lifecycle_backend.py`,
61 of 63), the hardware layer is consistently the best-wired part of the repository —
which is consistent with it being the part most constrained by physical reality
rather than by design preference.

AD-01 needs no action beyond the record.

The substance worth carrying forward is the *layering* this module demonstrates. It
does detection only, expresses capability as data (`ComputeDevice`), keeps the
allocation rule in the layer above, and — the detail that most distinguishes good
hardware code from bad — it distinguishes **"no GPUs" from "could not ask"** and
**"a GPU is lost" from "there are no GPUs"**. Both distinctions exist because the
alternative was a system that silently degrades on a driver reset, which on this
hardware (a 1660 Super that the WindowsApps MSVC llama.cpp build cannot run at all, per
`11d`) is a realistic failure rather than a theoretical one.