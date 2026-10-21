# 11t — `agents/safety/approval.py` depth pass (636 lines, 24 methods + 5 module functions)

> **G-05 APPROVAL ROUTE WIRED in v2.1.125 (ARCH-ENG-283).** Live orders now
> enqueue a normal `ApprovalKind.ACTION` with `requested_by="live_trading"` and
> the exact `TradeIntent` in the payload. `MainWindow._on_approval_decided()`
> routes that marker to `_execute_approved_live_order()`; every other ACTION
> still takes the generic dispatcher. The queue's existing duplicate-decision
> guard is complemented by `_executed_approval_ids`, so one approval submits at
> most one order.
>
> **AM-02 RESOLVED in v2.1.125 (ARCH-ENG-265).** `_maybe_persist` truncated the
> live approval log in place and swallowed every failure. The write now goes to
> a temp file and is `os.replace`d, and a failure logs a warning stating that
> the decisions will not survive a restart.
>

Depth-pass #20 of 83. **1 dead of 24 methods; 0 dead of 5 module functions.** This is the
**counter-example file** for the sweep's most frequent finding — the mechanism that is
correct *and* wired at both ends — and it is worth a document for that reason as much as
for its two small findings.

---

## Structure

```
L   50-54    ApprovalKind      L   65-118   ApprovalItem   (3 methods, all live)
L   57-61    ApprovalStatus    L  121-500   HumanApprovalQueue (21 methods)
L  525-546   approval_scope / assert_approval_covers
L  598-598   _approval_args_match
L  615-624   enqueue_approval
```

Largest methods: `_load` (55), `decide` (50), `_maybe_persist` (49), `enqueue_payment`
(34), `enqueue` (24), `find_by_id` (20).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AM-01 | info | **One dead method.** `items_for_kind` (`:372`, 4 lines) — a one-line filter over `self._items`, zero tests, no callers. The two consumers that need kind-filtering do it themselves: `gui/panels/approval_panel.py:165-168` holds its own per-kind colour map, and `gui/tabs/safety_tools_tab.py:430` lists *"every PENDING item … not only the"* one kind. |
| AM-02 | low | **Persistence failure is silent.** `_maybe_persist:437-438` ends `except Exception: pass  # persistence is best-effort`. For a component whose entire purpose is a durable, operator-visible record of human decisions, this is the one place a failure is invisible: if the log path becomes unwritable (disk full, permissions, a locked file on Windows), the operator approves a payment, the GUI shows `APPROVED`, and the record is absent on restart with **no diagnostic anywhere**. `NotificationService` is already imported at `:11` and already used by this class, so a one-line warning preserves both the "never crash on a disk error" intent and the operator's ability to know. |

---

## The counter-example: this is what "wired at both ends" looks like

The sweep's dominant defect — *"mechanism correct, wired at one end only"* — now has 15
instances. **This file is the case where both ends are wired, and it is heavily so.**

| Consumer | Line | What it does |
|---|---|---|
| `big_brain.py` | 280 | enqueues `ApprovalKind.ACTION` |
| `chat_completion.py` | 506, 621 | enqueues `ApprovalKind.ACTION` (2 sites) |
| `safety/dispatch.py` | 77 | enqueues `ApprovalKind.ACTION` |
| `safety/guard.py` | 442 | mirrors requests into the queue |
| `platforms/registration.py` | 94 | `RegistrationService(approval_queue=…)` |
| `earning/live_trading.py` | 405, 446, 517, 532 | enqueue + re-read (4 sites) |
| `earning/real_crypto_operator.py` | 84, 168 | `ApprovalKind.PAYMENT` + re-read |
| `earning/platform_submitter.py` | 205 | *"The decision is re-read from HumanApprovalQueue, never from a caller"* |
| `earning/moltbook_agent.py` | 191 | `enqueue_submission` |
| `services/code_patch_service.py` | 246, 275 | enqueue + `find_by_id` before `apply()` |
| `core/composition_root.py` | 163 | injected as a dependency |
| `core/alerting.py` | 250, 268 | queue-backed alerts |
| `runtime/context.py` | 100 | surfaces the last 8 pending |
| `main.py` | 498, 533 | owns the singleton, wires `on_change` |
| `gui/panels/approval_panel.py` | 39, 243, 256, 270 | the operator surface: approve / deny / defer |
| `gui/tabs/safety_tools_tab.py` | 64, 462, 534, 557 | second operator surface |

