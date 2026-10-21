"""ARCH-ENG-180/181/182 — three ways the runtime lied to the operator.

ARCH-ENG-180 — RAW CHAIN-OF-THOUGHT WAS RETURNED AS THE PERSONA'S ANSWER.

    answer = "".join(answer_parts)
    if not answer.strip() and reasoning_parts:
        answer = "".join(reasoning_parts)

When a reasoning model exhausts its token budget mid-thought it emits a
`reasoning` delta and never reaches the answer channel. This line took that raw
chain-of-thought and returned it AS THE ANSWER, so it became the persona's
visible dialogue turn, was appended to `conversation_history`, and was persisted
to the dialogue log as something the persona "said".

This is the class of defect this project exists to prevent, arriving from a new
direction. ARCH-ENG-056/102/110 stopped the SYSTEM presenting narrated-but-
unexecuted claims as real; ARCH-ENG-173 stopped it labelling an unexecuted tool
as executed. Here the SYSTEM relabelled raw model reasoning as a deliberate
answer — and it is worse than either, because raw CoT is also unreadable and
misattributed: the persona never chose to say it.

An empty answer channel is an EMPTY RESPONSE, and the tab already has a
deterministic handler for that. So `answer` stays empty and that path runs.

ARCH-ENG-181 — `DualBrainControl.cleanup` SHADOWED THE BACKEND'S TEARDOWN.

`DualBrainControl(ProviderLifecycleBackend, QWidget)` mixes the backend in as a
base class, and `ProviderLifecycleBackend.cleanup` holds the carefully ordered
teardown: set `_closing` FIRST so background callbacks stop re-arming, join the
probe thread, then stop and wait for every worker. Its own docstring names the
failure it prevents — "letting that escape would abort teardown and leave the
remaining threads running".

The widget's override never called `super()`, so none of that ran for the
widget — the only case that matters. The widget's own worker list also omitted
`_small_prep_worker` / `_big_prep_worker` (GGUF inspection before a launch) and
had no handling at all for the per-slot launch workers of extra devices
(`_slot_{n}_launch_worker`, slots 2+ in the N-brain roster). Any of those still
running at teardown aborts the process with the "QThread: Destroyed while thread
is still running" / exit-139 class.

ARCH-ENG-182 — `QTimer.singleShot` FROM A RAW `threading.Thread`.

`_do_restart` is started with `threading.Thread`, so it has NO Qt event loop. Its
error path called:

    QTimer.singleShot(0, lambda: self._set_loading(small, False, ""))

which posts a timer event to a loop that does not exist. The callback may never
run, leaving the brain row stuck at "Loading…" with no error anywhere — the
operator's model switch silently did nothing, and nothing in the UI says why.

Replaced with a Qt signal, which Qt queues onto the GUI thread because the
receiver's affinity is the GUI thread. That is precisely the distinction the
backend's own thread-marshalling comments describe.
"""

import ast
import inspect
import re
import textwrap
import unittest


def _code_only(func):
    """Source with the docstring stripped.

    These guards must not match the prose that documents the defect. Every
    assertion here is about structure, and ARCH-ENG-180/181/182 all quote the
    old code in their own docstrings.
    """
    body = textwrap.dedent(inspect.getsource(func))
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return body
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef, ast.Module))
                and ast.get_docstring(node, clean=False)):
            node.body = node.body[1:]
    return ast.unparse(tree)


# ── ARCH-ENG-180 ──────────────────────────────────────────────────────────────

