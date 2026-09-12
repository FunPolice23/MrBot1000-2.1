"""Model-size bands use explicit runtime parameter semantics."""

import unittest

from provider_models import ModelInfo, classify_model_band, infer_model_parameters
from agents.huggingface_models import HuggingFaceGGUFModel
from agents.dual_brain_runtime import BrainRole, build_config


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


if __name__ == "__main__":
    unittest.main()