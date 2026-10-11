"""Turn-1 context parity: the first-turn assembler must match the main path.

`get_dialogue_context` has TWO assemblers. When `conversation_history` is empty
it returns early from its own construction (`dialogue_tab.py:2013-2059`) with
its own budget constants, its own `max(1000, ...)` floor, its own `[:limit]`
slice, and duplicated instruction text — bypassing the `prefix_fixed`/`tail`
budgeting the main path uses.

Two verified divergences this locks in:
  1. The first-turn branch omits `WORK TRACKER` entirely (both sub-branches),
     while every subsequent turn includes it.
  2. The approval guard ("stop for human approval before ...") must survive at
     the minimum context limit, exactly as the main path guarantees.

These were marked xfail while the first-turn branch had its own budget/floor and
omitted the WORK TRACKER; the fold onto the shared `prefix_fixed`/`tail` helper
has landed, so both assertions are now hard.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from gui.tabs.dialogue_tab import DialogueTab  # noqa: E402


class _StubBrain:
    model = "D:/llama.cpp/models/Ternary-Bonsai-27B-Q2_g64.gguf"
    base_url = ""
    last_provider = "llamacpp"


def _turn1_tab(limit: int) -> DialogueTab:
    tab = DialogueTab(small_brain=_StubBrain(), big_brain=_StubBrain())
    tab.goal = "earn money"
    tab.current_speaker = "Edward Hurst"
    tab.conversation_history = []  # first turn
    tab._context_char_limit = limit
    return tab


def test_turn1_context_includes_work_tracker():
    """Turn 1 must carry the same goal-continuity tracker as every other turn."""
    ctx = _turn1_tab(16000).get_dialogue_context()
    assert "WORK TRACKER" in ctx, "first-turn context is missing the work tracker"


def test_turn1_approval_guard_survives_minimum_limit():
    """The approval guard must survive at the minimum context limit (4000).

    Verified: the turn-1 branch already keeps it (the board is capped by its
    `_reserve`), so this is a hard assertion, not an xfail.
    """
    ctx = _turn1_tab(4000).get_dialogue_context()
    assert "stop for human approval before" in ctx.lower(), (
        "approval guard evicted from first-turn context at the minimum limit")
