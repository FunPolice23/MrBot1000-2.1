# 11v — `agents/earning/live_trading.py` depth pass (615 lines, 24 methods)

> **G-05 RESOLVED in v2.1.125 (ARCH-ENG-283, AO-02 folded in).** `assess_order()`
> and `execute_order()` now have a production caller: the Live Portfolio order
> form -> `LiveOrderProposalWorker` -> `approval` -> `MainWindow._execute_approved_live_order()`.
> The approval carries the exact `TradeIntent`; execution re-assesses against
> live state and is idempotent per approval id. The gate reads
> `feature_enabled("live_trading")` (canonical `MRBOT_ENABLE_LIVE_TRADING`), not
> the old `MRBOT_LIVE_TRADING_ENABLED` spelling. **G-06 remains open.**

Depth-pass #22 of 83. **4 dead of 24 by AST-based analysis** — the first scan said 1, and
the difference matters. Also the most consequential re-verification of the depth pass:
**ARCH-ENG-203's fix was applied at one call site, not all of them.**

---

## Structure

```
L   20-21    LiveTradingError    L   44-54   TradeIntent
L   25-30    PortfolioSnapshot   L   58-62   RiskAssessment
L   34-40    MarketSnapshot      L   66-82   TradingPolicy
L   85-128   CcxtExchangeAdapter (5 methods)
L  131-603   LiveTradingService (19 methods)
```

Docstring: *"Live portfolio and trading service with deterministic risk controls… reads
real exchange state through the optional ccxt package and **can submit real orders only
when the operator explicitly enables live trading and supplies an approved order
decision**. Model output may expla[in]…"*

Largest: `assess_order` (89), `execute_order` (59), `_check_still_matches_what_was_approved`
(41), `_require_approval_for` (35), `_intent_differs` (33), `_reassess` (31).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AO-01 | info | **The entire live-trading order path has no entry point.** By AST-based analysis (real `Call` nodes, comments and docstrings excluded) **`execute_order`, `assess_order`, `propose_order` and `_is_approved` have no call site anywhere in production.** The first pass reported only `propose_order` dead; `execute_order` was counted live because comments at `:282` and `:467` mention it. **A comment is not a caller.** No GUI code calls any order method — `tab_feature_builders.py:2963-3016` builds the Live Portfolio tab for `status()` and `sync_portfolio()` only. Roughly **310 lines** of the most safety-engineered code in the repository, with three adversarial test files, that cannot be entered. |
| AO-02 | **med** | **The service reads a different env variable than the feature flag that reveals its tab.** `feature_enabled("live_trading")` reads `MRBOT_ENABLE_LIVE_TRADING` (canonical) or `ENABLE_LIVE_TRADING` (legacy) — `agents/core/feature_flags.py:10,20`. `LiveTradingService.__init__:138-141` reads **`MRBOT_LIVE_TRADING_ENABLED`** with its own parser. These are two different variables. The GUI checkbox labelled *"Enable live trading and portfolio tabs"* (`tab_feature_builders.py:2463`) is bound to the `feature_enabled` spelling. **Ticking it would reveal the tab while leaving `live_enabled` false**, so every order would fail at `execute_order:324` with *"Live trading is disabled; no order was submitted."* The operator's own control would not enable the feature it names. |
| AO-03 | **med** | **ARCH-ENG-203's disagreement still exists, at a different call site.** `feature_flags.py:31-45` records that `app/action_pipeline.py` read `PIPELINE_ALLOW_SELF_IMPROVE` with `.lower() == "true"` while `feature_enabled()` read the *same variable* with `_truthy()`, which accepts `"1"` — so for `PIPELINE_ALLOW_SELF_IMPROVE=1` the gate was open on one path and closed on the other, and *"neither raised."* `action_pipeline.py:380` was fixed. **`gui/builders/tab_feature_builders.py:2535` was not** — it still reads `os.getenv("PIPELINE_ALLOW_SELF_IMPROVE", "false").lower() == "true"`. The GUI checkbox and the enforcement now disagree on the documented example variable. More broadly there are **27 raw boolean `os.getenv` parsers** of `ENABLE`/`TRADING`/`ALLOW` flags in production, outside `feature_flags.py`, across **at least five distinct truthiness vocabularies** (below). |

---

## AO-01 is a staged feature, not a defect — and it says so

Both gates are explicitly off in the operator's `.env`:

```
.env:62    MRBOT_LIVE_TRADING_ENABLED=false
.env:340   MRBOT_ENABLE_LIVE_TRADING=false
.env:341   MRBOT_ENABLE_CRYPTO=true
```

