"""Manager-specific heartbeat and queue metrics projections."""

from __future__ import annotations

from typing import Any, Dict, Iterable


def update_lifecycle_metrics(
    metrics: Dict[str, int],
    states: Iterable[Dict[str, Any]],
) -> None:
    """Accumulate lifecycle state counts into manager heartbeat metrics."""
    for state in states:
        stage = state["current_stage"]
        if stage == "queued":
            metrics["total_tasks"] += 1
        elif stage == "applied":
            metrics["opportunities_applied"] += 1
        elif stage == "submitted":
            metrics["opportunities_submitted"] += 1
        elif stage == "paid":
            metrics["opportunities_paid"] += 1
            metrics["successful"] += 1
        elif stage == "failed":
            metrics["errors"] += 1


def heartbeat_summary(heartbeat_count: int, metrics: Dict[str, int]) -> str:
    """Format the stable heartbeat summary message."""
    return (
        f"Heartbeat #{heartbeat_count} summary: "
        f"{metrics['analysis']} analysis, "
        f"{metrics['job_search']} job search, "
        f"{metrics['coder']} coder, "
        f"{metrics['manager']} manager tasks, "
        f"queued={metrics['total_tasks']}, "
        f"successful={metrics['successful']}, "
        f"errors={metrics['errors']}"
    )


def runtime_snapshot(
    *,
    stats: Any,
    task_queue: Any,
    human_queue: Any,
    job_queue: Any,
    paused: bool,
) -> dict:
    """Combine runtime telemetry with manager backlog state."""
    snapshot = stats.snapshot()
    snapshot["pending_tasks"] = (
        task_queue.qsize() if hasattr(task_queue, "qsize") else 0
    )
    snapshot["pending_chat"] = (
        human_queue.qsize() if hasattr(human_queue, "qsize") else 0
    )
    snapshot["pending_jobs"] = len(job_queue) if isinstance(job_queue, list) else 0
    snapshot["paused"] = bool(paused)
    return snapshot


__all__ = [
    "heartbeat_summary",
    "runtime_snapshot",
    "update_lifecycle_metrics",
]
