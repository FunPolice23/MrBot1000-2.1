# 11K — `gui/tabs/earning_tab.py` depth pass (590 lines, 24 methods)

> **RESOLVED in v2.1.125 (ARCH-ENG-237).** BB-01 fixed on both halves: the tab
> now reads the "To address" field that had always existed but was a throwaway
> local — the placeholder `"0x" + "A" * 40` is never substituted, and an empty
> recipient is an honest refusal that names the risk (approving a placeholder
> would authorize a real transfer to it). And `RealCryptoOperator.propose_payment`
> validates the recipient at the entry boundary — chain-aware shape (EVM /
> Solana base58) plus the all-identical-digits dummy class — BEFORE a request
> is created or an approval is enqueued, so rejection creates nothing. The
> content check protects every future caller, not only this tab.
> Governed tests updated in step: ARCH-ENG-154's gate test supplies a real
> recipient from the field; ARCH-ENG-130's scoped-approval test uses a
> shape-valid dummy. Regression tests:
> `tests/engineering/test_arch_eng_237_recipient_not_placeholder.py`.

Depth-pass #37 of 83. **0 dead of 24.** One **med** finding — and it is the sharpest instance
yet of a class this sweep has now seen six times: *a mechanism built to a high standard,
carrying content that is wrong.*

---

## Structure

```
L   1-11    module docstring — Paths 1-4
L   32-590  EarningTab (24 methods)
```

Docstring: *"Unified Earning tab integrating Paths 1-4… Path 1: Freelance finder + proposal
writer + human-gated submitter. Path 2: Microtask earner. Path 3: Crypto wallet + payments +
operator. Path 4: Autonomous loop control + run state. **All real external actions are
human-gated by design.**"*

Largest: `setup_ui` (71), `_build_path3_group` (49), `get_summary` (44),
`_on_submit_proposal` (41), `_build_path1_group` (40), `_init_backends` (37).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| BB-01 | **med** | **The tab's payment button proposes a transfer to a hardcoded placeholder address, and the approver is shown it as a real payment.** `:476-492`: `to_address = "0x" + "A" * 40`, with the comment *"payment fields collected from UI controls in future iteration; for now we use sender as from_address with a **placeholder to_address**"*. That address flows into `real_crypto_operator.propose_payment`, which enqueues an `ApprovalKind.PAYMENT` whose description reads **"Send {amount} {currency} on {chain} to 0xAAAAAAAAAAAAAAAAAAAAAAAAAAAA. Approve to authorize the on-chain send; deny to keep it simulated."** — a fully-formed, human-readable request to move real funds, to an address that is not the operator's. **There are zero `to_address` validation sites in the entire tree** (searched for `valid`/`verify`/`check`/`len(`/`startswith` — none). |

---

## Why ARCH-ENG-130's excellent scoping makes BB-01 worse, not better

`real_crypto_operator.py:77-82` is a model of approval scoping:

> *"ARCH-ENG-130: enqueue a SCOPED payment approval so the human reviews the exact
> destination/amount/currency/chain, and the returned `approval_id` is what `confirm_and_send`
> requires. Scope lives in `details` with `tool="crypto_send"` so `assert_approval_covers` binds
> a later send to exactly this action (**one id can never be replayed against a different
> amount/destination**)."*

That is `11t`'s ARCH-ENG-129 binding, correctly applied to money. **And it is what makes BB-01
sharp.** The scope check guarantees the operator approves *precisely what was requested*. What
was requested is a placeholder. So the guarantee holds perfectly and delivers the operator to
an irreversible on-chain transfer to `0xAAA…`.

This is the inversion of the sweep's usual shape. Ordinarily a defect is a **missing** check.
Here every check is present, strong, and faithfully enforced — over content that should never
have been supplied. **A correct mechanism does not launder incorrect input.**

**Mitigating factors, stated precisely.** `:110-116` returns `blocked` if the guard blocks,
and `:118-120` — *"No safety guard or allowed → **simulate**"* — means a real send requires the
`flag` → `awaiting_approval` path. So no money moves without a human clicking Approve, and the
approval payload is bound to the exact action. **The failure is not an unauthorised transfer;
it is a plausible-looking authorisation request for a meaningless one.**

---

## The class this is the sixth instance of

| | file | the message says | the truth is |
|---|---|---|---|
| 1 | `provider_models.py:490` (AK-01, `11s`) | *"offline, bad key, or no models API"* | Anthropic needs neither — a missing `return` |
| 2 | `live_trading.py:139` (AO-02, `11v`) | tab visible ⇒ live enabled | two different env variables |
| 3 | `tab_feature_builders.py:2535` (AW-02, `11D`) | checkbox unchecked | self-improvement **enabled** |
| 4 | `safety_tools_tab.py:568` (AZ-01, `11H`) | clean APPROVED row | routing silently failed |
| 5 | **`earning_tab.py:480` (BB-01)** | **"Send 5 ETH to 0xAAA…"** | **the address is a literal** |
| 6 | `discoverer.py` (AP-01, `11w`) | *(printed to stdout)* | opt-in gates invisible |

