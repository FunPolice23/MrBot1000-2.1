"""ARCH-ENG-225 - a 2-second polling thread that was started and never stopped.

## What was wrong

`ProviderHotReload.start_monitoring()` is called once, at `main.py:543`. It
starts a daemon thread that polls `.env` every 2 seconds.

`stop_monitoring()` had **zero callers in the entire codebase** -- not in
`MainWindow.shutdown`, not in `closeEvent`, not in any test. So the thread ran
for the life of the process and was only ever ended by the interpreter killing
a daemon thread during finalisation: a thread executing Python while the
interpreter tears itself down.

That is not theoretical. A full-suite run on this machine terminated with:

    Windows fatal exception: access violation
    Thread 0x00006b28 (most recent call first):
      File "agents/providers/provider_hot_reload.py", line 69 in _monitor_loop

`MainWindow.shutdown` already documents this exact hazard for the tab-owned
threads it stops -- "Leaving them running leaks threads and crashes PySide6 at
process exit" -- and this thread was simply missing from that list.

Two further problems, both fixed here:

- The loop used `time.sleep(interval)`, so a stop could not interrupt it; it had
  to wait out the full interval. It now waits on an Event.
- The registered callbacks are bound methods of the main window. Leaving them
  registered keeps the entire window alive for as long as this process-wide
  singleton exists, which is why `stop_monitoring` takes `unregister_all`.

## What these tests pin

1. `stop_monitoring` actually stops the thread, promptly -- and is idempotent.
2. Restarting after a stop works, so this is not a one-way door.
3. `MainWindow.shutdown` calls it. A helper nobody calls is the bug; if the
   wiring regresses, these tests fail.
"""

import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from agents.providers.provider_hot_reload import ProviderHotReload  # noqa: E402


class TestStopMonitoringActuallyStops(unittest.TestCase):
    def setUp(self):
        # A fresh instance, NOT the singleton: the singleton is process-wide and
        # other tests may legitimately have it running.
        self.hr = ProviderHotReload()
        self.hr._env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
        self.hr.register_callback(lambda changes: None)

    def tearDown(self):
        self.hr.stop_monitoring(unregister_all=True)

    def _named_threads(self):
        return {t.name for t in threading.enumerate()}

    def test_the_loop_thread_actually_exists(self):
        """Precondition -- so 'the thread is gone' means something."""
        self.hr.start_monitoring(interval=2.0)
        time.sleep(0.2)
        self.assertIn("provider-hot-reload", self._named_threads(),
                      "no monitor thread was started; the rest of this file "
                      "would pass vacuously")

    def test_stop_ends_the_thread(self):
        self.hr.start_monitoring(interval=2.0)
        time.sleep(0.2)
        self.hr.stop_monitoring()
        self.assertNotIn("provider-hot-reload", self._named_threads(),
                         "stop_monitoring() returned but the thread is alive")

    def test_stop_does_not_wait_out_the_poll_interval(self):
        """The Event change. A `time.sleep` loop cannot beat this.

        With `interval=2.0` and a sleep-based loop, the earliest the thread can
        observe `_running = False` is up to 2 s away, so `join(timeout=5)`
        blocks for ~2 s. The Event makes it immediate.
        """
        self.hr.start_monitoring(interval=2.0)
        time.sleep(0.2)
        t0 = time.perf_counter()
        self.hr.stop_monitoring()
        dt = time.perf_counter() - t0
        self.assertLess(dt, 1.0,
                        f"stop took {dt:.2f}s with a 2 s poll interval -- the "
                        f"loop is still sleeping instead of waiting on an Event")

    def test_stop_is_idempotent(self):
        """`shutdown()` is documented as safe to call more than once."""
        self.hr.start_monitoring(interval=0.1)
        self.hr.stop_monitoring()
        self.hr.stop_monitoring()
        self.hr.stop_monitoring()
        self.assertFalse(self.hr.is_running)

    def test_stop_without_ever_starting_is_safe(self):
        hr = ProviderHotReload()
        hr.stop_monitoring()
        self.assertFalse(hr.is_running)

    def test_stop_can_restart(self):
        """Not a one-way door -- a regression here would silently disable
        hot-reload for the rest of the session."""
        self.hr.start_monitoring(interval=0.1)
        time.sleep(0.15)
        self.hr.stop_monitoring()
        self.hr.start_monitoring(interval=0.1)
        time.sleep(0.15)
        self.assertTrue(self.hr.is_running, "monitoring did not restart")
        self.assertIn("provider-hot-reload", self._named_threads())
        self.hr.stop_monitoring()

    def test_unregister_all_drops_the_window_callbacks(self):
        """Callbacks are bound methods of the main window.

        Leaving them in a process-wide singleton keeps the whole window alive.
        """
        marker = []
        self.hr.register_callback(lambda c: marker.append(c))
        self.assertEqual(len(self.hr._callbacks), 2)
        self.hr.stop_monitoring(unregister_all=True)
        self.assertEqual(self.hr._callbacks, [],
                         "callbacks survived shutdown; the singleton still "
                         "holds a reference to the main window")

    def test_unregister_all_is_opt_in(self):
        """So a caller that wants to keep them is not broken."""
        self.hr.start_monitoring(interval=0.1)
        self.hr.stop_monitoring()
        self.assertEqual(len(self.hr._callbacks), 1,
                         "stop_monitoring() dropped callbacks by default; "
                         "that was not requested")


