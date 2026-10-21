# 11F — `app/earning_memory.py` depth pass (2281 lines, 82 methods)

> **AX-03 RESOLVED in v2.1.125 (ARCH-ENG-263).** The deterministic fallback in
> `agents/earning/evaluation.py` repeated AU-01's substring match for its six
> skill tokens. It now uses the same `\b`-anchored contract, which matters most
> here: this path runs exactly when the model evaluation failed.
>

Depth-pass #32 of 83. **16 dead of 82** — the largest dead cluster yet, and it is almost
entirely *one* finding. This pass also **corrects P-02**, in the same shape as the three
earlier corrections in this sweep: *directionally right, materially imprecise about what
wiring it would produce.*

---

## Structure

```
L    1-9    module docstring — five memory tiers
L   31-35   OUTCOME_STATES  (14 canonical lifecycle states)
L   38-40   FAILURE_CAUSES  (structured — "memory MUST store WHY")
L  151-160  MemoryEntry      L  164-191   LearningMetrics
L  194-2240 EarningMemory    (75 methods)
L 2244-2246 create_memory    L  2254     (module __main__ harness)
```

Docstring: *"Multi-tiered memory system. Tier 1: Opportunity Memory… Tier 2: Outcome
Memory… **Tier 3: Skill Memory - learns which jobs/skills are profitable**… Tier 4:
Reputation Memory… **Tier 5: Pattern Memory - learns patterns from successes/failures**."*

Largest: `_init_db` (278), `record_outcome_v2` (111), `compute_opportunity_metrics` (83),
`compute_all_metrics` (58), `_metrics_from_rows` (57), `__init__` (45).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AX-01 | **med** | **Fifteen analytics methods are dead, and every one reads a table that has never held a row.** The cluster is contiguous (`:1658`–`:1810`) plus `apply_decay` and the two search-strategy readers: `most_reliable_platforms`, `highest_net_hourly_categories`, `best_performing_task_types`, `time_wasting_categories`, `best_proposal_templates`, `platforms_poor_acceptance`, `task_types_high_completion`, `profitable_but_often_fail`, `recurring_failure_causes`, `strategies_to_avoid`, `category_outcome_summary`, `top_search_strategies`, `get_search_strategy_stats`, `apply_decay`. Their sources are `outcome_memory_v2`, `failure_memory`, `search_strategy` and `decay_log` — **all four at 0 rows**, alongside `outcome_memory`, `success_memory` and `pattern_memory`. So **Tiers 3, 4 and 5 as promised in the docstring have no data source at all**, and wiring the analytics would produce empty reports. |
| AX-02 | **med** | **P-02 corrected.** The area sweep recorded `find_similar_opportunities` as dead — *"retrieval that would make it a learning memory."* It does **not** read `opportunity_memory` (the one table with 195 rows). It calls `get_successful_patterns(...)` twice (`:2126`, `:2136`), which reads the **pattern/success** tables — both at 0 rows. **Wiring it returns `[]`.** The retrieval is not the missing piece; the *writes* are — and the write path (`remember_success`, `:1261`, 43 lines) is live and healthy. Nothing succeeds, because ARCH-ENG-158 refuses to mark PAID without independent proof of payment. |
| AX-03 | low | **AU-01's substring defect recurs.** `:2132-2133` — `skills = ["python","ai","data","code","write","review"]` then `matching_skills = [s for s in skills if s in desc]`. No word boundaries, so `"ai"` matches *maintain/email/domain/chain* and `"data"` matches *database/metadata*. This is the same defect `11B` found in `freelance_finder._extract_skills:304`, in a second file — which makes it a pattern rather than an oversight. |
| AX-04 | info | **`create_memory` (`:2244`, 3 lines) is dead.** The module's factory is unused; `app/earning_pipeline.py:125` constructs `EarningMemory(db_path=self.memory_path)` directly. Vestigial convenience. |

---

## AX-01 — the causal chain, now four links long

`11r` recorded AJ-01 (the self-audit engine is constructed and never invoked) and AJ-02 (the
tables it would read are empty). `11s` corrected AJ-02: the emptiness is **by design**, under
ARCH-ENG-158's fail-closed behaviour. This pass adds the fourth link:

```
opportunities discovered and stored      195 rows in opportunity_memory   [LIVE]
        |
        v
no payment is ever independently proven
  -> ARCH-ENG-158 fails closed             outcome_memory_v2 = 0            [BY DESIGN, 11s]
        |                                    failure_memory  = 0
        |                                    success_memory  = 0
        |                                    pattern_memory  = 0
        |                                    search_strategy = 0
        |                                    decay_log       = 0
        v
15 analytics methods that read those six tables are dead    -> AX-01
        |
        v
the self-audit engine that would have reported this is also dead      -> AJ-01, 11r
```

**The important consequence is a fix-ordering rule, and it is now the third time this sweep
has had to state it.** `AJ-02` (`11r`), `AN-03` (`11u`), `AQ-01` (`11x`) and now AX-01 all say
the same thing from different directions:

> **Wiring a reader whose tables are empty produces a live component that reports nothing.**
> That is worse than a dead one, because it converts a visible gap into an invisible
> assurance.

So AX-01 is **not** "call these fifteen methods." It is the same finding as AJ-02 seen from
the memory layer: **a learning system whose learning has never happened, with a large
analytics surface waiting to report on it the moment it does.** The analytics are not the
missing piece; they are the part that is *already built*, waiting.

---

## AX-02 — the P-02 correction