Roughly 25 production modules, plus **297 test references across 33 test files** — including
`test_arch_eng_129_approval_scope_binding.py`, `test_arch_eng_165_verified_approval_scope.py`,
`test_arch_eng_130_crypto_send_approval_gate.py` and
`test_arch_eng_121_record_payment_evidence_floor.py`.

**This is the inverse of `11g`'s `_tool_propose_code_patch`** — the tool that was advertised
in `tools.py:59` but whose loop was only *enterable* — and the inverse of `AJ-01`, where the
engine was constructed and never called. Here: constructed, written to, re-read before
every consequential action, surfaced in two GUI panels, and persisted.

---

## ARCH-ENG-165 — the sweep's recurring defect, named at the moment it was fixed

`agents/safety/authorization.py:38-60` documents the exact defect class this sweep keeps
finding, **and enumerates its blast radius while doing so**:

> *"When the gate returned NEEDS_APPROVAL, a truthy `approved` upgraded the decision
> straight to ALLOWED with the reason 'Explicit approval supplied'. **Nothing consulted
> `HumanApprovalQueue` and nothing called `assert_approval_covers`, so the caller's
> assertion was the whole authorization.** The HIGH-TRUST handlers (`record_payment`,
> `social_post`, the crypto send) re-check the queue themselves and were never exposed —
> **but a mutating tool with no internal check (`file_write`, `run_command`,
> `workshop_payment`) executed on a bare boolean.**"*

Two things make this the best-written instance of the pattern in the codebase.

First, it distinguishes **what was exposed from what merely looked exposed**. The
high-trust handlers were already safe; the defect lived in the low-trust tools that had no
internal check. A note that said "the approval gate was bypassable" would have been
misdirection in both directions — it would overstate the high-trust risk and understate
the `file_write` / `run_command` risk, which is where a bare boolean actually reached
`run_command`.

Second, the fix keeps **two visibly distinct paths** rather than collapsing them:

> *"`approval_id` GIVEN — VERIFIED. The item is resolved from the shared queue and
> `assert_approval_covers(item, name, arguments)` must return None. That binds the
> approval to this exact tool and these exact arguments (ARCH-ENG-129), **so an approval
> for `$10` cannot execute a `$10,000` payment**, and an approval that was never APPROVED,
> or that records no tool scope, authorizes nothing. A refusal does NOT upgrade the
> decision: the original NEEDS_APPROVAL stands and the caller re-enqueues, so the operator
> sees the pending request."*

Three properties worth naming: the approval is bound to **arguments, not just a tool name**
(ARCH-ENG-129 — the `$10` / `$10,000` case); a refusal **does not escalate** to ALLOWED; and
a refusal **re-enqueues**, so the operator still sees the request instead of it vanishing.

---

## `_maybe_persist`'s eviction rule — a sharp distinction, with the bug it fixed named

`_maybe_persist` (`:390-438`) bounds a file that is rewritten in full on every change, and
the bound has an exception carved into it that is easy to get wrong:

> *"Two classes of item are NEVER evicted: PENDING items — losing one is the defect this
> file exists to fix: a request nobody can see is a request nobody can approve. Items a
> human DECIDED IN THIS PROCESS — approving a $5000 payment and then enqueueing 210 more
> items used to delete that approval from memory AND from disk, destroying both the live
> authorization and the audit record of a human decision. **A decision is not history the
> moment it is made; it is history only once the process that made it has exited** (at
> which point `_restored_decided` already refuses to honour it)."*

That is a real bug that was found, fixed, and stated — and the fix is principled rather than
a larger constant. `_decided_in_process` and `_restored_decided` are separate sets, and the
code also intersects both against the retained ids (`:429-431`) so they cannot drift
monotonically for the life of the process.

**`_restored_decided` is the security-critical half.** A decision restored from disk is
**history, not authorization** — `:140-142` says so, and the module-level comment at
`:19-21` repeats it. An approval made by a human in a previous process does not authorize
anything now. Without that distinction, restarting the app would resurrect every old
approval as live authority.

