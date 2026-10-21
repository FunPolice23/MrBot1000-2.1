# 10c — `agents/cognition/`

15 scripts, 3,097 lines. The epistemic / honesty layer.

---

## Structure

| File | Lines | Role | Consumed by |
|---|---:|---|---|
| `state.py` | 22 | canonical state facade | **nothing** |
| `ledger.py` | 65 | durable ledger via EventBus | only `state.py` |
| `memory_promotion.py` | 54 | promotion gate to durable memory | **nothing** |
| `contradictions.py` | 64 | first-class contradiction cases | **nothing** |
| `epistemic.py` | 114 | deterministic confidence classes | `dialogue_honesty` |
| `__init__.py` | 96 | re-exports | — |
| `operator_override.py` | 199 | human authority over model claims | `dialogue_honesty:102` |
| `dialogue.py` | 147 | natural dialogue records | `dialogue_tab.py:39` |
| `dialogue_honesty.py` | 266 | **honesty enforcement** | `dialogue_tab.py:305` |
| `speaker_registry.py` | 267 | N-brain speaker roster | `dialogue_tab.py` (4 sites) |
| `fact_ledger.py` | 370 | append-only claim register | `dialogue_honesty:21` |
| `reasoning_modes.py` | 238 | reasoning-mode policy | `brains/brain_got.py:22` |
| `personas.py` | 346 | persona identities | `big_brain`, `small_brain`, `chat_tab` |
| `coordinator.py` | 326 | cross-model collaboration | `tab_feature_builders.py:235` |
| `graph.py` | 523 | typed cognition artifacts | `brains/brain_got.py:21` |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| C-01 | med | **Four components have no consumer at all — not the app, not the GUI, not their own siblings.** `open_contradiction` / `ContradictionCase` (`contradictions.py`, 64 lines), `MemoryPromotionPolicy` (`memory_promotion.py`, 54), and `CanonicalCognitionState` (`state.py`, 22) have **zero** references outside their own module and `cognition/__init__.py`. `CognitionLedger` (65 lines) is referenced by exactly one line — `state.py:8` imports it — so it is kept alive only by a class nothing uses. **205 lines forming a two-link chain whose head is unreachable.** Each is re-exported from `cognition/__init__.py`, so the package presents them as available capability. |
| C-02 | low | **The lazy export surface in `agents/__init__.py` has no production consumers.** `from agents import X` has **zero** production call sites; every one of the 22 names is reached instead by direct submodule import. The surface is not broken — all 22 resolve (verified in area 10) — it is simply unused as a surface. This is *not* the same as C-01: `FactLedger`, `OperatorOverrideRegistry` and the epistemic stack are genuinely live through `DialogueHonestyService`. Only the import path is unused. Mitigated by the comment in `agents/__init__.py` calling it a "v2.1.1 experimental integration surface", which is honest about the status. |
| C-03 | low | **Five docstrings name files at paths that do not exist.** `coordinator.py` claims `agents/dual_brain_coordinator.py`, `dialogue_honesty.py` claims `agents/dialogue_honesty.py`, `epistemic.py` claims `agents/epistemic_calibration.py`, `operator_override.py` claims `agents/operator_override.py`, `personas.py` claims `agents/personas.py`. All five predate the move into `cognition/`. Pure documentation drift, but it is the kind that sends a reader — or an agent — looking for a file that is not there. (`fact_ledger.py` and `speaker_registry.py` were updated correctly, so this was a partial refactor.) |

---

## Verified as sound — the honesty stack is genuinely live

This is worth stating plainly because a coarse reading of C-01/C-02 would
suggest the epistemic layer is decorative. It is not.

`DialogueHonestyService` is constructed at `gui/tabs/dialogue_tab.py:305` and
exercised at four call sites:

| Site | Call |
|---|---|
| `:1460` | `apply_overrides()` — operator overrides applied to the live prompt |
| `:1462` | `epistemic_context_note(max_claims=5)` — injects a claim-state note |
| `:2036` | `record_claims(response_text)` — records claims from the response |
| `:2054` | `check_numeric_support(...)` — numeric support checking |

It is the component that wires `FactLedger` (`:21`), `OperatorOverrideRegistry`
(instantiated at `:102`) and the epistemic classifier together, and it is reached
from the GUI on every dialogue turn. **The operator-override path — human
authority over model claims — is live.** That is the most safety-relevant thing
in this directory and it is working.

`graph.py` (523 lines, the largest file here) is consumed by
`brains/brain_got.py:21` for `SupportMeasure`, and `coordinator.py` by
`tab_feature_builders.py:235`. Both live.

---

## Assessment

A strong directory with one clean seam. The honesty chain — fact ledger →
operator override → epistemic classification → prompt note — is built, wired and
running on every dialogue turn, and it is the part of this codebase that most
directly implements the operating principle stated in `run_lead_routine.py`
("do not allow an LLM response to become financial truth").

The unreferenced tail is not a safety problem; it is capability that was designed
and never connected. `contradictions.py` is the most interesting of the four:
first-class contradiction tracking is exactly the mechanism that would catch a
model asserting two incompatible things, and it has no caller. Whether to wire it
or retire it is a design decision — worth noting that `DialogueHonestyService`
already maintains a claim ledger, so contradictions would be cheap to add there
rather than needing a new integration point.

C-03 is a five-minute fix and is the kind of drift that erodes trust in
docstrings generally.