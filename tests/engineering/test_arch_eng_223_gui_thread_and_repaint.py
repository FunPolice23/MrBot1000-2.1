"""ARCH-ENG-223 - GUI-thread blocking and repaint work that never stopped.

Four defects, all the same shape: work scheduled to run on a timer that was
never told to stop, or that was paid whether or not anyone could see it.

## 1. `_schedule_slot_reprobe` probed the llama-server ON THE GUI THREAD

`check_llama_server` defaults to `timeout=10`
(`agents/providers/provider_lifecycle.py:53`). `_schedule_slot_reprobe` called
it directly from a `QTimer.singleShot`, on a 2 s interval with a 90-attempt
budget -- up to 3 minutes of GUI-thread blocking HTTP.

The case the loop exists for is precisely the case that times out: a
just-launched llama-server accepts the socket immediately but cannot answer
`/v1/models` until the model is resident in VRAM. So the slow path is the
NORMAL path, not an edge case.

Fixed by copying `_refresh_provider_status`, which already does this correctly
300 lines below in the same file.

Moving the check onto a worker introduced a second-order bug that this file
also pins: the original RETURNED once the server answered. A naive port that
just re-arms the timer would keep probing for the full 90 attempts after the
server was already up -- a regression traded for a different one.
`test_the_loop_stops_once_the_server_answers` is the guard.

## 2. The safety-layers table was a constant, rebuilt every tick

`SafetyTab._refresh_layers` is six hard-coded rows. It ran `setRowCount(0)`
then 6 x `insertRow` + 24 x `QTableWidgetItem` -- 24 allocations, a relayout
and a repaint -- twice a second while visible and every 15 s while hidden, for
the life of the process.

## 3. The opportunity-scan drain timer ran at 10 Hz forever

`opp_scan_drain_timer` was started at 100 ms in the builder and never stopped,
waking the Qt event loop ten times a second even with an empty queue and a
hidden tab. Now armed with the scan and stopped on the "done" event.

## 4. Every log line resized its row, visible or not

`_append_log_to_table` ran `insertRow` + 6 `setItem` + `resizeRowToContents`
per line, for every bus event and worker log, whether or not the Live Logs tab
was showing. `resizeRowToContents` invalidates the view layout and forces a
size-hint pass -- the canonical Qt table trap.

Measured on this machine, 2000 lines:

    hidden  ->   1.81 ms   (rows untouched)
    visible -> 301.85 ms   (6 items + resizeRowToContents per line)

Deferring is safe because `_log_emit` already appends every entry to
`self._log_buffer`, and both `_replay_log_buffer` and `_do_apply_log_filter`
rebuild the table from it.
"""

