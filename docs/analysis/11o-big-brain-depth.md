# 11o — `agents/brains/big_brain.py` depth pass (707 lines, 17 methods)

Depth-pass #15 of 83. **Zero dead of 17.** The main reasoning model's provider
adapter. No findings — this file is where the project's honesty discipline turns out to
apply to *hardware* rather than to money.

---

## Structure

```
L   33-697   class BigBrainAdapter (17 methods)
```

Docstring: *"GPU: 5060 Ti (device 0) with RAM overflow. Port: 1234."* — the operator's
actual hardware, named in the module.

Largest methods: `chat` (237), `analyze_with_tools` (121), `_execute_tool_calls` (62),
`__init__` (52), `_hardware_line` (49), `_build_system_prompt` (31).

---

## Findings

None. All 17 methods are live.

---

## Verified as sound — ARCH-ENG-115, the epistemic rule applied to hardware

`_hardware_line` (`:174-222`) tells the model which device it runs on, and the
docstring records how it used to get that wrong:

> *"ARCH-ENG-115: this used to fall back to `cfg.gpu_label` when detection came back
> empty. That default is the literal placeholder `"GPU 0 (detected hardware)"`
> (`ROLE_DEFAULTS`), so whenever `nvidia-smi` returned nothing — a transient driver
> hiccup, or the subprocess timing out under load — **the brain was told it runs on a
> specific GPU that had not been detected at all. The prompt asserted unverified
> hardware to the model**, and it also made `tests/runtime/test_brain_prompt_hardware.py`
> flaky: detection intermittently yields CPU-only, the prompt still claims 'GPU 0', and
> the test's 'names a real detected device' assertion fails ~50% of runs.
>
> Now: no confirmed device -> no hardware claim. **Omitting the section is strictly
> better than stating a false one.**"*

This is the same rule the codebase applies to money — an unverified LLM assertion must
not become accepted fact — applied to a fact the *prompt* originates. An LLM that
believes it is on a specific GPU will reason about its own capacity accordingly.

**The failure mode it documents is realistic on this hardware.** `nvidia-smi` timing
out under load is exactly what ARCH-ENG-055's collision scenario produces, and `11j`
recorded that `_LAST_DETECT_ERROR` exists precisely so "no GPUs" is never conflated
with "could not ask". The three layers — error signal (`11j`), prompt honesty (here),
and launch gate (`11l`) — are consistent with each other.

**The implementation has five empty-return guards and no false-claim path.**
`:209-212` returns `""` when detection does not confirm the device (*"Say nothing rather
than repeat an unverified placeholder as fact"*); `:214-215`, `:216-217` and `:221-222`
guard the remaining failure modes; and `_build_system_prompt:238-240` appends the
section only `if hw:`, so an unconfirmed device yields **no section at all** rather than
an empty or hedged one.

**The line it does emit is grounded and role-bearing** (`:218-220`): *"You run on
{label}. You are the larger-capacity brain; handle deep reasoning, planning, and
verification, and keep responses grounded in evidence."* The hardware fact comes from
`dev.label()` — the same `device_registry` rendering `11j` verified as *"VRAM for GPUs;
total system RAM for the CPU pool"* — so the model is told its capacity in the units the
system actually uses.

The comment at `:235-237` states the rule the implementation follows: *"Reflects the
ACTUAL detected hardware, never a hardcoded card."*

---

## Re-verification

**`10m` confirmed.** `openai_compatible.py` is reached from `big_brain.py`, consistent
with the adapter structure `10m` recorded. `AnthropicAdapter` is constructed in
`worker_provider_mixin.py:108` as `10o` recorded, and `11g` verified
`propose_code_patch` is advertised in the canonical schema at `tools.py:59`.

**`10h`'s ARCH-ENG-124 confirmed in this file.** `big_brain.py:348` and `:396` set
`temperature=0.3`, and the effort-score fix that produced the `$1,403.09/h` figure lives
in `agents/earning/intelligence.py:28-41` — `big_brain.py` is the *caller* of that path.

**`BIG_BRAIN_TEMPERATURE` default is `0.5` at `:77`**, read as
`float(os.getenv("BIG_BRAIN_TEMPERATURE", "0.5") or 0.5)` — the `or 0.5` idiom is safe
here because the fallback equals the default, unlike the `or 0.5` on `effort_score`
that ARCH-ENG-124 corrected.

---

## Assessment

Zero dead of 17, no findings, and the largest single method (`chat`, 237 lines) is a
reasonable size for the surface it implements.

The reason this file is worth a document despite having nothing wrong with it is
`_hardware_line`. The project's central discipline — *never let an unverified
assertion become accepted fact* — appears in this sweep in three domains: monetary
(`economic_accounting.py`'s seven-way firewall), epistemic (`opportunity_analysis.py`'s
*"NO LLM — a model must never be the authority on whether a gig is actually doable"*), and
now **hardware** here.

The hardware case is the subtlest of the three, because a wrong hardware claim is not
obviously a lie to anyone. A financial fabrication has a number that can be checked; a
hardware assertion reads as context. It is still a claim the model reasons from, and
ARCH-ENG-115 is right that it needs the same standard — *"Omitting the section is
strictly better than stating a false one."*

That line is also the best single statement of the principle the whole sweep has been
circling, and it is worth carrying into the fix list as the standard to apply to the
findings that remain: `W-02`'s ungated `social_automation`, `AA-01`'s unguarded host
protocol, `AF-01`'s dedup check. In each case the question is not "does this exist" but
"does anything assert it without having confirmed it".