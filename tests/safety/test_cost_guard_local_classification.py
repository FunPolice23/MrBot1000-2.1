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

from agents.safety.cost import (
    CostGuard, enforcement_skip_decision, estimate_call_cost, is_local_provider)

_LOCAL = [
    "big-brain", "small-brain", "llamacpp", "ollama", "lmstudio",
    "lm-studio", "vllm", "koboldcpp", "local-foo",
]
_BILLABLE = [
    "openai", "anthropic", "openrouter", "groq", "nvidia", "nvidia_nim",
    "deepseek", "mistral", "llama-cloud", "localstack-cloud",
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


class TestEstimateCallCost(unittest.TestCase):
    """A roster cloud-backed brain must record REAL cost (not a hardcoded 0.0),
    or it never counts against the daily budget and CostGuard never trips."""

    def test_local_brain_is_free(self):
        for name in _LOCAL:
            with self.subTest(provider=name):
                self.assertEqual(
                    estimate_call_cost(name, "any-model", 1000, 500), 0.0,
                    f"{name} runs on-machine and must cost 0.0")

    def test_cloud_brain_records_real_cost(self):
        # A priced cloud model must yield a non-zero cost so it accumulates
        # against the daily budget (the old hardcoded 0.0 let it bill freely).
        cost = estimate_call_cost("openai", "gpt-4o-mini", 1000, 500)
        self.assertGreater(cost, 0.0,
                           "a cloud-backed brain must record real cost, not 0.0")

    def test_unknown_pricing_never_fabricates(self):
        # An unpriced cloud model yields 0.0 (we never invent a cost), but it
        # is still classified cloud (not local) by the guard.
        self.assertEqual(estimate_call_cost("openai", "totally-unknown-xyz", 1000, 500), 0.0)
        self.assertFalse(is_local_provider("openai"))

    def test_zero_tokens_zero_cost(self):
        self.assertEqual(estimate_call_cost("openai", "gpt-4o-mini", 0, 0), 0.0)


class TestEnforcementSkipDecision(unittest.TestCase):
    """The brain-adapter enforcement gate: classify billable by provider NAME,
    never by recorded cost. Priced cloud -> capped by $; unpriced cloud ->
    recorded 0.0 (truthful) but still billable by name so the call-count cap
    applies; local -> free."""

    def setUp(self):
        self._old = os.environ.get("LLM_DAILY_BUDGET_USD")
        os.environ["LLM_DAILY_BUDGET_USD"] = "1.0"

    def tearDown(self):
        if self._old is None:
            os.environ.pop("LLM_DAILY_BUDGET_USD", None)
        else:
            os.environ["LLM_DAILY_BUDGET_USD"] = self._old

    def test_local_never_skipped_even_over_budget(self):
        for name in _LOCAL:
            with self.subTest(provider=name):
                skip, _ = enforcement_skip_decision(name, _FakeDB(999.0))
                self.assertFalse(skip, f"{name} is free — never budget-skipped")

    def test_billable_cloud_skipped_when_over_budget(self):
        skip, reason = enforcement_skip_decision("openai", _FakeDB(999.0))
        self.assertTrue(skip)
        self.assertIn("budget", reason.lower())

    def test_billable_cloud_allowed_when_under_budget(self):
        skip, _ = enforcement_skip_decision("openai", _FakeDB(0.0))
        self.assertFalse(skip)

    def test_unpriced_cloud_is_billable_by_name(self):
        # The design point: an unpriced cloud model records 0.0 cost, but it is
        # still BILLABLE by name, so the call-count cap (not the $-budget) is
        # its backstop. Lock both: recorded cost 0.0 AND name-classified cloud.
        self.assertEqual(estimate_call_cost("openai", "unpriced-xyz", 1000, 500), 0.0)
        self.assertFalse(is_local_provider("openai"))


if __name__ == "__main__":
    unittest.main()
