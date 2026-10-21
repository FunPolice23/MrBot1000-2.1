# 11n — `agents/dialogue/chat_completion.py` depth pass (722 lines, 5 functions)

> **AG-01 REFACTORED in v2.1.125 (ARCH-ENG-277).** The 525-line `chat_with_tools`
> with nine returns is now a ~95-line orchestrator over `_build_chat_messages`,
> `_run_generation`, `_log_empty_visible`, `_gate_tool_call`, `_record_tool`,
> `_text_tool_result`, `_run_function_calls` and `_final_answer`. The duplicated
> gate and trace blocks in the text-call and function-call branches are one
> implementation, so a fix can no longer land in one branch and miss the other.
>

Depth-pass #14 of 83. **Zero dead of 5.** The streaming tool-calling loop, which `10e`
called the best-reasoned code in the project. This pass confirms that at the level of
returns and control flow rather than by reading the docstrings.

---

## Structure

```
L   32-100   _NOT_EXECUTED_MARKERS            (the honesty marker table)
L  102-113   _tool_status                      (12 lines)
L  116-118   _tool_was_executed                (3 lines)
L  121-157   _describe_repeated_tool_call      (37 lines)  -- ARCH-ENG-110
L  160-192   _seed_executed_calls_from_history (33 lines)
L  195-719   chat_with_tools                   (525 lines)
```

`chat_with_tools` is **73% of the file**. That ratio is the structural fact here.

---

## Findings

No dead code and no defects. One maintainability observation, recorded because it is
real and because the alternative reading would be uncharitable.

| ID | Sev | Finding |
|---|---|---|
| AG-01 | low | **`chat_with_tools` is a 525-line function with nine `return` points.** That is a maintenance risk rather than a defect — but it is mitigated more than the shape suggests, below. The file's other four functions are all small and all live, so the concentration is in the loop rather than spread. |

---

## Verified as sound — the honesty discipline is structural, not incidental

**Four of the nine returns are honesty-preserving exits.** Every path where a tool did
not run correctly returns text that *says so* rather than a plausible-looking answer:

| Line | Return |
|---|---|
| `:493` | `_dedup_answer` — the repeat-suppressed answer path |
| `:494` | `_describe_repeated_tool_call(fn_name, fn_args)` — the general repeat case |
| `:562` | *"I named a tool without usable arguments, so nothing was executed and I have no result to report. Tell me the specific URL or query and I will run it properly."* |
| `:704` | *"the model re-issued the tool call after its result was already returned"* |

This is the substantive finding of the pass. A function with nine exits could easily
have two or three unguarded ones — and that is exactly the defect ARCH-ENG-214 found,
where `[Patch refused` classified as "executed" for a refusal that executed nothing.
Here the honesty path is applied at *each* failure exit rather than at one, which is
what makes `_NOT_EXECUTED_MARKERS` (checked at `:111`, inside `_tool_status`) a
sufficient backstop rather than the only defence.

**The loop is genuinely bounded.** `max_iterations: int = 5` at `:201` with
`for iteration in range(max_iterations)` at `:296`. `:596` documents the exhaustion
behaviour. No unbounded model/tool cycling.

**The monolith decomposes internally.** Two nested helpers — `_emit_tool` and
`_user_content` — so the trace-emission and message-assembly concerns are factored out
of the loop body rather than inlined.

**Fifteen parameters, three of them observability hooks** — `tool_trace`,
`stream_progress`, `on_tool_trace`. A loop that both streams partial output and reports
tool activity needs that surface, and having it as explicit parameters (rather than
module globals) is what makes the function testable.

---

## Re-verification

**`10e` confirmed and strengthened.** That pass verified `max_iterations=5` at `:296`
and the ARCH-ENG-110 rationale for `_describe_repeated_tool_call`. This pass adds the
control-flow view: the helper is reached from **two** call sites inside the loop
(`:494`, `:704`) plus one distinct malformed-arguments exit at `:562`, so the
repeat-detection path is not a single branch that could be bypassed.

**`_NOT_EXECUTED_MARKERS` remains the shared backstop.** `10e` recorded that
`tests/safety/test_arch_eng_214_tool_result_honesty.py` re-derives the prefix list from
handler sources and fails when a handler emits a new failure prefix not covered here.
That test is the reason a marker list maintained by hand stays correct.

**ARCH-ENG-227 / O-01 consistent.** The function calls `execute_tool` and
`get_all_tools` via `agents.safety.calling` (`:7-10`), which is the dispatcher
`11g` verified as the single authorization entry point — so every tool this loop runs
has passed through the gate and, where required, a verified approval.

---

## Assessment

Zero dead of 5 in the file that drives every model tool call in the dialogue surface.

AG-01 is worth stating precisely rather than as a complaint. A 525-line function with
nine returns is the kind of shape that usually goes wrong — the question is whether
the returns are *uniform* or whether some are unguarded. Here four of nine are
deliberate honesty exits with explicit operator-facing text, the loop is bounded, the
monolith factors its own helpers, and the observability surface is explicit. That is a
function that has been *hardened* into its current shape rather than one that grew
unattended: every awkward return is there because a specific failure needed a specific
answer.

The comparison worth drawing is with `11c`'s `earning_pipeline.discover` — also a
central function, also with a bounded contract, also correct. Both files were written by
someone who treats an early return as a place where a lie could enter, and both put
the guard on every exit rather than one.

The one thing this pass adds that `10e` could not: the honesty path here is *structural*
(applied per-exit), whereas `_NOT_EXECUTED_MARKERS` is a *backstop* (applied per-result).
Having both is why the tool loop is the most trustworthy surface in the application.