import inspect
import os
import queue
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import Mock  # noqa: E402


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestSlotReprobeDoesNotBlockTheGuiThread(unittest.TestCase):
    """Finding 1."""

    def setUp(self):
        _qapp()
        from gui.workers import provider_lifecycle_backend as plb
        self.mod = plb

    def _owner(self):
        for obj in vars(self.mod).values():
            if inspect.isclass(obj) and "_schedule_slot_reprobe" in vars(obj):
                return obj
        self.fail("no class defines _schedule_slot_reprobe")

    def _harness(self, ready, probe_seconds=0.08):
        from types import SimpleNamespace
        owner = self._owner()

        class Checker:
            def __init__(self):
                self.calls = 0

            def check_llama_server(self, port, **kw):
                self.calls += 1
                time.sleep(probe_seconds)
                return ready, []

        class H:
            _closing = False

            def __init__(self):
                self.provider_checker = Checker()
                self.refreshes = 0

            def _slot_config(self, slot):
                return SimpleNamespace(port=1234)

            def _refresh_provider_status(self, *a):
                self.refreshes += 1

            _schedule_slot_reprobe = owner._schedule_slot_reprobe

        return H()

    def test_the_call_returns_before_the_probe_finishes(self):
        h = self._harness(ready=False, probe_seconds=0.25)
        t0 = time.perf_counter()
        h._schedule_slot_reprobe(2)
        dt = time.perf_counter() - t0
        self.assertLess(dt, 0.10,
                        f"the GUI thread was blocked {dt*1000:.0f} ms by a probe "
                        f"that sleeps 250 ms; it is still on this thread")

    def test_the_probe_still_actually_happens(self):
        """Moving it off-thread must not lose the probe."""
        h = self._harness(ready=False, probe_seconds=0.02)
        h._schedule_slot_reprobe(2)
        time.sleep(0.25)
        self.assertGreaterEqual(h.provider_checker.calls, 1,
                                "no probe ran at all; the work was dropped, "
                                "not moved")

    def test_the_loop_stops_once_the_server_answers(self):
        """The regression a naive port introduces.

        The original returned from its own frame when `running` was true. With
        the check on a worker, the flag has to be read on the next tick -- or
        the loop keeps probing for the full 90 attempts after success.
        """
        h = self._harness(ready=True, probe_seconds=0.03)
        h._schedule_slot_reprobe(2)
        time.sleep(0.2)
        self.assertTrue(getattr(h, "_slot_2_reprobe_done", False),
                        "a successful probe did not record that it succeeded")
        calls_after_success = h.provider_checker.calls
        for _ in range(8):
            h._schedule_slot_reprobe(2)
        time.sleep(0.2)
        self.assertEqual(h.provider_checker.calls, calls_after_success,
                         "the loop kept probing after the server answered")

    def test_a_server_that_never_answers_keeps_being_probed(self):
        """The stop condition must not also stop the loop's actual job."""
        h = self._harness(ready=False, probe_seconds=0.01)
        for _ in range(6):
            h._schedule_slot_reprobe(2)
            time.sleep(0.05)
        self.assertGreaterEqual(h.provider_checker.calls, 3,
                                "the loop gave up on a server that is still "
                                "loading; the row would never flip to Running")

    def test_probes_do_not_stack(self):
        """A hung socket must not spawn a new thread every tick."""
        h = self._harness(ready=False, probe_seconds=0.15)
        for _ in range(10):
            h._schedule_slot_reprobe(2)
        self.assertLessEqual(h.provider_checker.calls, 2,
                             f"{h.provider_checker.calls} probes started while "
                             f"one was still blocked on the socket")


class TestSafetyLayersTableIsConstant(unittest.TestCase):
    """Finding 2."""

    def test_the_table_is_not_rebuilt_on_a_second_refresh(self):
        _qapp()
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
        from gui.tabs.safety_tools_tab import SafetyTab

        tab = SafetyTab.__new__(SafetyTab)
        tab.layers_table = QTableWidget(0, 4)
        SafetyTab._refresh_layers(tab)
        rows = tab.layers_table.rowCount()
        self.assertEqual(rows, 6, "the constant layer list did not populate")

        # Mark it; if the second refresh rebuilds, the mark disappears.
        tab.layers_table.setItem(0, 0, QTableWidgetItem("MARKER"))
        SafetyTab._refresh_layers(tab)
        self.assertEqual(tab.layers_table.item(0, 0).text(), "MARKER",
                         "the table was rebuilt; the guard is not effective")

    def test_the_source_really_populates_all_six(self):
        """So the test above cannot pass on an empty table."""
        _qapp()
        from PySide6.QtWidgets import QTableWidget
        from gui.tabs.safety_tools_tab import SafetyTab
        tab = SafetyTab.__new__(SafetyTab)
        tab.layers_table = QTableWidget(0, 4)
        SafetyTab._refresh_layers(tab)
        self.assertEqual(tab.layers_table.rowCount(), 6)
        for r in range(6):
            for c in range(4):
                self.assertIsNotNone(tab.layers_table.item(r, c),
                                     f"cell ({r},{c}) was never populated")


