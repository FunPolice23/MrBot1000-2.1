# 11I — `agents/brains/small_brain.py` depth pass (605 lines, 16 methods)

Depth-pass #35 of 83. **2 dead of 16.** The counterpart to `11o`'s `big_brain.py`, and the
comparison is the result: **the ARCH-ENG-115 fix was propagated to this file with an explicit
cross-reference** — while the one dead method here is one that must *not* be wired.

---

## Structure

```
L   24-595   SmallBrainAdapter (15 methods)
L   600-605  get_small_brain
```

Docstring: *"Small Brain — Provider adapter for the fast chat model… **GPU: optional
secondary device, or CPU/system RAM when no secondary GPU exists.** Port: 1235. Includes
program knowledge, memory, and personality."*

Largest: `chat` (307), `_build_system_prompt` (64), `__init__` (40), `_hardware_line` (36),
`_get_client` (34), `_finish_got_turn` (14), `should_escalate` (12).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| BA-01 | **med** | **`search_opportunities` (`:590`, 6 lines) is dead, and its prompt is the one thing in this file that must stay that way.** It is documented as a *"placeholder for Discovery Engine integration"* and its body is `self.chat(f"Search for opportunities matching this query: {query}\n\nReturn a list of potential opportunities with **platform, pay, and time estimate**.")`. That asks a language model to **produce pay figures from unverified text** — the precise fabrication ARCH-ENG-212 removed from `earning_pipeline.py` (`estimated_usd_value = tvl_usd * apy_percent`) and that `11w`'s `_stated_usd` refuses to perform with four rejection layers. The real discovery path is `agents/discovery/` (`11w`'s AP-02: `earning_pipeline.py:495-756` is the superseded island). **Wiring this would reintroduce, in a new file, the exact defect three ARCH-ENG tickets exist to prevent.** It is recorded as `med` so that a future "this method is unused, let's expose it" reads as a hazard rather than an opportunity. |
| BA-02 | info | **`get_small_brain` (`:600`, 6 lines) is dead** — zero references anywhere, zero tests. The exact symmetric counterpart to `get_big_brain` (`11s`'s AL-01, also dead). Both module-level convenience accessors are unused; both adapters are constructed directly (`worker_provider_mixin.py:108` per `10m`, and `dialogue_tab.py`'s `_model_fn`). One small observation: it is *satisfying* that the accessor sweep found both, because a one-sided sweep would have left the impression that only `get_big_brain` was vestigial. |

---

## ARCH-ENG-115, propagated with a cross-reference

`11o` recorded `big_brain.py`'s `_hardware_line` as the best-documented fix in the codebase:
*"no confirmed device → no hardware claim… **omitting the section is strictly better than
stating a false one**."*

**This file applies the same rule and says so by name** (`:157-162`):

> *"The device registry is the source of truth, and a label is asserted to the model only when
> detection CONFIRMED a device. **Same rule as `BigBrainAdapter._hardware_line` (ARCH-ENG-115)**:
> the config's `gpu_label` default is a placeholder (**`"CPU / System RAM"` for this role**),
> so falling back to it when detection came back empty told the brain it runs on hardware that
> was never verified."*

Three things make this better than a copy-paste:

1. **The cross-reference is explicit**, so a future reader of *either* file can find the other
   and the rule's origin. That is the opposite of the drift `11z`'s ARCH-ENG-211 documented,
   where a protection lived in one dispatcher and not another.
2. **The placeholder differs by role and the docstring names the difference** — `"CPU / System
   RAM"` here versus `"GPU 0 (detected hardware)"` in `11o`. The fix was reasoned about per
   role rather than mechanically copied.
3. **The guard structure matches**: `:180` returns `""` when no device resolves, `:183` on any
   detection exception, `:185` on an empty label, `:189` on any outer exception — **four
   empty-return paths and no false-claim path**, the same shape `11o` verified.

The emitted line is also role-bearing rather than merely factual (`:186-187`): *"You run on
{label}. You are the fast, lower-capacity brain; keep answers concise and **escalate heavy
reasoning to the Big Brain**."* The hardware fact is the substrate; the role instruction is
what the model actually needs it for.

**This is the sweep's recurring defect, inverted into its own remedy.** Eighteen instances of
*"mechanism correct, wired at one end only"* — and here the mechanism is correct, wired at both
ends, with the second end citing the first.

---

## `should_escalate` — a UI-freeze fix, documented with its thread

`:571-582` is the brain-boundary method, and its docstring records a performance defect with
the right detail:

> *"Keyword-only heuristic. The old version also did a blocking Small Brain round-trip
> ("Does this need deep reasoning?") to decide — **that ran on the GUI thread in the Chat tab
> and froze the UI for seconds on every message.** The keyword list is deliberately broad and
> covers the complex/analytical intents that warrant the Big Brain (v2.0.36y)."*

