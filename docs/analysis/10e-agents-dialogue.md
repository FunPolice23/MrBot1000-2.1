# 10e — `agents/dialogue/`

> **E-01/E-02 RESOLVED in v2.1.125 (ARCH-ENG-303).** `chat_router.py` is
> deleted with its test and its stale `PROTECTED_SOURCE_FILES` entry; the live
> chat path is `chat_completion.py`. `BoundedDiscussion` is retained as the
> evidence-aware protocol (its executable tests remain) rather than deleted.
>
> 6 scripts, 1,948 lines. The streaming tool-completion loop and the dialogue
> protocols around it.

---

## Structure and reachability

| File | Lines | Reached from |
|---|---:|---|
| `__init__.py` | 1 | — |
| `discussion.py` | 102 | **tests only** |
| `chat_router.py` | 257 | **tests only** |
| `opportunity_analysis.py` | 360 | `gui/tabs/dialogue_tab.py:3227, 3387` |
| `chat_router`-adjacent `convergence_plan.py` | 506 | `dialogue_tab.py` (as `_cp`) |
| `chat_completion.py` | 722 | `agents/safety/calling.py:170` → both brains |

Reachability was checked **exhaustively by every occurrence of every module and
symbol name**, not by a single import-pattern grep — the previous area produced a
false "three ungated flags" result from exactly that shortcut, and `chat_router`
in particular is referenced in four non-import places (a `PROTECTED_SOURCE_FILES`
entry, a help-catalog string, a code comment and the README) that an import grep
would have miscounted.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| E-01 | med | **359 lines in two modules are reachable only from their own tests.** `chat_router.py` (257 lines — `ChatRouter`, `ChatDecision`) is imported by `tests/dialogue/test_chat_router.py` and nothing else. `discussion.py` (102 lines — `BoundedDiscussion`, `DiscussionPurpose`) is imported by `tests/dialogue/test_discussion.py` and nothing else. Both are fully built, documented and tested; neither runs. |
| E-02 | low | **`chat_router.py` is listed in `PROTECTED_SOURCE_FILES` while being unused.** `base_worker.py:104` protects a file no production path reaches. It also appears in `README.md:362` as a documented component of the `dialogue/` package. So the project documents and protects a module it does not use — which is exactly the kind of thing that makes an audit of this kind necessary, and why "zero callers" needed checking against every reference form rather than imports alone. |

---

## Verified as sound — this directory contains the best-reasoned code in the project

**`opportunity_analysis.py` is a model of the financial-integrity rule.**
`analyse_candidate` returns `{requirements, viability, blockers, summary}` — and
**no monetary field at all**. `viability` is a three-valued string verdict
(`blocked` / `needs_review` / `viable`), and line 26 says so in as many words:
*"viability is a deterministic verdict, NOT a score converted to money."* Lines
33–35 and 303 state that it verifies no payment and no earnings — it reads the
listing's own claims and nothing more.

This is the direct counter-example to ARCH-ENG-212, where
`earning_pipeline` synthesised `tvl_usd * apy_percent/100 * 0.01` as
`estimated_usd_value`. The same codebase contains both behaviours, and this
module's docstring is explicit that it refuses the other one: *"NO LLM — a model
must never be the authority on whether a gig is actually doable."*

**`_describe_repeated_tool_call` (ARCH-ENG-110) shows the reasoning, not just the
fix.** The docstring records that a compact local model emits a bare tool call and
nothing else; that the duplicate guard stripped it to `""`; that the empty
response bypassed every capture point; and that Live mode showed a hard failure
with nothing in the log. The replacement wording then *deliberately claims
nothing about what the tool found* — the result is already in the transcript, and
the text must never be read as evidence of a successful search, which it names as
the "financial/epistemic truth rule".

**The loop is bounded.** `chat_with_tools` is 525 lines with
`max_iterations: int = 5` and `for iteration in range(max_iterations)` at `:296`
— no unbounded model/tool cycling.

**`_NOT_EXECUTED_MARKERS` (this file, extended by ARCH-ENG-230) is the anti-drift
guard that caught a real defect.** The prefix list is re-derived from the handler
sources by `tests/safety/test_arch_eng_214_tool_result_honesty.py`, which fails
when a handler emits a new failure prefix not covered here. That is what caught
`[Patch refused` classifying as "executed" for a refusal that executed nothing.

---

## Assessment

The live half of this directory is the strongest code in the project. Both the
tool-execution honesty layer and the candidate analyser encode the operating
principle from `run_lead_routine.py` — *do not allow an LLM response to become
financial truth* — and both do so explicitly in their docstrings rather than
implicitly in their code.

The two dead modules are a different question. `BoundedDiscussion` is a bounded,
evidence-aware discussion protocol for dual-brain collaboration, and
`ChatRouter` routes a chat message to a manager/summarizer and chooses main vs
chat model. Both describe capabilities the Dialogue tab visibly presents. Whether
the tab's collaboration surface is meant to use them, or whether they predate a
simpler design that replaced them, is a question the codebase does not answer —
and that is the useful thing this finding records.

E-02 is worth a moment: a module that is simultaneously in the README, in the
protected-source list, and unreachable is a stronger signal of drift than any
single instance of it.