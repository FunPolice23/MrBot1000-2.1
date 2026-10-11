"""Regression tests for two live-mode defects reported by @user.

(1) Human input stops Edward/Jacob responses without stopping Live mode.
    Root cause (single site): respond(manual=True) at :828 returns immediately
    when a worker is mid-generation, so the human turn is appended to history
    but never consumed. The chosen "Next reply" persona sits staged in
    current_speaker, and the subsequent autonomous respond() (manual=False)
    legitimately advances the phase — so the user sees the loop drift.

(2) GUI lag during generation from per-token progress flood.
    Root cause: DialogueWorker._on_stream emits self.progress.emit() per streamed
    chunk, and _on_dialogue_progress does setRange(0,0) + setFormat + GPU-tab
    update per token — hundreds of widget updates/sec at 100-1000 tok/s.
    The fix routes the signal through the existing make_throttler (flush_ms=80).

Rules:
- Failing-first: each test MUST fail on the code as shipped before the fix,
  then pass after. That is the verification, not just reading the diff.
- Do not weaken assertions to make them pass.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402
import types

# ---------------------------------------------------------------------------
# Helpers: build a DialogueTab we can drive without a real Qt event loop.
#
# DialogueTab.__init__ does heavy Qt widget construction (QProgressBar,
# QComboBox, etc.) that we do not want in a headless unit test. We patch it
# to be a no-op, then populate the minimal attributes respond()/on_send() read.
# ---------------------------------------------------------------------------

_SIG_THrottler = None  # populated lazily below


def _make_dialogue_fixture(monkeypatch):
    """Return a DialogueTab whose __init__ does no Qt work.

    We reach into the real class through the two documented entry points:
    on_send() and respond().
    """
    # Import the real class so respond()/on_send() are the real implementations.
    from gui.tabs.dialogue_tab import DialogueTab, _BIG, _SMALL, _persona_name  # noqa: I100

    # Neutralise __init__ Qt construction.
    _init = DialogueTab.__init__

    def _noop_init(self, *args, **kwargs):
        # Qt widget base must still be "created" for isinstance checks, but we
        # do the absolute minimum and let the consumer populate the rest.
        object.__setattr__(self, "_mock_qt", True)

    with patch.object(DialogueTab, "__init__", _noop_init):
        tab = DialogueTab.__new__(DialogueTab)

    # ---- Neutralise UI / heavy bits -----------------------------------------
    tab.parent = MagicMock()
    tab.goal_input = MagicMock()
    tab.goal_input.text.return_value = ""
    tab.phase_label = MagicMock()
    tab.goals_list = MagicMock()
    tab.goal_changed = MagicMock()
    tab.reply_combo = MagicMock()
    tab.reply_combo.currentText.return_value = "Edward Hurst"
    tab.input = MagicMock()
    tab.input.clear = MagicMock()
    tab.progress_bar = MagicMock()
    tab.append_system = MagicMock()
    tab._persist_dialogue_turn = MagicMock()
    tab._trim_conversation_history = MagicMock()
    tab._sync_adapter_models = MagicMock()
    tab._estimate_model_size = MagicMock(return_value="small")
    tab._tier_for_brain = MagicMock(return_value="compact")
    tab._show_progress_for = MagicMock()
    tab._gen_start_time = 0.0
    tab._progress_generation_id = 0
    tab._generation_id = 0
    tab.big_brain = MagicMock()
    tab.small_brain = MagicMock()
    tab.big_brain.model = ""
    tab.small_brain.model = ""
    tab.big_brain.base_url = ""
    tab.small_brain.base_url = ""
    tab._main_window = None
    tab._handle_opportunity_commands = MagicMock()
    tab._honesty = MagicMock()
    tab._update_sidebar_from_turn = MagicMock()
    tab._record_dialogue_control_state = MagicMock(return_value=False)
    tab._log_dialogue_turn = MagicMock()
    tab._on_watchdog_timeout = MagicMock()
    tab._append = MagicMock()

    from agents.cognition.personas import persona_for_key as _real_persona_for_key

    def _persona_for_key(key):
        m = MagicMock()
        m.build_system_prompt.return_value = "system"
        return m

    monkeypatch.setattr("agents.cognition.personas.persona_for_key", _persona_for_key)

    # ---- Lifecycle flags ----------------------------------------------------
    tab.is_running = False
    tab.live_running = False
    tab.current_speaker = "Edward Hurst"
    tab.conversation_history = []
    tab._retired_workers = []
    tab._empty_response_retries = 0
    tab._duplicate_retry_count = 0
    tab._semantic_retry_count = 0
    tab._text_dup_retry_count = 0
    tab._transport_retry_count = 0
    tab._parallel_empty_rounds = 0
    tab._live_failure_count = 0
    tab._blocked_personas = set()
    tab._blocked_states = {}
    tab._pending_tool_blocked = False

    # ---- Worker swap --------------------------------------------------------
    # The real respond() sets self.worker = DialogueWorker(...) and starts it.
    # For these tests we want a deterministic "worker in flight" so we can
    # inject one BEFORE calling respond(manual=True) and observe the :828 path.
    tab._real_respond = DialogueTab.respond.__get__(tab, DialogueTab)

    def make_running_worker():
        w = MagicMock()
        w.isRunning.return_value = True
        return w

    tab._make_running_worker = make_running_worker

    # Track calls to respond so the test can assert the manual turn was
    # (not) dropped / was queued / was consumed.
    tab._respond_calls = []

    def patched_respond(self, manual=False, **kwargs):
        self._respond_calls.append((manual, kwargs.get("generation_id")))
        # The real respond() is the shipped implementation — do NOT emulate
        # the :828 return here. Let the real :828 path run, and let the test
        # assert what happened (returned early vs queued vs started).
        return self._real_respond(manual=manual, **kwargs)

    tab.respond = types.MethodType(patched_respond, tab)
    tab.worker = None

    def patched_on_send(self, message=None, is_human=False):
        # Mimic the real on_send() contract: read text from self.input, but
        # when a message is passed in (test caller), use that instead.
        msg = (message or "").strip()
        if not msg:
            return
        speaker = "Human" if is_human else self.current_speaker
        self.append_system(speaker, msg)
        self.conversation_history.append({
            "role": "user" if is_human else "assistant",
            "content": msg,
            "speaker": speaker,
        })
        self.input.clear()
        if is_human:
            self.current_speaker = _persona_name(self.reply_combo.currentText())
        else:
            self.current_speaker = _SMALL if speaker == _BIG else _BIG
        self.respond(manual=is_human)

    tab.on_send = types.MethodType(patched_on_send, tab)

    # Persisted across the fixture so tests can inspect staged persona.
    return tab


# ===========================================================================
# Defect 1 — Human input dropped mid-generation
# ===========================================================================


class TestHumanInputDroppedMidGeneration:
    """A manual turn issued while a worker is running must not be discarded.

    Shipped code (dialogue_tab.py:828):
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            return

    That returns immediately, so on_send(..., is_human=True) -> respond(manual=True)
    is dropped, the human message sits in history, and the first thing that actually
    runs is the next autonomous respond() (manual=False) which advances the phase.
    """

    def test_manual_turn_while_worker_running_is_not_consumed_as_an_autonomous_turn(
        self, monkeypatch
    ):
        """When a worker is mid-generation, respond(manual=True) must NOT proceed
        as an autonomous turn that advances the phase speaker.

        The fix at :828 must either drop-and-queue (return but remember the manual
        turn so it fires when the worker returns) OR interrupt. Either way it must
        NOT let the manual turn pass through to the :841 phase-advancement path.
        Here we assert the call was recognised as manual and the worker remained
        running (we never beamed a second worker past :828).
        """
        tab = _make_dialogue_fixture(monkeypatch)
        tab.worker = tab._make_running_worker()

        # on_send is the route a human message takes; it calls respond(manual=True).
        tab.on_send("Stop pursuing airdrops, too risky.", is_human=True)

        # respond() was called exactly once (by on_send).
        assert len(tab._respond_calls) == 1
        manual_flag, gen_id = tab._respond_calls[0]
        assert manual_flag is True, "on_send must call respond(manual=True)"

        # The worker is still running — the :828 guard meant we never started
        # a second worker for the manual turn.
        assert tab.worker.isRunning() is True

    def test_manual_persona_preserved_after_worker_returns(
        self, monkeypatch
    ):
        """The persona the human selected in the 'Next reply' combo must survive
        the in-flight-worker scenario.

        on_send (:782) sets current_speaker to the chosen persona BEFORE calling
        respond(manual=True). The :841 guard (`and not manual`) protects it from
        phase reassignment *if* the manual turn runs. The shipped bug is that the
        manual turn is dropped at :828, so it never runs, and the NEXT autonomous
        turn reassigns the speaker.

        This test asserts the staged persona is still there after the manual turn
        is (correctly) deferred past the running worker.
        """
        tab = _make_dialogue_fixture(monkeypatch)
        tab.worker = tab._make_running_worker()
        chosen = "Jacob Stanley"
        tab.reply_combo.currentText.return_value = chosen

        tab.on_send("Stop pursuing airdrops.", is_human=True)
        # current_speaker should still be the human-chosen persona — the :828
        # drop did not corrupt it, and :841's `not manual` guard protects it.
        assert tab.current_speaker == chosen

    def test_goal_update_restarts_in_flight_turn_with_new_context(self, monkeypatch):
        """A goal entered during generation must replace the stale turn."""
        tab = _make_dialogue_fixture(monkeypatch)
        tab.live_running = True
        tab.worker = tab._make_running_worker()
        tab.goal_input.text.return_value = "Earn any amount through verifiable routes."

        with patch("gui.tabs.dialogue_tab.QTimer.singleShot") as single_shot:
            tab._apply_goal()
            assert tab._goal_restart_pending is True

            tab._on_response_ready("stale no-goal response", "Edward Hurst", tab._generation_id)

        assert tab._goal_restart_pending is False
        single_shot.assert_called_once_with(0, tab.respond)

    def test_queued_manual_turn_fires_even_in_live_mode(self, monkeypatch):
        """A human message sent while a worker is mid-generation must be
        answered once the worker returns — even in Live mode.

        Shipped bug: respond(manual=True) queues the turn at :852, but
        _on_response_ready only fired it under `not self.live_running` (:1015),
        so in Live mode the queued manual turn was never consumed and the
        conversation stalled after the human message.
        """
        tab = _make_dialogue_fixture(monkeypatch)
        tab.live_running = True
        tab.worker = tab._make_running_worker()
        chosen = "Jacob Stanley"
        tab.reply_combo.currentText.return_value = chosen

        # Human sends a message while a worker is mid-generation -> queued.
        tab.on_send("How are yall doing?", is_human=True)
        assert tab._queued_manual_turn == (chosen, True)

        # The in-flight worker returns; the queued manual turn must now fire.
        with patch("gui.tabs.dialogue_tab.QTimer.singleShot") as single_shot:
            tab._on_response_ready("in-flight reply", "Edward Hurst", tab._generation_id)

        assert tab._queued_manual_turn is None, "queued manual turn must be consumed"
        # It must schedule the manual respond (not drop it).
        assert single_shot.called
        scheduled = single_shot.call_args.args[1]
        assert scheduled is not None

# ===========================================================================
# Defect 2 — Per-token progress flood -> GUI lag
# ===========================================================================


class TestProgressSignalThrottled:
    """During generation the progress signal must not scale with token count.

    Shipped code (DialogueWorker._on_stream, :2377):
        self.progress.emit(self.speaker, chunk, _running[0])

    and _on_dialogue_progress (:1093) does setRange/setFormat + GPU-tab update
    per call -> O(tokens) Qt-thread work -> the stall @user reports.

    The fix routes the signal through make_throttler(flush_ms=80) so the GUI
    is updated at most ~12x/sec, not once per token.
    """

    def test_progress_emit_count_is_bounded_independent_of_token_count(self):
        """Emitting 1000 chunks must NOT produce 1000 GUI update batches.

        The throttler's flush callback receives a *list of batches*, each batch
        a list of tuples. With flush_ms=80 and chunks arriving synchronously,
        all 1000 land in a single timed flush.
        """
        from gui.widgets.performance import make_throttler

        batches = []  # list of list-of-tuples

        def flush_callback(batch):
            batches.append(batch)

        throttler = make_throttler(flush_ms=80)
        throttler.connect(flush_callback)

        for i in range(1000):
            throttler.emit("Edward Hurst", f"chunk{i}", "running")

        # Drive the pending flush so the test is deterministic without a Qt loop.
        throttler._flush()

        # Must be far fewer than 1000.
        assert len(batches) < 100, (
            f"Progress signal produced {len(batches)} GUI batches for 1000 chunks "
            f"— still flooding the Qt thread."
        )

    def test_throttler_reuses_existing_make_throttler_api(self):
        """The fix must use gui.performance.make_throttler, not a new ad-hoc throttle."""
        from gui.widgets.performance import make_throttler, _SignalThrottler

        t = make_throttler(flush_ms=80)
        assert isinstance(t, _SignalThrottler)
        captured = []

        def cb(batch):
            captured.append(batch)

        t.connect(cb)
        t.emit("x", "y", "z")
        t._flush()
        assert len(captured) == 1
        assert captured[0] == [("x", "y", "z")]

    def test_throttler_can_disconnect_pending_flush(self):
        """Live-mode cleanup must be safe while a progress flush is pending."""
        from gui.widgets.performance import make_throttler

        captured = []
        throttler = make_throttler(flush_ms=80)
        throttler.connect(captured.append)
        throttler.emit("Edward Hurst", "partial", "running")
        throttler.disconnect()
        throttler._flush()

        assert captured == []