**Every message** triggered a model round-trip before the message could be displayed. The fix
removes the round-trip entirely and the docstring says why the replacement is acceptable
(*"deliberately broad"*) rather than pretending a heuristic is precise.

The keyword list is a considered compromise: 17 terms covering the analytical intents. It will
over-escalate (`"explain"` and `"review"` are common in ordinary chat) and the code accepts
that — over-escalating to the Big Brain costs latency, under-escalating loses reasoning
quality, and the asymmetry favours the former.

---

## Verified as sound

**`classify` (`:584-588`) is live and asks for a label, not a number** — *"microtask /
freelance / airdrop / staking / **scam** / other"*. Distinguishing `scam` is a judgement the
model is being asked for and one the codebase needs; contrast BA-01, which asks for `pay`.
**The line between those two prompts is the line between classification and fabrication**, and
this file sits on the correct side of it everywhere except the dead method.

**`review` (`:564-569`) is live and well-scoped** — Big Brain's plan in, red flags out, with a
fixed reply format (`"APPROVED, or list specific concerns"`). Structured output, no invented
figures.

**Both brains are non-submitting by construction.** `11o` recorded Big Brain's *"can submit
real orders only when the operator explicitly enables live trading"* discipline; this module's
docstring makes no submission claim at all, and `search_opportunities` — the only method that
gestures at action — is a `self.chat()` string return, not a tool call.

**`__init__` (40 lines) declares the port and role in the module docstring** (`:1235`), and
`get_available_models` (`:120`) / `_get_first_available_model` (`:109`) are the *"Auto-detects
downloaded models — no hardcoded model names"* claim implemented rather than asserted — the same
discipline `11o` verified for Big Brain.

---

## Re-verification

**`11o` confirmed and extended by its counterpart.** `11o` recorded Big Brain as *"0 dead of
17"* plus `get_big_brain` via `11s`'s AL-01. Small Brain is **0 dead of 15** plus
`get_small_brain` and `search_opportunities`. The two adapters are structurally parallel — both
have `_hardware_line`, `_build_system_prompt`, `_get_client`, `_finish_got_turn`, and both carry
the ARCH-ENG-115 rule — so the parallelism is designed, not accidental.

**`11s` AL-01 confirmed symmetric.** `get_big_brain` (`big_brain.py:702`) and `get_small_brain`
(`:600`) are both dead, both 6 lines, both zero-reference. Two independent vestigial accessors,
not one.

**`11j` / ARCH-ENG-219 consistent.** The module docstring's *"GPU: optional secondary device,
or CPU/system RAM when no secondary GPU exists"* is the Small Brain's honest description of the
1660 Super / CPU-pool case, and `_hardware_line:174-175` selects the CPU device
(`elif cfg.gpu_layers == 0: dev = next((d for d in devices if d.is_cpu), None)`) only when
`gpu_layers` is 0 — i.e. the claim follows the configuration rather than a fixed assumption.

**`11w` / ARCH-ENG-212 — the contrast that makes BA-01 (see above).**

**`11D` consistent.** `dialogue_tab.py`'s `_model_fn` builds `SmallBrainAdapter().chat(prompt)`
for the Navigator role, matching `11o`'s `BigBrainAdapter().analyze_with_tools(prompt)` for the
Driver — so both adapters are live through the same collaboration path.

---

## Assessment

Two dead of sixteen, and the file's value is that it demonstrates the remedy the sweep has been
arguing for.

`11o` found ARCH-ENG-115's fix exemplary in `big_brain.py`. The more interesting fact is what
happened next: **the sibling adapter adopted the rule, named the source, and adjusted the
specifics for its own role.** That is the behaviour you want when a security-relevant invariant
is discovered in one of two parallel implementations, and it is the direct opposite of
`11z`'s ARCH-ENG-211, where the *hardened* path silently lost a protection its weaker sibling
had.

**BA-01 is the finding that should survive into the fix list in its negative form.** This
method is dead, it looks like an obvious gap ("the Small Brain should be able to search for
opportunities"), and wiring it would be an active regression. Its prompt asks a model for
*"platform, pay, and time estimate"* — the fabrication that `11w`'s `_stated_usd` spends 35
lines and three ARCH-ENG tickets preventing.

That is the **third** time the sweep has had to say *"do not wire this reader"* — after `AJ-02`
(`11r`), `AN-03` (`11u`) and `AQ-01` (`11x`). Each was a different mechanism, and the common
thread is worth stating for the fix list as a whole: **in this codebase the dead code is
usually not unfinished work.** It is, far more often, either a superseded mechanism whose
successor is elsewhere and documented, or a mechanism that exists precisely because it is not
wired. `11G`'s workshop write-half is the exception that proves the rule — and even there, the
history (`11G`'s AY-01) shows the missing half was never a decision anyone recorded.

The useful next step is not more sweeping. It is the **batched fix presentation** the sweep has
been deferring: these findings have now accumulated enough that they should be reviewed as a
set, with the three "do not wire" items called out separately from the genuinely-fixable ones.
