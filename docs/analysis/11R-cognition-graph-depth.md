# 11R — `agents/cognition/graph.py` depth pass (523 lines, 22 methods)

> **RESOLVED in v2.1.125 (ARCH-ENG-233, commit beb90e8).** BG-01 (high): the
> `CognitionRecord` cluster and the ledger/state/memory_promotion/contradictions
> satellites were deleted — verified no production consumer before the cut.
> BG-02 (med): resolved by the deletion — the three lax predicates lived in the
> deleted code; the strict live gate `action_eligible` is untouched. BG-04
> (info): resolved by the same deletion. BG-03 (low): still open
> (`ThoughtGraph.measure_all` remains part of the live half, recorded not
> fixed). Hand-verification before the fix corrected one detail in this doc:
> `dialogue_honesty.py`'s `Claim` is `fact_ledger`'s, not the graph cluster's,
> so the cluster's `Claim` had no production reference at all; and the island
> was covered by six test modules, not five — `test_thought_graph.py` touches
> `CognitionRecord` in one test (removed; the file's `ThoughtGraph` tests
> kept). `test_collaboration_failures.py` was mixed and its live half
> (`BoundedDiscussion` budget) was relocated to `test_discussion.py`.
> Regression tests: `tests/engineering/test_arch_eng_233_cognition_island_removed.py`.

Depth-pass #44. **A complete second cognition system, ~170 lines plus three satellite
modules, that loads in production and is called by nothing.** Covered by five test
modules, none of which run in the product.

---

## Structure

```
L   18-83    enums: InformationKind, ClaimStatus, ApprovalState, ActionState,
                     OutcomeState, ThoughtNodeKind, ThoughtEdgeKind
L   87-161   ThoughtNode(2)  ThoughtEdge(1)  SupportMeasure(2)
L  164-342   ThoughtGraph (10 methods)
L  346-514   InformationItem, Claim, Option, Decision, ApprovalRequest,
             ActionIntent, ToolExecution, Outcome, Lesson, CognitionRecord(3)
```

Module docstring:

> *"Typed cognition artifacts for inspectable dual-brain orchestration. These records
> describe reasoning state **without exposing private chain-of-thought**. They are
> **coordination contracts, not a second evidence system**: factual claims reference
> EvidenceStore records by id, while execution and approval state remains owned by the
> dispatcher and human approval workflow."*

Largest: `measure_support` (70), `CognitionRecord.validate` (23), `rank_options` (22),
`_has_dependency_cycle` (21), `CognitionRecord.to_dict` (21).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| BG-01 | **high** | **The entire `CognitionRecord` cluster (`:346-514`, 11 dataclasses, ~170 lines) has no production consumer** — yet it is *loaded* on every run and covered by five test modules. Details below. |
| BG-02 | **med** | **The evidence gate is expressed four times in two shapes with two different strictnesses.** The live expression is the *strictest*; the three dead ones are looser. Details below. |
| BG-03 | low | `ThoughtGraph.measure_all` (`:299`, 6 lines) — the whole-graph diagnostic summary — has no caller. Its docstring says *"for diagnostics and UI summaries"*; there are none. |
| BG-04 | info | `CognitionRecord.is_valid` (`:491`, 2 lines) — `not self.validate()`, a shorthand for a validator with no production caller. |

**Narrow scan result: 5 dead of 21** (excluding two `__post_init__` dataclass-machinery
false positives). The island analysis below is the more consequential result.

---

## BG-01 — a second cognition system that loads but is never called

**What IS live**, and verified from both ends:

```
app/earning_pipeline.py:26   from agents.earning.got import OpportunityGraphPlanner
  └─ agents/earning/got.py:15-22   from agents.cognition import (
                                    SupportMeasure, ThoughtEdge, ThoughtEdgeKind,
                                    ThoughtGraph, ThoughtNode, ThoughtNodeKind)
     └─ got.py:36    if self.support.action_eligible
        got.py:173   self.graph.measure_support(option_id, self.evidence_by_id)

agents/brains/big_brain.py:153  from agents.brains.brain_got import start_brain_turn
agents/brains/small_brain.py:136  (same, lazy)
  └─ brain_got.py:14-21   from agents.cognition import (ThoughtEdge, ThoughtEdgeKind,
                            ThoughtGraph, ThoughtNode, ThoughtNodeKind)
     └─ brain_got.py:65   self.graph = ThoughtGraph()
        brain_got.py:256  self._branch_scores = self.graph.rank_options(...)
        brain_got.py:352  "action_eligible": m.action_eligible
```

