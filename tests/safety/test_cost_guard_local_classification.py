"""Cost-guard local/billable classification (the inverted-spend regression).

`is_local_provider` decides which providers the daily-budget guard NEVER skips.
It previously recognised only `ollama`/`local*`, so the local dual-brain adapter
names (`big-brain`/`small-brain`) and llamacpp/vllm/koboldcpp classified as
BILLABLE — meaning that when the daily cap was hit, `CostGuard.should_skip`
skipped the FREE local brain and fell back to a paid cloud provider, spending
real money the budget exists to prevent (the exact opposite of the guard's
documented intent). This test locks the invariant.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.safety.cost import CostGuard, is_local_provider

_LOCAL = [
    "big-brain", "small-brain", "llamacpp", "ollama", "lmstudio",
    "lm-studio", "vllm", "koboldcpp", "local-foo",
]
_BILLABLE = [
    "openai", "anthropic", "openrouter", "groq", "nvidia", "nvidia_nim",
    "deepseek", "mistral",
]


class _FakeDB:
    def __init__(self, daily_cost):
        self._cost = daily_cost

    def get_llm_cost_usd(self, days=1):
        return self._cost


class TestIsLocalProvider(unittest.TestCase):
    def test_local_adapters_are_free(self):
        for name in _LOCAL:
            with self.subTest(provider=name):
                self.assertTrue(is_local_provider(name),
                                f"{name} runs on-machine and must be free")

    def test_cloud_providers_are_billable(self):
        for name in _BILLABLE:
            with self.subTest(provider=name):
                self.assertFalse(is_local_provider(name),
                                 f"{name} bills per token and must be billable")

    def test_empty_is_not_local(self):
        self.assertFalse(is_local_provider(""))
        self.assertFalse(is_local_provider(None))


class TestBudgetGuardLocalNeverSkipped(unittest.TestCase):
    """The core invariant: a budget overrun must never skip a FREE local brain."""

    def test_local_never_skipped_even_when_budget_exceeded(self):
        guard = CostGuard(1.0)
        over_budget = _FakeDB(999.0)
        self.assertTrue(guard.is_exceeded(over_budget), "precondition: cap exceeded")
        for name in _LOCAL:
            with self.subTest(provider=name):
                self.assertFalse(
                    guard.should_skip(over_budget, name),
                    f"{name} is free — the budget guard must NEVER skip it, "
                    "or it falls back to a paid cloud provider and spends money")

    def test_billable_is_skipped_when_budget_exceeded(self):
        guard = CostGuard(1.0)
        over_budget = _FakeDB(999.0)
        for name in _BILLABLE:
            with self.subTest(provider=name):
                self.assertTrue(
                    guard.should_skip(over_budget, name),
                    f"{name} is billable and over cap — it must be skipped")

    def test_disabled_budget_skips_nothing(self):
        guard = CostGuard(0.0)
        self.assertFalse(guard.should_skip(_FakeDB(999.0), "openai"))
        self.assertFalse(guard.should_skip(_FakeDB(999.0), "big-brain"))


if __name__ == "__main__":
    unittest.main()
