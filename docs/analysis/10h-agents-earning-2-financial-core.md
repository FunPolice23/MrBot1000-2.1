# 10h — `agents/earning/` (part 2: the financial core)

> **G-05 RESOLVED in v2.1.125 (ARCH-ENG-283, AO-02 folded in).** The live order
> path now has a production caller: the Live Portfolio tab proposes an order
> through `LiveOrderProposalWorker`, the approval records
> `requested_by="live_trading"` and the exact intent, and
> `MainWindow._execute_approved_live_order()` re-assesses and submits it once.
> The service reads the canonical `MRBOT_ENABLE_LIVE_TRADING` flag; the unused
> `MRBOT_LIVE_TRADING_ENABLED` spelling is gone.
>
> **G-06 RESOLVED in v2.1.125 (ARCH-ENG-289).** `LiveTradingService` now accepts
> a durable `daily_equity_path`; `sync_portfolio()` records the first equity
> observation per exchange and UTC day, and `assess_order()` derives
> `daily_loss_pct` from `PortfolioSnapshot.day_start_equity_usd` when no caller
> supplies one. The Live Portfolio tab passes the production path. The breaker
> can now actually trip, and the re-assessment on execution uses the same
> producer.
>
> **G-07 RESOLVED in v2.1.125 (ARCH-ENG-295).** `TradingPolicy` now documents
> and enforces its mixed units: `max_position_pct`, `max_daily_loss_pct` and
> `min_confidence` are fractions (0..1); `max_volatility_pct`, `max_spread_pct`
> and `min_expected_profit_pct` are percent points. `__post_init__` rejects a
> percent-style value in a fraction field (for example `max_daily_loss_pct=2.0`)
> instead of silently disabling the breaker. The historical names are kept for
> API stability.

Substance analysis of the live financial modules. Every module in this area
except the two orphans recorded in `10g` has a live production consumer,
including the two that first looked dead (`airdrop_claimer` via `tasks.py:26`,
`gas_estimator` through it) and the 1,067-line `opportunity_lifecycle`, which is
driven from eight call sites across `earning_pipeline.py` and `main.py`.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| G-05 | **high** | **The entire live-trading execution path is unreachable in production.** Every call to a `LiveTradingService` method in the entire repository comes from a test. `execute_order` (`:300-358`) — the method that places a real order via `CcxtExchangeAdapter.create_order` — has 34 call sites and **not one is production**. `assess_order` (`:210-298`), the 88-line risk gate, is likewise test-only. The service is genuinely constructed and registered at `tab_feature_builders.py:2922`, so the object exists and the GUI shows Live Portfolio and Strategy Simulator tabs — but nothing drives it. This reads as deliberate safety, and it composes with D-03 (`10d-agents-core.md`): the `live_trading` feature flag gates *tab visibility only*, so the operator gets the trading surface without the flag gating any behaviour behind it. The honest characterisation is that live trading is **unfinished**, not that it is gated. |
| G-06 | med | **The daily-loss circuit breaker could never trip even if G-05 were fixed.** `assess_order` takes `daily_loss_pct: float = 0.0` as a parameter (`:211`) and compares it against `max_daily_loss_pct = 0.02` at `:240` and `:266`. `daily_loss_pct` is **never computed anywhere in production** — its only occurrences are the policy default, the parameter, the two comparisons, the returned dict, and one test that passes it explicitly. Every production call would therefore supply `0.0`, and `0.0 >= 0.02` is False, so the breaker is inert by construction. Unlike G-01's `AirdropClaimer`, this is not a case of a whole module being unreferenced: it is a single safety parameter that has no producer. The same is true of `daily_loss_pct` in the hard-block at `:266`, so this is not a scoring nicety — it is one of the four conditions that force `decision = "blocked"`. |
| G-07 | med | **The `TradingPolicy` `_pct` family mixes two incompatible units.** Three conventions coexist in one ten-field dataclass (`:73-82`): |

  | Field | Default | Compared against | Unit |
  |---|---:|---|---|
  | `max_volatility_pct` | `12.0` | `ticker["percentage"]` (`:204`) | percent points ✓ |
  | `max_spread_pct` | `1.0` | `(ask-bid)/mid * 100` (`:196`) | percent points ✓ |
  | `max_position_pct` | `0.05` | `notional / total_equity` (`:219`) | fraction ✓ |
  | `min_confidence` | `0.70` | `strategy_confidence` | fraction ✓ |
  | `min_expected_profit_pct` | `0.25` | `intent.expected_profit_pct` | **ambiguous** |
  | `max_daily_loss_pct` | `0.02` | `daily_loss_pct` | **undetermined** |

  The concrete mismatch is `min_expected_profit_pct`. Its subject field is
  populated as `9.9` in `tests/engineering/test_cycle_092_live_trading.py:267`
  — percent points, consistent with the two genuinely-percent siblings — while
  the default threshold is `0.25`. Read as percent points, a 0.25% expected-profit
  floor is near-meaningless, since almost any positive forecast clears it. Read
  as a fraction it is a 25% floor that rejects almost everything. **The two
  readings differ by 100× and the code does not say which is intended**; the
  `_pct` suffix is used for both conventions in the same dataclass. G-06's
  `max_daily_loss_pct = 0.02` sits in the same undetermined group. |
