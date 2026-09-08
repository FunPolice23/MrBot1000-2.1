"""agents/evidence_factory.py — Turn existing producer outputs into Evidence (v2.0.34aq).

Producers (chain_verifier, upwork_client, payout_verifier, ...) keep their own return types;
this factory is the ONLY place that maps those into the shared Evidence vocabulary. That keeps
producers clean and gives the EvidenceStore one consistent shape to persist.

The factory NEVER marks evidence VERIFIED by itself beyond what the producer already proved:
- chain_verifier.ReceiptReport.verified (on-chain balance delta) => VERIFIED @ L5 CRYPTOGRAPHIC.
- payout_verifier VerificationEvidence => mapped by method/level.
- upwork submission response => VERIFIED @ L3 EXTERNAL (authenticated_api_response), or
  CONFLICTED when the API returned an error after a local "submitted" belief.
"""
from __future__ import annotations

import time

from agents.evidence import (
    Evidence, EvidenceStatus, VerificationLevel, VerificationResult,
    VerificationEvidence,
)


# ── chain_verifier ──
def from_receipt_report(report, source: str = "ethereum", subject_id: str = "",
                        wallet_name: str = "", producer: str = "chain_verifier") -> Evidence:
    """Map a `chain_verifier.ReceiptReport` to a balance_delta Evidence."""
    status = EvidenceStatus.VERIFIED if report.verified else EvidenceStatus.UNVERIFIED
    # H32: a read failure must surface as CONFLICTED (we don't know), not unverified belief.
    if getattr(report, "before_read_failed", False) or getattr(report, "after_read_failed", False):
        status = EvidenceStatus.CONFLICTED
    level = VerificationLevel.L5_CRYPTOGRAPHIC if report.verified else VerificationLevel.L1_SELF_REPORTED
    ev = Evidence.create(
        source=source, evidence_type="balance_delta", subject_type="airdrop_claim",
        subject_id=subject_id, external_id=wallet_name,
        status=status, verification_method="blockchain_balance_delta", verification_level=level,
        amount=float(getattr(report, "received_usd", 0.0) or 0.0), currency="USD",
        observed_at=time.time(),
        source_reference=f"{source}:balance:{wallet_name}",
        raw_reference=report.note,
        provenance={"producer": producer, "method": "balance_delta"},
        metadata={"before_usd": getattr(report, "before_usd", 0.0),
                  "after_usd": getattr(report, "after_usd", 0.0),
                  "delta_usd": getattr(report, "delta_usd", 0.0),
                  "expected_usd": getattr(report, "expected_usd", 0.0)},
    )
    return ev


def from_eligibility_report(report, source: str = "ethereum", subject_id: str = "",
                            wallet_name: str = "", producer: str = "chain_verifier") -> Evidence:
    status = EvidenceStatus.VERIFIED if report.eligible and report.on_chain_checked else EvidenceStatus.UNVERIFIED
    level = VerificationLevel.L3_EXTERNAL_SOURCE if report.on_chain_checked else VerificationLevel.L1_SELF_REPORTED
    return Evidence.create(
        source=source, evidence_type="eligibility", subject_type="airdrop_claim",
        subject_id=subject_id, external_id=wallet_name,
        status=status, verification_method="blockchain_balance_delta", verification_level=level,
        observed_at=time.time(), source_reference=f"{source}:eligibility:{wallet_name}",
        raw_reference=report.reason,
        provenance={"producer": producer, "method": "eligibility"},
        metadata={"on_chain_checked": report.on_chain_checked,
                  "scanner_risk_untrusted": report.scanner_risk_untrusted},
    )


# ── payout_verifier (back-compat: VerificationEvidence -> Evidence) ──
def from_verification_evidence(ve: VerificationEvidence, subject_id: str = "",
                               producer: str = "payout_verifier") -> Evidence:
    """Convert the legacy payout_verifier.VerificationEvidence into the new Evidence."""
    method_map = {
        "onchain_balance_delta": ("blockchain_balance_delta", VerificationLevel.L5_CRYPTOGRAPHIC),
        "manual_reference": ("manual_attestation", VerificationLevel.L1_SELF_REPORTED),
        "api_statement": ("api_response", VerificationLevel.L3_EXTERNAL_SOURCE),
    }
    vm, lvl = method_map.get(ve.method, ("local_record", VerificationLevel.L1_SELF_REPORTED))
    status = EvidenceStatus.VERIFIED if ve.verified else EvidenceStatus.UNVERIFIED
    return Evidence(
        source="payout", evidence_type=("balance_delta" if ve.method == "onchain_balance_delta"
                                        else "manual_attestation" if ve.method == "manual_reference"
                                        else "platform_transaction"),
        subject_type="opportunity", subject_id=subject_id,
        status=status, verification_method=vm, verification_level=lvl,
        amount=ve.observed_usd, currency="USD",
        gross_amount=ve.expected_usd, fees=0.0, gas=0.0, tax_expense=0.0, other_expenses=0.0,
        source_reference=ve.reference, raw_reference=ve.note,
        provenance={"producer": producer, "method": ve.method},
        history=[VerificationResult(status=status, method=vm, level=lvl,
                                    timestamp=ve.verified_at, note=ve.note,
                                    raw_reference=ve.reference)],
    )


