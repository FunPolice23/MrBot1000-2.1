"""ARCH-ENG-173 — a tool that never ran was reported to the operator as one.

`chat_with_tools` classified a tool result with an inline three-way substring
test, duplicated at both the text-call and function-call sites:

    "pending_approval" if "PENDING APPROVAL" in result
    else "blocked"      if result.startswith("[BLOCKED]")
    else "error"        if result.startswith("[Tool")
    else "executed"

That misses two shapes the runtime really produces:

  * `"[Approval unavailable: web_read was not executed: ...]"` — raised by
    `dispatch.execute_tool` when the approval queue itself is unreachable. The
    tool provably did NOT run, and the operator never got a chance to approve it.
  * `"[Search error: ...]"`, `"[Web error: ...]"` — the web tool handlers' own
    failure shape.

Both fell through to `"executed"`.

The consequence was on the UI side, and it was not cosmetic.
`DialogueTab._on_tool_activity` set `real_evidence = True`, reset
`_live_turns_since_evidence`, and printed `[TOOL] actual tool call: ...`
UNCONDITIONALLY, for every event regardless of status. So a tool that never ran
was presented to the operator as a real tool call, and each such event silenced
the "you are not making progress" nudge — meaning a persona could stall
indefinitely behind a tool that could never succeed.

This is the same class ARCH-ENG-056/102/110 closed from the other direction:
those rejected narrated-but-unexecuted claims. Here the SYSTEM was labelling an
unexecuted tool as executed.

The classifier is now a single deny-list, checked first, so a refusal shape added
later defaults to "did not run" rather than to "executed". One definition
replaces both duplicated inline sites so they cannot drift again.
"""

import unittest

# ARCH-ENG-173 import order matters: `agents.safety.calling` imports
# `agents.dialogue.chat_completion` at module scope, so importing the dialogue
# module first would hit a partially-initialised cycle. Import the safety
# package first to break it, exactly as production code does.
import agents.safety  # noqa: F401
from agents.dialogue.chat_completion import _tool_status, _tool_was_executed


class TestToolsThatDidNotRunAreNotReportedAsExecuted(unittest.TestCase):
    """ARCH-ENG-173 — the regression, one real result string per shape."""

    # Each of these is a string the runtime ACTUALLY produces. The first three
    # are the regression; the rest are the shapes the old classifier did catch,
    # kept so the fix cannot regress them.
    NOT_EXECUTED = (
        "[Approval unavailable: web_read was not executed: queue unreachable]",
        "[Search error: DDGS timeout after 5s]",
        "[Web error: connection refused]",
        "[BLOCKED] run_command requires human approval",
        "[Tool error: no such file]",
        "[Tool execution error: boom]",
        "[Authorization required: write_file must be invoked through the "
        "SafetyGate-approved dispatcher]",
        "[Unknown tool: frobnicate]",
        "[PENDING APPROVAL] request_id=abc; run_command was not executed.",
    )

    def test_none_of_them_is_reported_executed(self):
        for result in self.NOT_EXECUTED:
            with self.subTest(result=result[:48]):
                self.assertFalse(
                    _tool_was_executed(result),
                    f"a tool that did NOT run was classified 'executed': {result}")
                self.assertNotEqual(_tool_status(result), "executed")

    def test_the_approval_queue_failure_is_not_executed(self):
        """The worst case: queue down, nothing ran, nobody could approve."""
        result = ("[Approval unavailable: web_read was not executed: "
                  "ConnectionError('queue file locked')]")
        self.assertEqual(_tool_status(result), "error")

    def test_pending_approval_keeps_its_own_status(self):
        self.assertEqual(
            _tool_status("[PENDING APPROVAL] request_id=x; web_read was not executed."),
            "pending_approval")
        # ...and it is still NOT executed.
        self.assertFalse(_tool_was_executed(
            "[PENDING APPROVAL] request_id=x; web_read was not executed."))

    def test_blocked_keeps_the_blocked_status(self):
        self.assertEqual(
            _tool_status("[BLOCKED] record_payment requires an approval for this amount"),
            "blocked")


class TestRealToolResultsAreStillExecuted(unittest.TestCase):
    """ARCH-ENG-173 — the fix must not flag genuine tool output as a failure.

    A guard that classified everything as "error" would silence the progress
    nudge permanently and stop the Dialogue loop making progress.
    """

    EXECUTED = (
        "# MrBot1000\nA project README with no secrets.",
        "[Analysis of notes.md]\n\nsome extracted text",
        "NOUS_API_KEY=<your-key-here>",
        "",
        "Search results:\n- Example: https://example.com",
    )

    def test_real_results_are_executed(self):
        for result in self.EXECUTED:
            with self.subTest(result=result[:40]):
                self.assertTrue(_tool_was_executed(result),
                                f"a genuine tool result was not 'executed': {result}")

    def test_empty_result_is_not_a_failure(self):
        """An empty result is a real (if unhelpful) tool outcome, not an error."""
        self.assertEqual(_tool_status(""), "executed")


class TestClassifierIsCaseAndWhitespaceTolerant(unittest.TestCase):
    """ARCH-ENG-173 — a wrapper's whitespace or casing must not flip the verdict."""

    def test_leading_whitespace_is_tolerated(self):
        self.assertFalse(_tool_was_executed("  \n [BLOCKED] run_command"))
        self.assertFalse(_tool_was_executed("\n[Tool error: x]"))

    def test_lowercase_markers_are_matched(self):
        self.assertFalse(_tool_was_executed("[approval unavailable: boom]"))
        self.assertFalse(_tool_was_executed("[tool error: boom]"))

    def test_none_input_does_not_raise(self):
        self.assertTrue(_tool_was_executed(None))


