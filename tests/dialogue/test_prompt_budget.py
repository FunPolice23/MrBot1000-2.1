"""Prompt tier and shared assembly budget checks."""

import os
import unittest
from unittest.mock import patch

from agents.knowledge.prompt_assembly import assemble_role_prompt
from agents.brains.small_brain import SmallBrainAdapter
from agents.knowledge.prompting_engine import adaptive_prompt, enforce_prompt_budget, prompt_telemetry


class _Personality:
    def get_system_prompt_addon(self, role):
        return f"\nPERSONALITY:{role}"


class _Knowledge:
    def build_context(self, role, query):
        return f"CONTEXT:{role}:{query}:" + ("x" * 5000)


class TestPromptBudget(unittest.TestCase):
    def setUp(self):
        self.adapter = SmallBrainAdapter.__new__(SmallBrainAdapter)
        self.adapter.base_system_prompt = "BASE"
        self.adapter.personality = _Personality()
        self.adapter.knowledge = _Knowledge()
        # _build_system_prompt consults the active model for its prompt-tier
        # recommendation; a real adapter always has this set in __init__.
        self.adapter.model = "Qwen3.5-4B-UD-Q5_K_XL.gguf"
        # _build_system_prompt also reads this flag (set from the canonical
        # runtime config in __init__). A __new__-built adapter must set it or
        # the prompt builder raises AttributeError.
        self.adapter.decision_support_only = False

    def _prompt(self, tier):
        with patch.dict(os.environ, {"SMALL_BRAIN_PROMPT_TIER": tier}, clear=False):
            return self.adapter._build_system_prompt("query")

    def test_tiers_are_ordered_and_bounded(self):
        tiny = self._prompt("tiny")
        compact = self._prompt("compact")
        full = self._prompt("full")

        self.assertLess(len(tiny), len(compact))
        self.assertLess(len(compact), len(full))
        self.assertLess(len(compact), 3000)
        self.assertIn("UNKNOWN", tiny)
        self.assertNotIn("CONTEXT:small_brain:query:" + ("x" * 2000), compact)

    def test_invalid_tier_falls_back_to_compact(self):
        self.assertEqual(self._prompt("invalid"), self._prompt("compact"))

    def test_shared_assembly_has_stable_order_and_limit(self):
        prompt = assemble_role_prompt(
            "BASE", "small_brain", "query", _Personality(), _Knowledge(),
            extra="\nEXTRA", context_limit=20)

        self.assertLess(prompt.index("EXTRA"), prompt.index("PERSONALITY"))
        self.assertLess(prompt.index("PERSONALITY"), prompt.index("CURRENT CONTEXT"))
        self.assertTrue(prompt.endswith("x" * 20))

    def test_adaptive_prompt_modes_are_bounded(self):
        base = "BASE " + ("x" * 25000)
        fast = adaptive_prompt("dialogue", base, {"prompt_mode": "fast"})
        deep = adaptive_prompt("dialogue", base, {"prompt_mode": "deep"})
        self.assertLessEqual(len(fast), 4000)
        self.assertLessEqual(len(deep), 18000)
        self.assertLess(len(fast), len(deep))

    def test_adaptive_prompt_invalid_mode_uses_standard(self):
        standard = adaptive_prompt("dialogue", "BASE", {"prompt_mode": "standard"})
        invalid = adaptive_prompt("dialogue", "BASE", {"prompt_mode": "invalid"})
        self.assertEqual(standard, invalid)

    def test_prompt_telemetry_records_mode_and_technique(self):
        before = prompt_telemetry()["prompts"]
        adaptive_prompt("dialogue", "BASE", {"prompt_mode": "fast"})
        after = prompt_telemetry()
        self.assertEqual(after["prompts"], before + 1)
        self.assertGreaterEqual(after["by_mode"]["fast"], 1)
        self.assertGreaterEqual(after["by_technique"]["cot"], 1)

    def test_external_prompts_are_bounded(self):
        prompt = enforce_prompt_budget("x" * 20000, {"prompt_mode": "fast"})
        self.assertLessEqual(len(prompt), 4000)


if __name__ == "__main__":
    unittest.main()