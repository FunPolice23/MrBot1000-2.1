"""Phase 3: Dialogue speaker/reply selectors reflect every enabled device."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Stub:
    model = "stub-model"


class TestSpeakerSelectors(unittest.TestCase):
    def _tab(self):
        from gui.tabs.dialogue_tab import DialogueTab
        tab = DialogueTab(small_brain=_Stub(), big_brain=_Stub())
        self.addCleanup(setattr, tab, "_closing", True)
        return tab

    def test_speaker_combo_has_human_plus_every_brain(self):
        tab = self._tab()
        self.assertEqual(tab.speaker_combo.count(), 1 + len(tab._speakers))
        self.assertEqual(tab.speaker_combo.itemData(0), "Human")

    def test_reply_combo_has_every_brain(self):
        tab = self._tab()
        self.assertEqual(tab.reply_combo.count(), len(tab._speakers))

    def test_combo_items_carry_device_labels(self):
        tab = self._tab()
        texts = [tab.speaker_combo.itemText(i)
                 for i in range(tab.speaker_combo.count())]
        # At least one brain item shows a device (GeForce / CPU).
        brain_texts = texts[1:]
        self.assertTrue(any("GeForce" in t or "CPU" in t for t in brain_texts))

    def test_combo_name_resolution_exact(self):
        tab = self._tab()
        # Selecting a brain resolves to its exact name via UserRole.
        tab.speaker_combo.setCurrentIndex(1)
        self.assertEqual(tab._combo_speaker_name(tab.speaker_combo),
                         tab._speakers[0].name)

    def test_header_lists_all_speakers(self):
        tab = self._tab()
        header = tab.dialogue_header.text()
        for spk in tab._speakers:
            self.assertIn(spk.name, header)

    def test_next_speaker_round_robin(self):
        tab = self._tab()
        names = [s.name for s in tab._speakers]
        if len(names) >= 2:
            self.assertEqual(tab._next_speaker_after(names[0]), names[1])
            # Wraps around.
            self.assertEqual(tab._next_speaker_after(names[-1]), names[0])


if __name__ == "__main__":
    unittest.main()
