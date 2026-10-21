# 10 — `agents/autonomy/` and `agents/__init__.py`

> **A-01 RESOLVED in v2.1.125 (ARCH-ENG-280).** The learning engine's read
> side is live: `score_strategy()` plus `EarningPipeline._apply_self_improvement()`
> inside `filter()` blend platform reliability, tag success and strategy weight
> into a bounded ranking nudge, with a cold-start neutral path below
> `MIN_OUTCOMES`. The write side now reads the keys discovery actually writes
> (strategy from `provenance`, tags from category/task_type/platform), and
> `_adjust_weights()` seeds a `StrategyWeights` entry per learned strategy.
> **A-02/A-03 decided in v2.1.125.** A-02 keeps the gate: an outcome must be
> verified and carry evidence before it feeds learning. A-03 is merged rather
> than kept as a second store: `LearningLoop` is constructed with the same
> `EarningMemory` used by A-01, is fed from the live lifecycle, and its records
> are the outcomes the self-improvement read side consumes. No separate learning
> database remains.

8 scripts, 1,609 lines. The "Phase 5/6 autonomy subsystem".

---

## `agents/__init__.py` — 70 lines

**Purpose.** Lazy package-level exports. `__getattr__` resolves 22 historical
names on demand so `import agents` does not eagerly construct optional workers.

**Verification.** Checked for the drift this codebase has been bitten by twice
(ARCH-ENG-201: a blocklist defined then re-imported; ARCH-ENG-208: a duplicated
definition):

- `_EXPORTS` has 22 entries, `__all__` has 22 — the two sets are **identical**.
- Every declared `(module, symbol)` pair was **actually imported** and the symbol
  confirmed present. All 22 resolve.

**Assessment.** Clean. No findings.

---

## The subsystem

| File | Lines | Role |
|---|---:|---|
| `__init__.py` | 54 | re-exports |
| `grants.py` | 42 | `AutonomyGrant` — capability-scoped, expiring |
| `heartbeat.py` | 207 | credit monitoring, survival tiers |
| `onchain_identity.py` | 229 | agent identity / agent cards |
| `agent_registry.py` | 394 | agent specs, capability categories, delegation |
| `self_improvement.py` | 288 | outcome learning, strategy weights |
| `cli.py` | 325 | operator CLI, 12 commands |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| A-01 | **high** | **The learning engine is fed but never read — a write-only learning store.** `SelfImprovementEngine` *is* wired into the live pipeline: `app/earning_pipeline.py:145` injects `_record_strategy_outcome` as the lifecycle `outcome_callback`, and `:460` calls `engine.record_outcome(record)` for every finalized outcome, gated on verified evidence. The write side is real. The **read side has no consumers at all**: `get_strategy_weights`, `get_platform_reliability` and `get_tag_success_rate` have **zero** call sites anywhere — not in the app, not in the GUI, not even in tests. `get_recommendation` is read only by `cli.py` (`:185`, `:206`), and nothing in the application invokes `cli.py`. So every verified outcome is written, persisted, and then never consulted to change a decision. The application runs a learning engine and ignores what it learns. |
| A-02 | med | **The engine has also never received a single record.** `record_outcome` returns early unless `record.verified and record.evidence_ids` (`:122`), and `earning_pipeline.py:445` sets `verified = (outcome_state == "paid" and evidence_ids)`. `self_improvement_state.json` does not exist on disk, and `save()` is called unconditionally on an accepted record (`:134–135`) — so its absence proves no record has ever been accepted. Confirmed against the database: `earning_memory.db.outcome_memory_v2` is **empty (0 rows)** and `outcome_evidence` has **0 rows**. So A-01's read side is unreachable *and* its write side has never fired. Two independent reasons the subsystem is inert. |
| A-03 | med | **A second learning system is also inert.** `app/earning_learning_loop.py` writes through `memory.record_outcome_v2` (`:163`) into `outcome_memory_v2` — the table that is empty. ARCH-ENG-224 reconnected the *third* system (`DiscoveryScheduler.record_outcome`, which writes `strategy_memory`/`search_strategy`) and it does fire, because it is fed by discovery runs rather than by verified payments. So the codebase has **three** learning engines: one now live, one fed-but-unread (A-01), one never fed at all (A-03). Which one is authoritative is not recorded anywhere. |
| A-04 | low | **`cli.py` is runnable but never invoked.** It has an `if __name__ == "__main__":` guard (`:324`) and works as a manual operator tool — `python agents/autonomy/cli.py <cmd>`. Nothing imports it, no `python -m agents.autonomy` appears anywhere, and it is not referenced by any script or launcher. Legitimate as a manual tool; recorded because it is the *only* consumer of the engine's output, so "the data is unused" is true of the running application but not of a human who runs the CLI by hand. |

---

## Verified as sound

- **`AutonomyGrant` (`grants.py`, 42 lines) — dormant but correct, not a broken
  gate.** It is imported by `agents/safety/authorization.py` and used as the
  `grant` parameter of `authorize`/`dispatch`, but **never constructed in
  production** — only in `tests/earning/test_autonomy.py`. That is safe,
  because the check is an optional narrowing: `if grant is not None and not
  grant.allows(...)` (`authorization.py:67`). `None` is the normal path and skips
  the restriction entirely. This confirms the earlier reading rather than
  repeating it: a grant was designed to *narrow* authority that already exists,
  never to grant it, so its absence removes no protection.
- **`authorization.py` documents and enforces the ARCH-ENG-165 fix properly.**
  `approved=True` used to be a bare boolean that upgraded NEEDS_APPROVAL to
  ALLOWED on the caller's word alone. There are now two distinct paths —
  `approval_id` given means VERIFIED against the shared queue via
  `assert_approval_covers`, and `approval_id` absent means caller-asserted, with
  the reason string saying so plainly so it cannot be mistaken for the verified
  path. A refusal does **not** upgrade the decision; the original
  NEEDS_APPROVAL stands and the caller re-enqueues, so the operator still sees
  the pending request.

---

## Assessment

The subsystem is competently built and thoroughly documented, and its own
docstrings state its purpose accurately. The problem is not quality — it is that
`self_improvement.py` is wired at exactly one end.

**A-01 is the one to act on.** It is the same class as every other finding in
this sweep: correct mechanism, correctly gated, reachable from nowhere. Unlike
the others it is not harmless — the application is doing verified-outcome
learning work and then discarding the result, so an operator reading
`get_recommendation` would reasonably believe their outcomes are influencing
future scans. They are not.

Fixing A-01 means deciding where `get_strategy_weights` /
`get_platform_reliability` should be *read*. The obvious consumer is
`EarningPipeline`'s discovery path, which currently scores sources using the
`DiscoveryScheduler`'s own table rather than the engine it already maintains.
That is a design decision, not a mechanical fix, and is recorded for the
fix phase rather than decided here.

A-02 and A-03 are partly operational rather than code defects: the bot has never
recorded a verified payment, so several learning paths have no data to work
from. A-03's emptiness is worth confirming before any conclusion is drawn.