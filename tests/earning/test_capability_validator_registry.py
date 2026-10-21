"""CapabilityValidator registry wiring (earning-pipeline P1).

earning_pipeline.py built CapabilityValidator(self.memory) — passing an
EarningMemory where a CapabilityRegistry belongs, so validate()'s
registry.get(cap) raised AttributeError on every task. The fix is
CapabilityValidator() (default registry via get_default_registry()).

Targets BEHAVIOUR: the default validator validates a task without raising; a
non-registry argument (the old bug) crashes on .get. Pure, offline.
"""
import sys
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.earning.validator import CapabilityValidator
from agents.earning.spec import build_task


def _task():
    # A task with at least one inferred requirement so validate() reaches
    # registry.get(cap).
    return build_task("research", "conduct web research and write a summary",
                      extra_capabilities=["WEB_RESEARCH"])


class CapabilityValidatorRegistryTest(unittest.TestCase):
    def test_default_registry_supports_get(self):
        v = CapabilityValidator()
        self.assertTrue(hasattr(v.registry, "get"),
                        "default registry must be a CapabilityRegistry (.get)")

    def test_default_validator_validates_without_attributeerror(self):
        v = CapabilityValidator()
        f = v.validate(_task())   # the fix: must not raise AttributeError
        self.assertFalse(f.is_executable and f.verdict == "unsupported")
        self.assertIn(f.verdict, ("fully_automatable", "partially_automatable",
                                  "human_required", "unsupported"))

    def test_non_registry_arg_crashes_the_old_bug(self):
        # The OLD call passed self.memory (no .get) — reproducing that shape
        # proves the bug was real and why the fix (no arg) is correct.
        class _NoGet:  # mimics EarningMemory: no .get method
            pass
        v = CapabilityValidator(_NoGet())
        with self.assertRaises(AttributeError):
            v.validate(_task())


if __name__ == "__main__":
    unittest.main()