and `main.py:1540-1552` filters both "Live Portfolio" and "Strategy Simulator" out of
`tab_specs` unless `feature_enabled("live_trading")` — so on this machine the tab is not
built at all.

That makes AO-01 an **unfinished feature behind a double gate the operator has closed
twice**, under both the canonical name and the service's own. It is recorded as `info` and
it should **not** be "fixed" by wiring `execute_order` to something.

The point worth keeping is the ordering: **the safety machinery is complete and the entry
point is absent.** `propose_order` writes `payload={"intent": intent.__dict__}` into the
approval item; `_require_approval_for:454-458` requires exactly that payload and raises
*"Approval item does not name the order it authorized; no order was submitted"* without
it; `execute_order:326-327` consumes the approval once, after every gate passes. That loop
is closed and adversarially tested — `tests/engineering/test_cycle_092_review_fixes.py:170`
explicitly tests that a *second* `execute_order` with the same approval returns falsy.

It cannot fail closed, because it cannot be entered. That is a materially different
situation from `11g`'s `_tool_propose_code_patch` (advertised in `tools.py:59`, loop
enterable, approve hop missing) or `AJ-01` (constructed, never called). **This one is
inert at both ends.**

---

## AO-02 is ARCH-ENG-203's exact failure mode, for a different variable

`feature_flags.py:31-36` names the pattern precisely:

> *"This was a fifth independent parser for boolean environment values, and it disagreed
> with the one reading the SAME variable… Two components disagreed about whether
> self-improvement was permitted, over a spelling an operator would reasonably write.
> **Neither raised; the gate was simply open on one path and closed on the other.**"*

AO-02 is the same shape with a **different** variable, so it survived the fix:

| | variable read | parser |
|---|---|---|
| `feature_enabled("live_trading")` | `MRBOT_ENABLE_LIVE_TRADING` / `ENABLE_LIVE_TRADING` | `_truthy` |
| `LiveTradingService.live_enabled` | **`MRBOT_LIVE_TRADING_ENABLED`** | `in {"1","true","yes"}` (`:140`) |
| GUI checkbox → reveals the tab | `feature_enabled` spelling | `_truthy` |

Setting the canonical variable true reveals a tab whose service still reports
`execution_mode: "disabled"` (`status:154`). Setting `MRBOT_LIVE_TRADING_ENABLED` true does
the reverse — enables the service while the tab stays hidden. **Neither spelling alone
turns live trading on.**

Currently masked, because both `.env` values are `false` and AO-01 means no order can be
attempted regardless. It becomes live the moment AO-01 is wired, which is precisely why it
belongs in the same fix batch rather than a later one.

---

## AO-03 — 27 parsers, five vocabularies, one unfixed call site

The raw `os.getenv` boolean parsers found in production, grouped by the vocabulary they
accept:

| vocabulary | sites |
|---|---|
| `in {"1","true","yes"}` (default false) | `live_trading.py:140`, `discoverer.py:481,558`, `dialogue_tab.py:3647`, `tab_feature_builders.py:2492,2761,2776`, `web_discovery.py:71` |
| `== "true"` | **`tab_feature_builders.py:2520,2530,2535`**, `worker_llm_mixin.py:35` |
| `not in ("0","false","no","off")` (default **true**) | `circuit.py:27`, `provider_config_widget.py:29`, `worker_provider_mixin.py:327` |
| `not in ("1","true","yes")` (default true, inverted test) | `discoverer.py:213,219` |
| `.strip().lower()` truthiness | `tab_feature_builders.py:2901` |

**`tab_feature_builders.py:2535` is the unfixed half of ARCH-ENG-203.** For
`PIPELINE_ALLOW_SELF_IMPROVE=1`:

```
feature_enabled("self_improvement")                     -> True    (canonical _truthy)
tab_feature_builders.py:2535 checkbox .lower()=="true"  -> False
```

So the operator's checkbox renders **unchecked** for a value the enforcement layer treats
as **enabled**. That is the reverse of the disagreement ARCH-ENG-203 described — there the
gate was open where it should have been closed; here the control shows closed where it is
open. Either way the operator is misinformed, and nothing raises.

ARCH-ENG-203 fixed one call site. **That is the sweep's sixteenth instance of "mechanism
correct, wired at one end only"**, and the first where the fix was applied *after* the
defect was fully characterised — the docstring names the variable, the parser, both values,
and both answers.

---

## Verified as sound — and it is the best-designed money path in the codebase

**`_require_approval_for:436-441` states the trust rule and then implements it:**

> *"Fail closed unless a live APPROVED queue item names THIS order. **Every check here is
> derived from the queue's own record, never from a caller-supplied argument:** the payload
> is what the Approvals panel rendered for the human, so it is the only thing that can
> establish what was actually authorized."*

