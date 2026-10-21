"""ARCH-ENG-315 — "Keep X in system RAM" checkboxes fire the right flag.

Operator-visible effect before the fix: checking **Keep KV cache in system
RAM** (or **Keep projector on CPU**) in the Providers & GPU advanced flags
wrote ``<PREFIX>_KV_OFFLOAD=true`` — which the parser read as *"KV offload
is on"*, so ``build_llama_command`` emitted **nothing**. The promised
``--no-kv-offload`` / ``--no-mmproj-offload`` flag never fired, and the
brain silently kept offloading to VRAM.

The contract now: the GUI phrase is the operator's wish; the parser inverts
it into the offload state the command builder speaks (``kv_offload=False``
-> ``--no-kv-offload``). ``true`` = keep in system RAM = flag emitted;
absent/removed = llama.cpp's own default = no flag.
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _config(role_env, prefix, **extra):
    from agents.runtime.dual_brain import DualBrainRuntime, BrainRole
    env = dict(role_env)
    env[f"{prefix}_PROVIDER"] = "llamacpp"
    env[f"{prefix}_MODEL"] = "fake-model.gguf"
    env.update({f"{prefix}_{k}": str(v) for k, v in extra.items()})
    role = BrainRole.SMALL if prefix == "SMALL_BRAIN" else BrainRole.BIG
    return DualBrainRuntime.from_env(dict(env)).config(role)


class TestKVOffloadCheckboxDrivesTheCommand(unittest.TestCase):
    def test_a_checked_box_emits_no_kv_offload(self):
        cfg = _config({}, "SMALL_BRAIN", KV_OFFLOAD="true")
        self.assertIs(cfg.kv_offload, False,
                      "checked 'Keep KV cache in system RAM' must parse as "
                      "offload disabled")
        self.assertIn("--no-kv-offload", cfg.build_llama_command())

    def test_an_unchecked_or_absent_box_fires_nothing(self):
        command = _config({}, "SMALL_BRAIN").build_llama_command()
        self.assertNotIn("--no-kv-offload", command)
        command2 = _config({}, "BIG_BRAIN", KV_OFFLOAD="false")
        self.assertNotIn("--no-kv-offload", command2.build_llama_command(),
                         "'false' means the operator does NOT keep it in "
                         "system RAM, so no flag")

    def test_projector_box_emits_no_mmproj_offload_with_a_projector(self):
        cfg = _config({}, "SMALL_BRAIN",
                      MMPROJ="D:/models/mmproj-fake.gguf",
                      MMPROJ_OFFLOAD="true")
        self.assertIs(cfg.mmproj_offload, False)
        command = cfg.build_llama_command()
        self.assertIn("--no-mmproj-offload", command)
        self.assertIn("--mmproj", command)

    def test_projector_box_without_a_projector_writes_nothing(self):
        cfg = _config({}, "SMALL_BRAIN", MMPROJ_OFFLOAD="true")
        self.assertNotIn("--no-mmproj-offload", cfg.build_llama_command())

    def test_the_cpu_moe_box_is_not_affected(self):
        """CPU_MOE is not phrased as a keep-in-RAM negation: checked must
        still map directly to --cpu-moe."""
        cfg = _config({}, "SMALL_BRAIN", CPU_MOE="true")
        self.assertIs(cfg.cpu_moe, True)
        self.assertIn("--cpu-moe", cfg.build_llama_command())


if __name__ == "__main__":
    unittest.main()
