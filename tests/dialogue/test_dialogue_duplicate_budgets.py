"""Regression: the two duplicate paths must not share one retry budget.

`_on_response_ready` has two duplicate branches with different budgets:
  * repeated text      -> 1 recovery attempt  (`_text_dup_retry_count`)
  * semantic duplicate -> 3 recovery attempts (`_semantic_retry_count`)

They used to share `_duplicate_retry_count`, so a repeated-text event consumed
the semantic path's three attempts (and vice versa), and the live session could
be stopped after what the operator saw as a single repeat. `_semantic_retry_count`
existed, was reset on an accepted turn, and was never incremented or read — dead
state that was clearly meant to be the semantic path's own budget.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from gui.tabs.dialogue_tab import DialogueTab  # noqa: E402


class _StubBrain:
    model = "D:/llama.cpp/models/Qwen3.5-4B-UD-Q5_K_XL.gguf"
    base_url = ""
    last_provider = "llamacpp"


REPLY = ("I will pull the top three uGig listings from the board and present "
         "them for approval before committing any work.")


def _tab(stop_recorder):
    tab = DialogueTab(small_brain=_StubBrain(), big_brain=_StubBrain())
    tab.current_speaker = "Edward Hurst"
    tab.goal = "earn money"
    tab.live_running = True
    tab.stop_live = lambda: stop_recorder.append("stop_live")
    return tab


def test_repeated_text_uses_only_the_text_budget():
    stops = []
    tab = _tab(stops)
    tab.conversation_history = [
        {"role": "assistant", "speaker": "Edward Hurst", "content": REPLY},
    ]

    tab._on_response_ready(REPLY, "Edward Hurst")

    assert tab._text_dup_retry_count == 1, "text path must own its own counter"
    assert tab._semantic_retry_count == 0, (
        "a repeated-text event must not consume the semantic path's budget")
    assert stops == [], "one repeat must still retry, not stop the session"


def test_semantic_duplicate_uses_only_the_semantic_budget():
    stops = []
    tab = _tab(stops)
    # Seed a prior decision signature so the semantic check fires.
    from gui.tabs.dialogue_tab import _decision_signature as _ds
    tab._dialogue_decisions = [("Edward Hurst", _ds(REPLY))]

    tab._on_response_ready(REPLY, "Edward Hurst")

    assert tab._semantic_retry_count == 1, "semantic path must own its own counter"
    assert tab._text_dup_retry_count == 0, (
        "a semantic duplicate must not consume the repeated-text budget")
    assert stops == []


def test_spent_text_budget_does_not_block_a_semantic_recovery():
    """The behavioural proof of independence.

    The text budget is already spent (1/1). A semantic duplicate must still get
    its own recovery attempts instead of immediately stopping the session.
    """
    stops = []
    tab = _tab(stops)
    tab._text_dup_retry_count = 1  # text budget exhausted by an earlier event
    from gui.tabs.dialogue_tab import _decision_signature as _ds
    tab._dialogue_decisions = [("Edward Hurst", _ds(REPLY))]

    tab._on_response_ready(REPLY, "Edward Hurst")

    assert stops == [], (
        "the semantic path must not be cut short by the text path's spent budget")
    assert tab._semantic_retry_count == 1
