"""Tests for the hardware→brain allocation planner."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.runtime import hardware_plan as hp


def _fake_gpus(manager, specs):
    """Install fake GPUInfo objects on a ProviderManager without probing."""
    from agents.providers.provider_manager import GPUInfo
    gpus = [GPUInfo(index=i, name=n, memory_total_mb=mb, memory_used_mb=0,
                    memory_free_mb=mb, compute_capability=cap)
            for (i, n, mb, cap) in specs]
    manager._gpus = gpus
    manager._detected = True
    return gpus


class TestClassify(unittest.TestCase):
    def test_big_small_none_thresholds(self):
        self.assertEqual(hp._classify(16.0), "big")
        self.assertEqual(hp._classify(12.0), "big")   # boundary is inclusive
        self.assertEqual(hp._classify(6.0), "small")
        self.assertEqual(hp._classify(4.0), "small")  # boundary inclusive
        self.assertEqual(hp._classify(3.9), "none")


class TestBrainPlan(unittest.TestCase):
    def setUp(self):
        from agents.providers.provider_manager import ProviderManager
        self.pm = ProviderManager.instance()
        # snapshot/restore the singleton's detected state
        self._prev_gpus = getattr(self.pm, "_gpus", None)
        self._prev_detected = getattr(self.pm, "_detected", None)

    def tearDown(self):
        self.pm._gpus = self._prev_gpus
        self.pm._detected = self._prev_detected

    def test_two_gpus_assign_by_vram(self):
        # 5060 Ti 16GB + 1660 Super 6GB -> big on the 16GB, small on the 6GB,
        # regardless of PCI index order.
        _fake_gpus(self.pm, [
            (1, "GTX 1660 SUPER", 6144, "7.5"),
            (0, "RTX 5060 Ti", 16311, "12.0"),
        ])
        plan = hp.build_brain_plan(cpu_enabled=False)
        big = plan.big_brain()
        small = plan.small_brain()
        self.assertIsNotNone(big)
        self.assertIsNotNone(small)
        self.assertEqual(big.target.index, 0)      # 5060 Ti wins by VRAM
        self.assertEqual(big.target.brain_class, "big")
        self.assertEqual(small.target.index, 1)    # 1660 Super is the small
        self.assertEqual(small.target.brain_class, "small")
        self.assertNotEqual(big.port, small.port)
        # CPU brain not created when disabled
        self.assertFalse(any(b.is_cpu for b in plan.brains))

    def test_single_gpu_falls_back_to_cpu_when_enabled(self):
        _fake_gpus(self.pm, [(0, "RTX 5060 Ti", 16311, "12.0")])
        plan = hp.build_brain_plan(cpu_enabled=True)
        self.assertIsNotNone(plan.big_brain())
        small = plan.small_brain()
        # On this box the CPU pool has enough RAM/cores, so Small lands on CPU.
        if small is not None:
            self.assertTrue(small.is_cpu)
            self.assertEqual(small.target.kind, "cpu")

    def test_no_gpu_yields_no_brains(self):
        _fake_gpus(self.pm, [])
        plan = hp.build_brain_plan(cpu_enabled=False)
        self.assertEqual(plan.brains, [])
        self.assertTrue(any("No GPU" in n for n in plan.notes))

    def test_ports_are_sequential_and_unique(self):
        _fake_gpus(self.pm, [
            (0, "A100", 80000, "8.0"),
            (1, "3090", 24576, "8.6"),
            (2, "1660", 6144, "7.5"),
        ])
        plan = hp.build_brain_plan(cpu_enabled=False, base_port=1300)
        ports = [b.port for b in plan.brains]
        self.assertEqual(len(ports), len(set(ports)), "ports must be unique")
        self.assertEqual(ports, sorted(ports), "ports assigned in order")
        # Three GPUs -> big + small + one extra
        self.assertEqual(len(plan.brains), 3)

    def test_low_vram_gpu_skipped(self):
        _fake_gpus(self.pm, [
            (0, "RTX 5060 Ti", 16311, "12.0"),
            (1, "Tiny", 2048, "7.5"),   # 2 GB -> below small threshold
        ])
        plan = hp.build_brain_plan(cpu_enabled=False)
        # Only the big GPU is placed; the 2 GB card is noted as skipped.
        self.assertEqual(len(plan.brains), 1)
        self.assertTrue(any("too little VRAM" in n for n in plan.notes))

    def test_format_is_readable(self):
        _fake_gpus(self.pm, [(0, "RTX 5060 Ti", 16311, "12.0"),
                             (1, "GTX 1660 SUPER", 6144, "7.5")])
        plan = hp.build_brain_plan(cpu_enabled=False)
        text = hp.format_brain_plan(plan)
        self.assertIn("Big Brain", text)
        self.assertIn("Small Brain", text)


class TestCpuDetection(unittest.TestCase):
    def test_cpu_target_never_raises(self):
        t = hp.detect_cpu_target()
        self.assertEqual(t.kind, "cpu")
        self.assertEqual(t.index, -1)
        self.assertGreaterEqual(t.vram_gb, 0.0)


if __name__ == "__main__":
    unittest.main()
