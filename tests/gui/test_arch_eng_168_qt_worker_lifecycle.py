"""ARCH-ENG-168/169/170 — Qt lifecycle defects in the Dialogue tab.

Three defects, all in how a `DialogueWorker` (a `QThread`) relates to Qt.

ARCH-ENG-168 — `DialogueWorker.finished` SHADOWED `QThread.finished`.

    class DialogueWorker(QThread):
        finished = Signal(str, str)      # response, speaker

`QThread` already defines a zero-argument `finished` signal, emitted from C++
when the thread stops. Redefining it with a different arity rebinds that name to
the Python signal, so Qt's own completion emission resolves to a two-argument
slot. The standard ownership idiom `worker.finished.connect(
worker.deleteLater)` breaks on the arity mismatch, and Qt-internal completion
handling can raise inside the C++ event dispatch — the `Qt6Core 0xc0000409`
class this app has fought before. It also carried a response, so it was never
"finished" in the Qt sense; renamed `response_ready`, and the real
`QThread.finished` is now used for what it is for.

ARCH-ENG-169 — `requestInterruption()` WAS A NO-OP, and workers were never freed.

`cancel()` set only the private `_cancelled` flag. `main.py` additionally calls
`QThread.requestInterruption()` on shutdown — but NOTHING in the class ever
polled `isInterruptionRequested()` (zero call sites). So on the shutdown path the
worker had no way to observe either mechanism, and `main.py` discarded the result
of `thread.wait(5000)`, so the QThread could still be running when Qt destroyed
it: "QThread: Destroyed while thread is still running".

Separately: `deleteLater()` appeared NOWHERE in the file, and `_retired_workers`
was appended to on every stop/reset/cleanup and never pruned — so the tab held a
strong reference to every worker it had ever started, for the life of the
session.

Now: `cancel()` raises BOTH mechanisms, `_stop_requested()` reads BOTH, the real
`QThread.finished` drives `deleteLater`, and the retirement list is pruned and
capped.

ARCH-ENG-170 — A WIRED BUTTON CALLED A METHOD THAT DOES NOT EXIST.

    def force_forward(self):        # wired at setup_ui: self.force_btn.clicked
        ...
        self._run_single_turn()     # <- defined nowhere in the repository

The operator clicked "force forward" and got an `AttributeError`. `respond()` is
the per-turn entry point — what every other continuation in the file schedules,
and a no-op when a response is already in flight, so it cannot stack threads.
"""

import ast
import inspect
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]


class TestDialogueWorkerSignalHygiene(unittest.TestCase):
    """ARCH-ENG-168 — never shadow an inherited Qt signal."""

    def _worker_class(self):
        import agents.safety  # noqa: F401  (breaks the import cycle)
        from gui.tabs.dialogue_tab import DialogueWorker
        return DialogueWorker

    def test_the_worker_does_not_shadow_qthread_finished(self):
        from PySide6.QtCore import QThread
        worker = self._worker_class()
        own = worker.__dict__.get("finished")
        inherited = QThread.__dict__.get("finished", None)
        self.assertIsNone(
            own,
            "DialogueWorker defines its own `finished`, shadowing "
            "QThread.finished(). Qt emits the inherited signal from C++ when "
            "the thread stops; rebinding the name to a two-argument Python "
            "signal breaks the standard deleteLater idiom and can raise inside "
            "Qt's event dispatch. Name the response signal for what it means.")

    def test_the_response_signal_exists_and_is_named_for_its_meaning(self):
        worker = self._worker_class()
        self.assertTrue(hasattr(worker, "response_ready"),
                        "expected the renamed response signal")

    def test_the_inherited_finished_signal_is_still_reachable(self):
        from PySide6.QtCore import QThread
        worker = self._worker_class()
        self.assertTrue(hasattr(worker, "finished"),
                        "the inherited QThread.finished must remain reachable")

    def test_every_worker_signal_has_a_distinct_name(self):
        """A shadowing bug is exactly two signals sharing one name."""
        worker = self._worker_class()
        declared = {
            name for name, val in vars(worker).items()
            if type(val).__name__ == "Signal" or hasattr(val, "__class__")
        }
        # The four worker signals plus any inherited should not collide.
        for name in ("response_ready", "progress", "tool_activity",
                     "gpu_progress"):
            self.assertIn(name, declared,
                          f"{name} is no longer a declared signal")

    def test_no_emit_still_uses_the_renamed_signal(self):
        """The rename must be COMPLETE.

        This is not hypothetical: renaming the declaration and the connect site
        while leaving `self.finished.emit(response, speaker)` inside `run()`
        looked fine until a test hit the error branch and raised
        `TypeError: finished() only accepts 0 argument(s), 2 given!` — because
        Qt's inherited signal is genuinely zero-arity. A partial rename is
        therefore not a style issue; it is a runtime crash on the error path.
        """
        src = (REPO / "gui" / "tabs" / "dialogue_tab.py").read_text(
            encoding="utf-8")
        self.assertNotIn(
            "self.finished.emit(",
            src,
            "a worker signal is still emitted through the name that now "
            "resolves to QThread.finished (0-arity) — this raises TypeError "
            "whenever it is reached")
        self.assertGreaterEqual(
            src.count("self.response_ready.emit("), 2,
            "the response signal is emitted on both the success and the error "
            "path; one is missing")

    def test_the_connect_site_uses_the_renamed_signal(self):
        src = (REPO / "gui" / "tabs" / "dialogue_tab.py").read_text(
            encoding="utf-8")
        self.assertIn("worker.response_ready.connect(", src,
                      "the tab must subscribe to the renamed response signal")


