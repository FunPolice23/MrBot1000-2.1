"""ARCH-ENG-222 - the default context must fit the device it runs on.

## What was wrong

`ROLE_DEFAULTS` shipped `context: 64768` (big brain) and `32768` (small brain)
with `kv_cache: "f16"`, and `build_config` only ever reduced the context for
`gpu_layers == 0`. Nothing consulted the VRAM of the device the brain would
actually run on.

For an 8B-class model (36 layers, 8 KV heads, 128 head dim) at 64768 tokens in
f16:

    2 * 36 * 8 * 128 * 2 bytes * 64768 tokens  =  9.55 GB of KV cache

before a single weight is loaded. On the operator's GTX 1660 Super (6 GB) that
is not a slow context, it is a hard allocation failure: CUDA OOM, Windows TDR,
display-driver reset. On the 16 GB RTX 5060 Ti it leaves almost nothing for
weights.

## The contract these tests pin

1. The configured default is CLAMPED DOWN to what the device can hold.
2. An explicit `BIG_BRAIN_CONTEXT` / `SMALL_BRAIN_CONTEXT` in the env still wins
   untouched. A deliberate operator setting is not second-guessed; only the
   default is made safe.
3. The clamp never returns MORE than the default. It narrows a risky default;
   it does not expand one.
4. When the device cannot be determined, the default is left alone and the
   reason is returned -- not a guess.
5. A narrower KV type (`q8_0`, 1 byte) yields an equal-or-larger context than
   `f16`, because it halves KV memory. If this fails, the byte width is ignored.

## Why these tests inject devices

They do not touch the host's real GPUs. Every assertion here is about the
arithmetic and the precedence rules; none of it is about what hardware the
machine running the suite happens to have. `test_brain_prompt_hardware.py`
already burned on that mistake.
"""

import ast
import os
import pathlib
import struct
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
DUAL_BRAIN = REPO / "agents" / "runtime" / "dual_brain.py"


def _gpu(memory_gb, index=0):
    class _D:
        def __init__(self):
            self.id = f"gpu{index}"
            self.name = f"FAKE {memory_gb}GB"
            self.memory_gb = memory_gb
            self.index = index
            self.is_gpu = True
            self.is_cpu = False
            self.kind = "gpu"
            self.cores = 0

        def label(self):
            return f"{self.name} ({self.memory_gb:.0f} GB)"

    return _D()


class _PatchedDevices:
    """Swap `detect_devices` for a fixed list, then put it back."""

    def __init__(self, devices):
        self._devices = devices
        self._orig = None

    def __enter__(self):
        from agents.runtime import device_registry as dr
        self._orig = dr.detect_devices
        dr.detect_devices = lambda *a, **k: list(self._devices)
        return self

    def __exit__(self, *exc):
        from agents.runtime import device_registry as dr
        dr.detect_devices = self._orig
        return False


def _make_gguf(path, n_layer=36, kv_head=8, head_dim=128, embedding=4096,
               n_weights=1):
    """A real, minimal GGUF carrying the KV-shape keys `estimate_vram_gb` reads."""
    kv = b""

    def _u32(k, v):
        return (struct.pack("<Q", len(k)) + k + struct.pack("<I", 4)
                + struct.pack("<I", v))

    def _u64(k, v):
        return (struct.pack("<Q", len(k)) + k + struct.pack("<I", 10)
                + struct.pack("<Q", v))

    kv += _u32(b"general.architecture", 0)          # llama
    kv += _u32(b"llama.block_count", n_layer)
    kv += _u32(b"llama.attention.head_count", 32)
    kv += _u32(b"llama.attention.head_count_kv", kv_head)
    kv += _u32(b"llama.embedding_length", embedding)
    kv += _u64(b"llama.attention.key_length", head_dim)
    # Pad the file so weights_gb is realistic without writing gigabytes.
    with open(path, "wb") as f:
        f.write(b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0)
                + struct.pack("<Q", 7) + kv)
        f.write(b"\0" * (n_weights * 1024 * 1024))


