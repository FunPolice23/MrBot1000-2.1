"""Regression: a persona turn that only NARRATES a read/verify intent (no tool
call, no concrete decision) is a stall and must be rejected — but a turn that
pairs the intent with a real plan/commitment/approval-ask is legit progress.

ARCH-ENG-104: the small-model "I need to verify... let me read the page" loop
produced textually-distinct but semantically-identical turns that slipped past
the text/semantic duplicate detectors (the signature is normalized full text),
so the agent spun forever narrating verification it never performed. The tool
chain now works (ARCH-ENG-103), but a narrated-only turn is still not progress.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from gui.tabs.dialogue_tab import DialogueWorker


class _Brain:
    model = "m"

    def chat(self, *a, **k):
        return ""


class TestNarratedReadIntentGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.worker = DialogueWorker(_Brain(), "ctx", [], "Jacob Stanley",
                                     max_retries=0)

    def test_pure_narrated_verify_is_rejected(self):
        # The exact loop from the bug report.
        self.assertTrue(self.worker._is_bad_dialogue_response(
            "I need to verify the actual uGig opportunity #11 before "
            "committing. Let me read the real gig page to confirm "
            "deliverables and payment terms."))

    def test_let_me_check_only_is_rejected(self):
        self.assertTrue(self.worker._is_bad_dialogue_response(
            "Let me check the uGig gig details to confirm what's actually "
            "available."))

    def test_intent_with_concrete_plan_is_accepted(self):
        # States a read intent BUT carries a plan + approval ask = progress.
        self.assertFalse(self.worker._is_bad_dialogue_response(
            "I will check the bug fix gig on uGig to see the specific Python "
            "code. Once I have the code, I will outline a plan to fix the bug "
            "and write tests. I need your approval to start the fix and "
            "submit the solution."))

    def test_past_tense_finding_with_commitment_is_accepted(self):
        self.assertFalse(self.worker._is_bad_dialogue_response(
            "I read the gig page and confirmed it's a $60 Python bug fix. "
            "I'm committing to it now."))

    def test_turn_reporting_an_executed_tool_is_accepted(self):
        # A turn that actually ran a tool and reports the result passes even
        # though it mentions reading.
        self.assertFalse(self.worker._is_bad_dialogue_response(
            "Let me read what came back. [TOOL RESULT] search results "
            "retrieved at 2026-10-13: the uGig gig is live at $60."))


if __name__ == "__main__":
    unittest.main()
