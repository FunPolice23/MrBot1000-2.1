"""ARCH-ENG-220 — a fully-offloaded GPU brain was estimated to cost zero RAM.

## The gap

`brain_contention.estimate_model_ram_gb` added the KV cache to system RAM only
when `gpu_layers == 0`:

    ram = fp["weights_gb"] * (1.0 - frac)
    if gpu_layers == 0:
        ram += fp["kv_gb"]

With full GPU offload the offload fraction is 1.0, so the function returned
**exactly 0.0**. The model claimed a GPU-resident brain consumes no system memory
at all — so `can_add_brain`'s "does adding this exhaust RAM?" check always
answered "no", and `device_headroom` reported `ram_used = 0` for every GPU brain.

## Why that hides pressure on exactly the constrained machines

A GPU-resident brain still costs host memory: the CUDA context and driver
allocations, staging buffers for moving tensors across PCIe, and allocator slack
the CUDA caching allocator does not return.

More importantly, **weights fitting in VRAM does not mean the brain fits in
VRAM**. The KV cache scales with context, and llama.cpp spills it to system RAM
rather than failing. A GTX 1660 Super with 6 GB can hold 3.5 GB of quantised
weights and still not have room for a 32k-context KV cache — so the brain looks
fine on the VRAM check and then quietly consumes host memory that no gate was
counting. The failure mode is a machine that suddenly cannot launch anything.

## The fix

`brain_ram_footprint_gb` charges three things to system RAM:

* non-offloaded weight layers resident in host memory
* KV that spilled because the device could not hold it
* a flat host overhead per brain

`estimate_kv_spill_gb` places weights first — they are what the device is for —
and spills whatever KV does not fit in the remainder. An **unknown** device size
yields no spill, because inventing a figure from an unknown card would be a guess
presented as a measurement.

CPU-only brains are deliberately unchanged: their existing weights+KV figure is
already correct, and there is a test asserting the two agree exactly.

`estimate_model_ram_gb` is retained unchanged for callers wanting weights-only.
"""

import unittest

from agents.runtime.brain_contention import (HOST_OVERHEAD_GB,
                                             brain_ram_footprint_gb,
                                             estimate_kv_spill_gb,
                                             estimate_model_ram_gb)

MODEL = "m.gguf"
W, LAYERS, CTX = 3.5, 32, 32768


def _fp(**kw):
    base = dict(weights_gb=W, n_layer=LAYERS)
    base.update(kw)
    return base


class TestAGpuBrainIsNoLongerFree(unittest.TestCase):
    """ARCH-ENG-220 — the core defect."""

    def test_a_fully_offloaded_brain_used_to_cost_nothing(self):
        """Documents the old behaviour so the fix cannot silently revert."""
        self.assertEqual(
            estimate_model_ram_gb(MODEL, 99, CTX, **_fp(kv_gb=1.0)),
            0.0,
            "estimate_model_ram_gb no longer returns 0.0 for a fully-offloaded "
            "GPU brain; if it has been given a host cost, this precondition "
            "for the comparison below no longer holds")

    def test_a_gpu_brain_now_costs_at_least_host_overhead(self):
        for card in (4, 6, 16, 80):
            with self.subTest(card=card):
                ram = brain_ram_footprint_gb(MODEL, 99, CTX, card,
                                             **_fp(kv_gb=1.0))
                self.assertIsNotNone(ram)
                self.assertGreaterEqual(
                    ram, HOST_OVERHEAD_GB,
                    "a GPU brain was priced at zero host memory again")

    def test_kv_that_fits_is_not_charged_twice(self):
        plenty = brain_ram_footprint_gb(MODEL, 99, CTX, 16, **_fp(kv_gb=1.0))
        self.assertAlmostEqual(plenty, HOST_OVERHEAD_GB, places=6,
                               msg="KV that fits in VRAM was charged to RAM "
                                   "as well as to VRAM")


