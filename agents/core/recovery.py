"""Measurable recovery progress for bounded autonomous retries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Set


@dataclass
class RecoveryTracker:
    max_attempts: int = 3
    attempts: int = 0
    fingerprints: Set[str] = field(default_factory=set)
    evidence_ids: Set[str] = field(default_factory=set)
    history: List[dict] = field(default_factory=list)

    def attempt(self, state_fingerprint: str, evidence_ids: Iterable[str] = ()) -> bool:
        """Accept a retry only when it changes state or adds evidence."""
        if self.attempts >= self.max_attempts:
            return False
        fingerprint = (state_fingerprint or "").strip()
        new_evidence = set(evidence_ids) - self.evidence_ids
        changed_state = bool(fingerprint) and fingerprint not in self.fingerprints
        if not changed_state and not new_evidence:
            return False
        self.attempts += 1
        self.fingerprints.add(fingerprint)
        self.evidence_ids.update(new_evidence)
        self.history.append({
            "attempt": self.attempts,
            "state_fingerprint": fingerprint,
            "new_evidence_ids": sorted(new_evidence),
        })
        return True

    @property
    def exhausted(self) -> bool:
        return self.attempts >= self.max_attempts


__all__ = ["RecoveryTracker"]