class TestShutdownIsWired(unittest.TestCase):
    """The bug was a helper with no callers. This pins the caller."""

    def test_calling_mainwindow_shutdown_really_stops_the_thread(self):
        """Behavioural, not a source-text check.

        `MainWindow.shutdown` reads everything through `getattr(..., default)`,
        so it can be driven with a stub rather than a real window. An earlier
        draft of this test asserted that the literal string "stop_monitoring"
        appeared in tests/gui/test_section_e.py -- which is true only by
        accident: that file calls `mw.shutdown()`, and shutdown is where the
        stop lives. String-matching the test file proves nothing about the
        thread; this does.
        """
        import main
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])

        hr = ProviderHotReload()
        hr._env_path = "does-not-exist"
        hr.register_callback(lambda c: None)
        hr.start_monitoring(interval=30.0)     # long enough to prove it stops
        self.assertTrue(hr.is_running)

        class Stub:
            _shutting_down = False
            provider_hot_reload = hr

            def _stop_tab_background_threads(self):
                pass

            def _shutdown_ollama(self):
                pass

            db = None

        try:
            main.MainWindow.shutdown(Stub())
        finally:
            hr.stop_monitoring(unregister_all=True)

        self.assertFalse(hr.is_running,
                         "MainWindow.shutdown() returned without stopping the "
                         "provider hot-reload thread")
        self.assertNotIn("provider-hot-reload",
                         {t.name for t in threading.enumerate()},
                         "the monitor thread is still alive after shutdown; "
                         "this is the access-violation crash")

    def test_start_monitoring_still_has_its_caller(self):
        """Both ends: something starts it, something stops it."""
        import pathlib
        p = pathlib.Path(__file__).resolve().parents[2] / "main.py"
        src = p.read_text(encoding="utf-8")
        self.assertIn("start_monitoring", src, "nothing starts monitoring now")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    def test_the_thread_name_is_what_the_guards_look_for(self):
        hr = ProviderHotReload()
        hr._env_path = "does-not-exist"
        hr.start_monitoring(interval=5.0)
        time.sleep(0.15)
        try:
            names = {t.name for t in threading.enumerate()}
            self.assertIn("provider-hot-reload", names,
                          "the thread is unnamed or differently named, so "
                          "every guard in this file would silently pass")
        finally:
            hr.stop_monitoring()
        self.assertNotIn("provider-hot-reload",
                         {t.name for t in threading.enumerate()},
                         "the thread outlived stop_monitoring")


if __name__ == "__main__":
    unittest.main()