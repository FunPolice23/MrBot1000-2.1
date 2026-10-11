"""Tests for the reusable BrainSettingsRow widget (N-brain per-device settings)."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from gui.widgets.brain_settings_row import BrainSettingsRow  # noqa: E402


class TestBrainSettingsRow(unittest.TestCase):
    def _row(self, slot=0, role="big", is_cpu=False):
        return BrainSettingsRow(slot=slot, role=role, device_label="Card X",
                                is_cpu=is_cpu)

    def test_renders_all_controls(self):
        row = self._row()
        for attr in ("ctx_spin", "gpu_layers_spin", "threads_spin",
                     "batch_spin", "kv_combo", "split_combo", "temp_spin"):
            self.assertTrue(hasattr(row, attr), f"missing {attr}")

    def test_changed_signal_carries_slot(self):
        row = self._row(slot=2, role="small")
        seen = []
        row.changed.connect(lambda s: seen.append(s))
        row.ctx_spin.setValue(16384)
        self.assertIn(2, seen)

    def test_cpu_row_locks_gpu_layers_to_zero_disabled(self):
        row = self._row(slot=2, role="big", is_cpu=True)
        self.assertEqual(row.gpu_layers_spin.value(), 0)
        self.assertFalse(row.gpu_layers_spin.isEnabled())

    def test_gpu_row_allows_auto_gpu_layers(self):
        row = self._row(slot=0, role="big", is_cpu=False)
        self.assertTrue(row.gpu_layers_spin.isEnabled())
        self.assertEqual(row.gpu_layers_spin.minimum(), -1)  # Auto

    def test_bind_from_config(self):
        from agents.runtime.dual_brain import BrainConfig, BrainRole
        cfg = BrainConfig(role=BrainRole.BIG, context=40000, threads=12,
                          batch=4096, kv_cache="q8_0", split_mode="layer")
        row = self._row()
        row.bind(cfg)
        self.assertEqual(row.ctx_spin.value(), 40000)
        self.assertEqual(row.threads_spin.value(), 12)
        self.assertEqual(row.batch_spin.value(), 4096)
        self.assertEqual(row.kv_combo.currentText(), "q8_0")
        self.assertEqual(row.split_combo.currentText(), "layer")

    def test_apply_to_config(self):
        from agents.runtime.dual_brain import BrainConfig, BrainRole
        cfg = BrainConfig(role=BrainRole.BIG)
        row = self._row()
        row.ctx_spin.setValue(8192)
        row.threads_spin.setValue(6)
        row.batch_spin.setValue(1024)
        row.kv_combo.setCurrentText("q4_0")
        row.apply_to(cfg)
        self.assertEqual(cfg.context, 8192)
        self.assertEqual(cfg.threads, 6)
        self.assertEqual(cfg.batch, 1024)
        self.assertEqual(cfg.kv_cache, "q4_0")

    def test_apply_to_cpu_config_forces_gpu_layers_zero(self):
        from agents.runtime.dual_brain import BrainConfig, BrainRole
        cfg = BrainConfig(role=BrainRole.BIG, gpu_layers=None)
        row = self._row(is_cpu=True)
        row.apply_to(cfg)
        self.assertEqual(cfg.gpu_layers, 0)

    def test_values_dict(self):
        row = self._row()
        v = row.values()
        self.assertIn("context", v)
        self.assertIn("gpu_layers", v)
        self.assertIn("kv_cache", v)
        # GPU row at Auto (-1) reports gpu_layers None (omit the flag).
        self.assertIsNone(v["gpu_layers"])

    def test_values_dict_cpu_forces_zero(self):
        row = self._row(is_cpu=True)
        self.assertEqual(row.values()["gpu_layers"], 0)

    def test_bind_is_resilient_to_bad_config(self):
        row = self._row()
        row.bind(object())  # must not raise


if __name__ == "__main__":
    unittest.main()