class TestOpportunityDrainTimerIsArmedPerScan(unittest.TestCase):
    """Finding 3."""

    def setUp(self):
        _qapp()
        from gui.builders import tab_feature_builders as tfb
        self.mixin = tfb.FeatureTabBuildersMixin

    def _harness(self):
        from PySide6.QtCore import QTimer
        h = self.mixin()
        h.opp_scan_drain_timer = QTimer()
        h._opp_scan_queue = queue.Queue()
        h._opp_scan_active = False
        h._opp_scan_page = 1
        h._opp_scan_found = 0
        h.opp_status_label = Mock()
        h._refresh_opportunities = Mock()
        return h

    def test_it_is_not_running_before_any_scan(self):
        h = self._harness()
        self.assertFalse(h.opp_scan_drain_timer.isActive(),
                         "the 10 Hz drain timer was running before any scan")

    def test_the_done_event_stops_it(self):
        h = self._harness()
        h.opp_scan_drain_timer.start(100)
        h._opp_scan_queue.put(("done", 3, None))
        self.mixin._drain_opportunity_scan(h)
        self.assertFalse(h.opp_scan_drain_timer.isActive(),
                         "the drain timer stayed armed after the scan finished")

    def test_a_failed_scan_still_stops_it(self):
        h = self._harness()
        h.opp_scan_drain_timer.start(100)
        h._opp_scan_queue.put(("done", 0, "boom"))
        self.mixin._drain_opportunity_scan(h)
        self.assertFalse(h.opp_scan_drain_timer.isActive(),
                         "a failed scan left the 10 Hz timer running")


class TestLogRowsAreNotBuiltWhileHidden(unittest.TestCase):
    """Finding 4."""

    @classmethod
    def setUpClass(cls):
        _qapp()
        import main as M
        for obj in vars(M).values():
            if inspect.isclass(obj) and "_append_log_to_table" in vars(obj):
                cls.owner = obj
                return
        raise AssertionError("no class defines _append_log_to_table")

    def _entry(self):
        return {"ts": "12:00:00", "severity": "INFO", "source": "x",
                "msg": "hello", "tokens_sec": "", "category": "",
                "details": "", "color": "#aaaaaa"}

    def _harness(self):
        from PySide6.QtWidgets import QTableWidget
        h = self.owner.__new__(self.owner)
        h.log_table = QTableWidget(0, 6)
        h.auto_scroll_logs = None
        return h

    def test_a_hidden_tab_is_left_alone(self):
        h = self._harness()
        h.log_table.hide()
        QApplication = _qapp()
        QApplication.processEvents()
        before = h.log_table.rowCount()
        for _ in range(500):
            h._append_log_to_table(self._entry())
        self.assertEqual(h.log_table.rowCount(), before,
                         "rows were built into a hidden table; the log is not "
                         "showing, so nothing is gained")

    def test_a_visible_tab_still_receives_rows(self):
        """The fix must not be 'stop appending'."""
        h = self._harness()
        h.log_table.show()
        app = _qapp()
        app.processEvents()
        before = h.log_table.rowCount()
        for _ in range(100):
            h._append_log_to_table(self._entry())
        self.assertEqual(h.log_table.rowCount(), before + 100,
                         "a VISIBLE log tab stopped receiving rows; entries "
                         "would be missing until some other rebuild ran")

    def test_hidden_work_is_much_cheaper(self):
        """The actual point of the change."""
        hidden = self._harness()
        hidden.log_table.hide()
        _qapp().processEvents()
        t0 = time.perf_counter()
        for _ in range(1000):
            hidden._append_log_to_table(self._entry())
        hidden_dt = time.perf_counter() - t0

        visible = self._harness()
        visible.log_table.show()
        _qapp().processEvents()
        t0 = time.perf_counter()
        for _ in range(1000):
            visible._append_log_to_table(self._entry())
        visible_dt = time.perf_counter() - t0

        self.assertLess(hidden_dt, visible_dt / 5,
                        f"hidden {hidden_dt*1000:.1f} ms vs visible "
                        f"{visible_dt*1000:.1f} ms -- the deferred path is not "
                        f"actually cheaper, so the change is not worth its risk")


if __name__ == "__main__":
    unittest.main()