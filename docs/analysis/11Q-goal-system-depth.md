# 11Q — `agents/earning/goal_system.py` depth pass (526 lines, 28 methods)

> **RESOLVED in v2.1.125 (ARCH-ENG-244).** BF-01 + BF-02 fixed by the
> operator's full-wiring disposition, in this doc's own dependency order:
> the unguarded `add_earnings` is DELETED first (a credit exists if and
> only if an evidence row is verified and its amount is positive --
> `add_evidence`'s guard is the single money decision), then the whole
> `GoalTracker` went live. `process_event` reads the REAL production
> contract (ARCH-ENG-243's typed earning event, details `revenue` /
> `platform` / `success`, action `finalized:<state>`) -- resolving the
> BF-03 seam this doc recorded: `details['amount_usd']` and the invented
> `earning.<path>` vocabulary are gone, `_auto_match_event` deleted, and an
> unbound amount can no longer be assigned by guesswork. Binding is
> explicit (`details.goal_id` / `goal:<id>` tag) or operator-declared
> (`metadata.platforms`, case-insensitive); non-paid states are recorded
> with verified=False and never move money; a "paid" event with revenue 0
> (the ledger refused it) cannot credit a cent. `main.py`'s event-logger
> hook feeds the tracker on the same guarded seam as the alert engine, and
> the Management tab's new Earning Goals card is the operator surface this
> doc said the class lacked: create with platform binding, pause/resume
> (selection-preserving rebuild), confirm-gated delete, progress table and
> summary. Tests: `tests/engineering/test_arch_eng_244_goals_wired.py` +
> `tests/earning/test_goal_system.py` rebased onto the live contract.

Depth-pass #43 of 83. **Corrected count: 22 dead of 28 — 79%, the whole `GoalTracker` class is
unreachable.** And the correction required fixing my own scan, which reported 4 dead.

---

## Structure

```
L   32-36    GoalStatus          L   97-164   Goal (5 methods)
L   39-46    GoalPath            L  167-517   GoalTracker (20 methods)
L   50-93    EvidenceRow (3)
```

Docstring: *"A Goal is a **verifiable** unit of earning work… Each goal has: target_usd: the
monetary target; **current_usd: verified earnings so far**; evidence: list of **verifiable proof
rows**…"*

Largest: `_init_db` (39), `_auto_match_event` (35), `process_event` (34), `summary` (27),
`add_evidence` (22), `create` (18), `update` (17).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| BF-01 | **med** | **The entire `GoalTracker` (20 methods, `:167-517`) is unreachable — zero external references.** A qualified search for `GoalTracker` / `goal_tracker` / `goaltracker` across all production code returns **four hits, all inside this file**: the class definition (`:167`), its own `_instance` annotation (`:173`), its own `instance()` classmethod (`:190`), and its own `__all__` entry (`:521`). `GoalTracker.instance()` has **no callers**. `Goal` and `EvidenceRow` are reachable only through it. |
| BF-02 | **med** | **The verification contract is enforced by a dead method and claimed by a live one.** `add_evidence:342-347` is the **only** place in the file that guards a credit: `if evidence.verified and evidence.amount_usd > 0:` before incrementing `current_usd`. That method is dead. The method that does the incrementing, `add_earnings:363-370`, is **live within the class** and its docstring reads *"Add **verified** earnings to a goal"* — while its body is a bare `UPDATE goals SET current_usd = current_usd + ?`. **The word "verified" appears in the docstring and nowhere in the code.** |
| BF-03 | info | **The event seam uses a key nothing writes.** `process_event:446` and `_auto_match_event:463` read `details.get('amount_usd', 0.0)`. A tree-wide search for code that puts `amount_usd` **into** an event `details` dict finds **one** site — `EvidenceRow.to_dict:74`, a dataclass serialiser, not an event emitter. Meanwhile `agents/core/event_logger.py:506`'s `earning_event` (dead, `11M`'s BD-01) writes `details={"action", "revenue", "cost", "platform", "success"}` — **`revenue`, not `amount_usd`**. Two halves of one feature, each internally consistent, disagreeing on the field name. |
| BF-04 | info | **Three small members dead:** `list_evidence` (`:351`, 9 lines), `Goal.progress_pct` (`:120`, 4 lines, a property), `Goal.is_overdue` (`:126`, 4 lines, a property). Reachable only through `GoalTracker`. |

