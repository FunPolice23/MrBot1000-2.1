# 11u — `agents/core/comms.py` depth pass (623 lines, 34 methods)

> **AN-02 RESOLVED in v2.1.125 (ARCH-ENG-247) — wired, not deleted.**
> Operator disposition: wire the cancellation mechanism. The finding was
> stronger than "no caller": `_deliver` never consulted the token, so
> `cancel()` could return True and change nothing. The wire needed three
> parts, all now present: (1) a producer — the coordinator's `_record`
> now publishes to the bus (its class docstring already claimed it did;
> before, the bus had zero production publishers and only logged to the
> local MessageLog); (2) a token owner — one token per collaboration run,
> published with every stage message; (3) a consumer — the Collaboration
> tab's new Stop calls `cancel_active_run`, `collaborate` checks the token
> at each stage boundary (no further model spend) and the bus refuses the
> cancelled run's remaining deliveries (`cancelled_drops` makes it
> observable). Terminal run updates publish outside the token so the
> operator still sees the cancellation. Delivery order is now subscription
> order, making the cooperative "guard subscribes first" contract
> deterministic. **AN-01, AN-03 and AN-04 remain as recorded.** AN-04's
> `get_token` is no longer dead — it is the runtime's token factory.

Depth-pass #21 of 83. **11 dead of 34 methods** — the highest count since `11m` — and the
interesting result is that one of them *looks* like a missing safety limit and is not.

---

## Structure

```
L   39-65    MessageType       L  123-203   Message          (7 methods)
L   68-74    MessageStatus     L  210-235   CancellationToken (6 methods)
L  111-115   CancelledError    L  245-594   EventBus         (20 methods)
L  605-617   QtEventBridge (Qt-optional, guarded by try/except)
L  620-622   aliases: BusMessage, MESSAGE_TYPES
```

Docstring: *"Structured internal message/event protocol for MrBot1000… It replaces ad-hoc
string queues, positional Qt signal tuples, and the JSON-file SharedContext mirror with a
single, typed, thread-safe mes[sage bus]."*

Largest: `publish` (64), `__init__` (37), `_prune` (34), `cancel` (20), `_prior_sources`
(16), `request` (16), `snapshot` (15), `reset` (15).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AN-01 | low | **Filtered subscription is built, read, and never written.** `_by_type`, `_by_dest` and `_by_source` are initialised (`:262-264`), written **only** by the three dead `subscribe_*` methods, read by `_deliver:499-501` (`handlers |= set(...)` for all three), iterated by `unsubscribe:320-323`, and cleared by `reset:583-585`. In production they are **permanently empty**, so `_deliver`'s three union lines are no-ops. The sole subscriber, `QtEventBridge:612`, calls plain `self._bus.subscribe(self._on_bus)` with no filter, and dispatch-by-type happens client-side in a `if mtype == … / elif …` switch (`main.py:967-975`). **Server-side filtering exists; the application does client-side filtering.** Harmless with one subscriber — every message goes to every handler by design. |
| AN-02 | **med** | **Bus cancellation cannot work in production.** `publish(msg, token=…)` (`:367`) stores a token into `_tokens`/`_tokens_by_corr` (`:422-424`), `_prune` bounds them (`:452-455`), `cancel()` looks them up (`:511-527`), and `CancellationToken` provides `cancel`/`wait`/`cancelled`. But **no production call site passes `token=`** — the only occurrence is `request`'s internal forwarding at `:547` — and `get_token`, the one accessor that would create one on demand, is dead. So `_tokens` is always empty, `EventBus.cancel()` always returns `False`, and `CancellationToken` is only ever constructed by the dead `get_token`. The module docstring lists *"Cancellation (via `CancellationToken`)"* at `:13` among the bus's features. `gui/tabs/dialogue_tab.py:2201`'s `worker.cancel()` is a `QThread` cancel and unrelated. |
| AN-03 | info | **`max_loop_depth = 6` (`:275`) is assigned and never read anywhere in the repository**, and `_depth()` (`:344`, 13 lines — the correlation-depth walker it would need) is dead. **This is a vestige, not a missing guard** — see below. Recorded explicitly so it is not "fixed" by wiring up a redundant limit. |
| AN-04 | info | **Six further small dead methods**, all 2–12 lines, zero tests: `publish_error` (`:550`, 12), `get_token` (`:358`, 7 — folded into AN-02), `reset_instance` (`:305`, 4), `Message.as_error` (`:168`, 3), `Message.set_text` (`:151`, 3), `CancellationToken.raise_if_cancelled` (`:230`, 3), `CancellationToken.is_cancelled` (`:227`, 2). `is_cancelled` being dead while the `cancelled` property is live is a duplicate-spelling pair: one form is used, the other is not. `reset_instance` being dead with zero tests is notable for a singleton — `tests/providers/test_singleton_identity_guard.py` and `test_singleton_identity.py` exist but neither calls it. |

