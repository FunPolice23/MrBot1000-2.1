# 11P — `agents/earning/economic_accounting.py` depth pass (535 lines, 9 functions)

Depth-pass #42 of 83. **0 dead of 9 — no findings.** The monetary exemplar that this sweep has
cited since `11o`, examined at last. It earns the citation.

---

## Structure

```
L    1-20    module docstring — seven values, five non-negotiable rules
L   35-42    ExpenseCategory       L   48-152  EconomicProfile (1 method, to_dict 36L)
L  196-224   is_convertible / _record_unconvertible / to_usd
L  275-523   EconomicAccounting (5 methods)
```

Docstring — the seven values, and the rules that make them a firewall:

> *"ADVERTISED_VALUE — what the opportunity lists (**never revenue**); EXPECTED_VALUE —
> probability-adjusted forecast (**never revenue**); REALIZED_GROSS — sum of VERIFIED payment
> evidence; REALIZED_EXPENSE — sum of VERIFIED expense evidence; REALIZED_NET;
> VERIFIED_REVENUE — VERIFIED payment evidence; UNVERIFIED_REVENUE — UNVERIFIED/PARTIALLY_VERIFIED…
>
> **Rules (non-negotiable):** Advertised payment is NOT revenue. A successful submission is NOT
> revenue. A generated deliverable is NOT revenue. Revenue becomes realized ONLY when appropriate
> payment evidence exists. Only VERIFIED evidence counts toward realized/verified revenue."*

Largest: `get_profile` (128), `aggregate` (75), `EconomicProfile.to_dict` (36),
`get_verified_revenue` (18), `to_usd` (14), `get_total_expenses` (12).

---

## Findings

**None.** All nine are live, and the documented contract is enforced in code.

---

## The firewall, enforced structurally

**Verified revenue requires two conditions, not one** (`:311-315`):

```python
verified_payments = [
    e for e in payment_evidences
    if e.status == EvidenceStatus.VERIFIED
    and e.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE
]
```

**That is the same two-condition rule `11J`'s `_step12_verify` uses**, on a different surface,
in the same repository. The payment gate and the accounting layer agree on what "verified"
means — and `11J` established that gate as the reason no outcome has ever completed. **Two
independent money surfaces, one definition, no drift.**

**`realized_gross` is *definitionally* verified** (`:339`): `profile.realized_gross =
profile.verified_revenue`. Advertised cannot become gross by any path, because gross is an
assignment from the verified bucket rather than a separate computation.

**Advertised and expected are separate fields** (`:294`, `:298-300`), each read from a distinct
source — `opportunity.advertised_amount` and `intel_verdict.expected_value`. The docstring's
"never revenue" is not a convention; it is a type.

---

## ARCH-ENG-092 F5 — the best reasoning in the sweep

An unconvertible expense makes `realized_expense` a *lower* bound, which makes every derived
ratio an *upper* bound. `:379-388` states the direction of the error and the consequence:

> *"`realized_net / realized_expense` is a ratio whose denominator is known to be too small when
> any expense is unvalued — the true cost is >= the booked cost, so the true ROI is <= this
> number and could be negative. Publishing it would **rank an opportunity whose real cost is
> hidden above one whose cost is fully known.** 0.0 is the module's existing 'not computable'
> sentinel (it is what an expense-free profile reports), so **the number stays numeric for
> `sum()`/`+=` consumers while no longer being read as a return.**"*

Three properties worth naming:

1. **The error direction is stated**, not just the existence of the error. A reader who knows
   the bias is an *upper* bound can reason about it; a reader told only "approximate" cannot.
2. **The ranking consequence is spelled out** — and it is an *optimisation* consequence, which
   is the one that matters for a bot that picks what to work on.
3. **The fix is designed around the consumers.** Zeroing the value rather than omitting the key
   keeps `sum()` and `+=` working while removing the number's ability to be *read* as a return.
   `:395` applies the same suppression to `net_hourly_rate`.

**And `aggregate:444-469` carries it through to the portfolio level**, with the same reasoning
restated (`:444-448`) and the annotation **returned as data** (`:481-483`):

```python
"has_unconvertible_expense": has_unconvertible_expense,
"unconvertible_expense_amounts": unconvertible_expenses,
```

The flag travels with the number. That is `11r`'s AJ-02 restated — *"report insufficient data
rather than no problems found"* — in monetary form: a consumer cannot present the totals as a
clean figure without the incompleteness being right there in the dict.

---

## ARCH-ENG-092 — unconvertible money is recorded, not dropped

`:325-329`:

> *"record what could NOT be converted so **fail-safe zeroing is auditable rather than a silent
> disappearance of real money**."*

The conversion is fail-safe (`to_usd` returns 0.0 for an unknown currency — the `_stated_usd`
discipline from `11w`), and *that* is precisely why the un-converted amounts are recorded
separately. **A silent zero is indistinguishable from a genuine zero; this makes them
distinguishable.** The same three fields exist on both payment and expense paths (`:349-350`,
`:358-359`, `:362-363`, `:366-367`) — four recording sites, no gap.

---

## `get_verified_revenue` — the recurring defect, named and fixed

`:494-501` is the best short docstring in the codebase for what it is:

