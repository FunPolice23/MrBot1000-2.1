# 11D — `gui/builders/tab_feature_builders.py` depth pass (3898 lines, 67 methods)

> **G-05 + D-01 UI SURFACE WIRED in v2.1.125 (ARCH-ENG-283/281).** The Live
> Portfolio tab now builds an order request form and starts
> `LiveOrderProposalWorker`; the Management tab emits the reconciliation action
> wired to `MainWindow._reconcile_paid_evidence()`. The crypto toggle now gates
> the operator boundary (ARCH-ENG-281), and the live-trading toggle reads the
> canonical `MRBOT_ENABLE_LIVE_TRADING` spelling (ARCH-ENG-283).
>
> **AW-03 REFACTORED in v2.1.125 (ARCH-ENG-278).** `create_settings_tab` (997
> lines before AB-01's retirement, 870 after) is now a 98-line orchestrator over
> twelve `_build_*` section methods. Widget names and construction order are
> unchanged, so `save_settings` needed no edit; a structural test pins the
> orchestrator length, the exact call order, representative widget survival,
> and that no section was copied instead of moved.
>

> **PARTIALLY RESOLVED in v2.1.125 (ARCH-ENG-242).** AW-01 fixed: the
> Collaboration / Run Monitor tab is now wired into `tab_specs` (label
> "Collaboration", after Dialogue); its bidirectional goal bridges to
> Dialogue — which sat complete and dead on both sides — are live with it.
> The catalog gained a Collaboration entry in the same change:
> the ARCH-ENG-241 drift check makes the coverage test fail until it does.
> Diagnostics (the other 10s R-01 unwired tab) remains resolved by shim —
> its surface lives in DB Stats. AW-02 was fixed by ARCH-ENG-238. Remaining
> from this pass: AW-03 (`create_settings_tab`, 997 lines) and AW-04
> (two dead opportunity-tab helpers) stay recorded — structure findings,
> not wiring defects. Regression tests for wiring:
> `tests/engineering/test_arch_eng_242_collaboration_tab_reachable.py`.

> **PARTIALLY RESOLVED in v2.1.125 (ARCH-ENG-238).** AW-02 fixed: the
> self-improvement checkbox now reads `PIPELINE_ALLOW_SELF_IMPROVE` through
> `app.effects.env_bool` — the same canonical parser as the enforcement point
> (`app/action_pipeline.py:384`). `=1` now shows *checked* and the agent is
> indeed permitted; the display and the gate agree on every spelling.
> `PIPELINE_ALLOW_WRITE` keeps its inline parse by design — no other module
> reads it. AW-01 (the unwired Collaboration/Run Monitor tab) remains open.
> Regression tests: `tests/engineering/test_arch_eng_238_self_improve_checkbox_same_parser.py`
> (AST-based, with a pairing contract binding both readers of the variable).

Depth-pass #30 of 83. **4 dead of 67.** The second-largest file swept. Two of the four are
documented, correct migrations; the other two are real. It also confirms **AO-03 at the call
site**, with the operator-visible consequence spelled out.

---

## Structure

```
L  23-3895  FeatureTabBuildersMixin (67 methods)
```

Docstring: *"Feature-specific Qt tab builders."*

Largest methods: **`create_settings_tab` (997)**, `create_opportunities_tab` (229),
`create_file_browser_tab` (225), `create_social_activity_tab` (216),
`create_paper_trading_tab` (189), `create_db_stats_tab` (176),
`create_self_improvement_tab` (157), `refresh_diagnostics` (116),
`create_autonomous_learning_tab` (113), `create_logs_tab` (94).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AW-01 | **med** | **The Collaboration / Run Monitor tab cannot be reached.** `create_collaboration_tab` (`:226`, 41 lines) is not in `main.py`'s 24-entry `tab_specs` (`:1514-1539`) and has no other production caller — only `tests/gui/test_gui_smoke.py:321` asserts it *exists* (`hasattr`). It imports and constructs `gui/tabs/collaboration_tab.CollaborationTab` (`:237`), so a whole panel class is written, wired to the shared `DualBrainCoordinator` (`:250`), and never instantiated. Its own docstring describes intended behaviour — *"Owns the shared `DualBrainCoordinator` … so Chat/Dialogue/monitor all observe the same collaboration ledger … a down server degrades to a FAILED run (never blocks or crashes)"* — none of which is reachable. |
| AW-02 | **med** | **AO-03 confirmed at the call site, with the consequence:** `PIPELINE_ALLOW_SELF_IMPROVE=1` renders the checkbox **unchecked** while the pipeline has it **enabled**. `:2533-2535` reads `os.getenv("PIPELINE_ALLOW_SELF_IMPROVE", "false").lower() == "true"`, while `app/action_pipeline.py:384` reads the **same variable** through `env_bool(..., False)`, which accepts `1`/`yes`/`on`. An operator who hand-edits `.env` to the perfectly reasonable `=1` gets a checkbox showing *off* and an agent permitted to modify its own code. |
| AW-03 | low | **`create_settings_tab` is 997 lines** (`:1669-2665`) — the largest single method in the depth pass, by a factor of two over the next (`_is_bad_dialogue_response`, 484). It builds the providers/GPU group, model dropdowns, the feature-flag checkboxes, the pipeline toggles, the danger-zone controls and the save path. AW-02 lives inside it, and `11s`'s AK-01 (the Anthropic model list) is consumed by it. Not a defect in itself, but it is the file's dominant structure and the reason a single env-parser mistake was easy to introduce and hard to spot. |
| AW-04 | info | **Two small helpers dead:** `_portfolio_contains_duplicate` (`:3417`, 16 lines) and `_selected_opportunity_entry` (`:3537`, 4 lines) — zero references anywhere, production or test. Both sit inside `create_opportunities_tab`'s region, so they read as helpers for a de-duplication or selection feature that was started and not finished. |

---

## AW-02 — the disagreement, stated as the operator will meet it

This is `11v`'s AO-03 at the site, and the full shape is now visible. The checkbox group
at `:2528-2544` **reads on load and writes on toggle**:

```python
2530   os.getenv("PIPELINE_ALLOW_WRITE", "true").lower() == "true"       # single parser, consistent
2535   os.getenv("PIPELINE_ALLOW_SELF_IMPROVE", "false").lower() == "true"
2543   _check.stateChanged.connect(lambda state, name=_name: os.environ.__setitem__(
2544       name, str(bool(state)).lower()))
```

**The write side is fine** — toggling produces exactly `"true"`/`"false"`, which
`.lower() == "true"` reads correctly. The disagreement is only on the **read** side, and only
when the value came from somewhere other than this checkbox:

| `PIPELINE_ALLOW_SELF_IMPROVE` | `action_pipeline.py:384` (`env_bool`) | `:2535` (`.lower()=="true"`) | operator sees |
|---|---|---|---|
| `true` | True | True | checked — agrees |
| `false` | False | False | unchecked — agrees |
| `1` | **True** | **False** | **unchecked — DISAGREES** |
| `yes` / `on` | True | False | **unchecked — DISAGREES** |

`:2530` (`PIPELINE_ALLOW_WRITE`) has no competing reader — it is not in
`feature_flags._FEATURE_ENV` and no other module parses it — so **the disagreement is
specific to `PIPELINE_ALLOW_SELF_IMPROVE`**, which is exactly the variable ARCH-ENG-203
named when it fixed `app/action_pipeline.py:380`. The fix landed at one of the two sites.

**ARCH-ENG-221 in the same file is the counter-example worth citing**, because it shows the
project doing the right thing on a neighbouring line of the same subsystem.

---

## Verified as sound — a correct migration, and the third instance of that shape

**`create_diagnostics_tab` (`:937-943`) is a documented backward-compat shim, not a dead
surface:**

> *"Backward-compat shim: build only the diagnostics sections. **Since v2.1.11 these live
> inside the DB Stats tab.** This method is kept so existing tests and any external callers
> keep working; it builds a standalone widget containing just the diagnostics groups."*

Confirmed in both directions: `create_db_stats_tab` **does** create
`self.diagnostics_health_table` (`:851`) and `self.diagnostics_performance_label` (`:865`),
so the diagnostics surface the operator sees is live and built by the tab that is in
`tab_specs`. And `refresh_diagnostics:1546-1547` guards the 5-second timer:

```python
if not hasattr(self, "diagnostics_health_table"):
    return
```

So `main.py:2155`'s periodic call is a cheap no-op until DB Stats is first shown, then does
real work. **Nothing is missing and nothing crashes.**

This is the **third** instance of the well-handled migration shape, and it belongs beside
`11p`'s two `_detect_gpus` (documented fallback) and `11w`'s W-01 (documented supersession).
In each, the *relationship* is the first thing the newer code's docstring says. **That is the
test `AW-01` fails** — `create_collaboration_tab`'s docstring describes intended behaviour and
never says it is superseded, which is precisely why it reads as live.

**ARCH-ENG-221's `refresh_diagnostics` docstring (`:1527-1544`) is the best defect narrative
in this file**, and it explicitly frames its own defect as an *inversion* of three earlier
ones:

> *"ARCH-ENG-221: THIS USED TO PASS `refresh_health=True` UNCONDITIONALLY… Passing `refresh=True`
> bypassed that TTL entirely — so the 5 s diagnostics timer forced a fresh probe twice per
> TTL, each one `urllib.urlopen(timeout=3)` per role ON THE GUI THREAD… Against a llama-server
> that has accepted the socket but not yet loaded the model, that is up to a **6-second frozen
> window every 5 seconds.**
>
> Note the shape of the defect: it is the SAME one ARCH-ENG-179, -185 and -188 were raised
> for, **inverted**. Those cached an observation and presented it as current fact; this
> discarded the expiry that was built to stop it, and paid for the probe on the thread that
> must never block.
>
> `force=True` remains available for the explicit 'Refresh Diagnostics' button, where the
> operator has asked for live data and can wait."*

That last sentence is the distinction the codebase keeps making — **a stale cached value and
a deliberately fresh one must be visually and structurally distinguishable**, and `force`
exists so the operator can ask for the expensive truth. It is also the same principle as
`11A`'s AT-01 (an index that silently drops entries asserts a completeness it does not have).

**Lazy tab construction is deliberate and documented** (`main.py:1508-1513`): *"lazy-build tabs
on first show — faster startup + lower peak memory. Each tab starts as a placeholder; the real
builder runs once the operator first opens it. Widget attributes … are only needed after the
tab is visible, so deferring is safe."* Management and Providers & GPU are built eagerly
(`:1557-1561`) with the reason given: Management is the startup dashboard, and Providers & GPU
*"must never remain on a Loading label."*

---

## Re-verification

**`11v` / AO-03 confirmed (AW-02).** The finding said `tab_feature_builders.py:2535` was the
unfixed half of ARCH-ENG-203. Confirmed, with the write-side and read-side separated, and
with the scope narrowed: `:2530` is single-parser and consistent; only the
`PIPELINE_ALLOW_SELF_IMPROVE` checkbox disagrees.

**`11s` / AK-01's consumer located.** `_on_models_fetched` (`main.py:2515`) is driven from
this file's Settings tab — the ANTHROPIC tab is built here, and the one-line `return out`
missing in `app/provider_models.py:490` is what makes its model dropdown empty.

**`11h` consistent.** `provider_config_widget.py` and the Providers & GPU tab both consume
`_price_for`, which this file's builder surfaces.

**`11j` / ARCH-ENG-219 unaffected.** Brain placement is `brain_roster.py`'s; this file builds
the *display* of what that produces.

**`11g` / `legacy_tools` consistent.** The workshop buttons at `:602`, `:624` and `:650` all
pass `approval_queue=HumanApprovalQueue.instance()`, matching `11t`'s finding that the queue
is injected rather than imported ad hoc. The comment at `:214-216` explains that a
`tab_feature_builders`-specific fallback was removed and the shared queue is correct either
way — a decision recorded at the site.

---

## Assessment

Two medium findings, and the more valuable result is the contrast between them.

**AW-01 and the diagnostics shim are the same situation resolved two different ways.**
Diagnostics moved from its own tab into DB Stats; the old builder was kept, labelled
*"Backward-compat shim … Since v2.1.11 these live inside the DB Stats tab"*, and the live
refresh path guards on `hasattr` so the timer is a no-op until the widget exists. That is a
migration that can be read from the code. Collaboration simply is not in `tab_specs`, and its
docstring reads as though it were — **which is how a reader would conclude the operator has a
Run Monitor they do not have.**

The fix is one line in `main.py`'s `tab_specs` (plus the `optional_tabs` decision, if it
should be gated like the others). But it should be paired with a sentence in
`create_collaboration_tab`'s docstring saying *why* it is not listed — because the reason it
is absent is not recorded anywhere, and this sweep had to infer it from the absence of a tab
entry. That inference cost more than the fix will.

**AW-02 is a one-line fix with a disproportionate blast radius**, and it is the seventeenth
instance of the sweep's central theme in its purest form: two correct readers of one variable,
disagreeing silently. `action_pipeline.py` is right; this checkbox is wrong. The operator's
control shows one state and the agent has another, and the only way to find out which is to
read `action_pipeline.py`. ARCH-ENG-203 diagnosed this exact disease in a different feature
and cured one patient; the second patient is 1,150 lines away in a different subsystem, and
the general fix — deleting raw `os.getenv` boolean parsers in favour of `env_bool`, which
`11v` counted at **27 sites across five vocabularies** — was never applied.
