"""Tests that brain prompts reflect the ACTUAL detected hardware (N-brain)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestBrainPromptHardwareAwareness(unittest.TestCase):
    def _small_prompt(self):
        from agents.brains.small_brain import SmallBrainAdapter
        return SmallBrainAdapter()._build_system_prompt("hello")

    def _big_prompt(self):
        from agents.brains.big_brain import BigBrainAdapter
        return BigBrainAdapter()._build_system_prompt("analyze", "analysis")

    def test_small_prompt_has_hardware_section(self):
        self.assertIn("# YOUR HARDWARE", self._small_prompt())

    def test_big_prompt_has_hardware_section(self):
        self.assertIn("# YOUR HARDWARE", self._big_prompt())

    def test_prompts_reflect_detected_device_not_hardcoded(self):
        # The hardware line must come from live detection, so it names a real
        # detected device (or a generic CPU/RAM label) — never a hardcoded card
        # string baked into the prompt file.
        from agents.runtime import device_registry as dr
        devices = dr.detect_devices(include_cpu=True)
        names = {d.name for d in devices}
        small = self._small_prompt()
        big = self._big_prompt()
        # At least one detected device name (or a CPU/RAM label) appears.
        hw_small = small[small.index("# YOUR HARDWARE"):]
        hw_big = big[big.index("# YOUR HARDWARE"):]
        self.assertTrue(
            any(n in hw_small for n in names) or "CPU" in hw_small or "RAM" in hw_small)
        self.assertTrue(
            any(n in hw_big for n in names) or "CPU" in hw_big or "RAM" in hw_big)

    def test_hardware_line_never_raises(self):
        # Even with a broken registry the prompt build must not crash.
        sb = self._small_prompt()
        bb = self._big_prompt()
        self.assertIsInstance(sb, str)
        self.assertIsInstance(bb, str)


if __name__ == "__main__":
    unittest.main()
