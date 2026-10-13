"""Teardown signal-disconnect safety (v2.1.61, ARCH-ENG-074).

Symptom: MrBot1000 (python.exe) aborted with an access violation inside
Qt6Core.dll (0xc0000409, constant fault offset) on essentially every session,
correlating with using the Chat / Dialogue tabs and then closing the window
mid-generation. Windows recorded it as a BEX64 / Application Error with no
Python traceback — a C++ fault, not a Python exception.

Root cause: the Chat and Dialogue tabs run QThread workers (InferenceWorker,
EscalationWorker, DialogueWorker) that make long provider HTTP calls. On window
close while a worker is mid-generation, `_stop_orphan_tab_threads` found the
running thread and called `wait(5000)` — but WITHOUT disconnecting the worker's
signals first. A worker blocked in a long read cannot finish inside the grace
period, so it survives teardown; its queued cross-thread emissions
(`finished`/`progress`/`big_done`/`small_summary`/`exchange_complete`) then land
on widgets being destroyed, dereferencing dead C++ objects and aborting the
interpreter. The manager/summarizer threads already got the fix
(`_disconnect_worker_signals` before wait); the orphaned tab workers did not.

Fix (v2.1.61):
- `main.py:_stop_orphan_tab_threads` now calls `_disconnect_worker_signals`
  BEFORE the graceful wait, for every running tab worker.
- `ChatTab.cleanup()` and `DialogueTab.cleanup()` disconnect their workers'
  signals / stop their self-rearming live loop, so `_stop_tab_background_threads`
  (which calls cleanup() on tabs that expose it) reaches them too. Neither tab
  had a cleanup() before, so they were skipped.

These tests exercise the mechanism without booting the full MainWindow (which
needs a DB + full app): a synthetic QThread worker, the same
`_disconnect_worker_signals` logic, and the assertion that once disconnected a
late emission cannot reach a receiver. They also assert the tabs now expose a
callable cleanup().
"""
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread, Signal

_app = QApplication.instance() or QApplication([])


class _FakeWorker(QThread):
    """A worker with cross-thread signals, like the real chat/dialogue workers."""
    finished = Signal(str)
    big_done = Signal(str)
    small_summary = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.received = []

    def run(self):
        # Stay alive briefly so the test can disconnect mid-run, then emit.
        time.sleep(0.3)
        self.finished.emit("late")


def _disconnect_worker_signals(worker):
    """Delegate to the REAL MainWindow._disconnect_worker_signals.

    Previously this was a COPY of the logic that had to be kept in sync by hand
    — and it drifted (it lacked the shiboken6.isValid guard + warning
    suppression added in v2.1.77), so it re-emitted the exit RuntimeWarnings.
    Call the real method so the test can never drift from the implementation.
    """
    from main import MainWindow
    mw = MainWindow.__new__(MainWindow)
    mw._disconnect_worker_signals(worker)


class TestTeardownSignalDisconnect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def test_disconnect_worker_signals_detaches_receiver(self):
        """After disconnecting, a late emission cannot reach the receiver."""
        worker = _FakeWorker()
        got = []
        worker.finished.connect(lambda s: got.append(s))
        worker.start()
        # Disconnect while the worker is still running (mid-generation).
        time.sleep(0.05)
        self.assertTrue(worker.isRunning(), "worker should still be running")
        _disconnect_worker_signals(worker)
        # Let the worker finish and emit its queued `finished`.
        worker.wait(3000)
        self.app.processEvents()
        self.assertEqual(got, [], "a disconnected worker must not deliver signals")

    def test_connected_worker_would_deliver(self):
        """Control: without disconnecting, the emission IS delivered — proving
        the disconnect is what prevents the crash (not a broken test)."""
        worker = _FakeWorker()
        got = []
        worker.finished.connect(lambda s: got.append(s))
        worker.start()
        worker.wait(3000)
        self.app.processEvents()
        self.assertEqual(got, ["late"], "control: connected worker delivers")

    def test_disconnect_is_idempotent(self):
        """Disconnecting an already-disconnected (or unconnected) worker never
        raises — teardown calls it once but must be safe regardless."""
        worker = _FakeWorker()
        _disconnect_worker_signals(worker)  # nothing connected
        _disconnect_worker_signals(worker)  # idempotent
        self.assertTrue(True)

    def test_isSignal_absent_methodType_is_the_detector(self):
        """Regression guard for ARCH-ENG-074: this PySide6 (6.11) has NO
        QMetaMethod.isSignal(). Code that tests `method.isSignal()` raises
        AttributeError on the first signal; swallowed by an outer try/except it
        silently disconnects nothing — the exact latent bug that made every
        teardown "disconnect before wait" a no-op and left the chronic
        Qt6Core 0xc0000409 crash unfixed. Assert the working detector is
        methodType() == MethodType.Signal, and that isSignal() is genuinely
        absent so a future port can't quietly regress to it."""
        from PySide6.QtCore import QMetaMethod
        worker = _FakeWorker()
        meta = worker.metaObject()
        signal_type = QMetaMethod.MethodType.Signal
        saw_signal = False
        for i in range(meta.methodCount()):
            m = meta.method(i)
            if not m.isValid():
                continue
            # methodType() must classify the worker's declared signals.
            if m.methodType() == signal_type and bytes(m.name()) in (
                b"finished", b"big_done", b"small_summary", b"failed",
            ):
                saw_signal = True
                # And it must NOT be detectable via a nonexistent isSignal().
                self.assertFalse(
                    hasattr(m, "isSignal"),
                    "QMetaMethod.isSignal() must stay absent here; detect via methodType()",
                )
        self.assertTrue(saw_signal, "methodType() must detect the worker's signals")


class TestTabCleanupExists(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def test_chat_and_dialogue_tabs_expose_cleanup(self):
        """main.py's _stop_tab_background_threads calls cleanup() on tabs that
        expose it; Chat/Dialogue had none, so their workers were never stopped
        by that path. Both must now expose a callable cleanup()."""
        import importlib
        ct = importlib.import_module("gui.tabs.chat_tab")
        dt = importlib.import_module("gui.tabs.dialogue_tab")
        for mod, name in ((ct, "ChatTab"), (dt, "DialogueTab")):
            cls = getattr(mod, name, None)
            self.assertIsNotNone(cls, f"{name} must exist")
            self.assertTrue(
                callable(getattr(cls, "cleanup", None)),
                f"{name} must expose a callable cleanup() so teardown stops its workers",
            )


if __name__ == "__main__":
    raise SystemExit(unittest.main())
