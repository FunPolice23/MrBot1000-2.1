# 11C — `gui/tabs/dialogue_tab.py` depth pass (4398 lines, 94 methods)

> **LOW TIER CLOSED in v2.1.125.** AV-02 (ARCH-ENG-273): `_log_dialogue_turn` is
> now called from both turn sites (human send and persona response) through the
> instance seam `self._append_dialogue_log`, which is bound to the JSONL writer
> rather than aliased back to the UI append. AV-03 (ARCH-ENG-279):
> `_dialogue_model_blocked` is consulted before a turn runs; a sub-2B or base
> checkpoint is refused with the reason and the fix, and any evaluation error
> counts as not blocked so the gate can never become a new failure mode.
>

Depth-pass #29 of 83. The largest file swept so far. **4 dead of 94** — the scan first
reported 16, and the difference is the eleventh hidden-reference form. But the finding that
matters is not the dead count: **a 484-line validator's verdict is discarded on the
exhaust path**, and the remediation written for that exact case is never called.

---

## Structure

```
L   49-58    _WorkerCancelled
L  233-3537  DialogueTab        (80 methods)
L 3540-4398  DialogueWorker     (10 methods)
L   36-279   imports, DialogueLog seam, __init__ (84 lines)
```

Docstring: *"Persona-driven goal dialogue (v2.1). Driver (big, **5060 Ti**) and Navigator
(small, **1660 Super**) hold a goal-driven, fluid working conversation through a lifecycle:
discuss → discover → discuss → plan → discuss → action → discuss → monitor → (repeat)."*

Largest methods: **`_is_bad_dialogue_response` (484)**, `_on_response_ready` (424),
`get_dialogue_context` (271), `setup_ui` (182), `respond` (146), `run` (126),
`_build_opportunity_board` (115).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| **AV-01** | **high** | **A response that `_is_bad_dialogue_response` rejects is emitted into the shared transcript anyway once retries are exhausted.** See below. |
| AV-02 | low | **The `DialogueLog` sink is orphaned, and its test seam is broken.** `_log_dialogue_turn` (`:885`, 28 lines) is dead, and its only call to the module-level `_append_dialogue_log` (`:910`) is the sole non-definition use of `gui/panels/dialogue_log.py`'s `_append_dialogue_log` in the entire tree. Separately, the instance seam set at `:279` — `self._append_dialogue_log = self._append` — is **not what the method calls**: `:910` calls the module-level function. `tests/dialogue/test_dialogue_vram_tier.py:132` monkeypatches `dt._append_dialogue_log`, so it cannot intercept the module-level call. Even if `_log_dialogue_turn` were wired, that test seam would not engage. |
| AV-03 | low | **`_dialogue_model_blocked` (`:576`, 9 lines) is dead.** It returns `(blocked, reason)` for capacity/tuning gating — refusing a sub-2B model or a *base* (non-instruct) model with a stated reason. The operator's small brain runs on a **1660 Super**, where a base or small model is the realistic mistake; the gate that would explain *why* is not applied. |
| AV-04 | info | **`_clean_model_response` (`:565`, 10 lines) is dead** — strips the glued `' thinking'` marker that some local models emit at the start of a reply. The artefact reaches the dialogue view unstripped. |

---

## AV-01 — the exhaust path discards the verdict

`DialogueWorker.run` implements a careful, well-documented retry:

```python
3833   if self.anti_repetition and (
3834       self._is_bad_dialogue_response(response)
3835       or self._is_repetitive(response)
3836   ):
3837       # Try again with a stronger prompt
3838       for attempt in range(self.max_retries):
...
3872           if not self._is_bad_dialogue_response(response):
3873               break
3874
3876   response = response or "(empty)"
3877   self.progress.emit(self.speaker, response, False)
3878   self.response_ready.emit(response, self.speaker)
```

**The `for` loop ends without `break` when the retries are exhausted, and control falls
straight through to `:3876`.** The still-rejected response is emitted into the transcript.
`response or "(empty)"` does not help: it substitutes only for a falsy string, and
`_is_bad_dialogue_response:3924-3925` rejects the empty string *first*, so a genuinely empty
turn was already retried before reaching here.

So the validator's verdict is honoured **during** retries and discarded **after** them.

**Why that is high severity, in the validator's own words.** Its docstring (`:3916-3922`):

