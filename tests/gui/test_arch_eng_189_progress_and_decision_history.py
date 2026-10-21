"""ARCH-ENG-189/190 — two features that were built but could never run.

ARCH-ENG-189 — THE PROGRESS PANEL WAS PERMANENTLY EMPTY.

`progress_list` was created with `QListWidget()`, placed in the sidebar between
the Tasks and Goals panels, and cleared alongside them on reset — and nothing
ever added an item to it. Not one call site in the file. Three panels in a row,
two of them populated, and the operator had no way to tell "no progress yet"
from "this feature is broken".

The lifecycle phases ARE the progress, and `_next_phase()` is the single choke
point every autonomous turn passes through, so recording there captures each
phase exactly once, in order, for every entry point (Auto-Step, Live, manual)
without touching each of them.

ARCH-ENG-190 — THE SEMANTIC-DUPLICATE LOOP-BREAKER WAS DEAD CODE.

`_dialogue_decisions` was declared in `__init__` and read by the
semantic-duplicate check, and NEVER APPENDED TO. So `semantic_dup` was
permanently `False`, and the entire 34-line `if semantic_dup:` recovery branch
was unreachable.

Its own comment described a contract that did not exist:

    Two independent budgets: repeated *text* (1 recovery shot) vs repeated
    *decision signature* (3 recovery shots).

Only the textual budget was real. A persona that repeated the same decision in
REWORDED form — different casing, different line breaks — was not caught at all,
so the loop it was written to stop ran unbounded, burning tokens and filling the
transcript with the same content until the operator intervened.

This is the same shape as ARCH-ENG-188's health cache and ARCH-ENG-185's blocked
set: the consumer existed, the producer did not.
"""

import inspect
import textwrap
import types
import unittest
from unittest import mock


def _code_only(func):
    import ast
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


def _tab():
    import agents.safety  # noqa: F401  (import-cycle order)
    from gui.tabs.dialogue_tab import DialogueTab
    return DialogueTab


def _bound_stub(cls, methods=(), **attrs):
    """A stub carrying the REAL unbound methods named in `methods`.

    Binding the genuine methods (rather than reimplementing them in the stub) is
    the point: the first draft called `DialogueTab._next_phase(stub)`, and
    `_next_phase` then reached for `self._record_phase_progress`, which a plain
    SimpleNamespace does not have. Reimplementing the body in the test would
    have tested the test, not the code.

    Only the named methods are bound. Binding every method on the class raises
    SystemError on the ones that use `super()` or zero-arg `__class__`, which is
    correct behaviour and not worth working around.
    """
    tab = types.SimpleNamespace(**attrs)
    for name in methods:
        setattr(tab, name, getattr(cls, name).__get__(tab, cls))
    return tab

class _FakeList:
    """Stands in for QListWidget without needing a QApplication."""

    def __init__(self):
        self.items = []

    def addItem(self, text):
        self.items.append(text)

    def takeItem(self, index):
        return self.items.pop(index)

    def count(self):
        return len(self.items)

    def clear(self):
        self.items.clear()


# ── ARCH-ENG-189 ──────────────────────────────────────────────────────────────