---

## A scan correction — the eleventh hidden-reference form, and the first that over-reports liveness

My first pass reported **4 dead of 28**, with `process_event` counted live. It is not.

The reason: **`process_event` is also the name of a method on a different class.**
`main.py:1184` calls `engine.process_event(event)` and `alerting.py:352` calls
`engine.process_event(event)` — and `engine` in both cases is the **`AlertingEngine`**, not the
goal tracker. A name-based scan cannot tell them apart.

That is the **eleventh** mechanism by which a live reference has hidden from this sweep, and
the first that works in the *opposite* direction from every previous one:

| | direction |
|---|---|
| `11y` (dict dispatch), `11C` (Qt `Signal.connect`), `11A` (cross-drive path) | dead code looked **live** |
| `11s` (self-excluded from caller search), `11v` (comment-only references) | live code looked **dead** |
| **this one — same method name on two classes** | **dead code looked live** |

The general lesson is the sharpest version yet: a name-based reachability scan cannot resolve a
**receiver**, and in a codebase where `AlertingEngine.process_event` and
`GoalTracker.process_event` both exist and both do plausibly-named work, a collision is likely
rather than unlucky. Anything the sweep reports as live *by name alone* should be treated as
unverified until the receiver is resolved.

**I am recording this against my own method rather than quietly re-running it**, because the
corrected number (22 dead, not 4) is the headline of this pass and it was wrong for one
iteration. Every earlier pass's internal-reference counting was sound; this one only failed on
*external* name matching, and only for methods whose name is shared.

---

## BF-02 — the exact failure the sweep has been tracking, at its most compressed

The module's docstring says `current_usd` is *"**verified** earnings so far"* and that each goal
carries *"**verifiable** proof rows"*. That contract needs one thing: a check.

```python
# add_evidence — DEAD, 22 lines
343   if evidence.verified and evidence.amount_usd > 0:
344       conn.execute("UPDATE goals SET current_usd = current_usd + ? WHERE id = ?", ...)

# add_earnings — the method actually called, 8 lines
364   """Add verified earnings to a goal."""
367       conn.execute("UPDATE goals SET current_usd = current_usd + ? WHERE id = ?", ...)
```

**The guard and the unguarded version of the same statement sit 35 lines apart, and the guarded
one is the dead one.** That is `11B`'s `_extract_budget` shape — two spellings of one decision —
arriving in a money field, and it is the **ninth** instance of *"the same decision expressed N
times with N answers"* after `11v`'s 27 boolean parsers, `11N`'s four thinking-regexes and
`11L`'s drifted catalog.

**The severity is med rather than high because the whole class is unreachable** (BF-01), so
nothing credits any goal today. The two findings are one finding viewed from two ends, and
**BF-01 is what keeps it from being high**: an unreachable goal tracker cannot misreport
progress.

The moment the class is wired — and `11m`'s work makes that plausible — BF-02 becomes live, and
it becomes live *silently*, because a goal marked 100% complete on unverified amounts would
look exactly like a goal marked complete on verified ones.

---

## Verified as sound

**The data model separates the target from the progress** — `target_usd` and `current_usd` are
distinct fields, and `current_usd` is only ever reached by *addition* (`:345-347`, `:367-369`),
never by assignment from a computed total. There is no path by which a recomputation could
overstate progress.

**`Goal.to_dict` / `from_dict` (16 lines each) and `EvidenceRow.to_dict` / `from_dict` (12 each)
are symmetric pairs.** For a SQLite-backed record with JSON metadata columns, symmetric
serialisers are what keep a round-trip lossless, and these four are written to match.

