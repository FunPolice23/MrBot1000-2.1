"""tests/dialogue/test_numeric_support_wiring.py — ARCH-ENG-156 (review fix).

The Reviewer found the unit tests in ``tests/test_numeric_support_check.py``
proved the *service* works but never proved the *wiring* works: they build a
``DialogueHonestyService`` directly, so changing ``dialogue_tab.py`` to re-read
``get_dialogue_context()`` at reply time — which would contain the reply's own
dollar values and report nothing — left all 15 tests green. A guard whose
regression tests cannot fail is vacuous, which is the very defect class
ARCH-ENG-156 exists to remove.

These tests drive the REAL ``DialogueTab._on_response_ready`` path.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from gui.tabs.dialogue_tab import DialogueTab  # noqa: E402
from agents.cognition.dialogue_honesty import DialogueHonestyService  # noqa: E402


class _StubBrain:
    model = "D:/llama.cpp/models/Qwen3.5-4B-UD-Q5_K_XL.gguf"
    base_url = ""
    last_provider = "llamacpp"


def _tab(context: str = ""):
    tab = DialogueTab(small_brain=_StubBrain(), big_brain=_StubBrain())
    tab.current_speaker = "Edward Hurst"
    tab.goal = "earn money"
    tab.live_running = False
    # The context this turn was shown to the model, captured at REQUEST time by
    # respond(). It deliberately does NOT contain the reply's dollar values.
    tab._last_request_context = context
    return tab


def test_fabricated_value_is_caught_through_the_real_wiring():
    """End-to-end: a reply citing money absent from the context it was shown
    must produce a recorded numeric gap via the production call path."""
    tab = _tab("Human: how did the Upwork job go?")
    assert tab._honesty is not None, "the tab must own a honesty service"

    tab._on_response_ready("I earned $9,999.00 on Upwork today.", "Edward Hurst")

    assert tab._honesty.has_numeric_gaps(), (
        "a fabricated value must be recorded through the real wiring")
    assert tab._honesty.numeric_gaps()[-1]["values"] == ["$9,999.00"]
    assert tab._honesty.to_dict()["numeric_gap_count"] == 1


def test_supported_value_is_not_a_finding_through_the_real_wiring():
    tab = _tab("The listing advertises $9,999.00 for this job.")
    tab._on_response_ready(
        "The listing pays $9,999.00.", "Edward Hurst")
    assert not tab._honesty.has_numeric_gaps(), (
        "a value the model was actually shown must not be reported")


def test_the_check_cannot_abort_the_turn():
    """Reporting only: a hostile reply must not raise, and the turn must still
    land in the transcript."""
    tab = _tab("Human: anything?")
    tab._on_response_ready("I made $200 and $300 and $400.", "Edward Hurst")
    assert any(
        m.get("speaker") == "Edward Hurst" and "made $200" in m.get("content", "")
        for m in tab.conversation_history
    ), "the turn must survive the check"


def test_no_request_context_records_nothing():
    """A headless path that never set the request context must not invent gaps."""
    tab = _tab("")
    tab._on_response_ready("I earned $9,999.00.", "Edward Hurst")
    assert not tab._honesty.has_numeric_gaps()


# ── The vacuity probe that actually guards the wiring ────────────────────────

def test_wiring_regresses_if_context_is_reread_after_the_reply():
    """This is the test the Reviewer required.

    The reply is appended to ``conversation_history`` BEFORE the honesty call.
    A naive re-read of the context at that point contains the reply's own
    ``$9,999.00`` and reports ZERO gaps. Simulating that regression proves this
    test class can actually fail — i.e. the guard is not vacuous.
    """
    tab = _tab("Human: how did it go?")
    reply = "I earned $9,999.00 today."

    # Correct wiring: request-time context, captured before the reply existed.
    tab._honesty.check_numeric_support(reply, tab._last_request_context)
    assert tab._honesty.has_numeric_gaps(), "request-time context must catch it"

    # Simulated regression: what a post-reply re-read would compare against.
    post_reply_context = tab._last_request_context + "\nEdward Hurst: " + reply
    regressed = _tab(post_reply_context)
    regressed._honesty.check_numeric_support(reply, regressed._last_request_context)

    assert not regressed._honesty.has_numeric_gaps(), (
        "a post-reply context MUST mask the value — this assertion is what makes "
        "the suite able to fail if the wiring regresses")
    assert tab._honesty.numeric_gaps() != regressed._honesty.numeric_gaps(), (
        "the two wirings must produce DIFFERENT results, or the guard is vacuous")


def test_request_context_is_captured_before_the_reply_is_appended():
    """Ordering invariant on the fixture: the context argument passed to the
    check must not already contain the reply.

    Note this asserts the *call-site contract* through the real
    ``_on_response_ready``, not that ``respond()`` performs the capture — the
    fixture injects ``_last_request_context`` by hand. That half is covered by
    ``test_respond_captures_the_request_time_context`` below, which drives the
    real ``respond()``.
    """
    tab = _tab("Human: how did it go?")
    tab._on_response_ready("I earned $9,999.00 today.", "Edward Hurst")

    assert "$9,999.00" not in (tab._last_request_context or ""), (
        "the context argument must be captured BEFORE the reply is appended")
    assert "$9,999.00" in "".join(
        m.get("content", "") for m in tab.conversation_history), (
        "and the reply itself must be in the history (proving the two differ)")


def test_honesty_service_has_no_other_production_consumer_missing_the_check():
    """Scope assertion: the numeric check is wired next to the only
    ``record_claims`` call site, so no consumer is silently left unchecked."""
    import inspect

    from gui.tabs import dialogue_tab as dt

    src = inspect.getsource(dt)
    assert src.count("check_numeric_support(") == 1, (
        "exactly one call site is expected; a second must be reviewed")
    assert src.count("record_claims(") == 1, (
        "record_claims must have exactly one call site, adjacent to the check")


# ── The capture half of the wiring (Reviewer finding #1) ─────────────────────

def _tab_with_real_respond(conversation_history):
    """A DialogueTab whose ``__init__`` does no Qt work, so the REAL
    ``respond()`` can be driven. ``respond()`` builds a DialogueWorker and
    calls ``worker.start()``; we swap in a stub worker that records the context
    it was constructed with instead of launching a thread.
    """
    import types
    from unittest.mock import MagicMock, patch

    from gui.tabs.dialogue_tab import DialogueTab

    with patch.object(DialogueTab, "__init__", lambda self, *a, **k: None):
        tab = DialogueTab()

    tab.parent = MagicMock()
    tab.current_speaker = "Edward Hurst"
    tab.goal = "earn money"
    tab.live_running = False
    tab.is_running = False
    tab.conversation_history = list(conversation_history)
    tab.big_brain = _StubBrain()
    tab.small_brain = _StubBrain()
    tab._speakers = []
    tab._agent_runtime = None
    tab._progress_throttler = None
    tab.append_system = MagicMock()
    tab._sync_adapter_models = MagicMock()
    tab._persist_dialogue_turn = MagicMock()
    tab._tier_for_speaker = MagicMock(return_value="small")
    tab._model_output_contract = MagicMock(return_value="")
    tab._current_phase_speaker = MagicMock(return_value="Edward Hurst")
    tab._brain_for = MagicMock(return_value=tab.big_brain)
    tab._capture_action_proposal = MagicMock()
    tab._maybe_record_convergence = MagicMock()
    tab._persona_name = "Edward Hurst"

    # get_dialogue_context() reads a large set of live widgets; stub it to a
    # deterministic value so respond() reaches the capture line. The capture
    # line under test is `self._last_request_context = context`, i.e. whatever
    # get_dialogue_context() returned — so stubbing it does not weaken the
    # assertion that respond() performs the capture.
    sentinel = "Human: how did the job go?"
    tab.get_dialogue_context = lambda silent=False: sentinel

    # respond() reads these further down before constructing the worker.
    tab._generation_id = 0
    tab._pending_images = []
    tab._image_label = None
    tab._response_rate_gate = lambda: True
    tab._social_enabled = False
    tab._active_proposal = None
    tab._earning_operational_context = lambda: ""
    tab._get_control_context = lambda: ""
    tab._phase_index = 0
    tab._build_social_block = lambda: ""
    tab._on_dialogue_progress = MagicMock()
    tab._on_gpu_progress = MagicMock()
    tab._on_tool_activity = MagicMock()
    tab._schedule_live_continuation = MagicMock()
    # __init__ is patched out, so build the real honesty service explicitly.
    tab._honesty = DialogueHonestyService()

    captured = {}

    class _Signal:
        def __init__(self):
            self._cbs = []

        def connect(self, cb):
            self._cbs.append(cb)

    class _StubWorker:
        """Records the context it was shown, without launching a thread.

        Qt signals are stubbed as plain attribute holders so respond()'s
        ``worker.progress.connect(...)`` lines succeed.
        """

        def __init__(self, brain, context, history, speaker,
                     system_prompt=None, **kwargs):
            captured["context"] = context
            self.progress = _Signal()
            self.gpu_progress = _Signal()
            self.tool_activity = _Signal()
            # ARCH-ENG-168: the worker's response signal was renamed from
            # `finished`, which shadowed the inherited QThread.finished (0-arity).
            self.response_ready = _Signal()
            # `finished` is still connectable because the real QThread.finished
            # is reachable again (it drives deleteLater).
            self.finished = _Signal()
            self.deleteLater = lambda: None

        def start(self):
            captured["started"] = True

    tab._worker_cls = _StubWorker
    tab._patched_worker_cls = _StubWorker
    return tab, captured, sentinel


def test_respond_captures_the_request_time_context():
    """The production capture line must be exercised.

    The Reviewer's mutation #4 deleted ``self._last_request_context = context``
    from ``respond()`` and all 7 wiring tests still passed, because the fixture
    injected the attribute by hand. This test drives the REAL ``respond()`` and
    asserts it populates the attribute itself.
    """
    tab, captured, sentinel = _tab_with_real_respond([
        {"role": "user", "speaker": "Human", "content": "how did the job go?"},
    ])

    # Patch the worker class the real respond() constructs, then call respond().
    import gui.tabs.dialogue_tab as dt

    original = dt.DialogueWorker
    dt.DialogueWorker = tab._patched_worker_cls
    try:
        tab.respond(manual=True)
    finally:
        dt.DialogueWorker = original

    assert captured.get("started"), "the stub worker should have been started"
    assert hasattr(tab, "_last_request_context"), (
        "respond() must capture the request-time context itself — deleting "
        "this capture silently disables the numeric check with a green suite")
    assert tab._last_request_context == sentinel, (
        "the captured context must be exactly what get_dialogue_context() "
        "returned for this turn")
    assert captured["context"] == sentinel, (
        "the worker must be shown the same context that was captured")


def test_capture_line_deletion_is_caught():
    """Mutation guard for the Reviewer's finding #1.

    Deletes the capture line from ``respond()``'s SOURCE on disk, asserts that
    ``test_respond_captures_the_request_time_context`` fails against the mutated
    module, then restores the file byte-for-byte and re-asserts it passes.

    This is a real mutation test, not a simulation: without it, deleting
    ``self._last_request_context = context`` left the whole suite green.
    """
    import subprocess

    import gui.tabs.dialogue_tab as dt

    path = dt.__file__
    # Binary I/O deliberately: text mode normalises CRLF->LF on write, so the
    # restore would leave the file byte-different from the original and the
    # session guard would report a spurious modification.
    with open(path, "rb") as f:
        original_src = f.read()

    capture_line = b"self._last_request_context = context"
    assert capture_line in original_src, (
        "the capture line must exist for this mutation to be meaningful")

    mutated = original_src.replace(capture_line, b"pass  # MUTATED", 1)
    assert mutated != original_src

    try:
        with open(path, "wb") as f:
            f.write(mutated)

        # Run the capture test against the mutated source, in a fresh process
        # so the module is re-imported from disk.
        proc = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/dialogue/test_numeric_support_wiring.py::"
             "test_respond_captures_the_request_time_context", "-q"],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            capture_output=True, text=True, timeout=300,
        )
        assert proc.returncode != 0, (
            "deleting the capture line MUST fail the capture test — if it "
            "still passes, the suite is vacuous on the capture side")
        assert "must capture the request-time context" in (
            proc.stdout + proc.stderr), (
            "the failure must be the capture assertion, not an unrelated error")
    finally:
        with open(path, "wb") as f:
            f.write(original_src)

    # Verify the restore is byte-exact (binary compare — text mode would
    # normalise CRLF and make the check meaningless).
    with open(path, "rb") as f:
        assert f.read() == original_src, "the source must be restored exactly"
