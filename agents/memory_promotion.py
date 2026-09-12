"""Promotion gate from transient cognition/outcomes into durable memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from agents.cognition import Lesson, Outcome


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    reason: str
    source_outcome_ids: List[str]


class MemoryPromotionPolicy:
    """Allow durable lessons only when their outcome evidence is verified."""

    def evaluate(self, lesson: Lesson, outcomes: Iterable[Outcome]) -> PromotionDecision:
        outcome_list = list(outcomes)
        outcome_ids = set(lesson.source_outcome_ids)
        if not lesson.verified:
            return PromotionDecision(False, "lesson is not explicitly verified", list(outcome_ids))
        if not outcome_ids:
            return PromotionDecision(False, "lesson has no source outcomes", [])
        actual_ids = {outcome.outcome_id for outcome in outcome_list}
        if actual_ids != outcome_ids:
            return PromotionDecision(False, "lesson references unknown outcomes", list(outcome_ids))
        if any(not outcome.can_update_learning() for outcome in outcome_list):
            return PromotionDecision(False, "all source outcomes must be verified with evidence", list(outcome_ids))
        return PromotionDecision(True, "lesson is backed by verified outcomes", list(outcome_ids))

    def promote(self, database, lesson: Lesson, outcomes: Iterable[Outcome], *,
                title: Optional[str] = None, expires_days: Optional[int] = None) -> PromotionDecision:
        """Persist a verified lesson using the existing memory database."""
        outcome_list = list(outcomes)
        decision = self.evaluate(lesson, outcome_list)
        if not decision.allowed:
            return decision
        database.add_memory(
            category="lesson",
            title=title or "Verified outcome lesson",
            content=lesson.summary,
            importance=0.8,
            source="verified_outcome",
            tags="outcome_ids=" + ",".join(sorted(decision.source_outcome_ids)),
            expires_days=expires_days,
        )
        return decision


__all__ = ["MemoryPromotionPolicy", "PromotionDecision"]