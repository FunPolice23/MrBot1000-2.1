"""agents/evidence.py — First-class Evidence / provenance domain objects (v2.0.34aq).

Design (from architecture review): an EVENT is what the system says happened; EVIDENCE
supports that claim; VERIFICATION decides whether the evidence is sufficient. This module
is the shared vocabulary every subsystem emits into the EvidenceStore instead of inventing
its own meaning of "success".

Key principles:
- Evidence is IMMUTABLE. Status is never overwritten in place; `verify()` appends a
  VerificationResult to an append-only `history` and returns a NEW Evidence with the
  derived status. The original record is preserved for audits/migrations.
- `status` is a 6-value enum (NOT a bool): UNVERIFIED | PARTIALLY_VERIFIED | VERIFIED |
  REJECTED | CONFLICTED | EXPIRED. `CONFLICTED` matters: a local "submitted=True" plus an
  API HTTP 500 means we DON'T know — it is conflicted and reconcilable later, not merely
  unverified.
- `verification_level` (L0..L5) encodes trust: local self-report (L1) vs external API (L3)
  vs cryptographic on-chain receipt (L5). The revenue policy uses it to decide inclusion.
- `verification_method` is explicit so we can tell a `heuristic`-verified claim apart from a
  `blockchain_transaction_receipt`-verified one (they must NOT have equal trust).
- Monetary evidence is split (gross/fees/gas/tax/other/net) as SEPARATE evidence records
  under one subject so accounting = verified_revenue - verified_expenses with provenance.
- Provenance records producer + version + source + method so we know which verifier made it.

LLM boundary: the LLM may emit a `Claim`/`Observation` only. A deterministic verifier turns
a Claim into Evidence. The LLM is NEVER allowed to construct a VERIFIED Evidence directly.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ──────────────────────────────────────────────────────────────────────
class EvidenceStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    CONFLICTED = "CONFLICTED"
    EXPIRED = "EXPIRED"

    @property
    def is_affirmative(self) -> bool:
        """True if the evidence currently supports the claim (VERIFIED or partial)."""
        return self in (EvidenceStatus.VERIFIED, EvidenceStatus.PARTIALLY_VERIFIED)

    @property
    def is_terminal(self) -> bool:
        return self in (EvidenceStatus.VERIFIED, EvidenceStatus.REJECTED,
                        EvidenceStatus.EXPIRED)


class VerificationLevel(int, Enum):
    """Trust level of the evidence. Higher = stronger external proof.

    L0 UNBSERVED        — no observation at all
    L1 SELF_REPORTED     — local DB / LLM claim / operator says so (lowest trust)
    L2 LOCAL_VALIDATION  — checked against local system state
    L3 EXTERNAL_SOURCE   — an external API/party reported it (Upwork API response)
    L4 INDEPENDENT_VERIFICATION — cross-checked by a second independent source
    L5 CRYPTOGRAPHIC     — on-chain tx receipt + balance delta (irrefutable)
    """
    L0_UNOBSERVED = 0
    L1_SELF_REPORTED = 1
    L2_LOCAL_VALIDATION = 2
    L3_EXTERNAL_SOURCE = 3
    L4_INDEPENDENT_VERIFICATION = 4
    L5_CRYPTOGRAPHIC = 5


# Explicit verification methods (point 5 of the design). The spec's canonical set:
VERIFICATION_METHODS = (
    "local_record",                    # local DB self-report
    "heuristic",                       # rule-based guess (low trust)
    "human_attestation",               # operator testimony
    "human_confirmation",              # operator clicked "yes" (legacy alias)
    "manual_attestation",              # operator-supplied reference (legacy alias)
    "authenticated_api_response",      # a real authenticated platform API replied (Upwork)
    "authenticated_api_lookup",        # a read-back from an authenticated API
    "api_response",                    # generic API response (legacy)
    "platform_transaction",            # a platform-recorded transaction event
    "blockchain_transaction_receipt",  # on-chain tx receipt (cryptographic)
    "blockchain_balance_delta",        # on-chain before/after balance delta (cryptographic)
    "external_reconciliation",         # independent external reconciliation (e.g. bank stmt vs chain)
)

# Deterministic trust ordering of verification methods. This is NOT chosen by the LLM — it is
# policy. Higher confidence => stronger independent proof. Used by Evidence.confidence and the
# revenue policy so a manual/human attestation can NEVER outrank an independently verified payment.
METHOD_CONFIDENCE: Dict[str, float] = {
    "local_record": 0.10,
    "heuristic": 0.20,
    "human_attestation": 0.30,
    "manual_attestation": 0.30,
    "human_confirmation": 0.35,
    "api_response": 0.50,
    "authenticated_api_lookup": 0.60,
    "authenticated_api_response": 0.70,
    "platform_transaction": 0.70,
    "external_reconciliation": 0.85,
    "blockchain_transaction_receipt": 0.95,
    "blockchain_balance_delta": 1.00,
}

def method_confidence(method: str) -> float:
    """Deterministic confidence of a verification method (LLM-independent)."""
    return METHOD_CONFIDENCE.get(method, 0.5)


# ── Verification result (append-only history entry) ─────────────────────────────
@dataclass
class VerificationResult:
    """One verification attempt. Appended to Evidence.history; never mutated."""
    status: EvidenceStatus
    method: str
    level: VerificationLevel
    timestamp: float = field(default_factory=time.time)
    actor: str = ""          # who/what verified (e.g. "chain_verifier@2.0.34l", "human:cecil")
    note: str = ""
    raw_reference: str = ""  # tx hash, API response snippet, etc. (redact before LLM!)


# ── The Evidence record (immutable) ─────────────────────────────────────────────
@dataclass
class Evidence:
    """A first-class, immutable evidence/provenance record.

    Construct via `Evidence.create(...)` (assigns id + recorded_at) or directly in tests.
    To change status, call `evidence.verify(result)` which returns a NEW Evidence with the
    result appended to `history` and `status`/`verification_level`/`verification_method`
    derived from the latest result. The original object is never mutated.
    """
    # Identity / classification
    source: str                       # "upwork" | "ethereum" | "system" | "operator" | ...
    evidence_type: str                # "platform_submission" | "transaction_receipt" | ...
    subject_type: str = "opportunity" # "opportunity" | "airdrop_claim" | "payment" | ...
    subject_id: str = ""
    external_id: str = ""             # proposal-123 / 0x... / platform event id
    id: str = ""
    parent_evidence_id: str = ""      # links a sub-evidence (e.g. fee) to its payment

    # Time
    observed_at: float = field(default_factory=time.time)
    recorded_at: float = field(default_factory=time.time)

    # Verification state (derived from history; latest result wins for display)
    status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    verification_method: str = "local_record"
    verification_level: VerificationLevel = VerificationLevel.L1_SELF_REPORTED

    # Monetary (optional; for money-type evidence). Net provenance lives in SEPARATE records.
    amount: float = 0.0
    currency: str = ""
    gross_amount: float = 0.0
    fees: float = 0.0
    gas: float = 0.0
    tax_expense: float = 0.0
    other_expenses: float = 0.0

    # References / provenance / free metadata
    source_reference: str = ""        # "upwork:/proposals/123"
    raw_reference: str = ""           # redact before sending to LLM
    metadata: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    history: List[VerificationResult] = field(default_factory=list)

    # ── Construction ──
    @classmethod
    def create(cls, **kwargs) -> "Evidence":
        now = time.time()
        if "id" not in kwargs:
            kwargs["id"] = "ev_" + uuid.uuid4().hex[:20]
        kwargs.setdefault("recorded_at", now)
        kwargs.setdefault("observed_at", now)
        prov = kwargs.setdefault("provenance", {})
        prov.setdefault("producer_version", os.getenv("MRBOT_VERSION", "2.0.34aq"))
        return cls(**kwargs)

    # ── Immutable transition ──
    def verify(self, result: VerificationResult) -> "Evidence":
        """Return a NEW Evidence with `result` appended; status/level/method reflect it.

        The caller SHOULD persist the returned record (EvidenceStore is append-only). The
        original object is unchanged. CONFLICTED/REJECTED/EXPIRED are sticky unless a later
        result explicitly re-opens (e.g. a reconciliation result can move CONFLICTED->VERIFIED).
        """
        hist = list(self.history) + [result]
        new = Evidence(
            source=self.source, evidence_type=self.evidence_type,
            subject_type=self.subject_type, subject_id=self.subject_id,
            external_id=self.external_id, id=self.id,
            parent_evidence_id=self.parent_evidence_id,
            observed_at=self.observed_at, recorded_at=self.recorded_at,
            status=result.status, verification_method=result.method,
            verification_level=result.level,
            amount=self.amount, currency=self.currency,
            gross_amount=self.gross_amount, fees=self.fees, gas=self.gas,
            tax_expense=self.tax_expense, other_expenses=self.other_expenses,
            source_reference=self.source_reference, raw_reference=self.raw_reference,
            metadata=dict(self.metadata), provenance=dict(self.provenance),
            history=hist,
        )
        return new

    # ── Helpers ──
    def is_verified(self, min_level: VerificationLevel = VerificationLevel.L3_EXTERNAL_SOURCE) -> bool:
        """Affirmative AND at/above the required trust level."""
        return self.status.is_affirmative and self.verification_level >= min_level

    @property
    def confidence(self) -> float:
        """Deterministic trust in this evidence, derived from its verification METHOD (policy),
        NOT from any LLM score. A manual/human attestation can never outrank an independently
        verified payment (see METHOD_CONFIDENCE). Range 0..1."""
        return method_confidence(self.verification_method)

    def dup_key(self) -> str:
        """Content fingerprint for duplicate detection. Two records describing the SAME
        observation (same source/type/subject/id/amount/method/level/status) collide even if
        their row `id` differs — so the store can flag re-submissions without overwriting."""
        import hashlib
        parts = (
            self.source, self.evidence_type, self.subject_type, self.subject_id,
            self.external_id, f"{self.amount:.4f}", self.currency, self.status.value,
            self.verification_method, int(self.verification_level),
        )
        return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:20]

    # ── Deterministic transition helpers (NOT for LLM use) ──
    # These append a VerificationResult and return a NEW Evidence. Only deterministic
    # verifiers should call them; they are what turn a Claim into trusted Evidence.
    def mark_verified(self, method: str, level: VerificationLevel,
                      actor: str = "", note: str = "", raw_reference: str = "") -> "Evidence":
        return self.verify(VerificationResult(
            status=EvidenceStatus.VERIFIED, method=method, level=level,
            actor=actor, note=note, raw_reference=raw_reference))

    def mark_rejected(self, method: str, level: VerificationLevel,
                      actor: str = "", note: str = "") -> "Evidence":
        return self.verify(VerificationResult(
            status=EvidenceStatus.REJECTED, method=method, level=level,
            actor=actor, note=note))

    def mark_conflicted(self, method: str, level: VerificationLevel,
                        actor: str = "", note: str = "") -> "Evidence":
        return self.verify(VerificationResult(
            status=EvidenceStatus.CONFLICTED, method=method, level=level,
            actor=actor, note=note))

    def mark_expired(self, method: str = "local_record",
                     level: VerificationLevel = VerificationLevel.L1_SELF_REPORTED,
                     actor: str = "", note: str = "") -> "Evidence":
        return self.verify(VerificationResult(
            status=EvidenceStatus.EXPIRED, method=method, level=level,
            actor=actor, note=note))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "external_id": self.external_id,
            "parent_evidence_id": self.parent_evidence_id,
            "observed_at": self.observed_at,
            "recorded_at": self.recorded_at,
            "status": self.status.value,
            "verification_method": self.verification_method,
            "verification_level": int(self.verification_level),
            "amount": self.amount,
            "currency": self.currency,
            "gross_amount": self.gross_amount,
            "fees": self.fees,
            "gas": self.gas,
            "tax_expense": self.tax_expense,
            "other_expenses": self.other_expenses,
            "source_reference": self.source_reference,
            "raw_reference": self.raw_reference,
            "metadata": self.metadata,
            "provenance": self.provenance,
            "history": [
                {"status": h.status.value, "method": h.method, "level": int(h.level),
                 "timestamp": h.timestamp, "actor": h.actor, "note": h.note,
                 "raw_reference": h.raw_reference}
                for h in self.history
            ],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Evidence":
        hist = [
            VerificationResult(
                status=EvidenceStatus(h["status"]),
                method=h.get("method", "local_record"),
                level=VerificationLevel(h.get("level", 1)),
                timestamp=h.get("timestamp", 0.0),
                actor=h.get("actor", ""),
                note=h.get("note", ""),
                raw_reference=h.get("raw_reference", ""),
            )
            for h in d.get("history", [])
        ]
        return cls(
            source=d["source"], evidence_type=d["evidence_type"],
            subject_type=d.get("subject_type", "opportunity"),
            subject_id=d.get("subject_id", ""),
            external_id=d.get("external_id", ""),
            id=d.get("id", "ev_" + uuid.uuid4().hex[:20]),
            parent_evidence_id=d.get("parent_evidence_id", ""),
            observed_at=d.get("observed_at", 0.0),
            recorded_at=d.get("recorded_at", 0.0),
            status=EvidenceStatus(d.get("status", "UNVERIFIED")),
            verification_method=d.get("verification_method", "local_record"),
            verification_level=VerificationLevel(d.get("verification_level", 1)),
            amount=d.get("amount", 0.0),
            currency=d.get("currency", ""),
            gross_amount=d.get("gross_amount", 0.0),
            fees=d.get("fees", 0.0),
            gas=d.get("gas", 0.0),
            tax_expense=d.get("tax_expense", 0.0),
            other_expenses=d.get("other_expenses", 0.0),
            source_reference=d.get("source_reference", ""),
            raw_reference=d.get("raw_reference", ""),
            metadata=d.get("metadata", {}),
            provenance=d.get("provenance", {}),
            history=hist,
        )


# ── Backward-compat alias (payout_verifier.VerificationEvidence) ─────────────────
class VerificationEvidence(Evidence):
    """Legacy alias. `payout_verifier` emits Evidence; old code reading
    `VerificationEvidence(method=..., verified=...)` still works via `.summary`."""

    @property
    def verified(self) -> bool:
        return self.status == EvidenceStatus.VERIFIED

    @property
    def summary(self) -> str:
        if self.status == EvidenceStatus.VERIFIED:
            return (f"VERIFIED via {self.verification_method}: expected ${self.gross_amount or self.amount:.2f}, "
                    f"observed ${self.amount:.2f}")
        return f"UNVERIFIED ({self.verification_method}): {self.raw_reference or 'no evidence'}"


# ── Claim / Observation (what the LLM may emit; NEVER trusted directly) ──────────
@dataclass
class Claim:
    """An unverified assertion. The LLM / a subsystem proposes this; a deterministic
    verifier decides whether it becomes Evidence. The LLM MUST NOT instantiate Evidence
    with status=VERIFIED — it emits a Claim instead."""
    source: str
    evidence_type: str
    subject_type: str = "opportunity"
    subject_id: str = ""
    external_id: str = ""
    assertion: str = ""          # free-text "the client appears to have accepted the work"
    confidence: float = 0.0
    observed_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── EvidenceRequirement (policy half) ────────────────────────────────────────────
@dataclass
class EvidenceRequirement:
    """What evidence a lifecycle transition needs before it may fire."""
    transition: str                       # "SUBMITTED->PAID"
    required_types: List[str]            # ["platform_submission","completion_confirmation","payment_confirmation"]
    min_level: VerificationLevel = VerificationLevel.L3_EXTERNAL_SOURCE
    allow_manual_fallback: bool = False   # if True, manual_attestation counts (but not in hard revenue)
    note: str = ""


def make_money_evidence_set(gross: float, currency: str, fees: float = 0.0, gas: float = 0.0,
                            llm_cost: float = 0.0, other: float = 0.0,
                            source: str = "system", subject_id: str = "",
                            level: VerificationLevel = VerificationLevel.L1_SELF_REPORTED,
                            method: str = "local_record") -> List[Evidence]:
    """Split one payment into provenance-preserving component Evidence records.

    Gross payment + each expense is its OWN evidence; `parent_evidence_id` links them so
    accounting can compute net = verified_revenue - verified_expenses without losing the trail.
    When `level >= EXTERNAL` (the components derive from a verified external payment) each
    component is marked VERIFIED via an appended VerificationResult, so the accounting layer
    counts them as verified expenses/revenue rather than pending.
    """
    out: List[Evidence] = []
    payment_id = "ev_" + uuid.uuid4().hex[:20]
    verified = level >= VerificationLevel.L3_EXTERNAL_SOURCE
    vres = VerificationResult(status=EvidenceStatus.VERIFIED, method=method, level=level,
                              actor=f"{source}:money_split", note="derived from verified payment")
    gross_ev = Evidence.create(
        source=source, evidence_type="payment_gross", subject_type="payment",
        subject_id=subject_id, external_id=payment_id, parent_evidence_id=payment_id,
        amount=gross, currency=currency, gross_amount=gross,
        verification_method=method, verification_level=level,
        source_reference=f"{source}:payment:{subject_id}",
    )
    if verified:
        gross_ev = gross_ev.verify(vres)
    out.append(gross_ev)
    for kind, val in (("payment_fee", fees), ("payment_gas", gas),
                      ("payment_llm_cost", llm_cost), ("payment_other_expense", other)):
        if val and val > 0:
            e = Evidence.create(
                source=source, evidence_type=kind, subject_type="payment",
                subject_id=subject_id, parent_evidence_id=payment_id,
                amount=val, currency=currency, other_expenses=val,
                verification_method=method, verification_level=level,
                source_reference=f"{source}:{kind}:{subject_id}",
            )
            if verified:
                e = e.verify(vres)
            out.append(e)
    return out