The area sweep's P-02 said the dead `find_similar_opportunities` was *"retrieval that would
make it a learning memory"* — implying the store is full and nothing reads it. The function's
body shows otherwise:

```python
2124   platform = opp.get("platform", "")
2126   patterns = self.get_successful_patterns("platform_action", 0.3)
...
2136   patterns = self.get_successful_patterns("tag_success", 0.3)
```

Both sources are the **pattern** and **success** tiers. `opportunity_memory` — the 195-row
table — is not consulted at all, because this method matches an opportunity against *learned
patterns about past successes*, not against past opportunities.

That makes P-02 the fourth correction of this exact shape, and the three previous ones are
recorded in this sweep: `W-02` (*3 of 7 flags in dead code*), the `10i` amendment
(*`CONFLICTED` modellable but not resolvable*), and `O-01` (*`propose_code_patch` IS
advertised and live*). **The pattern is consistent enough to name: a finding inferred from a
function's name and location is right about the defect and wrong about what fixing it would
produce.** P-02's value is that it found the dead method; its error is the implied remedy.

The corrected statement is stronger, not weaker: **the memory system has a complete write
path, a complete analytics path, and no data flowing between them — because the pipeline
never completes a payment, by design.** That is a single, well-understood gap with one
upstream cause, and it is the same gap `11r` AJ-02 describes.

---

## Verified as sound

**`record_outcome_v2` (111 lines) is the largest live method and it is healthy.** `11s`
recorded that `record_outcome_v2` is live with correct writes, and that the tables are empty
because no outcome completes rather than because the write path is broken. That re-verifies
here from a different file.

**The enumerations are enforced, not documented-and-hoped-for (`:22-40`):**

> *"These are the **SINGLE SOURCE OF TRUTH** for valid outcome states, failure causes, and
> success causes. Recording an unknown value is rejected (deterministic)."*

And `FAILURE_CAUSES` carries the rule that matters: *"Structured failure causes — **memory
MUST store WHY, never just 'failure'**."* A memory that records only "it failed" cannot learn
which of the fourteen causes to avoid, which is exactly what the five dead analytics methods
(`recurring_failure_causes`, `strategies_to_avoid`, `profitable_but_often_fail`) would query.
The schema and the analytics were designed together; only the data is missing.

**`OUTCOME_STATES` resolves an ambiguity in the source data rather than papering over it
(`:27-30`):**

> *"NOTE: the user's list has 'rejected' twice (once after 'applied', once after 'paid'). We
> preserve both meanings as distinct states: `rejected_apply` → proposal/application was
> rejected (pre-acceptance); `rejected_pay` → payment was rejected/disputed-rejected
> (post-acceptance)."*

Silently deduplicating a repeated value would have merged two opposite business events. This
is the same instinct as `11p`'s two `_detect_gpus` and `11w`'s two frontmatter formats:
**when two things look alike, distinguish them rather than merge them.**

**`apply_decay:606-613` takes `self._lock` around its write**, even though it opens its own
`sqlite3.connect` — the locking is deliberate for the shared-DB race that ARCH-ENG-166
addressed, and the log row records `old_value`, `new_value`, `decay_factor` and a timestamp,
so a decay is auditable rather than silent.

**`compute_all_metrics` (58) and `_metrics_from_rows` (57) are live**, and the split between
"compute everything" and "compute from rows" keeps the query layer separate from the
aggregation.

---

## Re-verification

**`11s` confirmed from a second file.** `record_outcome_v2` live + tables empty is exactly
what `11s` recorded from `executor.py`'s side; this pass sees it from the memory side. The
ARCH-ENG-158 explanation is unchanged and is now the accepted account of the empty tables.

**`11r` AJ-02 extended.** The self-audit layer (`self_audit`) and this analytics layer are
independent readers of the same six empty tables. Both are dead. Neither is the cause; both
are consequences.

**`11c` consistent.** `executor.py` transitions the portfolio and `11s` traced why `PAID` is
unreachable. `earning_memory.py` is where a completed outcome would be recorded — and no
outcome completes.

**P-02 corrected (AX-02).** The method is dead, as recorded; the remedy implied by the finding
is wrong. See above.

**`11w` / ARCH-ENG-212 consistent.** `estimated_usd_value` and the outcome records are
separate concerns; this module's discipline is *structured failure causes*, which is the same
refusal to store a bare "failure" that `_stated_usd` applies to amounts.

---

## Assessment

Sixteen dead of 82, and the honest reading is that **fourteen of them are one finding.**

A learning system with five documented tiers, a canonical state machine, structured failure
causes, a complete write path, and a complete analytics path — and **no data flowing between
them.** That is not a set of sixteen defects; it is one gap, upstream, with two large bodies
of already-built code waiting on either side of it.

The fix-ordering rule this produces is the sweep's most repeated practical conclusion, now
stated four times from four directions: **do not wire a reader whose tables are empty.**
Wiring `run_audit` (`11r`), `max_loop_depth` (`11u`), `ActionPipeline.process` (`11x`) or
these fifteen analytics would each produce a live component reporting nothing — and in three
of those four cases, reporting that *nothing is wrong*.

**AX-03 is worth fixing on its own merits and for the pattern it reveals.** The same missing
word boundary now appears in two unrelated files (`freelance_finder._extract_skills`,
`earning_memory.find_similar_opportunities`). Two instances of the same mistake is the point
at which it stops being an oversight and becomes a habit — and both are in *matching* code,
where a false `ai` skill tag is worst. If the fix list is being assembled, this one belongs
in a "sweep for `in`-on-lowercased-string" entry rather than as two separate line edits.
