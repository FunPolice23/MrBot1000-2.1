# 11s — `app/provider_models.py` depth pass (636 lines, 7 methods + 18 module functions)

Depth-pass #19 of 83. **2 dead of 7 methods; 2 dead of 18 module functions.** Contains a
live defect that survives all the way to the GUI as a *misleading diagnostic*, and — more
importantly — **this pass forced a correction to AJ-02 from `11r`, and exposed a bug in
the sweep's own methodology.**

---

## Structure

```
L   41-129   ModelInfo      (7 methods, all live)
L  137-636   18 module-level functions
```

Docstring: *"Cloud-provider model discovery + pricing for the Settings tab. Given a
provider + API key (+ optional base_url), fetch the available models and return them with
pricing info so the UI can show a dropdown like `claude-3-5-sonnet — $3.00 in / $15.00 out`
or `model — FREE`."*

`_PROVIDERS` (`:131`) maps provider → `(kind, default_base, vendor)`; `kind` selects the
parser at `fetch_models:598-603`.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AK-01 | **med** | **`_from_anthropic()` builds a 6-model list and returns `None`.** `:490-496` populates `out` from `_ANTHROPIC_STATIC` and the function body contains **zero `Return` nodes** (AST-confirmed) — it falls off the end. `fetch_models:603` assigns `models = None`, and despite the `-> list[ModelInfo]` annotation and the docstring's *"Returns [] on any failure"*, **`None` is what propagates**. `_ANTHROPIC_STATIC` (`:237-244`) holds six priced, curated Anthropic models — Claude 3.5 Sonnet/Haiku, Claude 3 Opus/Sonnet/Haiku, Claude 2.1 — with context lengths and per-1M prices. **None of them is ever shown to anyone.** |
| AK-02 | info | **Two dead module functions.** `is_moe` (`:364`, 3 lines) and `is_fetchable` (`:566`, 2 lines). Five lines total, zero tests. `is_moe` is a one-line convenience wrapper over `get_arch_info(...).get("moe")`, which is called directly in five places; `is_fetchable` is `provider.upper() in _PROVIDERS`, which `fetch_models:575` re-implements inline as `if provider not in _PROVIDERS`. |
| AL-01 | **med** | **A bug in the sweep's own reachability scan, and the 7 findings it hid.** See below. |

---

## AK-01 verified to the real entry point — the consequence is a wrong *message*

The defect is a missing `return out`. What matters is what the operator sees, so this was
traced all the way to the GUI rather than stopped at the module boundary:

```
_from_anthropic()            -> None                      (no Return node)
  fetch_models:603          -> models = None
  fetch_models:614          -> if models:   ...   SKIPPED (None is falsy)
  fetch_models:621          -> return None               (annotated list[ModelInfo])
  main.py:359-362           -> try/except catches only RAISES; None raises nothing
                              self.finished.emit(None)
  main.py:2504              -> lambda models: _on_models_fetched(p, cs, None)
  main.py:2518              -> if not models:   TRUE  -> "no models" branch
```

**There is no crash.** `main.py:2518`'s `if not models:` guard catches the `None`,
because `not None` is `True`. The defensively-written caller survives a contract violation
that its own type annotation promised could not happen.

**But the operator is told something false.** The branch taken sets:

> *tooltip:* `f"No models returned for {provider} (offline, bad key, or no models API). You can still type a model name."`
> *log:* `f"[Models] {provider}: no models (offline/empty)"`

Anthropic is the **one provider in `_PROVIDERS` that requires neither a network call nor
an API key** — `_from_anthropic` takes no arguments and reads a curated constant. The
message diagnoses *offline*, *bad key*, and *no models API* when nothing was attempted and
none of the three could apply. The operator is sent to debug their connectivity or their
credentials for a code defect in the application.

This is the mirror image of ARCH-ENG-115. `11o` recorded that rule as *"omitting the
section is strictly better than stating a false one"* — applied to hardware claims. Here
the false statement is a **diagnostic**, and the same standard applies: the honest message
for "the model list came back as `None` because of a bug" is not "you appear to be
offline." A provider that needs no key should never produce a message blaming the key.

**`fetch_models`'s own `except Exception: models = []` (`:604-605`) is not the culprit** —
it never fires, because nothing raises. That is why the failure is invisible: the module's
one error-handling path is bypassed by a defect that uses none of it.

**Contrast that confirms the intended design** — the NVIDIA fallback at `:611-612` is
written correctly:

```python
if not models and kind == "nvidia":
    models = _nvidia_free_models()
```

`_nvidia_free_models` *does* `return out` (AST-confirmed), and the falsy-`None` test is
exactly right for it. The Anthropic branch is the only parser missing its return.

