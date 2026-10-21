# 11m — `app/database.py` depth pass (733 lines, 39 methods)

> **AF-02 + AF-03 RESOLVED in v2.1.125 (ARCH-ENG-271/272).** The file cache had
> no caller, so `file_cache` was permanently empty while DB Stats and the Clear
> button treated it as live; `WorkerFilesystemMixin._cached_read` now serves the
> root and research-folder scans and `read_specific_files` with mtime
> validation, degrading to a direct read on any cache error. `research_all` also
> writes `save_research_cache` and publishes
> `update_research_snapshot(...)`, so the snapshot reader finally has a
> producer; `force_research_rescan` runs the scan and falls back to the last
> good snapshot.
>

> **AF-01 RESOLVED in v2.1.125 (ARCH-ENG-249) — wired, and the finding was
> understated.** This pass said the write path was live and only the dedup
> guard was unreachable. Verification found `add_proposal` had **zero
> callers anywhere** (main, app, agents, gui, tests) — and neither did
> `get_proposals`. The `proposals` table was never written, while
> `count_proposals()` is read LIVE by DB Stats (main.py:2088): the operator
> was shown a proposal count that was structurally always zero.
> Operator disposition: wire `add_proposal` + `proposal_exists` at the
> submission path. `agents/earning/proposal.py` now takes an optional
> `persist_proposal_fn`; the pipeline passes `_persist_submitted_proposal`,
> which writes one row per title+platform (`status="submitted"`) only after
> the platform accepted the proposal, and can never raise — a persistence
> error must not un-submit an accepted proposal. The fix also deleted 121
> lines of unreachable code that sat after
> `EarningPipeline.submit_gig_proposal`'s service-delegation `return`: a
> second, silently stale copy of the very flow being wired. Pinned by
> `tests/engineering/test_arch_eng_249_proposal_dedup.py` (double
> submission → one row; declined/review-blocked → none; pre-existing row
> dedups; unwritable DB is non-fatal; AST check that the delegation is the
> whole body). **AF-02, AF-03 and AF-04 remain as recorded.**

Depth-pass #13 of 83. **29 of 39 live — 10 dead, 26%.** The highest dead ratio since
the earning-memory layers, and the first file in the depth pass where the dead code
sits in a *persistence* layer rather than a domain one.

`AgentDB` owns 14 tables: `thoughts`, `llm_calls`, `prompt_memory`, `events`,
`research_cache`, `actions`, `decisions`, `file_cache`, `settings`, `proposals`,
`instruction_quarantine`, `instruction_allowlist`, `instruction_blacklist`, `evidence`.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AF-01 | med | **`proposal_exists` (`:421`, 24 lines) is dead — the proposal-dedup guard.** Its own docstring names the defect it was written for: *"Used to avoid re-saving duplicate drafts every heartbeat (the job queue re-discovers the same Fiverr/Upwork gigs each cycle, and **the old save path blindly inserted a new row each time**)."* The check is an indexed two-column lookup with a title-only fallback, and nothing calls it. So a heartbeat that re-discovers a gig the queue has already drafted for will insert another `proposals` row. Bounded in severity — this concerns **duplicate drafts, not duplicate submissions**; the submission side is protected independently (the approval queue logs *"[Approval] Ignored duplicate decision for approval"* at `main.py:1061`, and the submission ramp tracks acceptance separately). The growth is unbounded over time rather than harmful per-row. |
| AF-02 | low | **The file cache is entirely dead.** `get_cached_file` (`:224`, 17 lines) and `save_file_to_cache` (`:242`, 9 lines) — 26 lines over the `file_cache` table, with no callers. |
| AF-03 | low | **The research-cache trio is dead.** `save_research_cache` (`:525`, 16 lines), `load_latest_research_cache` (`:542`, 12 lines) and `_get_llm_stats_basic` (`:306`, 16 lines) — 44 lines over `research_cache`. The `_basic` suffix suggests it is the uncached counterpart to ARCH-ENG-221's cached `get_llm_stats`, so its death means all stats traffic goes through the TTL cache. That is the intended state, not a loss. |
| AF-04 | info | **Three small accessors dead:** `get_thoughts` (`:269`, 12 lines, over the `thoughts` table), `get_recent_actions` (`:573`, 6 lines, over `actions`), and `__enter__` (`:597`, 2 lines — the context-manager entry, so `AgentDB` does not support `with`). |

---

## A precision on U-01

`AgentDB` owns `instruction_quarantine`, `instruction_allowlist` and
`instruction_blacklist`. So the **quarantine persistence layer is sound** — rows are
stored, listed by `gate.pending(...)`, and the allow/blacklist outcomes persist.

That sharpens U-01's fix: the missing piece is only the *presentation* layer.
Wiring `MainWindow.review_list` (which `11a` found never assigned) would have real data
behind it, because `InstructionGate` is already constructed against this DB at
`main.py:483` and `gate.pending(...)` already returns the queue. **The empty review
queue is not an empty database** — it is an unwired view over a populated one. That is
a materially easier fix than U-01's original framing implied, and worth recording
alongside it.

---

## Verified as sound

**`proposal_exists` fails in the safe direction** (`:442-443`): *"On any DB hiccup,
treat as 'not present' so we don't silently drop a draft — better to save a possible
duplicate than lose one."* A dedup check should fail toward keeping data. The design
is right; it is simply unreachable, which is why the choice never gets exercised.

**The quarantine schema is three tables, not one** — `instruction_quarantine` (`:126`),
`instruction_allowlist` (`:136`), `instruction_blacklist` (`:142`). That matches
`handlers.py`'s `_review_selected` design, which persists `url + content_hash` into a
`related` string *"so it is ALWAYS ignored"* — a blacklist that survives even if the
listing URL changes. The schema supports the stated intent.

---

## Re-verification

**`10i`'s evidence-store claim confirmed at the storage layer.**
`EvidenceStore(AgentDB(...))` (`app/earning_pipeline.py:135`) is backed by the
`evidence` table at `:157`. The evidence chain that `10i`, `10h` and `11f` traced is
persisted here, and this pass finds no dead methods in the evidence path — the 10 dead
methods are all in the cache and query layer.

**ARCH-ENG-156 / U-01 unaffected.** The DB-isolation work concerns
`dual_brain.db` via `program_knowledge`, not `AgentDB`, and remains as recorded.

**AF-01 does not contradict `11c`.** The proposal write path in `earning_pipeline.py`
is live; only this dedup *check* is unreachable. So drafts are written and the guard
against re-writing them is not consulted.

---

## Assessment

29 of 39 live, with 10 dead methods concentrated in exactly the places a persistence
layer accumulates: caches and convenience queries. That distribution is itself the
explanation — caches are added when a caller needs one, and the caller is eventually
rewritten, leaving the cache behind. AF-03's `_get_llm_stats_basic` is the clearest
example: ARCH-ENG-221 introduced a TTL cache in front of it and the uncached path was
never removed, which is a *correct* outcome with vestigial residue.

AF-01 is the one with a live consequence. It is also a clean example of a dead method
whose docstring is more informative than its absence suggests — the comment describes a
defect that was fixed once and can recur silently now.

The U-01 precision is the more useful output of this pass. `AgentDB` holds the
quarantine, allowlist and blacklist tables; `InstructionGate` reads them; `gate.pending()`
returns them. The review UI in `main.py` is the only missing piece, and it is missing
because a widget was never created — not because data is absent. **That converts U-01
from "a capability gap" to "a wiring gap with data behind it"**, which is a much smaller
and more tractable fix.