> *"Uses the SAME rule as `get_profile` (`status == VERIFIED` **and** `verification_level >=
> L3`). It used to accept any affirmative status at any level, so an L1 `manual_attestation`
> counted as verified revenue here while `get_profile` reported 0 for the same record — **two
> authorities disagreeing about the same evidence.** Nothing calls this today, so **it was a trap
> rather than a live leak.**"*

**"Two authorities disagreeing about the same evidence"** is this sweep's recurring defect in
its purest phrasing — and the fix is stated as *aligning the second authority to the first*,
not as changing either. Compare `11z`'s ARCH-ENG-211, where the same shape went unfixed and
*"the hardened path was strictly more permissive than the path it replaced"*. Here the
permissive path was brought to the strict one, and the note that it was latent rather than live
is what makes the fix defensible rather than merely tidy.

---

## ARCH-ENG-069 — a case bug with its consequence recorded

`:332-337`:

> *"`EvidenceStatus.UNVERIFIED.value` is the UPPERCASE string `"UNVERIFIED"`, so the old
> lowercase comparison never matched and `pending_revenue` was permanently `0.0` — manual/L1
> money silently landed in `unverified_revenue` instead of the 'Pending verification' bucket
> the design requires."*

A money value permanently pinned to zero by a string comparison. The fix (`str(e.status.value)
.lower() == "unverified"`) is robust; the value of the note is that it records **which money
was misbucketed** — manual/L1 evidence — so the historical records could be understood.

`:403-404` handles the remaining tri-state explicitly: `revenue_error_pct = 1.0  # found
revenue where none expected`, rather than dividing by zero or defaulting to 0.

---

## Verified as sound

**`EconomicProfile` is 105 lines of fields** (`:48-152`) with a 36-line `to_dict` — a wide,
flat record with one serialiser. For a value object consumed by a GUI, a report and a
rollup, that is the right shape: consumers read fields, and `to_dict` is the only place
serialisation knowledge lives.

**`is_convertible` (196) / `_record_unconvertible` (207) / `to_usd` (214)** are module-level
rather than methods — so the conversion policy is testable and reusable without an
`EconomicAccounting` instance, and `aggregate` uses the same three the profile builder does.

**`get_total_expenses:512-523` matches the expense rule exactly** — *"VERIFIED status only"* —
and its docstring says which rule it matches rather than restating it. The three money
accessors (`get_profile`, `get_verified_revenue`, `get_total_expenses`) now share one
definition, which is what prevents the disagreement from recurring.

**`aggregate:417-427` returns a fully-populated zero-shaped dict for an empty input** rather
than `{}` — so a consumer reading `result["roi"]` cannot `KeyError` on an empty portfolio, and
every key is present with a defensible value.

**Fee, gas and other-expenses are read from the payment evidence itself** (`:354-367`), each
with its own category and its own unconvertible-record. Gas fees on a crypto payout are the
classic hidden cost, and treating them as an expense bucket rather than netting them silently
is what makes `realized_net` mean what it says.

---

## Re-verification

**`11J` confirmed from the other side.** `_step12_verify` (`executor.py:311-408`) admits a
payout only on `VERIFIED` **and** `>= L3_EXTERNAL_SOURCE`. This module counts revenue on the
identical pair. **The gate that makes `outcome_memory_v2` empty and the layer that would book the
revenue use one definition** — which is the strongest form of consistency the sweep has found,
because it is the one place where a drift would silently create money.

**`11w` extended.** `_stated_usd` refuses to invent an amount from scraped text; this module
refuses to count an amount without evidence. Producer and accountant, same rule from opposite
ends — and both record what they could not process rather than letting it vanish.

**`11I` / `11B` extended.** `freelance_finder.budget` is a **string that never becomes a
number**, and `_stated_usd`'s output is `0.0`-or-a-verified-figure. Both feed
`advertised_value`, which `:294` reads into a field that `:339` shows cannot become gross.
**The path from a stranger's text to `realized_gross` is closed at three separate points.**

**`11F` consistent.** `11F`'s AX-01 restated that outcome tables are empty *by design* under
ARCH-ENG-158. This module is what would book those outcomes when they exist — and it will
report `verified_revenue = 0.0` until then, which is correct rather than a second failure.

**ARCH-ENG-092 / ARCH-ENG-069 / ARCH-ENG-092-F5 all verified present** with their reasoning
intact, and the F5 annotation present in **both** the per-profile path (`:373`, `:387-392`) and
the aggregate path (`:455`, `:464-469`, `:481-483`).

---

## Assessment

Zero dead of nine, no findings, and the file the sweep has cited as its monetary exemplar
survives the examination intact — which is worth stating plainly, because a citation that
stopped being checked would be exactly the "presence of tests/docs implies a function"
heuristic this sweep has caught nine times.

**What makes this module the right artefact to point at** is not that it has rules; it is that
every rule is load-bearing on a *different* axis from the others. `_stated_usd` refuses
fabrication; `_step12_verify` refuses unverified payment; `economic_accounting` refuses
aggregation of the two. And the last one adds something the others do not: **it reasons about
the direction of its own error and suppresses the derived number that error would bias**,
rather than merely refusing to produce a wrong one.

That last move is the most transferable idea in the sweep. Refusing to produce a wrong number
is necessary and common. Refusing to produce a number that is *directionally* wrong — and
saying in the returned dict that the cost base is incomplete — is rarer, and it is the
difference between a system that avoids mistakes and one that explains them.

**At 42 of 83 the sweep is past its midpoint**, and the three finding-classes have held
steadily: a missing last hop, the same decision N times with N answers, and a correct
mechanism carrying wrong content. This module has instances of the first two *in its history*
— ARCH-ENG-069 and the `get_verified_revenue` divergence are both fixed instances of class one
— and instances of none in its current state. That ratio is the codebase's quality in a single
number.
