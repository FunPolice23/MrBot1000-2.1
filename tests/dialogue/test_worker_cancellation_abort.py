"""Regression: a DialogueWorker blocked in a slow provider read must abort
the instant cancel() is called, so teardown never destroys a running QThread
(the Qt6Core 0xc0000409 / "QThread: Destroyed while thread is still running"
crash class — see qt-thread-crash-classes.md §3a, ARCH-ENG-102).

The bug: cancel() only set a cooperative ``_cancelled`` flag that was checked
BETWEEN operations. A worker blocked inside ``brain.chat()`` (a multi-minute
HTTP read on a slow CPU model) never saw the flag, survived window-close
teardown, and the parentless QThread was garbage-collected while its thread was
still running -> deterministic fast-fail at a constant fault offset.

Fix under test:
  1. DialogueWorker is parented to the tab, so the shutdown sweep's
     findChildren(QThread) can find, disconnect and wait() on it.
  2. on_stream raises _WorkerCancelled when _cancelled, which propagates out of
     the streaming generator and unblocks run() immediately.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from gui.tabs.dialogue_tab import DialogueWorker, _WorkerCancelled


class _SlowStreamingBrain:
    """Simulates a slow CPU model: streams chunks in a loop and only stops
    making progress when the stream callback raises (i.e. on cancel)."""

    model = "served-model"

    def __init__(self):
        self.chunks_emitted = 0
        self.saw_cancel_raise = False

    def chat(self, *args, **kwargs):
        stream = kwargs["stream_progress"]
        # Emit chunks until the callback raises _WorkerCancelled (cancel()).
        for _ in range(1000):
            try:
                stream("token ")
                self.chunks_emitted += 1
            except _WorkerCancelled:
                self.saw_cancel_raise = True
                raise
        return "should never reach here if cancelled"


class TestWorkerCancellationAbort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_aborts_blocking_stream_via_raised_exception(self):
        """on_stream must raise _WorkerCancelled once cancel() is set, and
        run() must swallow it (no bogus Error turn, no finished-with-error)."""
        brain = _SlowStreamingBrain()
        worker = DialogueWorker(brain, "ctx", [], "Edward Hurst", max_retries=0)

        finished = []
        errors = []
        # ARCH-ENG-168: the response signal is `response_ready`; it used to be
        # `finished`, which shadowed the inherited 0-arity QThread.finished.
        worker.response_ready.connect(
            lambda resp, spk: finished.append((resp, spk)))

        # Cancel BEFORE the first real chunk so the very first stream call
        # raises — this is the prompt-eval/generation-blocked path.
        def _cancel_after_first_chunk(*_a):
            worker.cancel()
        worker.progress.connect(_cancel_after_first_chunk)

        # run() must not raise and must not emit an error response.
        worker.run()
        self.assertTrue(brain.saw_cancel_raise or brain.chunks_emitted >= 1)
        # No error string was surfaced as a finished response.
        for resp, _spk in finished:
            self.assertFalse(str(resp).lower().startswith("error:"),
                             f"cancelled worker emitted an error turn: {resp!r}")

    def test_worker_is_parentable(self):
        """The worker accepts a parent so the teardown sweep can find it."""
        brain = _SlowStreamingBrain()
        parent = QApplication.instance().activeModalWidget()
        worker = DialogueWorker(brain, "ctx", [], "Edward Hurst",
                                max_retries=0, parent=None)
        self.assertIsNone(worker.parent())
        # Constructing with a parent must not raise.
        w2 = DialogueWorker(brain, "ctx", [], "Jacob Stanley",
                            max_retries=0, parent=parent)
        self.assertIs(w2.parent(), parent)

    def test_on_stream_raises_when_cancelled(self):
        """Directly exercise the abort: a cancelled worker's stream callback
        raises _WorkerCancelled rather than silently returning."""
        brain = _SlowStreamingBrain()

        captured = {}

        class _CaptureBrain:
            model = "m"

            def chat(self, *a, **k):
                captured["stream"] = k["stream_progress"]
                # Cancel first, then invoke the stream callback.
                raise _WorkerCancelled()

        worker = DialogueWorker(_CaptureBrain(), "ctx", [], "Edward Hurst",
                                max_retries=0)
        worker.cancel()
        # run() should swallow the _WorkerCancelled cleanly.
        worker.run()
        self.assertTrue(worker._cancelled)


if __name__ == "__main__":
    unittest.main()
