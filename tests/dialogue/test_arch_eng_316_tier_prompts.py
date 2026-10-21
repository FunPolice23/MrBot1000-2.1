"""ARCH-ENG-316 — the navigator's persona prompt follows its size tier.

Operator symptom after the ARCH-ENG-313 pause fix: the 1.2B small brain
generated turns again, but they were poor/aimless — restating the plan,
promising "I'll run a targeted read" and never doing it. Cause: the output
CONTRACT was tiny ("1-3 short sentences"), but the persona SYSTEM prompt
that frames the whole turn was built without a tier, so it defaulted to
FULL — `# RESPONSE PROCESS`, tool language ("You have REAL tools"),
"BE A REAL PARTICIPANT" council economics — prompt weight a 1.2B model
cannot follow. The tiny persona prompt exists and is good; it just never
reached the small brain.

Contract now: `_tier_for_speaker` resolves the same model-size tier the
output contract uses (`_tier_for_brain`), and `respond()` passes it into
`build_system_prompt`. A sub-2B speaker gets the tiny prompt; a large
model keeps the full one; "possible issues with big brain" must not
regress (a 30B-class brain keeps its full prompt).
"""

import ast
import inspect
import os
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _tab_for(model: str, is_big: bool):
    from gui.tabs.dialogue_tab import DialogueTab
    import agents.cognition.speaker_registry as reg

    tab = DialogueTab.__new__(DialogueTab)
    spk = SimpleNamespace(name="Tester", is_big=is_big,
                          brain=SimpleNamespace(model=model),
                          device_label="")
    tab._speakers = [spk]
    tab._speaker_for = lambda name: spk
    tab._brain_for = lambda speaker: spk.brain
    # Never touch nvidia-smi in a unit test: unknown VRAM must keep the
    # deterministic model-size tier.
    tab._brain_gpu_vram_gb = lambda small: None
    return tab, spk


class TestTheTierFollowsTheModel(unittest.TestCase):
    def test_a_sub_2b_navigator_is_tiny(self):
        tab, _ = _tab_for("tinyllama-1.1b", is_big=False)
        self.assertEqual(tab._tier_for_speaker("Tester"), "tiny")

    def test_a_smallish_model_is_compact(self):
        tab, _ = _tab_for("qwen2.5-7b-instruct", is_big=False)
        self.assertEqual(tab._tier_for_speaker("Tester"), "compact")

    def test_a_big_brain_keeps_full(self):
        # The operator's big brain must not be demoted by this change.
        tab, _ = _tab_for("qwen3.5-35b-a3b-instruct", is_big=True)
        self.assertEqual(tab._tier_for_speaker("Tester"), "full")


class TestRespondWiresTheTierIntoThePrompt(unittest.TestCase):
    def test_respond_passes_tier_to_build_system_prompt(self):
        from gui.tabs.dialogue_tab import DialogueTab
        src = (ROOT / "gui" / "tabs" / "dialogue_tab.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        fn = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "DialogueTab":
                for sub in node.body:
                    if (isinstance(sub, ast.FunctionDef)
                            and sub.name == "respond"):
                        fn = sub
        self.assertIsNotNone(fn, "respond() went missing")
        # tier= self._tier_for_speaker(...)
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "build_system_prompt"):
                self.assertTrue(
                    any(k.arg == "tier"
                        and "_tier_for_speaker" in ast.dump(k.value)
                        for k in node.keywords),
                    "respond() no longer passes tier into "
                    "build_system_prompt; sub-2B speakers would speak from "
                    "the full persona prompt again")
                break
        else:
            self.fail("respond() no longer calls build_system_prompt")

    def test_the_tiny_persona_prompt_is_actually_tiny(self):
        from agents.cognition.personas import persona_for_key
        persona = persona_for_key("Jacob Stanley")
        tiny = persona.build_system_prompt(goal="earn", tier="tiny")
        full = persona.build_system_prompt(goal="earn", tier="full")
        self.assertIn("1-3 short sentences", tiny)
        self.assertNotIn("# RESPONSE PROCESS", tiny)
        self.assertNotIn("# MEMORY", tiny)
        self.assertNotIn("You have REAL tools", tiny)
        self.assertLess(len(tiny), len(full),
                        "the tiny tier must be lighter than full")
        self.assertIn("# RESPONSE PROCESS", full)


if __name__ == "__main__":
    unittest.main()
