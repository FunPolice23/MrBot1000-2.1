"""Canonical tests for Section D (LLM quality & cost).

Run individually:  python -m unittest tests.test_section_d
Via suite:         python -m tests --test test_section_d

All tests are mock-first / offline (no live network, no credentials).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class FakeWorker:
    """Captures the chat= kwarg passed to worker.llm."""
    def __init__(self):
        self.last_chat = None
        self.last_kwargs = {}

    def llm(self, system="", user="", max_tokens=350, chat=True, think=False, **kw):
        self.last_chat = chat
        self.last_kwargs = dict(chat=chat, max_tokens=max_tokens, think=think, **kw)
        return "Draft proposal text."


class TestProposalModelRole(unittest.TestCase):
    """D1: proposal drafting model role follows PROPOSAL_MODEL_ROLE env."""

    def _make_manager(self):
        # Import lazily so the env is read at call time.
        import manager
        m = manager.ManagerThread.__new__(manager.ManagerThread)
        m.worker = FakeWorker()
        return m

    def test_default_role_is_chat(self):
        from tests.test_section_d import FakeWorker
        m = self._make_manager()
        with patch.object(m, "worker", FakeWorker()):
            # ensure default env
            os.environ.pop("PROPOSAL_MODEL_ROLE", None)
            out = type(m)._prepare_proposal_text(m, "Write a python gig proposal")
            self.assertEqual(m.worker.last_chat, True)
            self.assertTrue(out)

    def test_role_main_routes_to_main(self):
        from tests.test_section_d import FakeWorker
        m = self._make_manager()
        with patch.object(m, "worker", FakeWorker()):
            os.environ["PROPOSAL_MODEL_ROLE"] = "main"
            try:
                out = type(m)._prepare_proposal_text(m, "task")
                self.assertEqual(m.worker.last_chat, False)
                self.assertTrue(out)
            finally:
                del os.environ["PROPOSAL_MODEL_ROLE"]

    def test_role_chat_explicit(self):
        from tests.test_section_d import FakeWorker
        m = self._make_manager()
        with patch.object(m, "worker", FakeWorker()):
            os.environ["PROPOSAL_MODEL_ROLE"] = "chat"
            try:
                type(m)._prepare_proposal_text(m, "task")
                self.assertEqual(m.worker.last_chat, True)
            finally:
                del os.environ["PROPOSAL_MODEL_ROLE"]

    def test_unknown_role_falls_back_to_chat(self):
        from tests.test_section_d import FakeWorker
        m = self._make_manager()
        with patch.object(m, "worker", FakeWorker()):
            os.environ["PROPOSAL_MODEL_ROLE"] = "bogus"
            try:
                type(m)._prepare_proposal_text(m, "task")
                self.assertEqual(m.worker.last_chat, True)
            finally:
                del os.environ["PROPOSAL_MODEL_ROLE"]


class FakeLearningMemory:
    """Minimal EarningMemory stand-in for proposal-intro A/B tracking."""
    def __init__(self):
        self.rows = []  # list of (learning_type, insight, confidence)

    def store_learning(self, learning_type, insight, confidence=0.5):
        self.rows.append((learning_type, str(insight), float(confidence)))

    def get_recent_learned(self, learning_type=None, limit=10):
        out = []
        for (lt, ins, conf) in reversed(self.rows):
            if learning_type is None or lt == learning_type:
                out.append({"learning_type": lt, "insight": ins, "confidence": conf})
            if len(out) >= limit:
                break
        return out


class TestProposalTemplates(unittest.TestCase):
    def test_intro_rotation_distinct(self):
        from agents.proposal_templates import pick_intro, PROPOSAL_INTROS
        seen = {pick_intro("Upwork") for _ in range(20)}
        self.assertGreater(len(seen), 1)  # round-robins across variants
        self.assertLessEqual(len(seen), len(PROPOSAL_INTROS))

    def test_best_intro_none_before_samples(self):
        from agents.proposal_templates import best_intro, record_win, record_loss
        mem = FakeLearningMemory()
        # Fewer than MIN_SAMPLES -> still returns None (honest A/B).
        for _ in range(3):
            record_win("Upwork", "v0", memory=mem)
        self.assertIsNone(best_intro("Upwork", memory=mem))

    def test_best_intro_picks_winner(self):
        from agents.proposal_templates import best_intro, record_win, record_loss
        mem = FakeLearningMemory()
        # v0: 10 wins, v1: 2 wins / 8 losses -> v0 should win once enough data.
        for _ in range(10):
            record_win("Upwork", "v0", memory=mem)
        for _ in range(2):
            record_win("Upwork", "v1", memory=mem)
        for _ in range(8):
            record_loss("Upwork", "v1", memory=mem)
        self.assertEqual(best_intro("Upwork", memory=mem), "v0")

    def test_pick_intro_uses_best_when_available(self):
        from agents.proposal_templates import pick_intro, record_win, record_loss
        mem = FakeLearningMemory()
        for _ in range(10):
            record_win("Upwork", "v2", memory=mem)
        for _ in range(10):
            record_loss("Upwork", "v3", memory=mem)
        intro = pick_intro("Upwork", memory=mem)
        from agents.proposal_templates import PROPOSAL_INTROS, _idx_from_variant
        self.assertEqual(_idx_from_variant("v2"), PROPOSAL_INTROS.index(intro))

    def test_record_is_safe_without_memory(self):
        from agents.proposal_templates import record_win, record_loss
        # Must not raise when memory is None.
        record_win("Upwork", "v0", memory=None)
        record_loss("Upwork", "v0", memory=None)


class FakeAdapter:
    """Minimal provider adapter stand-in for D3 routing tests."""
    def __init__(self, name, order, default_model="", chat_model="",
                 available=True):
        self.name = name
        self.order = order
        self.default_model = default_model
        self.chat_model = chat_model
        self._avail = available

    def available(self):
        return self._avail

    def complete(self, model, system, user, max_tokens, chat=False):
        return "ok"


class TestCostAwareRouting(unittest.TestCase):
    def _make_worker(self, adapters, chat=False):
        # Build a WorkerAgent instance without running __init__ (avoid heavy setup).
        import agents.base_worker as bw
        w = bw.WorkerAgent.__new__(bw.WorkerAgent)
        w._provider_registry = adapters
        # _role_allows: allow all for the test.
        w._role_allows = lambda ad, chat: True
        w._chat_model_effective = lambda: None
        w._ollama_model_override = ""
        w._chat_ollama_model_override = ""
        return w

    def _adapters(self):
        return [
            FakeAdapter("ollama", 0, default_model="llama3.2"),
            FakeAdapter("openai", 40, default_model="gpt-4o"),       # $10/1M out
            FakeAdapter("anthropic", 50, default_model="claude-3-5-sonnet"),  # $15/1M
            FakeAdapter("groq", 70, default_model="llama-3.1-8b"),   # cheap/$0.2? unknown->None
            FakeAdapter("unknownp", 60, default_model="mystery-model"),  # None price
        ]

    def test_cost_aware_orders_cheapest_first(self):
        import os
        os.environ.pop("LLM_COST_AWARE", None)  # default on
        w = self._make_worker(self._adapters())
        names = [n for (n, _f, _mk, _dm) in w._build_providers(chat=False)]
        # ollama first (free), then cheapest known billable (groq unknown->last?),
        # then by price. openai(10) < anthropic(15); unknown->sorted last.
        self.assertEqual(names[0], "ollama")
        # cheapest known billable should precede the more expensive one
        self.assertLess(names.index("openai"), names.index("anthropic"))
        # unknown price sorts last
        self.assertEqual(names[-1], "unknownp")

    def test_disabled_cost_aware_keeps_adapter_order(self):
        import os
        os.environ["LLM_COST_AWARE"] = "0"
        try:
            w = self._make_worker(self._adapters())
            names = [n for (n, _f, _mk, _dm) in w._build_providers(chat=False)]
            # Without cost-aware, follows adapter.order: ollama, openai, anthropic,
            # unknownp, groq.
            self.assertEqual(names, ["ollama", "openai", "anthropic", "unknownp", "groq"])
        finally:
            del os.environ["LLM_COST_AWARE"]

    def test_local_always_first(self):
        import os
        os.environ.pop("LLM_COST_AWARE", None)
        w = self._make_worker(self._adapters())
        names = [n for (n, _f, _mk, _dm) in w._build_providers(chat=False)]
        self.assertEqual(names[0], "ollama")

    def test_no_providers_safe(self):
        import os
        os.environ.pop("LLM_COST_AWARE", None)
        w = self._make_worker([])
        self.assertEqual(w._build_providers(chat=False), [])


class TestCircuitBreaker(unittest.TestCase):
    def _breaker(self):
        from agents.circuit_breaker import ProviderCircuitBreaker
        return ProviderCircuitBreaker()

    def test_opens_after_threshold(self):
        import os
        os.environ.pop("LLM_CB_ENABLED", None)
        b = self._breaker()
        for _ in range(2):
            b.record_failure("openai")
        self.assertFalse(b.is_open("openai"))   # 2 < threshold 3
        b.record_failure("openai")
        self.assertTrue(b.is_open("openai"))     # 3 == threshold -> open

    def test_success_resets(self):
        import os
        os.environ.pop("LLM_CB_ENABLED", None)
        b = self._breaker()
        for _ in range(3):
            b.record_failure("openai")
        self.assertTrue(b.is_open("openai"))
        b.record_success("openai")
        self.assertFalse(b.is_open("openai"))    # success closes it

    def test_cooldown_expiry_half_open(self):
        import os, time
        os.environ["LLM_CB_COOLDOWN"] = "0.01"
        try:
            b = self._breaker()
            for _ in range(3):
                b.record_failure("groq")
            self.assertTrue(b.is_open("groq"))
            time.sleep(0.02)
            # cooldown elapsed -> half-open, allowed again, counts reset
            self.assertFalse(b.is_open("groq"))
        finally:
            del os.environ["LLM_CB_COOLDOWN"]

    def test_disabled_never_opens(self):
        import os
        os.environ["LLM_CB_ENABLED"] = "0"
        try:
            b = self._breaker()
            for _ in range(10):
                b.record_failure("anthropic")
            self.assertFalse(b.is_open("anthropic"))
        finally:
            del os.environ["LLM_CB_ENABLED"]

    def test_isolated_per_provider(self):
        import os
        os.environ.pop("LLM_CB_ENABLED", None)
        b = self._breaker()
        for _ in range(3):
            b.record_failure("openai")
        self.assertTrue(b.is_open("openai"))
        # a different provider is unaffected
        self.assertFalse(b.is_open("gemini"))


class TestProposalVariantPlumbing(unittest.TestCase):
    """D2 re-audit (v2.0.34z): the intro variant must reach the opp so the
    real-outcome hook can credit it (otherwise A/B never learns)."""

    def test_record_ramp_real_outcome_credits_variant(self):
        from agents.proposal_templates import best_intro, record_win
        from tests.test_section_d import FakeLearningMemory

        class FakeOpp:
            def __init__(s, platform, variant=None):
                s.platform = platform
                s.proposal_variant = variant

        mem = FakeLearningMemory()
        # Make a pipeline-like object exposing _record_ramp_real_outcome.
        import earning_pipeline as ep
        pipe = ep.EarningPipeline.__new__(ep.EarningPipeline)
        pipe.memory = mem

        opp = FakeOpp("Upwork", variant="v1")
        pipe._record_ramp_real_outcome(opp, accepted=True)
        # Seed enough wins for the variant to become the best.
        for _ in range(9):
            record_win("Upwork", "v1", memory=mem)
        self.assertEqual(best_intro("Upwork", memory=mem), "v1")

    def test_no_variant_no_credit(self):
        from agents.proposal_templates import best_intro
        from tests.test_section_d import FakeLearningMemory
        import earning_pipeline as ep

        mem = FakeLearningMemory()
        pipe = ep.EarningPipeline.__new__(ep.EarningPipeline)
        pipe.memory = mem

        class FakeOpp:
            platform = "Upwork"
            proposal_variant = None

        pipe._record_ramp_real_outcome(FakeOpp(), accepted=True)
        # No variant recorded -> best_intro stays None (honest A/B, no noise).
        self.assertIsNone(best_intro("Upwork", memory=mem))


if __name__ == "__main__":
    unittest.main()
