# 11l — `gui/workers/brain_launch_worker.py` depth pass (744 lines, 16 methods)

Depth-pass #12 of 83. **Zero dead of 16** — and this file holds the ARCH-ENG-231
remediation and the ARCH-ENG-055 system-RAM guard, so it is where the hardware policy
becomes an enforced runtime behaviour rather than a documented constraint.

---

## Structure

```
L   13-422   class BrainLaunchPrepWorker  (8 methods)  -- gates + command prep
L  426-741   class BrainLaunchWorker      (8 methods)  -- process supervision
```

---

## Findings

No dead methods and no defects. The two substantive observations below are
confirmations rather than problems.

---

## Verified as sound — ARCH-ENG-231 re-verified, and correct

This was my own remediation, so I checked it closely rather than assuming.

**The gate is called and a refusal genuinely halts the launch.** `_contention_gate`
is invoked at `:149`, and `:150-152` emits `prep_finished(small, False, blocked, None)`
and returns **before** `:155` builds the launch command. So a refused brain never
reaches command construction — the gate is upstream of the side effect, not advisory.

**The blocking rule is narrow, deliberately, and says so.** `:225` blocks only when
`over > self._SEVERE_OVERRUN_GB or over > free_gb`, with `_SEVERE_OVERRUN_GB = 4.0`
(`:162`). The docstring at `:169-182` states the reasoning, including the argument
against the obvious alternative:

> *"BLOCK when the gate can establish the footprint AND the request exceeds what is
> free by more than `_SEVERE_OVERRUN_GB`, or by more than the free amount itself. That
> is the territory where the CUDA allocator fails hard and Windows takes the driver
> down with it. WARN-ONLY otherwise… `can_add_brain` fails closed on an unknown
> footprint, and applying that here would block every cloud provider and every model
> named rather than pathed. **'Refuse to crash the driver' is a different decision from
> 'refuse to start a server whose cost cannot be measured.'**"*

And at `:140-148`, in the caller, the same reasoning is restated for the operator's
benefit, including why llama.cpp's legitimate spilling is tolerated.

**The override is honoured and narrow.** `MRBOT_ALLOW_RISKY_LAUNCH` is checked at
`:184-186` against `("1", "true", "yes", "on")` and returns "" immediately. It is
opt-in, not default.

**The refusal message is actionable**, naming four concrete remedies — *"Stop a brain,
lower the context, offload fewer layers, or pick a smaller model"* — and the override.

**`_committed_placements` (`:238-265`) judges against the other brains, not a
vacuum** — the docstring names the failure it prevents: *"so the gate is not judging
this one in a vacuum — which is exactly the case that used to look safe."* It walks
`BrainRole.BIG` and `BrainRole.SMALL`, skips `self.cfg` itself (`:252`) and skips
anything on the same port (`:254-255`, *"the same server"*), and returns `[]` on
any failure so the gate degrades to warn-only rather than raising.

---

## Verified as sound — ARCH-ENG-055 is the CPU/RAM requirement, implemented

This is the finding worth leading with, because it answers the hardware constraint
that recurred across four earlier areas — **not with a comment, but with a guard
that measures real process RAM**.

`:107-116` documents the physical mechanism in full:

> *"A GPU brain is NOT VRAM-isolated: llama.cpp mmaps the GGUF, so the model's weights
> live in the system page cache and are faulted into resident RAM under memory
> pressure. When the CPU/RAM brain then generates and builds its KV cache, it drains
> system RAM, which forces the GPU brain's ~10 GB model pages resident — the two
> footprints collide and the GPU brain's llama-server hits a failed allocation and
> ABORTS (silently: no OS crash, no GPU TDR). This is the **'big brain terminal just
> exits when I Chat the small brain'** report."*

That is a precise, physical explanation of why a VRAM-only model of GPU memory is
insufficient on this hardware — traced from mmapped pages through page-cache residency
to the specific operator-visible symptom, and it distinguishes this failure (silent
allocator abort) from a driver TDR, which is a *different* failure with a *different*
remedy.

`_gpu_free_vram_gb` (`:267-273`) reads live `nvidia-smi --query-gpu=index,memory.free`
rather than trusting configuration, which is what makes the headroom check reflect the
device's actual state at launch time.

---

## Re-verification

**The "fourth blind spot" from `agents/runtime/` is resolved.** In `10n` a reachability
scan flagged `brain_contention` as dead; it is called here at `:188`
(`from agents.runtime import brain_contention as bc`) inside `_contention_gate`, and
`can_add_brain` at `:210`, `device_headroom` at `:217` and `estimate_model_vram_gb` at
`:220` — all live. That module's 356 lines are load-bearing exactly as `10n`
concluded once the `import X as Y` form was accounted for.

**ARCH-ENG-219/1-model-per-device is respected indirectly.** The gate does not enforce
placement count; `brain_roster.py:26` does, and `11j` confirmed the layering is correct
(detection here, allocation there). This gate answers a *different* question — whether
the requested launch fits alongside what the others already hold.

**M-03 unaffected.** The gate reads `cfg.context` but does not compute a clamp;
the VRAM-clamp fallback gap remains in `dual_brain.py`.

---

## Assessment

Zero dead of 16, no defects, and the two most important behaviours in the whole
hardware-policy chain are both correct and both verified at the call site rather than
inferred from a docstring.

The distinction this file makes is worth carrying into the fix list. The
ARCH-ENG-231 gate is a **narrow refusal rule with an escape hatch and a reasoned
explanation of why it is not broader** — it declines to block on unmeasurable
footprints precisely because doing so would break cloud providers and named models.
That is a decision about product behaviour, not just safety, and it was documented as
one.

ARCH-ENG-055 is the stronger piece, because it took the requirement *"a GPU still uses
system RAM"* and implemented it as a measurement of live process residency rather than
as an assumption. Across this sweep the hardware constraints have been answered at four
levels — a constant (`brain_roster.py:26`), a model field (`device_registry.py:70`),
a clamp (`dual_brain.py:_vram_safe_context`), and now an enforced runtime guard that
reads `nvidia-smi` and real process RAM. Each level is live.