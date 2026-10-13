"""Phase D3 — social_post tool: HIGH-TRUST, approval-gated, no fabrication (ARCH-ENG-085).

moltbook exposes read/search + agent registration but NO public post/publish
API. social_post therefore refuses when no confirmed write endpoint is wired
rather than faking a post (the user's "never fabricate, truthful only" rule).
Invariants:
- refuses unless invoked through the dispatcher (mutation capability).
- refuses a missing approval_id / non-approved approval.
- refuses (plainly) when no confirmed writer is wired — never fabricates.
- posts through the injected writer only behind an APPROVED approval.
"""
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

import agents.safety.handlers as H
from agents.safety.approval import HumanApprovalQueue
from agents.safety.calling import _DISPATCH_CAPABILITY


class TestSocialPostGate(unittest.TestCase):
    def setUp(self):
        H.set_social_writer(None)
        self.queue = HumanApprovalQueue.instance()

    def tearDown(self):
        H.set_social_writer(None)

    def _approval(self, *, approve=True):
        item = self.queue.enqueue_submission("social post", "post to moltbook")
        if approve:
            self.queue.approve(item.id, notes="ok")
        return item.id

    def _call(self, args):
        return H._tool_social_post(args, authorization=_DISPATCH_CAPABILITY)

    def test_requires_dispatcher_capability(self):
        out = H._tool_social_post(
            {"network": "moltbook", "content": "hi", "approval_id": "x"},
            authorization=None)
        self.assertIn("Authorization required", out)

    def test_requires_approval_id(self):
        out = self._call({"network": "moltbook", "content": "hi"})
        self.assertIn("approval_id", out)

    def test_rejects_pending_approval(self):
        aid = self._approval(approve=False)
        out = self._call({"network": "moltbook", "content": "hi", "approval_id": aid})
        self.assertIn("not approved", out)

    def test_refuses_without_confirmed_writer_no_fabrication(self):
        aid = self._approval(approve=True)
        out = self._call({"network": "moltbook", "content": "hi", "approval_id": aid})
        self.assertIn("no confirmed write endpoint", out)
        self.assertIn("Refusing to fabricate", out)
        # Must NOT claim it posted.
        self.assertNotIn("posted to moltbook", out)

    def test_posts_behind_approved_approval_with_writer(self):
        seen = []

        def writer(payload):
            seen.append(payload)
            return "post-id-123"

        H.set_social_writer(writer)
        aid = self._approval(approve=True)
        out = self._call({"network": "moltbook", "content": "hello world",
                          "approval_id": aid})
        self.assertIn("posted to moltbook", out)
        self.assertIn("post-id-123", out)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["content"], "hello world")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
