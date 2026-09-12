"""First-class contradiction cases for competing claims."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from agents.cognition import Claim


class ContradictionStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    BLOCKED = "blocked"


@dataclass
class ContradictionCase:
    subject: str
    claims: List[Claim]
    case_id: str = field(default_factory=lambda: "conf_" + uuid.uuid4().hex[:20])
    status: ContradictionStatus = ContradictionStatus.OPEN
    resolution: str = ""
    resolution_evidence_ids: List[str] = field(default_factory=list)
    blocked_reason: str = ""

    def resolve(self, selected_claim: Claim, evidence_ids: List[str]) -> bool:
        if self.status is not ContradictionStatus.OPEN:
            return False
        if selected_claim not in self.claims:
            raise ValueError("selected claim is not part of this contradiction")
        if not evidence_ids:
            return False
        self.status = ContradictionStatus.RESOLVED
        self.resolution = selected_claim.text
        self.resolution_evidence_ids = list(evidence_ids)
        return True

    def block(self, reason: str) -> None:
        if self.status is ContradictionStatus.OPEN:
            self.status = ContradictionStatus.BLOCKED
            self.blocked_reason = reason.strip() or "contradiction unresolved"

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "subject": self.subject,
            "status": self.status.value,
            "claims": [claim.__dict__ for claim in self.claims],
            "resolution": self.resolution,
            "resolution_evidence_ids": self.resolution_evidence_ids,
            "blocked_reason": self.blocked_reason,
        }


def open_contradiction(subject: str, claims: List[Claim]) -> ContradictionCase:
    if not subject.strip() or len(claims) < 2:
        raise ValueError("a contradiction requires a subject and at least two claims")
    return ContradictionCase(subject=subject, claims=list(claims))


__all__ = ["ContradictionCase", "ContradictionStatus", "open_contradiction"]