# 11f — `agents/earning/opportunity_lifecycle.py` depth pass (1,067 lines, 37 methods)

> **Z-01 RESOLVED in v2.1.125 (ARCH-ENG-287).** The Management tab now exposes
> an operator-initiated "Reconcile Evidence" action (evidence id, independent
> method, note). `MainWindow._reconcile_paid_evidence()` verifies that the
> evidence belongs to the opportunity, restricts the method to
> `_INDEPENDENT_RECONCILIATION_METHODS`, picks the latest unresolved payment when
> the id is blank, records the reconciled evidence, reports refusals, and lets
> the existing lifecycle policy book `paid` only when submission, completion and
> payment all remain eligible. Manual/local re-assertion is still refused.
>
> **LOW TIER CLOSED in v2.1.125.** Z-03 (ARCH-ENG-256): `get_top_opportunities`
> had no caller outside its own definition and is deleted.
>

Depth-pass #6 of 83. The most financially critical class in the repository.
**31 of 37 live — 6 dead**, and two of them form a dead subsystem that matters:
the financial reconciliation path and the entire scheduler.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| Z-01 | **high** | **The financial reconciliation path is dead — and it is the only way a disputed payment can be resolved.** `reconcile_evidence` (`:479`, 49 lines) *"promote[s] a non-affirmative (CONFLICTED/REJECTED/UNVERIFIED) evidence to VERIFIED via INDEPENDENT external reconciliation (never an LLM assertion)"*. It is called by nothing. Worse, `agents/evidence/evidence_policy.py`'s `reconcile` (`:182`) — the policy function it delegates to — has **zero production callers**: the only import anywhere is at `opportunity_lifecycle.py:493`, *inside the dead method*. The remaining references are its own definition, a docstring, and a comment at `earning_pipeline.py:1428` that reasons about what it *would* enforce. So the escalation path is dead at both ends. This carries **ARCH-ENG-065**, a documented financial defect: *"the old code used `state.last_amount`, which `mark_submitted` had set to the caller-supplied claim — so a $5000 claim settled for $25 booked $5000 of verified revenue while `EconomicAccounting` on the same subject said $25. **Two authorities disagreed by the whole difference.**"* The fix is correct, documented, and unreachable. |
| Z-02 | med | **The lifecycle's entire scheduler is dead — it has no time-based transitions.** Four methods, none reachable: `scheduler_check` (`:202`, 40 lines) produces three action types — `promote_applied`, `expire`, `follow_up`; `process_scheduled_actions` (`:243`, 19 lines) executes them; `promote_to_applied` (`:179`) handles the promote action; and `promote_to_submitted` (`:188`, 11 lines) has **exactly one reference — its own `def`**, so it is orphaned independently of the rest. `promote_to_applied` is a **transitive** orphan: its only caller is `:248`, inside the dead `process_scheduled_actions`. The consequence is concrete and operational: **nothing expires an opportunity past its deadline** (`state.deadline < now`), **nothing follows up an opportunity stalled in `in_progress` for 24h+**, and nothing auto-promotes qualified queued opportunities. The lifecycle advances only when a caller explicitly drives it. |
| Z-03 | low | **`get_top_opportunities` (`:293`, 4 lines) is dead** — one reference, its own definition. |

---

## Verified as sound

**The live payment path is correctly gated.** `mark_paid_verified` is the live
entry (`:326-427`), it records to the `EvidenceStore` at `:331` and `:403`, re-reads
with `for_subject` at `:335` and `:406`, and gates the transition on policy rather
than on the caller's assertion. This matches the ARCH-ENG-043 and `10h` assessment
exactly, and `11c` re-confirmed three call sites.

**`mark_submitted` gates on a dispatch capability** (`:348`): *"When an
EvidenceStore is attached, the SUBMIT…"* — the transition is refused rather than
degraded when the store is absent, which is the correct direction for a financial
gate.

**ARCH-ENG-064's fix is present and readable** (`:916-923`) — trust now follows
*"affirmative status AND verification level >= L3 external source"* rather than a
bare `{"verified": True}` dict.

**The ARCH-ENG-065 logic inside the dead method is correct even where it is
unreachable**, and worth recording because a future re-wiring should not have to
re-derive it: the reconciled amount **replaces** the claim rather than being
`max()`-ed with it (`:508-517`), falling back to the recorded claim only when the
evidence carries no amount of its own, and appending a `submitted`-stage event with
`amount=0.0` when neither is positive (`:518-521`) so the transition is auditable
rather than silent.

**The state vocabulary in the module docstring** — `discovered → researched →
queued → applied → in_progress → submitted → paid/failed` — matches the live
`mark_*` methods.

---

## Re-verification, and a correction to `10i`

**`10i` needs amending.** That pass recorded that `EvidenceStatus` including
`CONFLICTED` is *"a first-class state… contradicting evidence is modelled rather
than resolved by last-write-wins — the correct shape for a store that later decides
whether money may be booked."*

That was accurate about **modelling** and incomplete about **resolution**. The
`CONFLICTED` state can be created but never cleared: the only method that promotes
a non-affirmative record to `VERIFIED` is Z-01's dead `reconcile_evidence`, and the
policy function behind it has no live caller. The earlier claim stands on modelling
and should now be read with this one.

---

## Assessment

31 of 37 live is a good ratio, and the *live* half is the most carefully written
code in the earning domain — the payment gate, the L3 floor, the ARCH-ENG-064 fix
and the ARCH-ENG-065 amount rule are all present, documented with their incident
evidence, and correctly wired.

Z-01 is the **thirteenth** instance of the sweep's core pattern and the highest-value
one yet, because the missing last hop is **financial reconciliation**. The system's
payment path can accept a verified payout (`mark_paid_verified`, live, correctly
gated) but cannot resolve one that later turns out to be **disputed, rejected or
incomplete**. Given ARCH-ENG-065's own scenario — a $5000 claim that settled for $25
— the case for reconciliation is precisely the case where the claim and the
settlement disagree, and that case is currently unhandleable. The safe direction
(without it, a disputed record simply stays unverified and no money is booked) means
this is a **capability gap rather than a financial risk** — but it is a gap in the
one mechanism the whole evidence architecture exists to provide.

Z-02 is a separate subsystem with a different character: the lifecycle is a state
machine with no clock. Everything time-based — deadline expiry, stall follow-up,
score-based auto-promotion — is implemented and unreachable, so the lifecycle only
moves when someone pushes it. Combined with `11c`'s finding that `run_full_cycle`
is the live driver and `11e`'s that the 20-stage loop runs per-opportunity rather
than on a schedule, the picture is consistent: **the system has thorough per-opportunity
machinery and no autonomous temporal loop over it.**