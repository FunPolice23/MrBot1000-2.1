"""Agent → Web Browser tab navigation bus (ARCH-ENG-105).

The agents browse the web through ``agents/integrations/web_eyes.py`` (text
extraction for their data). This bus lets that activity surface in the Web
Browser tab as REAL page loading (a ``QWebEngineView``), so the operator can
watch what the agents fetch — not just read ``[TOOL]`` lines in Dialogue.

Threading contract: the agent tools run on a worker/QThread and must NEVER touch
a Qt widget directly. The bus is a ``QObject`` whose signals the tab connects to
with a **queued** connection, so an ``emit`` from the worker thread is
automatically marshalled onto the GUI thread by Qt — the tab's slots (which own
the QWebEngineView) run there. Fail-open: if Qt/webengine is unavailable or no
tab is connected, the announce is a harmless no-op and the agent's text path is
unaffected.
"""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import QObject, Signal

# Recent agent navigations kept so a lazily-built Web Browser tab (built on
# first show) can replay what the agents browsed before it existed. Small ring
# buffer; drained by the tab on connect.
_RECENT_MAX = 50
_recent: deque = deque(maxlen=_RECENT_MAX)


class _WebNavBus(QObject):
    """Process-local singleton carrying agent web-navigation events.

    The tab connects to these with ``Qt.QueuedConnection`` so an emit from a
    worker thread is delivered on the GUI thread automatically.
    """

    # url, context_label (e.g. "agent web_read" / "agent web_search")
    navigate = Signal(str, str)
    # structured activity record for the tab's log panel
    activity = Signal(dict)

    def __init__(self) -> None:
        super().__init__()


_bus: _WebNavBus | None = None


def web_nav_bus() -> _WebNavBus:
    """Return the singleton nav bus (created lazily on first use)."""
    global _bus
    if _bus is None:
        _bus = _WebNavBus()
    return _bus


def announce_web_navigation(url: str, context: str = "agent") -> None:
    """Announce that an agent is navigating to *url*.

    Safe to call from any thread. The connected tab slot is queued onto the GUI
    thread by Qt, so the QWebEngineView (GUI-thread-only) loads the page without
    a cross-thread widget access. Also recorded in a small ring buffer so a
    lazily-built tab can replay recent activity. Never raises.
    """
    if not url:
        return
    url = str(url)
    if not (url.startswith("http://") or url.startswith("https://")):
        return
    try:
        _recent.append(("nav", url, str(context)))
        web_nav_bus().navigate.emit(url, context)
    except Exception:
        pass


def announce_web_activity(record: dict) -> None:
    """Announce a structured web-activity record (query/url/status/preview)."""
    if not isinstance(record, dict):
        return
    try:
        _recent.append(("activity", dict(record)))
        web_nav_bus().activity.emit(dict(record))
    except Exception:
        pass


def recent_navigations() -> list:
    """Return a snapshot of recent (kind, ...) entries for a late-built tab."""
    try:
        return list(_recent)
    except Exception:
        return []


__all__ = ["web_nav_bus", "announce_web_navigation", "announce_web_activity",
           "recent_navigations"]
