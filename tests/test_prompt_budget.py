"""Prompt tier and shared assembly budget checks."""

import os
import unittest
from unittest.mock import patch

from agents.prompt_assembly import assemble_role_prompt
from agents.small_brain import SmallBrainAdapter


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


if __name__ == "__main__":
    unittest.main()