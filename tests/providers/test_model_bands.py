"""Model-size bands use explicit runtime parameter semantics."""

import unittest

from app.provider_models import ModelInfo, classify_model_band, infer_model_parameters
from agents.providers.huggingface_models import HuggingFaceGGUFModel
from agents.runtime.dual_brain import BrainRole, build_config


class TestModelBands(unittest.TestCase):
    def test_dense_boundaries(self):
        self.assertEqual(classify_model_band(1.0), "small")
        self.assertEqual(classify_model_band(3.9), "small")
        self.assertEqual(classify_model_band(4.0), "medium")
        self.assertEqual(classify_model_band(11.9), "medium")
        self.assertEqual(classify_model_band(12.0), "large")
        self.assertEqual(classify_model_band(35.0), "large")
        self.assertEqual(classify_model_band(35.1), "frontier")

    def test_moe_uses_active_parameters_only_when_explicit(self):
        self.assertEqual(
            classify_model_band(30.0, moe=True, active_params_billion=3.0),
            "small",
        )
        self.assertEqual(classify_model_band(30.0, moe=True), "large")

    def test_model_info_displays_total_and_active_sizes(self):
        model = ModelInfo(
            id="qwen-coder-30b-a3b",
            label="Qwen Coder",
            moe=True,
            params_billion=30.0,
            active_params_billion=3.0,
        )
        self.assertEqual(model.size_band, "small")
        self.assertEqual(model.size_label, "30B total / 3B active")
        self.assertIn("small", model.combo_text)
        self.assertIn("30B total / 3B active", model.tooltip)

    def test_unknown_size_is_explicit(self):
        self.assertEqual(classify_model_band(None), "unknown")
        self.assertEqual(ModelInfo(id="unknown", label="Unknown").size_band, "unknown")

    def test_parameter_inference_requires_explicit_notation(self):
        self.assertEqual(infer_model_parameters("Qwen-Coder-30B-A3B"), (30.0, 3.0))
        self.assertEqual(infer_model_parameters("llama-3.1-8b"), (8.0, None))
        self.assertEqual(infer_model_parameters("model-with-no-size"), (None, None))

    def test_huggingface_model_uses_same_band_contract(self):
        model = HuggingFaceGGUFModel(
            repo_id="demo/qwen-30b-a3b",
            title="Qwen",
            params_billion=30.0,
            active_params_billion=3.0,
            moe=True,
        )
        self.assertEqual(model.size_band, "small")
        self.assertEqual(model.size_label, "30B total / 3B active")

    def test_cpu_only_small_brain_gets_conservative_context_defaults(self):
        config = build_config(
            BrainRole.SMALL,
            {"SMALL_BRAIN_GPU_LAYERS": "0"},
        )
        self.assertEqual(config.context, 4096)
        self.assertEqual(config.batch, 256)

    def test_explicit_cpu_context_override_wins(self):
        config = build_config(
            BrainRole.SMALL,
            {"SMALL_BRAIN_GPU_LAYERS": "0", "SMALL_BRAIN_CONTEXT": "8192"},
        )
        self.assertEqual(config.context, 8192)


class TestCpuDecisionModelSelection(unittest.TestCase):
    """v2.1.50 (ARCH-ENG-050): CPU/RAM mode must never launch an oversized model.

    A big model loaded CPU-only (``--n-gpu-layers 0``) exceeds available RAM;
    llama-server loads, then dies right after the load banner with no tokens.
    The start path must substitute a fitting model (<= CPU_SMALL_MODEL_MAX_B)
    rather than warn-and-load the big one.
    """

    def test_oversized_model_is_rejected_for_cpu(self):
        from agents.runtime.dual_brain import (
            is_cpu_decision_model, estimate_model_size_b, CPU_SMALL_MODEL_MAX_B)
        # The real models this box tried to run on the CPU pool.
        for big in (
            "D:/llama.cpp/models/Bonsai-27B-GGUF/Bonsai-27B-Q1_0.gguf",
            "D:/llama.cpp/models/GLM-4.7-Flash-REAP-23B-A3B-UD-Q3_K_XL.gguf",
        ):
            self.assertGreater(estimate_model_size_b(big) or 0, CPU_SMALL_MODEL_MAX_B)
            self.assertFalse(is_cpu_decision_model(big))

    def test_small_model_is_accepted_for_cpu(self):
        from agents.runtime.dual_brain import is_cpu_decision_model
        self.assertTrue(is_cpu_decision_model(
            "D:/llama.cpp/models/gemma-3-1B-it-QAT-GGUF/gemma-3-1B-it-QAT-Q4_0.gguf"))

    def test_choose_prefers_smallest_eligible_over_big(self):
        from agents.runtime.dual_brain import (
            choose_cpu_decision_model, is_cpu_decision_model)
        candidates = [
            "D:/llama.cpp/models/Bonsai-27B-GGUF/Bonsai-27B-Q1_0.gguf",
            "D:/llama.cpp/models/gemma-3-1B-it-QAT-GGUF/gemma-3-1B-it-QAT-Q4_0.gguf",
            "D:/llama.cpp/models/Llama-3.2-3B-Instruct.Q6_K.gguf",
        ]
        chosen = choose_cpu_decision_model("", candidates)
        # Must pick a model that actually fits the CPU budget, never the 27B.
        self.assertTrue(chosen)
        self.assertTrue(is_cpu_decision_model(chosen))
        self.assertNotIn("27B", chosen)

    def test_configured_cpu_model_wins_when_eligible(self):
        from agents.runtime.dual_brain import (
            choose_cpu_decision_model, is_cpu_decision_model)
        configured = "D:/llama.cpp/models/LFM2.5-1.2B-Instruct-GGUF/LFM2.5-1.2B-Instruct-Q8_0.gguf"
        chosen = choose_cpu_decision_model(configured, [])
        self.assertEqual(chosen, configured)
        self.assertTrue(is_cpu_decision_model(chosen))


if __name__ == "__main__":
    unittest.main()