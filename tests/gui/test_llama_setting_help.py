"""Phase G3 — advanced llama.cpp settings have mouse-hover help (ARCH-ENG-094).

Every advanced control carries a non-empty tooltip sourced from the central
llama_setting_help catalog, and the catalog covers all the documented keys.
"""
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestHelpCatalog(unittest.TestCase):
    def test_catalog_covers_all_keys(self):
        from agents.knowledge.llama_setting_help import LLAMA_SETTING_HELP
        for key in ("ctx", "gpu_layers", "threads", "batch", "kv_cache",
                    "split_mode", "temperature", "mtp", "spec_draft_n_max",
                    "flash_attn", "cache_reuse", "context_shift", "mmproj"):
            self.assertIn(key, LLAMA_SETTING_HELP)
            self.assertTrue(LLAMA_SETTING_HELP[key].strip(), key)

    def test_tooltip_unknown_returns_default(self):
        from agents.knowledge.llama_setting_help import tooltip
        self.assertEqual(tooltip("nope", "fallback"), "fallback")
        self.assertEqual(tooltip("nope"), "")


class TestSettingsRowTooltips(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def test_every_control_has_tooltip(self):
        from gui.widgets.brain_settings_row import BrainSettingsRow
        row = BrainSettingsRow(0, "big", "Test GPU")
        controls = {
            "ctx": row.ctx_spin,
            "gpu_layers": row.gpu_layers_spin,
            "threads": row.threads_spin,
            "batch": row.batch_spin,
            "kv_cache": row.kv_combo,
            "split_mode": row.split_combo,
            "temperature": row.temp_spin,
        }
        for name, w in controls.items():
            self.assertTrue(w.toolTip().strip(),
                            f"{name} control has no tooltip")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
