# 11B — `agents/earning/freelance_finder.py` depth pass (330 lines, 13 methods)

> **AU-01 RESOLVED in v2.1.125 (ARCH-ENG-263).** `_extract_skills` matched with
> plain `in`, so `ai` fired inside *email*, `sql` inside *MySQL*, `ios` inside
> *opinions*. Matching now uses `\b` anchors; phrases still match as phrases
> and `node` still matches `Node.js`. The same defect on the evaluation
> fallback (AX-03) was fixed in the same change.
>

Depth-pass #28 of 83. **0 dead of 13.** One low finding. The module's real interest is that
it solves the problem `11w` had to *defend against* — by not having the problem at all.

---

## Structure

```
L   1-11    module docstring
L  24-34    FreelanceOpportunity (dataclass, 10 fields, no methods)
L  40-65    DEFAULT_PLATFORMS (13) + TARGETED_SEARCH_TERMS (4)
L  67-70    __init__          L   72-105  search          (34)
L 107-132   _search_platform  L  134-150  _search_targeted (17)
L 152-176   _search_upwork    L  177-201  _search_fiverr   (24)
L 202-227   _search_reddit    L  228-252  _search_prolific (24)
L 253-276   _search_general   L  277-293  _extract_budget
L 294-304   _extract_skills   L  307-317  _extract_time
L 320-330   _opp_to_dict
```

Docstring: *"Real freelance opportunity hunter (v2.1 Path 1). Searches real freelance
platforms for live paying gigs using the web controller. **Does NOT submit or apply — only
researches and ranks opportunities.**"*

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AU-01 | low | **`_extract_skills:304` matches substrings without word boundaries**, so short tokens produce false positives. The test is `return [s for s in common_skills if s in text_lower]` — plain `in` on a lowercased string. Verified: *"Maintain the existing **email** campaign and **domain** records"* → `['ai']`; *"Design review needed; **chain**-of-custody documentation"* → `['design', 'ai']`. `'ai'` matches `maintain`, `email`, `domain`, `chain`, `detail`, `air`; `'ios'` matches `studios`, `scenarios`. Every multi-word skill (`"data analysis"`, `"machine learning"`) works correctly, so the defect is confined to the three- and four-letter entries. The `skills` list is displayed in the earning tab, so a gig titled *"Maintain the CRM"* is tagged `ai`. A `re.search(rf"\b{re.escape(s)}\b", …)` fixes it without changing behaviour for the rest. |

---

## The structural answer to the fabricated-payout problem

`11w` recorded `_stated_usd` — 35 lines whose entire purpose is to stop a dollar figure
parsed from a stranger's text becoming a trusted amount. This module needs **none of that**,
and the reason is a single type annotation:

```python
@dataclass
class FreelanceOpportunity:
    budget: str = ""              # :29  — a STRING
    source: str = "web_search"    # :33  — provenance as a field
```

**There is nowhere for a fabricated number to live.** The budget is stored as the text that
appeared in the search snippet, and `_opp_to_dict:325` passes `"budget": opp.budget` through
unchanged. Traced to the only consumer — `gui/tabs/earning_tab.py:344`, `search_result =
self.freelance_finder.search(query)` — and nothing in the tree converts `FreelanceOpportunity.budget`
to a number. The `.budget` matches elsewhere are different objects: `GraphBudget` (`got.py`),
`state.budget` (`opportunity_lifecycle`), `budget_usd` from authenticated adapters.

Compare `11w`'s `EarningOpportunity.estimated_usd_value: float = 0.0` — a numeric field that
had to be defended three times by ARCH-ENG-118/119 (which had defaulted it to `10.0`),
ARCH-ENG-212 (which derived it from `tvl_usd * apy_percent`), and `_stated_usd`'s four
rejection layers. **Same problem, same domain, opposite design.** Here the defence is that
the question cannot be asked.

**The honest names make the distinction explicit.** `_search_targeted:136` — *"Search a
marketplace family **without pretending it has an API adapter**."* And the module docstring
treats the missing integration as a precondition rather than a caveat:

> *"These are web-search targets, not authenticated integrations: **results remain
> human-review-only until a separate platform adapter and approval-gated action exists.**"*

That is ARCH-ENG-227's "practice copy before the real thing" discipline applied to a
*documentation* — the gate is named as something that does not exist yet, so nobody reads
the current state as permission.

`_search_targeted:149` also requires `r.get("title") and r.get("url")`, so **every emitted
opportunity has a traceable origin.** A result without a URL is dropped rather than
surfaced, which means the operator can always check the claim.

---

## Verified as sound

**The module refuses the submission path in its own name and docstring** — *"Does NOT submit
or apply"*. The `approval-gated action` the docstring names does not exist here, and
`11t`'s approval queue is not consulted because nothing needs gating: no money moves and no
external side effect occurs.

**`_search_platform:107-132` dispatches all 13 platform names and never returns `None`** —
eight named handlers, one `{"contra","freelancer","toptal","peopleperhour"}` group, and
`_search_general` as the fallback for anything else.

**Targeted searches use real marketplaces as query terms** (`:45-65`), with named
`sites:` operators across virtuals.io, fetch.ai, gitcoin.co, immunefi.com, code4rena.com,
sherlock.xyz and onlydust.io. That is a plausible way to find real bounty work without an
adapter, and saying so is more useful than a stubbed client.

**Caching is bounded at 10 minutes** (`:70`), and the finder takes its `WebController` by
constructor injection (`:67-68`) — which is why it is testable at all.

---

## Re-verification

**`11w` confirmed and used as the contrast.** `discoverer.py` had to defend a numeric field;
this file never had one. The two modules are adjacent in purpose — both turn scraped web text
into opportunity records — and they reached opposite designs. Recording both is more useful
than recording either alone, because the contrast is the argument: **a string field is a
stronger guarantee than a validated float**, because validation must be correct on every
path while a type cannot be.

**ARCH-ENG-212 consistent.** The rule that `estimated_usd_value` must be `0.0` when no honest
value is derivable applies with more force here, where no numeric field exists at all. The
`float(getattr(g, "budget_usd", 0.0) or 0.0)` conversions at `discovery_sources.py:99-100`
are legitimate precisely because those come from **authenticated** adapters — and the naming
distinguishes them (`advertised_amount` vs `estimated_net_value`).

**`10i` / opportunity_portfolio unaffected.** This module's output type is
`FreelanceOpportunity`, not the portfolio's `PortfolioEntry`, and nothing bridges the two —
the docstring's *"human-review-only"* is the boundary.

**`11x` / ARCH-ENG-164 pattern, inverted.** Here a *second* implementation of
freelance-gig-discovery does not exist and no `TOOL_DEFS` advertise `write_file`-style
mutations from this module.

---

## Assessment

One low finding, thirteen live methods, no structural problem.

**AU-01 is cosmetic but worth a one-line fix**, because `_extract_skills` is the only place
in this module that makes a claim about text without checking it carefully — and the rest of
the module is a model of checking carefully. A gig tagged `ai` because its title contains
*"m**ai**ntain"* is the kind of small wrongness that erodes trust in everything else the tab
displays. `re.search(rf"\b{re.escape(s)}\b", text_lower)` preserves correct behaviour for all
the multi-word skills and fixes the three-letter ones.

The more useful result is the contrast with `11w`. Two modules, same domain, same
requirement (*do not invent a number from scraped text*), and they solved it in opposite
ways: one by building a 35-line parser with four rejection layers and three ARCH-ENG fixes
behind it, the other by choosing `budget: str`. The second is not a less rigorous engineer
— it is the same rigor applied earlier, at the point where it is cheapest. **A type is a
guarantee; a validator is a promise.** When `11r`'s AJ-02 and the remaining findings are
turned into fixes, this is the shape to aim for: make the unsafe thing unrepresentable
before writing the check that catches it.