class TestKvSpillIsChargedToRam(unittest.TestCase):
    """ARCH-ENG-220 — the operator's 6 GB card."""

    def test_spill_is_weights_first(self):
        """3.5 GB weights on a 6 GB card leaves 2.5 GB for a 4 GB KV."""
        self.assertAlmostEqual(estimate_kv_spill_gb(3.5, 4.0, 6.0), 1.5,
                               places=6)

    def test_no_spill_when_everything_fits(self):
        self.assertEqual(estimate_kv_spill_gb(3.5, 1.0, 16.0), 0.0)

    def test_spill_when_weights_alone_exceed_the_card(self):
        """All of the KV spills, because no VRAM is left for it.

        8 GB of weights on a 6 GB card leaves `room = max(0, 6 - 8) = 0`, so the
        entire 2 GB KV spills. The WEIGHT overflow is deliberately not counted
        here: that is a VRAM-capacity question the VRAM gate rejects on, and
        doubling it into the RAM figure would charge for the same shortfall
        twice. An earlier draft expected 4.0 (KV plus the weight excess) and was
        wrong -- the excess is not host RAM, it simply does not fit anywhere.
        """
        self.assertAlmostEqual(estimate_kv_spill_gb(8.0, 2.0, 6.0), 2.0,
                               places=6)

    def test_unknown_device_size_invents_no_spill(self):
        for unknown in (None, 0, -1):
            with self.subTest(value=unknown):
                self.assertEqual(estimate_kv_spill_gb(3.5, 4.0, unknown), 0.0,
                                 "a spill was derived from an unknown card "
                                 "size; that is a guess, not a measurement")

    def test_a_tight_card_costs_more_ram_than_a_roomy_one(self):
        tight = brain_ram_footprint_gb(MODEL, 99, CTX, 6, **_fp(kv_gb=4.0))
        roomy = brain_ram_footprint_gb(MODEL, 99, CTX, 16, **_fp(kv_gb=4.0))
        self.assertGreater(tight, roomy,
                           "a 6 GB card and a 16 GB card were priced the same; "
                           "the tight one spills KV to host memory")


class TestCpuBrainsAreUnchanged(unittest.TestCase):
    """ARCH-ENG-220 — the fix must not alter a correct calculation."""

    def test_cpu_only_figures_agree_exactly(self):
        for kv in (0.0, 1.0, 3.0):
            with self.subTest(kv=kv):
                old = estimate_model_ram_gb(MODEL, 0, CTX, **_fp(kv_gb=kv))
                new = brain_ram_footprint_gb(MODEL, 0, CTX, None,
                                             **_fp(kv_gb=kv))
                self.assertAlmostEqual(old, new, places=9)

    def test_a_cpu_brain_still_carries_its_weights_and_kv(self):
        ram = brain_ram_footprint_gb(MODEL, 0, CTX, None, **_fp(kv_gb=3.0))
        self.assertAlmostEqual(ram, W + 3.0, places=6)

    def test_partial_offload_counts_the_resident_weights(self):
        # gpu_layers=0 is handled above; here a fractional layer split.
        half = brain_ram_footprint_gb(MODEL, 1, CTX, None,
                                     **_fp(kv_gb=1.0))
        self.assertGreater(half, 0.0)
        self.assertLess(half, W + 1.0)


class TestUnknownFootprintStillFailsClosed(unittest.TestCase):
    """ARCH-ENG-220 — the estimate's None contract must survive."""

    def test_unknown_footprint_is_none(self):
        self.assertIsNone(brain_ram_footprint_gb("nonexistent-model-xyz",
                                                 99, CTX, 16))


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-220 — each detector must be able to fail."""

    def test_the_overhead_is_positive(self):
        self.assertGreater(HOST_OVERHEAD_GB, 0.0,
                           "a zero host overhead makes every GPU brain free "
                           "again and the gate blind")

    def test_a_known_footprint_resolves(self):
        self.assertIsNotNone(
            brain_ram_footprint_gb(MODEL, 99, CTX, 16, **_fp(kv_gb=1.0)),
            "a known model resolved to None, so the tests above would pass "
            "vacuously")