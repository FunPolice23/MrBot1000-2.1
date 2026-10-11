"""Bounded queue operations for manager operator/task input."""

from __future__ import annotations

import queue
from typing import Any


def put_drop_oldest(target: queue.Queue, value: Any) -> None:
    """Put a value, dropping the oldest queued value when capacity is reached."""
    try:
        target.put_nowait(value)
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        target.put_nowait(value)


__all__ = ["put_drop_oldest"]