**Six instances, one shape: the reporting surface is correct and well-built, and the thing it
reports is wrong.** In five of six the consequence is a misleading *message*; in BB-01 it is a
misleading *authorisation request*, which is the highest-stakes version of the pattern the
sweep has produced.

The general lesson is the one `11w`'s `_stated_usd` and `11J`'s `_step12_verify` both point at:
**validate content at the boundary where it enters, not only at the boundary where it is
used.** `_step12_verify` refuses a dict that claims `verified: True` even though the dict's
*shape* is fine; BB-01's `propose_payment` faithfully carries an address that was never a real
address. The same discipline applied one hop earlier would reject it.

---

## `_on_submit_proposal` — the positive control, in the same file

The submission path is the counter-example within this same module, and it is worth reading
alongside BB-01 because it shows the standard the file meets elsewhere.

`:396-399` states the API contract and the failure it prevents:

> *"The real API is `prepare_submission -> request_approval -> submit`. **Calling `submit()`
> directly (or with `proposal_text=`) either raises `TypeError` or bypasses the approval gate
> entirely.**"*

And the code follows that order exactly, with three branches handled:

| branch | line | operator sees |
|---|---|---|
| gate refuses | `:403-408` | **"The submission was NOT sent."** |
| awaiting approval | `:409-415` | *"Queued for human approval (id …). It will not be sent until a human approves it in the Approvals tab."* |
| already approved | `:416-417` | the result |

**Claim and code match**, and the failure message names the negative outcome explicitly — the
`11s`/AK-01 lesson applied correctly. **The same file, the same standard, one path right and
one path with a placeholder address** is what makes BB-01 a specific defect rather than a
general one.

**Three `QMessageBox.warning` guards precede any work** (`:381-390`): no proposal text, no
selected row, no backend — each refusing before touching the submitter.

---

## Verified as sound

**`get_summary` (44 lines) is a live rollup** — Path 1-4 state in one place, which is what an
operator opens the tab for.

**`_init_backends` (37 lines)** constructs `FreelanceFinder`, `PlatformSubmitter`,
`WalletManager` and the crypto operator up front, with each group's build method tolerating a
`None` backend (`:388-390` checks `self.platform_submitter is None` explicitly rather than
assuming). That is the same defensive-shape `11C`'s `_NullWidget` provides in the other
direction — a missing backend produces a message, not a traceback.

**`refresh_coordinator` is imported and used** (`:28`), so this tab participates in the shared
refresh path rather than polling on its own timer.

**The simulated path is explicit** — `:118-120`'s `simulate_payment` means the default state of
the crypto operator is *"nothing real happens"*, with the real send behind an approval. That is
the right default direction for a money feature.

---

## Re-verification

**`11t` confirmed at the consumer.** `real_crypto_operator`'s four `HumanApprovalQueue` sites
(`:84`, `:168`, and the `assert_approval_covers` import at `:25`) are all live and all reached
from here — `11t` recorded them as consumers and this pass confirms the caller.

**`11v` consistent.** AO-01 recorded that the live-*trading* order path has no entry point;
this is a different money surface (crypto payments), it **is** wired, and it is
approval-gated. The distinction is the point — not every money surface is inert.

**`11w` / `11B` consistent.** `_on_freelance_search` (25 lines) drives
`freelance_finder.search()`, whose `budget` field `11B` recorded as a **string that never
becomes a number**. So the budget column in this tab's table (`:394`) is displayed text, never
a computed figure.

**`11x` / AQ-01's pattern, inverted.** `ActionPipeline.process` is a money-adjacent surface
that cannot safely be wired (`11x`); this is one that is wired and gated correctly. The
difference is that `_require_approval_for`-style verification exists downstream here and does
not there.

---

## Assessment

Zero dead of twenty-four, and one med finding that is worth more than the dead count would have
been.

**BB-01's fix is not a validation check — it is removing the button.** A `to_address` field
that the operator fills in, wired to the existing `propose_payment`, is a small UI addition
(`_build_path3_group` already builds the other payment controls, `:49` lines). Adding a regex
instead would leave a payment button whose destination is a typo away from an irreversible
transfer.

The alternative — a `to_address` line edit plus a `not to_address.startswith("0xAAAA")`
guard — is defensible only if the button is clearly marked as a stub. It currently is not: the
approval request it produces is indistinguishable from a real one.

**The class-level observation is the more useful output.** This is the sixth instance of
*"the mechanism is right and the message is wrong"*, and the first where the message is an
authorisation. That progression is worth carrying into the fix list as its own item: the
sweep's recurring finding has been *"mechanism correct, wired at one end only"*, and BB-01 is
the first case where the wiring is complete at both ends, the mechanism is exemplary, and the
defect is entirely in **what was fed to it**.

A useful test for the consolidated fix list, then: for every approval-gated or
reporting path, ask not only *"does the gate run?"* but *"would a human reading this output be
able to tell that the input was a placeholder?"* In five of the six instances above, the answer
is currently no.