So the **`ThoughtGraph` half (`:18-342`) is genuinely load-bearing** — it is the support
propagation behind both the earning pipeline's option ranking and the brains' branch
scoring. This is real, and it is the reason `graph.py` is worth sweeping.

**What is not live** is everything from `InformationItem` (`:346`) down. `brain_got.py`
and `got.py` import **six** names from `agents.cognition` — and all six are from the
`ThoughtGraph` half. None of them import `CognitionRecord`, `Claim`, `Outcome`, `Lesson`,
or any of the other eleven.

A name-by-name production-usage sweep (excluding tests) confirms it. Every symbol below
appears **only inside `graph.py` itself and its `__init__.py` re-export**, plus at most
one same-package consumer:

| Symbol | Production references outside `agents/cognition/` |
|---|---|
| `InformationItem` | **none** |
| `Option`, `Decision`, `ApprovalRequest`, `ActionIntent`, `ToolExecution` | **none** |
| `OutcomeState`, `ActionState`, `ApprovalState`, `InformationKind` | **none** |
| `CognitionRecord` | **none** |
| `Claim` | `agents/cognition/dialogue_honesty.py` only |
| `Lesson` | `agents/cognition/memory_promotion.py` only |
| `Outcome` | `agents/autonomy/*` — a *different* `Outcome`, not this one |
| `ThoughtGraph`, `ThoughtNode`, `ThoughtEdge`, `SupportMeasure`, `ThoughtNodeKind`, `ThoughtEdgeKind` | **live** (`brain_got.py`, `earning/got.py`) |

### The island's shape

```
tests/dialogue/test_cognition.py                 ─┐
tests/dialogue/test_cognition_observability.py    ─┤
tests/dialogue/test_memory_promotion.py           ─┼──> ledger.py   ─┐
tests/runtime/test_collaboration_failures.py      ─┤    state.py     ─┼──> CognitionRecord
tests/dialogue/test_contradictions.py            ─┘    memory_      ─┘    (and its 11 siblings)
                                                          promotion.py
                    ↑ every one of these four modules is imported by exactly ONE
                      production file: agents/cognition/__init__.py — and no
                      production module imports any name from them.
```

### Why this is the sweep's sharpest instance, not just another one

**The four modules are imported by `agents/cognition/__init__.py` (`:34-37`)** — which
`brain_got.py:14` and `got.py:15` both trigger, because `from agents.cognition import …`
executes the package `__init__` first.

So `ledger.py`, `state.py`, `memory_promotion.py` and `contradictions.py` **execute on
every run of the product**, their classes are constructed by nothing, and every symbol they
export is consumed by nothing outside `agents/cognition/`.

This is the *package-facade re-export* form — one of the eleven hidden-reference forms
this sweep has catalogued — but in a variant worth isolating: **the facade guarantees the
module is imported, so every "is this wired up?" check that asks about files passes, while
every check that asks about symbols fails.** The module looks alive because it loads. It is
not alive because anything calls it.

**And it is fully tested.** Five test modules exercise it; the suite is green; `graph.py`
and `ledger.py` even have observability tests (`test_cognition_observability.py`). This is
the *"presence of tests implies a function"* heuristic in its purest form — **the coverage
is real, the assertions are real, and none of it runs in the product.** `11y`'s AR-01,
`11s`'s AL-01 and `11Q`'s name-collision bug were all instances of the same lesson; this is
the instance where the sweep's own methodology would have produced a false negative, and the
only reason it did not is that the narrow scan flagged the *members* before the island was
considered.

**`CognitionRecord.validate` (`:467-489`, 23 lines) is the reason this is high rather than
low.** It is a genuine contract validator — it checks that supported claims carry
`evidence_ids`, that completed actions carry execution proof, that verified outcomes carry
evidence, and that execution/approval ids match their action intent. That is precisely the
"no claim advances without evidence" invariant the rest of this sweep has been chasing. It
is correct, it is documented, it is tested, and **no production path calls it.**

---

## BG-02 — one rule, four expressions, two strictnesses

The invariant *"an artifact may only influence the next stage if it is supported **and**
carries evidence"* appears four times in this file, in two incompatible shapes:

**Live — `SupportMeasure.action_eligible` (`:141-149`), four conditions:**

```python
return (
    self.recommendation == "supported"
    and self.contradiction == 0.0
    and self.unresolved_dependencies == 0
    and bool(self.evidence_ids)
)
```

