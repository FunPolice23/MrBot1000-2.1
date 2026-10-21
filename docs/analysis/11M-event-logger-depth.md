# 11M — `agents/core/event_logger.py` depth pass (567 lines, 33 methods)

> **RESOLVED in v2.1.125 (ARCH-ENG-243).** BD-01 + BD-02 fixed by the
> operator's mixed disposition: `earning_event`, `safety_event` and
> `llm_spend_event` are LIVE -- wired at the earning pipeline's finalize
> step (lifecycle-EFFECTIVE values; a payment verified down shows revenue
> 0, never a fabricated win), the CostGuard's single trip decision and the
> filesystem write gate's refusals (one `_blocked_signal` helper, guarded
> so telemetry cannot alter the gate), and LLM-call completion in both
> brain adapters and the worker mixin (shared `estimate_call_cost` pricer,
> billable-only, matching the panel's "Cloud API cost only" note). With
> real spend events, `llm_spend_threshold_rule` can fire at last.
> `heartbeat_event` was REMOVED with everything that consumed it (the
> legacy manager heartbeat was already retired): the `EventType.HEARTBEAT`
> member, the Insights panel's tier/heartbeat rows and reader, and the
> `survival_tier_change_rule` -- whose construction crashed
> `add_default_rules()` at startup once the enum member went, proving the
> coupling was live. BD-03 (count_by_type / clear_in_memory / iso_ts
> dead utilities) remains info -- though `clear_in_memory` is now exercised
> by ARCH-ENG-243's behavioral tests. BF-03's seam (goal system reads
> `amount_usd` where the emitter's contract writes `revenue`) remains
> recorded. Regression tests:
> `tests/engineering/test_arch_eng_243_typed_events_wired.py`.

Depth-pass #39 of 83. **7 dead of 33** — and they are the **four typed emitters**, whose
payloads match a live consumer's reads exactly. This pass finds that **the Insights tab's four
data panels and the entire alerting-rules layer are inert for one reason.**

---

## Structure

```
L   32-40   EventLevel         L   58-122  Event (5 methods)
L   43-54   EventType (10)     L  127-549  StructuredEventLogger (27 methods)
```

Docstring: *"Unified structured event logger (Phase 6). Ties together: Evidence store,
Comms, **Safety events (cost cap, recursion, tool firewall, human gate)**, **Heartbeat ticks
(tier, credits, tasks executed)**, **LLM spend events**, System lifecycle events."*

Largest: `query` (100), `log` (30), `__init__` (24), `_write_event` (19), `_prune_old_files`
(15), `Event.to_dict`/`from_dict` (15).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| BD-01 | **med** | **The four typed emitters are dead, and everything that reads their output is live and empty.** `earning_event` (`:498`), `safety_event` (`:512`), `llm_spend_event` (`:525`) and `heartbeat_event` (`:538`) have no callers. A tree-wide search for any *emission* of `EventType.HEARTBEAT` / `LLM_SPEND` / `EARNING` / `SAFETY` outside this module returns **none** — the only matches are the three **queries** in `gui/tabs/earning_insights.py`. Yet that tab reads exactly the keys the dead emitters write (§ below), and it is built from `tab_specs` ("Insights", `11D`) with the logger injected at `tab_feature_builders.py:609`. **Four of its five panels are therefore permanently empty: spend `$0.00`, tier `unknown`, outcomes `[]`, safety incidents `0`.** |
| BD-02 | **med** | **The alerting-rules layer is inert for the same reason.** `agents/core/alerting.py` *"Sits between the event logger and the notification service"* — every rule filters on an event type and fires on a match. `survival_tier_change_rule` (`:162-168`) filters `EventType.HEARTBEAT`; the cloud-spend threshold rule (`:114-115`) filters `EventType.LLM_SPEND`. **Neither type is ever emitted, so neither rule can ever fire.** The operator gets no "Cloud LLM spend alert" and no "Survival tier change" notification, because the events those rules wait for do not exist. |
| BD-03 | info | **Two small utilities dead:** `count_by_type` (`:422`, 5 lines) and `clear_in_memory` (`:434`, 7 lines); plus `Event.iso_ts` (`:121`, 2 lines), an unused property alongside the live `to_dict`/`from_dict`. `clear_in_memory` is the more interesting of the three — `11u`'s AN-03 found `EventBus.reset_instance` dead for the same reason (a cache-reset affordance written alongside the cache and never used). |
| BD-04 | info | **The Insights tab reads a key the emitter does not write.** `earning_insights.py:447` reads `details.get("status", "completed")` from an `earning` event, but `earning_event:506` writes `{action, revenue, cost, platform, success}` — no `status`. The `default=` hides it, so every outcome row would render `"completed"` regardless of the real outcome. Harmless today (no events), and it would silently misreport the moment BD-01 were wired without this also being fixed. |

---

## The producer/consumer payloads are a matched pair

This is what makes BD-01 a designed-but-unwired system rather than four forgotten helpers:

| dead emitter | writes `details` | live reader | reads |
|---|---|---|---|
| `llm_spend_event:532` | `{model, provider, tokens, **est_usd**}` | `earning_insights:411` | `details.get("**est_usd**", 0.0)` |
| `heartbeat_event:545` | `{**tier**, credits, tasks_run, errors}` | `earning_insights:416` | `details.get("**tier**", "unknown")` |
| `earning_event:506` | `{action, **revenue**, cost, **platform**, success}` | `earning_insights:445-446` | `details.get("**platform**", …)`, `details.get("**amount**", details.get("**revenue**", 0))` |
| `safety_event:519` | `{gate_type, **blocked**, description}` | `earning_insights:460` | `details.get("**blocked**")` |

**Every key the consumer reads is a key the producer writes.** These two sides were designed
together — the emitters exist precisely to feed this tab — and the only missing piece is the
calls.

Note the inverse of `11F`'s AX-01. There, fifteen readers were dead and their tables empty
(here be dragons). Here, **four producers are dead and their consumers are live and empty.**
Same underlying shape — *the two ends are not connected* — and the same fix-ordering rule
applies in reverse: **wiring the producers here is safe and useful**, because unlike
`_step12_verify` or `run_audit`, these emitters fabricate nothing. They report what the caller
tells them, and the callers would be the real subsystems.

---

## BD-02 — the alerting layer is the more consequential half

`alerting.py`'s docstring is explicit about its role:

> *"Sits between the event logger and the notification service: Each rule filters events by
> type/source/level; on a matching event, the rule evaluates a condition; if the condition
> fires, the rule emits a notification and/or a metric update. Rules are configurable: **spend
> thresholds, tier change alerts, safety-block alerts, pending-approval aging, earning
> milestones**."*

The rules themselves are well-built. The cloud-spend rule (`:114-128`) is careful in a way
worth crediting: it filters to `EventType.LLM_SPEND` only, skips non-cloud providers (*"Local
/ free provider — skip counting toward the cloud budget"*, `:119`), maintains a rolling window,
and sets `fired_in_window` so a sustained overspend alerts **once** rather than every event.
`on_fire:130-147` publishes a notification whose message states the exclusion (*"Local model
usage is excluded from this budget"*) rather than leaving the operator to infer it.

**None of it can run.** `condition()` returns `False` at the first line for want of an event.

That matters more here than a missing dashboard would, because of what these rules are for.
`safety-block alerts` and `pending-approval aging` are the notifications an operator would
want when something is going wrong — and `11t`/`11H` established that this codebase's approval
surface is fully wired and operator-facing. **The alerting exists to tell the operator that the
approval queue is stuck or a gate is firing, and it is watching for events that do not exist.**

---

## Verified as sound — the logger itself is heavily used

This is emphatically **not** a dead module:

| method | production callers |
|---|---|
| `error` | **448** |
| `query` | **334** |
| `info` | 81 |
| `warning` | 88 |
| `critical` | 25 |
| `log` | 115 |
| `instance` | 112 |
| `recent` | 63 |

`StructuredEventLogger.instance()` is wired at `main.py:491` with `on_log` connected at `:536`,
and injected into `earning_insights` at `tab_feature_builders.py:609`. `query` is a 100-line
filtering API consumed from `base_worker.py`, `big_brain.py` and dozens of other sites.

**So the finding is precisely scoped:** the *generic* logging path is one of the most-used
surfaces in the codebase, and the *typed convenience emitters* — the ones that would make the
logger "unified" in the sense its docstring promises — are the dead part. The module's six
promised sources reduce to one (system lifecycle, via `main.py`'s direct `info`/`error` calls).

**`reset_singleton` has three callers** (`alerting.py:382`, `notifications.py:73`,
`approval.py:174`) — the test-and-reset affordance exists and is used, which is the opposite of
`11u`'s `reset_instance`. `_prune_old_files` (15 lines) and `_maybe_rotate` are live internal
rotation machinery.

---

## Re-verification

**`11t` extended (BD-02).** `11t` recorded `alerting.py:243-268` as an approval-queue consumer
and described its "queue-backed alerts". This pass finds that its *rules* — the part that
raises notifications — are all keyed on the four unemitted event types. `11t` saw the consumer
half; the producer half was never checked.

**`11D` supplied the ground truth.** "Insights" is in `tab_specs` (`main.py:1526`) and receives
its logger at `tab_feature_builders.py:601-609`, so the consumer is genuinely wired.

**`11I` / `11J` pattern, inverted.** `11I`'s BA-01 is a dead method that must stay dead; BD-01
is four dead methods that are safe to wire. The distinction is exactly what `11B` established —
`budget: str` could not be misused because there was nowhere to put a number; `earning_event`
cannot be misused because it reports what its caller passes and its consumers read only those
keys.

**`11r` / AJ-02 restated — and this one gets it right.** `earning_insights.py` wraps three of
its four query blocks in `try/except Exception: pass` (`:420-421`, `:450-451`, `:467-468`). That
is the silence `11t`'s AM-02 criticised in `_maybe_persist` — but here it is arguably
defensible for a *dashboard* (a display panel should not raise on the GUI thread). The gap is
that it also swallows **the safety-incidents query** (`:454-468`), where silence is less
defensible. Worth noting in the fix list alongside AM-02 rather than as a new finding.

---

## Assessment

Seven dead of thirty-three, and the finding is that **a monitoring system is built on both ends
and not connected in the middle.**

BD-01 and BD-02 are one finding seen from two places, and the place that matters is BD-02. The
Insights tab showing four empty panels is a cosmetic problem. **The alerting rules not firing
is not** — those rules exist to tell the operator that a safety gate is blocking, that cloud
spend is over budget, or that an approval has been pending too long. Each is a thing that could
go wrong in a system whose safety architecture `11t`, `11z` and `11v` spent three passes
documenting, and each now fails silently.

**The fix is four call sites, and they are the safe kind.** The distinction this sweep has
kept drawing applies here in reverse of `AJ-02`/`AN-03`/`AQ-01`: wiring these emitters
introduces no fabricated data and no unverified authority. They are reporters. The operators
that would call them are identifiable — `safety_event` from the gate that `11k`/`11t` verified,
`llm_spend_event` from the cost tracker, `heartbeat_event` from the autonomous loop, and
`earning_event` only where a real outcome exists (`11F`'s AX-01 caveat: **not** from a parsed
figure — the field would have to come from verified evidence, or the panel would reintroduce
exactly the fabrication ARCH-ENG-212 removed).

**BD-04 is the item to fix in the same pass.** If `earning_event` is wired without adding a
`status` key, every outcome row will read `"completed"` — a panel that reports success for
outcomes whose status was never recorded. That is the *eighth* instance of this sweep's
newest class, arriving as a default parameter: `details.get("status", "completed")` asserts a
completion that no producer writes.
