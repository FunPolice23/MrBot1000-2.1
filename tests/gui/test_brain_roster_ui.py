"""Phase 4 roster UI: count spinners add/remove rows; roster round-trips.

Headless (offscreen). Uses an isolated settings root so no test touches the
operator's real config.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from agents.runtime.brain_roster import BrainRoster, BrainSlot  # noqa: E402
from gui.widgets.brain_roster_panel import BrainRosterPanel, _SlotRow  # noqa: E402

_DEVICES = [
    SimpleNamespace(id="gpu0", label=lambda: "RTX 5060 Ti (16 GB)", memory_gb=16.0),
    SimpleNamespace(id="gpu1", label=lambda: "GTX 1660 Super (6 GB)", memory_gb=6.0),
]
_MODELS = ["D:/llama.cpp/models/a.gguf", "D:/llama.cpp/models/b.gguf"]


class TestBrainRosterPanel(unittest.TestCase):
    def _panel(self, root):
        return BrainRosterPanel(devices=_DEVICES, models=_MODELS, root=root)

    def test_count_spinner_adds_and_removes_rows(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            panel = self._panel(root)
            big = panel._tier_widgets["big"]
            self.assertEqual(big["rows"].count(), 1)
            big["spin"].setValue(3)
            self.assertEqual(big["rows"].count(), 3, "1->3 must add two rows")
            big["spin"].setValue(1)
            self.assertEqual(big["rows"].count(), 1, "3->1 must remove them")

    def test_small_tier_independent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            panel = self._panel(root)
            small = panel._tier_widgets["small"]
            small["spin"].setValue(2)
            self.assertEqual(small["rows"].count(), 2)
            self.assertEqual(panel._tier_widgets["big"]["rows"].count(), 1,
                             "small count must not change big rows")

    def test_slot_row_captures_fields(self):
        row = _SlotRow(0, "big", _DEVICES, _MODELS,
                       BrainSlot(tier="big", provider="llamacpp", model="x.gguf",
                                 device_id="gpu0", enabled=True))
        row.provider_combo.setCurrentText("openai")
        row.model_combo.setCurrentText("gpt-4o-mini")
        row.device_combo.setCurrentIndex(row.device_combo.findData("gpu1"))
        row.enable_cb.setChecked(False)
        slot = row.to_slot()
        self.assertEqual(slot.provider, "openai")
        self.assertEqual(slot.model, "gpt-4o-mini")
        self.assertEqual(slot.device_id, "gpu1")
        self.assertFalse(slot.enabled)

    def test_roster_round_trips(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            panel = self._panel(root)
            big = panel._tier_widgets["big"]
            big["spin"].setValue(2)
            row0 = big["rows"].itemAt(0).widget()
            row0.provider_combo.setCurrentText("openai")
            row0.model_combo.setCurrentText("gpt-4o-mini")
            # Edits are debounced (fsync-storm guard); flush — the same path
            # the save handlers use via save_roster_from — before reading back.
            panel._flush_save()
            loaded = BrainRoster.load(root=root)
            self.assertEqual(len(loaded.big), 2)
            self.assertEqual(loaded.big[0].provider, "openai")
            self.assertEqual(loaded.big[0].model, "gpt-4o-mini")


    def test_edits_are_debounced_not_saved_per_keystroke(self):
        # P1 fsync-storm guard: a single edit is collected but NOT persisted
        # until flush (the save is coalesced), so a keystroke in the editable
        # model field cannot storm settings.json with tmp+fsync+os.replace.
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            panel = self._panel(root)
            row0 = panel._tier_widgets["big"]["rows"].itemAt(0).widget()
            row0.provider_combo.setCurrentText("openai")
            loaded = BrainRoster.load(root=root)
            self.assertNotEqual(
                loaded.big[0].provider, "openai",
                "a single edit must not immediately persist (fsync-storm guard)")
            panel._flush_save()
            loaded2 = BrainRoster.load(root=root)
            self.assertEqual(loaded2.big[0].provider, "openai")


if __name__ == "__main__":
    unittest.main()


def test_provider_combo_offers_only_runtime_supported_providers():
    """P1: the dropdown must not offer a provider the runtime coerces to
    llamacpp (e.g. deepseek/mistral would point the brain at a dead local
    server with no error)."""
    from agents.runtime.dual_brain import SUPPORTED_PROVIDERS
    from gui.widgets.brain_roster_panel import _CLOUD_SAMPLES
    for p in _CLOUD_SAMPLES:
        assert p in SUPPORTED_PROVIDERS, (
            f"panel offers {p!r} which the runtime coerces to llamacpp")
    assert "deepseek" not in _CLOUD_SAMPLES
    assert "mistral" not in _CLOUD_SAMPLES
    # At least the runtime-supported cloud vendors are offered.
    assert set(_CLOUD_SAMPLES), "panel offered no cloud providers"
