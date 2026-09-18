"""agents/fact_ledger.py — Append-only register of claims and their verification.

The ledger is the authoritative record of WHAT HAS BEEN CLAIMED and HOW STRONGLY
it is supported. It deliberately is NOT writable by a model:

* a model may only PROPOSE a claim (``source_kind=SourceKind.LLM``);
* a claim reaches SUPPORTED/VERIFIED only by attaching Evidence whose
  deterministic ``VerificationLevel`` meets the claim's requirement — or it is
  REFUTED. There is no API that lets a caller hand in a status;
* every state change appends a new immutable revision. Nothing is mutated in
  place, so the audit trail cannot be rewritten after the fact.

This builds on ``agents.evidence`` (``Claim``, ``VerificationLevel``,
``EvidenceStatus``) rather than duplicating it, and preserves the existing
policy that human attestation can never outrank independent verification:
``evidence.METHOD_CONFIDENCE["human_attestation"]`` is 0.30, so an operator
assertion alone cannot satisfy a L3+ requirement.

Deterministic application logic is authoritative here — never model narration.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from agents.evidence import Claim, VerificationLevel


class SourceKind(str, Enum):
    """Who asserted a claim. Only OPERATOR carries human authority."""

    LLM = "llm"
    TOOL = "tool"
    OPERATOR = "operator"
    SYSTEM = "system"


# Deterministic authority ordering. Operator (human) outranks tool evidence,
# which outranks system plumbing, which outranks model narration. This is
# policy, not a model decision.
_SOURCE_AUTHORITY: Dict[SourceKind, int] = {
    SourceKind.OPERATOR: 3,
    SourceKind.TOOL: 2,
    SourceKind.SYSTEM: 1,
    SourceKind.LLM: 0,
}


def source_authority(kind: SourceKind) -> int:
    """Deterministic authority rank for a claim source (higher wins)."""
    return _SOURCE_AUTHORITY.get(kind, 0)


class ClaimStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    VERIFIED = "verified"
    REFUTED = "refuted"
    SUPERSEDED = "superseded"

    @property
    def is_affirmative(self) -> bool:
        """True if the ledger currently treats the claim as standing."""
        return self in (ClaimStatus.SUPPORTED, ClaimStatus.VERIFIED)


# Only these transitions are permitted. Everything else raises, so a claim can
# never loop back (e.g. REFUTED -> VERIFIED) or jump straight to VERIFIED.
_ALLOWED_TRANSITIONS: Dict[ClaimStatus, frozenset] = {
    ClaimStatus.PROPOSED: frozenset({
        ClaimStatus.SUPPORTED, ClaimStatus.VERIFIED,
        ClaimStatus.REFUTED, ClaimStatus.SUPERSEDED,
    }),
    ClaimStatus.SUPPORTED: frozenset({
        ClaimStatus.VERIFIED, ClaimStatus.REFUTED, ClaimStatus.SUPERSEDED,
    }),
    ClaimStatus.VERIFIED: frozenset({
        ClaimStatus.REFUTED, ClaimStatus.SUPERSEDED,
    }),
    ClaimStatus.REFUTED: frozenset({ClaimStatus.SUPERSEDED}),
    ClaimStatus.SUPERSEDED: frozenset(),
}

DEFAULT_MIN_LEVEL = VerificationLevel.L3_EXTERNAL_SOURCE


class LedgerError(Exception):
    """Base class for ledger violations."""


class IllegalTransition(LedgerError):
    """A requested status change is not permitted from the current status."""


class UnsubstantiatedVerification(LedgerError):
    """VERIFIED was requested without evidence that meets the requirement."""


@dataclass(frozen=True)
class LedgerEntry:
    """One immutable revision of one claim. Never mutated after creation."""

    claim_id: str
    revision: int
    statement: str
    source: str
    source_kind: SourceKind
    status: ClaimStatus
    evidence_refs: Tuple[str, ...] = ()
    verification_level: int = 0
    method: str = ""
    required_level: int = int(DEFAULT_MIN_LEVEL)
    subject_type: str = ""
    subject_id: str = ""
    observed_at: float = 0.0
    recorded_at: float = 0.0
    note: str = ""

    @property
    def authority(self) -> int:
        return source_authority(self.source_kind)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "revision": self.revision,
            "statement": self.statement,
            "source": self.source,
            "source_kind": self.source_kind.value,
            "status": self.status.value,
            "evidence_refs": list(self.evidence_refs),
            "verification_level": self.verification_level,
            "method": self.method,
            "required_level": self.required_level,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "observed_at": self.observed_at,
            "recorded_at": self.recorded_at,
            "note": self.note,
        }


class FactLedger:
    """In-memory, append-only claim register.

    Persistence is intentionally left to the caller for now; the invariant that
    matters is that the revision history is append-only and that no caller can
    hand in a VERIFIED status.
    """

    def __init__(self, default_required_level: VerificationLevel = DEFAULT_MIN_LEVEL):
        self._required = default_required_level
        self._history: Dict[str, List[LedgerEntry]] = {}

    # ── Recording ───────────────────────────────────────────────────────────

    def record_claim(self, claim: Claim, source_kind: SourceKind,
                     required_level: Optional[VerificationLevel] = None) -> LedgerEntry:
        """Record a claim as PROPOSED.

        There is deliberately no ``status`` parameter: a model (or any other
        caller) cannot assert a verified fact. Only :meth:`attach_evidence` can
        raise a claim above PROPOSED.
        """
        if not isinstance(claim, Claim):
            raise LedgerError("record_claim expects an agents.evidence.Claim")
        if not str(claim.assertion or "").strip():
            raise LedgerError("a claim needs a non-empty assertion")

        now = time.time()
        entry = LedgerEntry(
            claim_id=uuid.uuid4().hex,
            revision=0,
            statement=str(claim.assertion).strip(),
            source=str(claim.source or source_kind.value),
            source_kind=source_kind,
            status=ClaimStatus.PROPOSED,
            evidence_refs=(),
            verification_level=int(VerificationLevel.L0_UNOBSERVED),
            required_level=int(required_level or self._required),
            subject_type=str(claim.subject_type or ""),
            subject_id=str(claim.subject_id or ""),
            observed_at=float(claim.observed_at or now),
            recorded_at=now,
        )
        self._history[entry.claim_id] = [entry]
        return entry

    def attach_evidence(self, claim_id: str, evidence_ref: str,
                        level: VerificationLevel, method: str = "",
                        note: str = "") -> LedgerEntry:
        """Attach deterministic evidence and advance the claim's status.

        Reaching VERIFIED requires an evidence reference AND a level at or above
        the claim's ``required_level``. Anything weaker becomes SUPPORTED — it
        stands, but it is not a verified fact.
        """
        current = self._latest(claim_id)
        if not str(evidence_ref or "").strip():
            raise UnsubstantiatedVerification(
                "evidence_ref is required; a claim cannot be verified on nothing")
        if current.status in (ClaimStatus.SUPERSEDED,):
            raise IllegalTransition("a superseded claim is closed")

        level = VerificationLevel(level)
        new_status = (ClaimStatus.VERIFIED
                      if int(level) >= int(current.required_level)
                      else ClaimStatus.SUPPORTED)
        # Allow re-attaching evidence at the same effective status so callers can
        # accumulate multiple references without the ledger raising on the second
        # sub-threshold attachment. Only enforce the transition table when the
        # status actually changes.
        if new_status == current.status:
            refs = tuple(list(current.evidence_refs) + [str(evidence_ref)])
            if str(method or "").strip():
                method = str(method)
            return self._append(
                current,
                status=current.status,
                evidence_refs=refs,
                verification_level=max(int(level), int(current.verification_level)),
                method=method or current.method,
                note=note,
            )
        self._assert_transition(current.status, new_status)

        refs = tuple(list(current.evidence_refs) + [str(evidence_ref)])
        return self._append(
            current,
            status=new_status,
            evidence_refs=refs,
            verification_level=max(int(level), int(current.verification_level)),
            method=str(method or current.method),
            note=note,
        )

    def refute(self, claim_id: str, note: str = "",
               method: str = "human_attestation") -> LedgerEntry:
        """Mark a claim as REFUTED. Refutation is terminal for the claim."""
        current = self._latest(claim_id)
        self._assert_transition(current.status, ClaimStatus.REFUTED)
        return self._append(current, status=ClaimStatus.REFUTED,
                            method=method, note=note)

    def supersede(self, claim_id: str, by_claim_id: str, note: str = "") -> LedgerEntry:
        """Mark a claim as SUPERSEDED by a later claim."""
        current = self._latest(claim_id)
        self._assert_transition(current.status, ClaimStatus.SUPERSEDED)
        if not self._history.get(by_claim_id):
            raise LedgerError(f"unknown superseding claim: {by_claim_id}")
        return self._append(current, status=ClaimStatus.SUPERSEDED,
                            note=note or f"superseded by {by_claim_id}")

    def supersede_by_reference(self, claim_id: str, reference: str,
                               note: str = "") -> LedgerEntry:
        """Mark a claim as SUPERSEDED by an external authority reference.

        Used by ``operator_override``: an override is not a ledger claim, so it
        cannot be validated against the claim registry. The reference must still
        be non-empty, and the claim-edge check in :meth:`supersede` is left
        intact for claim-to-claim supersession.
        """
        current = self._latest(claim_id)
        self._assert_transition(current.status, ClaimStatus.SUPERSEDED)
        if not str(reference or "").strip():
            raise LedgerError("a supersession needs a non-empty reference")
        return self._append(current, status=ClaimStatus.SUPERSEDED,
                            note=note or f"superseded by {reference}")

    # ── Queries ─────────────────────────────────────────────────────────────

    def latest(self, claim_id: str) -> Optional[LedgerEntry]:
        rows = self._history.get(claim_id)
        return rows[-1] if rows else None

    def history(self, claim_id: str) -> List[LedgerEntry]:
        """Full immutable revision history for a claim (append-only)."""
        return list(self._history.get(claim_id, []))

    def all_claims(self) -> List[LedgerEntry]:
        return [rows[-1] for rows in self._history.values() if rows]

    def by_status(self, status: ClaimStatus) -> List[LedgerEntry]:
        return [e for e in self.all_claims() if e.status == status]

    def verified_claims(self) -> List[LedgerEntry]:
        """Claims backed by evidence meeting their requirement.

        This is the only set that may be injected as grounding anchors.
        """
        return self.by_status(ClaimStatus.VERIFIED)

    def claims_about(self, subject_id: str) -> List[LedgerEntry]:
        return [e for e in self.all_claims() if e.subject_id == subject_id]

    def prune(self, max_claims: int) -> int:
        """Drop the oldest unverified claims so the ledger cannot grow forever.

        Only PROPOSED and REFUTED entries are eligible. VERIFIED entries are
        grounding anchors and SUPERSEDED entries are the audit trail of an
        operator override, so neither is ever dropped. Returns how many were
        removed. Bounded memory is the one concession to strict append-only
        history; the entries that carry authority are never touched.
        """
        if max_claims <= 0:
            return 0
        excess = len(self._history) - int(max_claims)
        if excess <= 0:
            return 0
        removable = [
            cid for cid, rows in self._history.items()
            if rows and rows[-1].status in (ClaimStatus.PROPOSED,
                                            ClaimStatus.REFUTED)
        ]
        removable.sort(key=lambda cid: self._history[cid][-1].recorded_at)
        removed = 0
        for cid in removable:
            if removed >= excess:
                break
            del self._history[cid]
            removed += 1
        return removed

    # ── Internals ───────────────────────────────────────────────────────────

    def _latest(self, claim_id: str) -> LedgerEntry:
        entry = self.latest(claim_id)
        if entry is None:
            raise LedgerError(f"unknown claim: {claim_id}")
        return entry

    @staticmethod
    def _assert_transition(current: ClaimStatus, new: ClaimStatus) -> None:
        if new == current:
            raise IllegalTransition(f"claim is already {current.value}")
        allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
        if new not in allowed:
            raise IllegalTransition(
                f"{current.value} -> {new.value} is not permitted")

    def _append(self, current: LedgerEntry, *, status: ClaimStatus,
                evidence_refs: Optional[Tuple[str, ...]] = None,
                verification_level: Optional[int] = None,
                method: Optional[str] = None, note: str = "") -> LedgerEntry:
        """Append a new immutable revision derived from ``current``."""
        entry = LedgerEntry(
            claim_id=current.claim_id,
            revision=current.revision + 1,
            statement=current.statement,
            source=current.source,
            source_kind=current.source_kind,
            status=status,
            evidence_refs=(current.evidence_refs if evidence_refs is None
                           else evidence_refs),
            verification_level=(current.verification_level
                                if verification_level is None
                                else verification_level),
            method=current.method if method is None else method,
            required_level=current.required_level,
            subject_type=current.subject_type,
            subject_id=current.subject_id,
            observed_at=current.observed_at,
            recorded_at=time.time(),
            note=note,
        )
        self._history[current.claim_id].append(entry)
        return entry
