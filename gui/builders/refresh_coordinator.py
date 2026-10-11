"""Shared refresh scheduling for GUI tabs.

Only one Qt timer services registered views. Hidden views are disabled rather
than moved to a slower polling timer, so background tabs perform no refresh
work while they are not visible.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer


@dataclass
class _Entry:
    callback: Callable[[], None]
    interval_ms: int
    visible: bool = False
    last_refresh: float = 0.0


class RefreshCoordinator(QObject):
    """One process-local timer with visibility-aware callback registration."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: dict[str, _Entry] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh_due)

    def register(self, key: str, callback: Callable[[], None], interval_ms: int) -> None:
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        self._entries[key] = _Entry(callback, interval_ms)
        if not self._timer.isActive():
            self._timer.start()

    def unregister(self, key: str) -> None:
        self._entries.pop(key, None)
        if not self._entries:
            self._timer.stop()

    def set_visible(self, key: str, visible: bool) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        entry.visible = visible
        if visible:
            entry.last_refresh = 0.0
            self._refresh_entry(key, entry)

    def _refresh_due(self) -> None:
        now = time.monotonic()
        for key, entry in tuple(self._entries.items()):
            if entry.visible and (now - entry.last_refresh) * 1000 >= entry.interval_ms:
                self._refresh_entry(key, entry)

    def _refresh_entry(self, key: str, entry: _Entry) -> None:
        entry.last_refresh = time.monotonic()
        entry.callback()


_coordinator: RefreshCoordinator | None = None


def refresh_coordinator() -> RefreshCoordinator:
    """Return the GUI-thread coordinator singleton."""
    global _coordinator
    if _coordinator is None:
        _coordinator = RefreshCoordinator()
    return _coordinator


__all__ = ["RefreshCoordinator", "refresh_coordinator"]
