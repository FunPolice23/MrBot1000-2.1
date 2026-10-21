"""Tests that brain prompts reflect the DETECTED hardware (N-brain).

## Why this file injects a registry instead of detecting live

This test used to call `dr.detect_devices()` and assert against whatever the
host machine happened to have. That made it a **~50% flake** on any machine, and
the cause was recorded in the source it was testing:

    agents/brains/big_brain.py:188-190 (ARCH-ENG-115)
      "...also made tests/runtime/test_brain_prompt_hardware.py flaky:
       detection intermittently yields CPU-only, the prompt still claims
       'GPU 0', and the test's 'names a real detected device' assertion
       fails ~50% of runs."

ARCH-ENG-115 correctly fixed the underlying product defect -- a prompt must not
assert unverified hardware -- but left the test asserting against live detection.
So the suite's green/red signal depended on the operator's GPU.

`_hardware_line()` emits the section only when `cfg.device_id`, `cfg.gpu_layers`
or `cfg.device` matches a DETECTED device. `.env` sets
`BIG_BRAIN_DEVICE=0` / `SMALL_BRAIN_DEVICE=1`, so the lookup is by device index.
Any detection run that returns CPU-only, or indices that do not line up, leaves
no match and the section is omitted -- by design, since a false claim is worse
than none.

## What this file tests now

Both paths, deterministically:

* **A registry with the configured device** -> the section is present and names
  THAT device. This is the behaviour that matters, and it is now independent of
  the host's hardware.
* **A registry with no matching device** -> the section is omitted, and the
  prompt still builds. This pins the ARCH-ENG-115 contract that unverified
  hardware is never asserted as fact.

One test still touches live detection, deliberately: it asserts only that the
call SUCCEEDS, never that a particular device was found.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _fake_device(ident, name, gb, index=0, is_gpu=True, kind="gpu", cores=0):
    """A ComputeDevice-shaped stand-in. Only the attributes `_hardware_line`
    reads are needed: id, index, is_gpu, is_cpu, name, label()."""
    class _D:
        def __init__(self):
            self.id = ident
            self.name = name
            self.memory_gb = gb
            self.index = index
            self.is_gpu = is_gpu
            self.is_cpu = not is_gpu
            self.kind = kind
            self.cores = cores

        def label(self):
            return f"{self.name} ({self.memory_gb:.0f} GB)"

    return _D()


class _PatchedRegistry:
    """Context manager replacing `device_registry.detect_devices`."""

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


class TestHardwareSectionIsRendered(unittest.TestCase):
    """The behaviour that matters, independent of the host's hardware."""

    def _prompt(self, brain, query):
        if brain == "small":
            from agents.brains.small_brain import SmallBrainAdapter
            return SmallBrainAdapter()._build_system_prompt(query)
        from agents.brains.big_brain import BigBrainAdapter
        return BigBrainAdapter()._build_system_prompt(query, "analysis")

    def _both_with(self, devices):
        with _PatchedRegistry(devices):
            return self._prompt("small", "hello"), self._prompt("big", "analyze")

    def test_small_prompt_has_hardware_section(self):
        devices = [_fake_device("cpu0", "System RAM", 32.0, index=0,
                                is_gpu=False, kind="cpu", cores=12),
                   _fake_device("gpu0", "NVIDIA GeForce TESTCARD", 16.0, index=0),
                   _fake_device("gpu1", "NVIDIA GeForce TESTSECOND", 8.0, index=1)]
        small, _ = self._both_with(devices)
        self.assertIn("# YOUR HARDWARE", small)

    def test_big_prompt_has_hardware_section(self):
        devices = [_fake_device("cpu0", "System RAM", 32.0, index=0,
                                is_gpu=False, kind="cpu", cores=12),
                   _fake_device("gpu0", "NVIDIA GeForce TESTCARD", 16.0, index=0),
                   _fake_device("gpu1", "NVIDIA GeForce TESTSECOND", 8.0, index=1)]
        _, big = self._both_with(devices)
        self.assertIn("# YOUR HARDWARE", big)

    def test_the_section_names_the_configured_device_not_a_placeholder(self):
        """The ARCH-ENG-115 contract: no unverified hardware as fact."""
        devices = [_fake_device("cpu0", "System RAM", 32.0, index=0,
                                is_gpu=False, kind="cpu", cores=12),
                   _fake_device("gpu0", "NVIDIA GeForce TESTCARD", 16.0, index=0),
                   _fake_device("gpu1", "NVIDIA GeForce TESTSECOND", 8.0, index=1)]
        small, big = self._both_with(devices)
        for name, prompt in (("small", small), ("big", big)):
            with self.subTest(brain=name):
                self.assertIn("# YOUR HARDWARE", prompt)
                section = prompt[prompt.index("# YOUR HARDWARE"):]
                self.assertTrue(
                    any(d.name in section for d in devices),
                    f"the {name} hardware section named no injected device: "
                    f"{section[:120]!r}")
                self.assertNotIn(
                    "(detected hardware)", section,
                    "the ROLE_DEFAULTS placeholder reached the prompt; that is "
                    "exactly what ARCH-ENG-115 removed")