class TestEmittersCarryTheFlag(unittest.TestCase):
    """ARCH-ENG-173 / ARCH-ENG-277 — every emit sets `executed`, or the UI guesses.

    The two call branches used to carry identical inline copies of the classifier
    and the emit dict. ARCH-ENG-277 folded them into `_record_tool`, so a fix can
    no longer land in one branch and miss the other. This asserts the shared
    emitter still supplies the flag.
    """

    def test_the_shared_emitter_sets_the_executed_flag(self):
        import inspect
        from agents.dialogue import chat_completion
        src = inspect.getsource(chat_completion)
        self.assertEqual(
            src.count('"executed": _tool_was_executed(result)'), 1,
            "the shared tool recorder must carry the `executed` flag")
        # Both sources must go through it, or one branch lost its recording.
        self.assertIn('"text_call")', src)
        self.assertIn('"function_call")', src)
        self.assertEqual(src.count("_record_tool("), 3,
                         "definition plus the two call sites")

    def test_no_inline_status_classifier_survives(self):
        """The duplicated inline classifier must not creep back in."""
        import inspect
        from agents.dialogue import chat_completion
        src = inspect.getsource(chat_completion)
        self.assertNotIn('if "PENDING APPROVAL" in result', src,
                         "the old inline classifier returned; use _tool_status")
        self.assertNotIn('else "blocked" if result.startswith("[BLOCKED]")', src,
                         "the old inline classifier returned; use _tool_status")


class TestUiOnlyCountsExecutedToolsAsEvidence(unittest.TestCase):
    """ARCH-ENG-173 — the UI half: `real_evidence` and the progress guard."""

    def _ledger_and_guard(self):
        """A minimal stand-in for the tab's tool-activity handler.

        Uses the real code path's contract without constructing a QWidget, so
        this stays a plain unit test runnable headless.
        """
        import types

        tab = types.SimpleNamespace(
            _dialogue_control_ledger=[],
            _live_turns_since_evidence=5,
            _pending_tool_blocked=False,
            _blocked_states={},
            conversation_history=[],
            appended=None,
            system_text=None,
        )

        def _record_dialogue_control_state(speaker, message):
            tab._dialogue_control_ledger.append(
                {"speaker": speaker, "message": message, "real_evidence": False})

        def append_system(text):
            tab.system_text = text

        tab._record_dialogue_control_state = _record_dialogue_control_state
        tab.append_system = append_system
        return tab

    def _apply(self, tab, event):
        from gui.tabs.dialogue_tab import DialogueTab
        # Invoke the real unbound method against the stand-in.
        DialogueTab._on_tool_activity(tab, "Edward", event)

    def test_a_blocked_tool_is_not_recorded_as_real_evidence(self):
        tab = self._ledger_and_guard()
        self._apply(tab, {"name": "run_command", "status": "blocked",
                          "result_preview": "[BLOCKED] needs approval",
                          "source": "text_call", "executed": False})
        self.assertFalse(tab._dialogue_control_ledger[-1]["real_evidence"],
                         "a BLOCKED tool was recorded as real evidence")

    def test_a_blocked_tool_does_not_reset_the_progress_guard(self):
        """Silencing the nudge for a tool that never ran lets a persona stall."""
        tab = self._ledger_and_guard()
        before = tab._live_turns_since_evidence
        self._apply(tab, {"name": "web_read", "status": "error",
                          "result_preview": "[Approval unavailable: ...]",
                          "source": "function_call", "executed": False})
        self.assertEqual(tab._live_turns_since_evidence, before,
                         "a tool that never ran reset the progress guard")

    def test_the_ui_says_it_did_not_run(self):
        tab = self._ledger_and_guard()
        self._apply(tab, {"name": "web_read", "status": "error",
                          "result_preview": "[Approval unavailable: ...]",
                          "source": "function_call", "executed": False})
        self.assertIn("did NOT run", tab.system_text or "",
                      "the operator was not told the tool did not run")
        self.assertNotIn("actual tool call", tab.system_text or "")

    def test_a_real_tool_does_reset_the_progress_guard(self):
        tab = self._ledger_and_guard()
        self._apply(tab, {"name": "web_read", "status": "executed",
                          "result_preview": "some page text",
                          "source": "function_call", "executed": True})
        self.assertTrue(tab._dialogue_control_ledger[-1]["real_evidence"])
        self.assertEqual(tab._live_turns_since_evidence, 0)

    def test_a_real_tool_is_announced_as_an_actual_call(self):
        tab = self._ledger_and_guard()
        self._apply(tab, {"name": "web_read", "status": "executed",
                          "result_preview": "x", "source": "function_call",
                          "executed": True})
        self.assertIn("actual tool call", tab.system_text or "")

    def test_an_older_emitter_without_the_flag_still_behaves(self):
        """Back-compat: no `executed` key must fall back to the status."""
        tab = self._ledger_and_guard()
        self._apply(tab, {"name": "web_read", "status": "blocked",
                          "result_preview": "[BLOCKED] x", "source": "text_call"})
        self.assertFalse(tab._dialogue_control_ledger[-1]["real_evidence"])

        tab2 = self._ledger_and_guard()
        self._apply(tab2, {"name": "web_read", "status": "executed",
                           "result_preview": "x", "source": "text_call"})
        self.assertTrue(tab2._dialogue_control_ledger[-1]["real_evidence"])


if __name__ == "__main__":
    unittest.main()