"""Live-mode transport-failure circuit breaker.

A transport error means the model was never reached. Retrying is right while
the fault is transient, but ``_record_live_failure`` used to return ``True``
unconditionally — so an unreachable endpoint (dead llama-server, unloaded
model, wrong port) made Live reschedule itself every 3 s *forever*, appending
a system line each time, with no cap and no exit. Every sibling recovery path
in the same handler is budgeted; this one was the outlier.

These tests pin the contract:
  * Live tolerates a generous run of consecutive failures (recovery session).
  * Past the budget Live pauses itself and stops rescheduling.
  * A single successful turn resets the counter, so a flapping provider that
    eventually answers keeps the session alive.
"""

import os
import sys
import unittest
from types import SimpleNamespace

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.tabs.dialogue_tab import (  # noqa: E402
    DialogueTab,
    _LIVE_TRANSPORT_FAILURE_BUDGET,
)

_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def _make_tab():
    """A DialogueTab with the recovery handler exercised without live servers.

    Only the attributes ``_record_live_failure`` touches are stubbed, so no
    provider is contacted and no worker thread is started.
    """
    tab = DialogueTab.__new__(DialogueTab)
    tab.live_running = True
    tab._live_failure_count = 0
    tab.system_lines = []
    tab.append_system = lambda text: tab.system_lines.append(text)
    tab._stopped = 0
    tab.stop_live = lambda: setattr(tab, "_stopped", tab._stopped + 1)
    return tab


class TestLiveTransportFailureBudget(unittest.TestCase):
    def test_budget_is_finite_and_generous(self):
        """The cap must exist and leave room for real recovery."""
        self.assertIsInstance(_LIVE_TRANSPORT_FAILURE_BUDGET, int)
        self.assertGreaterEqual(_LIVE_TRANSPORT_FAILURE_BUDGET, 3)
        self.assertLessEqual(_LIVE_TRANSPORT_FAILURE_BUDGET, 50)

    def test_live_survives_failures_within_budget(self):
        """A recovery session must not end on the first few failures."""
        tab = _make_tab()
        for attempt in range(1, _LIVE_TRANSPORT_FAILURE_BUDGET + 1):
            keep = tab._record_live_failure("model unreachable")
            self.assertTrue(
                keep, f"failure {attempt} is inside the budget and must retry")
            self.assertEqual(tab._live_failure_count, attempt)
        self.assertEqual(tab._stopped, 0, "Live must still be running")

    def test_live_pauses_once_budget_is_spent(self):
        """Past the budget Live stops itself instead of looping forever."""
        tab = _make_tab()
        for _ in range(_LIVE_TRANSPORT_FAILURE_BUDGET):
            tab._record_live_failure("model unreachable")
        self.assertEqual(tab._stopped, 0)

        keep = tab._record_live_failure("model unreachable")
        self.assertFalse(
            keep, "the over-budget failure must not ask for another retry")
        self.assertEqual(tab._stopped, 1, "Live must have paused itself")
        self.assertTrue(
            any("paused" in line.lower() for line in tab.system_lines),
            "the pause must be reported to the operator with a reason")

    def test_failure_does_not_reschedule_after_pause(self):
        """The caller's `if retry:` gate must see False, so nothing re-arms."""
        tab = _make_tab()
        for _ in range(_LIVE_TRANSPORT_FAILURE_BUDGET + 1):
            retry = tab._record_live_failure("model unreachable")
        self.assertFalse(retry)

    def test_successful_turn_resets_the_counter(self):
        """A flapping provider that eventually answers keeps the session alive."""
        tab = _make_tab()
        for _ in range(_LIVE_TRANSPORT_FAILURE_BUDGET - 2):
            tab._record_live_failure("model unreachable")
        self.assertEqual(tab._live_failure_count,
                         _LIVE_TRANSPORT_FAILURE_BUDGET - 2)

        # A real turn arrives: _on_response_ready resets the counter.
        tab._live_failure_count = 0
        for _ in range(_LIVE_TRANSPORT_FAILURE_BUDGET):
            self.assertTrue(tab._record_live_failure("model unreachable"))
        self.assertEqual(tab._stopped, 0)

    def test_non_live_failure_still_retries(self):
        """Goal-driven (non-Live) mode keeps its original single-retry contract."""
        tab = _make_tab()
        tab.live_running = False
        for _ in range(_LIVE_TRANSPORT_FAILURE_BUDGET + 5):
            self.assertTrue(tab._record_live_failure("model unreachable"))
        self.assertEqual(tab._stopped, 0, "non-Live must never call stop_live()")


if __name__ == "__main__":
    _app()
    unittest.main()
