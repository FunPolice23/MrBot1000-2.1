# 10g — `agents/earning/` (part 1: structure and reachability)

> **G-01 RESOLVED in v2.1.125 (ARCH-ENG-300).** The dead
> `EarningCapabilityExecutor` module is deleted. The CLI now runs the live
> `EarningPipeline`, and the earning tab no longer tries to import a
> non-existent `EarningCapability`.

54 scripts, 13,719 lines — the largest area in the project, and where most
earlier findings ultimately point. This first pass establishes the reachability
map for the whole directory and the payment-integrity path. Substance analysis of
the remaining files continues.

---

## Reachability map

Every module was classified by production references, counting **both** references
outside the package and intra-package ones. Two counting errors were caught and
corrected during this pass, and both are recorded below because they change
conclusions.

| Class | Modules |
|---|---|
| Live from outside `agents/earning/` | 33 |
| Live only intra-package | 12 |
| **Truly dead** | **1** (`goal_system.py`) |
| Live module, dead entry points | 3 (`spec.py`, `capability.py`, `got.py`) |

`__init__.py` re-exports **21 modules via 21 relative imports** and declares
**47 names** in `__all__`. That structure matters for reachability analysis: a
module can be reached through the package facade even with no direct importer, and
a relative import (`from .got import GraphBudget`) is invisible to a
`earning\.got`-style grep.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| G-01 | med | **`capability.py` (302 lines) is dead in production.** `EarningCapabilityExecutor` is **never constructed** in production — zero call sites. Its only production references are its own module body, the `__init__.py` re-export, and its `EarningCapabilityResult` construction at `:145`. Four test files construct it. The module docstring reads *"First real autonomous earning…"* — a strong claim attached to 302 lines of capability-execution logic that no production path reaches. |
| G-02 | med | **`goal_system.py` (526 lines) is entirely dead.** A complete goal-tracking subsystem — `GoalStatus`, `GoalPath`, `EvidenceRow`, `Goal`, `GoalTracker` — with **zero production references of any kind**, inside the package or outside it. Four test references, including `test_singleton_identity.py` and `test_singleton_identity_guard.py`, so its identity invariants are asserted but nothing observes them. This is the largest single dead module found so far. |
| G-03 | low | **The task-semantics layer in `spec.py` is inert; tasks are constructed by hand.** The module is live — `Task` is used by `big_brain.py` — but every function that would *build* a `Task` from real input is uncalled: `build_task` (`:152`, defined never called), `task_from_opportunity` (`:170`, defined never called), `set_requirement_inferrer` (`:125`, defined never called), and `infer_task_requirements` (`:131`, called only by `build_task`, which is itself dead). `TaskFeasibility` is likewise referenced only inside `spec.py` and `validator.py`. So the requirement-inference and feasibility-semantics layer exists, is tested, and never runs — callers construct `Task` literals instead. |
| G-04 | low | **`GoalTracker`'s singleton invariants are tested but unobserved.** Folded into G-02 rather than double-counted: two test modules are dedicated to asserting this singleton's identity behaviour, which implies the singleton was considered load-bearing at some point. |

---

## Counting errors caught during this pass

Both would have produced false findings, and both are the same class of mistake
this sweep keeps making — trusting one grep shape.

1. **`earning\.gas_estimator` matched nothing.** `gas_estimator.py` (61 lines)
   looked like a total orphan. It is imported at
   `agents/earning/airdrop_claimer.py:65`. It is a *transitive* orphan rather
   than a live module, but that is a different claim and needs its own evidence.
2. **Twelve of the 47 exported names showed zero consumers outside the package.**
   On inspection, **nine were false positives** — return types and annotations
   used by attribute access inside live modules, which need no import:
   `ValidationReport` (36 uses, all inside the live `validators.py`),
   `CapabilityRegistry`/`get_default_registry` (used by the live `validator.py`),
   `TaskFeasibility` (used by `validator.py`), and `GraphBudget`/
   `OpportunityGraphRank` (used inside the live `got.py`). Only the three in
   G-01/G-03 survived. **A name with no importer is not a name with no callers.**

A third pattern failed noisily: a grep whose alternation was split into
per-character searches, producing ~170,000 nonsense hits. Worth recording because
it wasted a call and could easily have been misread as a finding.

---

## Verified as sound — the payment path is the best safety design in the project

The operator-facing payout flow (`main.py:1765-1846`) is worth setting out
because it is the counter-example to most of this directory's dead code, and
because it is directly relevant to the open question of why `outcome_memory_v2`
is empty and no payment has ever been recorded.

**Verification gates the transition; the GUI does not.** `_verify_and_mark_paid`
routes through `pipe.lifecycle.mark_paid_verified(opp_id, amount, evidence=…)`
and only reports success if `state.status == "paid"` (`:1820`) — the lifecycle's
own policy decides, not the caller. Failure is explicit and fail-closed: *"Payout:
NOT verified — left as submitted (audit logged)"* (`:1845`).

**A missing verifier cannot fail open.** `_build_payout_verifier` swallows any
import error and returns `None` (`:1758-1763`), which leaves `evidence` as
`None`. That is only safe because the transition is gated downstream by the
lifecycle rather than by the presence of evidence. The broad `except` does hide
the cause, but the direction of failure is correct.

**The operator cannot inflate their own auto-submission threshold.** This is
ARCH-ENG-043, and it is the sharpest piece of reasoning in the area. After a
successful verification the code credits the submission ramp, but only if
`is_affirmative_verification(state)` holds (`:1833`), with the comment stating
why: *"'paid' alone is not proof of payment. A manual (operator-typed) reference is
L1 self-report, which must never advance the win-rate that unlocks
auto-submission."* So typing your own bank reference into the GUI marks the
opportunity paid but cannot raise the win rate that lets the system submit
unattended. Without this, the human-in-the-loop gate would be self-certifying.

**The exception handler is on the conservative branch.** `except Exception: pass`
at `:1842` wraps only the ramp bookkeeping, so a failure there means *no* ramp
credit — the safe direction.

**`PayoutVerifier` is genuinely live**, constructed at `main.py:1761` and used
for both `verify_crypto` (`:1799`, on-chain via `WalletManager`) and
`verify_manual` (`:1804`, operator reference). Its evidence object is passed
through as a real `Evidence` subclass so the lifecycle can gate on it.

---

## Assessment

`agents/earning/` is the most heavily re-exported directory in the project: a
47-name public facade over 21 modules, with the facade as the primary integration
surface. That design is coherent, and it is why the naive reachability numbers
came out wrong twice.

The dead code is real but concentrated — **828 lines** across `capability.py` and
`goal_system.py`, plus the inert half of `spec.py`. It is not a directory in
decline; it is one with a live core (33 modules reached from outside) and two
subsystems from an earlier design that were never retired.

`capability.py` and `goal_system.py` are both worth a decision rather than
deletion on principle. `goal_system.py` has tests dedicated to its singleton
identity, which is evidence it was once load-bearing; `capability.py` carries the
strongest claim in its docstring. Retiring either is a product decision, not a
cleanup.

The payment path deserves the opposite treatment from everything else found so
far in this sweep. It is the clearest example in the codebase of a safety
mechanism that was designed adversarially — anticipating an operator who would
want to shortcut it — and then implemented correctly.