---

## AN-03 is the one that had to be checked properly

`max_loop_depth` being unread *looks* like the sweep's most serious recurring shape: a named
safety limit that does nothing — `W-02`'s ungated `social_automation`, `AF-01`'s missing
dedup check, `AA-01`'s unwired host-contract guard. **It is not that, and reporting it as
such would have been wrong.**

`publish` (`:367-430`) implements **four independent guards**, each incrementing
`loop_violations`, each failing the message explicitly and emitting a typed ERROR:

```
1) :379  self-loop            — REQUEST_TYPES and destination == source
2) :392  ping-pong / cycle    — _prior_sources(msg): reject a destination that has
                                already INITIATED a request in this correlation chain
3) :400  edge replay          — (source, destination) already seen for this correlation
4) :410  dedup                — same message_id delivered before
```

`_prior_sources` (`:467-482`) walks the parent chain and is documented as *"Used by loop
prevention to reject pings back to an originator"*, with the design rationale at
`:386-391`:

> *"This structurally forbids Chat↔Manager request loops without blocking legitimate
> RESULT/event messages returning to the originator."*

**The structural guards subsume a depth counter.** A ping-pong A→B→A is caught by (2) the
moment the destination reappears as a source; an A→B→A→B is caught by (3). A depth limit
would have caught both too, but less precisely — it would also reject a legitimate chain
merely for being long, and it says nothing about *which* participant was pinged. So the
design moved from a depth heuristic to a structural one, and left `_depth` and
`max_loop_depth` behind.

**One theoretical gap, stated for completeness.** The guards bound *repetition*, not
*length*: a chain through N distinct sources with N distinct edges is never rejected,
whereas a working depth limit of 6 would have rejected it at the seventh hop. In practice
the bus's participants are module-level singletons and the source set is finite, so any
chain longer than the number of distinct sources must repeat one and is rejected by (2).
The bound is real, just implicit in the source set rather than stated in a constant.

---

## Verified as sound

