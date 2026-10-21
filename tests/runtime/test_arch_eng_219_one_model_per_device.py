"""ARCH-ENG-219 — one model per device, unless the device has >= 32 GB VRAM.

## The hole

`BrainRoster.to_placements()` de-duplicated devices, but only for AUTO-assigned
slots. Line 166 read:

    dev = by_id.get(slot.device_id) or _auto_device(slot, devices, taken)

`by_id.get()` returns a device **without consulting `taken`**. So an explicit
`slot.device_id` bypassed the check entirely, and two slots naming the same
device produced two placements for it.

This is the operator's rule rather than an inference: below roughly 32 GB of
VRAM a second resident model does not fit alongside the first, and llama.cpp
spills to system RAM — slow enough to look like a hang.

## The rule

    capacity(device) = 2  if device is a GPU with >= 32 GB VRAM else 1

CPU devices are excluded from the exemption regardless of `memory_gb`: on a CPU
pool that field is total system **RAM**, not VRAM, so a 64 GB-RAM machine must not
be read as able to host two models.

Capacity is **2, not unlimited**. A first draft tested only "is this device
already taken", so a third model fitted onto a 32 GB card — the predicate was
true, so the check never fired. The unit of the rule is a per-device budget.

## Rejections are recorded, not silent

A dropped slot that reports nothing is indistinguishable from one the operator
never configured. `last_rejected_placements` carries the reason, and the two
causes report DIFFERENTLY: a first draft emitted "below the 32 GB needed" for
both, so a third model refused from a 48 GB card was reported as having too
little VRAM — false, and it would send the operator to look at the wrong number.

`to_placements()` has no production caller yet, which is exactly why this is
fixed here rather than discovered later.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
ROSTER = REPO / "agents" / "runtime" / "brain_roster.py"


class _Dev:
    """Minimal stand-in for `ComputeDevice`."""

    def __init__(self, ident, gb, gpu=True, kind="gpu"):
        self.id = ident
        self.memory_gb = gb
        self.is_gpu = gpu
        self.kind = kind

    def label(self):
        return f"{self.kind.upper()}:{self.id} ({self.memory_gb:.0f}GB)"


def _run(devices, tiers):
    from agents.runtime.brain_roster import BrainRoster, BrainSlot
    slots = [BrainSlot(tier=t, device_id=devices[0].id, model=f"M{i}")
             for i, t in enumerate(tiers)]
    roster = BrainRoster(big=[s for s in slots if s.tier == "big"],
                         small=[s for s in slots if s.tier != "big"])
    placements = roster.to_placements(devices)
    return placements, getattr(roster, "last_rejected_placements", [])


class TestTheCapacityRule(unittest.TestCase):
    """ARCH-ENG-219 — the hardware rule."""

    def test_the_predicate(self):
        from agents.runtime.brain_roster import device_can_host_multiple_models

        cases = ((8, True, False), (24, True, False), (31.9, True, False),
                 (32, True, True), (48, True, True), (64, True, True))
        for gb, is_gpu, expected in cases:
            with self.subTest(gb=gb, is_gpu=is_gpu):
                self.assertIs(
                    device_can_host_multiple_models(_Dev("d", gb, gpu=is_gpu)),
                    expected,
                    f"{gb} GB (gpu={is_gpu}) should "
                    f"{'allow' if expected else 'refuse'} two resident models")

    def test_a_cpu_pool_never_qualifies_however_much_ram(self):
        """`memory_gb` is system RAM for a CPU device, not VRAM."""
        from agents.runtime.brain_roster import device_can_host_multiple_models

        self.assertFalse(
            device_can_host_multiple_models(_Dev("cpu0", 128, gpu=False,
                                                 kind="cpu")),
            "a 128 GB-RAM CPU pool was treated as able to host two models; "
            "that field is RAM, not VRAM")

    def test_the_threshold_is_32_gb(self):
        from agents.runtime.brain_roster import MULTI_MODEL_MIN_VRAM_GB
        self.assertEqual(MULTI_MODEL_MIN_VRAM_GB, 32.0)


class TestPlacementEnforcement(unittest.TestCase):
    """ARCH-ENG-219 — behaviour at the placement layer."""

    def test_one_model_per_device_below_the_threshold(self):
        placements, rejected = _run([_Dev("g", 24)], ["big", "small"])
        self.assertEqual(len(placements), 1)
        self.assertEqual(len(rejected), 1,
                         "a second model on a 24 GB card was not reported")

    def test_two_models_allowed_at_the_threshold(self):
        placements, rejected = _run([_Dev("g", 32)], ["big", "small"])
        self.assertEqual(len(placements), 2)
        self.assertEqual(rejected, [])

    def test_capacity_is_two_not_unlimited(self):
        """The bug a boolean test missed: three fitted on a 32 GB card."""
        placements, rejected = _run([_Dev("g", 32)], ["big", "small", "small"])
        self.assertEqual(len(placements), 2,
                         "three resident models were placed on a 32 GB card")
        self.assertEqual(len(rejected), 1)

    def test_capacity_holds_above_the_threshold_too(self):
        placements, rejected = _run([_Dev("g", 80)], ["big", "small", "small"])
        self.assertEqual(len(placements), 2)
        self.assertEqual(len(rejected), 1)

    def test_distinct_devices_are_unaffected(self):
        """The common case must not regress."""
        from agents.runtime.brain_roster import BrainRoster, BrainSlot
        devices = [_Dev("a", 8), _Dev("b", 24)]
        roster = BrainRoster(
            big=[BrainSlot(tier="big", device_id="a", model="MA")],
            small=[BrainSlot(tier="small", device_id="b", model="MB")])
        placements = roster.to_placements(devices)
        self.assertEqual(len(placements), 2)
        self.assertEqual(getattr(roster, "last_rejected_placements", []), [])
        self.assertEqual(len({p["port"] for p in placements}), 2,
                         "placements on distinct devices need distinct ports")

    def test_two_placements_get_distinct_ports(self):
        placements, _ = _run([_Dev("g", 48)], ["big", "small"])
        self.assertEqual(len({p["port"] for p in placements}), 2,
                         "two models on one device must not collide on a port")


class TestOnlyLocalModelsConsumeDeviceBudget(unittest.TestCase):
    """ARCH-ENG-219 -- the scoping an EXISTING test forced.

    `test_brain_roster.py::test_to_placements_3big_2small_unique_ports_cloud_
    no_port` asserts that a CLOUD slot may name a device a local brain already
    uses, and it is right. An OpenAI or Groq brain loads NO model onto the GPU and
    is placed with `port=None`; it consumes no VRAM. A first draft of this rule
    counted every slot against the device budget and refused that configuration
    -- breaking a test that had been correct all along.

    The rule is about RESIDENT LOCAL MODELS, which is what a VRAM figure
    describes. This test exists so the scoping cannot be tightened away.
    """

    def test_a_cloud_brain_may_share_a_device(self):
        from agents.runtime.brain_roster import BrainRoster, BrainSlot
        roster = BrainRoster(
            big=[BrainSlot(tier="big", device_id="gpu0", provider="llamacpp")],
            small=[BrainSlot(tier="small", device_id="gpu0", provider="groq",
                             model="m")])
        placements = roster.to_placements([_Dev("gpu0", 8)])
        self.assertEqual(
            len(placements), 2,
            "a cloud brain was refused a device already used by a local one; "
            "it loads no model there and consumes no VRAM")
        cloud = [p for p in placements if p["provider"] == "groq"][0]
        self.assertIsNone(cloud["port"], "a cloud brain is placed with no port")
        self.assertEqual(getattr(roster, "last_rejected_placements", []), [])

    def test_three_cloud_brains_do_not_exhaust_the_budget(self):
        from agents.runtime.brain_roster import BrainRoster, BrainSlot
        roster = BrainRoster(
            big=[BrainSlot(tier="big", device_id="gpu0", provider="openai"),
                 BrainSlot(tier="big", device_id="gpu0", provider="groq"),
                 BrainSlot(tier="big", device_id="gpu0", provider="openai",
                           model="gpt2")],
            small=[])
        placements = roster.to_placements([_Dev("gpu0", 8)])
        self.assertEqual(len(placements), 3,
                         "cloud slots were counted against the local VRAM "
                         "budget and started refusing each other")

    def test_a_local_and_a_cloud_brain_on_a_small_device(self):
        """One local model fits; the cloud brain is free."""
        from agents.runtime.brain_roster import BrainRoster, BrainSlot
        roster = BrainRoster(
            big=[BrainSlot(tier="big", device_id="gpu0", provider="llamacpp",
                           model="A")],
            small=[BrainSlot(tier="small", device_id="gpu0", provider="ollama",
                             model="B"),
                   BrainSlot(tier="small", device_id="gpu0", provider="groq",
                             model="C")])
        placements = roster.to_placements([_Dev("gpu0", 8)])
        self.assertEqual(len(placements), 2,
                         "the second LOCAL model on an 8 GB card was accepted")
        rejected = getattr(roster, "last_rejected_placements", [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["model"], "B",
                         "the wrong slot was rejected; the cloud slot must not "
                         "consume the local VRAM budget")


class TestRejectionsAreObservable(unittest.TestCase):
    """ARCH-ENG-219 — a silent drop is the defect this codebase keeps making."""

    def test_the_rejection_carries_the_model_and_the_reason(self):
        _, rejected = _run([_Dev("g", 24)], ["big", "small"])
        self.assertTrue(rejected)
        entry = rejected[0]
        self.assertEqual(entry["model"], "M1", "the rejected model is unnamed")
        self.assertIn("VRAM", entry["reason"])
        self.assertEqual(entry["device_id"], "g")

    def test_the_two_causes_report_differently(self):
        """A third model on a 48 GB card must not say 'not enough VRAM'."""
        _, too_small = _run([_Dev("g", 24)], ["big", "small"])
        _, at_capacity = _run([_Dev("g", 48)], ["big", "small", "small"])
        self.assertIn("below the 32 GB", too_small[0]["reason"])
        self.assertIn("capacity", at_capacity[0]["reason"])
        self.assertNotIn(
            "below the 32 GB", at_capacity[0]["reason"],
            "a device with 48 GB was reported as having too little VRAM; that "
            "is false and would send the operator to the wrong number")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-219 — each detector must be able to fail."""

    def test_the_predicate_rejects_a_real_device(self):
        from agents.runtime.brain_roster import device_can_host_multiple_models
        self.assertFalse(
            device_can_host_multiple_models(_Dev("d", 8)),
            "the predicate accepts every device, so the placement tests would "
            "pass regardless of the rule")

    def test_the_placement_scan_can_place_anything(self):
        """Otherwise every 'was rejected' assertion is vacuous."""
        placements, rejected = _run([_Dev("g", 48)], ["big", "small"])
        self.assertEqual(len(placements), 2)
        self.assertEqual(len(rejected), 0,
                         "the harness cannot produce a rejection, so the "
                         "rejection tests prove nothing")

    def test_the_removed_bypass_is_not_reintroduced(self):
        """`by_id.get(...)` must not come back without a `taken` check."""
        tree = ast.parse(ROSTER.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "to_placements")
        body = ast.unparse(fn)
        self.assertIn("_capacity_for", body,
                      "to_placements no longer enforces a per-device capacity")
        self.assertIn("last_rejected_placements", body,
                      "rejections are no longer recorded")

    def test_the_rule_is_recorded_in_the_source(self):
        self.assertIn("ARCH-ENG-219", ROSTER.read_text(encoding="utf-8"),
                      "the capacity rule needs a marker, or someone will "
                      "simplify it back to a boolean")