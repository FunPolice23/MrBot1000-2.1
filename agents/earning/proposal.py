"""Safety-gated proposal submission orchestration."""

from __future__ import annotations

from typing import Any, Callable, Optional


def submit_gig_proposal(
    opportunity: Any,
    draft: str,
    *,
    result_type: type,
    reviewer: Any = None,
    confirm_cb: Optional[Callable[[str], bool]] = None,
    client: Any = None,
    default_client: Any = None,
    memory: Any = None,
    trust_boundary: Any = None,
    track_fn: Callable[..., Any],
    record_submission_fn: Callable[[Any], None],
    lifecycle: Any = None,
) -> Any:
    """Submit a proposal through review, human/ramp, and evidence gates."""
    try:
        from agents.knowledge.proposal_templates import pick_intro

        if not getattr(opportunity, "proposal_variant", None):
            opportunity.proposal_variant = pick_intro(
                getattr(opportunity, "platform", "unknown"),
                memory=memory,
            )
    except Exception:
        pass

    if reviewer is not None:
        try:
            review = reviewer.review(
                opportunity.description or "",
                draft,
                job_title=opportunity.title or "",
            )
        except Exception as exc:
            return result_type(
                success=False,
                opportunity=opportunity,
                action_taken="review_error",
                message=f"Review gate error: {exc}",
            )
        if not review.can_submit:
            track_fn(
                opportunity,
                "failed",
                note=f"review blocked: {review.summary}",
            )
            return result_type(
                success=False,
                opportunity=opportunity,
                action_taken="review_blocked",
                message=f"Blocked by review gate: {review.summary}",
            )

    summary = (
        f"Job: {opportunity.title}\n"
        f"Budget: ${opportunity.payment_amount or opportunity.estimated_usd_value:.0f}\n"
        f"Platform: {opportunity.platform}\n\n"
        f"Cover preview:\n{draft[:600]}"
    )
    if callable(confirm_cb):
        confirmed = bool(confirm_cb(summary))
    else:
        from agents.earning.submission_ramp import get_ramp

        ramp = get_ramp(memory)
        ai_policy = getattr(trust_boundary, "ai_policy", "ai_allowed")
        if ramp.requires_human(
            opportunity.platform,
            ai_policy=ai_policy,
        ):
            track_fn(
                opportunity,
                "failed",
                note="ramp requires human confirmation",
            )
            return result_type(
                success=False,
                opportunity=opportunity,
                action_taken="ramp_human_required",
                message=(
                    "Human confirmation required by submission ramp "
                    "(cold-start or insufficient win-rate)"
                ),
            )
        confirmed = True

    if not confirmed:
        track_fn(
            opportunity,
            "failed",
            note="human declined / no confirmation",
        )
        return result_type(
            success=False,
            opportunity=opportunity,
            action_taken="human_declined",
            message="Human confirmation required and not granted",
        )

    submit_client = client or default_client
    if submit_client is None or not getattr(
        submit_client, "can_submit", lambda: False
    )():
        return result_type(
            success=False,
            opportunity=opportunity,
            action_taken="no_client",
            message="No submit-capable Upwork client available",
        )

    track_fn(opportunity, "applied", note="submission in flight")
    try:
        from agents.earning.platform_throttle import get_throttle

        get_throttle().acquire(opportunity.platform)
        result = submit_client.submit_proposal(
            job_id=opportunity.id,
            cover=draft,
            budget=float(opportunity.payment_amount or 0.0),
        )
    except Exception as exc:
        record_submission_fn(opportunity)
        track_fn(opportunity, "failed", note=f"submit error: {exc}")
        return result_type(
            success=False,
            opportunity=opportunity,
            action_taken="submit_error",
            message=f"Submit error: {exc}",
        )

    if not result:
        record_submission_fn(opportunity)
        track_fn(opportunity, "failed", note="empty submit response")
        return result_type(
            success=False,
            opportunity=opportunity,
            action_taken="submit_failed",
            message="Upwork returned no proposal",
        )

    proposal_id = result.get("proposal_id", "")
    evidence = None
    try:
        from agents.evidence.evidence_factory import from_upwork_submission

        evidence = from_upwork_submission(
            proposal_id=proposal_id,
            profile_id=result.get("submitted_by", ""),
            job_id=opportunity.id,
            subject_id=opportunity.id,
            errored=bool(result.get("error")),
            error_text=result.get("error", ""),
        )
    except Exception:
        evidence = None

    record_submission_fn(opportunity)
    track_fn(opportunity, "submitted", note=f"proposal_id={proposal_id}")
    if evidence is not None and lifecycle is not None:
        lifecycle.mark_submitted(
            opportunity.id,
            note=f"proposal_id={proposal_id}",
            evidence=evidence,
        )
    return result_type(
        success=True,
        opportunity=opportunity,
        action_taken="submitted",
        message=f"Submitted proposal {proposal_id} for {opportunity.title}",
    )


__all__ = ["submit_gig_proposal"]
