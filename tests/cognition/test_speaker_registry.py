"""Tests for the N-brain speaker registry (Phase 1)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.cognition.speaker_registry import (  # noqa: E402
    Speaker, build_speakers, speaker_for_slot, speaker_for_key,
    speaker_for_name, default_pingpong_order,
    BIG_TIER_NAME_POOL, SMALL_TIER_NAME_POOL,
)


def _placement(role, device_id, name, port, is_cpu=False, label=""):
    return {
        "role": role, "device_id": device_id, "kind": "cpu" if is_cpu else "gpu",
        "index": -1 if is_cpu else 0, "name": name, "memory_gb": 16,
        "is_cpu": is_cpu, "port": port, "label": label or name,
    }


def _clear_name_env():
    for k in list(os.environ):
        if k.startswith("BRAIN_SLOT") or k in ("BIG_BRAIN_NAME", "SMALL_BRAIN_NAME"):
            os.environ.pop(k, None)


class TestBuildSpeakers(unittest.TestCase):
    def setUp(self):
        _clear_name_env()

    def tearDown(self):
        _clear_name_env()

    def test_two_placements_edward_and_jacob(self):
        speakers = build_speakers([
            _placement("big", "gpu:A", "Big GPU", 1234),
            _placement("small", "gpu:B", "Small GPU", 1235),
        ])
        self.assertEqual(len(speakers), 2)
        self.assertEqual(speakers[0].name, "Edward Hurst")
        self.assertEqual(speakers[0].tier, "big")
        self.assertTrue(speakers[0].is_primary_big)
        self.assertEqual(speakers[0].key, "big_brain")
        self.assertEqual(speakers[1].name, "Jacob Stanley")
        self.assertEqual(speakers[1].tier, "small")
        self.assertTrue(speakers[1].is_primary_small)
        self.assertEqual(speakers[1].key, "small_brain")

    def test_four_placements_distinct_names_per_tier(self):
        # 2 big + 1 small + CPU (small) -> Edward, a 2nd big name, Jacob, a 2nd small.
        speakers = build_speakers([
            _placement("big", "gpu:A", "Big GPU", 1234),
            _placement("small", "gpu:B", "Small GPU", 1235),
            _placement("big", "gpu:C", "Extra Big", 1236),
            _placement("small", "cpu", "CPU", 1237, is_cpu=True),
        ])
        self.assertEqual(len(speakers), 4)
        names = [s.name for s in speakers]
        # No two speakers share a name.
        self.assertEqual(len(set(n.casefold() for n in names)), 4)
        self.assertEqual(speakers[0].name, "Edward Hurst")
        self.assertEqual(speakers[1].name, "Jacob Stanley")
        # Extra big + extra small come from the pools (distinct, non-famous).
        self.assertIn(speakers[2].name, BIG_TIER_NAME_POOL)
        self.assertIn(speakers[3].name, SMALL_TIER_NAME_POOL)
        self.assertEqual(speakers[2].tier, "big")
        self.assertEqual(speakers[3].tier, "small")
        self.assertEqual(speakers[2].key, "brain_slot2")
        self.assertEqual(speakers[3].key, "brain_slot3")

    def test_no_famous_person_names_in_pool(self):
        # The extra-name pools must not reuse famous historical names.
        famous = {"ada lovelace", "alan turing", "grace hopper", "nikola tesla",
                  "marie curie", "albert einstein", "isaac newton"}
        for n in BIG_TIER_NAME_POOL + SMALL_TIER_NAME_POOL:
            self.assertNotIn(n.casefold(), famous)

    def test_env_override_wins(self):
        os.environ["BRAIN_SLOT2_NAME"] = "Custom Name"
        speakers = build_speakers([
            _placement("big", "gpu:A", "A", 1234),
            _placement("small", "gpu:B", "B", 1235),
            _placement("big", "gpu:C", "C", 1236),
        ])
        self.assertEqual(speakers[2].name, "Custom Name")

    def test_legacy_big_small_name_env(self):
        os.environ["BIG_BRAIN_NAME"] = "My Big"
        os.environ["SMALL_BRAIN_NAME"] = "My Small"
        speakers = build_speakers([
            _placement("big", "gpu:A", "A", 1234),
            _placement("small", "gpu:B", "B", 1235),
        ])
        self.assertEqual(speakers[0].name, "My Big")
        self.assertEqual(speakers[1].name, "My Small")

    def test_slot_key_naming_wins_over_legacy(self):
        os.environ["BIG_BRAIN_NAME"] = "Legacy"
        os.environ["BRAIN_SLOT0_NAME"] = "Slot Wins"
        speakers = build_speakers([_placement("big", "gpu:A", "A", 1234)])
        self.assertEqual(speakers[0].name, "Slot Wins")

    def test_device_label_carried(self):
        speakers = build_speakers([
            _placement("big", "gpu:A", "A", 1234, label="RTX 5060 Ti (16 GB)"),
        ])
        self.assertEqual(speakers[0].device_label, "RTX 5060 Ti (16 GB)")

    def test_brains_mapped_by_slot(self):
        fake_big, fake_small = object(), object()
        speakers = build_speakers(
            [_placement("big", "gpu:A", "A", 1234),
             _placement("small", "gpu:B", "B", 1235)],
            brains={0: fake_big, 1: fake_small})
        self.assertIs(speakers[0].brain, fake_big)
        self.assertIs(speakers[1].brain, fake_small)

    def test_duplicate_names_disambiguated(self):
        # Operator sets the same name for two slots -> registry keeps them unique.
        os.environ["BRAIN_SLOT0_NAME"] = "Same"
        os.environ["BRAIN_SLOT2_NAME"] = "Same"
        speakers = build_speakers([
            _placement("big", "gpu:A", "A", 1234),
            _placement("small", "gpu:B", "B", 1235),
            _placement("big", "gpu:C", "C", 1236),
        ])
        names = [s.name for s in speakers]
        self.assertEqual(len(set(n.casefold() for n in names)), 3)

    def test_empty_placements(self):
        self.assertEqual(build_speakers([]), [])


class TestSpeakerLookups(unittest.TestCase):
    def setUp(self):
        _clear_name_env()
        self.speakers = build_speakers([
            _placement("big", "gpu:A", "A", 1234),
            _placement("small", "gpu:B", "B", 1235),
            _placement("big", "gpu:C", "C", 1236),
        ])

    def tearDown(self):
        _clear_name_env()

    def test_speaker_for_slot(self):
        self.assertIs(speaker_for_slot(self.speakers, 2), self.speakers[2])
        self.assertIsNone(speaker_for_slot(self.speakers, 99))

    def test_speaker_for_key(self):
        self.assertIs(speaker_for_key(self.speakers, "big_brain"), self.speakers[0])
        self.assertIs(speaker_for_key(self.speakers, "brain_slot2"), self.speakers[2])
        self.assertIsNone(speaker_for_key(self.speakers, "nope"))

    def test_speaker_for_name(self):
        self.assertIs(speaker_for_name(self.speakers, "Edward Hurst"), self.speakers[0])
        self.assertIsNone(speaker_for_name(self.speakers, "Nobody"))

    def test_default_pingpong_order(self):
        order = default_pingpong_order(self.speakers)
        self.assertEqual([s.slot for s in order], [0, 1])


if __name__ == "__main__":
    unittest.main()