---

## `default_log_path()` — a hazard anticipated before it could bite

`:25-47` is 23 lines of path resolution, and the docstring explains why most of the care is
about the test suite:

> *"**A test run must be structurally incapable of writing the operator's LIVE queue** —
> several existing tests call `HumanApprovalQueue.instance()` and then `clear_all()`,
> which would otherwise persist an empty list over real pending approvals. Same rule as
> `app/environment.py`'s `.env` write refusal: under pytest the queue stays in memory
> unless a test opts in by setting `MRBOT_APPROVAL_QUEUE_PATH`."*

The guard is `if "pytest" in sys.modules: return ""` (`:45-46`), which makes the failure mode
**structurally impossible** rather than merely unlikely — the same standard ARCH-ENG-115 set
for hardware claims. The path is `~/.mrbot1000/approvals.json`, derived from the home
directory, never hardcoded and *"never inside the source tree (which may be read-only, and
which a re-clone would silently replace)."*

**Checked and not a finding:** `approvals.json` is not covered by `_SECRET_FILE_NAMES`
(`agents/safety/handlers.py`, 9 entries). That is correct — the file records *decisions* and
tool arguments (amounts, paths, targets), not credentials. The secret-file machinery exists
for files that hold keys, and an approval decision is not a key.

---

## Re-verification

**`11g` confirmed.** `_SECRET_FILE_NAMES` is the same machinery `11g` verified at
`handlers.py:516`, and `_tool_propose_code_patch` (`:224`) is the entry point this queue
backs — `code_patch_service.py:273-275` resolves `approval_queue.find_by_id(patch_id)`
before `apply()`, so the propose→approve→apply loop is genuinely closed here rather than
merely enterable.

**`11k` / `guard.py` confirmed.** `guard.py:312` — *"The DECISION lives in
HumanApprovalQueue; this map only remembers…"* — is the same separation of concerns this
file implements, and `guard.py:442` / `:521` / `:545` all route through this queue. The 7
dead methods `11k` recorded do not include an approval decision, consistent with the
decision having been moved out of the guard rather than left behind in it.

**`11f` consistent.** `opportunity_lifecycle.py` consumes approvals through the same
`assert_approval_covers` path (`handlers.py:748`, `:862`), so the ARCH-ENG-165 fix applies
to the lifecycle's high-trust handlers exactly as documented — those were already safe.

**`W-02` unaffected and worth restating.** `11c` recorded that `social_automation` has no
live gate. This pass did not find the gate for it here either — but the queue *could*
accept one (`enqueue_approval`, `:615`, dispatches all four kinds including
`ApprovalKind.ACTION`). So W-02 remains a missing *caller*, not a missing *mechanism*, which
is consistent with everything in this document.

---

## Assessment

One dead four-line filter and one silent `except`. This is among the cleanest modules in
the depth pass.

The reason it earns a full document is that it is the **positive control** for the sweep's
central finding. Fifteen instances now say *"the mechanism is right, one end is missing"* —
`U-01`'s instruction quarantine with no review surface, `W-02`'s ungated
`social_automation`, `AJ-01`'s audit engine that is constructed and never run, `AA-01`'s
host-contract guard written and never called, `AK-01`'s Anthropic parser. Against those,
this file shows what the finished version looks like: a queue constructed once, shared
through a composition root, injected as a dependency rather than imported ad hoc, written to
from fifteen call sites, **re-read from the shared store before every consequential
action**, bound to specific arguments, surfaced in two operator panels, and persisted with
a retention rule that protects live authorizations.

ARCH-ENG-165 is the reason the contrast is so sharp. That docstring is the sweep's defect
described from the inside, by someone who had just fixed it: *"so the caller's assertion was
the whole authorization."* A codebase that can write that sentence about its own past
failure — and then fix the high-trust path without falsely claiming the low-trust path was
ever at risk — is applying the standard the rest of the findings should be measured against.

AM-02 is the one item worth acting on, and the irony is instructive: the only silent failure
in the module is in the function whose job is to make a human decision **durable**. The
`NotificationService` needed to surface it is already imported eleven lines above.
