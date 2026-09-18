"""agents/operator_override.py — Human authority over model claims.

An operator (the human) may state a fact that outranks anything a model has
claimed. This registry records those statements, keeps them auditable, and lets
deterministic code resolve conflicts in the human's favour.

Hard boundaries, by design:

* An override carries **authority**, not **evidence**. It can SUPERSEDE a
  conflicting model claim in the ledger, but it can never create VERIFIED
  evidence — the ledger's ``attach_evidence`` path is the only route to that,
  and it requires a deterministic verification level.
* Overrides are append-only: issuing and revoking both append revisions, so the
  audit trail cannot be rewritten.
* Nothing here bypasses a human approval gate. An override is the human
  speaking; it does not let automation skip a gate on their behalf.

Conflicts are resolved by scope, deterministically — an active override for a
subject takes precedence over claims about that subject. No model decides.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agents.fact_ledger import ClaimStatus, FactLedger, SourceKind


class OverrideError(Exception):
    """Base class for override violations."""


@dataclass(frozen=True)
class OverrideRecord:
    """One immutable revision of an operator override."""

    override_id: str
    revision: int
    statement: str
    subject_id: str = ""          # "" means the override is global
    issued_by: str = "operator"
    active: bool = True
    issued_at: float = 0.0
    recorded_at: float = 0.0
    note: str = ""

    @property
    def source_kind(self) -> SourceKind:
        # Always human authority — this is the point of the component.
        return SourceKind.OPERATOR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "override_id": self.override_id,
            "revision": self.revision,
            "statement": self.statement,
            "subject_id": self.subject_id,
            "issued_by": self.issued_by,
            "active": self.active,
            "issued_at": self.issued_at,
            "recorded_at": self.recorded_at,
            "note": self.note,
        }


class OperatorOverrideRegistry:
    """Append-only register of human overrides."""

    def __init__(self):
        self._history: Dict[str, List[OverrideRecord]] = {}

    # ── Issuing / revoking ──────────────────────────────────────────────────

    def issue(self, statement: str, subject_id: str = "",
              issued_by: str = "operator", note: str = "") -> OverrideRecord:
        """Record a human statement. This is the only way to create authority."""
        text = str(statement or "").strip()
        if not text:
            raise OverrideError("an override needs a non-empty statement")
        now = time.time()
        rec = OverrideRecord(
            override_id=uuid.uuid4().hex,
            revision=0,
            statement=text,
            subject_id=str(subject_id or ""),
            issued_by=str(issued_by or "operator"),
            active=True,
            issued_at=now,
            recorded_at=now,
            note=note,
        )
        self._history[rec.override_id] = [rec]
        return rec

    def revoke(self, override_id: str, note: str = "") -> OverrideRecord:
        """Deactivate an override (append-only; the record is not deleted)."""
        current = self._current(override_id)
        if not current.active:
            raise OverrideError(f"override {override_id} is already revoked")
        return self._append(current, active=False, note=note)

    def amend(self, override_id: str, statement: str,
              note: str = "") -> OverrideRecord:
        """Replace the text of an active override, keeping the history."""
        current = self._current(override_id)
        if not current.active:
            raise OverrideError("cannot amend a revoked override")
        text = str(statement or "").strip()
        if not text:
            raise OverrideError("an override needs a non-empty statement")
        return self._append(current, statement=text, note=note)

    # ── Queries ─────────────────────────────────────────────────────────────

    def current(self, override_id: str) -> Optional[OverrideRecord]:
        rows = self._history.get(override_id)
        return rows[-1] if rows else None

    def history(self, override_id: str) -> List[OverrideRecord]:
        return list(self._history.get(override_id, []))

    def active(self) -> List[OverrideRecord]:
        return [rows[-1] for rows in self._history.values()
                if rows and rows[-1].active]

    def active_for(self, subject_id: str) -> List[OverrideRecord]:
        """Active overrides that cover a subject (its own, plus global ones)."""
        return [o for o in self.active()
                if o.subject_id == subject_id or o.subject_id == ""]

    # ── Conflict resolution (deterministic) ─────────────────────────────────

    def resolve(self, subject_id: str) -> Optional[OverrideRecord]:
        """Return the operator statement that governs a subject, if any.

        A subject-specific override wins over a global one; ties break on the
        most recently issued.
        """
        candidates = self.active_for(subject_id)
        if not candidates:
            return None
        specific = [o for o in candidates if o.subject_id]
        pool = specific or candidates
        return max(pool, key=lambda o: o.issued_at)

    def apply_to_ledger(self, ledger: FactLedger) -> List[str]:
        """Supersede conflicting *model* claims in the ledger.

        Only claims asserted by a model (``SourceKind.LLM``) that are still
        affirmative are superseded — tool evidence and previously verified
        claims are left alone, because authority does not erase evidence.
        Returns the list of affected claim ids.
        """
        affected: List[str] = []
        for entry in ledger.all_claims():
            if entry.source_kind != SourceKind.LLM:
                continue
            # Already closed: nothing to supersede.
            if entry.status in (ClaimStatus.REFUTED, ClaimStatus.SUPERSEDED):
                continue
            # Evidence-backed: an override carries authority, not evidence, so
            # it must not silently erase a claim that deterministic evidence
            # verified. Overturning that needs an explicit human process.
            if entry.status == ClaimStatus.VERIFIED:
                continue
            override = self.resolve(entry.subject_id)
            if override is None:
                continue
            ledger.supersede_by_reference(
                entry.claim_id, override.override_id,
                note=f"operator override {override.override_id}")
            affected.append(entry.claim_id)
        return affected

    # ── Internals ───────────────────────────────────────────────────────────

    def _current(self, override_id: str) -> OverrideRecord:
        rec = self.current(override_id)
        if rec is None:
            raise OverrideError(f"unknown override: {override_id}")
        return rec

    def _append(self, current: OverrideRecord, *, statement: Optional[str] = None,
                active: Optional[bool] = None, note: str = "") -> OverrideRecord:
        rec = OverrideRecord(
            override_id=current.override_id,
            revision=current.revision + 1,
            statement=current.statement if statement is None else statement,
            subject_id=current.subject_id,
            issued_by=current.issued_by,
            active=current.active if active is None else active,
            issued_at=current.issued_at,
            recorded_at=time.time(),
            note=note,
        )
        self._history[current.override_id].append(rec)
        return rec
