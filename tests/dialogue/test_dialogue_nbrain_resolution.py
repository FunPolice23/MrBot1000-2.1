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
        tab.big_brain = _FakeBrain("qwen3.5-32b-instruct")
        tab.small_brain = _FakeBrain("qwen2.5-7b-instruct")
        # Pin VRAM offline so tests never probe nvidia-smi; values chosen so
        # the big tier is uncapped and the small tier matches its card.
        tab._vram_cache = {True: 15.9, False: 16.0}
        return tab

    def _speakers(self):
        from agents.cognition.speaker_registry import Speaker
        return [
            Speaker(slot=0, key="big_brain", name="Edward Hurst", tier="big",
                    brain=_FakeBrain("qwen3.5-32b-instruct"), is_primary_big=True),
            Speaker(slot=1, key="small_brain", name="Jacob Stanley", tier="small",
                    brain=_FakeBrain("qwen2.5-7b-instruct"), is_primary_small=True),
            Speaker(slot=2, key="brain_slot2", name="Rowan Vale", tier="big",
                    brain=None),
            Speaker(slot=3, key="brain_slot3", name="Pip Marlowe", tier="small",
                    brain=None),
        ]

    def test_brain_for_primary_names(self):
        tab = self._make_tab(self._speakers())
        self.assertEqual(tab._brain_for("Edward Hurst").model,
                         "qwen3.5-32b-instruct")
        self.assertEqual(tab._brain_for("Jacob Stanley").model,
                         "qwen2.5-7b-instruct")

    def test_tier_for_primary_names(self):
        tab = self._make_tab(self._speakers())
        self.assertEqual(tab._tier_for_speaker("Edward Hurst"), "full")
        self.assertEqual(tab._tier_for_speaker("Jacob Stanley"), "compact")

    def test_brain_for_third_speaker_resolves_lazily(self):
        # ARCH-ENG-316: the tier follows the model size now, so stub the lazy
        # adapter classes with deterministic sizes instead of the live env.
        import agents.brains.big_brain as bb_mod
        import agents.brains.small_brain as sb_mod

        class _Big:
            def __init__(self, config=None):
                self.model = "qwen3.5-32b-instruct"

        class _Small:
            def __init__(self, config=None):
                self.model = "qwen2.5-7b-instruct"

        orig_big, orig_small = bb_mod.BigBrainAdapter, sb_mod.SmallBrainAdapter
        bb_mod.BigBrainAdapter = _Big
        sb_mod.SmallBrainAdapter = _Small
        try:
            tab = self._make_tab(self._speakers())
            # Slot 2 (big) has no adapter yet -> _brain_for builds an adapter.
            brain = tab._brain_for("Rowan Vale")
            self.assertIsNotNone(brain)
            # Tier is big (full size) for the extra big brain.
            self.assertEqual(tab._tier_for_speaker("Rowan Vale"), "full")
            # Slot 3 (small) -> compact tier.
            self.assertEqual(tab._tier_for_speaker("Pip Marlowe"), "compact")
        finally:
            bb_mod.BigBrainAdapter = orig_big
            sb_mod.SmallBrainAdapter = orig_small

    def test_brain_for_unknown_falls_back_to_legacy(self):
        tab = self._make_tab(self._speakers())
        # An unknown name falls back to the small adapter (legacy default).
        self.assertEqual(tab._brain_for("Nobody").model, "qwen2.5-7b-instruct")

    def test_speaker_for_returns_none_when_roster_absent(self):
        from gui.tabs.dialogue_tab import DialogueTab
        tab = DialogueTab.__new__(DialogueTab)  # no _speakers attr
        tab.big_brain = _FakeBrain("qwen3.5-32b-instruct")
        tab.small_brain = _FakeBrain("qwen2.5-7b-instruct")
        self.assertIsNone(tab._speaker_for("Edward Hurst"))
        # _brain_for still resolves via the legacy fallback.
        self.assertEqual(tab._brain_for("Edward Hurst").model,
                         "qwen3.5-32b-instruct")

    def test_runtime_key_for_third_speaker(self):
        tab = self._make_tab(self._speakers())
        spk = tab._speaker_for("Rowan Vale")
        self.assertEqual(spk.key, "brain_slot2")

    def test_brain_for_extra_slot_passes_brain_config(self):
        # Phase 5: an extra-slot Speaker with a per-slot BrainConfig must seed
        # the adapter with it (roster-driven provider/model/endpoint), not the
        # legacy env path. Capture the constructor arg via a stub.
        import agents.brains.big_brain as bb_mod
        from agents.cognition.speaker_registry import Speaker
        sentinel_cfg = object()
        spk = Speaker(slot=2, key="brain_slot2", name="Rowan Vale", tier="big",
                      brain=None, brain_config=sentinel_cfg)
        tab = self._make_tab([spk])
        captured = {}

        class _Capture:
            def __init__(self, config=None):
                captured["config"] = config
                self.model = "captured"

        orig = bb_mod.BigBrainAdapter
        bb_mod.BigBrainAdapter = _Capture
        try:
            brain = tab._brain_for("Rowan Vale")
        finally:
            bb_mod.BigBrainAdapter = orig
        self.assertIs(captured.get("config"), sentinel_cfg)
        self.assertEqual(brain.model, "captured")

    def test_brain_for_extra_slot_small_passes_brain_config(self):
        # Same for a small-tier extra slot (SmallBrainAdapter).
        import agents.brains.small_brain as sb_mod
        from agents.cognition.speaker_registry import Speaker
        sentinel_cfg = object()
        spk = Speaker(slot=3, key="brain_slot3", name="Pip Marlowe", tier="small",
                      brain=None, brain_config=sentinel_cfg)
        tab = self._make_tab([spk])
        captured = {}

        class _Capture:
            def __init__(self, config=None):
                captured["config"] = config
                self.model = "captured"

        orig = sb_mod.SmallBrainAdapter
        sb_mod.SmallBrainAdapter = _Capture
        try:
            brain = tab._brain_for("Pip Marlowe")
        finally:
            sb_mod.SmallBrainAdapter = orig
        self.assertIs(captured.get("config"), sentinel_cfg)
        self.assertEqual(brain.model, "captured")


if __name__ == "__main__":
    unittest.main()
