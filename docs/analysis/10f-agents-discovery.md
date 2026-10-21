# 10f — `agents/discovery/`

> **F-01 RESOLVED in v2.1.125 (ARCH-ENG-282).** `DiscoveryScheduler.tick()` now
> returns the opportunities it found, not only counts. `run_discovery_cycle()`
> dedupes them, persists/adapts them through
> `EarningDiscoveryService.remember_and_adapt()`, and hands legacy rows to
> `run_full_cycle()`/`run_autonomous_loop()`; the explicit `discover()` scan is
> only the no-due-task fallback. `moltbook` is in the default source list.
> **F-02 is also resolved by 282**: the scheduler tick is live, and
> `_profitable_categories()` calls `compute_all_metrics()` from it, so the
> docstring's "on every tick" claim is now true rather than stale.

8 scripts, 1,590 lines. The pluggable discovery engine, its application-facing
port, and the history-driven scheduler.

---

## Structure and reachability

| File | Lines | Reached from |
|---|---:|---|
| `__init__.py` | 1 | — |
| `discovery_port.py` | 58 | `agents/earning/discovery.py:46` |
| `discovery_engine.py` | 112 | `discovery_port.py:11` |
| `web_discovery.py` | 176 | `discovery_sources.py:468` |
| `scrape_resilience.py` | 179 | `integrations/fiverr.py:93`, `integrations/web.py:131` |
| `discovery_strategies.py` | 203 | `earning_pipeline.py:156`, `discovery_scheduler.py:96` |
| `discovery_scheduler.py` | 388 | `earning_pipeline.py:157` — **constructed live, selection path dead** |
| `discovery_sources.py` | 473 | `discovery_port.py` |

**No orphans.** Every module has a production consumer, confirmed exhaustively by
every occurrence of every module and symbol name. An import-pattern grep reported
`discovery_engine` and `web_discovery` as having zero outside importers; both are
false negatives — the engine is used by its sibling port, and `WebDiscoverySource`
is instantiated inside `discovery_sources.py:468`.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| F-01 | **high** | **The `DiscoveryScheduler` accumulates state that nothing ever reads.** The scheduler's write side is live and runs on every discovery — `discover()` calls `record_outcome()` at `:318` and `:322` and `mark_searched(cat)` at `:327` (the ARCH-ENG-224 fix). Its read side never runs. `select_tasks()` (`:161`) is reachable only through `tick()` (`:371`), and `tick()` is called from exactly one place: `run_discovery_cycle` (`:332-375`), which has **zero production callers**. The live path is `main.py:337` and `agents/autonomy/cli.py:51` → `run_full_cycle()` (`:1300-1335`), which calls `_log, discover, evaluate, filter, execute` and never touches `run_discovery_cycle`. Discovery therefore runs against a caller-supplied fixed `sources` list, while per-source quality scores and category-searched state accumulate correctly and are read by nothing. This is the recurring defect class — *mechanism correct, wired at one end only* — and it is a defect **in the ARCH-ENG-224 remediation itself**: that change re-enabled the *recording* of per-source attribution, but nothing consumes the recording, because the consumer sits behind a method nobody calls. |
| F-02 | med | **A docstring now asserts something demonstrably false.** `app/earning_memory.py:1952` states *"`DiscoveryScheduler` calls this on every tick to decide where to search next, so this was on the discovery hot path, not an occasional report."* The tick never runs, so that justification is wrong. The **ARCH-ENG-229 fix itself is not wasted** — `compute_opportunity_metrics` is genuinely live via `app/earning_learning_loop.py:212`, and `LearningLoop` is genuinely constructed in production at `earning_pipeline.py:139` — so the N+1 collapse stands on the learning-loop path. Only the recorded *reason* for it was false, which is worth correcting because the next reader will trust it. `discovery_scheduler.py:21` has the same shape, describing the LLM-backed `SearchStrategyGenerator` as the live design when its only consumer is `tick()`. |
| F-03 | info | **`MRBOT_ENABLE_CRYPTO=true` in `.env:341`.** Recorded here because it was found while checking gating, not because it belongs to this directory: it makes D-01 (`10d-agents-core.md`) concrete. The operator has the "Enable crypto operations" toggle switched on, and no crypto behaviour changes as a result. |
| F-04 | info | **`ALLOW_WEB_DISCOVERY=True` in `.env:358`**, so `WebDiscoverySource` is active on this machine. The opt-in is working as designed; this is an inventory note, not a defect. The path is the ARCH-ENG-213 SSRF-guarded one, and the checkbox that controls it lives at `tab_feature_builders.py:2493`. |
| F-05 | low | **The "boundary" is a convention, not a boundary.** `discovery_port.py` is described as the *"Application-facing discovery boundary"* but defines no `Protocol` or ABC — `DiscoveryPort` as an identifier has zero references in the entire repository. Only `BuiltinDiscoveryService` exists, and nothing prevents `earning/discovery.py` from importing `discovery_engine` directly if someone chooses to. Cheap to tighten, low value today with one implementation. |

---

## Verified as sound

**`WebDiscoverySource` is registered but disabled by default, with the reasoning
written down.** `discovery_sources.py:463-466` states the change explicitly: the
source is registered *"but DISABLED by default (gated behind the
ALLOW_WEB_DISCOVERY human-review flag), so the genuinely-dynamic web search path
is now WIRED (the scheduler's 'web' tasks finally execute) without changing
default behavior until an operator opts in."* The comment at `:472` repeats it.
This is fail-closed wiring done honestly — it notes that the scheduler's tasks
*finally execute*, which is only true because of F-01's dead `tick()`.

**`scrape_resilience.py` raises rather than invents.** On exhausted retries it
raises `RateLimitedError` (`:157`, `:166`) and `CaptchaBlockedError` (`:154`)
instead of returning a plausible-looking empty result. That is the same discipline
as `discoverer.py:344` — *"Returns [] so the system does not fake findings"* —
applied one layer down.

**`discovery_port.py` is a thin, correct adapter** (58 lines, one class). It is
the right size for a port that currently has a single implementation.

---

## Assessment

This directory is the best-connected one in the project: every module has a live
consumer, the gating is documented where it is applied, and the resilience layer
refuses to fabricate results. There are no orphans to triage.

F-01 is the finding that matters, and its significance is larger than its
file count suggests. `DiscoveryScheduler` is 388 lines of history-driven source
selection — exploration/exploitation, bandit-style per-source quality scoring,
category-level search tracking — and the module docstring presents it as *"the
single place that decides where to search next."* It does not, and has not since
the refactor. What ships instead is `run_full_cycle`, which searches whatever
source list the GUI or CLI hands it.

The uncomfortable part is the provenance. ARCH-ENG-224's CHANGELOG entry says the
change *"retained discovery stats + fed them to `DiscoveryScheduler`"* — which is
true, and which reads at the time like closing a loop. It closed the write half.
Because the write half is the half that is *observable* (the data appears, the
scores move, the tests pass), the gap did not surface. This is the sharpest
instance so far of the pattern this sweep keeps finding, and it is worth carrying
forward as a review rule: **when reconnecting a feedback loop, verify the
consumer of the data as carefully as the producer.**

F-02 is the same failure in prose — a justification written while the code was
believed live, never revisited. It is cheap to fix and misleading not to.