**Dead — three predicates, two conditions each:**

```python
Claim.can_support_action()    (374)  self.status == ClaimStatus.SUPPORTED and bool(self.evidence_ids)
Outcome.can_update_learning()  (431)  self.state == OutcomeState.VERIFIED and bool(self.evidence_ids)
Lesson.can_be_promoted()      (441)  self.verified and bool(self.source_outcome_ids)
```

**And a fifth time — as validation *errors*, not a gate (`:477-486`):**

```python
477   for claim in self.claims:
478       if claim.status == ClaimStatus.SUPPORTED and not claim.evidence_ids:
479           errors.append("supported claims require evidence_ids")
484   if self.outcome and self.outcome.state == OutcomeState.VERIFIED:
485       if not self.outcome.evidence_ids:
486           errors.append("verified outcome requires evidence_ids")
```

**The problem is not duplication — it is which one is strictest.** The live gate requires
**no contradiction and no unresolved dependencies** on top of support and evidence. The
dead predicates check **neither**. So:

> If the `CognitionRecord` cluster were wired tomorrow, `can_support_action` would admit
> claims that `action_eligible` rejects — a claim with a live contradiction and dangling
> dependencies would pass the record-level gate and fail the graph-level one. **Two gates,
> one question, and the newly-wired one is the permissive one.**

That is `11z`'s ARCH-ENG-211 shape — *"the hardened path was strictly more permissive than
the path it replaced"* — except that here **neither path replaced the other.** They coexist,
which is why the laxness has never been observed: there is no moment at which the
replacement happened and the regression could have been caught.

`can_update_learning` is the instructive one. It **is** called — by
`memory_promotion.py:31`. The narrow scan flagged it dead because that call site's receiver
type is unannotated. It is dead **by transitivity**: its only caller is inside an island
whose own only consumer is a test.

---

## Verified as sound

**`measure_support` (`:228-297`, 70 lines) is the best piece of reasoning in this file.** Its
docstring states the propagation rule *and* why the rule is that way:

> *"Supporting nodes propagate their strongest score **without compounding it**;
> contradictions subtract their source score. This keeps graph propagation useful while
> ensuring **evidence-backed support remains necessary**."*

The cycle guard is explicit — `if node_id in seen: return SupportMeasure(node_id, 0.0, 0.0,
1.0, 1, [])` (`:245-246`) — returning a *degenerate* measure rather than recursing, and the
default `recommendation` is `"insufficient_support"` (`:139`), so an unmeasured node cannot
read as supported.

**`SupportMeasure`'s class docstring is `:131`: *"Deterministic support summary; it is
advisory and never grants authority."*** That single line is the module's entire thesis, and
`action_eligible`'s own docstring keeps it: *"whether the graph is sufficiently supported
to **recommend a gate check**"* — not to take an action. **The gate recommends; the
dispatcher decides.** `brain_got.py:32` restates it: *"so narration never becomes
verification."*

**`rank_options:315-316` raises rather than skipping on a wrong node kind** —
`if node is None or node.kind != ThoughtNodeKind.OPTION: raise ValueError(...)`. A ranking
function that silently dropped a mis-typed node would produce a plausible list containing
fewer options, which is exactly the `11w` `_stated_usd` failure mode. Raising is the
correct choice for an *ordering* function whose output size is meaningful.

**`rank_options:318-327` sorts on a four-key tuple, most-discriminating first** —
`(action_eligible, recommendation == "supported", contradiction == 0.0, direct + propagated)`,
`reverse=True`. Tuple ordering gives lexicographic precedence, so the boolean gates dominate
the numeric tiebreak. Ranking by raw support first and filtering afterwards would have
been the natural mistake; this gets the precedence right.

**`ThoughtGraph.validate:329-333` walks edges against nodes and accumulates errors rather
than raising** — the right shape for a validator whose result is a report.

**Every dataclass in the file is `@dataclass(frozen=True)`** except `CognitionRecord`, which
is the mutable aggregate holding them. The records cannot be edited after construction, so
a claim's evidence list cannot be mutated into agreement with a later verdict.

---

## Re-verification

**`11P` / ARCH-ENG-212, extended.** `economic_accounting` refuses to count an amount without
VERIFIED evidence. `action_eligible` refuses to recommend a gate check without
`evidence_ids`, a supported recommendation, zero contradiction and zero unresolved
dependencies. **Both are the same refusal, expressed once each, and both are live.** This is
the second place in the repository where the evidence discipline is *enforced* rather than
documented — and the first where it also refuses on *contradiction* rather than only on
absence.

