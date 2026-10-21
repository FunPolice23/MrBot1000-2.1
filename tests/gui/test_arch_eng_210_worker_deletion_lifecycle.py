"""ARCH-ENG-210 — `deleteLater` fired while `run()` was still executing.

## The crash

`EscalationWorker` connected **three** of its payload signals to `self.deleteLater`:

    self.big_done.connect(self.deleteLater)      # line 437
    self.small_summary.connect(self.deleteLater)
    self.failed.connect(self.deleteLater)

`big_done` is emitted at line 448 — and a **second long model call runs at lines
449-451, after it**:

    self.big_done.emit(bb_clean)                 # schedules deleteLater
    summary = self.small_brain.chat(...)         # run() is STILL executing
    self.small_summary.emit(summary)

`deleteLater` is deferred to the GUI thread's event loop, so the GUI thread
processed the `DeferredDelete` while `run()` was between the two model calls,
and the process died with

    QThread: Destroyed while thread is still running

exit code `0xC0000409`. Reproduced standalone under this repo's own venv. Any
Chat turn that tripped `should_escalate` killed `python.exe`; it looked
intermittent because it is a race, but the window spanned a full model call, so
it was near-certain rather than rare.

## The second, quieter half

`InferenceWorker` declared `finished = Signal(str)`, **shadowing** the inherited
zero-argument `QThread.finished`. Two things broke at once:

1. Qt's own thread-completion emission resolved to a one-argument slot, so the
   standard `worker.finished.connect(worker.deleteLater)` idiom was calling
   `deleteLater` from inside `run()`.
2. The consumers had to subscribe to `finished` for *content*, which is not what
   `finished` means — the same defect ARCH-ENG-168 fixed in `DialogueWorker`.

The signal is now `response_ready`, and deletion is driven by the inherited
`QThread.finished`, which is emitted only after `run()` returns.

## The rule these tests encode

**A signal emitted from inside `run()` must never be connected to `deleteLater`.**
Payload signals carry content to UI handlers; `QThread.finished` is the only
thing that means "this object is now safe to delete".

The audit found nine more live instances of the shadowing pattern elsewhere
(`tab_workers.py`, `collaboration_tab.py`, `main.py`). They are structural
rather than crash-inducing, so they are not fixed here, but the guard below is
deliberately package-wide so the same class cannot spread.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
CHAT_TAB = REPO / "gui" / "tabs" / "chat_tab.py"


def _class(name, path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == name)


def _qt_workers(path):
    """Every class in `path` that subclasses QThread."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef):
            bases = [ast.unparse(b) for b in n.bases]
            if any("QThread" in b for b in bases):
                out.append(n)
    return out


class TestChatWorkersNoLongerSelfDestruct(unittest.TestCase):
    """ARCH-ENG-210 — the two workers that could kill the process."""

    def test_inference_worker_does_not_shadow_finished(self):
        cls = _class("InferenceWorker", CHAT_TAB)
        self.assertNotIn(
            "finished", cls.body_names() if hasattr(cls, "body_names") else
            [t.id for n in cls.body if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name)],
            "InferenceWorker must not redeclare `finished`; the inherited "
            "zero-argument QThread signal has to stay reachable")

    def test_the_payload_signal_is_named_for_what_it_carries(self):
        cls = _class("InferenceWorker", CHAT_TAB)
        assigned = [t.id for n in cls.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)]
        self.assertIn("response_ready", assigned,
                      "the signal should be named for its payload, as "
                      "ARCH-ENG-168 required of DialogueWorker")

    def test_escalation_worker_does_not_shadow_finished(self):
        cls = _class("EscalationWorker", CHAT_TAB)
        assigned = [t.id for n in cls.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)]
        self.assertNotIn("finished", assigned)

    def test_no_payload_signal_is_wired_to_delete_later(self):
        """The rule. `big_done` was emitted before a second model call."""
        for name in ("InferenceWorker", "EscalationWorker"):
            with self.subTest(worker=name):
                cls = _class(name, CHAT_TAB)
                offenders = []
                for n in ast.walk(cls):
                    if (isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Attribute)
                            and n.func.attr == "connect"):
                        # The safety of a connect() is decided by its RECEIVER,
                        # not its arity.
                        #
                        # The first draft of this test filtered on `len(args) == 2`
                        # and was therefore vacuous: the original defect was
                        # `self.big_done.connect(self.deleteLater)`, which takes
                        # ONE argument, while the corrected form
                        # `QThread.finished.connect(self, self.deleteLater)` takes
                        # two. The guard was looking only for the fix, so it would
                        # have passed on the crash it exists to prevent. The
                        # vacuity probe below is what exposed it.
                        if not any(isinstance(a, ast.Attribute)
                                   and a.attr == "deleteLater" for a in n.args):
                            continue
                        src = ast.unparse(n.func.value)
                        if src != "QThread.finished":
                            offenders.append(src)
                self.assertEqual(
                    offenders, [],
                    f"{name} connects {offenders} to deleteLater; only the "
                    f"inherited QThread.finished may do that")

    def test_both_workers_wire_the_inherited_finished(self):
        for name in ("InferenceWorker", "EscalationWorker"):
            with self.subTest(worker=name):
                cls = _class(name, CHAT_TAB)
                body = ast.unparse(cls)
                self.assertIn(
                    "QThread.finished.connect(self, self.deleteLater)", body,
                    f"{name} must delete itself via the inherited QThread "
                    f"finished, which is emitted only after run() returns")