class TestReasoningIsNeverTheAnswer(unittest.TestCase):
    """ARCH-ENG-180 — the reasoning channel is not the answer channel."""

    def _src(self):
        import agents.safety  # noqa: F401  (import-cycle order)
        from agents.dialogue import chat_completion
        return inspect.getsource(chat_completion)

    def _generation_code(self):
        """ARCH-ENG-277 (AG-01): the loop and its generation phase now live in
        `chat_with_tools` and `_run_generation`. Read both, or these contracts
        pass by not looking at the code that implements them."""
        from agents.dialogue import chat_completion
        return "\n".join(
            _code_only(getattr(chat_completion, name))
            for name in ("chat_with_tools", "_run_generation"))

    def test_reasoning_is_not_promoted_to_the_answer(self):
        src = self._src()
        code = self._generation_code()
        self.assertNotIn(
            'answer = "".join(reasoning_parts)', code,
            "raw chain-of-thought is still returned as the persona's answer; it "
            "is then shown in the transcript, added to conversation_history, and "
            "persisted to the dialogue log as something the persona said")
        self.assertNotIn(
            "answer = ''.join(reasoning_parts)", code,
            "raw chain-of-thought is still returned as the persona's answer")

    def test_an_empty_answer_still_raises_for_the_empty_handler(self):
        """The fix must route to the existing deterministic empty path."""
        code = self._generation_code()
        # Quote-agnostic: `ast.unparse` normalises string literals to single
        # quotes, so asserting on the source spelling would be brittle.
        self.assertIn("empty stream response", code,
                      "an empty answer must still raise so the tab's bounded "
                      "empty-response handler runs, rather than being filled "
                      "with reasoning")
        self.assertIn("RuntimeError", code,
                      "the empty-response raise must still be a RuntimeError so "
                      "the existing `except TypeError` fallback does not "
                      "swallow it")

    def test_a_real_answer_is_untouched(self):
        """The fix must not drop a genuine answer that follows reasoning."""
        code = self._generation_code()
        self.assertIn("answer_parts", code,
                      "the ANSWER channel must still be assembled as before")
        # `ast.unparse` normalises quotes, so accept either spelling rather than
        # asserting on the exact source form.
        self.assertTrue(
            any(f"{q}.join(answer_parts)" in code for q in ("'", '"')),
            "the answer must still be built from answer_parts, not from "
            "reasoning_parts")


# ── ARCH-ENG-181 ──────────────────────────────────────────────────────────────

class TestCleanupCallsTheBackend(unittest.TestCase):
    """ARCH-ENG-181 — the mixin's teardown must actually run."""

    def _control(self):
        from gui.widgets.dual_brain_control import DualBrainControl
        return DualBrainControl

    def test_cleanup_calls_super(self):
        code = _code_only(self._control().cleanup)
        self.assertIn(
            "super()", code,
            "DualBrainControl.cleanup overrides ProviderLifecycleBackend.cleanup "
            "and never calls super(), so NONE of the backend's worker teardown "
            "runs for the widget — the only case that matters")

    def test_cleanup_covers_the_prep_workers(self):
        code = _code_only(self._control().cleanup)
        self.assertIn("_small_prep_worker", code,
                      "the prep workers are QThreads that inspect a GGUF before "
                      "launch; one left running at teardown aborts the process")
        self.assertIn("_big_prep_worker", code)

    def test_cleanup_covers_per_slot_launch_workers(self):
        code = _code_only(self._control().cleanup)
        self.assertIn("_slot_launch_worker_names", code,
                      "extra devices' launchers (_slot_{n}_launch_worker) had "
                      "no teardown at all — the N-brain roster's slots 2+ could "
                      "be running a QThread when Qt destroyed the widget")

    def test_slot_worker_discovery_finds_every_slot(self):
        import types
        tab = types.SimpleNamespace()
        tab._slot_0_launch_worker = object()
        tab._slot_2_launch_worker = object()
        tab._slot_3_launch_worker = object()
        tab._small_launch_worker = object()      # not a slot worker
        names = self._control()._slot_launch_worker_names(tab)
        self.assertEqual(sorted(names),
                         ["_slot_0_launch_worker", "_slot_2_launch_worker",
                          "_slot_3_launch_worker"])

    def test_slot_worker_discovery_tolerates_a_bare_object(self):
        """`vars()` on an object with no __dict__ must not raise."""
        class NoDict:
            __slots__ = ()
        self.assertEqual(self._control()._slot_launch_worker_names(NoDict()), [])

    def test_the_backend_teardown_is_still_intact(self):
        """The fix must not have emptied the base class's careful ordering."""
        from gui.workers.provider_lifecycle_backend import ProviderLifecycleBackend
        code = _code_only(ProviderLifecycleBackend.cleanup)
        self.assertIn("_closing", code,
                      "the closing flag must be set FIRST so background "
                      "callbacks stop re-arming during teardown")
        self.assertIn("_provider_probe_thread", code)
        self.assertIn("gpu_worker", code)