class TestProgressPanelShowsPhases(unittest.TestCase):
    """ARCH-ENG-189 — the panel must be able to show something."""

    def _tab_stub(self):
        return _bound_stub(
            _tab(), methods=("_next_phase", "_record_phase_progress"),
            progress_list=_FakeList(),
            _phase_index=0,
            active_lifecycle=[("PROPOSE", True, "d"),
                              ("GATE", False, "n"),
                              ("VERIFY", True, "d")],
            _dialogue_decisions=[],
        )

    def test_a_phase_lands_in_the_progress_panel(self):
        tab = self._tab_stub()
        for _ in range(3):
            _tab()._next_phase(tab)
        self.assertEqual(len(tab.progress_list.items), 3,
                         "the Progress panel is empty; nothing populates it")

    def test_phases_appear_in_order_with_their_index(self):
        tab = self._tab_stub()
        for _ in range(3):
            _tab()._next_phase(tab)
        self.assertIn("PROPOSE", tab.progress_list.items[0])
        self.assertIn("GATE", tab.progress_list.items[1])
        self.assertIn("VERIFY", tab.progress_list.items[2])

    def test_the_phase_index_still_advances(self):
        """The fix must not change what `_next_phase` returns."""
        tab = self._tab_stub()
        first = _tab()._next_phase(tab)[0]
        second = _tab()._next_phase(tab)[0]
        self.assertEqual(first, "PROPOSE")
        self.assertEqual(second, "GATE")
        self.assertEqual(tab._phase_index, 2)

    def test_the_cycle_wraps_without_error(self):
        tab = self._tab_stub()
        for _ in range(7):
            _tab()._next_phase(tab)
        self.assertEqual(len(tab.progress_list.items), 7)
        self.assertIn("PROPOSE", tab.progress_list.items[3],
                      "the lifecycle did not wrap as expected")

    def test_the_panel_is_bounded(self):
        """A multi-hour Live session must not grow the list without limit."""
        from gui.tabs import dialogue_tab as mod
        tab = self._tab_stub()
        for _ in range(mod._MAX_PROGRESS_ROWS * 3):
            _tab()._next_phase(tab)
        self.assertLessEqual(len(tab.progress_list.items), mod._MAX_PROGRESS_ROWS,
                             f"grew to {len(tab.progress_list.items)} rows")

    def test_the_newest_rows_are_the_ones_kept(self):
        """The cap must drop the OLDEST rows, not the newest."""
        from gui.tabs import dialogue_tab as mod
        tab = self._tab_stub()
        cycle = tab.active_lifecycle
        total = mod._MAX_PROGRESS_ROWS * 2 + 1
        for _ in range(total):
            _tab()._next_phase(tab)
        expected_newest = cycle[(total - 1) % len(cycle)][0]
        self.assertIn(expected_newest, tab.progress_list.items[-1],
                      "the newest phase was evicted; the oldest should be")
        expected_oldest = cycle[(total - mod._MAX_PROGRESS_ROWS) % len(cycle)][0]
        self.assertIn(expected_oldest, tab.progress_list.items[0],
                      "the oldest retained row is wrong; the cap kept the wrong end")

    def test_a_missing_panel_does_not_break_a_turn(self):
        """Best-effort: a torn-down widget must never fail a dialogue turn."""
        tab = _bound_stub(
            _tab(), methods=("_next_phase", "_record_phase_progress"),
            progress_list=None, _phase_index=0,
            active_lifecycle=[("PROPOSE", True, "d")])
        self.assertEqual(_tab()._next_phase(tab)[0], "PROPOSE")

    def test_a_malformed_phase_does_not_break_a_turn(self):
        for bad in (None, (), "PROPOSE", 17):
            with self.subTest(phase=bad):
                tab = self._tab_stub()
                _tab()._record_phase_progress(tab, bad)
                self.assertEqual(len(tab.progress_list.items), 0)


# ── ARCH-ENG-190 ──────────────────────────────────────────────────────────────

