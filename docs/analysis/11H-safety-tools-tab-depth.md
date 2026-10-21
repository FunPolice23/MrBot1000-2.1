# 11H — `gui/tabs/safety_tools_tab.py` depth pass (623 lines, 16 methods)

> **U-01 RESOLVED in v2.1.125 (ARCH-ENG-284).** The tab now carries the
> instruction-quarantine review surface as a fourth sub-tab. It lists pending
> `SKILL.md`/playbook rows with source, kind, title and hash; shows
> pending/allowed/blocked counts; and routes Approve/Blacklist to the same
> `InstructionGate` used by the platform adapters. The dead MainWindow
> `_refresh_review_queue`/`_review_selected` island is gone.
>
> **AZ-01 RESOLVED in v2.1.125 (ARCH-ENG-269).** An approved decision was lost
> silently when no executor handler was attached or when re-reading the queue
> failed: the row left the pending list and nothing ran. Both paths (and a
> raised routing error) now call `_report_unrouted`, which logs a warning and
> raises a `NotificationService` warning naming the approval id and reason.
>

Depth-pass #34 of 83. **0 dead of 16 — no functional finding.** This is the file where the
sweep's recurring defect is **named, reproduced with a test-shaped description, and fixed** —
and where the remaining residue is one silent path downstream of that fix.

---

## Structure

```
L  21-49    _ROUTABLE_APPROVAL_KINDS = (ACTION, SUBMISSION)
L  52-623   SafetyTab (16 methods)
```

No module docstring. Largest: `_create_config_tab` (103), `_create_status_tab` (99),
`_refresh_approvals` (72), `_create_approvals_tab` (63), `_on_approve` (39),
`_refresh_layers` (37), `setup_ui` (28).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AZ-01 | low | **The decision-routing half is silent on both failure paths.** `_route_decision:568` reaches the shared execution path by **`getattr(self.parent(), "_on_approval_decided", None)`** — a duck-typed lookup *by string name* — and both failure modes return without a trace: `:569-570` `if not callable(handler): return`, and `:578-581` `except Exception: pass`. **`SafetyTab` has no log channel at all** (no `log_signal`, no `_log`, no `log_fn` anywhere in the file), so neither can surface. The operator sees the row flip to APPROVED via `self.refresh()` while the action does not execute. |

---

## The never-dropped rule — the sweep's recurring defect, fixed here

`_on_approve:500-520` is the best defect narrative in the GUI layer, and it describes
precisely the class this sweep has now recorded eighteen times:

> *"The human's click is **NEVER dropped**. `SafetyGuard.approve()` only knows the ids it
> raised itself, so an approval the chat dispatcher or the Big Brain enqueued straight into
> `HumanApprovalQueue` made it return `False` — and the item **stayed PENDING forever,
> silently, with no log and no error**. Reproduced: `guard.approve(dispatch_id) -> False`,
> the queue item never left 'pending', and `_route_decision` never ran."*

The failure is precisely *"mechanism correct, wired at one end only"* — `SafetyGuard` held
the authority for ids it raised, and every id raised by the chat dispatcher or the Big Brain
(`11z`'s and `11t`'s producers) fell through it.

**And the fix takes the right shape.** `:529-535`:

```python
ok = self.safety_guard.approve(approval_id)   # guard first: it owns its records
if not ok:
    ok = self.approval_queue.approve(approval_id, notes="Approved from Safety & Tools")
```

The guard is **not replaced** — it keeps precedence because it owns its own records and
mirrors decisions into the queue. The queue is the fallback authority. That is the same
resolution `11z` recorded for the two `_detect_gpus` and `11p` for the dispatchers: **one
mechanism keeps its role, the other covers the gap, and the relationship is documented.**

**The security argument is stated and, unusually, enforced in code rather than only claimed:**

> *"This cannot fabricate an approval — the id came from a row a human selected, and
> `_on_approval_decided` re-reads the queue before executing anything."*

`:573-575` does exactly that:

```python
item = self.approval_queue.find_by_id(approval_id)
if item is None or item.status != ApprovalStatus.APPROVED:
    return
```

**The claim and the code match.** A tab that merely *believed* it had recorded a decision
would be a finding; this one re-reads the queue and refuses to route anything it cannot
confirm.

`_route_decision:564-566` states the same property from the other side:

> *"Best-effort and fail-safe: this only notifies. **It cannot execute anything by itself** —
> the handler re-reads the decision from the queue, so a decision this tab did not actually
> record will not run."*

**`_on_reject:543-546` applies the rule to the irreversible direction**, and gets the priority
right:

> *"Same never-dropped rule as `_on_approve`: a rejection the guard does not recognise is
> recorded in the queue instead of being swallowed, so **an operator who clicks Reject never
> leaves an irreversible request looking pending and re-approvable**."*

A dropped *approval* is an inconvenience; a dropped *rejection* is an irreversible request that
looks re-approvable. Both are closed, and the docstring says which is worse.

---

## AZ-01 — the residue, and why it is specifically a logging gap