**`_row_to_goal:489` (16 lines) is a separate mapper**, so SQL column names appear in one place
rather than being spread across the accessors.

**`delete:318-324` removes the evidence rows and the goal in one transaction** —
`DELETE FROM evidence WHERE goal_id = ?` then `DELETE FROM goals WHERE id = ?`, with no
orphaned evidence left behind. That is the `11H` `safety_tools_tab._on_approve` ordering
(`record the decision, then act`) applied to a delete, and the ordering is correct: children
first, so there is no window in which a goal exists with no evidence policy governing it.

**`check_completion:372-378` guards on status before acting** — `if goal.status !=
GoalStatus.ACTIVE.value: return` — so a completed goal is not re-evaluated on every subsequent
earning event. Without that, a goal at 100% would be recomputed on every event forever.

**`_auto_match_event:453-461` maps seven event types to goal paths, with `'payment.received':
None` meaning "any path"** — and the comment says so. An explicit `None` as a wildcard beats
a separate code path, which is `11D`'s `OUTCOME_STATES` instinct applied to dispatch.

---

## Re-verification

**`11M` / BD-01 extended, and this is the seam that closes it.** `11M` found four typed emitters
dead and the Insights tab's panels empty. `BD-03`'s note anticipated this: *"the field would have
to come from verified evidence, or the panel would reintroduce exactly the fabrication
ARCH-ENG-212 removed."* **BF-03 shows the goal tracker's half of that integration was never
finished either** — and in the *opposite* direction: it would accept an amount from an event
detail with no verification check at all. Fixing `BD-01` without fixing `BF-02` would wire an
unverified amount into a goal's `current_usd`.

**`11P` consistent, and the contrast is instructive.** `economic_accounting` requires
`EvidenceStatus.VERIFIED` **and** `>= L3_EXTERNAL_SOURCE` on both its profile builder and its
quick accessor — the fix `get_verified_revenue`'s docstring records as *"two authorities
disagreeing about the same evidence."* **The goal system has the same two-authority shape, and
the disagreement is still live**: `add_evidence` checks, `add_earnings` does not. `11P` shows
what the resolved version looks like in the same repository.

**`11F` / ARCH-ENG-212 consistent.** `estimated_usd_value` is `0.0` when no honest value is
derivable; `goal_system`'s `current_usd` starts at 0 and only ever increments. Both refuse to
begin from a plausible-looking default.

**`11e` / autonomous_loop unaffected.** No import relationship either way; the goal tracker is
a consumer of events, and the loop is a producer.

---

## Assessment

Twenty-two of twenty-eight members unreachable, and the correct disposition is almost certainly
deletion rather than wiring — but the reasoning matters, because it is the case where those
differ most.

**BF-01's reason for being unwired is not recorded anywhere**, unlike `11D`'s diagnostics shim
(which said *"since v2.1.11 these live inside the DB Stats tab"*). So this is not the
well-handled migration shape; it is `11G`'s workshop, where a subsystem exists with no
documented decision. That distinction determines the fix: a documented shim should be deleted
with its note intact, whereas this should be either wired — with BF-02 fixed first — or deleted
with `__all__` cleaned up.

**BF-02 is the finding to carry forward regardless of BF-01's disposition**, because it will
outlive whichever is chosen. If the class is deleted, the mismatch goes with it. If it is wired,
the mismatch is *already* in the code and would become reachable. **The sequencing rule this
sweep keeps arriving at applies here in its sharpest form yet: for a dead entry point, ask what
would be true downstream the moment it was.** For `GoalTracker`, the answer is *"a goal would
show progress that no verified evidence supports"* — and the mechanism that would make it so is
present, reachable from the live path, and eight lines long.

**One methodological note for the record.** This pass produced the sweep's most consequential
scan correction (4 dead → 22 dead), and it came from a class-name collision rather than from
any of the ten previously catalogued forms. The consolidated fix list should therefore include
a scan upgrade — **resolve the receiver, not just the name** — before any further depth passes
are run, because every remaining file carries the same risk and the error is silent in the
direction that *understates* dead code.