class TestDecisionHistoryIsWritten(unittest.TestCase):
    """ARCH-ENG-190 — the consumer existed; the producer did not."""

    def _tab_stub(self):
        return _bound_stub(
            _tab(), methods=("_record_dialogue_decision",),
            _dialogue_decisions=[],
            _text_dup_retry_count=0,
            _semantic_retry_count=0,
            progress_list=_FakeList(),
            _phase_index=0,
            active_lifecycle=[("PROPOSE", True, "d")],
        )

    def _semantic_dup(self, tab, speaker, sig):
        """Reproduce the production check exactly.

        Both sides are normalised: production computes
        `sig = _decision_signature(response)` before comparing, and the writer
        normalises again on the way in. Comparing a raw string against a stored
        normalised one would never match -- which is precisely why the check has
        to normalise at BOTH ends.
        """
        from gui.tabs.dialogue_tab import _decision_signature
        want = _decision_signature(sig)
        return any(
            want == prev_sig
            for prev_speaker, prev_sig in reversed(
                getattr(tab, "_dialogue_decisions", []))
            if prev_speaker == speaker
        )

    def test_a_repeated_decision_is_now_detected(self):
        """THE REGRESSION: this was permanently False."""
        tab = self._tab_stub()
        cls = _tab()
        sig = "the ledger shows a payment of nine dollars"
        cls._record_dialogue_decision(tab, "Edward", sig)
        self.assertTrue(
            self._semantic_dup(tab, "Edward", sig),
            "a persona repeating the same decision is still not detected — the "
            "semantic-duplicate loop-breaker remains dead code")

    def test_reworded_repeats_are_detected(self):
        """The case the TEXTUAL path cannot catch."""
        tab = self._tab_stub()
        cls = _tab()
        cls._record_dialogue_decision(tab, "Edward", "check the ledger first")
        # Different casing and line breaks; identical decision.
        self.assertTrue(
            self._semantic_dup(tab, "Edward", "Check  the   ledger first"))

    def test_a_different_decision_is_not_flagged(self):
        tab = self._tab_stub()
        cls = _tab()
        cls._record_dialogue_decision(tab, "Edward", "check the ledger")
        self.assertFalse(self._semantic_dup(tab, "Edward", "check the bank"))

    def test_a_different_speaker_is_not_flagged(self):
        """Two personas may legitimately reach the same conclusion."""
        tab = self._tab_stub()
        cls = _tab()
        cls._record_dialogue_decision(tab, "Edward", "check the ledger")
        self.assertFalse(self._semantic_dup(tab, "Jacob", "check the ledger"))

    def test_the_history_is_bounded(self):
        from gui.tabs import dialogue_tab as mod
        tab = self._tab_stub()
        for i in range(mod._MAX_DECISION_HISTORY * 3):
            _tab()._record_dialogue_decision(tab, "Edward", f"decision {i}")
        self.assertLessEqual(len(tab._dialogue_decisions),
                             mod._MAX_DECISION_HISTORY)

    def test_an_empty_decision_is_not_recorded(self):
        """A blank turn carries no decision; storing '' makes blanks collide."""
        tab = self._tab_stub()
        cls = _tab()
        cls._record_dialogue_decision(tab, "Edward", "")
        cls._record_dialogue_decision(tab, "Edward", "   ")
        self.assertEqual(tab._dialogue_decisions, [])

    def test_the_accept_path_is_the_writer(self):
        """Every entry point must flow through it, or turns are missed."""
        from gui.tabs.dialogue_tab import DialogueTab
        code = _code_only(DialogueTab._on_response_ready)
        self.assertIn("_record_dialogue_decision", code,
                      "no writer: the semantic-duplicate branch is unreachable")

    def test_a_duplicate_is_never_recorded(self):
        """A recovery retry must not feed the very check that triggered it.

        Structural rather than line-number based: the record call must sit in the
        ACCEPT branch (`if not is_empty_reply:`), which is the only place a turn
        has been judged distinct. An absolute line number is brittle and, in the
        first draft, silently asserted nothing.
        """
        import ast
        from gui.tabs.dialogue_tab import DialogueTab
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(DialogueTab._on_response_ready)))

        record_calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_record_dialogue_decision"
        ]
        self.assertEqual(len(record_calls), 1,
                         "expected exactly one accept-path record call")
        record_line = record_calls[0].lineno

        # The two duplicate-recovery branches must both return BEFORE the record,
        # or a rejected repeat would be recorded as a fresh decision and the next
        # turn would compare against itself.
        dup_guards = [n.lineno for n in ast.walk(tree)
                      if isinstance(n, ast.If)
                      and isinstance(n.test, ast.Name)
                      and n.test.id in ("text_dup", "semantic_dup")]
        self.assertTrue(dup_guards, "no duplicate guard found to compare against")
        for line in dup_guards:
            self.assertLess(
                line, record_line,
                "a turn can be recorded before the duplicate checks reject it")

        # ...and the record must live INSIDE the non-empty accept branch, not
        # merely near it. Walking up from the call to its enclosing `if not X`
        # is structural and immune to how long the explanatory comment is -- the
        # first draft compared line numbers and failed purely because the
        # ARCH-ENG-190 comment block sits between the guard and the call.
        # ast nodes carry no parent pointers, so link them before walking up.
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                child._owner = parent
        cursor = record_calls[0]
        while cursor is not None:
            if (isinstance(cursor, ast.If)
                    and isinstance(cursor.test, ast.UnaryOp)
                    and isinstance(cursor.test.op, ast.Not)
                    and getattr(cursor.test.operand, "id", None) == "is_empty_reply"):
                in_accept = True
                break
            cursor = getattr(cursor, "_owner", None)
        self.assertTrue(
            in_accept,
            "the record is not inside `if not is_empty_reply:`, so a rejected or "
            "empty turn would be recorded as a fresh decision")

    def test_reset_clears_the_decision_history(self):
        """Otherwise the first turn after a Reset is judged against erased text."""
        from gui.tabs.dialogue_tab import DialogueTab
        code = _code_only(DialogueTab.reset_dialogue)
        self.assertIn("_dialogue_decisions", code,
                      "Reset must clear the remembered decisions, or the first "
                      "turn of the new session can be rejected as a repeat of "
                      "something the operator just erased")
        self.assertIn("_semantic_retry_count", code)
        self.assertIn("_text_dup_retry_count", code)


