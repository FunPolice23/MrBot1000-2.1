# 11i — `agents/earning/opportunity_portfolio.py` depth pass (854 lines, 31 methods)

Depth-pass #9 of 83. **30 of 31 live.** The work-queue layer on top of the lifecycle
tracker, with a 16-state vocabulary that turns out to be the most thoroughly
modelled in the repository.

---

## Structure

```
L   39-40    class IllegalTransitionError
L   45-71    class WorkStatus          (16 states)
L   83-163   class WorkStatusConfig    (per-status config)
L  169-205   class PortfolioEntry      (2 methods)
L  210-487   class OpportunityPortfolio (15 methods)
L  507-591   class QueuePolicy         (3 methods)
L  597-604   class CapacityConfig
L  609-787   class WorkQueue           (10 methods)
```

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AC-01 | info | **`WorkQueue.get_blocked` (`:770`, 3 lines) is the only dead method.** Its entire body is `return [e for e in self.portfolio.list_work(WorkStatus.BLOCKED)]`, and `list_work` is live — so the capability exists one call away, and `summary` (`:774`, live) already reports counts by status including `BLOCKED`. The reason text is separately surfaced by the live `resolve_next_action` (`:813-820`), which substitutes `entry.blocked_reason` as the human-facing reason whenever the status is `BLOCKED` (`:816-817`). Nothing is lost. Recorded because a 30-of-31 result is otherwise clean, and because it is worth stating explicitly that the *state* is fully modelled even though this *accessor* is not — a distinction the module's own design makes and a dead-code count alone would miss. |

---

## Verified as sound — the most thoroughly modelled state machine in the project

**`WorkStatus.BLOCKED` is not a dormant enum value — it is the most thoroughly
modelled state in the codebase.** Three things make that clear:

1. **It is an overlay, not a replacement.** `WorkStatusConfig` at `:101` records
   `WorkStatus.BLOCKED: "__preserve__"` with the comment *"keeps current lifecycle
   stage"*. Blocking an entry does not overwrite where it was; it suspends it.
2. **It is reachable from nearly every other state.** `BLOCKED` appears in the
   transition tables at `:120`, `:125`, `:128`, `:132`, `:136`, `:140`, `:149`,
   `:152` and `:156` — as a legal successor from `QUALIFIED`, `ABANDONED`, `EXPIRED`,
   `AWAITING_APPROVAL`, `READY`, `REJECTED`, `IN_PROGRESS`, `COMPLETED`,
   `PAYMENT_PENDING`, `PAID` and `FAILED`. Eleven source states.
3. **It has its own next-action and a surfaced reason.** `_NEXT_ACTION_MAP` at `:801`
   maps it to `("unblock_or_abandon", "blocked")`, and `resolve_next_action`
   (`:813-820`) overrides the generic reason with `entry.blocked_reason` so the
   operator sees *why* rather than merely *that*.

**`IllegalTransitionError` exists and is raised**, so the state machine fails
loudly on an illegal move rather than silently accepting one — the opposite
failure direction from the dead-code cluster this sweep has been finding.

**`WorkQueue` implements real capacity admission control**, not a list:
`_current_counts` (`:680`, 22L) snapshots utilisation across dimensions,
`would_exceed_capacity` (`:703`, 28L) checks a candidate against them,
`_projected_counts` (`:751`) computes the post-consumption state, and `select_next`
(`:732`, 18L) walks them. `rescore_all` (`:635`, 36L) persists a policy score for
every non-terminal entry — the *write* side that `10q`'s P-02 found missing in
`EarningMemory`, present and live here.

---

## Re-verification

**No earlier finding is contradicted.** The `10q` observation that this module is
reached from `application_services`, `autonomous_loop` and `composition_root` stands
— 10 outside consumers, the most-wired file in `agents/earning/`.

**Consistent with `11f`.** This module sits *on top of* `OpportunityLifecycleTracker`,
which is where Z-01's dead reconciliation and Z-02's dead scheduler live. So the
portfolio layer has its own state machine, its own transitions and its own queue
policy — all live — while the lifecycle beneath it has none of its temporal behaviour
wired. The two-layer picture is coherent and consistent with both documents.

---

## Assessment

30 of 31 live, with the single dead method being a one-line convenience over
capability that exists and is used.

This file is worth singling out for a different reason than its dead-code count.
`WorkStatus.BLOCKED` being an *overlay that preserves the underlying lifecycle
stage* — `"__preserve__"` at `:101` — is a design decision that resolves a tension
the rest of the codebase does not address. `11f` found the lifecycle has no clock and
no reconciliation; the portfolio's answer to "how do I represent work that cannot
proceed right now, without losing where it was" is to suspend rather than overwrite,
and it makes that explicit in a table rather than in a comment.

That is the third time this sweep has found the answer to a gap recorded elsewhere,
rather than only the gap. The `dual_brain.py` chat-template fallback (`11d`),
`dispatch.py`'s alias resolution (`11g`), and now this are all cases where a mechanism
exists and is live, and the finding is about something adjacent that is not.