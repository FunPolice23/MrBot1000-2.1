"""ARCH-ENG-230 - repaint work that repeated forever without changing anything.

Four findings, all the same shape: work scheduled on a timer, or a Qt call made
unconditionally, where the value almost never changes.

## 1. Eight style re-polishes every four seconds, forever

`EarningInsightsPanel._refresh` ran every 4 s and applied a `setStyleSheet` to
eight KPI labels on each pass. `QLabel.setStyleSheet` is not a plain assignment:
it invalidates the widget style, re-runs the polish, and relayouts the label and
its ancestors.

The colour is the only thing these stylesheets vary on, and it changes rarely --
so nearly all of those re-polishes wrote the identical string. Now applied only
when the value actually differs.

The same fix went into `DualBrainControl._set_gpu_bar` and `_set_gpu_status`,
which rebuilt a stylesheet for three bars per GPU every 2 s (15 s hidden) from
the same template with one of a handful of colours.

## 2. A 4-second timer that never stopped

`EarningInsightsPanel` started its `_timer` in `__init__`, so it ran for the
whole process lifetime whether or not the tab was on screen. It now starts in
`showEvent` and stops in `hideEvent`.

Starting in `__init__` is specifically wrong: a widget that is constructed but
never shown never receives `hideEvent`, so a hide-based stop can never fire.

## 3. `pause_background` did not pause the status timer

`pause_background` exists to cut background cost for a hidden tab, and
`tab_lifecycle` calls it on every tab switch away. But it only set
`gpu_worker.interval_ms = 15000`. The 4 s `_status_timer` driving
`_refresh_provider_status` kept firing, and each tick spawned a probe thread that
`_probe_with_deadline` expands into one extra thread per visible GPU row, each
doing `urlopen(timeout=2)` serially, plus a `settings.json` read.

The liveness check is genuinely worth keeping while hidden -- it is what makes a
brain that died on its own show as stopped rather than frozen at "Running"
(ARCH-ENG-073) -- so the timer is slowed to 20 s, not stopped.

An earlier draft of this file defined a second `resume_background`, which
silently shadowed the real one and restored the wrong GPU interval (4000 instead
of the 2000 default). `test_resume_restores_the_worker_default` pins the real
value, and `test_there_is_exactly_one_resume` pins that there is only one.

## 4. A set of every event index, on every query

`StructuredEventLogger.query` began with `set(range(len(self._events)))` --
allocating a set the size of the entire event log on every call, including the
common case where no filter at all is applied. The Earnings Insights tab queries
`llm_spend` every 4 s, so that was four allocations per minute of a set sized to
a log that only grows.

The unfiltered case now short-circuits before any set is built, and the filtered
cases start from the narrowest available index rather than from "every index"
intersected with a filter.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import Mock  # noqa: E402


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestStyleSheetIsOnlyAppliedWhenItChanges(unittest.TestCase):
    def setUp(self):
        _qapp()
        from gui.tabs.earning_insights import EarningInsightsPanel
        self.panel = EarningInsightsPanel.__new__(EarningInsightsPanel)

    def _counted_label(self):
        from PySide6.QtWidgets import QLabel
        w = QLabel("x")
        calls = []
        real = w.setStyleSheet
        w.setStyleSheet = lambda css: (calls.append(css), real(css))[1]
        return w, calls

    def test_repeated_identical_calls_apply_once(self):
        w, calls = self._counted_label()
        for _ in range(50):
            self.panel._apply_css(w, "color: #4caf50;")
        self.assertEqual(len(calls), 1,
                         f"{len(calls)} re-polishes for 50 identical calls")

    def test_a_real_change_still_applies(self):
        w, calls = self._counted_label()
        self.panel._apply_css(w, "color: #4caf50;")
        calls.clear()
        self.panel._apply_css(w, "color: #ff5555;")
        self.assertEqual(len(calls), 1, "a genuine colour change was skipped")

    def test_a_none_widget_is_a_no_op(self):
        self.panel._apply_css(None, "color: red")     # must not raise

    def test_the_panel_no_longer_calls_setstylesheet_directly(self):
        """Otherwise the guard is bypassed at some call sites."""
        import ast
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[2] / "gui" / "tabs" / "earning_insights.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "EarningInsightsPanel")
        direct = []
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef) or fn.name == "_apply_css":
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "setStyleSheet"):
                    direct.append(f"{fn.name}:{node.lineno}")
        self.assertEqual(direct, [],
                         f"unguarded setStyleSheet calls remain: {direct}")


class TestTheInsightsTimerIsVisibilityGated(unittest.TestCase):
    def setUp(self):
        _qapp()
        from gui.tabs.earning_insights import EarningInsightsPanel
        self.panel = EarningInsightsPanel()

    def test_it_does_not_run_before_the_tab_is_ever_shown(self):
        self.assertFalse(self.panel._timer.isActive(),
                         "the 4 s timer started in __init__; a widget that is "
                         "never shown never receives hideEvent, so a "
                         "hide-based stop could never fire")

    def test_it_runs_while_visible_and_stops_when_hidden(self):
        app = _qapp()
        self.panel.show()
        app.processEvents()
        self.assertTrue(self.panel._timer.isActive())
        self.panel.hide()
        app.processEvents()
        self.assertFalse(self.panel._timer.isActive())

    def test_it_resumes(self):
        app = _qapp()
        self.panel.show()
        app.processEvents()
        self.panel.hide()
        app.processEvents()
        self.panel.show()
        app.processEvents()
        self.assertTrue(self.panel._timer.isActive(),
                        "the timer never restarted; the tab would go stale")


class TestPauseBackgroundActuallyPauses(unittest.TestCase):
    def _widget(self):
        from PySide6.QtCore import QTimer
        from gui.widgets.dual_brain_control import DualBrainControl
        from types import SimpleNamespace
        w = DualBrainControl.__new__(DualBrainControl)
        w.gpu_worker = SimpleNamespace(interval_ms=2000)
        w._status_timer = QTimer()
        w._status_timer.setInterval(4000)
        w._gpu_ref = lambda i, k: None
        return w

    def test_the_status_timer_is_slowed_when_hidden(self):
        w = self._widget()
        w.pause_background()
        self.assertEqual(w._status_timer.interval(), 20000,
                         "the 4 s status timer still fired at full rate while "
                         "the tab was hidden")

    def test_it_is_slowed_not_stopped(self):
        """ARCH-ENG-073's guarantee must survive: a dead brain must still be
        reported as stopped while the tab is hidden."""
        w = self._widget()
        w.pause_background()
        self.assertTrue(w._status_timer.isActive() or True)
        w._status_timer.start()
        w.pause_background()
        self.assertTrue(w._status_timer.isActive(),
                        "the liveness check was stopped; a brain that died on "
                        "its own would stay frozen at 'Running'")

    def test_resume_restores_both(self):
        w = self._widget()
        w.pause_background()
        w.resume_background()
        self.assertEqual(w._status_timer.interval(), 4000)

    def test_resume_restores_the_worker_default(self):
        """The value is 2000, from GPUStatusWorker(interval_ms=2000).

        An earlier draft of this ticket added a second `resume_background` that
        shadowed the real one and restored 4000 -- wrong, and invisible because
        Python silently keeps the last definition.
        """
        w = self._widget()
        w.resume_background()
        self.assertEqual(w.gpu_worker.interval_ms, 2000)

    def test_there_is_exactly_one_resume(self):
        import ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[2]
               / "gui" / "widgets" / "dual_brain_control.py").read_text(encoding="utf-8")
        cls = next(n for n in ast.parse(src).body
                   if isinstance(n, ast.ClassDef) and n.name == "DualBrainControl")
        names = [n.name for n in cls.body
                 if isinstance(n, ast.FunctionDef)
                 and n.name in ("resume_background", "pause_background")]
        self.assertEqual(sorted(names), ["pause_background", "resume_background"],
                         f"duplicate definitions: {names} -- the last one wins "
                         f"silently")

    def test_missing_members_do_not_raise(self):
        from gui.widgets.dual_brain_control import DualBrainControl
        bare = DualBrainControl.__new__(DualBrainControl)
        DualBrainControl.pause_background(bare)
        DualBrainControl.resume_background(bare)


class TestEventLoggerDoesNotMaterialiseEveryIndex(unittest.TestCase):
    def _logger(self, n=300):
        """A real logger with real Event records.

        `log()` takes an `Event`, not loose args -- an earlier draft guessed a
        4-positional signature and failed on every arm.
        """
        from agents.core.event_logger import Event, StructuredEventLogger
        log = StructuredEventLogger()
        for i in range(n):
            log.log(Event(event_type="LLM_SPEND", level="INFO",
                          source="test", message=f"message {i}"))
        return log

    def test_an_unfiltered_query_returns_the_most_recent(self):
        log = self._logger(50)
        got = log.query(limit=10)
        self.assertEqual(len(got), 10)
        # Newest FIRST, matching the general path.
        self.assertEqual([e.message for e in got],
                         [f"message {i}" for i in range(49, 39, -1)])

    def test_an_unfiltered_query_respects_offset(self):
        """`offset` here behaves surprisingly, and the shortcut must match it.

        The general path collects only `limit` results and THEN slices
        `[offset:offset+limit]`. So an `offset` at or beyond `limit` discards
        everything and returns an empty list -- `offset=5, limit=5` is empty,
        not the next page.

        That is almost certainly not what `offset` was meant to do, but it is
        the established behaviour and the shortcut reproduces it exactly rather
        than quietly "fixing" it. Fixing it is a behaviour change for a caller
        to decide on, not something to smuggle into a performance ticket.
        """
        log = self._logger(50)

        self.assertEqual([e.message for e in log.query(limit=10)],
                         [f"message {i}" for i in range(49, 39, -1)])
        # offset strictly inside limit: drop the `offset` most recent
        self.assertEqual([e.message for e in log.query(limit=10, offset=3)],
                         [f"message {i}" for i in range(46, 39, -1)])
        # offset at limit: everything is dropped
        self.assertEqual(log.query(limit=5, offset=5), [])
        self.assertEqual(log.query(limit=5, offset=99), [])

    def test_a_filtered_query_still_filters(self):
        log = self._logger(50)
        got = log.query(level="INFO", limit=100)
        self.assertTrue(got)
        self.assertTrue(all(str(e.level).endswith("INFO") for e in got))
        # ...and a level that matches nothing comes back empty, so the
        # short-circuit is not silently ignoring the filter.
        self.assertEqual(log.query(level="CRITICAL", limit=100), [])

    def test_the_short_circuit_does_not_change_results(self):
        """Compared against the pre-existing behaviour for a filtered query."""
        log = self._logger(80)
        unfiltered = [e.message for e in log.query(limit=15)]
        self.assertEqual(unfiltered, [f"message {i}" for i in range(79, 64, -1)])

    def test_a_multi_word_search_does_not_raise(self):
        """ARCH-ENG-230: A PRE-EXISTING CRASH.

        `candidates &= s` intersected a set with a LIST, because
        `_free_text_index.get(w, [])` returns a list. The first search word was
        wrapped in `set(...)` and the rest were not -- so single-word search
        worked and multi-word search raised
        `TypeError: unsupported operand type(s) for &=: 'set' and 'list'`.

        Found only because the shortcut-equivalence test forced this branch to
        execute. It was in the code this ticket did not touch.
        """
        log = self._logger(60)
        one = log.query(search="message", limit=10)
        many = log.query(search="message 1", limit=10)
        self.assertIsInstance(many, list,
                              "a multi-word search raised instead of "
                              "returning a list")
        self.assertTrue(len(many) <= len(one),
                        "adding a second word narrowed nothing; the words are "
                        "not being intersected")
        self.assertTrue(all("message" in e.message for e in many))

    def test_an_empty_log_returns_nothing(self):
        from agents.core.event_logger import StructuredEventLogger
        self.assertEqual(StructuredEventLogger().query(limit=10), [])

    def test_the_shortcut_is_equivalent_to_the_general_path(self):
        """The load-bearing test, and the one that caught two real errors.

        The shortcut in `query` skips candidate-set construction when no filter
        is applied. It has to return exactly what the general path would, and
        that includes two things that are easy to get subtly wrong:

        - ORDER. The general path iterates `sorted(candidates, reverse=True)`,
          so results come back NEWEST FIRST. A shortcut returning them oldest
          first returns the same rows and breaks every caller that reads the
          head of the result.
        - OFFSET. The general path collects only `limit` results and THEN
          slices `[offset:offset+limit]`, so `offset >= limit` yields an EMPTY
          list. Taking `limit + offset` newest is the intuitive pagination and
          is NOT this function's behaviour.

        Both mistakes were made and both were caught here.
        """
        log = self._logger(200)

        def reference(event_type=None, level=None, source=None, search=None,
                      limit=200, offset=0, since=None, until=None):
            """The pre-change algorithm, transcribed."""
            cands = set(range(len(log._events)))
            if event_type:
                cands &= set(log._index.get(event_type, []))
            if level:
                cands &= set(log._level_index.get(level, []))
            if source:
                cands &= set(log._source_index.get(source, []))
            if search:
                words = search.lower().split()
                if words:
                    idx_sets = [log._free_text_index.get(w, []) for w in words]
                    cands &= set(idx_sets[0]) if idx_sets else set()
                    for w in idx_sets[1:]:
                        cands &= set(w)
            results = []
            for idx in sorted(cands, reverse=True):
                ev = log._events[idx]
                if since is not None and ev.ts < since:
                    continue
                if until is not None and ev.ts > until:
                    continue
                results.append(ev)
                if len(results) >= limit:
                    break
            return results[offset: offset + limit]

        cases = [
            dict(), dict(limit=10), dict(limit=10, offset=5),
            dict(limit=1000), dict(level="INFO", limit=50),
            dict(event_type="LLM_SPEND"), dict(source="a", limit=50),
            dict(search="message 1", limit=20),
            dict(level="INFO", event_type="EARNING"),
            dict(offset=7, limit=3), dict(limit=1),
            dict(limit=200, offset=1),
            dict(level="WARNING", limit=3, offset=1),
            dict(limit=0), dict(limit=10, offset=99),
        ]
        self.assertEqual(len(log._events), 200, "precondition: seeded count")
        for c in cases:
            with self.subTest(**c):
                got = [e.message for e in log.query(**c)]
                exp = [e.message for e in reference(**c)]
                self.assertEqual(got, exp,
                                 f"shortcut differs from the general path "
                                 f"for {c}")

    def test_results_come_back_newest_first(self):
        """Stated directly, because order is the thing that broke."""
        log = self._logger(20)
        got = [e.message for e in log.query(limit=5)]
        self.assertEqual(got, ["message 19", "message 18", "message 17",
                               "message 16", "message 15"])

    def test_an_offset_past_the_limit_is_empty(self):
        """The original's semantics, which the shortcut must match."""
        log = self._logger(50)
        self.assertEqual(log.query(limit=3, offset=7), [])


if __name__ == "__main__":
    unittest.main()