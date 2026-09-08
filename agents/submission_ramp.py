"""Human-in-the-loop submission ramp (v2.0.34r, Section C2).

Goal: balance speed vs ban risk. The first N proposals per platform require a
human in the loop; only after N submissions with a win-rate at/above threshold
do we allow auto-submit (still gated behind the review gate + TrustBoundary).

Design:
- State lives in the existing ``EarningMemory`` reputation table (success/failed
  counts per platform) — no new file, no drift risk.
- ``SubmissionRamp.requires_human(platform)`` returns True until
  ``submitted >= RAMP_MIN_SUBMISSIONS`` AND ``win_rate >= RAMP_WIN_RATE``.
  Cold-start (no submissions) => always human (safe default).
- When the platform's ``ai_policy`` forbids AI (``ai_disallowed``/``human_only``),
  we FORCE human regardless of ramp — the ramp only *relaxes* when policy allows
  auto, matching TrustBoundary semantics.
- ``record_outcome(platform, accepted)`` writes the win/loss back to reputation
  so the ramp (and WinRateGuard) stay in sync.
- All knobs env-overridable with safe defaults.

This is a *safety* relaxation, not a bypass: ``submit_gig_proposal`` still runs
the ProposalReviewer first, and auto-paths only open when a human has already
confirmed N times with good outcomes.
"""

from __future__ import annotations

import os
from typing import Optional


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return v


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    if not (0.0 <= v <= 1.0):
        return default
    return v


class SubmissionRamp:
    """Per-platform count-based human-confirmation ramp."""

    def __init__(self, memory=None,
                 min_submissions: Optional[int] = None,
                 win_rate_threshold: Optional[float] = None):
        # min submissions before auto-unlock is even considered.
        self.min_submissions = (
            min_submissions if min_submissions is not None
            else _env_int("RAMP_MIN_SUBMISSIONS", 5))
        # win-rate that must be met (alongside the count) to unlock auto.
        self.win_rate_threshold = (
            win_rate_threshold if win_rate_threshold is not None
            else _env_float("RAMP_WIN_RATE", 0.6))
        # Optional EarningMemory for reputation-backed decisions.
        self._memory = memory

    def _platform_key(self, platform: str) -> str:
        return (platform or "unknown").strip().title() or "unknown"

    def _reputation(self, platform: str) -> dict:
        if self._memory is not None:
            try:
                return self._memory.get_platform_reputation(
                    self._platform_key(platform))
            except Exception:
                pass
        return {"success": 0, "failed": 0, "total": 0, "success_rate": 0.0}

    def requires_human(self, platform: str,
                       ai_policy: str = "ai_allowed") -> bool:
        """True => a human confirmation is required before submitting.

        Forces human when:
          - platform AI policy is not ``ai_allowed`` (never auto under
            ai_disallowed / human_only), OR
          - cold-start: fewer than ``min_submissions`` submitted, OR
          - win-rate below ``win_rate_threshold`` given enough samples.
        """
        # Policy wins: if the platform forbids AI, the ramp can't relax.
        if ai_policy in ("ai_disallowed", "human_only"):
            return True

        rep = self._reputation(platform)
        total = int(rep.get("total", 0) or 0)
        rate = float(rep.get("success_rate", 0.0) or 0.0)

        # Cold-start: not enough samples -> stay human.
        if total < self.min_submissions:
            return True
        # Enough samples but weak win-rate -> stay human.
        if rate < self.win_rate_threshold:
            return True
        # Met both gates -> auto allowed (review gate still runs in pipeline).
        return False

    def record_outcome(self, platform: str, accepted: bool) -> None:
        """DEPRECATED (H39 fix, v2.0.34u): do NOT use for the submit-time call —
        a submission is not an acceptance. This now records only a *submission
        attempt* (no success/failure), matching `record_submission`. For the real
        accept/reject, call `record_accept` / `record_reject` when the outcome is
        actually known (paid / rejected / failed).
        """
        self.record_submission(platform)

    def record_submission(self, platform: str) -> None:
        """Record a proposal *submission* (not an acceptance). Bumps the attempt
        count so the cold-start gate can progress, without inflating win-rate.
        """
        if self._memory is None:
            return
        try:
            self._memory.record_attempt(self._platform_key(platform))
        except Exception:
            pass

    def record_accept(self, platform: str, revenue: float = 0.0) -> None:
        """Record a *real* acceptance/win (proposal was paid/accepted)."""
        if self._memory is None:
            return
        try:
            self._memory.record_win(self._platform_key(platform), revenue)
        except Exception:
            pass

    def record_reject(self, platform: str) -> None:
        """Record a *real* rejection/loss (proposal was rejected/failed)."""
        if self._memory is None:
            return
        try:
            self._memory.record_loss(self._platform_key(platform))
        except Exception:
            pass

    def status(self, platform: str, ai_policy: str = "ai_allowed") -> dict:
        rep = self._reputation(platform)
        return {
            "platform": self._platform_key(platform),
            "total": int(rep.get("total", 0) or 0),
            "success_rate": float(rep.get("success_rate", 0.0) or 0.0),
            "min_submissions": self.min_submissions,
            "win_rate_threshold": self.win_rate_threshold,
            "requires_human": self.requires_human(platform, ai_policy),
        }


# Module-level singleton (lazy, like other agents). Injected memory is set once
# at startup by the pipeline/main; until then it operates in cold-start (human).
_RAMP: Optional[SubmissionRamp] = None
_RAMP_LOCK = __import__("threading").Lock()


def get_ramp(memory=None) -> SubmissionRamp:
    global _RAMP
    if _RAMP is None:
        with _RAMP_LOCK:
            if _RAMP is None:
                _RAMP = SubmissionRamp(memory=memory)
    elif memory is not None and _RAMP._memory is None:
        _RAMP._memory = memory
    return _RAMP


def set_ramp_memory(memory) -> None:
    """Wire an EarningMemory instance into the singleton (call at startup)."""
    global _RAMP
    if _RAMP is None:
        _RAMP = SubmissionRamp(memory=memory)
    else:
        _RAMP._memory = memory
