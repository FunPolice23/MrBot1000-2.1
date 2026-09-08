"""agents/proposal_reviewer.py — Pre-submission review gate (A1).

Before any proposal is allowed to hit the Upwork API, it must pass this gate.
The gate answers three questions the operator explicitly required:

  1. Is it FINISHED / no errors?  -> AnalystWorker code/proposal metrics
                                   (clarity, structure, missing sections).
  2. Does it MEET THE REQUIREMENTS of the work requested?
                                   -> requirements-coverage check that extracts
                                      the job's stated requirements (bullets,
                                      "must/should/need to", numbered list) and
                                      verifies the draft addresses each one.
  3. Is it safe to submit?        -> TrustBoundary already enforces human
                                   confirmation; this gate is the *content*
                                   quality bar, not the auth bar.

Design: the gate is model-optional. If an AnalystWorker is provided it uses
LLM-assisted analysis; otherwise it falls back to deterministic heuristics so
the pipeline can still run (and tests can run) without network/keys.

The gate NEVER submits. It only returns a ReviewResult the pipeline uses to
decide: block, or pass to the human-confirm step, then to the client.
"""

import re
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ReviewResult:
    can_submit: bool
    coverage_score: float = 0.0      # fraction of requirements addressed (0-1)
    quality_score: float = 0.0       # from AnalystWorker if available
    missing_requirements: List[str] = field(default_factory=list)
    missing_sections: List[str] = field(default_factory=list)
    potential_issues: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    reviewed_at: float = field(default_factory=time.time)

    @property
    def summary(self) -> str:
        bits = []
        if self.missing_requirements:
            bits.append(f"MISSING REQ({len(self.missing_requirements)}): "
                        + "; ".join(self.missing_requirements[:3]))
        if self.missing_sections:
            bits.append(f"MISSING SECTIONS: " + ", ".join(self.missing_sections[:3]))
        if self.potential_issues:
            bits.append(f"ISSUES: " + "; ".join(self.potential_issues[:2]))
        if not bits:
            bits.append(f"OK coverage={self.coverage_score:.0%} "
                        f"quality={self.quality_score:.0%}")
        return " | ".join(bits)


# Patterns that signal a stated requirement in a job posting.
_REQ_LINE_PATTERNS = [
    re.compile(r"^\s*[-*]\s+(.+)$", re.M),                 # bullet lists
    re.compile(r"^\s*\d+[.)]\s+(.+)$", re.M),               # numbered lists
    re.compile(r"(?:must|need(?:s|ed)?\s+(?:to\s+)?|should|require[ds]?\s+(?:to\s+)?|have to)\s+([^.;\n]{6,200})",
               re.I),                                       # "must/should/need to ..."
]
# Section markers a good proposal/cover should contain. Match on word STEMS
# (not whole-word) so natural forms — "Deliverables", "delivering", "providing",
# "includes", "approaches" — are not falsely flagged as missing.
_EXPECTED_SECTIONS = [
    ("understanding", r"understand\w*"),
    ("approach",      r"approach\w*|plan\w*|step\w*|process\w*|i'?ll|i will"),
    ("deliverable",   r"deliver\w*|provid\w*|includ\w*"),
    ("timeline",      r"timeline\w*|within|by \w|day\w*|hour\w*|turnaround"),
]
_MIN_COVER_CHARS = 200      # a one-line cover is not "finished"
_MIN_COVER_CHARS_HARD = 80  # below this it's not submittable at all


