"""Phase 5: team brief + shared-skills persona resolution + generalized LIFECYCLE."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeBrain:
    def __init__(self, name):
        self.model = name


def _speakers():
    from agents.cognition.speaker_registry import Speaker
    return [
        Speaker(slot=0, key="big_brain", name="Edward Hurst", tier="big",
                brain=_FakeBrain("e"), device_label="NVIDIA GeForce RTX 5060 Ti",
                is_primary_big=True),
        Speaker(slot=1, key="small_brain", name="Jacob Stanley", tier="small",
                brain=_FakeBrain("j"), device_label="NVIDIA GeForce GTX 1660 SUPER",
                is_primary_small=True),
        Speaker(slot=2, key="brain_slot2", name="Rowan Vale", tier="big",
                brain=None, device_label="CPU / System RAM"),
        Speaker(slot=3, key="brain_slot3", name="Pip Marlowe", tier="small",
                brain=None, device_label="CPU / System RAM"),
    ]


class TestTeamBrief(unittest.TestCase):
    def test_empty_for_single_brain(self):
        from agents.cognition.speaker_registry import build_team_brief
        spks = _speakers()
        self.assertEqual(build_team_brief(spks[:1], spks[0], "goal"), "")
        self.assertEqual(build_team_brief(spks, None, "goal"), "")

    def test_brief_lists_peers_not_self(self):
        from agents.cognition.speaker_registry import build_team_brief
        spks = _speakers()
        brief = build_team_brief(spks, spks[0], "earn money legally")
        # Edward's brief lists the others, not Edward himself.
        self.assertIn("Jacob Stanley", brief)
        self.assertIn("Rowan Vale", brief)
        self.assertIn("Pip Marlowe", brief)
        self.assertNotIn("Edward Hurst —", brief)
        # Tier + device tags present (for the peers).
        self.assertIn("big (earning agent)", brief)
        self.assertIn("small (helper/support)", brief)
        self.assertIn("NVIDIA GeForce GTX 1660 SUPER", brief)  # Jacob's device
        # Goal + peer-deliberation rule.
        self.assertIn("Shared goal: earn money legally", brief)
        self.assertIn("Peer deliberation", brief)
        self.assertIn("add YOUR OWN", brief)

    def test_brief_reduces_to_two_brains(self):
        from agents.cognition.speaker_registry import build_team_brief
        spks = _speakers()
        brief = build_team_brief(spks[:2], spks[0], "goal")
        # Edward sees only Jacob as a peer.
        self.assertIn("Jacob Stanley", brief)
        self.assertNotIn("Rowan Vale", brief)

    def test_a2_best_to_worst_deliberation_instruction(self):
        """A2: the peer council is told to name the full ranked list, argue
        best->worst, and converge on ONE action — not pick the first row."""
        from agents.cognition.speaker_registry import build_team_brief
        spks = _speakers()
        brief = build_team_brief(spks[:2], spks[0], "earn money")
        self.assertIn("do NOT just pick the first row", brief)
        self.assertIn("name the full ranked list", brief)
        self.assertIn("best->worst", brief)
        self.assertIn("converge on ONE concrete next action", brief)

    def test_a2_absent_for_single_brain_back_compat(self):
        """Back-compat: a single brain gets no team brief (and so no A2 text)."""
        from agents.cognition.speaker_registry import build_team_brief
        spks = _speakers()
        self.assertEqual(build_team_brief(spks[:1], spks[0], "goal"), "")


class TestSharedSkillsPersona(unittest.TestCase):
    def test_big_tier_uses_driver_skillset_with_own_name(self):
        from agents.cognition.personas import DRIVER
        # An extra big brain (Rowan Vale) shares Edward's earning-agent skillset
        # but speaks as its own name via name_override.
        prompt = DRIVER.build_system_prompt(
            goal="earn", name_override="Rowan Vale")
        identity = prompt.split("\n# MEMORY")[0]
        self.assertIn("You are Rowan Vale", identity)
        self.assertNotIn("You are Edward Hurst", identity)
        # Shared skillset markers (earning discipline) still present.
        self.assertIn("earning opportunities", prompt)

    def test_small_tier_uses_navigator_skillset_with_own_name(self):
        from agents.cognition.personas import NAVIGATOR
        prompt = NAVIGATOR.build_system_prompt(
            goal="earn", name_override="Pip Marlowe")
        # The IDENTITY block speaks as the override name, not the role default.
        identity = prompt.split("\n# MEMORY")[0]  # identity is before memory
        self.assertIn("You are Pip Marlowe", identity)
        self.assertNotIn("You are Jacob Stanley", identity)

    def test_name_override_empty_keeps_current_name(self):
        from agents.cognition.personas import DRIVER
        prompt = DRIVER.build_system_prompt(goal="earn")
        # No override -> uses the role default / env name.
        self.assertIn(DRIVER.current_name, prompt)

    def test_team_brief_injected_into_full_prompt(self):
        from agents.cognition.personas import DRIVER
        from agents.cognition.speaker_registry import build_team_brief
        spks = _speakers()
        brief = build_team_brief(spks, spks[0], "earn")
        prompt = DRIVER.build_system_prompt(
            goal="earn", team_brief=brief, name_override="Edward Hurst")
        self.assertIn("# TEAM (peer council", prompt)
        self.assertIn("Peer deliberation", prompt)

    def test_dialogue_resolves_extra_big_brain_to_driver_skillset(self):
        from gui.tabs.dialogue_tab import DialogueTab
        tab = DialogueTab.__new__(DialogueTab)
        tab._speakers = _speakers()
        tab.big_brain = _FakeBrain("big-model")
        tab.small_brain = _FakeBrain("small-model")
        # _tier_for_speaker: Rowan (big) -> full tier.
        self.assertEqual(tab._tier_for_speaker("Rowan Vale"), "full")
        # Pip (small) -> compact tier.
        self.assertEqual(tab._tier_for_speaker("Pip Marlowe"), "compact")


class TestGeneralizedLifecycle(unittest.TestCase):
    def _tab(self):
        from gui.tabs.dialogue_tab import DialogueTab, LIFECYCLE
        tab = DialogueTab.__new__(DialogueTab)
        tab._speakers = _speakers()
        tab.active_lifecycle = LIFECYCLE
        tab._phase_index = 0
        tab._big_turn_cursor = 0
        tab._small_turn_cursor = 0
        return tab

    def test_two_brains_alternate_big_small(self):
        tab = self._tab()
        # Phase 0 is a big (driver) turn, phase 1 a small (navigator) turn.
        # With 1 big + 1 small this is exactly Edward then Jacob.
        tab._speakers = _speakers()[:2]
        speakers = [tab._current_phase_speaker() for _ in range(4)]
        self.assertEqual(speakers[0], "Edward Hurst")   # big phase
        self.assertEqual(speakers[1], "Jacob Stanley")   # small phase
        self.assertEqual(speakers[2], "Edward Hurst")    # wraps
        self.assertEqual(speakers[3], "Jacob Stanley")

    def test_legacy_fallback_without_roster(self):
        from gui.tabs.dialogue_tab import DialogueTab, LIFECYCLE
        tab = DialogueTab.__new__(DialogueTab)  # no _speakers
        tab.active_lifecycle = LIFECYCLE
        tab._phase_index = 0
        # No roster -> classic Driver/Navigator names (mapped to Edward/Jacob
        # downstream by _persona_name).
        self.assertEqual(tab._current_phase_speaker(), "Driver")
        self.assertEqual(tab._current_phase_speaker(), "Navigator")

    def test_multi_big_brains_rotate_within_tier(self):
        tab = self._tab()
        # 2 big brains (Edward, Rowan). Consecutive big phases should rotate
        # between them via the per-tier cursor.
        # Phases: 0=big, 2=big (both big turns).
        first_big = tab._current_phase_speaker()   # consumes phase 0 (big)
        _small = tab._current_phase_speaker()       # consumes phase 1 (small)
        second_big = tab._current_phase_speaker()   # consumes phase 2 (big)
        self.assertEqual(first_big, "Edward Hurst")
        # The next big turn goes to the other big brain (Rowan Vale).
        self.assertEqual(second_big, "Rowan Vale")


if __name__ == "__main__":
    unittest.main()
