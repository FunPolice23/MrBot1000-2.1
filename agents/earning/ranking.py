"""Graph-based ranking for evaluated earning opportunities."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from agents.earning.got import OpportunityGraphPlanner


def rank_opportunities(
    opportunities: List[Any],
    *,
    evidence_store: Any,
    log_fn: Callable[[str], None],
    strategy_feedback: Any = None,
) -> Tuple[List[Any], Any, list]:
    """Attach graph ranks and return opportunities in ranked order.

    When `strategy_feedback` (a StrategyFeedback) is supplied, its per-platform
    outcome adjustment is applied ON TOP of the GoT rank: historically-paying
    platforms rank a little higher, never-paying ones a little lower. This is
    advisory only (it reweights order, never approves/submits) and cold-start
    safe (platforms with too few recorded runs get no adjustment). Omitting it
    preserves the original GoT-only ordering.
    """
    evidence_by_id = {}
    for opportunity in opportunities:
        try:
            for evidence in evidence_store.for_subject(
                "opportunity", opportunity.id
            ):
                evidence_by_id[evidence.id] = evidence
        except Exception as exc:
            log_fn(
                f"[GoT] evidence snapshot unavailable for "
                f"{opportunity.id}: {exc}"
            )

    planner = OpportunityGraphPlanner(
        opportunities,
        evidence_by_id=evidence_by_id,
    )
    ranks = planner.rank()
    rank_by_id = {rank.opportunity_id: rank for rank in ranks}
    for opportunity in opportunities:
        rank = rank_by_id.get(opportunity.id)
        opportunity.got_rank = rank.to_dict() if rank else {}

    # ── Strategy feedback (Phase C): adjust by recorded platform outcomes ──
    feedback_stats = None
    if strategy_feedback is not None:
        try:
            feedback_stats = strategy_feedback.platform_stats()
        except Exception as exc:
            log_fn(f"[Feedback] platform stats unavailable: {exc}")
            feedback_stats = None

    base_position = {
        rank.opportunity_id: index for index, rank in enumerate(ranks)
    }

    def _sort_key(opportunity: Any):
        pos = base_position.get(opportunity.id, len(base_position))
        if feedback_stats is None:
            return pos
        platform = getattr(opportunity, "platform", "") or ""
        try:
            adj = strategy_feedback.ranking_adjustment(platform, stats=feedback_stats)
        except Exception:
            adj = 1.0
        # Lower adjusted position = ranked higher. A paying platform (adj>1)
        # moves up; a never-paying one (adj<1) moves down. Clamped inside
        # ranking_adjustment, so this stays a gentle nudge, never a reorder
        # across the whole list.
        return pos / adj if adj else pos

    opportunities.sort(key=_sort_key)
    return opportunities, planner.graph, ranks


__all__ = ["rank_opportunities"]