| G-08 | info | **`expected_profit_pct` and `strategy_confidence` are excluded from approval matching.** `_intent_differs` (`:476-482`) compares only order-shaping fields, and documents why: the scoring hints are *"advisory: they inform the risk decision, not the order itself, so a refreshed estimate must not invalidate a legitimate approval."* The reasoning is sound — the order is unchanged — and it is the security-conscious direction (an approval cannot be widened). But it does mean an approval granted at high expected profit survives a collapse in that estimate, and the same two fields *are* decisive for the risk score at `:252-257`. Defensible as written, recorded because the two roles are in tension. |

---

## Verified as sound — four documented fabrication incidents, each closed properly

This area has been systematically hardened against invented money, and the
remediations are documented with enough detail to be independently checkable.
That is rare and worth recording as a positive.

**ARCH-ENG-124 — `intelligence.py:28-41`.** The LLM's `effort` axis is a score
(0..1 after v2.1.95 normalisation), not a duration. It was passed straight into
`effort_hours`, so `0.1` became "0.1 hours" and the engine divided expected value
by it: on a $2,500 GitHub bounty with `effort_score=0.1` this produced
**`expected_hourly_value = $1,403.09/h`** with verdict *"attractive"*. The
comment names the exact figure, its propagation into
`got.OpportunityGraph._utility` (`0.1 * hourly`, feeding the ranking), and that it
**reached the operator**. Hours are now passed only when the opportunity states
them, else `None`. The fix also notes the old `or 0.5` fallback turned an honest
LLM `0` (trivial task) into `0.5`.

**ARCH-ENG-120 — `airdrop_scanner.py:195-211`.** A `$` figure in crypto news is
as often a market price as a payout: *"Bitcoin holds at $95,000 as airdrop season
begins"* booked **$95,000** as an airdrop value, which flowed into
`advertised_amount` / `expected_net_revenue` and produced a fabricated
*"attractive"* verdict in `opportunity_intelligence`. The fix requires
value-intent cues (`worth`, `valued at`, `reward`, `allocation`, `payout`, …),
and states the golden rule: *an amount a listing never attributed to the payout is
unknown (0.0), never a guess.*

**ARCH-ENG-118 / 119 — `discoverer.py:426-433`.** Both bounty fallbacks wrote a
hardcoded `10.0`. The comment says "unknown" while the code asserted a $10 prize
the issue never offered, feeding the canonical bounty board and therefore
validation, ranking, and the autonomous loop's economics. Now bounds-checked
against `MAX_BOUNTY_USD` and set to `0.0` when unstated.

**ARCH-ENG-064 — `opportunity_lifecycle.py:916-923`.** Inverted trust: the code
read `ev.get("verified")`, but `Evidence.to_dict()` emits `status` /
`verification_level` / `verification_method` and *never* a `verified` key. So a
genuine L5 on-chain payout reported `verified_revenue_usd() == 0.0` and was listed
in `unverified_payouts()`, **while a hand-written `{"verified": True}` dict
booked its full `expected_usd` as revenue.**

**`economic_accounting.py:1-19` encodes the firewall explicitly**, with five
non-negotiable rules stated in the module docstring: advertised payment is not
revenue; a successful submission is not revenue; a generated deliverable is not
revenue; revenue becomes realized only when appropriate payment evidence exists;
only VERIFIED evidence counts toward realized revenue. It imports
`PAYMENT_EVIDENCE_TYPES` from `payment_evidence.py`, so the shared vocabulary is
genuinely wired rather than duplicated.

---

## The sweep's recurring defect class, found in the codebase's own history

`opportunity_lifecycle.py:925-930` records ARCH-ENG-159 and is worth quoting for
what it says about this project:

> *"the legacy `if not status: return bool(ev.get("verified"))` branch was
> removed. ARCH-ENG-121 had already decided the policy is FAIL CLOSED … and
> `handlers._is_approved` closed the same branch — but that defence sat only at
> the CALLER. The gate itself still honoured the shape, so any other producer of a
> bare `{"verified": True}` dict booked [revenue]."*

That is the identical pattern this sweep has found independently in
`can_add_brain`, `CodePatchService.drain`, `register_module`, `CoderWorker`,
`SelfImprovementEngine`'s read side, and `DiscoveryScheduler.tick`: **the
mechanism is correct and the defence sits at one end of the wire only.** The
project has already named it, diagnosed it, and written down the lesson once —
in the context of financial evidence. Six months of later refactors have
apparently not propagated it, and G-05/G-06 are the same shape in a different
subsystem.

---

## Assessment

`agents/earning/`'s live core is in good shape and its financial-integrity work
is the strongest in the project. Four separate fabrication defects were found,
each traced to its propagation path, each fixed with an explicit rule rather than
a special case, and each documented well enough to audit. The semantic firewall
between advertised / expected / realized / verified is real and enforced through
a shared evidence vocabulary.

The weak point is not integrity — it is **reachability**. G-05 and G-06 together
mean that the one subsystem which could lose the operator money in real time is
the one subsystem with no production driver and an inert safety parameter. Both
are latent rather than dangerous today, and the correct reading is "unfinished"
rather than "miswired".

The units problem in G-07 is the one that would matter most if G-05 were ever
fixed, because it would then gate real orders. It should be resolved *before*
live trading is wired up, not after.