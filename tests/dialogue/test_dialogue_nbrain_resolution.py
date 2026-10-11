"""Phase 2: DialogueTab resolves brains/tiers via the speaker registry.

Verifies the N-brain lookup helpers work and reduce to the legacy big/small
behavior for the 2-brain case, and that a 3rd speaker resolves correctly.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeBrain:
    def __init__(self, name):
        self.model = name


class TestDialogueSpeakerResolution(unittest.TestCase):
    """Build a DialogueTab-like object and exercise _brain_for/_tier_for_speaker
    without full __init__ (which needs Qt + adapters)."""

    def _make_tab(self, speakers):
        from gui.tabs.dialogue_tab import DialogueTab
        tab = DialogueTab.__new__(DialogueTab)
        tab._speakers = speakers
        tab.big_brain = _FakeBrain("big-model")
        tab.small_brain = _FakeBrain("small-model")
        return tab

    def _speakers(self):
        from agents.cognition.speaker_registry import Speaker
        return [
            Speaker(slot=0, key="big_brain", name="Edward Hurst", tier="big",
                    brain=_FakeBrain("edward-model"), is_primary_big=True),
            Speaker(slot=1, key="small_brain", name="Jacob Stanley", tier="small",
                    brain=_FakeBrain("jacob-model"), is_primary_small=True),
            Speaker(slot=2, key="brain_slot2", name="Rowan Vale", tier="big",
                    brain=None),
            Speaker(slot=3, key="brain_slot3", name="Pip Marlowe", tier="small",
                    brain=None),
        ]

    def test_brain_for_primary_names(self):
        tab = self._make_tab(self._speakers())
        self.assertEqual(tab._brain_for("Edward Hurst").model, "edward-model")
        self.assertEqual(tab._brain_for("Jacob Stanley").model, "jacob-model")

    def test_tier_for_primary_names(self):
        tab = self._make_tab(self._speakers())
        self.assertEqual(tab._tier_for_speaker("Edward Hurst"), "full")
        self.assertEqual(tab._tier_for_speaker("Jacob Stanley"), "compact")

    def test_brain_for_third_speaker_resolves_lazily(self):
        tab = self._make_tab(self._speakers())
        # Slot 2 (big) has no adapter yet -> _brain_for builds a BigBrainAdapter.
        brain = tab._brain_for("Rowan Vale")
        self.assertIsNotNone(brain)
        # Tier is big (full) for the extra big brain.
        self.assertEqual(tab._tier_for_speaker("Rowan Vale"), "full")
        # Slot 3 (small) -> small tier.
        self.assertEqual(tab._tier_for_speaker("Pip Marlowe"), "compact")

    def test_brain_for_unknown_falls_back_to_legacy(self):
        tab = self._make_tab(self._speakers())
        # An unknown name falls back to the small adapter (legacy default).
        self.assertEqual(tab._brain_for("Nobody").model, "small-model")

    def test_speaker_for_returns_none_when_roster_absent(self):
        from gui.tabs.dialogue_tab import DialogueTab
        tab = DialogueTab.__new__(DialogueTab)  # no _speakers attr
        tab.big_brain = _FakeBrain("big-model")
        tab.small_brain = _FakeBrain("small-model")
        self.assertIsNone(tab._speaker_for("Edward Hurst"))
        # _brain_for still resolves via the legacy fallback.
        self.assertEqual(tab._brain_for("Edward Hurst").model, "big-model")

    def test_runtime_key_for_third_speaker(self):
        tab = self._make_tab(self._speakers())
        spk = tab._speaker_for("Rowan Vale")
        self.assertEqual(spk.key, "brain_slot2")


if __name__ == "__main__":
    unittest.main()
