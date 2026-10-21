"""Shared GUI error collector.

ARCH-ENG-305 (R-02): settings persistence used to swallow ten failures with
``pass``/``continue``. An operator could save, see "Settings saved", and never
learn that a control was not read or an environment update did not apply.

This collector keeps the GUI usable (one bad control must not abort the rest of
the save) while making the failing section visible in the log and queryable by
tests/diagnostics.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger("mrbot.gui.errors")

_FAILURES: Counter[str] = Counter()
_LAST: dict[str, str] = {}


def record_gui_error(section: str, exc: BaseException | Any) -> None:
    """Record a non-fatal GUI failure against a stable section name."""
    name = (section or "unknown").strip() or "unknown"
    message = f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else str(exc)
    _FAILURES[name] += 1
    _LAST[name] = message
    logger.warning("GUI section %s failed: %s", name, message)


def gui_error_snapshot() -> dict[str, dict[str, Any]]:
    """Return counts and the last message for every failing section."""
    return {
        name: {"count": count, "last": _LAST.get(name, "")}
        for name, count in sorted(_FAILURES.items())
    }


def reset_gui_errors() -> None:
    """Clear the collector (tests/diagnostics only)."""
    _FAILURES.clear()
    _LAST.clear()
