"""Single-source of truth for the release version.

Every user-visible or model-visible version string must resolve to the same
value. Before this test existed, ``ProgramKnowledge.PROGRAM_VERSION`` was a
hand-maintained ``"2.1.1"`` that drifted ~30 releases behind ``app/version.py``
— so both Dialogue personas were prompted with "# MrBot1000 v2.1.1" while the
application window title read v2.1.31. The models were mis-reporting their own
build to the operator.

These tests fail loudly if any version surface is ever allowed to drift again.
"""

import importlib.util
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.version import __version__ as RELEASE  # noqa: E402


class TestReleaseVersionIsSingleSourced(unittest.TestCase):
    def test_app_version_is_the_authoritative_release(self):
        """The authority itself must look like a release version."""
        self.assertRegex(RELEASE, r"^\d+\.\d+\.\d+$")

    def test_program_knowledge_tracks_the_release(self):
        """The version both brains are prompted with must equal the release."""
        from agents.knowledge.program_knowledge import ProgramKnowledge
        self.assertEqual(ProgramKnowledge.PROGRAM_VERSION, RELEASE)

    def test_persona_prompt_carries_the_real_release(self):
        """A persona system prompt must advertise the true build, not a stale one."""
        from agents.cognition.personas import persona_for_key
        for key in ("driver", "navigator"):
            persona = persona_for_key(key)
            prompt = persona.build_system_prompt(query="version check")
            lines = [ln for ln in prompt.splitlines()
                     if "MrBot1000 v" in ln]
            self.assertTrue(
                lines, f"persona {key!r} prompt carries no version header")
            for line in lines:
                self.assertIn(f"v{RELEASE}", line)

    def test_memory_context_header_tracks_the_release(self):
        """The injected memory-context header must not advertise a stale build."""
        from agents.cognition.personas import persona_for_key
        persona = persona_for_key("navigator")
        header = persona.memory_context("version check")
        if header:
            self.assertIn(f"v{RELEASE}", header.splitlines()[0])

    def test_root_package_version_tracks_the_release(self):
        """The root package must re-export the release, not a duplicate literal."""
        spec = importlib.util.spec_from_file_location(
            "mrb_root_init", os.path.join(PROJECT_ROOT, "__init__.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.__version__, RELEASE)


if __name__ == "__main__":
    unittest.main()
