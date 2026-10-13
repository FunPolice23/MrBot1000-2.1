"""mmproj auto-detect must match the projector to the SELECTED model.

Regression for the "big brain caught an error / didn't finish loading" bug: the
Auto button took ``sorted(folder.glob('mmproj*.gguf'))[0]`` — the first
projector alphabetically — regardless of which model was selected. With several
projectors in the models folder it always picked ``mmproj-gemma-4-26B-...``, so
a GLM-4.7-Flash model was launched with a gemma-4-26B vision projector. llama.cpp
rejects that mismatch at startup and the visible llama-server terminal aborts
silently (no OS crash, no log file), so the operator only sees "the terminal
just exited."

``DualBrainControl._mmproj_core`` reduces a model or projector filename to its
shared identity (strip ``mmproj-`` prefix + trailing quant/format tag);
``_token_related`` matches model↔projector as identical, or a prefix/suffix of
one another. If nothing matches, the field is left EMPTY (text-only) — never an
unrelated projector.
"""
import pytest

from gui.widgets.dual_brain_control import DualBrainControl as C


class TestMmprojCore:
    def test_strips_mmproj_prefix_and_quant(self):
        assert C._mmproj_core("mmproj-gemma-4-26B-A4B-it-BF16") == "gemma-4-26B-A4B-it"
        assert C._mmproj_core("gemma-4-26B-A4B-it-Q4_K_M") == "gemma-4-26B-A4B-it"

    def test_model_and_projector_collapse_to_same_core(self):
        assert (C._mmproj_core("gemma-4-26B-A4B-it-Q4_K_M")
                == C._mmproj_core("mmproj-gemma-4-26B-A4B-it-BF16"))

    def test_strips_various_quant_tokens(self):
        assert C._mmproj_core("Qwen3.8-27B-Q4_K_M") == "Qwen3.8-27B"
        assert C._mmproj_core("mmproj-Qwen3.8-27B-BF16") == "Qwen3.8-27B"
        assert C._mmproj_core("Llama-3.2-3B-Instruct.Q6_K") == "Llama-3.2-3B-Instruct"
        assert C._mmproj_core("Ternary-Bonsai-27B-Q2_g64") == "Ternary-Bonsai-27B"


class TestMmprojMatching:
    def _match(self, model, proj):
        mc = C._mmproj_core(model)
        pc = C._mmproj_core(proj)
        return mc == pc or C._token_related(mc.split("-"), pc.split("-"))

    @pytest.mark.parametrize("model,proj", [
        # The exact reported bug: GLM must NOT match a gemma projector.
        ("GLM-4.7-Flash-REAP-23B-A3B-UD-Q3_K_XL", "mmproj-gemma-4-26B-A4B-it-BF16"),
        ("Llama-3.2-3B-Instruct.Q6_K", "mmproj-gemma-4-26B-A4B-it-BF16"),
        # Different size / family / model must NOT match.
        ("gemma-4-26B-A4B-it-Q4_K_M", "mmproj-gemma-4-12B-it-BF16"),
        ("Qwen3.8-27B-Q4_K_M", "mmproj-Qwen3.5-9B-BF16"),
        ("gemma-4-26B-A4B-it-Q4_K_M", "mmproj-Qwen3.8-27B-BF16"),
        ("Ministral-3-14B-Instruct-2512-Q5_K_M",
         "mmproj-Ministral-3-3B-Instruct-2512-F16"),
    ])
    def test_non_matching_pairs_reject(self, model, proj):
        assert not self._match(model, proj)

    @pytest.mark.parametrize("model,proj", [
        ("gemma-4-26B-A4B-it-Q4_K_M", "mmproj-gemma-4-26B-A4B-it-BF16"),
        ("Qwen3.8-27B-Q4_K_M", "mmproj-Qwen3.8-27B-BF16"),
        ("Qwen3.5-9B-BF16", "mmproj-Qwen3.5-9B-BF16"),
        ("gemma-4-12B-it-BF16", "mmproj-gemma-4-12B-it-QAT-BF16"),   # -QAT variant
        ("Ternary-Bonsai-27B-Q2_g64", "mmproj-Bonsai-27B-BF16"),     # brand prefix
    ])
    def test_matching_pairs_accept(self, model, proj):
        assert self._match(model, proj)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
