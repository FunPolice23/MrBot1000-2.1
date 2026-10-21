"""Phase G1 — MTP capability detection + launch-flag wiring (ARCH-ENG-092).

- detect_mtp is True only for models carrying an MTP head (nextn/mtp/shared_head
  tensors); False (fail-safe) for models without one and on read failure.
- build_llama_command emits --spec-type draft-mtp (+ --spec-draft-n-max) only
  when spec_type is set; otherwise the command is unchanged.
"""
import os
import sys
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Real models on this box (verified to carry / lack an MTP head).
_MTP_MODEL = r"D:/llama.cpp/models/Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf"   # has nextn
_NO_MTP_MODEL = r"D:/llama.cpp/models/GLM-4.7-Flash-REAP-23B-A3B-UD-Q3_K_XL.gguf"  # none


class TestDetectMtp(unittest.TestCase):
    def test_capable_model_detected(self):
        if not os.path.exists(_MTP_MODEL):
            self.skipTest("MTP model not present")
        from agents.providers.model_capabilities import detect_mtp
        info = detect_mtp(_MTP_MODEL)
        self.assertTrue(info["supported"])
        self.assertGreater(info["head_tensors"], 0)

    def test_noncapable_model_not_detected(self):
        if not os.path.exists(_NO_MTP_MODEL):
            self.skipTest("GLM model not present")
        from agents.providers.model_capabilities import detect_mtp
        info = detect_mtp(_NO_MTP_MODEL)
        self.assertFalse(info["supported"])
        self.assertEqual(info["head_tensors"], 0)

    def test_missing_path_fails_safe(self):
        from agents.providers.model_capabilities import detect_mtp
        self.assertFalse(detect_mtp("")["supported"])
        self.assertFalse(detect_mtp("N:/does/not/exist.gguf")["supported"])

    def test_tooltip_mentions_availability(self):
        from agents.providers.model_capabilities import mtp_tooltip
        # No model / unreadable -> a clear non-availability message (never
        # claims MTP is available).
        self.assertIn("no model", mtp_tooltip("").lower())
        bad = mtp_tooltip("N:/nope.gguf").lower()
        self.assertTrue(("unavailable" in bad) or ("not a readable" in bad))


class TestCommandWiring(unittest.TestCase):
    def _cfg(self, **kw):
        from agents.runtime.dual_brain import BrainConfig, BrainRole
        base = dict(role=BrainRole.BIG, model="m.gguf", port=1234, context=8192,
                    threads=4, batch=512, device=0, gpu_layers=0)
        base.update(kw)
        return BrainConfig(**base)

    def test_flag_omitted_by_default(self):
        cmd = self._cfg().build_llama_command()
        self.assertNotIn("--spec-type", cmd)

    def test_flag_present_when_enabled(self):
        cmd = self._cfg(spec_type="draft-mtp",
                        spec_draft_n_max=4).build_llama_command()
        self.assertIn("--spec-type", cmd)
        self.assertIn("draft-mtp", cmd)
        i = cmd.index("--spec-draft-n-max")
        self.assertEqual(cmd[i + 1], "4")

    def test_flag_present_without_nmax(self):
        cmd = self._cfg(spec_type="draft-mtp").build_llama_command()
        self.assertIn("draft-mtp", cmd)
        self.assertNotIn("--spec-draft-n-max", cmd)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
