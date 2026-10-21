"""Phase 5 (data shape) — Speaker.brain_config populated in build_speakers.

Targets BEHAVIOUR: a roster-driven placement (BrainRoster.to_placements, which
carries provider/model) yields a Speaker with a BrainConfig for its slot's own
provider/model; a legacy device placement (no provider) leaves brain_config None
(back-compat). This is the data shape _brain_for consumes to seed extra-slot
adapters. Pure: synthetic devices/placements, no Qt/network.
"""
import sys
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.cognition.speaker_registry import build_speakers
from agents.runtime.brain_roster import BrainRoster, BrainSlot


class _Dev:
    def __init__(self, id, kind, index=0, memory_gb=0.0):
        self.id = id; self.kind = kind; self.index = index
        self.name = id; self.memory_gb = memory_gb

    @property
    def is_gpu(self):
        return self.kind == "gpu"

    @property
    def is_cpu(self):
        return self.kind == "cpu"

    def label(self):
        return self.id


def _placement(role, device_id, name, port, label="", provider=None, model="",
               is_cpu=False, index=0, kind="gpu", memory_gb=16.0):
    p = {"role": role, "device_id": device_id, "name": name, "port": port,
         "is_cpu": is_cpu, "label": label or name, "kind": kind,
         "index": index, "memory_gb": memory_gb}
    if provider is not None:            # roster-driven placements carry these
        p["provider"] = provider
        p["model"] = model
    return p


class SpeakerBrainConfigTest(unittest.TestCase):
    # ── back-compat: legacy placement -> brain_config None ─────────────────
    def test_legacy_placement_has_no_brain_config(self):
        speakers = build_speakers([_placement("big", "gpu0", "GPU", 1234)])
        self.assertIsNone(speakers[0].brain_config,
                          "a legacy device placement must not fabricate a config")

    # ── roster-driven: cloud slot -> its provider/model/endpoint ───────────
    def test_cloud_slot_brain_config(self):
        speakers = build_speakers([
            _placement("big", "gpu0", "GPU", 1234, provider="openai", model="gpt-x")])
        cfg = speakers[0].brain_config
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.model, "gpt-x")
        self.assertEqual(cfg.endpoint, "https://api.openai.com/v1")

    def test_local_slot_brain_config_loopback(self):
        speakers = build_speakers([
            _placement("big", "gpu0", "GPU", 1234, provider="llamacpp", model="local-y")])
        cfg = speakers[0].brain_config
        self.assertEqual(cfg.provider, "llamacpp")
        self.assertEqual(cfg.model, "local-y")
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:1234/v1")

    # ── end-to-end: roster -> to_placements -> build_speakers ──────────────
    def test_roster_to_placements_to_speakers(self):
        devices = [_Dev("gpu0", "gpu", 0, 16.0), _Dev("cpu", "cpu", -1, 32.0)]
        roster = BrainRoster(
            big=[BrainSlot(tier="big", provider="openai", model="gpt",
                           device_id="gpu0")],
            small=[BrainSlot(tier="small", provider="llamacpp", model="s",
                             device_id="cpu")])
        placements = roster.to_placements(devices)
        speakers = build_speakers(placements)
        big = next(s for s in speakers if s.is_primary_big)
        small = next(s for s in speakers if s.is_primary_small)
        self.assertEqual(big.brain_config.provider, "openai")
        self.assertEqual(big.brain_config.model, "gpt")
        self.assertEqual(small.brain_config.provider, "llamacpp")
        self.assertEqual(small.brain_config.model, "s")


if __name__ == "__main__":
    unittest.main()
