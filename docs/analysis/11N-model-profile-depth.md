# 11N — `agents/providers/model_profile.py` depth pass (558 lines, 15 functions)

> **BE-02 RESOLVED in v2.1.125 (ARCH-ENG-262).** `extract_thinking_from_content`
> was a superseded copy of the logic already inlined in
> `agents/safety/response.py`, and a less tolerant one (no whitespace allowance
> around the `<|channel>` markers). It is deleted; `response.py`'s docstring now
> records that the stripper is inlined deliberately, and the live stripper is
> pinned behaviourally.
>

> **PARTIALLY RESOLVED in v2.1.125 (ARCH-ENG-239).** BE-01 fixed: the ONE
> canonical think-block matcher now lives in
> `agents/brains/worker_thinking` (`strip_think_blocks` / `split_think_blocks`,
> case-insensitive + DOTALL). response.py's `_remove_think_blocks` alias,
> response.py's `enable_thinking_param` branch, and chat_tab.py's pattern 3
> all delegate to it; the worker's legacy unclosed-block policy is
> deliberately preserved. `<THINK>`/`<Think>` is now stripped or split
> identically on every path. The fifth, dead copy in this file
> (`extract_thinking_from_content`, BE-02) remains — that is the separate low
> finding. BE-03/BE-04 (dead accessors incl. `supports_vision`) remain open.
> Regression tests:
> `tests/engineering/test_arch_eng_239_think_block_matcher_shared.py`.

Depth-pass #40 of 83. **5 dead of 15.** The dead set is a superseded local copy of logic that
lives elsewhere — and tracing it surfaced something the sweep had not previously recorded:
**four live implementations of the same string operation, differing in case-sensitivity.**

---

## Structure

```
L   1-9     module docstring — families, tool format, thinking mode, system role, vision
L  26-307   FAMILY_PROFILES: 14 family dicts (thinking/thinking_tag/reasoning_field/…)
L  309-556  15 module functions
```

Docstring: *"Model-profile detection. Auto-detects the model family from GGUF metadata,
filename, and server `/props` endpoint. Provides the correct configuration for: Tool-calling
format, Thinking/reasoning mode (`enable_thinking`, `reasoning_content`), System-role
handling…"*

Largest: `detect_family_from_metadata` (32), `detect_model_family` (29),
`detect_family_from_server_props` (28), **`extract_thinking_from_content` (26, dead)**,
`get_model_profile` (22), **`supports_vision` (19, dead)**.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| BE-01 | **med** | **Four *live* implementations of thinking-marker stripping, differing in case-sensitivity — and a fifth, dead copy in this file.** `agents/safety/response.py:173` `_remove_think_blocks` strips with **`re.IGNORECASE`**; `response.py:210` strips again **without** it; `gui/tabs/chat_tab.py:225` compiles `<think>(.*?)</think>` **without** it; `agents/brains/worker_thinking.py:6` uses string `.index()` rather than a regex. A model emitting `<THINK>` or `<Think>` is stripped by one path and passed through by the others. This is `11z`'s ARCH-ENG-211 family — a correct mechanism with parallel copies — except here the copies are all **live**, so the drift is reachable rather than latent. |
| BE-02 | low | **`extract_thinking_from_content` (`:514`, 26 lines) is a superseded copy, and the comment that replaced it still describes the delegation.** `response.py:200-210` *inlines* this file's logic rather than importing it, and its docstring at `:187-189` says *"If a `profile` is provided, **use the family-specific thinking extractor** to strip inline `<think>` or `<|channel>thought` blocks"* — describing a delegation that no longer happens. The inlined version is also **more tolerant** than the original: `<\|\s*channel\s*>thought\s*.*?\s*<\s*channel\s*\|>` allows whitespace the dead copy's `<\|channel>thought\s*(.*?)\s*<\|channel\|>` does not. Deleting the dead copy would lose the record of the family-specific contract, so it is worth checking the inline version's coverage before removal rather than after. |
| BE-03 | info | **Three trivial accessors dead:** `supports_tool_calling` (`:461`, 3 lines), `supports_thinking` (`:466`, 3 lines), `describe_profile` (`:552`, 7 lines — a logging helper, `f"{family}(tools={tools},thinking={thinking},system={system})"`). The first two are one-line profile-field reads superseded by `get_profile()` / `get_model_profile()`, both of which are live from four sites. |
| BE-04 | info | **`supports_vision` (`:493`, 19 lines) is dead.** The only substantive dead method — a family-capability check with no callers. Note that `build_extra_body` (live) never consults it, so vision is a profile field with no consumer anywhere. |

---

## BE-01 — why case-sensitivity is the specific hazard

Three of the four live implementations are regexes over the same literal:

| site | pattern | case-insensitive? |
|---|---|---|
| `response.py:173` | `<think>.*?</think>` | **yes** (`re.IGNORECASE \| re.DOTALL`) |
| `response.py:210` | `<think>.*?</think>` | **no** (`re.DOTALL`) |
| `chat_tab.py:225` | `<think>(.*?)</think>` | **no** (`re.DOTALL`) |
| `worker_thinking.py:6-14` | `content.index("<think>")` | **no** (exact substring) |