---

## AL-01 — the sweep's reachability scan had a bug, and it hid 7 findings

**My scan, run over `app/provider_models.py`, reported 10 dead module-level functions.**
All ten were false negatives. They are called from `fetch_models` and `clear_cache` within
the same file.

The cause: for **methods** I counted internal references (excluding the `def` line), but
for **module-level functions** I searched only *other files*, excluding the file itself.
So a module-private helper called by its own module's public function looked dead.

I found this because the result was implausible — four dead provider parsers, in a module
whose one live entry point dispatches to exactly those parsers by `kind` at `:598-603`.
Reporting "10 dead" without checking would have been a fabricated finding.

**Re-run correctly across all 18 already-depth-swept files that have module-level
functions, the corrected scan finds 7 genuinely dead ones that earlier documents
under-reported:**

| File | Function | Line | Size |
|---|---|---|---|
| `main.py` | `validate_clipboard_json` | 264 | 26L |
| `main.py` | `_log_html` | 368 | 15L |
| `main.py` | `_log_shutdown_warning` | 402 | 15L |
| `gui/workers/provider_lifecycle_backend.py` | `host_contract_satisfied` | 151 | 10L |
| `agents/earning/opportunity_lifecycle.py` | `initialize_lifecycle_export` | 1057 | 11L |
| `agents/earning/opportunity_portfolio.py` | `apply_next` | 823 | 32L |
| `agents/brains/big_brain.py` | `get_big_brain` | 702 | 6L |

Three of these change how earlier findings should be read:

**`host_contract_satisfied` (`:151`) is AA-01.** `11b` recorded *"AA-01 — unguarded host
protocol."* The guard function **exists, is correct, and is never called**: it is a
ten-line `hasattr` sweep over `HOST_METHODS`/`HOST_ATTRS` whose docstring says *"Empty list
means the mixin can be used with this object."* So AA-01 is not merely an unguarded path —
**the guard was written and left unwired.** That is the sweep's fifteenth instance of
*"mechanism correct, wired at one end only."*

**`apply_next` (`:823`, 32 lines) is a superseded status machine**, and its death is
**correct**, not a defect. `opportunity_portfolio.py:843-849` holds a `_NEXT_STATUS` map
(`NEW → EVALUATING → QUALIFIED → … → PAYMENT_PENDING → PAID`) that `apply_next` walks.
`agents/earning/executor.py` performs the real transitions itself via
`portfolio.transition_work_status(...)` at `:303` (READY), `:305` (IN_PROGRESS) and
`:501` (PAID). This is the *same* shape as `AH-01`'s two `_detect_gpus` — an older
mechanism retained beside a newer one that supersedes it — and the newer one is the one
that is live.

**`_log_html` (`main.py:368`, 15 lines) is benign, and was worth checking precisely
because it looked like a security control.** Its docstring describes HTML-escaping log
text *"so a stray '<' / '&' in log text can't break the view or inject markup (defense
against untrusted gig/scrape data ending up in the log)"* — and untrusted gig/scrape data
does flow through this codebase (the same file's `_log_html` neighbour mentions the
`'BEGIN UNTRUSTED GIG DATA'` envelope). It is dead because **the live log is no longer an
HTML view**: `log_signal.connect(self._safe_log)` (`main.py:552`) routes to `_safe_log`
(`:1209`) → `_append_log` (`:1357`) → `_append_log_to_table` (`:1243`), a table widget,
which has no HTML injection surface. So the escaping helper is superseded by a rendering
model that does not need escaping. **No security finding** — but it would have been the
most alarming-looking of the seven if reported without this check.

**Methodology going forward:** the corrected scan counts internal references for
module-level functions exactly as it does for methods. Every remaining depth-pass file is
scanned with the corrected version.

---

## Correction to AJ-02 (`11r`) — the empty tables are *by design*

This pass traced `apply_next` to `executor.py` and found the explanation for the empty
`outcome_memory_v2` / `outcome_evidence` tables that `11r` recorded. **It corrects AJ-02
as written, in the codebase's favour.**

`agents/earning/executor.py:23-43` (ARCH-ENG-158) documents it directly:

> *"steps 12/14 could not verify a payment, so they asserted one. Steps 12 and 14
> previously wrote `step_results[12] = {"verified": True}` as a literal and then
> transitioned the portfolio to `WorkStatus.PAID` at step 14 with no evidence of any kind.
> The pipeline therefore reported a completed, paid opportunity for any task that reached
> step 11 … That is precisely the shape `agents/safety/handlers.py::_is_approved` and
> `OpportunityLifecycleTracker._is_verified_evidence` were hardened to refuse
> (ARCH-ENG-064/118/119/121): **the caller asserting its own claim, dressed as a
> verification.**
>
> Both steps now consult a real `EvidenceStore` and the shared evidence policy. The
> portfolio only reaches PAID when a real `Evidence` satisfies the same
> `SUBMITTED->PAID` / `CLAIMED->REVENUE_REALIZED` contract that
> `AutonomousLoop._stage_verify` enforces … With no evidence store wired, or no qualifying
> evidence, the pipeline **fails CLOSED**: step 12 records why, step 14 leaves the entry in
> PAYMENT_PENDING, and the result reports `final_status="payment_unverified"`.
> **`WorkStatus.PAID` is no longer reachable from this module without independent proof of
> payment.**"*

**What this changes.** `11r` presented the empty tables as a second defect stacked on
AJ-01, and speculated that the fix might involve getting outcomes to complete. That was
wrong in an important way: **the tables are empty because the safety mechanism is working
exactly as ARCH-ENG-158 intends.** No payment has been independently verified, so no
outcome is recorded and no entry reaches PAID. `11c`'s observation that
`record_outcome_v2` is live with healthy writes but nothing has ever completed is not a
write-path defect — it is the fail-closed branch being taken every time.

**What survives of AJ-02, restated.** The finding that matters is narrower and, if
anything, sharper: **the self-audit layer must never report a clean bill of health on
empty tables, and there is no reason to expect those tables to fill soon.** Under
ARCH-ENG-158 they stay empty until real payment evidence exists. So AJ-02 is not "wire up
the audit once there is data" — it is **"the audit must distinguish 'no data' from 'no
problems' permanently,"** because the no-data state is the system's *designed* resting
state, not a transient condition to be waited out.

That is a better finding than the one it replaces. `11r` proposed the general fix —
*"report insufficient data rather than no problems found"* — and ARCH-ENG-158 shows why it
is not a nicety but the load-bearing requirement.

---

## Re-verification

**`11o` confirmed and extended.** `get_big_brain` (`big_brain.py:702`, 6 lines) is dead —
consistent with `11o`'s "0 dead of 17" for `BigBrainAdapter`, which counted only *class
methods*. The module-level accessor was missed by that document's own scope and is caught
by AL-01's corrected scan. `BigBrainAdapter` itself remains fully live.

**`10q` / R-03 area consistent.** `_price_for` (`:247`) is the pricing authority with
**13 external consumers** across `worker_provider_mixin`, `agents/safety/cost.py`,
`app/database.py`, `provider_config_widget` and `main.py` — the widest fan-out in this
module and the reason its 13-call correctness matters.

**`11h` consistent.** `provider_config_widget.py` consumes `_price_for` directly for
inline price display, independent of the fetch path — so pricing in the Settings tab is
correct today even though AK-01 breaks Anthropic's *model list*.

**`11m`/provider layer unaffected.** This module is UI-facing discovery and pricing; it
performs no allocation and no brain placement, so `brain_roster.py:26` (ARCH-ENG-219) and
`_vram_safe_context` (M-03) are untouched.

---

## Assessment

Two dead five-line accessors, one live defect, one methodology correction, and one
correction that lands in the codebase's favour.

AK-01 is a one-line fix (`return out` at `:497`) but the interesting part is what it
revealed about the error path. `fetch_models` wraps its parsers in `except Exception:
models = []` — a deliberate, correct safety net — and the defect routes straight around
it, because returning `None` raises nothing. **The one branch designed to make provider
fetching never crash is the branch this bug avoids**, which is why the failure surfaced as
a plausible-looking message rather than a stack trace. That is worth remembering when
fixing it: the fix is not only `return out`, it is also making `fetch_models` honour its
own documented contract, since the `None` would otherwise recur silently the next time a
parser is added.

The scan bug (AL-01) is the more important result for the sweep itself. It produced ten
false negatives on its first application — and I nearly recorded them. The check that
caught it was noticing that the result was *implausible* (four dead parsers in a module
whose one entry point dispatches to those parsers), which is the same instinct that caught
the `wallet_crypto` / `credential_vault` false positives in `11q`. **Implausible results
are worth as much attention as plausible ones.** Seven real findings were hiding behind the
error, one of which upgrades AA-01 from "unguarded" to "guard written and never wired."

And the AJ-02 correction is the one to carry into the fix list. The empty outcome tables
are not a bug to be cleared — they are ARCH-ENG-158 failing closed on every run, which is
the system refusing to record a payment it cannot prove. **The system is right and the
audit layer is the thing that has not caught up.** The fix is to make the audit honest
about a state that is expected to persist, not to manufacture evidence to fill it.
