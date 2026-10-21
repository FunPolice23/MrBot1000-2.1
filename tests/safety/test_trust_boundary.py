import os
import sys

import unittest

from agents.safety.trust import TrustBoundary, HIGH_TRUST_ACTIONS


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ARCH-ENG-205: `TestPlatformAdapters` was removed with the adapters it tested.
# It exercised `FiverrAdapter` and `RedditAdapter`, all of which had zero
# references outside `agents/platforms/__init__.py` -- an eager re-export, so the
# modules loaded on every registration-panel build while nothing ever used them.
# `TestTrustBoundary` above is kept: it exercises `agents.safety/trust.py`, which
# is live and still enforced. Only the unused implementations went, not the rules.

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

if __name__ == "__main__":
    unittest.main()

