"""Tests for the N-brain Provider Control panel rendering (Phase 3)."""

import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from gui.widgets.dual_brain_control import DualBrainControl  # noqa: E402
from agents.runtime.dual_brain import DualBrainRuntime  # noqa: E402
from agents.providers.provider_manager import ProviderManager  # noqa: E402


def _wait_detected(app, timeout=12):
    deadline = time.time() + timeout
    while not ProviderManager.instance()._detected and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)


class TestProviderControlNRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def _widget(self):
        w = DualBrainControl(runtime=DualBrainRuntime.from_env())
        self.app.processEvents()
        _wait_detected(self.app)
        w._apply_runtime()
        self.app.processEvents()
        return w

    def test_renders_one_row_per_slot(self):
        w = self._widget()
        try:
            n_slots = len(w.runtime.slots())
            self.assertEqual(len(w._provider_rows), n_slots)
            self.assertGreaterEqual(len(w._provider_rows), 2)
        finally:
            w._closing = True

    def test_slot0_is_big_slot1_is_small(self):
        w = self._widget()
        try:
            self.assertEqual(w._provider_rows[0].role, "big")
            self.assertEqual(w._provider_rows[1].role, "small")
        finally:
            w._closing = True

    def test_legacy_aliases_point_at_rows(self):
        w = self._widget()
        try:
            self.assertIs(w.sb_start_btn, w._provider_rows[1].start_btn)
            self.assertIs(w.bb_start_btn, w._provider_rows[0].start_btn)
            self.assertIs(w.sb_status, w._provider_rows[1].status)
            self.assertIs(w.bb_status, w._provider_rows[0].status)
        finally:
            w._closing = True

    def test_row_headers_show_detected_device(self):
        w = self._widget()
        try:
            big_header = w._provider_rows[0].header.text()
            small_header = w._provider_rows[1].header.text()
            self.assertIn("Big Brain", big_header)
            self.assertIn("Small Brain", small_header)
        finally:
            w._closing = True

    def test_refresh_does_not_rebuild_when_count_unchanged(self):
        w = self._widget()
        try:
            before = w._provider_rows
            w._apply_runtime()
            self.app.processEvents()
            self.assertIs(w._provider_rows, before)
        finally:
            w._closing = True

    def test_row_start_signal_routes_to_big_handler(self):
        w = self._widget()
        try:
            called = []
            orig = w._on_start_big_brain
            w._on_start_big_brain = lambda *a: called.append("big")
            w._provider_rows[0].start_btn.click()
            self.assertEqual(called, ["big"])
            w._on_start_big_brain = orig
        finally:
            w._closing = True

    def test_row_start_signal_routes_to_small_handler(self):
        w = self._widget()
        try:
            called = []
            orig = w._on_start_small_brain
            w._on_start_small_brain = lambda *a: called.append("small")
            w._provider_rows[1].start_btn.click()
            self.assertEqual(called, ["small"])
            w._on_start_small_brain = orig
        finally:
            w._closing = True

    def test_detected_brains_summary_lists_all_slots(self):
        w = self._widget()
        try:
            # The per-device settings section renders one BrainSettingsRow per slot.
            rows = getattr(w, "_settings_rows", [])
            self.assertEqual(len(rows), len(w.runtime.slots()))
            self.assertGreaterEqual(len(rows), 2)
            # The two role brains (big + small) must both be represented.
            roles = {r.role for r in rows}
            self.assertIn("big", roles)
            self.assertIn("small", roles)
        finally:
            w._closing = True

    def test_detected_brains_summary_shows_ctx_control(self):
        w = self._widget()
        try:
            rows = getattr(w, "_settings_rows", [])
            self.assertGreaterEqual(len(rows), 1)
            # Every settings row exposes an editable context spin.
            for r in rows:
                self.assertTrue(hasattr(r, "ctx_spin"))
                self.assertGreaterEqual(r.ctx_spin.value(), 2048)
        finally:
            w._closing = True


if __name__ == "__main__":
    unittest.main()
