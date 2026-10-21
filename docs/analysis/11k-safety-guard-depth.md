# 11k — `agents/safety/guard.py` depth pass (782 lines, 43 methods)

> **LOW TIER CLOSED in v2.1.125.** AE-01 (ARCH-ENG-257): the four runtime list
> mutators (`add_to_denylist`, `add_to_allowlist`, `remove_from_denylist`,
> `remove_from_allowlist`) are deleted -- the lists are fixed at construction
> from settings and the setters implied an editing capability nothing uses.
> AE-03 (ARCH-ENG-258): `set_approval_callback` is deleted; `self._callback`
> was never assigned and approval enqueues into the shared queue directly.
> AE-04 (ARCH-ENG-259): `check_and_raise` and `get_remaining` are deleted.
>

Depth-pass #11 of 83. **36 of 43 live.** The multi-layer safety orchestrator. Seven
dead methods, and they cluster into two superseded mechanisms rather than scattering.

---

## Structure

```
L   30-35    SafetyLevel        L  302-566  HumanApprovalLayer   (10 methods)
L   39-47    SafetyAction       L  569-638  RateLimiterLayer     (4 methods)
L   51-66    SafetyResult       L  643-774  SafetyGuard          (10 methods)
L   71-91    SafetyLayer        L  777-782  SafetyViolation
L   94-127   CostGuardLayer     L  246-299  ToolFirewallLayer    (6 methods)
L  130-243   RecursionDetectorLayer (4)     L  94-127 CostGuardLayer (2)
```

Five layers, all constructed from config and sorted by priority descending
(`:675`), then run in order with first-match-wins semantics (`:679-707`).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AE-01 | low | **The tool firewall's allow/deny lists are fixed at construction — all four mutators are dead.** `add_to_denylist` (`:289`), `add_to_allowlist` (`:292`), `remove_from_denylist` (`:295`), `remove_from_allowlist` (`:298`) — 2 lines each, zero tests, no callers. The lists come from `self.config.get("allowlist", [])` / `"denylist"` at `:254-255` and never change. Vestigial API: the correct way to change them is to change the config and rebuild the guard. |
| AE-02 | info | **The firewall's default posture is permissive.** `default_allow = self.config.get("default_allow", True)` (`:256`), and the allowlist only binds when non-empty (`:277`). So with no configured allowlist, **every tool not on the denylist is allowed**. The layer is deny-list based by default and allow-list based only if an operator configures one. Worth stating explicitly because "ToolFirewallLayer" reads as a restrictive component and is in fact permissive unless configured. The denylist is still checked first (`:266`), and the failure messages carry `suggested_action` text (`:273`, `:284`), so the refusal is actionable. |
| AE-03 | low | **`set_approval_callback` (`:320`) is dead — superseded by a better mechanism.** `self._callback = None` at `:318` and never assigned. The layer now enqueues directly into the shared `HumanApprovalQueue.instance()` at `:442`, and the comment at `:311-315` records why: *"The DECISION lives in `HumanApprovalQueue`; this map only remembers which queued items this layer asked for, so `get_pending()` can scope itself to its own requests instead of reporting the whole queue."* That refactor is an improvement on every axis — scoped reads, a bounded `_owned_max = 256` (`:316`), and a `threading.Lock` (`:317`) — and the callback setter was simply left behind. Same shape as `hardware_plan.py` (M-01) and the parallel discovery layer (W-01): a better mechanism superseded an older one, which was not retired. |
| AE-04 | low | **`check_and_raise` (`:719`, 6 lines) and `RateLimiterLayer.get_remaining` (`:632`, 7 lines) are dead.** A raising convenience wrapper and a quota query. Both have zero tests. |

---

## Verified as sound

**Layer ordering is deterministic and first-match-wins.** `_setup_layers` (`:652`)
builds all five from config then sorts `key=lambda l: l.priority, reverse=True`
(`:675`), so evaluation order does not depend on dict ordering or registration
sequence. `check` (`:677-712`) returns the first non-`None` layer result and
short-circuits, returning a final allow only when every layer passes.

**Priorities encode the right ordering.** `ToolFirewallLayer.priority = 80` (highest)
runs before `HumanApprovalLayer.priority = 70` — a denied tool is refused
structurally before anyone is asked to approve it, which is the correct order: do not
spend the operator's attention on an action that policy forbids outright.

**`HumanApprovalLayer` reaches the operator-visible queue, not a private one.**
`:367` names the requirement explicitly — *"HumanApprovalQueue — the one the GUI
Approvals panel and…"* — and `:442` uses `HumanApprovalQueue.instance()`. So a
request raised by the safety guard appears in the same Approvals tab the operator
already watches, rather than in a second queue that would need its own UI. This is
the property that makes the guard's approval path usable at all.

**Concurrency discipline is thorough.** Nine `with self._lock:` sites across
`HumanApprovalLayer` (`:317`, `:382`, `:447`, `:476`, `:486`, `:499`, `:506`, `:549`)
and `RateLimiterLayer` (`:582`, `:589`, `:635`), plus two in `RecursionDetectorLayer`
(`:167`, `:230`, `:241`). Given that `tmp/probe_concurrency*.py` exist specifically to
probe *"force >=10 threads"* into `guard.check`, this layer has clearly been under
concurrency scrutiny, and the locking matches.

**`_owned_max = 256` bounds a map that a naive implementation would have left
unbounded** (`:316`) — the same class of fix as ARCH-ENG-228's `_cache`/`_stats` LRUs.

---

## Re-verification

**Consistent with `11g`.** `guard.py`'s `SafetyGuard.check` and
`dispatch.execute_tool`'s `authorization` decision are the two entry points the earlier
pass verified. Nothing here contradicts `11g`'s finding that all 20 handlers route
through the dispatcher with a verified approval binding — this module's
`HumanApprovalLayer` is the layer that decides *whether approval is needed*, and it is
correctly wired to the same shared queue.

**ARCH-ENG-043 unaffected.** The win-rate gate that stops an operator-typed reference
from advancing auto-submission operates downstream of `PayoutVerifier`, not through
this layer.

---

## Assessment

36 of 43 live. The seven dead methods are not scattered — they form two identifiable
clusters, both **superseded mechanism rather than missing work**:

- AE-01: the firewall's runtime list mutators, obsoleted by config-driven construction
- AE-03: the approval callback, obsoleted by direct shared-queue integration

In both cases the replacement is *better than the thing it replaced* — config-driven is
simpler and inspectable, and the shared queue gives scoped reads, a bounded map and
proper locking. The residue is the old API surface. That is a materially better
situation than the dead cluster in `10q` (`EarningMemory`'s 15 analytical readers,
where nothing replaced them) or `11f` (reconciliation and scheduling, where the
replacement is absent).

AE-02 is the one item with an operational consequence, and it is not a defect: the
firewall is permissive unless an allowlist is configured. Recorded because the class
name implies otherwise, and because the next person to reason about tool safety from
reading alone would get it backwards.