"""Qt-independent shutdown policy for the manager loop."""

from __future__ import annotations


def request_shutdown(manager: object) -> None:
    """Request an idempotent stop without owning Qt thread operations."""
    if getattr(manager, "running", False):
        manager.running = False


__all__ = ["request_shutdown"]
