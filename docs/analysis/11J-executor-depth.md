# 11J — `agents/earning/executor.py` depth pass (592 lines, 22 methods)

Depth-pass #36 of 83. **0 dead of 22 — no findings.** The money path's decisive gate, and
this pass **closes the AJ-02 chain from its source**: the empty outcome tables are the
fail-closed branch working exactly as ARCH-ENG-158 intends, and the gate is *satisfiable*.

---

## Structure

```
L   58-64    StepStatus          L   95-110  ExecutionPlan
L   70-89    ExecutionContext    L  116-140  ExecutionResult
L  145-560   TaskExecutor (19 methods)
L  565-566   ExecutionNotPossibleError
L  569-583   _entry_id (module fn)
```

Docstring: *"Generalized Task Execution Framework engine (v2.0.36i). Drives a 14-step
execution pipeline through deterministic validators and human gates, moving a
PortfolioEntry through WorkStatus transitions. **The LLM may suggest; deterministic validators
decide completion.**"*

Largest: `_step12_verify` (92), `execute` (53), `_step13_record_evidence` (35),
`_step14_learn` (28), `_step5_create_plan` (18), `_work_status_for_step` (18).

---

## Findings

**None.** All 22 methods are live.

---

## `_step12_verify` — five fail-closed paths, each with a distinct reason

This is the method ARCH-ENG-158 rewrote, and it is the reason `outcome_memory_v2` and
`outcome_evidence` are empty. It has **five** distinct failure paths, and each records a
*different* reason, so an operator reading the step log learns which of them fired:

| condition | line | status | reason |
|---|---|---|---|
| no evidence store wired | `:372-378` | `BLOCKED` | *"no evidence store wired to the executor; payment cannot be verified"* |
| no evidence at all | `:388-393` | `FAILED` | *"no evidence recorded for this opportunity"* |
| evidence fails the policy | `:419-422` | `FAILED` | *"evidence exists but does not satisfy the SUBMITTED->PAID policy (missing/under-verified required types)"* |
| policy passes, nothing L3 | `:423-425` | `FAILED` | *"no payment evidence at VERIFIED and >=L3_EXTERNAL_SOURCE"* |
| store/policy raises | `:440-445` | `FAILED` | *"evidence check failed: {e}"* |
| **success** | `:410-417` | `COMPLETED` | *"N payment evidence record(s) at >=L3_EXTERNAL_SOURCE satisfied the SUBMITTED->PAID policy"* |

Success requires **both** conditions, not either: `eligible` (the shared policy's verdict
from `evidence_policy.is_transition_eligible`) **and** `qualifying` (records that are
`EvidenceStatus.VERIFIED` and `>= VerificationLevel.L3_EXTERNAL_SOURCE`, `:405-408`).

**The forgery is closed structurally, not by validation** (`:402-404`):

> *"Status and level must be carried by the record itself. **A dict or a bare
> `{"verified": True}` cannot reach here: `for_subject` only ever returns `Evidence`
> instances.**"*

ARCH-ENG-158's original defect was `step_results[12] = {"verified": True}` written as a
literal. The fix does not merely check the dict — it makes the check read **typed attributes
off real objects that the store's type signature guarantees**. `11B` recorded this principle
as *"a type is a guarantee; a validator is a promise"*, and this is the same move applied to
the money gate.

**`:440` states the invariant in the comment**: `# a policy/store error is never a successful
payout`. And the amount is **summed from the qualifying evidence** (`:413-414`) — not from the
task dict, not from the caller — so the figure and the authorisation come from the same
records.

`:363-365` completes the contract: *"**Nothing here consults the caller, the task dict, or the
submission receipt.**"* That is ARCH-ENG-158's *"the caller asserting its own claim, dressed
as a verification"*, refused at the source.

---

## The gate is satisfiable — no circular dependency

`11s`'s AJ-02 correction established that the empty tables are by design. This pass checks the
obvious objection: **can step 12 ever pass, given that step 13 is what records evidence?**

It can. `execute:197-202` runs steps 12, 13 and 14 **unconditionally and in order** — step 12's
verdict does not short-circuit the sequence. And `_step13_record_evidence:450-457` documents
that it is not the source:

> *"This step used to build a hand-rolled dict … and append it to an in-memory list that
> nothing ever read. **It looked like evidence, and a dict is exactly the shape the payment
> gate refuses** … It now records only real `Evidence` objects **that already exist**, and
> persists anything not yet stored. **It never manufactures a payment record.**"*

**Evidence provenance is external by design.** Step 12 reads the store; step 13 only persists
what is already on `ctx.evidence`. So the loop is not circular — the store is populated by
whatever observes the real payment, and the executor is a *reader* of that, never a writer of
its own success.

`:473-474` records the honest version of a no-op run: *"no new evidence was produced by this
run; step 12 resolved any pre-existing records from the store"*.

**`:203-206` is the sentence that protects all of it:**

> *"ARCH-ENG-158: the terminal status is a function of **what step 12 actually proved**, not of
> how far the pipeline walked. **Reaching step 14 is not evidence of payment.**
> `_step12_verify` already recorded its own status; **do not overwrite it**."*

And `:207-211` keeps two concepts apart that are easy to merge:

```python
if ctx.outcome and ctx.outcome.get("paid"):
    return self._build_result(ctx, success=True, status="paid")
reason = (ctx.outcome or {}).get("reason", "no qualifying payment evidence")
return self._build_result(ctx, success=True, status="payment_unverified", detail=reason)
```

**`success=True` with `status="payment_unverified"`.** The *work* succeeded; the *money* is
unproven. Collapsing those into one boolean is exactly the conflation ARCH-ENG-158 removed, and
the code keeps them separate all the way to the caller's result object.

---

## The two early exits are correctly placed

Both are `return`s *before* step 12, so neither can produce a payment claim:

```python
181   if ctx.human_gates:
182       self._record_step(ctx, 6, StepStatus.BLOCKED, "Human gates required")
183       return self._build_result(ctx, success=False, status="awaiting_approval")
...
188   if ctx.validation_report and not ctx.validation_report.passed:
189       self._record_step(ctx, 8, StepStatus.FAILED, "Validation failed")
190       return self._build_result(ctx, success=False, status="blocked")
```

A task awaiting human approval never reaches the verify step at all — so **an un-approved task
cannot even attempt to claim payment.** That is the right place for the gate, and it means
step 12's fail-closed behaviour only ever applies to work that genuinely ran to completion.

---

## Verified as sound

**The module's contract is stated once and honoured throughout** — *"The LLM may suggest;
deterministic validators decide completion."* Nothing in `_step12_verify` consults a model.

**`_work_status_for_step` (18 lines) and `_build_result` (17 lines)** keep the state machine and
the result shaping out of the step bodies, so a step's failure mode is a `StepStatus` plus a
reason rather than an exception the caller must interpret.

**`ExecutionNotPossibleError` (`:565-566`)** is a distinct type for step 4's outcome, so
"cannot be done" is not represented as "failed" — the same distinction `_step12_verify`
maintains between FAILED and BLOCKED.

**`_entry_id` (`:569-583`, 14 lines)** is a module-level helper rather than a method, because
both `TaskExecutor` and module-level code need it — and it is the kind of helper that *should*
be module-level (single responsibility, no state).

---

## Re-verification

**`11s` AJ-02 closed from the source.** `11s` corrected AJ-02 on the basis of `executor.py`'s
docstring; this pass reads the implementation. The chain is now fully established from three
files: `executor.py` (the gate — five fail-closed paths, satisfiable), `earning_memory.py`
(`11F` — the tables the gate would write, empty), and `earning_pipeline.py` (`11c`/`11w` — the
supervisor that never completes an opportunity). **The system is right; the audit layer
(`11r`) and the analytics layer (`11F`) are what have not caught up.**

**`11z` / ARCH-ENG-165 consistent.** `_step12_verify` is the same discipline as
`assert_approval_covers`: authority derived from a shared store rather than a caller-supplied
argument. Both are instances of *"re-read the record that the human actually saw"*.

**`11w` / ARCH-ENG-212 consistent.** `earning_memory.py` refuses to store a fabricated
`estimated_usd_value`; this module refuses to accept one. The producer and the verifier apply
the same rule from opposite ends.

**`11H` consistent.** `safety_tools_tab`'s `_route_decision` re-reads the queue before routing;
`_step12_verify` re-reads the store before paying. **Two unrelated modules, same shape:
the decision is re-read from its authority, never taken from the caller's assertion.**

**ARCH-ENG-158 confirmed complete.** The docstring's three claims — backup-free, evidence
consulted, fail-closed — are all implemented, and the `PAID` transition at `:499-501` remains
gated on `ctx.outcome["paid"]`, which only step 12 can set.

---

## Assessment

Zero dead of twenty-two, on the module that decides whether the system believes it was paid.

There is very little to say about a file that gets this right, which is why this document is
short. The three things worth recording:

1. **`_step12_verify` closes the forgery structurally.** ARCH-ENG-158's defect was a dict
   literal; the fix reads typed attributes from objects the store's signature guarantees, so
   the forgery no longer has a shape that can reach the check. That is `11B`'s *"a type is a
   guarantee; a validator is a promise"* applied to money — and it is the right order of work.

2. **The gate is satisfiable, and that was worth checking.** A fail-closed gate whose evidence
   is recorded by a later step would be a deadlock dressed as a safety property. Step 12 reads
   the store; step 13 only persists what already exists; provenance is external by design. The
   empty tables are therefore a true statement about the world, not an artefact of the
   implementation — which is the distinction `11s` needed and this pass supplies from the
   source.

3. **`:203-206` is the most valuable single line in the codebase for anyone about to
   "simplify" it:** *"Reaching step 14 is not evidence of payment… do not overwrite it."* Every
   remaining finding in this sweep is a missing last hop. This line is the guard against
   reintroducing one, and it is a comment rather than an assertion — so it is the first thing
   a future refactor would delete.

That last point connects to the note at the end of `11I`. **These findings have accumulated
enough to be worth reviewing as a set rather than one file at a time**, with the "do not wire"
items (`AJ-02`, `AN-03`, `AQ-01`, `BA-01`) listed separately from the genuinely fixable ones.
The sweep has 47 files left; the marginal value of continuing file-by-file is now below the
value of consolidating what exists.
