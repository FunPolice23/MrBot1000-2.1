# 11w — `agents/earning/discoverer.py` depth pass (612 lines, 12 methods)

> **AP-02 / W-01 DISPOSITION EXECUTED in v2.1.125 (ARCH-ENG-285).** The
> superseded 262-line discovery island in `app/earning_pipeline.py` is deleted,
> not revived; `agents/discovery/` remains the live path. The three gates that
> lived only in the island were moved to the live source classes under
> ARCH-ENG-286, so this doc's disposition is now the implemented state.
>
> **AP-01 RESOLVED in v2.1.125 (ARCH-ENG-266).** The 15 bare `print()` calls are
> gone: counts and fetch failures go through the module logger, and the two
> switched-off discovery features now raise a one-per-process
> `NotificationService` notice naming the enabling variable.
>

Depth-pass #23 of 83. **0 dead of 12 — no findings in this module's code.** Its interest is
that it is where the project's central discipline is applied to *untrusted scraped text*,
and it supplies the disposition for W-01, the largest dead island in the sweep.

---

## Structure

```
L   93-127   _stated_usd              (module function, 35 lines)
L  131-144   EarningOpportunity       (dataclass, 10 fields)
L  147-603   EarningDiscoverer        (11 methods)
```

Docstring: *"Dynamic earning opportunity discovery. Scans RSS feeds, social media, and
public platforms for earning opportunities that pay $1+ in USD or crypto."*

Largest: `_discover_github_bounties` (90), `_discover_referral_programs` (82),
`_discover_reddit` (70), `_discover_faucets` (47), `discover_all` (39).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AP-01 | low | **All observability is bare `print()`.** 15 `print()` calls and **no logging or notification import anywhere in the file.** `discover_all:191-220` reports the per-source yield — `Found 7 from Reddit`, `Found 0 from Twitter (bearer token not configured)`, `Found 0 from referral programs (opt-in disabled)` — to stdout only. The application has an in-app Live Log (`main.py:log_signal` → `_safe_log` → `_append_log`, per `11a`), and every other module routes through it. **The two opt-in gates an operator might want to enable — `ALLOW_REFERRAL_DISCOVERY` and `ALLOW_FAUCET_DISCOVERY` — announce their disabled state to a console the operator does not have open.** |
| AP-02 | info | **W-01 now has a disposition.** The 289-line dead discovery island in `app/earning_pipeline.py` (L495-756, recorded as W-01/W-02 by `11c`) duplicates orchestration that `agents/discovery/` performs properly and *live*: `discovery_engine.py:57` `discover_all`, `discovery_port.py:50,55`, `discovery_sources.py:436`. Both island call sites — `earning_pipeline.py:593` (`SocialEarningPlatform().discover_all()`) and `:735` (`EarningDiscoverer().discover_all()`) — sit inside the dead range; the live caller is `DynamicSource._discover:436`. This is the **contrast** to `11p`'s two `_detect_gpus`, where the newer module documented its relationship to the older one; here the older island has no stated relationship to the newer path at all. |

---

## `_stated_usd` — the honesty discipline applied to untrusted text

`11o` recorded the project's central rule — *never let an unverified assertion become
accepted fact* — appearing in three domains: monetary (`economic_accounting.py`'s seven-way
firewall), epistemic (`opportunity_analysis.py`), and hardware (`big_brain.py`'s
`_hardware_line`). **This is the fourth, and the hardest: the assertion is a dollar figure
parsed out of a stranger's Reddit post.**

```python
def _stated_usd(text: str) -> float:
    """USD figure the listing attributes to its own payout, else 0.0.

    0.0 means UNKNOWN — never a guess. Per the financial-truth rule used by
    v2.1.68/93/94: an amount a listing never attributed to a payout is unknown,
    and a producer that cannot establish one must emit 0.0 rather than a
    default. The magnitude window is the last line of defence: even a
    well-attributed figure outside it is treated as a mis-parse, not a prize.
    """
```

**The decision procedure is layered, and each layer rejects for a different reason** —
which is what makes it a defence rather than a heuristic:

| Layer | Rule | Rejects |
|---|---|---|
| `_MIN_STATED_USD`–`_MAX_STATED_USD` (`:89-90`) | `$1.0`–`$100,000.0` | implausible as a posted payout — *"treated as a mis-parse, not a prize"* |
| `_PRICE_CONTEXT_CUES` (`:113-114`) | `sale price`, `listed at`, `worth of`, … | *"the figure quotes a price"* |
| `_COST_CONTEXT_CUES` (`:115-116`) | `fee`, `deposit`, … | *"the figure is money the worker pays"* |
| `_MARKET_SUBJECT_RE` + `_COIN_ADJACENCY_CHARS` (`:117-121`) | `btc`, `bitcoin`, `eth`, … within 20 chars | *"`…Bitcoin $95,000` prices the coin"* |
| `_PAYOUT_CUES` (`:123-126`) | `pays`, `bounty`, `reward`, `per hour`, … | accepts — **before or after** |

**Two design choices carry most of the weight.**

First, **the coin-adjacency carve-out at `:119-120`**: if a coin name sits within 20
characters of the figure *and* no payout verb intervenes, the figure prices the coin
instead. The comment gives the case that motivates it — *"a payout verb in between (`ETH
stakers claim $500`) keeps it a payout"* — so the exception is stated rather than left
implicit.

Second, **the cue is checked in a 45-character window before and 32 after** (`:66-68`),
because *"job prose puts the cue on either side (`pays $1,500` / `$25 reward for the
survey`)"*. A forward-only check would miss half the phrasings.

**`_MIN_STATED_USD`/`_MAX_STATED_USD` deliberately share a ceiling with a sibling
producer** (`:85-88`): *"Same ceiling the sibling GitHub-bounty producer uses
(`MAX_BOUNTY_USD`) **so the two do not disagree** about what an implausible figure is."*
That is the same discipline as `11p`'s two `_detect_gpus` — a cross-module constant
agreement, asserted in a comment, so neither producer drifts. And `_COIN_ADJACENCY_CHARS`
(`:83`) explicitly mirrors `airdrop_scanner.COIN_ADJACENCY_CHARS` for the same reason.

---

## Three ARCH-ENG fixes hardened exactly this field

The test names tell the history, and it is a history of the same defect recurring:

**ARCH-ENG-118/119** — `tests/engineering/test_arch_eng_118_119_no_fabricated_payout.py:11`:
*"`EarningDiscoverer._discover_github_bounties` defaulted to `10.0` both when [no amount was
stated]"*, and `:190` asserts `opps[0].estimated_usd_value == 0.0`. **A default of 10.0
where the truth was unknown** — precisely the fabrication `_stated_usd` now refuses.

**ARCH-ENG-212** — `test_arch_eng_212_no_fabricated_payout.py:7` reconstructs the removed
expression `estimated_usd_value = opp.tvl_usd * (opp.apy_percent / 100) * 0.01`, and `:36`
states the rule: *"There is no honest value derivable from this data."* The comment left at
`app/earning_pipeline.py:664-691` preserves the same reasoning — *"It mattered because
`estimated_usd_value` feeds the earning pipeline's scoring"* — and `:691` is now
`estimated_usd_value=0.0`.

**ARCH-ENG-123/124/125** — `test_arch_eng_123_124_125.py:22` imports `_stated_usd` directly
and exercises the parser's branches.

**The end state is a field that cannot hold a fabricated value.** `EarningOpportunity`
(`:131-144`) declares `estimated_usd_value: float = 0.0` — unknown, not a guess — and
downstream consumers read it with the same care:

- `agents/earning/opportunity_lifecycle.py:118` — `state.budget = getattr(opportunity, 'estimated_usd_value', 0.0) or 0.0`
- `agents/earning/tasks.py:38` — `estimated_value_usd=opportunity.estimated_usd_value`
- `gui/builders/tab_feature_builders.py:3294` — `expected_value=float(getattr(opportunity, "estimated_usd_value", 0.0) or 0.0)`

All three use the `or 0.0` idiom, which converts both a missing attribute and a `None`
into the unknown sentinel. And the lifecycle's budget sits behind ARCH-ENG-159's evidence
floor (`test_arch_eng_159_lifecycle_evidence_floor.py`), so a parsed figure cannot become a
recorded outcome by that route either.

---

## Verified as sound — the two opt-in gates

**Referral programs and faucets are opt-in, off by default, and say so in the source.**
`_discover_referral_programs:481` and `_discover_faucet:558` each begin with
`if os.getenv("ALLOW_…_DISCOVERY", "0").strip().lower() not in ("1","true","yes")` — and
`discover_all:210,216` labels them *"opt-in only — disabled by default"* in comments.

**This is a fifth instance of the AO-03 vocabulary problem**, and worth naming as a
consistency point rather than a new finding: these two use the *inverted* test
(`not in (...)`) with a `"0"` default, while `live_trading.py:140` and `discoverer`'s own
`_stated_usd`-adjacent peers use `in {"1","true","yes"}`. The two forms are equivalent for
the values tested, but the spread is the point AO-03 made — and here at least the
discoverer's own gates are the conservative ones, defaulting closed.

---

## Re-verification

**W-01 / W-02 disposition supplied (AP-02).** The dead island's two discovery call sites
(`:593`, `:735`) are superseded by `agents/discovery/`, which is live and which
`discovery_sources.py:1-13` documents as the deliberate migration:

> *"Each legacy client (Upwork, Fiverr, social, airdrop, DeFi, microtask, content, and the
> legacy EarningDiscoverer 'dynamic' path) is wrapped in a `BaseOpportunitySource` that
> emits the canonical structured `Opportunity`. Behavior is preserved… **These sources are
> registered with the DiscoveryEngine by EarningPipeline (T5), so the core pipeline is
> untouched but the new model flows through.**"*

That last clause is the relationship `11p` found documented between the two `_detect_gpus`
implementations and did **not** find between this island and `agents/discovery/`. The island
is the "core pipeline untouched" half, and it is what should go.

**The wrapper preserves provenance explicitly** (`discovery_sources.py:9-10`): *"Provenance
is always set to `source::external_url` so the external origin stays identifiable (**an LLM
never invents these; they come from real client output**)."* That is the epistemic rule
applied at the boundary, and it pairs with `_stated_usd`'s refusal to invent a number from
the same text.

**`11c` / W-02's `social_automation` gate unaffected.** `earning_pipeline.py:504` remains
inside the dead island, as recorded.

**ARCH-ENG-124 unaffected.** `test_arch_eng_123_124_125.py` exercises this parser, and
ARCH-ENG-124's `effort_score` fix is in `agents/earning/intelligence.py:28-41` — a
different producer on the same honesty theme, and `11o` already confirmed
`big_brain.py` as its caller.

---

## Assessment

Zero dead of twelve, no functional finding, and two low/informational items.

AP-01 is worth fixing for a reason specific to this module rather than in general: the two
`opt-in disabled` messages at `:214` and `:220` are the **only** place the operator is told
that referral and faucet discovery exist and are switched off. Sending that to stdout means
the information is effectively unavailable — the operator who never opens a console never
learns the feature is there. `NotificationService` is already used by `agents/safety/
approval.py:11` in the sibling safety package, so the pattern is established.

AP-02 is the more useful result. **It closes W-01 with a disposition rather than leaving it
as "289 dead lines."** The sweep has had several instances of the two-`_detect_gpus` shape,
where a newer implementation documents its relationship to an older one and the older one
is kept as a degradation path. This is the same shape with the documentation on the *newer*
module's side and nothing on the older module's side — so the older one is not a fallback,
it is a duplicate. That makes the fix decision unambiguous: `earning_pipeline.py:495-756`
can go, because `agents/discovery/` is the live path and says so.

And `_stated_usd` is the best single artefact in the sweep for the principle the fix list
keeps needing. It refuses four distinct ways of turning a stranger's text into money —
a quoted price, a cost to the worker, a coin valuation, and an implausible magnitude —
accepts only when the listing itself attributes the figure to a payout, and emits `0.0`
when it cannot. **That is the standard every remaining finding should be measured against:**
not "can this produce a number" but "what would it take for something unverified to become
a number."
