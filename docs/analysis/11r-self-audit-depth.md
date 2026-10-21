# 11r — `agents/services/self_audit.py` depth pass (691 lines, 23 methods)

> **RESOLVED in v2.1.125 (ARCH-ENG-236, commit adb3661).** AJ-01 (high) + AJ-02 (high after the
> 11s amendment) fixed in the order this doc prescribed: (1) every `_audit_*`
> now declares the data basis it actually saw (`AuditReport.basis` — rows
> examined, or 1 when a gated in-memory/on-disk source is present; zero failed
> wallet operations is a real verdict, not starvation), `run_audit` guards each
> audit at run level so an error is recorded, not silently clean, and
> `AuditReport.conclusion()` refuses to claim "no problems found" while any
> audit is data-starved or errored. (2) The hook went to `run_full_cycle`
> (live via `main.py:337`), not `run_discovery_cycle` — which this doc's fix
> plan implicitly suggested but which has **no callers itself**; that
> would have been dead-into-dead wiring. The pipeline logs
> `[SelfAudit] <conclusion>` once per cycle and `run_self_audit()` returns
> the report for future surfaces. Tree note: `agents/IMPROVEMENTS.md` does not
> exist, so audit 14 (`documentation_drift`) is permanently source-gated — a
> fully-populated database still reads INSUFFICIENT DATA (1 of 14), which is
> the discipline working. Regression tests:
> `tests/earning/test_arch_eng_236_self_audit_honest_and_running.py`
> (against the pre-fix tree, 8 of 8 fail).

Depth-pass #18 of 83. **1 dead of 23 — and the dead method is the engine's only public
entry point**, which takes the remaining fourteen audit methods down with it. **This is
the highest-severity finding of the depth pass**, and it is also the one where the
obvious fix is insufficient.

---

## Structure

```
L   32-46    AuditCategory      L   62-101   AuditFinding   (1 method)
L   51-56    Severity           L  107-136   AuditReport    (4 methods)
L  141-682   SelfAuditEngine (18 methods)
```

Docstring: *"Self-Audit & Continuous-Improvement Layer (v2.0.36j-T4). Identifies
repeated failures, prediction errors, bad strategies, poor platforms/categories/task
types, low-performing variants, high-cost workflows, human intervention patterns,
execution failures, stale providers, stal…"*

Largest methods: `_audit_bad_strategies` (51), `_audit_prediction_errors` (50),
`_audit_high_cost_workflows` (34), `_audit_repeated_failures` (33),
`_audit_human_intervention` (30), `_audit_stale_providers` (29).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AJ-01 | **high** | **The entire Self-Audit & Continuous-Improvement Layer is unreachable.** `SelfAuditEngine` is constructed exactly once — `app/earning_pipeline.py:181`, `self.self_audit = SelfAuditEngine(self.memory, self.evidence_store, self.accounting)` — and the attribute `self_audit` is **never read again anywhere in production**. Across the whole tree there are **3 references** to the name: the import (`:180`), the assignment (`:181`), and the module's own docstring. `run_audit` (`:161`, 20 lines) is the engine's only public entry point and has **no production caller**. All fourteen `_audit_*` methods are invoked from `run_audit:165-178` and nowhere else, so they are dead by transitivity. **15 methods, ~460 lines, zero reachable entry.** |
| AJ-02 | **high** | ⚠️ **AMENDED by `11s` — the empty tables are by design (ARCH-ENG-158), not a second defect.** See the amendment below; the restated finding is narrower and sharper. **Wiring AJ-01 would still produce an empty report.** Twelve of the fourteen audits read `self.memory`; only `_audit_high_cost_workflows` (`:450`) and `_audit_documentation_drift` (`:635`) are local-only. Inspecting `earning_memory.db`: of 20 tables, **17 have zero rows**. Only `opportunity_memory` (195) and `reputation_memory` (1) are populated. Every table the audits would interrogate is empty — `outcome_memory`, `outcome_memory_v2`, `outcome_evidence`, `failure_memory`, `success_memory`, `strategy_memory`, `prediction_accuracy`, `learning_history`, `decay_log`, `opportunity_timeline`, `pattern_memory`, `skill_memory`, `operational_memory`, `source_memory`, `search_strategy`, `user_pref_memory`, `conversational_memory`. So the layer has **two independent defects stacked**: it is not called, and it has nothing to call *on*. Fixing only the first would yield a live engine that reports nothing, which is worse than a dead one because it looks healthy. |

