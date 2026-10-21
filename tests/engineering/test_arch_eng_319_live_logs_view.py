"""ARCH-ENG-319 -- the Live Logs table is a *view*: complete whenever shown,
empty-when-hidden by design, with row↔entry mapping that survives filtering.

The finding
-----------
The deferred-table model of ARCH-ENG-223 was right (no widget work while
hidden) but the replay that was supposed to materialise the view ran at BUILD
time, while the freshly built widget was still hidden. The hidden guard
therefore deferred every row, nothing rescheduled it, and the operator opened
an empty Live Logs tab until they poked the filter.

Two latent defects of the same shape were fixed in the same pass:

* live appends ignored the active filters — a new line that did not match the
  operator's filter still landed on the table, polluting a filtered view;
* the details panel indexed ``_log_buffer[row]`` while the table showed a
  filtered view, so with a filter active the details panel described the
  WRONG entry. The view now records its own row mapping (`_view_entries`).

Fix: one rebuild path (`_replay_log_view`) shared by replay and filter-apply,
the view mapping in `_view_entries`, filters enforced inside
`_append_log_to_table` (the only row-producing method), and the rebuild
hooked to the tab shell's showEvent so every open shows the complete view.
"""

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QTableWidget, QLineEdit, QTextEdit


def _qapp():
    return QApplication.instance() or QApplication([])


def _entry(msg="hello", severity="INFO", source="x", category="System",
           color="#aaaaaa", tokens_sec="", details=""):
    return {"ts": "12:00:00", "severity": severity, "source": source,
            "msg": msg, "tokens_sec": tokens_sec, "category": category,
            "details": details, "color": color}


class TestArchEng319LiveLogsView(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _qapp()
        import main as M
        for obj in vars(M).values():
            if inspect.isclass(obj) and "_append_log_to_table" in vars(obj):
                cls.owner = obj
                return
        raise AssertionError("no class defines _append_log_to_table")

    def _harness(self, visible=True):
        h = self.owner.__new__(self.owner)
        h.log_table = QTableWidget(0, 6)
        if visible:
            h.log_table.show()
        else:
            h.log_table.hide()
        _qapp().processEvents()
        h.auto_scroll_logs = None
        h.log_filter = QLineEdit()
        h.log_severity_combo = QComboBox()
        h.log_severity_combo.addItems(["All", "INFO", "WARNING", "ERROR"])
        h.log_category_combo = QComboBox()
        h.log_category_combo.addItems(["All", "System", "LLM"])
        h.log_details = None
        h._log_buffer = []
        return h

    def test_replay_after_show_fills_the_table(self):
        """The core defect: entries logged while hidden must appear once the
        tab is shown — without touching any filter."""
        h = self._harness(visible=False)
        for i in range(5):
            h._append_log(f"line {i}")
        h._replay_log_buffer()          # build-time replay (still hidden)
        self.assertEqual(h.log_table.rowCount(), 0,
                         "a hidden tab must receive no rows (ARCH-ENG-223)")
        self.assertEqual(len(h._log_buffer), 5,
                         "a hidden replay must lose nothing from the buffer")

        h.log_table.show()
        _qapp().processEvents()
        h._replay_log_buffer()          # the showEvent-triggered rebuild
        self.assertEqual(h.log_table.rowCount(), 5,
                         "the view was still empty after the tab became "
                         "visible; nothing rescheduled the deferred rebuild")
        self.assertEqual(len(h._view_entries), 5)

    def test_visible_live_appends_lay_on_the_table(self):
        h = self._harness()
        before = h.log_table.rowCount()
        h._append_log("fresh line")
        self.assertEqual(h.log_table.rowCount(), before + 1)
        self.assertEqual(len(h._view_entries), before + 1)

    def test_filtered_live_append_stays_off_the_view(self):
        h = self._harness()
        h.log_severity_combo.setCurrentText("INFO")
        h._append_log("plain info line")            # matches -> row
        self.assertEqual(h.log_table.rowCount(), 1)
        self.assertEqual(h._view_entries[0]["msg"], "plain info line")
        h._append_log("overflow WARNING flag")      # severity autodetected? no
        self.assertEqual(h.log_table.rowCount(), 1,
                         "a live append that does not match the filter "
                         "polluted the filtered view")
        self.assertEqual(len(h._view_entries), 1)

    def test_details_panel_maps_the_visible_rows(self):
        h = self._harness()
        h.log_details = QTextEdit()
        h.log_severity_combo.setCurrentText("INFO")
        h._append_log("matching info row")
        h._append_log("omitted warning line")
        h._append_log("second info row")
        self.assertEqual(h.log_table.rowCount(), 2)
        h.log_table.selectRow(1)
        h._show_log_details()
        self.assertIn("second info row", h.log_details.toPlainText(),
                      "the details panel described the wrong entry: the row "
                      "was mapped into the unfiltered buffer")

    def test_clear_resets_both_buffer_and_view(self):
        h = self._harness()
        h._append_log("one")
        h._append_log("two")
        h._clear_log()
        self.assertEqual(h.log_table.rowCount(), 0)
        self.assertEqual(len(self._view_len(h)), 0)

    def _view_len(self, h):
        return h._view_entries

    def test_shell_replays_rebuild_on_every_show(self):
        """The tab builder wires the rebuild to the shell's showEvent."""
        from unittest.mock import Mock, patch

        from gui.builders.tab_builders import TabBuildersMixin

        class Harness(TabBuildersMixin):
            def __getattr__(self, name):
                m = Mock(name=name)
                setattr(self, name, m)
                return m

        h = Harness()
        h._replay_log_buffer = Mock()
        w = h.create_logs_tab()
        self.assertTrue(hasattr(w, "showEvent"), "the log tab shell must be "
                        "the custom widget with the show hook")
        h._replay_log_buffer.reset_mock()  # the build-time call doesn't count
        w.show()
        for _ in range(50):
            if h._replay_log_buffer.called:
                break
            _qapp().processEvents()
        self.assertTrue(h._replay_log_buffer.called,
                        "the shell never triggered a rebuild after becoming "
                        "visible -- the Live Logs tab opens empty again")

        # hide -> show again: every open must rebuild (deferred lines appear)
        h._replay_log_buffer.reset_mock()
        w.hide()
        _qapp().processEvents()
        w.show()
        for _ in range(50):
            if h._replay_log_buffer.called:
                break
            _qapp().processEvents()
        self.assertTrue(h._replay_log_buffer.called,
                        "re-opening the Live Logs tab did not rebuild the view")


if __name__ == "__main__":
    unittest.main()
