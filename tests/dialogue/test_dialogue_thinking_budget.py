"""Adjustable dialogue thinking-budget + reasoning detection (v2.1.51, ARCH-ENG-051).

Reasoning models spend part of the reply token budget on a hidden thinking
channel before the visible answer. A too-small budget makes them burn it all on
reasoning and return an empty visible reply (finish_reason: length) — the exact
failure a 27B reasoning model hit on the CPU/RAM brain. The dialogue budget must
give ANY reasoning model (any size, 1B..MoE) an adjustable reserve so think AND
answer both fit, and reasoning must be detectable generically (not by a fixed
name list).
"""
import os
import unittest


class SmallBrainFake:
    def __init__(self, model, context_length=32768):
        self.model = model
        self.context_length = context_length


class BigBrainFake:
    def __init__(self, model, context_length=32768):
        self.model = model
        self.context_length = context_length


_DIALOGUE_KEYS = (
    "DIALOGUE_MAX_TOKENS", "DIALOGUE_AUTO_TOKENS", "DIALOGUE_ENABLE_THINKING",
    "DIALOGUE_THINK_TOKENS", "DIALOGUE_THINK_TOKENS_SMALL",
    "DIALOGUE_THINK_TOKENS_BIG",
)


class _EnvPatch:
    """Context manager: clear the dialogue token keys, apply overrides, restore."""

    def __init__(self, **overrides):
        self.overrides = {k: v for k, v in overrides.items() if v != ""}
        self._old = None

    def __enter__(self):
        self._old = dict(os.environ)
        for k in _DIALOGUE_KEYS:
            os.environ.pop(k, None)
        os.environ.update(self.overrides)
        return self

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self._old)
        return False


class TestReasoningDetection(unittest.TestCase):
    """model_emits_reasoning must recognize reasoning models generically."""

    def test_bonsai_is_reasoning(self):
        from agents.brains.worker_thinking import model_emits_reasoning
        self.assertTrue(model_emits_reasoning(
            "D:/llama.cpp/models/Bonsai-27B-GGUF/Bonsai-27B-Q1_0.gguf"))

    def test_common_reasoning_families(self):
        from agents.brains.worker_thinking import model_emits_reasoning
        for m in ("qwen3-4b-thinking", "deepseek-r1-distill", "nemotron-reasoning",
                  "glm-4.7-flash", "qwq-32b"):
            self.assertTrue(model_emits_reasoning(m), m)

    def test_plain_model_is_not_reasoning(self):
        from agents.brains.worker_thinking import model_emits_reasoning
        self.assertFalse(model_emits_reasoning(
            "D:/llama.cpp/models/gemma-3-1B-it-QAT-GGUF/gemma-3-1B-it-QAT-Q4_0.gguf"))
        self.assertFalse(model_emits_reasoning("some-random-model"))

    def test_runtime_latch_learns_unknown_reasoning_model(self):
        from agents.brains.worker_thinking import (
            model_emits_reasoning, record_model_reasoning)
        # A name with NO reasoning hint, so only the runtime latch can flag it.
        name = "mystery-model-7b"
        self.assertFalse(model_emits_reasoning(name))
        record_model_reasoning(name)
        self.assertTrue(model_emits_reasoning(name))


class TestDialogueThinkingHeadroom(unittest.TestCase):
    """The adjustable per-class thinking reserve."""

    def _headroom(self, is_small, env):
        from gui.tabs.dialogue_tab import DialogueWorker
        with _EnvPatch(**env):
            return DialogueWorker._dialogue_thinking_headroom(is_small)

    def test_default_is_2048(self):
        self.assertEqual(self._headroom(True, {}), 2048)
        self.assertEqual(self._headroom(False, {}), 2048)

    def test_per_class_override(self):
        self.assertEqual(
            self._headroom(True, {"DIALOGUE_THINK_TOKENS_SMALL": "6144"}), 6144)
        self.assertEqual(
            self._headroom(False, {"DIALOGUE_THINK_TOKENS_BIG": "8192"}), 8192)

    def test_global_override_wins(self):
        self.assertEqual(
            self._headroom(True, {"DIALOGUE_THINK_TOKENS": "9000",
                                  "DIALOGUE_THINK_TOKENS_SMALL": "100"}), 9000)

    def test_invalid_falls_back_to_default(self):
        self.assertEqual(
            self._headroom(True, {"DIALOGUE_THINK_TOKENS_SMALL": "abc"}), 2048)


class TestResolveMaxTokensThinking(unittest.TestCase):
    """_resolve_max_tokens must give reasoning models the adjustable headroom."""

    def _resolve(self, brain, env):
        from gui.tabs.dialogue_tab import DialogueWorker
        with _EnvPatch(**env):
            return DialogueWorker._resolve_max_tokens(brain)

    def test_reasoning_small_brain_gets_headroom(self):
        # A small-class reasoning brain (27B Bonsai on CPU) must get >= the
        # thinking reserve so it can think AND answer, not an empty reply.
        brain = SmallBrainFake(
            "D:/llama.cpp/models/Bonsai-27B-GGUF/Bonsai-27B-Q1_0.gguf",
            context_length=32768)
        budget = self._resolve(brain, {"DIALOGUE_THINK_TOKENS_SMALL": "6144"})
        self.assertGreaterEqual(budget, 6144)

    def test_non_reasoning_small_brain_not_inflated(self):
        # A plain small model keeps its scaled budget (ctx//8 = 4096), with NO
        # thinking headroom added — proving the reserve only applies to
        # reasoning models.
        brain = SmallBrainFake(
            "D:/llama.cpp/models/gemma-3-1B-it-QAT-GGUF/gemma-3-1B-it-QAT-Q4_0.gguf",
            context_length=32768)
        budget = self._resolve(brain, {})
        self.assertEqual(budget, 4096)

    def test_reasoning_small_brain_default_headroom(self):
        # With no override, a reasoning small brain still gets the default 2048
        # reserve; combined with the 4096 scaled budget the result is >= 4096.
        brain = SmallBrainFake(
            "D:/llama.cpp/models/Bonsai-27B-GGUF/Bonsai-27B-Q1_0.gguf",
            context_length=32768)
        budget = self._resolve(brain, {})
        self.assertGreaterEqual(budget, 4096)

    def test_big_reasoning_brain_gets_headroom(self):
        brain = BigBrainFake(
            "D:/llama.cpp/models/GLM-4.7-Flash-REAP-23B-A3B-UD-Q3_K_XL.gguf",
            context_length=64768)
        budget = self._resolve(brain, {"DIALOGUE_THINK_TOKENS_BIG": "8192"})
        self.assertGreaterEqual(budget, 8192)


if __name__ == "__main__":
    unittest.main()