The fix above moved the "silently, with no log and no error" mode **one hop downstream**. The
decision can no longer be lost — it is recorded in the queue before routing is attempted, which
is correct. But the *execution* half can still fail invisibly, and the tab has nowhere to say
so.

The asymmetry between the two approval surfaces is what makes this worth recording:

| | `ApprovalPanel` (`11t`) | `SafetyTab` (here) |
|---|---|---|
| decision recording | `self.approval_queue.approve(...)` | guard first, queue fallback |
| routing mechanism | **`item_decided = Signal(str, ApprovalStatus, str)`** (`:34`), emitted at `:244`, `:257`, `:271` | **`getattr(self.parent(), "_on_approval_decided", None)`** (`:568`) |
| coupling | a Qt signal, rename-safe | **a string name** |
| log channel | none found | none |

**One surface couples by signal, the other by string.** A rename of `_on_approval_decided`, or
a tab reparented under something that lacks it, silently disables routing on this surface
only — and because `refresh()` still runs, the operator sees a clean APPROVED.

The fix is two lines: give `SafetyTab` the parent's `log_signal` (or a `log_fn` constructor
argument, as `action_pipeline.py` does via `main.py:450`) and emit on both early returns. That
matters more than usual here, because the docstring at `:511-513` explicitly names *"silently,
with no log and no error"* as **the** defect — so a reader of this file will reasonably expect
that property to hold everywhere, and it currently holds only up to the routing call.

---

## Verified as sound

**`_ROUTABLE_APPROVAL_KINDS = (ACTION, SUBMISSION)` (`:21`, `:49`) is an explicit allowlist.**
`11t` recorded that payments are deliberately excluded from routable kinds — `:44` says
*"(`HumanApprovalQueue.enqueue`), so a payment request stays fully visible"* without being
actionable from this surface. Constraining which kinds this tab can drive, in a named constant
at module level, is the right way to express that.

**`_refresh_approvals` (72 lines) lists every PENDING item, not a filtered subset** — `:430`:
*"Every PENDING item in `HumanApprovalQueue` is listed, not only the…"*. The operator sees the
whole queue, so a payment request that this tab cannot action is still **visible**. That
distinction — visible but not actionable — is what `11t` described as the correct scope, and it
is the reason the missing routing log matters less than it would if items were merely absent.

**Two tab surfaces, not one.** `11t` recorded `approval_panel.py` as the primary; this is the
second. Neither is a duplicate: this one co-hosts the config and status tabs (`_create_config_tab`,
`_create_status_tab`, `_refresh_layers`), so an operator reviewing the safety posture has the
queue, the layers and the config in one place.

---

## Re-verification

**`11t` confirmed, and its most important claim is now traced end-to-end.** `11t` recorded the
queue as *"the most completely wired safety component in the codebase"* and listed
`safety_tools_tab.py:64, 462, 534, 557` as consumer sites. `:534` and `:557` are the two
`self.approval_queue.approve(...)` / `.deny(...)` fallbacks read above — **the operator's click
is guaranteed to land in the queue even when the guard does not own the id.** The wiring `11t`
described is real at the decision end.

**`11k` / `guard.py` consistent.** `SafetyGuard.approve()` still owns its own records and is
tried first, exactly as `11k`'s layering described (the decision living in the queue, the guard
remembering). This file respects that split rather than collapsing it.

**`11z` consistent.** The Big Brain's direct `HumanApprovalQueue` enqueues
(`big_brain.py:280`) are precisely the ids `SafetyGuard.approve()` cannot see — and the docstring
names that source explicitly (`:510`).

**`11v` / AO-02 unaffected.** Live trading approvals are `ApprovalKind.PAYMENT`, excluded from
`_ROUTABLE_APPROVAL_KINDS`, so the `AO-01` inert cluster stays inert here — correctly.

---

## Assessment

Zero dead of sixteen, and one low finding that is the residue of a fix rather than a fresh
defect.

`_on_approve`'s docstring is, on its own, worth more than most of the findings in this sweep —
not because it describes something clever, but because it describes the **exact** defect class
this sweep keeps meeting, names the reproducer, explains why the obvious fix (replace the
guard) was wrong, and states the security invariant that the fix had to preserve. That is what
a well-handled instance of this defect looks like, and it is now the second counter-example
after `11t`.

**AZ-01 is worth fixing precisely because the file sets the standard it then misses.** The
docstring says *"silently, with no log and no error"* is the defect; the routing half still
fails that way, one hop on. The asymmetry with `ApprovalPanel` names the cause: one surface
couples to the execution path by **signal**, the other by **string**, so a rename or reparent
disables routing silently on exactly one of them.

That is a general observation about this codebase's GUI, and it is the mirror image of
everything `11y`–`11C` recorded about its scans. Those passes found *references the scanner
could not see*; this one finds a *reference the compiler and IDE cannot see either*. A
`getattr` by string name is invisible to static analysis, to refactoring tools, and to the
sweep's own reachability scans — which is why the two approval surfaces could drift apart
without any tool objecting.
