"""agents/evidence_policy.py — Verification policy: what evidence a transition needs,
what trust level is sufficient, and whether money counts toward verified revenue (v2.0.34aq).

This is the deterministic half that decides lifecycle transitions and revenue inclusion.
It consumes Evidence from the store; it never invents success. Per the design, the lifecycle
engine becomes: EvidenceStore -> VerificationPolicy -> LifecycleTransition.

Revenue rule (point 14): only evidence that is VERIFIED at level >= EXTERNAL (L3) enters the
hard "Verified Revenue" KPI. Manual attestation / human confirmation (L1) is shown separately
as "Pending verification" and NEVER inflates the hard number until independently reconciled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Union

from agents.evidence import (
    Evidence, EvidenceRequirement, EvidenceStatus, VerificationLevel, VerificationResult,
)

# A slot may be a single evidence_type string OR a tuple of alternatives (any one satisfies).
Slot = Union[str, tuple]


@dataclass
class EvidenceRequirement:
    """What evidence a lifecycle transition needs.

    `required_types` is an ordered list of slots. Each slot is either a single
    evidence_type string, or a tuple of alternatives (any one of which satisfies the slot).
    Every slot must be satisfied by a VERIFIED/PARTIALLY_VERIFIED evidence at >= `min_level`
    (manual/human only counts where `allow_manual_fallback`).
    """
    transition: str
    required_types: List[Slot]
    min_level: VerificationLevel = VerificationLevel.L3_EXTERNAL_SOURCE
    allow_manual_fallback: bool = False
    note: str = ""


# ── Required-evidence registry (point 16 of the design) ─────────────────────────
# Payment slot = any producer-recognised payment evidence (Upwork api stmt, on-chain
# balance delta, operator manual attestation, OR independent external reconciliation).
# The gate only checks "payment happened"; revenue_eligibility() downstream keeps manual/L1
# money in "pending" until reconciled, and METHOD_CONFIDENCE keeps manual strictly below
# independently verified payment (manual 0.30 < authenticated_api 0.70 < crypto 1.0).
_PAYMENT_SLOT = ("payment_confirmation", "payment_gross", "balance_delta", "platform_transaction",
                 "manual_attestation", "external_reconciliation")

REQUIREMENTS: Dict[str, EvidenceRequirement] = {
    "DISCOVERED->RESEARCHED": EvidenceRequirement(
        "DISCOVERED->RESEARCHED", [("discovery", "research_summary")], VerificationLevel.L1_SELF_REPORTED,
        allow_manual_fallback=True, note="Local discovery is enough to research."),
    "RESEARCHED->QUEUED": EvidenceRequirement(
        "RESEARCHED->QUEUED", [("research_summary", "discovery")], VerificationLevel.L1_SELF_REPORTED,
        allow_manual_fallback=True),
    "QUEUED->APPLIED": EvidenceRequirement(
        "QUEUED->APPLIED", [("application",)], VerificationLevel.L2_LOCAL_VALIDATION,
        allow_manual_fallback=True),
    "APPLIED->IN_PROGRESS": EvidenceRequirement(
        "APPLIED->IN_PROGRESS", [("application",)], VerificationLevel.L2_LOCAL_VALIDATION),
    "IN_PROGRESS->SUBMITTED": EvidenceRequirement(
        "IN_PROGRESS->SUBMITTED", [("platform_submission",)], VerificationLevel.L3_EXTERNAL_SOURCE,
        note="A real external platform acknowledgement (API) is required, not local belief."),
    "SUBMITTED->PAID": EvidenceRequirement(
        "SUBMITTED->PAID",
        [("platform_submission",), ("completion_confirmation",), _PAYMENT_SLOT],
        VerificationLevel.L3_EXTERNAL_SOURCE,
        note="Submission + completion + payment, each externally verifiable (any recognised payment type)."),
    # Airdrop path (point 16 example): an on-chain balance delta at L5 (cryptographic) is
    # sufficient proof of received value (the receipt report IS the cryptographic proof).
    "CLAIMED->REVENUE_REALIZED": EvidenceRequirement(
        "CLAIMED->REVENUE_REALIZED",
        [("balance_delta", "transaction_receipt")], VerificationLevel.L5_CRYPTOGRAPHIC,
        note="On-chain balance delta (cryptographic) proving value was received."),
    # Manual payout (point 16): allowed but stays out of hard revenue
    "PENDING->PAID_MANUAL": EvidenceRequirement(
        "PENDING->PAID_MANUAL", [("manual_attestation",)], VerificationLevel.L1_SELF_REPORTED,
        allow_manual_fallback=True,
        note="Manual attestation permitted, but revenue is 'Pending verification' until reconciled."),
}


def requirement_for(transition: str) -> EvidenceRequirement:
    return REQUIREMENTS.get(transition)


def _slot_satisfied(slot: Slot, req: EvidenceRequirement, evidence: List[Evidence]) -> bool:
    """True if `slot` is satisfied by at least one evidence in `evidence`."""
    needed = (slot,) if isinstance(slot, str) else slot
    for ev in evidence:
        if ev.evidence_type not in needed:
            continue
        if ev.status in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED):
            if ev.verification_level >= req.min_level:
                return True
            # manual/human attestation below required level: only if fallback allowed
            if req.allow_manual_fallback and ev.verification_method in (
                    "manual_attestation", "human_confirmation"):
                return True
    return False


def is_transition_eligible(transition: str, evidence: List[Evidence]) -> bool:
    """True iff every required slot is present with status VERIFIED/PARTIALLY_VERIFIED at/above
    the required verification_level.

    Missing types => not eligible. CONFLICTED/REJECTED/EXPIRED types do NOT satisfy a
    requirement (they block the transition until reconciled). Manual attestation satisfies
    only transitions that `allow_manual_fallback`.
    """
    req = REQUIREMENTS.get(transition)
    if req is None:
        return True  # no policy registered => caller's existing logic decides (back-compat)
    for slot in req.required_types:
        if not _slot_satisfied(slot, req, evidence):
            return False
    return True


def revenue_eligibility(evidence: List[Evidence]) -> Dict[str, float]:
    """Split a subject's monetary evidence into verified / pending / unverified revenue.

    Returns dict with keys: verified_revenue, pending_revenue, unverified_revenue,
    verified_expenses, pending_expenses (each in its own currency; we sum per currency and
    return the USD-ish aggregate assuming currency matches; mixed currencies kept separate in
    `by_currency`). For the KPI, only VERIFIED @ level>=EXTERNAL money counts as `verified`.
    """
    out = {"verified_revenue": 0.0, "pending_revenue": 0.0, "unverified_revenue": 0.0,
           "verified_expenses": 0.0, "pending_expenses": 0.0}
    for ev in evidence:
        if ev.evidence_type == "payment_gross":
            amt = ev.amount or ev.gross_amount
            if ev.status == EvidenceStatus.VERIFIED and ev.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE:
                out["verified_revenue"] += amt
            elif ev.status in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED):
                # verified by manual/human only => pending until independently reconciled
                out["pending_revenue"] += amt
            else:
                out["unverified_revenue"] += amt
        elif ev.evidence_type in ("payment_fee", "payment_gas", "payment_llm_cost", "payment_other_expense"):
            amt = ev.amount
            if ev.status == EvidenceStatus.VERIFIED and ev.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE:
                out["verified_expenses"] += amt
            else:
                out["pending_expenses"] += amt
        elif ev.evidence_type in ("manual_attestation", "manual_reference"):
            # Manual/human-attested money is recognised but kept in PENDING (lower confidence);
            # it can NEVER become hard verified_revenue until independently reconciled.
            amt = ev.amount or ev.gross_amount
            if ev.status in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED):
                out["pending_revenue"] += amt
            else:
                out["unverified_revenue"] += amt
    return out


def confidence_for(ev: Evidence) -> float:
    """Deterministic method-based confidence (LLM-independent). See MethodConfidence in evidence.py."""
    from agents.evidence import method_confidence
    return method_confidence(ev.verification_method)


def reconcile(ev: Evidence, reconciler: str, note: str = "",
             method: str = "external_reconciliation",
             level: VerificationLevel = VerificationLevel.L4_INDEPENDENT_VERIFICATION
             ) -> Evidence:
    """Promote a non-affirmative (CONFLICTED/REJECTED/UNVERIFIED) evidence to VERIFIED via
    INDEPENDENT external reconciliation.

    This is the ONLY escalation path that flips a non-affirmative record to affirmative, and it
    requires real external reconciliation (e.g. bank statement vs on-chain delta, a second source
    confirming). It is NEVER called by the LLM path. Manual attestation alone cannot reconcile —
    `method` must be an independent verification method (external_reconciliation / api / on-chain).
    """
    if method in ("manual_attestation", "human_attestation", "human_confirmation", "local_record"):
        # Manual/local re-assertion is NOT independent reconciliation — refuse to escalate.
        return ev
    return ev.verify(VerificationResult(
        status=EvidenceStatus.VERIFIED, method=method, level=level,
        actor=reconciler, note=note or "reconciled via independent external source",
    ))