**`publish` delivers outside the lock.** `:428-430` — *"deliver outside the lock to avoid
deadlocks from re-entrant publish"*. A handler that publishes in response to a message is
the normal case here (the coordinator's `_emit` runs inside a handler), so taking the lock
across `_deliver` would deadlock immediately. The comment names the hazard.

**ARCH-ENG-166's cleanup note (`:276-288`) records a real leak being closed.** *"`_inflight`,
`_delivered`, `_edges`, `_tokens` and `_tokens_by_corr` were only ever cleared by
`reset()`"* — five unbounded structures that grew for the life of the process. `_prune`
(`:432-465`) now bounds them by insertion order, and the comment at `:435` explains why
`_inflight` is treated differently from the others: it *"is additionally never pruned while
its [parent] is mid-flight"*, so pruning it cannot orphan a chain mid-walk.

**Every rejection is explicit and typed.** Each of the four guards sets
`msg.status = FAILED`, writes a specific `msg.error` string, and calls `_emit_error` — so a
rejected loop produces a typed `MessageType.ERROR` on the bus rather than silence. This is
`test_arch_eng_166_shared_state_concurrency.py`'s subject and the design is sound.

**`QtEventBridge` degrades safely.** The whole class is wrapped in `try/except` with
`QtEventBridge = None` (`:616-617`), so the bus module imports cleanly in a headless or
non-Qt context — which is what lets `agents/cognition/` and `app/earning_pipeline.py` use
the bus without a GUI.

---

## Re-verification

**The bus is genuinely wired — 49 references across 9 production modules.** Producers:
`agents/cognition/coordinator.py:39,159` (a `STAGE_REQUEST_TYPE`/`STAGE_RESULT_TYPE` map
from `CollaborationStage` to `MessageType`), `agents/cognition/ledger.py:7,16`,
`agents/runtime/agent.py:16,96`, `app/earning_pipeline.py:1448-1451` (P3, publishing
`OPPORTUNITY_UPDATE` *"instead of writing a JSON-file SharedContext mirror"*).
Consumer: `QtEventBridge` installed at `main.py:573-577` and `gui/tabs/dialogue_tab.py:1559`.

**A scan-error worth recording.** My first pass reported *"zero production call sites for
`subscribe` — and for all three filtered variants"*, which would have made AN-01 read as
though the entire subscription surface were dead. It is not: `QtEventBridge:612` subscribes
**from inside `comms.py`**, and my scan excluded the file under test. This is the ninth
form of reference the sweep has had to learn — after absolute imports, dict-valued
dispatch, attribute-access return types, relative imports, package-facade re-exports,
`from pkg import module as alias`, subpackage paths, and `from pkg import module` — and the
second time today that a plausible-looking negative came from the scan rather than the
code. The lesson is the same one `11s` recorded: **implausible results deserve the same
attention as plausible ones.**

**`COMMS_REDESIGN.md` is referenced by the module docstring and does not exist** in the
repository (`rglob` found no match). The redesign's rationale is therefore only recoverable
from the docstring itself and the P3/P4 comments at `app/earning_pipeline.py:1441` and
`main.py:573`. Worth noting for the fix list: a design document cited by the backbone
module has gone missing.

**`11c` / W-01 unaffected.** `app/earning_pipeline.py` is both a bus producer (`:1448`) and
the holder of the 289-line dead discovery island. The P3 comment shows the JSON
`SharedContext` mirror was replaced by the bus — and the replaced mirror's absence is not
reported as dead code, which is consistent with a completed migration rather than an
abandoned one.

---

## Assessment

Eleven dead of 34, but the shape is unusual for this sweep: **almost none of it is a
capability the application needed and did not get.** The bus is wired at both ends, its
guards are real, and its prune logic was hardened against a genuine leak.

The findings are, in order of importance:

1. **AN-02** is the one to act on — not because it breaks anything, but because the module
   *documents* cancellation as a feature and the feature can never fire. A maintainer
   building a cancel button on this bus would get `False` forever and no error. That is the
   same class of trap as `AA-01`'s unwritten-but-present guard: the interface looks
   available, so nothing questions it until it is depended upon.

2. **AN-03** is the one to record and *not* fix. A depth limit that is never read is
   indistinguishable, from a distance, from a safety limit that does not work — and the
   instinct to wire it up would make the code worse, because the structural guards are
   stronger and a depth counter would reject legitimate long chains. The honest disposition
   is to delete `_depth` and `max_loop_depth` as vestigial, or to document in the class why
   they remain.

3. **AN-01** is cost, not risk. Three dicts and three union operations per delivery, in
   exchange for a capability the single subscriber chooses not to use.

4. **AN-04** is cleanup.

The most useful thing this pass produced is the negative result on AN-03. The sweep has
found fifteen instances of *"mechanism correct, wired at one end only"*, and the natural
next step is to assume every unread safety constant is another instance. Checking this one
properly showed it was not — the guard exists, is stronger than the constant it replaced,
and the constant is the leftover. **Not every dangling safety constant is a missing
defence**, and the difference is only ever visible by reading what replaced it.
