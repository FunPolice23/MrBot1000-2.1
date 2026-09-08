"""agents/provenance.py — Truth-status labels + provenance chain (v2.0.36k).

The LLM may emit observations and claims. The system must NEVER silently
convert an estimate into a fact. Every piece of information carries a truth
status and a provenance chain so the decision layer can weight it correctly.

Truth statuses (ordered by reliability, low → high):
  - ESTIMATE      — rough calculation/guess (never a fact)
  - PREDICTION    — model/statistical forecast (uncertain by nature)
  - OBSERVATION   — raw external data point (unverified)
  - VERIFIED_RESULT — independently confirmed by evidence
  - FACT          — internally recorded ground truth (e.g. a state transition we performed)

Provenance tracks WHO produced WHEN via WHAT METHOD from WHAT SOURCE.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Truth status ───────────────────────────────────────────────────────────────

class TruthStatus(str, Enum):
    ESTIMATE = "estimate"
    PREDICTION = "prediction"
    OBSERVATION = "observation"
    VERIFIED_RESULT = "verified_result"
    FACT = "fact"

    @property
    def reliability_rank(self) -> int:
        """Higher = more reliable. Used to compare/resolve conflicting info."""
        return {
            TruthStatus.ESTIMATE: 1,
            TruthStatus.PREDICTION: 2,
            TruthStatus.OBSERVATION: 3,
            TruthStatus.VERIFIED_RESULT: 4,
            TruthStatus.FACT: 5,
        }[self]


# ── Provenance record ──────────────────────────────────────────────────────────

@dataclass
class ProvenanceRecord:
    """How a piece of information came to be."""
    source: str = ""                        # "upwork", "ollama:gemma-4-E2B", "system", "operator:cecil"
    method: str = ""                        # "web_search", "llm_inference", "state_transition", "evidence_verification"
    reference: str = ""                     # url, evidence_id, transaction hash, etc.
    timestamp: float = field(default_factory=time.time)
    actor: str = ""                         # who/what produced it

    def to_dict(self) -> dict:
        return {
            "source": self.source, "method": self.method,
            "reference": self.reference, "timestamp": self.timestamp, "actor": self.actor,
        }


# ── Information atom ───────────────────────────────────────────────────────────

@dataclass
class InfoAtom:
    """A single piece of information with truth status and provenance."""
    value: Any
    status: TruthStatus
    key: str = ""                           # e.g. "expected_revenue", "platform_acceptance_rate"
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    confidence: float = 0.0                 # 0..1
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key, "value": self.value, "status": self.status.value,
            "provenance": self.provenance.to_dict(), "confidence": self.confidence, "notes": self.notes,
        }

    def is_at_least(self, status: TruthStatus) -> bool:
        """Check if this info meets a minimum reliability threshold."""
        return self.status.reliability_rank >= status.reliability_rank


# ── Provenance chain ────────────────────────────────────────────────────────────

@dataclass
class ProvenanceChain:
    """Ordered chain of records showing how a conclusion was reached."""
    chain_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    records: List[ProvenanceRecord] = field(default_factory=list)

    def add(self, record: ProvenanceRecord) -> None:
        self.records.append(record)

    def to_dict(self) -> dict:
        return {"chain_id": self.chain_id, "records": [r.to_dict() for r in self.records]}


# ── Fact store (opportunity-scoped) ────────────────────────────────────────────

class FactStore:
    """Stores information atoms for one opportunity, grouped by key.
    Never silently upgrades an estimate to a fact."""

    def __init__(self, opportunity_id: str):
        self.opportunity_id = opportunity_id
        self._atoms: Dict[str, List[InfoAtom]] = {}
        self._chain = ProvenanceChain()

    def add(self, atom: InfoAtom) -> None:
        """Add an information atom. Preserves truth status as-is."""
        if atom.key not in self._atoms:
            self._atoms[atom.key] = []
        self._atoms[atom.key].append(atom)
        self._chain.add(atom.provenance)

    def get(self, key: str) -> List[InfoAtom]:
        """Get all atoms for a key."""
        return self._atoms.get(key, [])

    def get_best(self, key: str) -> Optional[InfoAtom]:
        """Get the most reliable atom for a key."""
        atoms = self._atoms.get(key, [])
        if not atoms:
            return None
        return max(atoms, key=lambda a: a.status.reliability_rank)

    def get_best_value(self, key: str, default: Any = None) -> Any:
        """Get the most reliable value for a key."""
        atom = self.get_best(key)
        return atom.value if atom else default

    def has_fact(self, key: str) -> bool:
        """Check if we have a FACT for this key."""
        return any(a.status == TruthStatus.FACT for a in self._atoms.get(key, []))

    def has_verified(self, key: str) -> bool:
        """Check if we have a VERIFIED_RESULT or FACT for this key."""
        return any(a.status in (TruthStatus.VERIFIED_RESULT, TruthStatus.FACT)
                   for a in self._atoms.get(key, []))

    def explain(self, key: str) -> str:
        """Generate a human-readable explanation of what we know about a key."""
        atoms = self._atoms.get(key, [])
        if not atoms:
            return f"No information about '{key}'."
        best = max(atoms, key=lambda a: a.status.reliability_rank)
        return (f"{key} = {best.value} (status: {best.status.value}, "
                f"source: {best.provenance.source}, confidence: {best.confidence:.0%})")

    def to_dict(self) -> dict:
        return {
            "opportunity_id": self.opportunity_id,
            "atoms": {k: [a.to_dict() for a in v] for k, v in self._atoms.items()},
            "chain": self._chain.to_dict(),
        }


__all__ = [
    "TruthStatus",
    "ProvenanceRecord",
    "InfoAtom",
    "ProvenanceChain",
    "FactStore",
]
