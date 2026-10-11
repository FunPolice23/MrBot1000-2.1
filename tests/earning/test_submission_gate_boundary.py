"""The real human gate for autonomous submissions is the submission ramp.

A security review read ``AutonomousLoop._stage_request_approval`` — which only
compares ``advertised_amount > 100.0`` — and concluded that sub-$100
opportunities execute and submit with no human decision. That conclusion is
**wrong**, but it was a reasonable misreading of an undocumented boundary, so
the fact is pinned here by execution rather than left to code reading.

What actually protects a submission is ``agents/earning/proposal.py``:
``submit_gig_proposal`` runs the ProposalReviewer, then — when no
``confirm_cb`` is supplied, which is exactly how the autonomous loop calls it —
consults ``SubmissionRamp.requires_human`` and FAILS CLOSED with
``ramp_human_required`` on cold-start, on a low win-rate, or whenever the
platform's AI policy is not ``ai_allowed``.

These tests assert that downstream gate, so a future change to the ramp or the
proposal path cannot quietly turn the loop's dollar threshold into the only
protection.
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.earning.proposal import submit_gig_proposal  # noqa: E402
from agents.earning import submission_ramp as _ramp_mod  # noqa: E402
from agents.earning.submission_ramp import SubmissionRamp  # noqa: E402
from app.earning_pipeline import PipelineResult  # noqa: E402


class _RampIsolation(unittest.TestCase):
    """Reset the process-wide ramp singleton around every test.

    ``get_ramp`` memoizes a single ``SubmissionRamp`` and, once one is built,
    *adopts* the first non-None ``memory`` handed to it. Without this reset a
    test that injects a warm reputation permanently changes what every later
    test — and any other test module in the same pytest process — observes,
    which made the cold-start assertions pass or fail depending on run order.
    """

    def setUp(self):
        self._saved_ramp = _ramp_mod._RAMP
        # Force a FRESH singleton, do not merely save/restore. Other test
        # modules (e.g. tests/dialogue/test_group3_honesty) call
        # set_ramp_memory() with a temp DB they then delete; the surviving
        # singleton keeps that dead memory and, because get_ramp only adopts a
        # memory while ``_memory is None``, any memory this module passes is
        # silently ignored. Starting from None makes these tests authoritative.
        _ramp_mod._RAMP = None

    def tearDown(self):
        _ramp_mod._RAMP = self._saved_ramp


def _opp(amount=25.0, platform="upwork", task_type="writing"):
    return type("Opp", (), {
        "id": "opp-low", "title": "Small writing task", "platform": platform,
        "task_type": task_type, "payment_amount": amount,
        "advertised_amount": amount, "description": "Write 300 words.",
    })()


class _RecordingClient:
    """Stands in for a real platform client; records whether it was reached."""

    def __init__(self):
        self.calls = []

    def can_submit(self):
        return True

    def submit_proposal(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "message": "submitted", "proposal_id": "p-1"}


def _submit(opp, memory=None, trust_boundary=None):
    """Call the proposal path exactly as the autonomous loop does: no confirm_cb."""
    client = _RecordingClient()
    result = submit_gig_proposal(
        opp, "Auto-generated proposal.",
        result_type=PipelineResult, reviewer=None, confirm_cb=None,
        client=client, default_client=client, memory=memory,
        trust_boundary=trust_boundary, track_fn=lambda *a, **k: None,
        record_submission_fn=lambda *a, **k: None, lifecycle=None,
    )
    return result, client


class TestAutonomousSubmissionIsGatedDownstream(_RampIsolation):
    def test_cold_start_blocks_submission_and_never_calls_the_client(self):
        """The default (no history) state must fail closed."""
        result, client = _submit(_opp())
        self.assertFalse(result.success)
        self.assertEqual(result.action_taken, "ramp_human_required")
        self.assertEqual(client.calls, [],
                         "no submission may reach the platform on cold-start")

    def test_low_win_rate_blocks_even_with_enough_submissions(self):
        """Many submissions but a weak win-rate must still require a human."""
        memory = type("Mem", (), {"get_platform_reputation": lambda self, p: {
            "success": 2, "failed": 8, "total": 10, "success_rate": 0.2}})()
        result, client = _submit(_opp(), memory=memory)
        self.assertFalse(result.success)
        self.assertEqual(client.calls, [])

    def test_ai_disallowed_policy_overrides_a_warm_ramp(self):
        """Platform policy wins: the ramp may only ever relax, never override."""
        warm = type("Mem", (), {"get_platform_reputation": lambda self, p: {
            "success": 9, "failed": 1, "total": 10, "success_rate": 0.9}})()

        ramp = SubmissionRamp(memory=warm, min_submissions=5,
                              win_rate_threshold=0.6)
        self.assertFalse(ramp.requires_human("upwork", ai_policy="ai_allowed"),
                         "premise: a warm ramp does relax under ai_allowed")
        self.assertTrue(ramp.requires_human("upwork", ai_policy="ai_disallowed"),
                        "ai_disallowed must force a human regardless of ramp")
        self.assertTrue(ramp.requires_human("upwork", ai_policy="human_only"))

        boundary = type("TB", (), {"ai_policy": "ai_disallowed"})()
        result, client = _submit(_opp(), memory=warm, trust_boundary=boundary)
        self.assertFalse(result.success)
        self.assertEqual(client.calls, [],
                         "a forbidden-AI platform must never be auto-submitted")

    def test_relaxed_ramp_is_the_documented_and_only_auto_path(self):
        """Pins the one path that auto-submits, so it stays deliberate.

        With a warm ramp under ai_allowed the proposal is submitted without a
        per-call human decision. That is the documented trust escalation: the
        operator's earlier confirmed submissions are what earned it. This test
        records that the relaxation is reachable ONLY through reputation +
        policy, never through the dollar threshold alone.
        """
        warm = type("Mem", (), {"get_platform_reputation": lambda self, p: {
            "success": 9, "failed": 1, "total": 10, "success_rate": 0.9}})()
        result, client = _submit(_opp(), memory=warm)
        self.assertTrue(result.success)
        self.assertEqual(len(client.calls), 1)


class TestApprovalStageScopeIsDocumented(unittest.TestCase):
    def test_request_approval_stage_declares_its_real_scope(self):
        """The stage must not look like the only human gate when it is not one."""
        import inspect

        from agents.services.autonomous_loop import AutonomousLoop
        doc = inspect.getdoc(AutonomousLoop._stage_request_approval) or ""
        self.assertIn("financial-exposure", doc.lower())
        self.assertIn("NOT the human-approval gate", doc)


if __name__ == "__main__":
    unittest.main()
