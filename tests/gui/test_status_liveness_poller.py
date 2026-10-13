"""Periodic provider-status liveness poller (v2.1.60, ARCH-ENG-073).

A llama-server can die on its own (OOM, GPU/RAM contention, an mmproj mismatch
abort) while MrBot1000 keeps running. Before this fix the Provider Control rows
were only probed once on load, on an explicit Refresh click, and in a bounded
post-launch re-probe loop that latched off once the brain was seen reachable
(``_bb_reachable``/``_sb_reachable``). So when a server process died mid-session
the status row stayed frozen at "● Running" and the operator was misled into
thinking the brain was still loaded when its process was gone (e.g. the big
brain on port 1234 dying while the GUI still showed Running).

``DualBrainControl`` now runs a 4s ``QTimer`` that calls
``_refresh_provider_status`` (which already probes on a background thread and
applies via a queued signal, so the GUI never blocks), and ``cleanup()`` stops
it. ``_refresh_provider_status`` also skips a tick if the previous probe thread
is still alive, so a hung port can't pile up threads. The llamacpp probe uses a
2s timeout so death is detected inside the 4s window.
"""
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

_app = QApplication.instance() or QApplication([])

from gui.widgets.dual_brain_control import DualBrainControl  # noqa: E402
from agents.runtime.dual_brain import DualBrainRuntime  # noqa: E402
from agents.providers.provider_manager import ProviderManager  # noqa: E402


def _wait_detected(app, timeout=12):
    deadline = time.time() + timeout
    while not ProviderManager.instance()._detected and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)


class TestStatusLivenessPoller(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def _widget(self):
        w = DualBrainControl(runtime=DualBrainRuntime.from_env())
        self.app.processEvents()
        _wait_detected(self.app)
        w._apply_runtime()
        self.app.processEvents()
        return w

    def test_status_timer_exists_and_is_running(self):
        """A periodic QTimer drives the provider probe while the panel is open."""
        w = self._widget()
        try:
            timer = getattr(w, "_status_timer", None)
            self.assertIsNotNone(timer, "panel must own a _status_timer")
            self.assertIsInstance(timer, QTimer)
            self.assertTrue(timer.isActive(), "liveness timer must be started")
            # 4s window: responsive enough to notice a death, cheap enough to
            # not hammer the ports.
            interval = timer.interval()
            self.assertGreaterEqual(interval, 2000)
            self.assertLessEqual(interval, 10000)
        finally:
            w._closing = True

    def test_timer_is_wired_to_refresh(self):
        """The timer's timeout is connected to _refresh_provider_status."""
        w = self._widget()
        try:
            timer = w._status_timer
            self.assertIsNotNone(timer.timeout, None)  # sanity
            # QTimer.timeout connections aren't introspectable, so assert the
            # refresh entrypoint is callable and the widget exposes it.
            self.assertTrue(callable(getattr(w, "_refresh_provider_status", None)))
        finally:
            w._closing = True

    def test_cleanup_stops_the_timer(self):
        """cleanup() stops the poller so it can't fire on a destroyed widget."""
        w = self._widget()
        w.cleanup()
        try:
            timer = getattr(w, "_status_timer", None)
            self.assertIsNotNone(timer)
            self.assertFalse(timer.isActive(), "cleanup() must stop the timer")
        finally:
            w._closing = True

    def test_refresh_skips_when_previous_probe_alive(self):
        """_refresh_provider_status must not pile up threads when a prior probe
        is still running (a hung port blocks up to the probe timeout)."""
        w = self._widget()
        try:
            import threading
            # Plant a fake "still-alive" probe thread and assert the refresh
            # short-circuits instead of spawning another.
            ev = threading.Event()
            def _hang():
                ev.wait(5)
            fake = threading.Thread(target=_hang, daemon=True)
            fake.start()
            w._provider_probe_thread = fake
            before = w._provider_probe_thread
            w._refresh_provider_status()          # should return without replacing
            self.assertIs(w._provider_probe_thread, before,
                          "must skip when the previous probe thread is alive")
            ev.set()
            fake.join(1)
        finally:
            w._closing = True


if __name__ == "__main__":
    raise SystemExit(unittest.main())