class TestTheBranchIsNoLongerDead(unittest.TestCase):
    """ARCH-ENG-190 — structural: the writer exists and is reachable."""

    def test_the_semantic_branch_is_present(self):
        from gui.tabs.dialogue_tab import DialogueTab
        code = _code_only(DialogueTab._on_response_ready)
        self.assertIn("semantic_dup", code,
                      "the semantic-duplicate check was removed entirely")

    def test_the_two_budgets_are_independent(self):
        """The documented contract: text 1 shot, decision signature 3 shots."""
        from gui.tabs.dialogue_tab import DialogueTab
        src = inspect.getsource(DialogueTab._on_response_ready)
        self.assertIn("self._text_dup_retry_count += 1", src)
        self.assertIn("self._semantic_retry_count += 1", src)
        # Distinct budgets, as the comment claims.
        self.assertNotEqual(src.count("budget = 1"), 0)
        self.assertNotEqual(src.count("budget = 3"), 0)


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-189/190 — the fixtures must express the defects."""

    def test_the_check_is_capable_of_returning_true(self):
        """If the fixture could never be a duplicate, the test is vacuous."""
        tab = types.SimpleNamespace(_dialogue_decisions=[("E", "x")])
        self.assertTrue(any("x" == s for who, s in tab._dialogue_decisions
                            if who == "E"))

    def test_the_check_is_false_on_an_empty_history(self):
        """The pre-fix state, reproduced."""
        tab = types.SimpleNamespace(_dialogue_decisions=[])
        self.assertFalse(any(
            "x" == s for who, s in reversed(tab._dialogue_decisions)
            if who == "E"))

    def test_the_reworded_pair_really_is_the_same_signature(self):
        from gui.tabs.dialogue_tab import _decision_signature
        self.assertEqual(_decision_signature("Check  the   ledger first"),
                         _decision_signature("check the ledger FIRST"))
        self.assertNotEqual(_decision_signature("check the ledger"),
                            _decision_signature("check the bank"))