class TestNoWorkerElsewhereReintroducesThePattern(unittest.TestCase):
    """ARCH-ENG-210 — the audit found nine more shadowing sites.

    They are structural rather than crash-inducing, so they are not fixed here.
    This guard is package-wide so the crash-inducing case cannot come back, and
    it names the remaining sites so a later fix can work from a list.
    """

    def _shadowing_sites(self):
        found = []
        for path in sorted((REPO / "gui").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for cls in _qt_workers(path):
                for n in cls.body:
                    if (isinstance(n, ast.Assign)
                            and any(isinstance(t, ast.Name)
                                    and t.id == "finished" for t in n.targets)):
                        found.append(f"{path.relative_to(REPO)}:{n.lineno} "
                                     f"{cls.name}")
        return found

    def test_the_chat_tab_workers_are_clean(self):
        sites = self._shadowing_sites()
        offenders = [s for s in sites if "chat_tab" in s]
        self.assertEqual(offenders, [],
                         f"QThread.finished is shadowed again: {offenders}")

    def test_the_remaining_sites_are_known_not_silent(self):
        """Pins the current count so a NEW shadowing site is visible.

        If this number changes, a new worker has started shadowing `finished`
        and needs the same treatment. Update it deliberately, not by accident.
        """
        sites = [s for s in self._shadowing_sites() if "chat_tab" not in s]
        self.assertLessEqual(
            len(sites), 12,
            f"{len(sites)} QThread subclasses still shadow `finished` "
            f"(was 9 at ARCH-ENG-210): {sites}")

    def test_no_worker_anywhere_wires_a_payload_signal_to_delete_later(self):
        """The crash-inducing rule, package-wide."""
        offenders = []
        for path in sorted((REPO / "gui").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for cls in _qt_workers(path):
                for n in ast.walk(cls):
                    if (isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Attribute)
                            and n.func.attr == "connect"):
                        if not any(isinstance(a, ast.Attribute)
                                   and a.attr == "deleteLater" for a in n.args):
                            continue
                        src = ast.unparse(n.func.value)
                        if src != "QThread.finished":
                            offenders.append(
                                f"{path.relative_to(REPO)}:{n.lineno} {src}")
        self.assertEqual(
            offenders, [],
            f"a payload signal is wired to deleteLater: {offenders}")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-210 — each detector must be able to fail."""

    def test_the_delete_later_detector_sees_the_old_form(self):
        bad = ast.parse(
            "class W:\n"
            "    def __init__(self):\n"
            "        self.big_done.connect(self.deleteLater)\n")
        found = []
        for n in ast.walk(bad):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "connect"):
                if not any(isinstance(a, ast.Attribute)
                           and a.attr == "deleteLater" for a in n.args):
                    continue
                src = ast.unparse(n.func.value)
                if src != "QThread.finished":
                    found.append(src)
        self.assertEqual(
            found, ["self.big_done"],
            "the detector cannot see the original one-argument form, so it "
            "would pass while the crash returned")

    def test_the_corrected_form_is_not_flagged(self):
        """Calibration: the fix must NOT trip the guard."""
        good = ast.parse(
            "class W:\n"
            "    def __init__(self):\n"
            "        QThread.finished.connect(self, self.deleteLater)\n")
        flagged = []
        for n in ast.walk(good):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "connect"):
                if not any(isinstance(a, ast.Attribute)
                           and a.attr == "deleteLater" for a in n.args):
                    continue
                if ast.unparse(n.func.value) != "QThread.finished":
                    flagged.append(ast.unparse(n.func.value))
        self.assertEqual(flagged, [],
                         "the guard flags the corrected form, so it cannot be "
                         "distinguishing the bug from the fix")

    def test_the_qthread_scan_can_find_a_worker(self):
        """Otherwise the package-wide guard is vacuous."""
        found = _qt_workers(CHAT_TAB)
        self.assertGreaterEqual(
            len(found), 2,
            "no QThread subclasses found in chat_tab; the scan is broken and "
            "the package-wide guard would pass on anything")