# ── upwork submission (H1) ──
def from_upwork_submission(proposal_id: str, profile_id: str, job_id: str = "",
                           subject_id: str = "", errored: bool = False,
                           error_text: str = "", producer: str = "upwork_client") -> Evidence:
    """A real platform submission. Verified via authenticated_api_response (L3) when the API
    returned a proposal id; CONFLICTED when the API errored after a local 'submitted' belief."""
    if errored:
        status = EvidenceStatus.CONFLICTED
        level = VerificationLevel.L1_SELF_REPORTED
        method = "api_response"
        ref = error_text
    else:
        status = EvidenceStatus.VERIFIED
        level = VerificationLevel.L3_EXTERNAL_SOURCE
        method = "authenticated_api_response"
        ref = f"proposal:{proposal_id}"
    ev = Evidence.create(
        source="upwork", evidence_type="platform_submission", subject_type="opportunity",
        subject_id=subject_id, external_id=proposal_id or "",
        status=status, verification_method=method, verification_level=level,
        observed_at=time.time(), source_reference=f"upwork:/proposals/{proposal_id}",
        raw_reference=ref, provenance={"producer": producer, "method": "authenticated_api_response"},
        metadata={"profile_id": profile_id, "job_id": job_id,
                  "submitted_by": profile_id or "me"},
    )
    return ev


# ── external reconciliation (independent cross-check) ──
def from_external_reconciliation(report, source: str = "reconciliation",
                                 subject_id: str = "", subject_type: str = "payment",
                                 producer: str = "evidence_policy") -> Evidence:
    """Map an independent external reconciliation (e.g. bank statement vs on-chain delta, a
    second source confirming) to a VERIFIED evidence at L4 (independent). This is the ONLY
    escalation that flips a non-affirmative record to affirmative, and it is never driven by the
    LLM. `report` must expose `.verified` (bool) and `.note` (str)."""
    verified = bool(getattr(report, "verified", False))
    status = EvidenceStatus.VERIFIED if verified else EvidenceStatus.UNVERIFIED
    level = VerificationLevel.L4_INDEPENDENT_VERIFICATION if verified else VerificationLevel.L1_SELF_REPORTED
    return Evidence.create(
        source=source, evidence_type="external_reconciliation", subject_type=subject_type,
        subject_id=subject_id,
        status=status, verification_method="external_reconciliation", verification_level=level,
        amount=float(getattr(report, "amount_usd", 0.0) or 0.0), currency="USD",
        observed_at=time.time(),
        source_reference=getattr(report, "reference", f"{source}:reconcile:{subject_id}"),
        raw_reference=getattr(report, "note", ""),
        provenance={"producer": producer, "method": "external_reconciliation"},
        metadata={"reconciled_with": getattr(report, "reconciled_with", "")},
    )


# ── blockchain transaction receipt (cryptographic) ──
def from_blockchain_receipt(report, source: str = "ethereum", subject_id: str = "",
                            wallet_name: str = "", producer: str = "chain_verifier") -> Evidence:
    """Map an on-chain transaction receipt to a VERIFIED evidence at L5 CRYPTOGRAPHIC."""
    verified = bool(getattr(report, "verified", False))
    status = EvidenceStatus.VERIFIED if verified else EvidenceStatus.UNVERIFIED
    level = VerificationLevel.L5_CRYPTOGRAPHIC if verified else VerificationLevel.L1_SELF_REPORTED
    return Evidence.create(
        source=source, evidence_type="transaction_receipt", subject_type="airdrop_claim",
        subject_id=subject_id, external_id=wallet_name,
        status=status, verification_method="blockchain_transaction_receipt", verification_level=level,
        amount=float(getattr(report, "amount_usd", 0.0) or 0.0), currency="USD",
        observed_at=time.time(),
        source_reference=getattr(report, "tx_hash", f"{source}:receipt:{wallet_name}"),
        raw_reference=getattr(report, "note", ""),
        provenance={"producer": producer, "method": "transaction_receipt"},
        metadata={"tx_hash": getattr(report, "tx_hash", ""),
                  "block_number": getattr(report, "block_number", 0)},
    )