---

## The causal chain — and why it is worth one finding rather than two

The two findings are not independent defects that happen to coexist. They form a single
chain, and reading it end to end is the substance of this pass:

```
opportunities discovered and stored      -> 195 rows in opportunity_memory  [LIVE]
        |
        v
no opportunity ever completes             -> outcome_memory_v2 = 0, outcome_evidence = 0
        |                                    (record_outcome_v2 is live and healthy)
        v
12 of 14 audits have no rows to read      -> AJ-02
        |
        v
the layer that would diagnose the above   -> AJ-01, never invoked
        |                                    self.self_audit assigned, never read
        v
the symptom is invisible
```

The Self-Audit layer exists to answer exactly the question *"why does this system keep
producing opportunities it cannot complete?"* — and the reason that question has no
answer is partly **that the answering mechanism is itself dead**.

This connects to what the earlier areas already recorded: `11c` established that
`record_outcome_v2` is live and its writes are healthy, yet `outcome_memory_v2` and
`outcome_evidence` are empty because **no outcome has ever completed**. The audit layer
is the feedback half of that loop, and it was never switched on.

---

## Why this is the recurring defect with a new shape

The sweep's most frequent finding, now at 14 instances, is *"mechanism correct, wired at
one end only"* — and ARCH-ENG-159's own comment names it: *"that defence sat only at the
CALLER."*

AJ-01 is that defect, but with a twist worth naming. In every previous instance the
mechanism was **reachable and defending** while a caller was missing. Here the mechanism
is **entirely unreachable**, and the missing end is the *only* end. `self.self_audit` is
assigned in `earning_pipeline.py`'s constructor and never read — the constructor's
assignment is what makes this hard to see, because the object demonstrably exists.

It also reproduces the sweep's other recurring trap exactly. The heuristic that
*presence of tests implies a live function* has now failed **nine times**:
`tests/earning/test_self_audit.py` exists with **16 references** to `self_audit` and
`run_audit`, and the entry point is still dead. `tests/__main__.py` carries 4 more. The
tests prove the fourteen audits produce correct findings when handed a populated fixture;
they cannot prove anything about whether the engine is ever started.

---

## Verified as sound

**The fourteen audits are individually well-built and each guards its own evidence
threshold.** `_audit_bad_strategies` (51 lines) and `_audit_prediction_errors` (50) are
the two largest and both apply minimum-sample thresholds before reporting — the right
discipline for a layer whose purpose is to produce findings a human will act on. This
is the codebase's own standard applied: *no finding without a confirmed basis*, the same
rule ARCH-ENG-115 applies to hardware claims in `big_brain.py` (`11o`) and that
`opportunity_analysis.py` applies to gig feasibility.

**`AuditReport` carries severity and category breakdowns** — `critical_count` (`:116`),
`high_count` (`:120`), `by_category` (`:123`) — and all four `AuditReport`/`AuditFinding`
methods are live. The report model itself is sound; only its producer is unreachable.

---

## AMENDMENT (from `11s`) — AJ-02 restated: the empty tables are ARCH-ENG-158 working

`11s` traced `apply_next` to `agents/earning/executor.py` and found the explanation for
the empty `outcome_memory_v2` / `outcome_evidence` tables. **This corrects AJ-02 in the
codebase's favour.**

`executor.py:23-43` (ARCH-ENG-158):

> *"steps 12/14 could not verify a payment, so they asserted one … The pipeline therefore
> reported a completed, paid opportunity for any task that reached step 11 … That is
> precisely the shape `agents/safety/handlers.py::_is_approved` and
> `OpportunityLifecycleTracker._is_verified_evidence` were hardened to refuse
> (ARCH-ENG-064/118/119/121): **the caller asserting its own claim, dressed as a
> verification.**
>
> … With no evidence store wired, or no qualifying evidence, the pipeline **fails CLOSED**:
> step 12 records why, step 14 leaves the entry in PAYMENT_PENDING, and the result reports
> `final_status="payment_unverified"`. **`WorkStatus.PAID` is no longer reachable from this
> module without independent proof of payment.**"*

