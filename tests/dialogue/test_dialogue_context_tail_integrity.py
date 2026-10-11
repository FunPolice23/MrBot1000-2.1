"""Tail-integrity tests for the dialogue context assembly.

The context is assembled as prefix + board + tail and then sliced to a character
limit. The board is the only elastic block; the mandatory framing must always
survive:

* the untrusted-page guard (``untrusted data``)   -- prompt-injection defence
* the ``DIALOGUE CONTROL`` framing                -- narrated calls are not evidence
* the ``WORK TRACKER`` line                       -- do not reset the goal

This class of bug has recurred every time a different block was bounded, so the
property is asserted directly instead of being re-derived by reading the
assembly order.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from gui.tabs.dialogue_tab import DialogueTab  # noqa: E402

_MANDATORY = ("untrusted data", "DIALOGUE CONTROL", "WORK TRACKER")
_LIMIT = 16000


class _StubBrain:
    model = "Qwen3.6-14B-A3B-FableVibes-Q4_K_M.gguf"
    base_url = ""
    last_provider = "llamacpp"


def _entry(i: int):
    return SimpleNamespace(
        opportunity_id=f"opp_{i}",
        platform="GitHub",
        category="bounty",
        expected_value=float(100 + i),
        work_status=SimpleNamespace(value="open"),
        opportunity_ref={
            "title": f"Candidate number {i} with a reasonably long descriptive title",
            "url": f"https://example.test/opportunity/{i}",
            "source": "GitHub",
            "category": "bounty",
        },
    )


def _tab(entries: int, history_turns: int) -> DialogueTab:
    app = None
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
    except Exception:
        pytest.skip("PySide6 unavailable")
    assert app is not None

    tab = DialogueTab(small_brain=_StubBrain(), big_brain=_StubBrain())
    tab._context_char_limit = _LIMIT
    visible = [_entry(i) for i in range(entries)]
    tab._visible_opportunity_entries = lambda: (object(), visible)
    tab.conversation_history = []
    for i in range(history_turns):
        tab.conversation_history.append(
            {"role": "assistant", "speaker": "Edward Hurst",
             "content": f"Turn {i}: " + "analysis of candidate options " * 20})
        tab.conversation_history.append(
            {"role": "user", "speaker": "Human",
             "content": f"Human directive {i}: " + "keep going and do not repeat " * 15})
    return tab


def _assert_mandatory_present(context: str, label: str):
    missing = [marker for marker in _MANDATORY if marker not in context]
    assert not missing, (
        f"{label}: mandatory framing evicted by truncation: {missing} "
        f"(len={len(context)} limit={_LIMIT})")


def test_mandatory_framing_survives_a_full_board():
    tab = _tab(entries=200, history_turns=2)
    _assert_mandatory_present(tab.get_dialogue_context(), "full board, short history")


def test_mandatory_framing_survives_a_long_conversation():
    """Worst case: elastic history AND a board both large at once.

    The board budget has a 1000-char floor, so when prefix+tail already approach
    the limit the composed string exceeds it and the trailing slice evicts the
    mandatory tail again.
    """
    tab = _tab(entries=200, history_turns=200)
    context = tab.get_dialogue_context()
    assert len(context) <= _LIMIT, f"context exceeds limit: {len(context)}"
    _assert_mandatory_present(context, "full board + long history")


def test_mandatory_framing_survives_a_small_limit():
    """The guarantee must hold for any configured limit, not just the default."""
    tab = _tab(entries=0, history_turns=500)
    tab._context_char_limit = 4000
    _assert_mandatory_present(tab.get_dialogue_context(), "small limit, long history")
