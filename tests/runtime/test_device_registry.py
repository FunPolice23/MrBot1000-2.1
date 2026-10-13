"""Tests for the device registry (detection, policy, allocation)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.runtime import device_registry as dr


def _dev(dev_id, kind, mem, idx=0, name="Card", cores=0, cap=""):
    return dr.ComputeDevice(id=dev_id, kind=kind, index=idx, name=name,
                            memory_gb=mem, cores=cores, compute_capability=cap)


class TestCapability(unittest.TestCase):
    def test_gpu_classes_by_vram(self):
        self.assertEqual(_dev("a", "gpu", 16).capability_class(), "big")
        self.assertEqual(_dev("a", "gpu", 12).capability_class(), "big")   # boundary
        self.assertEqual(_dev("a", "gpu", 6).capability_class(), "small")
        self.assertEqual(_dev("a", "gpu", 4).capability_class(), "small")  # boundary
        self.assertEqual(_dev("a", "gpu", 3).capability_class(), "none")

    def test_cpu_classes_by_ram_and_cores(self):
        # Big needs lots of RAM AND many cores.
        self.assertEqual(_dev("cpu", "cpu", 48, cores=16).capability_class(), "big")
        self.assertEqual(_dev("cpu", "cpu", 48, cores=4).capability_class(), "small")
        # 8 GB with many cores is still small-class (>= 4 GB, >= 4 cores).
        self.assertEqual(_dev("cpu", "cpu", 8, cores=16).capability_class(), "small")
        # Too little RAM or too few cores -> unsuitable.
        self.assertEqual(_dev("cpu", "cpu", 3, cores=16).capability_class(), "none")
        self.assertEqual(_dev("cpu", "cpu", 48, cores=2).capability_class(), "none")


class TestResolveAssignments(unittest.TestCase):
    def setUp(self):
        self.big = _dev("GPU-BIG", "gpu", 16, idx=0, name="Big Card")
        self.small = _dev("GPU-SMALL", "gpu", 6, idx=1, name="Small Card")
        self.cpu = _dev("cpu", "cpu", 48, idx=-1, name="CPU", cores=12)
        self.devices = [self.big, self.small, self.cpu]

    def test_default_all_enabled_auto(self):
        asgs = dr.resolve_assignments(self.devices, dr.DevicePolicy())
        roles = {a.device.id: a.role for a in asgs}
        self.assertEqual(roles["GPU-BIG"], "big")
        self.assertEqual(roles["GPU-SMALL"], "small")
        self.assertEqual(roles["cpu"], "big")

    def test_disable_device(self):
        pol = dr.DevicePolicy(enabled={"GPU-SMALL": False})
        asgs = dr.resolve_assignments(self.devices, pol)
        a = next(a for a in asgs if a.device.id == "GPU-SMALL")
        self.assertFalse(a.enabled)
        self.assertEqual(a.role, "none")
        self.assertIn("disabled", a.reason)

    def test_cannot_promote_small_gpu_to_big(self):
        pol = dr.DevicePolicy(role={"GPU-SMALL": "big"})
        asgs = dr.resolve_assignments(self.devices, pol)
        a = next(a for a in asgs if a.device.id == "GPU-SMALL")
        self.assertEqual(a.role, "small")   # stays small, override rejected
        self.assertTrue(a.auto)
        self.assertIn("cannot host big", a.reason)

    def test_can_downgrade_cpu_to_small(self):
        pol = dr.DevicePolicy(role={"cpu": "small"})
        asgs = dr.resolve_assignments(self.devices, pol)
        a = next(a for a in asgs if a.device.id == "cpu")
        self.assertEqual(a.role, "small")
        self.assertFalse(a.auto)   # explicit override


class TestBrainPlacements(unittest.TestCase):
    def setUp(self):
        self.big = _dev("GPU-BIG", "gpu", 16, idx=0, name="Big Card")
        self.small = _dev("GPU-SMALL", "gpu", 6, idx=1, name="Small Card")
        self.cpu = _dev("cpu", "cpu", 48, idx=-1, name="CPU", cores=12)
        self.devices = [self.big, self.small, self.cpu]

    def test_gpus_preferred_over_cpu_within_class(self):
        asgs = dr.resolve_assignments(self.devices, dr.DevicePolicy())
        placements = dr.brain_placements(asgs, base_port=1234)
        # First big-class placement must be the GPU, not the CPU.
        first_big = next(p for p in placements if p["role"] == "big")
        self.assertTrue(first_big["kind"] == "gpu")

    def test_ports_sequential_unique(self):
        asgs = dr.resolve_assignments(self.devices, dr.DevicePolicy())
        placements = dr.brain_placements(asgs, base_port=1300)
        ports = [p["port"] for p in placements]
        self.assertEqual(len(ports), len(set(ports)))
        self.assertEqual(ports, sorted(ports))
        self.assertEqual(ports[0], 1300)

    def test_single_gpu_plus_cpu(self):
        # Disable the small GPU -> Big on the 16GB card, 2nd brain on CPU.
        pol = dr.DevicePolicy(enabled={"GPU-SMALL": False})
        asgs = dr.resolve_assignments(self.devices, pol)
        placements = dr.brain_placements(asgs)
        self.assertEqual(len(placements), 2)
        self.assertEqual(placements[0]["role"], "big")
        self.assertTrue(placements[0]["kind"] == "gpu")
        self.assertTrue(placements[1]["is_cpu"])

    def test_only_one_device_enabled(self):
        pol = dr.DevicePolicy(enabled={"GPU-SMALL": False, "cpu": False})
        asgs = dr.resolve_assignments(self.devices, pol)
        placements = dr.brain_placements(asgs)
        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0]["role"], "big")


class TestPersistence(unittest.TestCase):
    def test_policy_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = dr.DevicePolicy(
                enabled={"GPU-BIG": True, "GPU-SMALL": False},
                role={"cpu": "small"})
            self.assertTrue(dr.save_policy(pol, root=tmp))
            loaded = dr.load_policy(root=tmp)
            self.assertTrue(loaded.enabled["GPU-BIG"])
            self.assertFalse(loaded.enabled["GPU-SMALL"])
            self.assertEqual(loaded.role["cpu"], "small")

    def test_save_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"providers": [{"name": "ollama"}]}')
            dr.save_policy(dr.DevicePolicy(enabled={"x": True}), root=tmp)
            import json
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("providers", data)           # untouched
            self.assertTrue(data["devices"]["enabled"]["x"])

    def test_missing_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            pol = dr.load_policy(root=tmp)
            self.assertEqual(pol.enabled, {})
            self.assertEqual(pol.role, {})

    def test_corrupt_settings_json_does_not_block_future_saves(self):
        # v2.1.55 (ARCH-ENG-055): a corrupt settings.json (here: NUL bytes, the
        # exact corruption this box hit) made save_policy return False forever —
        # the merge-read raised inside the same try as the write — so per-device
        # settings silently never persisted again. save must quarantine the bad
        # file and write a clean policy.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)
            self.assertTrue(dr.save_policy(dr.DevicePolicy(enabled={"x": True}),
                                           root=tmp))
            loaded = dr.load_policy(root=tmp)
            self.assertTrue(loaded.enabled["x"])
            # The bad file is preserved for inspection, never deleted.
            self.assertTrue(any(n.startswith("settings.json.corrupt-")
                                for n in os.listdir(tmp)))

    def test_truncated_json_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"providers": [{"name": "oll')
            self.assertTrue(dr.save_policy(dr.DevicePolicy(role={"cpu": "small"}),
                                           root=tmp))
            self.assertEqual(dr.load_policy(root=tmp).role["cpu"], "small")

    def test_save_is_atomic_no_partial_file_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            dr.save_policy(dr.DevicePolicy(enabled={"a": True}), root=tmp)
            leftovers = [n for n in os.listdir(tmp) if ".tmp-" in n]
            self.assertEqual(leftovers, [])


class TestDetection(unittest.TestCase):
    def test_detect_devices_never_raises(self):
        devs = dr.detect_devices(include_cpu=True)
        self.assertIsInstance(devs, list)
        # The CPU pool is always present when requested.
        self.assertTrue(any(d.is_cpu for d in devs))

    def test_detect_without_cpu(self):
        devs = dr.detect_devices(include_cpu=False)
        self.assertFalse(any(d.is_cpu for d in devs))


if __name__ == "__main__":
    unittest.main()