> *"Reject model boilerplate, corruption, and **unverified action narratives**. A persona
> turn must be a concrete, evidence-grounded decision or ask. Anything that **narretes tool
> calls, claims external completion**, reveals model identity, repeats a boilerplate phrase,
> or degenerates into a token loop **is rejected before it can enter the shared transcript**."*

The promise is *"before it can enter the shared transcript."* The exhaust path is how it
enters. And the rejected content is precisely the dangerous kind: a response **claiming
external completion** that the validator judged ungrounded reaches the operator — and every
downstream reader of that transcript — as a persona turn.

**The remediation exists, is correct, and is dead.** `_safe_fallback_response`
(`:3691-3708`):

```python
"""Return a bounded, phase-aware fallback when retries are exhausted."""
bits = ["BLOCKED: the model could not produce a usable response after a retry."]
```

and its non-discover branch says:

> *"No registration, account creation, or external commitment may be **declared approved
> from dialogue alone**."*

That sentence exists **only** in the dead method. It is the guard-rail for precisely the
failure AV-01 opens, and the exhaust path is the only place it would ever be needed.

This is the sweep's recurring defect — *"mechanism correct, wired at one end only"* — at its
most operationally consequential point, and it is the **eighteenth** instance. It is also
the mirror image of `11w`'s `_stated_usd`: there, an unverified figure is refused; here, a
verified refusal is discarded.

**Why it is likely to fire on this hardware specifically.** The docstring names the operator's
two cards — Driver on a 5060 Ti, Navigator on a **1660 Super**. Running quantised local
models, empty turns, unclosed `<think>` blocks and token loops are *routine*, which is why a
484-line validator exists at all. AV-03's dead capacity gate makes it more likely still: a
base (non-instruct) model can be selected with no warning, and the validator will then
reject nearly every turn — driving straight to the exhaust path.

---

## The eleventh reference form — Qt signal connections

The AST scan reported **16 dead of 94**. Eleven were false negatives, every one connected
as a Qt signal handler:

```
:1122  self.reset_btn.clicked.connect(self.reset_dialogue)
:1014  self.force_btn.clicked.connect(self.force_forward)
:1145  self.thoughts_btn.clicked.connect(self._show_thoughts)
:1113  self.live_btn.clicked.connect(self._toggle_live)
:1135  self.image_btn.clicked.connect(self._attach_image)
:1127  self.help_btn.clicked.connect(self._open_help)
:1083  self._create_collapsible_panel(..., self._add_task)
:1514  self._progress_throttler.connect(self._on_dialogue_progress)
:1516  worker.gpu_progress.connect(self._on_gpu_progress)
:1517  worker.tool_activity.connect(self._on_tool_activity)
:1005  self.goal_input.returnPressed.connect(self._apply_goal)
```

`obj.signal.connect(self._handler)` is an **attribute load**, not a call — so neither the
AST `Call`-target scan nor a name-based regex sees the reference. That is **266 lines** across
`_show_thoughts` (79), `reset_dialogue` (67), `_on_tool_activity` (57) and
`_on_dialogue_progress` (45) alone.

This is the **eleventh** mechanism the sweep has had to learn, after absolute imports,
dict-valued dispatch (`11y`), attribute-access return types, relative imports,
package-facade re-exports, `from pkg import module as alias`, subpackage paths,
`from pkg import module`, self-exclusion from the caller search (`11s`), comment-only
references (`11v`), and cross-drive path scope (`11A`). **In a PySide6 codebase this is not
an edge case — it is the dominant wiring idiom**, and any reachability scan run over `gui/`
will under-report by a large margin unless it explicitly handles `Signal.connect`.

---

## Verified as sound

**ARCH-ENG-056 — the retry budget fix (`:3850-3867`)** is the clearest example of the
sweep's best comment in this file:

> *"Qwen-style inline reasoning can consume a short turn budget before producing the visible
> answer… `max(self.max_tokens, 2048)` returned self.max_tokens UNCHANGED for every
> reasoning model — since v2.1.51 a reasoning brain's base budget is already >= the 2048
> thinking headroom, so the recovery turn got no extra room and burned out on the hidden
> channel exactly as the first turn did. Grow it by the larger of +2048 or +50%: strictly
> more room, still a fraction of the model's context, and only this one attempt."*

That is a defect named, root-caused, bounded, and justified in six lines. Note the closing
constraint — *"and only this one attempt"* — which is what stops the fix becoming an
unbounded token spend.

