"""Evidence helpers used by earning lifecycle orchestration."""

from __future__ import annotations

from typing import Any, Optional


def build_manual_attestation(note: str, amount: float) -> Optional[dict]:
    """Build pending operator evidence; it is never affirmative verification."""
    reference = (note or "").strip()
    if not reference:
        return None
    return {
        "method": "manual_reference",
        "verified": False,
        "expected_usd": float(amount or 0.0),
        "observed_usd": float(amount or 0.0),
        "reference": reference,
        "note": (
            "operator-attested reference "
            "(pending independent verification)"
        ),
        "verified_at": None,
    }


def _verification_level(verification: Any) -> Optional[int]:
    """Read the verification trust level (L0..L5) off a state's verification record.

    Accepts either an ``Evidence.to_dict()`` mapping (``verification_level`` is
    persisted as an int) or an ``Evidence`` object. Returns ``None`` when the
    record carries no level at all — the legacy self-report dicts produced by
    ``build_manual_attestation`` have no level and no status.
    """
    if isinstance(verification, dict):
        raw = verification.get("verification_level")
    else:
        raw = getattr(verification, "verification_level", None)
    if raw is None:
        return None
    try:
        return int(getattr(raw, "value", raw))
    except (TypeError, ValueError):
        return None


# The trust floor for a *financial* decision. A payment that only reached L1
# (self-reported / operator attestation) is not evidence that money arrived, so
# it must not unlock a ramp win or be treated as realised revenue. This mirrors
# ``Evidence.is_verified`` and ``evidence_policy``'s revenue rule.
AFFIRMATIVE_MIN_LEVEL = 3  # VerificationLevel.L3_EXTERNAL_SOURCE


def is_affirmative_verification(state: Any) -> bool:
    """Return true only for VERIFIED/PARTIALLY_VERIFIED payment evidence that
    also clears the external-source trust floor (L3).

    Trust level is part of the verdict, not an optional extra. Before this check
    existed, a store-less lifecycle reached ``mark_paid_verified``'s "no store"
    branch, which flipped ``status`` to ``paid`` on ANY affirmative Evidence —
    including an L1 ``manual_attestation`` (operator-typed transaction
    reference). ``is_affirmative_verification`` then returned True for that
    state, so the caller credited a submission-ramp WIN from self-reported
    evidence. The ramp win-rate is the counter that unlocks auto-submission, so
    a fabricated or unverified payout could talk the system into submitting
    real proposals with no human in the loop. Verified by execution: an L1
    manual attestation on a store-less tracker produced
    ``status='paid'`` / ``is_affirmative_verification=True``.

    A record with no level at all fails closed (None is not >= L3).
    """
    if state is None:
        return False
    verification = getattr(state, "verification", None)
    if not verification:
        return False
    status = (
        verification.get("status")
        if isinstance(verification, dict)
        else getattr(verification, "status", None)
    )
    # `status` may be an EvidenceStatus enum rather than a plain string. Compare
    # on its `.value` so an Evidence *object* is handled the same as its
    # to_dict() form — str(EvidenceStatus.VERIFIED) is 'EvidenceStatus.VERIFIED'
    # on Python 3.14, which would never match the literal set below.
    status_value = getattr(status, "value", status)
    if str(status_value or "").upper() not in {"VERIFIED", "PARTIALLY_VERIFIED"}:
        return False
    level = _verification_level(verification)
    return level is not None and level >= AFFIRMATIVE_MIN_LEVEL


__all__ = ["build_manual_attestation", "is_affirmative_verification"]