class TestInterruptionHasTeeth(unittest.TestCase):
    """ARCH-ENG-169 — both cancellation mechanisms must be raised and read."""

    def _worker_class(self):
        import agents.safety  # noqa: F401
        from gui.tabs.dialogue_tab import DialogueWorker
        return DialogueWorker

    def test_the_run_loop_polls_interruption(self):
        worker = self._worker_class()
        src = inspect.getsource(worker)
        self.assertIn("_stop_requested", src,
                      "run() must poll for a stop request")
        self.assertGreaterEqual(
            src.count("if self._stop_requested()"), 3,
            "a stop request is only observed between operations; poll it at "
            "several points so a worker blocked on a provider call can exit")

    def test_stop_requested_reads_both_mechanisms(self):
        worker = self._worker_class()
        src = inspect.getsource(worker._stop_requested)
        self.assertIn("_cancelled", src,
                      "the internal flag must still be honoured")
        self.assertIn("isInterruptionRequested", src,
                      "Qt's interruption flag must be honoured too — this is "
                      "what main.py raises, and nothing read it before")

    def test_cancel_raises_both_mechanisms(self):
        worker = self._worker_class()
        src = inspect.getsource(worker.cancel)
        self.assertIn("requestInterruption", src,
                      "cancel() must raise Qt's interruption flag; main.py's "
                      "shutdown path relies on the worker observing it")
        self.assertIn("_cancelled", src)

    def test_isinterruptionrequested_is_guarded(self):
        """It throws once the QThread is gone; the poll must not propagate."""
        worker = self._worker_class()
        src = inspect.getsource(worker._stop_requested)
        self.assertIn("except RuntimeError", src,
                      "isInterruptionRequested() raises RuntimeError on a "
                      "destroyed thread; the poll must swallow it")


class TestWorkersAreReclaimed(unittest.TestCase):
    """ARCH-ENG-169 — no unbounded worker references, and deleteLater is used."""

    def _tab_source(self):
        return (REPO / "gui" / "tabs" / "dialogue_tab.py").read_text(
            encoding="utf-8")

    def test_delete_later_is_wired_to_the_real_finished_signal(self):
        src = self._tab_source()
        self.assertIn("worker.finished.connect(worker.deleteLater)", src,
                      "the real QThread.finished must drive deleteLater so a "
                      "finished worker is actually destroyed")

    def test_retired_workers_are_pruned_and_capped(self):
        import agents.safety  # noqa: F401
        from gui.tabs.dialogue_tab import DialogueTab
        src = inspect.getsource(DialogueTab._retire_worker)
        self.assertIn("isRunning", src,
                      "finished workers must be dropped from the retirement list")
        self.assertIn("len(self._retired_workers)", src,
                      "the retirement list must be capped")
        self.assertIsNotNone(getattr(DialogueTab, "_retire_worker", None))

    def test_no_raw_append_bypasses_the_pruner(self):
        src = self._tab_source()
        self.assertNotIn(
            "self._retired_workers.append(",
            src,
            "a direct append bypasses the prune/cap; use _retire_worker()")

    def test_a_retirement_cap_is_defined(self):
        src = self._tab_source()
        self.assertIn("_MAX_RETIRED_WORKERS", src,
                      "the cap constant must exist")


class TestForceForwardCallsSomethingReal(unittest.TestCase):
    """ARCH-ENG-170 — a wired button must not call a method that doesn't exist."""

    def _force_forward_ast(self):
        src = (REPO / "gui" / "tabs" / "dialogue_tab.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "force_forward":
                return node
        self.fail("force_forward not found")

    def test_every_self_call_in_force_forward_resolves(self):
        """Reproduce the defect: `self._run_single_turn()` did not exist."""
        node = self._force_forward_ast()
        calls = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "self"
        }
        self.assertTrue(calls, "force_forward makes no self calls; is it dead?")

        src = (REPO / "gui" / "tabs" / "dialogue_tab.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        defined = {
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        # Methods assigned onto the class (signals, mixins) count as defined.
        missing = sorted(c for c in calls if c not in defined)
        self.assertEqual(
            missing, [],
            f"force_forward calls self.{', self.'.join(missing)} which does not "
            f"exist — clicking the wired button raises AttributeError")

    def test_force_forward_is_actually_wired_to_a_button(self):
        """Only worth fixing if it is reachable."""
        src = (REPO / "gui" / "tabs" / "dialogue_tab.py").read_text(
            encoding="utf-8")
        self.assertIn("force_btn.clicked.connect(self.force_forward)", src,
                      "force_forward is expected to be wired; if it is not, "
                      "the reachability argument for fixing it changes")

    def test_force_forward_uses_the_documented_turn_entry_point(self):
        node = self._force_forward_ast()
        src = ast.unparse(node)
        self.assertIn("respond(", src,
                      "force_forward must go through respond(), the per-turn "
                      "entry point that is a no-op when a turn is in flight")


if __name__ == "__main__":
    unittest.main()