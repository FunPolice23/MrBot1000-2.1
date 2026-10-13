"""Phase G4 — per-model recommended settings resolver (ARCH-ENG-095).

recommend() joins family detection + live MTP detection. MTP is reported True
only when the model actually carries an MTP head; unknown families fall back to
safe generic defaults. Never raises / never fabricates.
"""
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

_MTP_MODEL = r"D:/llama.cpp/models/Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf"   # has nextn
_NO_MTP_MODEL = r"D:/llama.cpp/models/GLM-4.7-Flash-REAP-23B-A3B-UD-Q3_K_XL.gguf"  # none
_GEMMA = r"D:/llama.cpp/gemma-4-12b-it-UD-Q4_K_XL.gguf"  # dense-ish, no mtp


class TestRecommend(unittest.TestCase):
    def test_unknown_path_safe_defaults(self):
        from agents.providers.model_recommendations import recommend
        r = recommend("N:/does/not/exist.gguf")
        # A path that can't be read yields safe generic values (never raises,
        # never fabricates an MTP capability).
        self.assertFalse(r["mtp"])
        self.assertFalse(r["mtp_head_present"])
        self.assertGreaterEqual(r["context"], 2048)
        self.assertIn(r["family"], ("unknown", "llama"))

    def test_mtp_reported_only_when_head_present(self):
        if not (os.path.exists(_MTP_MODEL) and os.path.exists(_NO_MTP_MODEL)):
            self.skipTest("models not present")
        from agents.providers.model_recommendations import recommend
        # A model with an MTP head in an MTP-typical family -> mtp True.
        r_mtp = recommend(_MTP_MODEL)
        self.assertTrue(r_mtp["mtp_head_present"])
        # GLM (no head) -> mtp False even though it's a capable family.
        r_glm = recommend(_NO_MTP_MODEL)
        self.assertFalse(r_glm["mtp"])
        self.assertEqual(r_glm["spec_draft_n_max"], 0)

    def test_dense_gemma_mtp_off(self):
        if not os.path.exists(_GEMMA):
            self.skipTest("gemma not present")
        from agents.providers.model_recommendations import recommend
        r = recommend(_GEMMA)
        self.assertFalse(r["mtp"])

    def test_all_families_have_required_keys(self):
        from agents.providers.model_recommendations import RECOMMENDATIONS
        for fam, rec in RECOMMENDATIONS.items():
            for key in ("context", "gpu_layers", "kv_cache", "flash_attn",
                        "mtp", "spec_draft_n_max", "notes"):
                self.assertIn(key, rec, f"{fam} missing {key}")

    def test_summary_is_readable(self):
        from agents.providers.model_recommendations import summary
        s = summary("N:/nope.gguf")
        self.assertIn("ctx", s)
        self.assertIn("MTP", s)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
