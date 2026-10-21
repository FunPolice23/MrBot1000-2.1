# 11L — `agents/knowledge/help_catalog.py` depth pass (575 lines, 2 functions)

> **RESOLVED in v2.1.125 (ARCH-ENG-241).** BC-01 fixed: the "Browse Root"
> entry now reads Web Browser, all 24 `tab_specs` labels are covered — the
> optional ones each name their canonical env key (`MRBOT_ENABLE_*`) — the
> four phantom grounding citations were replaced with real paths
> (`agents/cognition/personas.py`, `gui/builders/tab_feature_builders.py`,
> `gui/tabs/chat_tab.py`, `gui/builders/tab_builders.py`), and the mirror
> now has an executable check:
> `tests/engineering/test_arch_eng_241_help_catalog_tracks_main_tabs.py`
> parses main.py's `tab_specs`/`optional_tabs` and fails on drift, with the
> stdlib-only importability contract asserted. BC-02 (the Approvals entry)
> was created in the same pass; BC-03 (substring lookup, no word
> boundaries) remains a recorded info finding. The generalisation stands:
> *a hand-maintained mirror with no executable check is a claim, not a
> mirror* — and this one is now backed by a check.

Depth-pass #38 of 83. **0 dead of 2.** ~540 of the 575 lines are data. This is the **seventh**
instance of the *"mechanism is correct and the content is wrong"* class, and the first where
the surface is the one an operator reads *for the purpose of trusting what the app does*.

---

## Structure

```
L   1-33    module docstring — grounding claim + exposed API contract
L   35-537  FEATURES: 53 entries (each a dict: feature/category/description/example)
L  539-557  lookup(keyword)      (19 lines)
L  560-571  catalog_text()       (11 lines)
```

Docstring: *"A dependency-light, read-only catalog of the app's major features/controls so that
a help panel, in-app search box, or automation can answer **'what does this do?'** without
importing the GUI. **Every entry is grounded in the real code.**"*

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| BC-01 | **med** | **The catalog has drifted from the UI it documents, and nothing detects it.** It contains an entry for **"Browse Root / file browser tab"** — the real tab label is **"Web Browser"** (`main.py:1523`, per `11D`). It omits **14 of the 24** real `tab_specs` labels: Model Library, Approvals, Registration, Web Browser, Insights, Opportunities, Social Activity, Self-Improvement, Autonomous Learning, Live Portfolio, Strategy Simulator, Analytics, Reputation, Data Explorer. And the docstring's grounding list cites **four files that do not exist**: `gui/tab_builders.py` (the real path is `gui/builders/tab_feature_builders.py`), `gui/chat_tab.py` (`gui/tabs/chat_tab.py`), `gui/model_switcher.py`, and `agents/personas.py`. **There are zero tests referencing `help_catalog`.** |
| BC-02 | **info** | **"Approvals" has no catalog entry.** `11t` established `HumanApprovalQueue` as the most completely wired safety component in the codebase and `11H` that it has two dedicated operator surfaces; this 53-entry catalog covers Payments, Earnings, Wallet & crypto management and Settings, and says nothing about the tab where the operator approves irreversible actions. |
| BC-03 | info | **`lookup:550-556` matches substrings without word boundaries** across feature/category/description — `"gpu"` matches "input", `"ai"` matches "maintain". Third instance of this family after `11B`'s AU-01 and `11F`'s AX-03. Materially lower severity here: for a search box over 53 curated entries a false positive is a nuisance, not a wrong tag. |

---

## The drift, measured

| | count |
|---|---|
| real tabs in `main.py` `tab_specs` | **24** |
| tabs the catalog describes | 10 |
| …of which named incorrectly | 1 (`Browse Root` ≠ `Web Browser`) |
| real tabs with no entry | **14** |
| catalog entries | 53 (the rest are controls and flags, not tabs) |
| files cited as grounding that do not exist | **4** |
| tests referencing the catalog | **0** |

The 53 entries are not all tabs — most are individual controls and llama.cpp flags
(`Flag: Flash Attention`, `Flag: KV cache in system RAM`, …), and those are plausibly accurate.
**The tab-level entries are where the drift is**, because tab labels are the one thing in this
catalog that `main.py` owns as a single list.

The concentration matters: the 14 missing tabs are almost exactly the **optional** ones —
Social Activity, Self-Improvement, Autonomous Learning, Live Portfolio, Strategy Simulator —
plus Approvals, Registration, Insights, Opportunities, Analytics, Reputation, Data Explorer,
Model Library, Web Browser. So the catalog describes the always-on tabs reasonably and says
**nothing about the capability-gated ones**.

That is the worst possible drift direction for this particular artifact. The optional tabs are
the ones behind `feature_enabled(...)` flags (`11v`'s AO-02, `11D`'s tab filtering), so they are
where an operator is most likely to need an explanation of *why a tab is missing* or *what
turning the flag on does* — and the catalog, which is the natural place to look, cannot help.

---

## BC-01 is the seventh instance, and the class is now worth naming formally