**`_is_bad_dialogue_response` is genuinely excellent work**, and this finding is about its
caller, not it. Beyond the unverified-narrative check: it strips tool syntax via
`_remove_tool_syntax` and rejects when nothing persona-visible remains (`:3934-3940`);
rejects an unclosed `<think>` as *"a recoverable generation failure rather than displaying
chain of thought"* (`:3942-3947`); detects binary corruption by reducing the text to
`0`/`1`/`_` and checking emptiness (`:3950-3953`); and detects self-identification with a
**single regex** rather than a prose list, so newly-introduced models are caught
automatically (`:3957-3959`). 484 lines doing that job is not bloat — it is the depth of
care that local models on a 1660 Super actually require.

**`_WorkerCancelled` returns quietly (`:3879-3883`)** with the reason stated: *"Emitting an
error here would feed a bogus 'Error:' turn into the transcript and could re-arm a Live
continuation after teardown."* Correct — cancellation is not a model failure and must not be
recorded as one.

**Tool-activity accumulation is comment-documented (`:291`)**: *"evidence. Reset by
`_on_tool_activity`; when it exceeds the limit the…"* — the reset responsibility is written
down at the point of the field.

---

## Re-verification

**`11A` confirmed — and its live consumer is here.** `dialogue_tab.py:3121-3122` imports and
calls `skill_index_prompt(max_chars)` from `_build_skill_index` (`:3089`). That consumer is
live, which is why AT-01 (the 17-of-25 truncation) is an operator-visible problem rather
than a latent one.

**`11w` / ARCH-ENG-212 inverted.** `_stated_usd` refuses to let an unverified figure become
money. AV-01 is the same requirement inverted: a *rejected* figure — an unverified action
narrative — becomes part of the permanent transcript anyway. The two findings are the same
principle applied at the two ends of the pipeline, and they fail in opposite directions.

**`11n` / chat_completion consistent.** Both are dialogue-response surfaces; `chat_completion.py:520-524`
and `:635-639` call `runtime.execute_tool(...)` for tool handling, the same
`_DISPATCH_CAPABILITY`-gated path `11z` verified.

**`11t` unaffected.** No approval queue involvement — the dialogue tab produces turns, not
approvals. The `_safe_fallback_response` text's *"No registration, account creation, or
external commitment may be declared approved from dialogue alone"* is a **prompt-side**
restraint, and is the tab's counterpart to `11v`'s verified-approval requirement.

**`10e-agents-dialogue` consistent.** This file is the largest surface of that area, and the
area sweep's themes (phase lifecycle, persona gating, APPROVED/BLOCKED convergence) are all
visible here.

---

## Assessment

Four dead methods, eleven scan false-negatives, and one high finding.

**AV-01 is the most valuable result in the depth pass since `AJ-01`, and it is a genuinely
sad shape.** The codebase contains a 484-line validator whose stated purpose is to keep
unverified action narratives out of the shared transcript, and an 18-line fallback whose
stated purpose is to say *"BLOCKED: the model could not produce a usable response"* when
retries run out — including an explicit warning that no external commitment may be declared
from dialogue alone. Both are correct. **The second is never called, and the first's verdict
is thrown away at exactly the moment it matters.**

The fix is one line: at `:3876`, branch on the validator rather than emitting unconditionally
—

```python
if self.anti_repetition and self._is_bad_dialogue_response(response):
    response = self._safe_fallback_response()
```

— which simultaneously wires the dead method and closes the exhaust path. It is worth doing
as a pair, because the two halves are only correct together: calling the fallback *only* on
the exhaust path would miss a response that became bad between the last check and the emit,
and discarding the verdict *without* the fallback would leave the turn empty with no
explanation.

**AV-02 and AV-03 point the same way, and are worth fixing as a group.** The per-turn
telemetry is the diagnostic that would have made AV-01 visible in the field: its record
captures `transport_retry_count`, `empty_retry_count`, `duplicate_retry_count`, `model`,
`tier` and `outcome` — precisely the fields needed to answer *"how often does the exhaust
path fire, and on which model?"* — and none of it is written anywhere. The sink module
exists, the method exists, and the seam is wired to the wrong symbol.

That is the sweep's eighteenth instance of *"mechanism correct, wired at one end only"*, and
the common thread across all eighteen is worth stating once more: **the codebase's hardest
problem is not building defences; it is closing the last hop.** Every instance in this pass
had the defence already written, tested, and documented. What was missing was a call.
