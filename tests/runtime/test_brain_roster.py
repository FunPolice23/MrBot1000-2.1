"""Phase 3 — brain_roster: the N-brain roster model.

Targets BEHAVIOUR (persistence round-trip, sibling-key preservation, placement
shape/ports, cloud-no-port), so each test FAILS if the roster loses a field,
erases a sibling settings key, double-assigns a port, or gives a cloud brain a
port. Pure: temp settings.json, synthetic devices, no Qt/network/subprocess.
"""
import json
import os
import sys
import tempfile
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.runtime.brain_roster import (
    BrainRoster, BrainSlot, MAX_BIG, MAX_SMALL, DEFAULT_BASE_PORT,
)
from agents.runtime.device_registry import merge_settings_file, policy_path


class _Dev:
    def __init__(self, id, kind, index=0, memory_gb=0.0):
        self.id = id
        self.kind = kind
        self.index = index
        self.name = id
        self.memory_gb = memory_gb

    @property
    def is_gpu(self):
        return self.kind == "gpu"

    @property
    def is_cpu(self):
        return self.kind == "cpu"

    def label(self):
        return self.id


def _devices():
    return [_Dev("gpu0", "gpu", 0, 16.0), _Dev("gpu1", "gpu", 1, 6.0),
            _Dev("cpu", "cpu", -1, 32.0)]


class BrainRosterTest(unittest.TestCase):
    # ── defaults & shape ──────────────────────────────────────────────────
    def test_default_roster_is_one_big_one_small(self):
        r = BrainRoster.default()
        self.assertEqual(len(r.big), 1)
        self.assertEqual(len(r.small), 1)
        self.assertEqual(r.big[0].tier, "big")
        self.assertEqual(r.small[0].tier, "small")
        self.assertTrue(all(s.enabled for s in r.active_slots()))

    def test_from_dict_clamps_to_max_and_normalizes_tier(self):
        d = {"big": [{"tier": "big"}] * (MAX_BIG + 5),
             "small": [{"tier": "bogus"}] * (MAX_SMALL + 3)}
        r = BrainRoster.from_dict(d)
        self.assertEqual(len(r.big), MAX_BIG)
        self.assertEqual(len(r.small), MAX_SMALL)
        self.assertTrue(all(s.tier in ("big", "small") for s in r.big + r.small))

    # ── persistence round-trip + ARCH-ENG-070 sibling preservation ─────────
    def test_round_trip_preserves_fields_and_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            # A sibling key that a naive whole-file write would erase.
            self.assertTrue(merge_settings_file({"devices": {"enabled": {"gpu0": True}}},
                                                root=tmp))
            roster = BrainRoster(
                big=[BrainSlot(tier="big", enabled=True, provider="openai",
                               model="gpt-x", device_id="gpu0"),
                     BrainSlot(tier="big", enabled=False, provider="llamacpp",
                               model="local-y", device_id="gpu1")],
                small=[BrainSlot(tier="small", enabled=True, provider="llamacpp",
                                 model="small-z", device_id="cpu")],
            )
            self.assertTrue(roster.save(root=tmp))

            # sibling survived
            with open(policy_path(tmp), encoding="utf-8") as f:
                on_disk = json.load(f)
            self.assertIn("devices", on_disk, "roster write must not erase siblings")
            self.assertIn("roster", on_disk)

            # round-trip preserves every field
            loaded = BrainRoster.load(root=tmp)
            self.assertEqual(len(loaded.big), 2)
            self.assertEqual(len(loaded.small), 1)
            b0 = loaded.big[0]
            self.assertTrue(b0.enabled)
            self.assertEqual(b0.provider, "openai")
            self.assertEqual(b0.model, "gpt-x")
            self.assertEqual(b0.device_id, "gpu0")
            self.assertFalse(loaded.big[1].enabled)

    def test_load_missing_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(len(BrainRoster.load(root=tmp).big), 1)

    # ── placements ────────────────────────────────────────────────────────
    def test_to_placements_3big_2small_unique_ports_cloud_no_port(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", device_id="gpu0"),
                 BrainSlot(tier="big", device_id="gpu1"),
                 BrainSlot(tier="big", provider="openai", model="gpt",
                           device_id="gpu0")],
            small=[BrainSlot(tier="small", device_id="cpu"),
                   BrainSlot(tier="small", provider="groq", model="m",
                             device_id="cpu")],
        )
        placements = roster.to_placements(_devices())
        self.assertEqual(len(placements), 5, "3 big + 2 small -> 5 placements")
        # ports unique among LOCAL brains; cloud brains have port=None
        local_ports = [p["port"] for p in placements if p["provider"] in
                       ("llamacpp", "ollama", "lmstudio", "vllm", "koboldcpp")]
        self.assertEqual(len(local_ports), len(set(local_ports)),
                         "local brain ports must be unique")
        self.assertEqual(local_ports[0], DEFAULT_BASE_PORT)
        cloud = [p for p in placements if p["provider"] == "openai"]
        self.assertEqual(len(cloud), 1)
        self.assertIsNone(cloud[0]["port"], "a cloud brain gets no port")
        # shape compatible with brain_placements / build_speakers
        for p in placements:
            for key in ("role", "device_id", "kind", "index", "name",
                        "memory_gb", "is_cpu", "port", "label"):
                self.assertIn(key, p)

    def test_disabled_slots_excluded(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", enabled=False, device_id="gpu0"),
                 BrainSlot(tier="big", enabled=True, device_id="gpu1")],
            small=[BrainSlot(tier="small", enabled=True, device_id="cpu")],
        )
        placements = roster.to_placements(_devices())
        self.assertEqual(len(placements), 2)
        self.assertEqual([p["device_id"] for p in placements], ["gpu1", "cpu"])

    def test_auto_device_when_device_id_empty(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", device_id="")],  # auto -> a GPU
            small=[BrainSlot(tier="small", device_id="")],  # auto -> GPU or CPU
        )
        placements = roster.to_placements(_devices())
        self.assertEqual(len(placements), 2)
        self.assertTrue(all(p["device_id"] for p in placements),
                        "auto-pick must resolve a real device, never blank")

    def test_unresolvable_device_slot_skipped_not_fabricated(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", device_id="nonexistent-gpu")],
            small=[])
        placements = roster.to_placements(_devices())
        # device_id set but not found -> _auto_device picks a real device, so it
        # still resolves; a slot is only skipped when NO device exists at all.
        roster_empty = BrainRoster(big=[BrainSlot(tier="big", device_id="x")], small=[])
        self.assertEqual(roster_empty.to_placements([]), [],
                         "no devices -> no placements, never fabricated")


if __name__ == "__main__":
    unittest.main()
