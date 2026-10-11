"""Tests for the reusable BrainControlRow widget (N-brain Phase 2)."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from gui.widgets.brain_control_row import BrainControlRow  # noqa: E402


class TestBrainControlRow(unittest.TestCase):
    def _row(self, slot=0, role="big", label=""):
        return BrainControlRow(slot=slot, role=role, device_label=label)

    def test_renders_role_and_slot(self):
        row = self._row(slot=2, role="small")
        self.assertEqual(row.slot, 2)
        self.assertEqual(row.role, "small")
        self.assertIn("Small Brain", row.header.text())

    def test_start_signal_carries_slot(self):
        row = self._row(slot=3, role="big")
        seen = []
        row.start_clicked.connect(lambda s: seen.append(s))
        row.start_btn.click()
        self.assertEqual(seen, [3])

    def test_stop_signal_carries_slot(self):
        row = self._row(slot=1, role="small")
        row.set_running(True)  # stop only enabled when running
        seen = []
        row.stop_clicked.connect(lambda s: seen.append(s))
        row.stop_btn.click()
        self.assertEqual(seen, [1])

    def test_device_label_updates_header(self):
        row = self._row(slot=0, role="big")
        row.set_device_label("NVIDIA GeForce RTX 5060 Ti")
        self.assertIn("RTX 5060 Ti", row.header.text())
        self.assertIn("Big Brain", row.header.text())

    def test_set_running_toggles_buttons(self):
        row = self._row()
        # Fresh row: start enabled, stop disabled.
        self.assertTrue(row.start_btn.isEnabled())
        self.assertFalse(row.stop_btn.isEnabled())
        row.set_running(True)
        self.assertFalse(row.start_btn.isEnabled())
        self.assertTrue(row.stop_btn.isEnabled())
        row.set_running(False)
        self.assertTrue(row.start_btn.isEnabled())
        self.assertFalse(row.stop_btn.isEnabled())

    def test_set_model_and_status(self):
        row = self._row()
        row.set_models(["/models/qwen3-27b.gguf", "/models/other.gguf"])
        row.set_model("/models/qwen3-27b.gguf")
        self.assertIn("qwen3-27b", row.model_combo.currentText())
        self.assertEqual(row.current_model(), "/models/qwen3-27b.gguf")
        row.set_status("● Running", "#4caf50")
        self.assertIn("Running", row.status.text())

    def test_set_models_fills_dropdown_and_preselects(self):
        row = self._row()
        row.set_models(["/a.gguf", "/b.gguf"], selected="/b.gguf")
        self.assertEqual(row.model_combo.count(), 3)  # "Select a model..." + 2
        self.assertEqual(row.current_model(), "/b.gguf")

    def test_model_changed_signal_carries_slot_and_path(self):
        row = self._row(slot=2, role="big")
        row.set_models(["/a.gguf", "/b.gguf"])
        seen = []
        row.model_changed.connect(lambda s, p: seen.append((s, p)))
        row.model_combo.setCurrentIndex(2)  # pick /b.gguf
        self.assertEqual(seen, [(2, "/b.gguf")])

    def test_bind_from_config(self):
        from agents.runtime.dual_brain import BrainConfig, BrainRole
        cfg = BrainConfig(role=BrainRole.BIG, gpu_label="RTX 4090 (24 GB)",
                          model="my-model")
        row = self._row(slot=0, role="small")
        row.bind(cfg)
        self.assertEqual(row.role, "big")
        self.assertIn("RTX 4090", row.header.text())
        # bind selects the config's model in the dropdown when present.
        row.set_models(["/models/my-model"])
        row.bind(cfg)
        self.assertEqual(row.current_model(), "/models/my-model")

    def test_bind_is_resilient_to_bad_config(self):
        row = self._row()
        row.bind(object())  # must not raise
        self.assertEqual(row.slot, 0)


if __name__ == "__main__":
    unittest.main()