# ── ARCH-ENG-182 ──────────────────────────────────────────────────────────────

class TestNoQtTimerFromARawThread(unittest.TestCase):
    """ARCH-ENG-182 — a raw worker has no event loop for a QTimer to fire on."""

    def _control(self):
        from gui.widgets.dual_brain_control import DualBrainControl
        return DualBrainControl

    def test_do_restart_does_not_use_qtimer(self):
        code = _code_only(self._control()._do_restart)
        self.assertNotIn(
            "QTimer.singleShot", code,
            "QTimer.singleShot from a `threading.Thread` posts to a loop that "
            "does not exist; the brain row stays stuck at 'Loading...' with no "
            "error anywhere")

    def test_do_restart_marshals_through_a_signal_instead(self):
        code = _code_only(self._control()._do_restart)
        self.assertIn("_clear_loading_on_gui_thread", code,
                      "the GUI update must be marshalled onto the Qt thread")

    def test_the_marshalling_signal_is_declared(self):
        from gui.widgets.dual_brain_control import DualBrainControl
        self.assertTrue(hasattr(DualBrainControl, "_loading_clear_requested"),
                        "the marshalling signal does not exist")

    def test_the_marshalling_signal_is_connected(self):
        src = inspect.getsource(self._control())
        self.assertIn(
            "self._loading_clear_requested.connect(",
            src,
            "the signal is declared but never connected, so emitting it does "
            "nothing — the same stuck-'Loading...' bug in a new shape")

    def test_a_worker_side_emitter_is_guarded_against_teardown(self):
        code = _code_only(self._control()._clear_loading_on_gui_thread)
        self.assertIn("RuntimeError", code,
                      "emitting from a worker while Qt is tearing down raises; "
                      "it must be swallowed, not abort the shutdown")

    def test_the_gui_side_handler_refuses_after_closing(self):
        code = _code_only(self._control()._on_loading_clear_requested)
        self.assertIn("_closing", code,
                      "a queued call can land after teardown started; the slot "
                      "must not touch widgets then")

    def test_the_real_restart_path_still_emits_its_ready_signal(self):
        """The fix must not have broken the happy path."""
        code = _code_only(self._control()._do_restart)
        self.assertIn("_restart_ready.emit", code,
                      "the successful restart hand-off must be unchanged")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-180/181/182 — each detector must be able to fail."""

    def test_the_reasoning_probe_can_express_a_thinking_only_response(self):
        """Prove the fixture shape this defect produced is representable."""
        answer_parts, reasoning_parts = [], ["internal thought "]
        answer = "".join(answer_parts) or "".join(reasoning_parts)
        self.assertIn("internal thought", answer,
                      "the probe cannot reproduce the leak, so the guard is "
                      "vacuous")

    def test_the_slot_name_matcher_is_anchored(self):
        """`_slot_1_launch_worker_extra` must NOT match."""
        from gui.widgets.dual_brain_control import DualBrainControl
        self.assertTrue(re.fullmatch(
            r"_slot_\d+_launch_worker", "_slot_7_launch_worker"))
        self.assertIsNone(re.fullmatch(
            r"_slot_\d+_launch_worker", "_slot_7_launch_worker_extra"))


if __name__ == "__main__":
    unittest.main()