class TestContextIsClampedToTheDevice(unittest.TestCase):
    def setUp(self):
        from agents.runtime import dual_brain as db
        self.db = db

    def test_the_6gb_card_no_longer_gets_a_32k_context(self):
        """The operator's actual low-end card."""
        with _PatchedDevices([_gpu(6.0, index=0)]):
            ctx, _why = self.db._vram_safe_context(32768, self.db.BrainRole.SMALL,
                                                   0, None)
        self.assertLess(ctx, 32768,
                        "a 6 GB card was given a 32k f16 context; that is the "
                        "CUDA-OOM/TDR case this ticket exists to close")

    def test_the_16gb_card_gets_more_than_the_6gb_card(self):
        with _PatchedDevices([_gpu(16.0, index=0)]):
            big, _ = self.db._vram_safe_context(32768, self.db.BrainRole.SMALL, 0, None)
        with _PatchedDevices([_gpu(6.0, index=0)]):
            small, _ = self.db._vram_safe_context(32768, self.db.BrainRole.SMALL, 0, None)
        self.assertGreater(big, small,
                           "a 16 GB card and a 6 GB card got the same context; "
                           "the clamp is not reading device VRAM")

    def test_a_measured_model_is_clamped_far_below_the_default(self):
        tmp = tempfile.mkdtemp(prefix="arch222_")
        path = os.path.join(tmp, "m.gguf")
        _make_gguf(path, n_weights=200)          # ~200 MB of weights
        with _PatchedDevices([_gpu(6.0, index=0)]):
            ctx, why = self.db._vram_safe_context(64768, self.db.BrainRole.BIG,
                                                  0, None, model_path=path)
        self.assertLess(ctx, 64768)
        self.assertIn("exceed", why.lower(),
                      "the reason must state that the fit failed, not just "
                      "that a number changed")

    def test_q8_0_kv_is_never_worse_than_f16(self):
        """A narrower KV type halves KV memory, so the context may grow."""
        tmp = tempfile.mkdtemp(prefix="arch222b_")
        path = os.path.join(tmp, "m.gguf")
        _make_gguf(path, n_weights=400)
        with _PatchedDevices([_gpu(8.0, index=0)]):
            f16, _ = self.db._vram_safe_context(64768, self.db.BrainRole.BIG, 0,
                                                None, model_path=path, kv_type_bytes=2)
            q8, _ = self.db._vram_safe_context(64768, self.db.BrainRole.BIG, 0,
                                               None, model_path=path, kv_type_bytes=1)
        self.assertGreaterEqual(q8, f16,
                                "q8_0 KV must allow at least the context f16 "
                                "allows; the byte width is being ignored")

    def test_the_clamp_never_EXPANDS_a_default(self):
        tmp = tempfile.mkdtemp(prefix="arch222c_")
        path = os.path.join(tmp, "m.gguf")
        _make_gguf(path, n_weights=1)
        with _PatchedDevices([_gpu(80.0, index=0)]):        # absurdly large card
            ctx, _ = self.db._vram_safe_context(4096, self.db.BrainRole.BIG, 0,
                                                None, model_path=path)
        self.assertEqual(ctx, 4096, "a clamp that expands is not a clamp")

    def test_ample_vram_leaves_the_default_alone(self):
        tmp = tempfile.mkdtemp(prefix="arch222d_")
        path = os.path.join(tmp, "m.gguf")
        _make_gguf(path, n_weights=1)
        with _PatchedDevices([_gpu(80.0, index=0)]):
            ctx, why = self.db._vram_safe_context(64768, self.db.BrainRole.BIG, 0,
                                                  None, model_path=path)
        self.assertEqual(ctx, 64768)
        self.assertIn("no clamp needed", why.lower(),
                      "when nothing was clamped the message must say so, not "
                      "report a clamp that did not happen")


class TestUndeterminableDeviceIsNotGuessed(unittest.TestCase):
    def setUp(self):
        from agents.runtime import dual_brain as db
        self.db = db

    def test_no_device_keeps_the_default_and_says_why(self):
        with _PatchedDevices([]):
            ctx, why = self.db._vram_safe_context(32768, self.db.BrainRole.SMALL, 0, None)
        self.assertEqual(ctx, 32768)
        self.assertIn("not detected", why.lower())

    def test_a_device_with_no_reported_vram_keeps_the_default(self):
        with _PatchedDevices([_gpu(0.0, index=0)]):
            ctx, why = self.db._vram_safe_context(32768, self.db.BrainRole.SMALL, 0, None)
        self.assertEqual(ctx, 32768)
        self.assertIn("no vram", why.lower())

    def test_detection_failure_keeps_the_default(self):
        from agents.runtime import device_registry as dr
        orig = dr.detect_devices

        def boom(*a, **k):
            raise RuntimeError("nvidia-smi exploded")

        dr.detect_devices = boom
        try:
            ctx, why = self.db._vram_safe_context(32768, self.db.BrainRole.SMALL, 0, None)
        finally:
            dr.detect_devices = orig
        self.assertEqual(ctx, 32768)
        self.assertIn("detection failed", why.lower())

    def test_a_missing_model_file_does_not_raise(self):
        with _PatchedDevices([_gpu(6.0, index=0)]):
            ctx, _ = self.db._vram_safe_context(64768, self.db.BrainRole.BIG, 0,
                                                None, model_path=r"D:\nope\gone.gguf")
        self.assertIsInstance(ctx, int)


