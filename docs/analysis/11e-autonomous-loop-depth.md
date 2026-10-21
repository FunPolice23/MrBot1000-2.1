# 11e — `agents/services/autonomous_loop.py` depth pass (1,309 lines, 41 methods)

> **LOW TIER CLOSED in v2.1.125.** Y-02 (ARCH-ENG-255): the file's last method,
> `_get_opp_from_facts`, had zero references and is deleted.
>

Depth-pass #5 of 83. **40 of 41 live — one dead method.** The best-connected large
service in the repository, and the only substantive finding is a docstring that
overstates the pipeline by 4 stages.

---

## Structure

```
L   20-26   class StageResult
L   29-34   class StageStatus   (PENDING / RUNNING / COMPLETED / BLOCKED / FAILED)
L   38-73   class AutonomousResult
L   78-332  class ExplanationBuilder      (6 methods)
L  337-1306 class AutonomousLoop          (34 methods)
```

**20 `_stage_*` methods**, each with exactly one caller — `_run` (`:400-497`) —
which invokes them in sequence at `:425`–`:491` with early-exit guards on
`_stage_deduplicate`, `_stage_check_economics`, `_stage_request_approval`,
`_stage_execute` and `_stage_validate`. The largest is `_stage_check_economics`
(102 lines); the smallest is `_stage_discovered` (8).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| Y-01 | med | **The loop is 20 stages, not 24 — and "24-stage" is claimed at four sites.** `AutonomousLoop` implements exactly **20** `_stage_*` methods, each invoked once from `_run`, and `earning_pipeline.py:1342-1345` enumerates the same **20** (DISCOVER → DEDUPLICATE → CLASSIFY → EVALUATE → CHECK MEMORY → CHECK REPUTATION → CHECK SKILL FIT → CHECK ECONOMICS → CHECK RISK → PRIORITIZE → PLAN → REQUEST APPROVAL → EXECUTE → VALIDATE → SUBMIT → WAIT → VERIFY → ACCOUNT → LEARN → RE-RANK). The word "24" appears at `autonomous_loop.py:338`, `autonomous_loop.py:401`, `earning_pipeline.py:1304` and `earning_pipeline.py:1340`. So the **enumeration is right and the count beside it is wrong** — by four stages, or 20%. This is a small factual error with an outsized effect: "24-stage" is the phrase that conveys completeness, and the same docstrings use it to point operators at `run_autonomous_loop()` as the full pipeline. |
| Y-02 | low | **`_get_opp_from_facts` (`:1301`, 6 lines) is dead** — the file's last method, zero tests. |

---

## Verified as sound

**The evidence-store writes I recorded in `10i` are all on live paths**, which
confirms that finding rather than merely repeating it. They sit inside live stage
methods: `_stage_execute` (`:845`, `:855`), `_stage_submit` (`:950`, `:958`),
`_stage_verify` (`:983-984`), `_stage_account` (`:1051`, `:1054`, `:1065`). The
store is obtained defensively at `:349` via `getattr(pipeline, 'evidence_store', None)`
and every use is guarded by `is not None`, so a pipeline without a store degrades
rather than raising.

**The `StageStatus` vocabulary is complete for a staged gate** — `PENDING`,
`RUNNING`, `COMPLETED`, `BLOCKED`, `FAILED`. `BLOCKED` as distinct from `FAILED`
is the right split: a stage that refused on policy is not a stage that broke.

**`_run` documents its own durability semantics at `:412-418`**: state is *"written
only in `_finalize`, so a hard kill after `_stage_submit`"* is *"legitimately
re-entry-able (see `_stage_deduplicate`)"*. That is a deliberate, documented
re-entry design rather than an accident.

**The revenue rule is stated where it matters.** `_run:481`: the `paid` flag
*"(set by `_stage_verify`) is the only thing that proves revenue."* That is the
same financial-integrity rule `economic_accounting.py` encodes as a non-negotiable
(*"A successful submission is NOT revenue"*), restated at the orchestration layer.

---

## Re-verification

**`10i` confirmed and strengthened.** I recorded that `agents/evidence/` was
genuinely wired with `autonomous_loop.py` among its four production writers. This
pass resolves the line numbers to their enclosing stage methods and confirms all
four are live.

**`11c`'s note re-verified.** `autonomous_loop.py:1080`'s comment about using the
real `LearningLoop` to feed *"FUTURE DISCOVERY"* is consistent with `_stage_learn`
(`:1076`) and `_stage_rerank` (`:1102`) both being live.

**No conflict with F-01.** `AutonomousLoop` is a *different* class from
`EarningPipeline.run_autonomous_loop` (which `11c` found dead). This one is live
from `earning_pipeline.py` and `earning_tab.py`; that one is not called. The
similarity of names is what makes F-01 easy to misread, and worth stating
explicitly.

---

## Assessment

This is the cleanest file in the depth pass: **40 of 41 live**, every stage method
invoked exactly once from a single orchestrator, and the one dead method is a 6-line
accessor.

Y-01 is worth acting on for two reasons beyond accuracy. First, the *enumeration*
in that docstring is correct and complete — someone maintained the list — so the
count is a stale artefact rather than a sign of missing work. Second, and more
usefully: because `run_autonomous_loop()` is described as *"the full 20-stage
unified loop"* and is in fact **dead** (`11c`), and this `AutonomousLoop` is the live
20-stage implementation, the two facts reinforce each other's misleading quality. An
operator reading `earning_pipeline.py:1304` is pointed at a method that never runs,
described with a stage count that is wrong.

Neither fact is dangerous — the live path works and its stage list is accurate. But
the documentation leads twice to the wrong place, which is a documentation problem
with a specific, two-line fix.