class TestUnverifiedHardwareIsOmitted(unittest.TestCase):
    """Pins the deliberate choice to say nothing rather than guess."""

    def _prompt(self, brain):
        if brain == "small":
            from agents.brains.small_brain import SmallBrainAdapter
            return SmallBrainAdapter()._build_system_prompt("hello")
        from agents.brains.big_brain import BigBrainAdapter
        return BigBrainAdapter()._build_system_prompt("analyze", "analysis")

    def test_no_matching_device_omits_the_section_and_still_builds(self):
        # CPU only: `.env` binds the big brain to device index 0 with full GPU
        # offload, so nothing matches. Omitting is correct; asserting a device
        # would be the ARCH-ENG-115 bug.
        devices = [_fake_device("cpu0", "System RAM", 32.0, index=0,
                                is_gpu=False, kind="cpu", cores=12)]
        with _PatchedRegistry(devices):
            small = self._prompt("small")
            big = self._prompt("big")
        self.assertIsInstance(small, str)
        self.assertIsInstance(big, str)
        # Whichever section is dropped, neither prompt may claim a device.
        for name, prompt in (("small", small), ("big", big)):
            with self.subTest(brain=name):
                self.assertNotIn("(detected hardware)", prompt)
                if "# YOUR HARDWARE" in prompt:
                    section = prompt[prompt.index("# YOUR HARDWARE"):]
                    self.assertNotIn("GPU 0", section.split("\n")[1]
                                     if len(section.split("\n")) > 1 else "",
                                     "a device was asserted that detection did "
                                     "not confirm")

    def test_an_empty_registry_does_not_raise(self):
        with _PatchedRegistry([]):
            self.assertIsInstance(self._prompt("small"), str)
            self.assertIsInstance(self._prompt("big"), str)


class TestLiveDetectionStillWorks(unittest.TestCase):
    """One deliberate live check -- the call SUCCEEDS, not what it finds."""

    def test_detect_devices_succeeds_on_this_host(self):
        from agents.runtime import device_registry as dr
        devices = dr.detect_devices(include_cpu=True)
        self.assertIsInstance(devices, list)
        for d in devices:
            self.assertTrue(getattr(d, "id", None),
                            "a detected device has no id")
        # Deliberately asserts NOTHING about which devices exist: that is
        # host-dependent and was the entire source of the flake.


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """The injected registry must actually take effect."""

    def test_the_patch_is_installed_and_removed(self):
        from agents.runtime import device_registry as dr
        original = dr.detect_devices
        with _PatchedRegistry([_fake_device("x", "PROBE", 1.0)]):
            self.assertIsNot(dr.detect_devices, original,
                             "the registry patch did not take effect, so every "
                             "injection-based assertion above is vacuous")
            self.assertEqual(len(dr.detect_devices(include_cpu=True)), 1)
        self.assertIs(dr.detect_devices, original,
                      "the registry patch leaked past the context manager; that "
                      "leak is what made the original test flaky")

    def test_the_injected_devices_carry_the_read_attributes(self):
        d = _fake_device("gpu0", "TESTCARD", 16.0, index=0)
        for attr in ("id", "name", "index", "is_gpu", "is_cpu", "memory_gb"):
            self.assertTrue(hasattr(d, attr), f"missing {attr}")
        self.assertIn("TESTCARD", d.label())


if __name__ == "__main__":
    unittest.main()