def _extract_requirements(job_text: str) -> List[str]:
    """Pull candidate requirement strings from a job posting."""
    if not job_text:
        return []
    reqs: List[str] = []
    for pat in _REQ_LINE_PATTERNS:
        for m in pat.finditer(job_text):
            frag = m.group(1).strip() if m.lastindex else m.group(0).strip()
            frag = frag.strip("*-• \t.")
            if 6 <= len(frag) <= 220:
                reqs.append(frag)
    # de-dupe, keep order
    seen, out = set(), []
    for r in reqs:
        k = r.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _coverage(requirements: List[str], cover: str) -> (float, List[str]):
    """Return (coverage_fraction, missing_list).

    A requirement is 'addressed' if a meaningful keyword from it appears in the
    cover (case-insensitive substring or token overlap). Deterministic, no LLM.
    """
    if not requirements:
        return 1.0, []  # nothing required -> trivially satisfied
    cover_l = cover.lower()
    missing = []
    hit = 0
    for req in requirements:
        rl = req.lower()
        # keyword = the longest non-stopword token, or just check token overlap
        tokens = [t for t in re.findall(r"[a-z0-9]{4,}", rl)
                  if t not in _STOP]
        addressed = any(tok in cover_l for tok in tokens) or rl in cover_l
        if addressed:
            hit += 1
        else:
            missing.append(req)
    return (hit / len(requirements), missing)


_STOP = {
    "must", "should", "need", "needs", "needed", "have", "will", "with", "that",
    "this", "from", "into", "your", "able", "capable", "using", "used", "experience",
    "work", "working", "require", "required", "requires", "please", "would", "could",
    "able", "knowledge", "understanding", "good", "strong", "excellent",
}


class ProposalReviewer:
    """Content-quality + requirements-coverage gate for gig proposals."""

    def __init__(self, analyst=None):
        # analyst: optional AnalystWorker for LLM-assisted quality scoring.
        self.analyst = analyst

    def review(self, job_description: str, cover: str,
               job_title: str = "") -> ReviewResult:
        """Run the full gate. Returns a ReviewResult (never raises)."""
        notes: List[str] = []
        issues: List[str] = []

        cover = (cover or "").strip()
        if len(cover) < _MIN_COVER_CHARS_HARD:
            return ReviewResult(
                can_submit=False,
                coverage_score=0.0,
                potential_issues=["Cover too short to be a real proposal"],
                notes=["Cover below hard minimum length"],
            )

        # 1) Requirements coverage (deterministic).
        requirements = _extract_requirements(job_description or "")
        coverage, missing = _coverage(requirements, cover)

        # 2) Section completeness (deterministic heuristic).
        missing_sections = []
        for name, pat in _EXPECTED_SECTIONS:
            if not re.search(pat, cover, re.I):
                missing_sections.append(name)

        # 3) Quality via AnalystWorker if available.
        quality = 0.0
        if self.analyst is not None:
            try:
                metrics = self.analyst.analyze_proposal(cover,
                                                         proposal_id=job_title or "review")
                quality = float(getattr(metrics, "quality_score", 0.0) or 0.0)
                missing_sections.extend(getattr(metrics, "missing_sections", []) or [])
                issues.extend(getattr(metrics, "potential_bugs", []) or [])
                if not getattr(metrics, "can_submit", True):
                    issues.append("Analyst flagged proposal as not submittable")
            except Exception as e:
                notes.append(f"analyst review skipped: {e}")

        # 4) Decision.
        # Hard blocks: no requirements addressed, or cover far too short to be real.
        hard_fail = (requirements and coverage < 0.34) or len(cover) < _MIN_COVER_CHARS_HARD
        if hard_fail:
            issues.append("Does not meet stated requirements / not finished")

        # Soft quality bar: below the comfortable length but still submittable if
        # it meets requirements + sections. Warn, don't block.
        if _MIN_COVER_CHARS_HARD <= len(cover) < _MIN_COVER_CHARS:
            notes.append("Cover is short; consider expanding before submitting")

        can = not hard_fail and coverage >= 0.67
        # missing_sections alone is a soft warning, not a hard block, unless
        # the proposal is also short on coverage. Require at least approach +
        # deliverable sections for a real submission.
        required_sections = {"approach", "deliverable"}
        missing_required = required_sections.intersection(set(missing_sections))
        if missing_required:
            can = False
            issues.append(f"Missing required sections: {', '.join(missing_required)}")

        return ReviewResult(
            can_submit=bool(can),
            coverage_score=round(coverage, 3),
            quality_score=round(quality, 3),
            missing_requirements=missing,
            missing_sections=missing_sections,
            potential_issues=issues,
            notes=notes,
        )
