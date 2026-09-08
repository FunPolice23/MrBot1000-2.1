import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.trust_boundary import TrustBoundary, HIGH_TRUST_ACTIONS
from agents.platforms.base import PlatformAdapter
from agents.platforms.fiverr import FiverrAdapter
from agents.platforms.reddit import RedditAdapter


class TestTrustBoundary(unittest.TestCase):
    def test_high_trust_always_requires_human(self):
        tb = TrustBoundary(ai_policy="ai_allowed")
        for act in ("create_account", "set_password", "post", "send_funds",
                    "download_exec", "submit_proposal", "grant_oauth"):
            self.assertTrue(tb.requires_human_confirmation(act))
            allowed, reason = tb.may_auto_execute(act, instruction_trusted=True)
            self.assertFalse(allowed, f"{act} must never auto-execute")
            self.assertIn("high-trust", reason)

    def test_low_trust_ai_allowed_with_untrusted_instruction_blocked(self):
        tb = TrustBoundary(ai_policy="ai_allowed")
        allowed, reason = tb.may_auto_execute("search_gigs", instruction_trusted=False)
        self.assertFalse(allowed)
        self.assertIn("allowlist", reason)

    def test_ai_disallowed_forces_human_for_all(self):
        tb = TrustBoundary(ai_policy="ai_disallowed")
        self.assertTrue(tb.requires_human_confirmation("search_posts"))
        allowed, _ = tb.may_auto_execute("search_posts", instruction_trusted=True)
        self.assertFalse(allowed)


class TestPlatformAdapters(unittest.TestCase):
    def _gate(self):
        # Minimal fake gate: returns allowed with empty content (no DB needed
        # for shape tests). We only exercise list_actions / action gating here.
        class FakeGate:
            def fetch_instruction(self, url, **kw):
                from agents.instruction_gate import QuarantinedInstruction
                return QuarantinedInstruction(url=url, status="allowed",
                                              content="", content_hash="")
        return FakeGate()

    def test_fiverr_lists_actions(self):
        a = FiverrAdapter(self._gate())
        self.assertIn("submit_proposal", a.list_actions())
        self.assertIn("search_gigs", a.list_actions())

    def test_fiverr_submit_requires_human(self):
        a = FiverrAdapter(self._gate())
        # Without human confirmation -> refused.
        res = a.execute_action("submit_proposal", {"gig": 1})
        self.assertFalse(res["ok"])
        self.assertIn("human confirmation", res["reason"])
        # With confirmation -> allowed (stub).
        res2 = a.execute_action("submit_proposal", {"gig": 1}, human_confirmed=True)
        self.assertTrue(res2["ok"])

    def test_reddit_post_blocked_without_human(self):
        a = RedditAdapter(self._gate())
        res = a.execute_action("post_comment", {"text": "hi"})
        self.assertFalse(res["ok"])
        self.assertIn("human", res["reason"])

    def test_adapter_fetch_routes_through_gate(self):
        calls = []
        class TrackingGate:
            def fetch_instruction(self, url, **kw):
                calls.append(url)
                from agents.instruction_gate import QuarantinedInstruction
                return QuarantinedInstruction(url=url, status="allowed",
                                             content="", content_hash="")
        a = FiverrAdapter(TrackingGate())
        # Fiverr has no instruction_url -> returns allowed empty, no fetch.
        q = a.fetch_instructions()
        self.assertEqual(q.status, "allowed")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
