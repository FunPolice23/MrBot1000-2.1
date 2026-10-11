"""Submission-ramp bookkeeping for earning proposals."""

from __future__ import annotations

from typing import Any


def record_ramp_submission(opportunity: Any, *, memory: Any) -> None:
    """Record an attempt without crediting a win."""
    try:
        from agents.earning.submission_ramp import get_ramp

        ramp = get_ramp(memory)
        ramp.record_submission(getattr(opportunity, "platform", "unknown"))
    except Exception:
        # Bookkeeping must never break a submission path.
        pass


__all__ = ["record_ramp_submission"]
