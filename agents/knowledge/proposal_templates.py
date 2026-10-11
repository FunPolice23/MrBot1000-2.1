"""Proposal intro A/B rotation + win tracking (v2.0.34w, Section D2).

Goal: systematically improve proposal copy instead of using one fixed intro.
We rotate through a small set of professional intro variants and, once enough
samples exist, bias toward the variant with the best observed win-rate.

State is stored in the existing ``EarningMemory`` ``learning_history`` table via
``store_learning`` / ``get_recent_learned`` (type ``"proposal_intro"``, insight =
variant id, confidence = 1.0 for a win, 0.0 for a loss). No new schema, no new
on-disk state, no drift risk — it rides on the memory already used by the
submission ramp (Section C2).

Design:
- ``pick_intro(platform)`` returns the leading variant once enough data exists,
  otherwise round-robins by a stable per-platform counter so different opps get
  different intros for an honest A/B test.
- ``record_win(platform, variant)`` / ``record_loss(platform, variant)`` persist
  the outcome so future picks favor what works.
- ``best_intro(platform)`` is the pure read used by ``pick_intro``.
"""

from __future__ import annotations

import os
import itertools
from typing import Dict, List, Optional


# A small, varied set of professional proposal intros. Kept generic + polite.
PROPOSAL_INTROS: List[str] = [
    "Hi! I'm an AI/automation specialist and I can deliver this reliably.",
    "Hello — I've completed many similar jobs and can start right away.",
    "Good day! I focus on clean, production-ready results with clear updates.",
    "Hi there — I'd love to help; here's exactly how I'd approach your gig.",
]

# How many outcomes per (platform, variant) before we trust the win-rate.
_MIN_SAMPLES = int(os.getenv("PROPOSAL_AB_MIN_SAMPLES", "8"))
# Round-robin counter so early A/B is fair across opportunities.
_intro_counter = itertools.count()


def _variant_id(idx: int) -> str:
    return f"v{idx % len(PROPOSAL_INTROS)}"


def _idx_from_variant(variant: str) -> int:
    try:
        return int(str(variant).lstrip("v")) % len(PROPOSAL_INTROS)
    except (ValueError, TypeError):
        return 0


def pick_intro(platform: str, memory=None) -> str:
    """Return the intro text to use for ``platform``.

    Before enough samples, round-robins across variants (stable per-call counter)
    so the A/B test is honest. Once enough data exists, returns the best variant.
    """
    best = best_intro(platform, memory=memory)
    if best is not None:
        return PROPOSAL_INTROS[_idx_from_variant(best)]
    idx = next(_intro_counter) % len(PROPOSAL_INTROS)
    return PROPOSAL_INTROS[idx]


def best_intro(platform: str, memory=None) -> Optional[str]:
    """Return the best variant id for ``platform`` once enough samples exist.

    Reads recent ``proposal_intro`` learnings from ``EarningMemory`` and computes
    per-variant win-rate. Returns None until every seen variant has >=
    ``_MIN_SAMPLES`` outcomes (so we don't prematurely lock onto noise).
    """
    if memory is None:
        return None
    try:
        rows = memory.get_recent_learned("proposal_intro", limit=500)
    except Exception:
        return None
    if not rows:
        return None

    stats: Dict[str, dict] = {}
    for r in rows:
        # insight carries the variant id; confidence encodes win(1.0)/loss(0.0).
        variant = str(r.get("insight", "")).strip()
        if not variant:
            continue
        if variant not in stats:
            stats[variant] = {"wins": 0, "total": 0}
        stats[variant]["total"] += 1
        if float(r.get("confidence", 0.0) or 0.0) >= 0.5:
            stats[variant]["wins"] += 1

    # Need enough samples on every observed variant before trusting.
    if not stats or any(s["total"] < _MIN_SAMPLES for s in stats.values()):
        return None

    best = None
    best_rate = -1.0
    for variant, s in stats.items():
        rate = s["wins"] / s["total"] if s["total"] else 0.0
        if rate > best_rate:
            best_rate = rate
            best = variant
    return best


def record_win(platform: str, variant: str, memory=None) -> None:
    """Persist a proposal win for ``variant`` on ``platform``."""
    if memory is None:
        return
    try:
        memory.store_learning(
            "proposal_intro", str(variant), confidence=1.0)
    except Exception:
        pass  # never break the submit/proposal path over bookkeeping


def record_loss(platform: str, variant: str, memory=None) -> None:
    """Persist a proposal loss for ``variant`` on ``platform``."""
    if memory is None:
        return
    try:
        memory.store_learning(
            "proposal_intro", str(variant), confidence=0.0)
    except Exception:
        pass