class TestOperatorSettingStillWins(unittest.TestCase):
    """The clamp changes a DEFAULT. It must never override a decision."""

    def test_an_explicit_context_env_is_respected(self):
        from agents.runtime import dual_brain as db
        with _PatchedDevices([_gpu(6.0, index=0)]):
            cfg = db.build_config(db.BrainRole.SMALL,
                                  env={"SMALL_BRAIN_CONTEXT": "16384"})
        self.assertEqual(cfg.context, 16384,
                         "an explicit SMALL_BRAIN_CONTEXT was clamped away")

    def test_without_an_override_the_clamp_applies(self):
        from agents.runtime import dual_brain as db
        # `build_config` resolves the device by the ROLE DEFAULT index, not 0:
        # small defaults to device 1. Injecting a 6 GB card at index 0 while
        # asking about a role that targets device 1 means "device not found",
        # which correctly leaves the default alone -- so the fixture has to
        # match the role.
        idx = db.ROLE_DEFAULTS[db.BrainRole.SMALL]["device"]
        with _PatchedDevices([_gpu(6.0, index=idx)]):
            cfg = db.build_config(db.BrainRole.SMALL, env={})
        self.assertLess(cfg.context, db.ROLE_DEFAULTS[db.BrainRole.SMALL]["context"])

    def test_the_clamp_targets_the_roles_own_device_index(self):
        """A clamp computed against the wrong device would be worse than none."""
        from agents.runtime import dual_brain as db
        small_idx = db.ROLE_DEFAULTS[db.BrainRole.SMALL]["device"]
        big_idx = db.ROLE_DEFAULTS[db.BrainRole.BIG]["device"]
        # 6 GB where the small brain lives, 16 GB where the big brain lives.
        devices = [_gpu(6.0, index=small_idx), _gpu(16.0, index=big_idx)]
        with _PatchedDevices(devices):
            small = db.build_config(db.BrainRole.SMALL, env={})
            big = db.build_config(db.BrainRole.BIG, env={})
        self.assertGreater(big.context, small.context,
                           "the big brain (16 GB) got a smaller context than "
                           "the small brain on a 6 GB card")

    def test_cpu_only_still_gets_4096(self):
        from agents.runtime import dual_brain as db
        cfg = db.build_config(db.BrainRole.SMALL, env={"SMALL_BRAIN_GPU_LAYERS": "0"})
        self.assertEqual(cfg.context, 4096,
                         "the pre-existing cpu_only rule was replaced rather "
                         "than composed with")


class TestTheGuardCannotPassByReadingItself(unittest.TestCase):
    def test_the_synthetic_gguf_really_measures(self):
        """Otherwise every measured-model assertion above is vacuous."""
        from agents.providers.gguf_meta import estimate_vram_gb
        tmp = tempfile.mkdtemp(prefix="arch222e_")
        path = os.path.join(tmp, "m.gguf")
        _make_gguf(path, n_layer=36, kv_head=8, head_dim=128, n_weights=8)
        est = estimate_vram_gb(path, context=8192, kv_type_bytes=2)
        self.assertTrue(est["complete"],
                        f"synthetic GGUF did not yield a KV shape: {est}")
        self.assertEqual(est["n_layer"], 36)
        self.assertEqual(est["kv_head"], 8)
        self.assertEqual(est["head_dim"], 128)
        # 2*36*8*128*2*8192 = 1.21 GB
        self.assertAlmostEqual(est["kv_gb"], 1.21, delta=0.05,
                               msg=f"KV arithmetic wrong: {est['kv_gb']} GB")

    def test_the_injection_really_takes_effect(self):
        from agents.runtime import device_registry as dr
        orig = dr.detect_devices
        with _PatchedDevices([_gpu(6.0)]):
            self.assertIsNot(dr.detect_devices, orig)
            self.assertEqual(len(dr.detect_devices(include_cpu=False)), 1)
        self.assertIs(dr.detect_devices, orig, "the patch leaked")

    def test_build_config_actually_calls_the_clamp(self):
        """Not just defined -- reached. A helper nobody calls is not a fix."""
        body = ast.unparse(ast.parse(DUAL_BRAIN.read_text(encoding="utf-8")))
        fn = next(n for n in ast.walk(ast.parse(DUAL_BRAIN.read_text(encoding="utf-8")))
                  if isinstance(n, ast.FunctionDef) and n.name == "build_config")
        calls = [ast.unparse(c) for c in ast.walk(fn)
                 if isinstance(c, ast.Call)]
        self.assertTrue(any("_vram_safe_context" in c for c in calls),
                        "build_config no longer calls _vram_safe_context; the "
                        "clamp is defined but unreachable")

    def test_no_module_level_unconditional_clamp(self):
        """The clamp must not be applied to ROLE_DEFAULTS itself.

        `ROLE_DEFAULTS` is read by `default_role_settings()` (dual_brain.py:1249),
        which the UI shows. Editing the dict would make the Settings screen lie
        about the configured default. Only the built config may be clamped.
        """
        body = ast.unparse(ast.parse(DUAL_BRAIN.read_text(encoding="utf-8")))
        self.assertNotRegex(
            body, r'ROLE_DEFAULTS\s*\[[^\]]+\]\s*\[\s*["\']context["\']\s*\]\s*=',
            "ROLE_DEFAULTS was mutated in place; the UI would display a value "
            "that is no longer what the operator configured")


if __name__ == "__main__":
    unittest.main()