That is the ARCH-ENG-158 lesson (`11s`) generalised to trading: the caller cannot assert
its own claim, because the approval's `payload` is the artifact the human actually saw.
`_intent_differs:459-463` then compares the approved intent against the requested one and
refuses on any difference, with both sides rendered in the error message via `_describe`.

**One approval, one order.** `:464-467`: *"The item stays APPROVED forever, so without a
ledger a re-delivered decision replays the same live order N times against real funds.
The consume itself lives in `execute_order` so it runs exactly once, after every gate
passes."* The mechanism is `self._executed_approval_ids` (`:143-146`), with the comment
explaining that **the ledger — not the queue status — enforces once-per-approval**, because
queue status cannot express "consumed".

**Verification and consumption are deliberately separate** (`:318-321`):
`_require_approval_for` *verifies* and is called **up to twice**, because `_reassess:386`
re-derives the verdict from live exchange state between the two calls; the approval is
*consumed* exactly once, afterwards. That is the correct decomposition for a system where
the market moves between approval and execution.

**`execute_order` fails closed in five distinct places** before touching the adapter:
`_require_adapter()` (`:323`), `live_enabled` (`:324`), approval (`:326`), re-assessed
verdict (`:329-331`) — each raising a `LiveTradingError` whose message ends **"no order was
submitted"**. Every failure tells the operator, in those words, that nothing happened.

**`.env` carries the risk documentation with the settings** — `:74` *"Use
withdrawal-disabled API keys"*, `:76` *"Coinbase ccxt has no sandbox URL; use a read-only
key for live"*, `:61` *"Install requirements-live.txt only after reviewing exchange
permissions."*

---

## Re-verification

**W-02 CONFIRMED, not corrected.** `app/earning_pipeline.py:504` does gate
`social_automation` (`if source == "social" and not feature_enabled("social_automation")`) —
but `:504` falls inside the **289-line dead discovery island (L495-756)** that `11c`
recorded as W-01/W-02. The gate exists and is unreachable, exactly as W-02 stated.

**`11t` confirmed and extended.** All four `live_trading` approval-queue call sites from
`11t` (`:405`, `:446`, `:517`, `:532`) are accounted for: three are `find_by_id` reads and
`:517` is inside dead `propose_order`. `11t`'s verdict that this queue is the most
completely wired safety component in the repository holds — and this pass shows one of its
consumers is itself inert.

**`11p` / `provider_manager` unaffected.** The adapter reads exchange state through ccxt,
not through the provider registry; no allocation or brain placement is involved, so
ARCH-ENG-219 and M-03 are untouched.

**`paper_trading` is the live path.** `agents/earning/paper_trading.py:216,310-318` calls
`_execute_order` freely — which is consistent with the module docstring's *"intentionally
separate from `paper_trading`"* and with the Strategy Simulator tab being the one the
operator actually uses.

---

## Assessment

Four dead of 24, but only one is a finding about this module's code, and it is the mildest
of the three.

**AO-01 is the sweep's recurring defect at its most benign.** Everything the codebase does
well is present here — fail-closed ordering, payload-derived authority, once-per-approval
consumption, re-assessment against live state — and none of it can be reached. The honest
disposition is to leave it: the operator has the flag off in two places, the tabs are
hidden, and wiring an order-entry UI to 310 lines of unexercised-in-anger risk controls is
a product decision, not a defect fix. It is recorded so that whoever eventually builds the
order form knows the guards already exist and are tested — and so that AO-02 is fixed
*before* that day, not after.

**AO-02 and AO-03 are the real results, and they are one finding.** ARCH-ENG-203
identified the disease — boolean environment flags parsed independently in several places,
disagreeing without raising — and cured one patient. `feature_flags.py` is the canonical
parser; `tab_feature_builders.py:2535` is still the sick one, on the very variable the
docstring names. And `live_trading.py:139` is a **new** instance, with a variable name that
is not even in `_FEATURE_ENV`, so no amount of fixing `feature_flags.py` would catch it.

**The pattern across all three is that the canonical mechanism exists and callers route
around it** — `11t`'s queue is re-read correctly everywhere except the one consumer that is
itself dead; ARCH-ENG-203's parser is correct everywhere except two call sites. A fix that
touches `feature_flags.py` alone will not clear either finding. The durable fix is to make
`live_trading.py` read `feature_enabled("live_trading")` like every other capability, and
to move `tab_feature_builders.py:2535` onto it — and, more generally, to delete the raw
`os.getenv` boolean parsers rather than reconcile them, because twenty-seven sites across
five vocabularies is not a set anyone can hold in their head.
