# 10i — `agents/evidence/`

> **H-01 RESOLVED in v2.1.125 (ARCH-ENG-299).** `QualityController` is no longer
> demo-only: `TaskWorkspace.submit()` runs its deterministic
> `pre_submit_check()` over the actual deliverables before promoting the
> workspace to `submitted`. A failed or unreadable check blocks submission and
> returns the quality detail.

8 scripts, 1,620 lines. The evidence vocabulary the entire financial-integrity
argument rests on — worth examining precisely because so much rests on it.

---

## Structure and reachability

| File | Lines | Reached from |
|---|---:|---|
| `__init__.py` | 1 | — |
| `numeric_evidence.py` | 90 | `agents/cognition/dialogue_honesty.py:23` |
| `evidence_store.py` | 153 | `app/earning_pipeline.py:135` |
| `provenance.py` | 169 | `agents/services/autonomous_loop.py` |
| `evidence_factory.py` | 162 | `airdrop_claimer`, `opportunity_lifecycle`, `proposal`, `earning_pipeline` |
| `evidence_policy.py` | 207 | `executor.py`, `opportunity_lifecycle.py` ×3 |
| `document_scanner.py` | 407 | `agents/safety/workspace.py:164` |
| `evidence.py` | 431 | 12 modules — the shared vocabulary |

**No orphans.** The package is genuinely load-bearing: `EvidenceStore` is
constructed on AgentDB's evidence table at `earning_pipeline.py:135` and
**written** from `opportunity_lifecycle.py:331/403/495`, `airdrop_claimer.py:196`
and `autonomous_loop.py:855/958/1065`, then read back by `economic_accounting`,
`ranking.py:29` and `composition_root.py:137`. That the store's table
(`outcome_evidence`) holds 0 rows is consistent with the picture from `10h` —
nothing has ever been paid — rather than evidence of a broken write path.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| H-01 | med | **The pre-submission quality gate is demo-only.** `QualityController` (`:316-384`, ~68 lines) is documented as *"Controls quality gates before work submission"* and provides `pre_submit_check`, `double_check` and `_check_consistency`. Its **only** construction in the entire repository is at `:404`, inside `if __name__ == "__main__":` (`:387`) — a demo block that writes a sample file and prints analysis. So none of those three methods ever runs in the application. In a codebase whose organising principle is *verify before claiming*, the gate in front of submission is the one piece of that apparatus that was never wired. |
| H-02 | low | **The demo block uses a POSIX path in a Windows-only codebase.** `:392` writes `"/tmp/sample_test.txt"`, which resolves to `D:\tmp\sample_test.txt`. Harmless as far as it goes — it is demo code — but it is demo code that ships inside a protected, live module, and it suggests the demo was written on a different platform than the one it now runs on. |
| H-03 | low | **`document_scanner.py` reports through `print()`, not the event log.** Ten `print()` calls, at least three of them in `DocumentScanner` error paths (`:138`, `:165`, `:168`) rather than in the demo. `agents/core/event_logger.py` provides a structured logger and this module is in `PROTECTED_SOURCE_FILES`, so its output cannot be made to reach the operator's log without editing it. |
| H-04 | info | **`document_scanner.py` looks orphaned at one reference and is not.** Its only reference outside the package is `workspace.py:13`, which reads like a bare docstring mention. It is in fact called at `workspace.py:164` — `scanner.verify_completion(...)` — inside `Workspace.verify()`, which the submission path uses. Recorded because the appearance and the reality differ sharply, and "one reference" would have been the wrong conclusion from a single grep shape. |

---

## Verified as sound

**The trust ladder is well-formed and monotonic.** `VerificationLevel` defines
L0_UNOBSERVED, L1_SELF_REPORTED, L2_LOCAL_VALIDATION, L3_EXTERNAL_SOURCE,
L4_INDEPENDENT_VERIFICATION, L5_CRYPTOGRAPHIC — *"Higher = stronger external
proof."* The naming makes the L1/L3 distinction explicit, which is exactly the
distinction ARCH-ENG-043 relies on to stop an operator-typed reference from
advancing the win-rate. Having `L3_EXTERNAL_SOURCE` as a named rung rather than a
magic number is what makes that check readable.

**`EvidenceStatus` includes `CONFLICTED` as a first-class state** alongside
`UNVERIFIED`, `PARTIALLY_VERIFIED`, `VERIFIED`, `REJECTED` and `EXPIRED`.
Contradicting evidence is modelled as its own outcome rather than being resolved
silently by last-write-wins — the correct shape for a store that later decides
whether money may be booked.

**`EvidenceStore` is genuinely written to, not just constructed.** This is worth
stating because `10h` found so much in this area that was *not* wired, and the
natural inference would be to assume the same here. It is not. Four independent
production writers, a real DB-backed store, and three production readers.

**`numeric_evidence.py` is live and load-bearing for the honesty stack** via
`agents/cognition/dialogue_honesty.py:23` (`has_unsupported_values`), which is
the same subsystem assessed in `10c`. The function name states the property being
enforced: a monetary figure in a response that appears nowhere in the supplied
context is *unsupported*.

---

## Assessment

`agents/evidence/` is the subsystem I expected to find hollow after `10h`, and it
is not. The vocabulary is coherent, the trust ladder is explicit, `CONFLICTED` is
modelled rather than papered over, and the store has four real production writers
and three real readers. This is load-bearing infrastructure and it holds.

H-01 is the finding, and its significance is in the contrast. The system has an
elaborate, well-designed apparatus for establishing that work is good enough to
submit — a document scanner that computes readability, completeness and risk, and
a quality controller with a pre-submit check, a double check and a consistency
check. `Workspace.verify()` calls the scanner. **Nothing calls the quality
controller.** The scanner is wired and the gate that consumes its output is a
demo.

That is the same shape as `DiscoveryScheduler.tick()` (F-01) and the
ARCH-ENG-159 caller-only defence: a mechanism that is correct, present, and
sits at one end of the wire. It is the third instance in this sweep of a
verification step that exists and is not enforced, and the reason it has gone
unnoticed is the same each time — the code that implements it is tested or
demonstrated, so it looks exercised.

Worth noting for whoever decides the fix list: H-01 is the cheapest of the three
to close, because `Workspace.verify()` already returns the scanner's output and
the quality controller has a well-defined input signature. It needs a caller, not
new code.