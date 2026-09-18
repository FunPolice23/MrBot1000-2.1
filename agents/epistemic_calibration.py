"""agents/epistemic_calibration.py — Deterministic confidence classification.

Maps a claim's ledger state to an epistemic label and a confidence number the
model can be told to respect. Everything here is policy, computed from the
ledger and the deterministic ``evidence.METHOD_CONFIDENCE`` table — the model
never rates itself.

The output is used two ways:

* ``disclaimer`` / ``context_note`` — a short, honest framing injected into the
  model's context so it does not overstate unverified knowledge;
* ``confidence`` — a number a caller can surface in the UI.

Boundary: this classifies, it does not decide. It never promotes a claim to
verified and never lets a model's own words raise its confidence.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from agents.evidence import VerificationLevel, method_confidence
from agents.fact_ledger import ClaimStatus, LedgerEntry


class EpistemicLevel(str, Enum):
    UNKNOWN = "unknown"
    SPECULATIVE = "speculative"      # proposed, no evidence
    PLAUSIBLE = "plausible"          # supported by weak evidence
    CORROBORATED = "corroborated"    # verified by an external source (L3/L4)
    CONFIRMED = "confirmed"          # verified cryptographically (L5)
    REFUTED = "refuted"
    OVERRIDDEN = "overridden"        # superseded by operator authority


# Deterministic floor/ceiling so a weak method can never masquerade as strong.
_PLAUSIBLE_CEILING = 0.5
_SPECULATIVE_CONFIDENCE = 0.1


def classify(entry: Optional[LedgerEntry]) -> EpistemicLevel:
    """Classify a ledger entry's epistemic standing (deterministic)."""
    if entry is None:
        return EpistemicLevel.UNKNOWN
    if entry.status == ClaimStatus.REFUTED:
        return EpistemicLevel.REFUTED
    if entry.status == ClaimStatus.SUPERSEDED:
        return EpistemicLevel.OVERRIDDEN
    if entry.status == ClaimStatus.PROPOSED:
        return EpistemicLevel.SPECULATIVE
    if entry.status == ClaimStatus.SUPPORTED:
        return EpistemicLevel.PLAUSIBLE
    if entry.status == ClaimStatus.VERIFIED:
        if int(entry.verification_level) >= int(VerificationLevel.L5_CRYPTOGRAPHIC):
            return EpistemicLevel.CONFIRMED
        return EpistemicLevel.CORROBORATED
    return EpistemicLevel.UNKNOWN


def confidence(entry: Optional[LedgerEntry]) -> float:
    """Deterministic confidence in [0, 1] for a ledger entry."""
    if entry is None:
        return 0.0
    level = classify(entry)
    if level in (EpistemicLevel.UNKNOWN, EpistemicLevel.REFUTED,
                 EpistemicLevel.OVERRIDDEN):
        return 0.0
    if level == EpistemicLevel.SPECULATIVE:
        return _SPECULATIVE_CONFIDENCE
    base = method_confidence(entry.method)
    if level == EpistemicLevel.PLAUSIBLE:
        return min(base, _PLAUSIBLE_CEILING)
    # CORROBORATED / CONFIRMED: evidence-backed, use the method's confidence.
    return base


def disclaimer(entry: Optional[LedgerEntry]) -> str:
    """A short, honest framing for a single claim (for prompt injection)."""
    level = classify(entry)
    if level == EpistemicLevel.UNKNOWN:
        return "I have no verified information about this."
    if level == EpistemicLevel.SPECULATIVE:
        return "This is an unverified claim; do not present it as fact."
    if level == EpistemicLevel.PLAUSIBLE:
        return "This is only weakly supported; treat it as tentative."
    if level == EpistemicLevel.CORROBORATED:
        return "This is corroborated by an external source."
    if level == EpistemicLevel.CONFIRMED:
        return "This is confirmed by cryptographic evidence."
    if level == EpistemicLevel.REFUTED:
        return "This claim has been refuted; do not repeat it as true."
    if level == EpistemicLevel.OVERRIDDEN:
        return "The operator has overridden this claim; defer to the operator."
    return ""


def context_note(entries: List[LedgerEntry], max_claims: int = 8) -> str:
    """Aggregate epistemic framing for a set of claims (for prompt injection).

    Only claims that are still standing (not refuted/superseded) are included,
    and the list is bounded so it cannot blow the prompt budget.
    """
    standing = [e for e in entries
                if e is not None
                and e.status not in (ClaimStatus.REFUTED,
                                     ClaimStatus.SUPERSEDED)]
    if not standing:
        return ""
    lines = []
    for entry in standing[:max_claims]:
        lines.append(f"- {entry.statement} [{classify(entry).value}, "
                     f"confidence {confidence(entry):.2f}]")
    return ("EPISTEMIC STATUS (deterministic, not model self-assessment):\n"
            + "\n".join(lines))