| | surface | says | truth |
|---|---|---|---|
| 1 | `provider_models.py:490` | "offline, bad key, or no models API" | needs neither — missing `return` |
| 2 | `live_trading.py:139` | tab visible ⇒ live enabled | two env variables |
| 3 | `tab_feature_builders.py:2535` | checkbox unchecked | self-improvement **enabled** |
| 4 | `safety_tools_tab.py:568` | clean APPROVED row | routing silently failed |
| 5 | `earning_tab.py:480` | "Send 5 ETH to 0xAAA…" | the address is a literal |
| 6 | `discoverer.py` `discover_all` | *(stdout only)* | opt-in gates invisible |
| **7** | **`help_catalog.FEATURES`** | **"Browse Root / file browser tab"** | **the tab is "Web Browser"; 14 tabs absent** |

The first six were all cases where a *mechanism* reported on content it was not fed correctly,
or reported nowhere. **The seventh is different in kind: there is no mechanism at all.** The
catalog is a hand-maintained transcription of the UI, and a transcription drifts.

**And it drifts silently, because nothing checks it.** The docstring makes an explicit claim —
*"Every entry is grounded in the real code"* — and **zero tests** verify it. That is the same
gap ARCH-ENG-206/207 addressed for deletions (`11G`'s AY-04: *"A deletion with no executable
check is a claim, not a change"*), applied to a hand-maintained mirror: **a hand-maintained
mirror with no executable check is a claim, not a mirror.**

---

## Verified as sound

**The module honours its importability contract, which is a real constraint.** `:19-20`:
*"This module is IMPORTABLE STANDALONE: stdlib only, no Qt, no project deps, no import of gui/
or any agents module at import time. **Keep it that way**"* — and the file's only import is
`from typing import List` (`:36`). `help_dialog.py:34` imports it without pulling in Qt-bound
modules, so the "answer what does this do without importing the GUI" purpose genuinely works.

**The consumer has an honest failure mode.** `gui/panels/help_dialog.py:40-41` synthesises a
visible entry when the catalog cannot be loaded:

> `"description": f"Could not load agents/help_catalog: {e}"`
> `"example": "Check that agents/help_catalog.py exists and imports."`

**A broken help surface reports itself rather than rendering empty.** That is `11r`'s AJ-02
restated — *"report insufficient data rather than no problems found"* — applied correctly, and
it is why BC-01 is a drift finding rather than a breakage finding.

**`lookup` always returns a list** (`:543`, `:557`) and handles `None`/whitespace via
`(keyword or "").strip().lower()` (`:545`) — a search box that cannot raise on a bad input.

**`catalog_text()` is 11 lines** and exists so automation can consume the same data the panel
renders — a second consumer from one source, which is the right shape for this artifact even
though the first source is hand-maintained.

**`11x` / AQ-01 is invisible here, which is the finding.** Self-Improvement has no catalog
entry, so an operator reading help cannot learn that the tab is flag-gated or that
`PIPELINE_ALLOW_SELF_IMPROVE` controls whether the agent may modify its own code — the exact
setting `11D`'s AW-02 found to be displayed wrongly in the Settings tab.

---

## Re-verification

**`11D` supplied the ground truth.** `11D` extracted `main.py`'s 24-entry `tab_specs` and
established that "Live Portfolio" and "Strategy Simulator" are gated on `live_trading`, and
"Social Activity" / "Self-Improvement" / "Autonomous Learning" on their own flags. Every one of
those five is in the catalog's missing set.

**`11v` AO-02 extended.** AO-02 found the live-trading feature flag reads a variable the tab
filter does not. The catalog's silence on Live Portfolio is a third layer of the same
invisibility — the flag is mis-wired, the tab may be hidden, and the help does not mention it.

**`11t` / `11H` extended (BC-02).** Both established the approval surface as fully wired and
safety-critical. The help catalog omits it.

**`11B` / AU-01 and `11F` / AX-03 extended (BC-03).** Third instance of substring matching
without word boundaries, now in three files.

---

## Assessment

Zero dead of two, and a **med** finding that is entirely about maintenance rather than logic.

**BC-01 is not a one-line fix**, and the reason is the point. Adding the 14 missing tabs is
easy; what stops the next drift is a test. The natural one is small and mechanical: assert
that every label in `main.py`'s `tab_specs` appears as a `category` or `feature` in `FEATURES`.
That would have caught "Browse Root" immediately, would have caught the tab additions, and
would make the docstring's *"grounded in the real code"* claim an executable check instead of
an assertion — which is the standard `11G`'s AY-04 identified as already applied to deletions
and never extended to this mirror.

**BC-02 is the entry worth adding first.** Of the fourteen missing tabs, Approvals is the one
where the cost of not knowing is highest: it is where a human authorises irreversible actions,
and an operator who cannot find an explanation of it is relying on `11H`'s tooltips alone.

**The class is now formally nameable, and that is the sweep's most portable result.** Seven
instances, and the generalisation is:

> **A hand-maintained description of a system that can change will drift, and it drifts
> silently unless something executable checks the correspondence.**

The codebase already applies the fix to deletions (`11G`) and to env-var parsing (`11v`'s
AO-03: 27 sites, one canonical parser). What it has not applied is to *documentation of
structure* — the help catalog's tab list being the clearest case, and the one an operator is
most likely to consult precisely when something is not behaving as expected.
