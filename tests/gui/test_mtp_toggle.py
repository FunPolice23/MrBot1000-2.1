"""Phase G2 — Provider Control MTP toggle greys out for unsupported models (ARCH-ENG-093).

The MTP checkbox must be enabled only when the selected model carries an MTP
head, and greyed (disabled, unchecked, reason tooltip) otherwise.
"""
import os
import sys
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_MTP_MODEL = r"D:/llama.cpp/models/Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf"
_NO_MTP_MODEL = r"D:/llama.cpp/models/GLM-4.7-Flash-REAP-23B-A3B-UD-Q3_K_XL.gguf"


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestMtpToggle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def _row(self):
        from gui.widgets.brain_control_row import BrainControlRow
        return BrainControlRow(0, "big", "Test GPU")

    def test_capable_model_enables_checkbox(self):
        if not os.path.exists(_MTP_MODEL):
            self.skipTest("MTP model not present")
        row = self._row()
        row.set_models([_MTP_MODEL], selected=_MTP_MODEL)
        self.assertTrue(row.mtp_check.isEnabled())
        row.mtp_check.setChecked(True)
        self.assertTrue(row.mtp_enabled())

    def test_noncapable_model_greys_checkbox(self):
        if not os.path.exists(_NO_MTP_MODEL):
            self.skipTest("GLM model not present")
        row = self._row()
        row.set_models([_NO_MTP_MODEL], selected=_NO_MTP_MODEL)
        self.assertFalse(row.mtp_check.isEnabled())
        self.assertFalse(row.mtp_check.isChecked())
        self.assertIn("no MTP head", row.mtp_check.toolTip())

    def test_no_model_greys_checkbox(self):
        row = self._row()
        row.set_models([], selected="")
        self.assertFalse(row.mtp_check.isEnabled())

    def test_switching_model_reevaluates(self):
        if not (os.path.exists(_MTP_MODEL) and os.path.exists(_NO_MTP_MODEL)):
            self.skipTest("models not present")
        row = self._row()
        row.set_models([_MTP_MODEL, _NO_MTP_MODEL], selected=_MTP_MODEL)
        self.assertTrue(row.mtp_check.isEnabled())
        # Switch to the non-capable model -> greyed.
        row.set_model(_NO_MTP_MODEL)
        self.assertFalse(row.mtp_check.isEnabled())

    def test_mtp_changed_signal_emits(self):
        if not os.path.exists(_MTP_MODEL):
            self.skipTest("MTP model not present")
        row = self._row()
        got = []
        row.mtp_changed.connect(lambda slot, en: got.append((slot, en)))
        row.set_models([_MTP_MODEL], selected=_MTP_MODEL)
        row.mtp_check.setChecked(True)
        self.assertIn((0, True), got)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