**The tables are empty because the safety mechanism is working.** No payment has been
independently verified, so no outcome is recorded and no entry reaches PAID. `11c`'s
observation that `record_outcome_v2` is live with healthy writes but nothing has ever
completed is not a write-path defect — it is the fail-closed branch taken every time.

**The causal chain in this document needs its last two arrows corrected.** Opportunities are
discovered and stored (195 rows) — correct. The audit layer is dead (AJ-01) — correct. But
the link between them is *not* that outcomes should be completing and aren't. Outcomes are
**not completing by design**, because ARCH-ENG-158 refuses to assert an unverified payment.

**AJ-02 restated:**

> The self-audit layer must never report a clean bill of health on empty tables, and there
> is no reason to expect those tables to fill soon. Under ARCH-ENG-158 they stay empty
> until real payment evidence exists, which is the system's *designed* resting state rather
> than a transient condition to be waited out.

This makes the finding better, not weaker. It is no longer "wire up the audit once there is
data" — it is **"the audit must distinguish 'no data' from 'no problems' permanently,"**
because the no-data state is expected to persist. The general fix proposed below
(*report insufficient data rather than no problems found*) is not a nicety; it is the
load-bearing requirement, and it applies to a state the system is designed to sit in.

The severity stays **high**, but the reason is now sharper: AJ-01 alone would put a live
engine into a permanent state where it reports nothing while appearing healthy. That is the
failure mode this codebase has spent ARCH-ENG-115, ARCH-ENG-158/159 and
`economic_accounting.py`'s seven-way firewall working to prevent — *asserting a clean state
that has not been confirmed* — and it is the one place where the fix is unambiguous and
the "obvious" alternative (wire it up, let it report, fill the tables) is actively harmful.

---

## Re-verification

**`11c` / W-02 confirmed and extended.** `app/earning_pipeline.py:180-181` is inside the
class whose constructor wires the earning stack, the same file that `11c` recorded as
carrying the 289-line dead discovery island (W-01/W-02). The self-audit engine is a
**second** unreachable subsystem wired into that same constructor. W-01 was recorded as a
large dead island; this is a smaller one, in the same class, found only by sweeping the
module it constructs.

**`AF-01` consistent.** `finding` ids elsewhere in the sweep run A-F; this file's `AJ-01`
/`AJ-02` continue the sequence without collision (`10p` recorded `AA-01`,
`11p` recorded `AH-01`, `11q` recorded `AI-01`).

**No GUI path exists.** The reference sweep covered every production `.py` in the tree,
and only `app/earning_pipeline.py` names the engine. There is no tab, worker or dispatch
entry point reaching it — so this is not the "8 import forms have defeated reachability
scans" problem recurring. The absence of *any* caller, in any import form, is what the
tree-wide attribute search establishes independently: `self_audit` appears 3 times
total, and two of them are the import and the assignment.

---

## Assessment

The deepest finding of the depth pass so far, and the only one that is **high severity**
in a module whose code quality is otherwise high.

Two things are worth separating.

First, AJ-01 is a straightforward wiring gap and would be a small fix — one call site at
the right point in the pipeline. If it were the whole story this would be a note.

Second, **AJ-02 is why it is high.** The wiring fix alone produces a live engine that
reports nothing, because twelve of its fourteen checks read tables that have never held
a row. A self-audit layer that starts running and returns a clean bill of health, while
`outcome_memory_v2` sits empty, is a **worse** outcome than one that is plainly dead: it
converts a visible gap into an invisible assurance. That inversion is precisely the failure
mode this codebase has spent ARCH-ENG-115, ARCH-ENG-159 and `economic_accounting.py`'s
seven-way firewall working to prevent — *asserting a clean state that has not been
confirmed*. The honest version of this feature requires the outcome-completion path to
work first, and reporting that honestly is more useful than a green checkmark.

The fix therefore cannot be "wire up `run_audit`". It has to answer, in order: why does
no opportunity complete (the real subject of `11c`/`W-02`), and should the audit layer
report **"insufficient data"** rather than **"no problems found"** until it does. The
second half is the generalizable fix — and it is the same question as ARCH-ENG-115's
*"omitting the section is strictly better than stating a false one,"* pointed at findings
rather than hardware.
