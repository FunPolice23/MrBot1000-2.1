"""ARCH-ENG-317: plain Dialogue turns must not claim GoT orchestration.

The Dialogue tab is mostly simple back-and-forth talk. Before this change every
turn built its BrainTurnGraph by running the keyword resolver over the ENTIRE
turn context — and the board text routinely contains "options"/"compare"/
"evidence" — so casual conversation was labelled tree_of_thoughts /
graph_of_thoughts / react even though no branching ever happened (no production
caller supplies branch candidates). Now a dialogue_mode turn without branch
candidates records the honest linear skeleton (direct_dialogue). A turn that
deliberately carries branch candidates still resolves and branches normally,
and non-dialogue callers keep the resolver's behaviour.
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.brains.big_brain import BigBrainAdapter
from agents.brains.brain_got import start_brain_turn
from agents.brains.small_brain import SmallBrainAdapter
from agents.cognition.reasoning_modes import (
    PatternSelection,
    ReasoningPattern,
)

TRIGGER_HEAVY = "compare the options and verify the evidence listings"


def _patched_chat(adapter, message, **kwargs):
    """Drive adapter.chat with a stubbed provider so no server is needed."""
    client = Mock()
    client.chat.completions.create.return_value = None
    with patch.object(adapter, "_get_client", return_value=client), \
         patch("agents.safety.calling.chat_with_tools",
               return_value="hello there"), \
         patch("agents.providers.model_profile.get_model_profile",
               return_value={}):
        return adapter.chat(message, [], system_prompt="Persona", **kwargs)


def _pattern_of(graph):
    return (graph.get("pattern") or {}).get("name")


class TestArchEng317DialogueGotRouting(unittest.TestCase):
    """Dialogue turns record direct_dialogue; deliberate branching is intact."""

    def test_small_brain_dialogue_turn_records_direct_dialogue(self):
        adapter = SmallBrainAdapter(model="test-model")
        out = _patched_chat(adapter, TRIGGER_HEAVY, dialogue_mode=True)
        self.assertEqual(out, "hello there")
        self.assertEqual(_pattern_of(adapter.last_thought_graph),
                         ReasoningPattern.DIRECT_DIALOGUE.value)

    def test_big_brain_dialogue_turn_records_direct_dialogue(self):
        adapter = BigBrainAdapter(model="test-model")
        out = _patched_chat(adapter, TRIGGER_HEAVY, dialogue_mode=True)
        self.assertEqual(out, "hello there")
        self.assertEqual(_pattern_of(adapter.last_thought_graph),
                         ReasoningPattern.DIRECT_DIALOGUE.value)

    def test_branch_candidates_still_resolve_and_branch(self):
        """A turn that deliberately carries candidates is a real branching turn."""
        adapter = SmallBrainAdapter(model="test-model")
        _patched_chat(
            adapter, "compare the options", dialogue_mode=True,
            branch_candidates=[{"text": "a"}, {"text": "b"}])
        graph = adapter.last_thought_graph
        self.assertNotEqual(_pattern_of(graph),
                            ReasoningPattern.DIRECT_DIALOGUE.value)
        self.assertTrue(graph.get("branch_summary"))

    def test_non_dialogue_calls_keep_resolver_behaviour(self):
        """dialogue_mode=False keeps keyword routing (analysis flows)."""
        adapter = SmallBrainAdapter(model="test-model")
        _patched_chat(adapter, TRIGGER_HEAVY, dialogue_mode=False)
        self.assertEqual(_pattern_of(adapter.last_thought_graph),
                         ReasoningPattern.TREE_OF_THOUGHTS.value)

    def test_explicit_pattern_overrides_resolver_in_brain_got(self):
        """start_brain_turn honours an explicit PatternSelection verbatim."""
        turn = start_brain_turn(
            "small_brain", TRIGGER_HEAVY,
            pattern=PatternSelection(
                ReasoningPattern.DIRECT_DIALOGUE,
                "plain dialogue turn: back-and-forth conversation needs "
                "no branching"))
        data = turn.finish("reply")
        self.assertEqual(data["pattern"]["name"],
                         ReasoningPattern.DIRECT_DIALOGUE.value)
        self.assertEqual(data["pattern"]["max_branches"], 1)


if __name__ == "__main__":
    unittest.main()
