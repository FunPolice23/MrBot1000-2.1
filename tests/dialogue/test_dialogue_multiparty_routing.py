"""Phase 4: multi-party routing — persistence keys + agent descriptors generalize
to N devices, reducing to the legacy big/small behavior for 2 brains."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeBrain:
    def __init__(self, name):
        self.model = name


class TestMultiPartyRouting(unittest.TestCase):
    def _speakers(self):
        from agents.cognition.speaker_registry import Speaker
        return [
            Speaker(slot=0, key="big_brain", name="Edward Hurst", tier="big",
                    brain=_FakeBrain("e"), is_primary_big=True),
            Speaker(slot=1, key="small_brain", name="Jacob Stanley", tier="small",
                    brain=_FakeBrain("j"), is_primary_small=True),
            Speaker(slot=2, key="brain_slot2", name="Rowan Vale", tier="big",
                    brain=None),
            Speaker(slot=3, key="brain_slot3", name="Pip Marlowe", tier="small",
                    brain=None),
        ]

    def _tab(self):
        from gui.tabs.dialogue_tab import DialogueTab
        tab = DialogueTab.__new__(DialogueTab)
        tab._speakers = self._speakers()
        tab.big_brain = _FakeBrain("big-model")
        tab.small_brain = _FakeBrain("small-model")
        return tab

    def test_create_agent_runtime_builds_one_descriptor_per_speaker(self):
        tab = self._tab()
        tab.goal = "test goal"
        rt = tab._create_agent_runtime()
        # 4 speakers -> 4 agents (peer/support roles, not driver/navigator).
        self.assertEqual(len(rt.states), 4)
        # agent_id == the speaker's registry key.
        keys = set(rt.states.keys())
        self.assertEqual(
            keys, {"big_brain", "small_brain", "brain_slot2", "brain_slot3"})
        # Big brains are peers; small brains are support (shared-skills council).
        roles = {k: st.descriptor.role for k, st in rt.states.items()}
        self.assertEqual(roles["big_brain"], "peer")
        self.assertEqual(roles["brain_slot2"], "peer")
        self.assertEqual(roles["small_brain"], "support")

    def test_create_agent_runtime_legacy_fallback_two_brains(self):
        from gui.tabs.dialogue_tab import DialogueTab
        tab = DialogueTab.__new__(DialogueTab)  # no _speakers
        tab.goal = "test"
        rt = tab._create_agent_runtime()
        self.assertEqual(len(rt.states), 2)
        keys = set(rt.states.keys())
        self.assertEqual(keys, {"edward", "jacob"})
        roles = {k: st.descriptor.role for k, st in rt.states.items()}
        self.assertEqual(roles["edward"], "driver")
        self.assertEqual(roles["jacob"], "navigator")

    def test_round_robin_over_four_speakers(self):
        tab = self._tab()
        names = [s.name for s in tab._speakers]
        # Advance through the whole roster and wrap.
        seq = [names[0]]
        cur = names[0]
        for _ in range(len(names)):
            cur = tab._next_speaker_after(cur)
            seq.append(cur)
        # After a full cycle we return to the start.
        self.assertEqual(seq[-1], names[0])
        # Each step moves to the next distinct speaker.
        self.assertEqual(seq[:4], [names[0], names[1], names[2], names[3]])

    def test_round_robin_two_brains_is_alternation(self):
        from gui.tabs.dialogue_tab import DialogueTab, _BIG, _SMALL
        tab = DialogueTab.__new__(DialogueTab)  # no roster -> legacy
        self.assertEqual(tab._next_speaker_after(_BIG), _SMALL)
        self.assertEqual(tab._next_speaker_after(_SMALL), _BIG)

    def test_persist_dialogue_turn_persona_uses_registry_key(self):
        from unittest.mock import patch
        tab = self._tab()
        tab.goal = "g"
        calls = []
        class _DB:
            def log_conversation(self, brain, speaker, msg, goal):
                calls.append(("log", brain, speaker))
        class _Eng:
            def evolve_from_interaction(self, *a):
                calls.append(("evolve",) + a)
        with patch("agents.knowledge.program_knowledge.get_database", return_value=_DB()), \
             patch("agents.knowledge.program_knowledge.get_personality_engine", return_value=_Eng()):
            tab._persist_dialogue_turn("Rowan Vale", "hello")
        # A persona turn logs only to that speaker's registry brain key.
        log_brains = [c[1] for c in calls if c[0] == "log"]
        self.assertEqual(log_brains, ["brain_slot2"])

    def test_persist_dialogue_turn_human_logs_all_brains(self):
        from unittest.mock import patch
        tab = self._tab()
        tab.goal = "g"
        calls = []
        class _DB:
            def log_conversation(self, brain, speaker, msg, goal):
                calls.append(("log", brain, speaker))
        class _Eng:
            def evolve_from_interaction(self, *a):
                calls.append(("evolve",) + a)
        with patch("agents.knowledge.program_knowledge.get_database", return_value=_DB()), \
             patch("agents.knowledge.program_knowledge.get_personality_engine", return_value=_Eng()):
            tab._persist_dialogue_turn("Human", "hi")
        log_brains = sorted(c[1] for c in calls if c[0] == "log")
        # Human turn logs to every enabled brain + evolves each.
        self.assertEqual(
            log_brains,
            ["big_brain", "brain_slot2", "brain_slot3", "small_brain"])
        evolve_brain_idxs = [c[1] for c in calls if c[0] == "evolve"]
        self.assertEqual(len(evolve_brain_idxs), 4)


if __name__ == "__main__":
    unittest.main()