**`11J` / ARCH-ENG-158, consistent in spirit, opposite in mechanism.** The executor fails
closed on a per-outcome basis. The graph fails closed on a per-node basis. `rank_options`
raises on a malformed input rather than returning a short list.

**`11M` / BD-01 and BG-03 are the same gap seen from two ends.** `measure_all` is the
"measure every node for diagnostics and UI summaries" entry point and has no caller — while
`11M` found the Insights tab's panels inert. **If those panels are ever wired, `measure_all`
is the obvious missing last hop**, and unlike `BD-01`'s emitters it already exists, works,
and has no data-source problem.

**`11Q`'s scan correction is vindicated here.** The name-based scanner reported
`Outcome.can_update_learning` dead, with a `[name-only refs elsewhere]` flag. The reference
*was* real — `memory_promotion.py:31` — and it was still dead, because the caller is in an
island. **A flag that says "this may be reachable" and a verdict that says "it is reachable"
are different claims, and only the second one is dangerous.**

**`11F`'s "empty by design" is not this.** `AX-01` restated that the outcome tables are
empty because ARCH-ENG-158 fails closed. Here the tables are irrelevant: the record cluster
has no writer at all. **Do not wire it to fill a table** — the fix-ordering rule the sweep
has now stated four times applies with full force.

---

## Assessment

BG-01 is the most consequential structural finding since `11G`'s write-only workshop,
because it is better camouflaged. The workshop at least looked abandoned. This looks
*architected*: 11 typed classes, a 23-line contract validator, an observability test module,
a coherent package with 14 modules and a clean `__all__`.

**The camouflage is structural rather than accidental.** `agents/cognition/__init__.py`
does the right thing as a package — it re-exports the public surface — and that correct
behaviour is precisely what makes the island invisible to any file-level check. **A facade
that works correctly will always defeat a check that asks about files.**

The correct disposition is almost certainly **deletion of the `CognitionRecord` cluster
plus `ledger.py`/`state.py`/`memory_promotion.py`/`contradictions.py`** — roughly 315 lines
and six test modules — rather than wiring. But the recommendation that follows from
BG-02's sequencing rule is not "delete":

> **If it is deleted, BG-02 disappears with it. If it is wired, BG-02 becomes a live
> disagreement between two gates where the newly-wired one is the more permissive.**
>
> Either way, **BG-02 must be resolved before any decision to wire**, because it is the only
> finding in this file that has two possible bad outcomes rather than one.

There is a third option worth naming, because it is the one this codebase has taken before:
keep the cluster as a **schema**, delete its behaviour, and make `CognitionRecord` a
passive record that `measure_support` populates. That would preserve `validate()` as a
contract assertion on construction — which is exactly where `11H`'s `safety_tools_tab` puts
its check — without creating a second gate. **That is the only disposition in which BG-02
does not need fixing first.**

---

## Method note — scanner calibration

This pass used the new receiver-resolving reachability tool rather than the per-file text
scan, and **the tool reported `ThoughtGraph` and all 22 members dead.** That was wrong:
`big_brain.py:154` and `small_brain.py:137` lazily `from agents.brains.brain_got import
start_brain_turn`, and the tool does not model an import inside a function body.

Calibration against eight files with hand-verified answers:

| file | tool | expected |
|---|---:|---:|
| `gui/tabs/dialogue_tab.py` | 4/94 | 4/94 ✓ |
| `gui/widgets/dual_brain_control.py` | 0/105 | 0/105 ✓ |
| `agents/safety/approval.py` | 1/29 | 0 |
| `agents/earning/executor.py` | 3/22 | 0 |
| `agents/providers/huggingface_models.py` | 3/33 | 0 |
| `agents/core/comms.py` | 9/34 | 11 (under by 2) |
| `agents/knowledge/workshop.py` | 31/52 | 23 |
| `agents/safety/guard.py` | 21/43 | 7 |

**Six of eight are over-inclusive, two match, one under-counts by two.** That is the safe
direction for a candidate generator, and every finding above was hand-verified before being
recorded — which is why the tool's false positive on this very file was caught. **The
twelfth hidden-reference form is "an import inside a function body"; the sweep has now
defeated reachability analysis twelve times, and the correct operational response is
unchanged: a scan is a first pass, never a verdict.**