"""Graph-based ranking for evaluated earning opportunities."""

from __future__ import annotations

from typing import Any, Callable, List, Tuple

from agents.earning.got import OpportunityGraphPlanner


def rank_opportunities(
    opportunities: List[Any],
    *,
    evidence_store: Any,
    log_fn: Callable[[str], None],
) -> Tuple[List[Any], Any, list]:
    """Attach graph ranks and return opportunities in ranked order."""
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

    rank_position = {
        rank.opportunity_id: index for index, rank in enumerate(ranks)
    }
    opportunities.sort(
        key=lambda opportunity: rank_position.get(
            opportunity.id, len(rank_position)
        )
    )
    return opportunities, planner.graph, ranks


__all__ = ["rank_opportunities"]