The first is the one on the main dialogue path (`11C`'s `dialogue_tab` → `chat_completion` →
`response._visible_response_content`), and it is the tolerant one — **by luck rather than by
design**, since the three implementations are not documented as related. `worker_thinking.py`'s
comment at `:30-32` shows the author *was* reasoning about precedence ("*the authoritative
signal is the runtime `reasoning_content`… only as a fallback*"), which makes the absence of a
shared helper more conspicuous: the careful reasoning was applied to *which signal wins* and
not to *where the string is matched*.

The fix is small and obvious — one helper, four call sites — and it is worth grouping in the
fix list with `11v`'s AO-03 (27 raw boolean parsers) and `11L`'s BC-01, since all three are
*"the same decision expressed N times, with N different answers"*.

---

## Verified as sound

**`_visible_response_content:191-199` gets the precedence right, and it is the harder half of
the problem.** The docstring states it (`:181-186`):

> *"For thinking/reasoning models (Qwen3-Think, DeepSeek, NVIDIA Nemotron), the provider may
> place private thought in `reasoning_content` and the final answer in `content`. **When
> `content` is empty but `reasoning_content` carries the only visible output, fall back to it**
> so the operator still receives a response instead of an opaque empty error."*

```python
197   cleaned = _remove_think_blocks(_remove_reasoning_channels(content))
198   if not cleaned and reasoning and isinstance(reasoning, str):
199       cleaned = _remove_think_blocks(_remove_reasoning_channels(reasoning))
```

**The fallback fires only when `cleaned` is empty** — not when it merely looks short, and not
unconditionally. So a model that answers in `content` is never double-counted, and one that
answers only in the reasoning channel is not blanked. That is the *unknown ≠ zero* discipline
this sweep has now seen in `_stated_usd` (`11w`), `_step12_verify` (`11J`) and AT-01's truncation
notice (`11A`), applied to a response body.

**`_remove_think_blocks:169-170`'s docstring states the intent in one line** — *"Remove
LFM/Gemma think blocks **without exposing hidden reasoning**"* — which is a policy statement,
not a description.

**The profile table is well-designed.** 14 families each declaring `thinking`, `thinking_tag`,
`reasoning_field` and `notes`, including the distinction that matters most:

- `model_profile.py:28,34-35` — Qwen 3.8: *"thinking delivered in separate `reasoning_content`
  field"*, `thinking_tag: "<think>"` **and** `reasoning_field: "reasoning_content"`
- `model_profile.py:41,47` — Qwen 3.6/3: *"thinking inline in content as `<think>…</think>`"*
- `model_profile.py:72,97,121,133,…` — families with `thinking_tag: None`, i.e. no inline form

**Same family, different delivery channel** — and the table distinguishes them explicitly with
`notes`. That is `11F`'s `OUTCOME_STATES` instinct (`rejected_apply` vs `rejected_pay`): two
things that look alike, distinguished rather than merged.

**`build_extra_body:542-549` is minimal and correct** — it sets `chat_template_kwargs.enable_thinking`
only when `wants_enable_thinking(profile)` **and** the caller opts in, and `preserve_thinking`
only when the family declares it. Called from four live sites (`big_brain.py:508,587,603`,
`small_brain.py:300`).

**Detection has three independent sources** — GGUF metadata (`:318`, 32 lines), filename
(`:352`), and server `/props` (`:361`, 28 lines) — with `detect_model_family:391` (29 lines) as
the resolver. Three sources rather than one is right for a codebase that runs local models
where any one may be unavailable.

---

## Re-verification

**`11o` / `11I` confirmed at the consumer.** `11o` recorded `big_brain.py`'s
`temperature=0.3` and the effort-score fix; `11I` recorded the small-brain counterpart. This
pass confirms both brains call `get_model_profile` and `build_extra_body` — `big_brain.py:508-509`
(plus `needs_flat_system`) and `small_brain.py:300-301`. **Both adapters are live consumers of
this module**, which is why only five of fifteen functions are dead.

**`11C` extended.** `dialogue_tab.py:3852` and `:3946` both test for `"<think>"`, and `11C`
recorded that `:3946` rejects an *unclosed* block inside `_is_bad_dialogue_response`. That is
detection at the tab level; separation happens in `response.py`. The two are complementary, not
duplicative — the tab rejects a turn that burned its budget on hidden reasoning, and
`response.py` strips the blocks from turns it accepts.

**`11N` / `chat_completion` consistent.** `chat_completion.py:346,352,454,687` reads
`reasoning_content` from streaming deltas and messages, which is the same signal
`worker_thinking.py:63` documents as authoritative for budget sizing.

**`11z`'s ARCH-ENG-211 inverted, and that is the good outcome.** `worker_thinking.py:30-32`
exists because *that* scan was private to one place; the response-side logic was consolidated
into `agents/safety/response.py` and is shared. So one side of `11z`'s finding was fixed
properly. BE-01 is what remains: the consolidation reached the *profile-specific* branch
(`response.py:201-210`) by inlining rather than importing, leaving the original behind.

---

## Assessment

Five dead of fifteen, and the file is in good shape structurally — a well-designed profile
table, three detection sources, a minimal request builder, and a shared response-cleaning
layer that gets the hard precedence right.

**BE-01 is the finding worth acting on**, and it is small: four live copies of one regex with
inconsistent case-handling. It is the third instance in this sweep of *"the same decision
expressed N times, with N different answers"* — after `11v`'s 27 boolean parsers and `11L`'s
drifted help catalog — and the cheapest of the three to fix, because unlike the other two it
is a pure code consolidation with no data to re-derive.

**BE-02 needs one check before deletion rather than after.** The dead copy is not identical
to the live inline version: the inline regex tolerates whitespace the original did not. That
difference is an improvement, and it means the original documents the contract while the
inline version is the better implementation — the reverse of the usual. Worth confirming that
`channel_thought` coverage in `response.py:206` is at least as broad as
`model_profile.py:525-527` before removing the specification.

**BE-04 is worth a sentence in the fix list rather than a line edit.** `supports_vision` reads a
profile field that nothing consumes. Either the vision capability is used somewhere this sweep
has not reached, or vision support is declared in 14 family profiles and never acted on — which
would be the same shape as `11D`'s AW-01 (a panel the operator cannot reach), one layer down.
