"""Phase 0 — brain_contention: the multi-model-per-device gate.

Targets BEHAVIOUR (a brain is / is not admitted, and the refusal names the
exhausted resource), so each test FAILS if the contention math is removed or
made permissive. Pure: synthetic devices + weight overrides, no GGUF, no Qt, no
subprocess.
"""
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

from agents.runtime.brain_contention import (
    can_add_brain,
    device_headroom,
    estimate_model_ram_gb,
    estimate_model_vram_gb,
    VRAM_SAFETY_MARGIN_GB,
)


class _Dev:
    """Minimal ComputeDevice stand-in (is_gpu/is_cpu/memory_gb/cores/name/id)."""

    def __init__(self, id, kind, memory_gb, cores=0, name=""):
        self.id = id
        self.kind = kind
        self.memory_gb = memory_gb
        self.cores = cores
        self.name = name or id

    @property
    def is_gpu(self):
        return self.kind == "gpu"

    @property
    def is_cpu(self):
        return self.kind == "cpu"


def _gpu(mem=16.0):
    return _Dev("gpu0", "gpu", mem, name="Test GPU")


def _cpu(mem=64.0, cores=16):
    return _Dev("cpu", "cpu", mem, cores=cores, name="CPU pool")


def _place(model="m", gpu_layers=None, ctx=8192, threads=4, device_id="gpu0",
           weights_gb=7.0, n_layer=None, kv_gb=1.0, is_cpu=False):
    return {"model": model, "gpu_layers": gpu_layers, "context": ctx,
            "threads": threads, "device_id": device_id, "is_cpu": is_cpu,
            "weights_gb": weights_gb, "n_layer": n_layer, "kv_gb": kv_gb}


class BrainContentionTest(unittest.TestCase):
    # ── footprint math ────────────────────────────────────────────────────
    def test_full_offload_vram_is_weights_plus_kv(self):
        # gpu_layers=None -> full offload -> all weights in VRAM + KV.
        v = estimate_model_vram_gb("m", None, 8192, weights_gb=7.0, kv_gb=1.0)
        self.assertAlmostEqual(v, 8.0)

    def test_partial_offload_ram_differs_from_full(self):
        # Full offload: no weights left in RAM. Partial (16/32 layers): half the
        # weights stay resident in system RAM.
        ram_full = estimate_model_ram_gb("m", None, 8192, weights_gb=7.0,
                                         n_layer=32, kv_gb=1.0)
        ram_partial = estimate_model_ram_gb("m", 16, 8192, weights_gb=7.0,
                                            n_layer=32, kv_gb=1.0)
        self.assertAlmostEqual(ram_full, 0.0)
        self.assertAlmostEqual(ram_partial, 3.5)
        self.assertNotAlmostEqual(ram_full, ram_partial)

    def test_cpu_only_keeps_weights_and_kv_in_ram(self):
        ram = estimate_model_ram_gb("m", 0, 8192, weights_gb=7.0, kv_gb=1.0)
        self.assertAlmostEqual(ram, 8.0)  # 7 weights + 1 KV, nothing offloaded

    def test_unknown_footprint_returns_none(self):
        self.assertIsNone(estimate_model_vram_gb("", None, 8192))
        self.assertIsNone(estimate_model_ram_gb("", 0, 8192))

    # ── the add-gate: VRAM ────────────────────────────────────────────────
    def test_two_mid_models_on_16gb_second_rejected_with_vram_reason(self):
        gpu, cpu = _gpu(16.0), _cpu(64.0, 16)
        cand = _place(weights_gb=7.0, kv_gb=1.0)  # 8.0 GB VRAM each
        ok1, _ = can_add_brain(gpu, [], cand, devices=[gpu, cpu])
        self.assertTrue(ok1, "the first 8 GB model fits a 16 GB card")
        ok2, reason = can_add_brain(gpu, [cand], cand, devices=[gpu, cpu])
        self.assertFalse(ok2, "a second 8 GB model does not fit (8+8 + margin > 16)")
        self.assertIn("VRAM", reason)

    # ── the add-gate: CPU cores ───────────────────────────────────────────
    def test_thread_sum_guard_rejects_over_subscribed_cores(self):
        cpu = _cpu(64.0, cores=6)
        # 3 brains x 6 threads = 18 on a 6-core box: the sum must be rejected.
        b1 = _place(gpu_layers=0, threads=6, device_id="cpu", is_cpu=True,
                    weights_gb=0.5, kv_gb=0.1)
        ok1, _ = can_add_brain(cpu, [], b1, devices=[cpu])
        self.assertTrue(ok1, "the first 6-thread brain uses all 6 cores (0 left, still fits)")
        b2 = dict(b1)
        ok2, reason = can_add_brain(cpu, [b1], b2, devices=[cpu])
        self.assertFalse(ok2, "a second 6-thread brain oversubscribes 6 cores")
        self.assertIn("core", reason.lower())

    # ── the add-gate: system RAM ──────────────────────────────────────────
    def test_ram_exhaustion_names_ram(self):
        cpu = _cpu(mem=8.0, cores=16)
        cand = _place(gpu_layers=0, threads=2, device_id="cpu", is_cpu=True,
                      weights_gb=7.0, kv_gb=1.0)  # 8 GB RAM on an 8 GB box
        ok, reason = can_add_brain(cpu, [], cand, devices=[cpu])
        self.assertFalse(ok)
        self.assertIn("RAM", reason)

    # ── fail-closed ───────────────────────────────────────────────────────
    def test_unknown_footprint_is_rejected_not_guessed(self):
        gpu, cpu = _gpu(16.0), _cpu(64.0, 16)
        cand = _place(model="", weights_gb=None)  # size unknowable
        ok, reason = can_add_brain(gpu, [], cand, devices=[gpu, cpu])
        self.assertFalse(ok)
        self.assertIn("footprint", reason.lower())

    # ── headroom reporting ────────────────────────────────────────────────
    def test_device_headroom_subtracts_committed_placements(self):
        gpu, cpu = _gpu(16.0), _cpu(64.0, 16)
        p = _place(weights_gb=7.0, kv_gb=1.0, threads=4)  # 8 GB VRAM, 0 RAM, 4 threads
        h = device_headroom(gpu, [p], devices=[gpu, cpu])
        self.assertAlmostEqual(h["vram_free_gb"], 8.0)
        self.assertEqual(h["cores_free"], 12)


if __name__ == "__main__":
    unittest.main()
