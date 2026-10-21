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

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import agents.safety.handlers as H
from agents.safety.approval import HumanApprovalQueue
from agents.safety.calling import _DISPATCH_CAPABILITY


class TestSocialPostGate(unittest.TestCase):
    def setUp(self):
        H.set_social_writer(None)
        self.queue = HumanApprovalQueue.instance()

    def tearDown(self):
        H.set_social_writer(None)

    def _approval(self, *, approve=True, content="hi"):
        """Enqueue a scoped social_post approval (ARCH-ENG-129).

        The approval names the tool AND the content. Before the scope binding
        the queued item carried no scope, and `social_post` checked only
        `status == APPROVED` — a human who approved 'Hello team' had
        'BUY THIS NOW <link>' published (reproduced by execution).
        """
        from agents.safety.approval import ApprovalItem, ApprovalKind
        item = self.queue.enqueue(ApprovalItem(
            kind=ApprovalKind.ACTION,
            title="social post",
            description="post to moltbook",
            details={"tool": "social_post",
                     "arguments": {"network": "moltbook", "content": content}},
            payload={"tool": "social_post",
                     "arguments": {"network": "moltbook", "content": content}},
        ))
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
        aid = self._approval(approve=True, content="hello world")
        out = self._call({"network": "moltbook", "content": "hello world",
                          "approval_id": aid})
        self.assertIn("posted to moltbook", out)
        self.assertIn("post-id-123", out)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["content"], "hello world")

    def test_different_content_than_approved_is_refused(self):
        """ARCH-ENG-129: the approval authorizes the CONTENT the human saw.

        Reproduced on the real code before the fix: an approval recorded for
        'Hello team' published 'BUY THIS NOW <link>' — outbound public content
        behind a gate that never read what the human reviewed.
        """
        seen = []
        H.set_social_writer(lambda p: seen.append(p) or {"ok": True})
        aid = self._approval(approve=True, content="Hello team")
        out = self._call({"network": "moltbook", "content": "BUY THIS NOW http://x",
                          "approval_id": aid})
        self.assertIn("refused", out)
        self.assertEqual(seen, [])

    def test_approval_for_another_tool_is_refused(self):
        """ARCH-ENG-129: an approval authorizes ONE tool, not a capability.

        Reproduced on the real code before the fix: a human-approved
        ``file_write`` approval was replayed as the ``approval_id`` for
        ``record_payment``, which booked $777 of verified revenue.
        """
        from agents.safety.approval import ApprovalItem, ApprovalKind
        item = self.queue.enqueue(ApprovalItem(
            kind=ApprovalKind.ACTION, title="Chat tool request: file_write",
            description="write scratch.txt", requested_by="dialogue",
            details={"tool": "file_write",
                     "arguments": {"path": "scratch.txt", "content": "x"}},
            payload={"tool": "file_write",
                     "arguments": {"path": "scratch.txt", "content": "x"}},
        ))
        self.queue.approve(item.id, notes="ok")
        out = self._call({"network": "moltbook", "content": "hi",
                          "approval_id": item.id})
        self.assertIn("refused", out)
        self.assertIn("file_write", out)

    def test_unscoped_approval_authorizes_nothing(self):
        """ARCH-ENG-129: fail closed on an item that records no scope.

        ``enqueue_submission`` (the legacy GUI/agent path) records only a
        title and description. It names no tool, so it cannot authorize a
        HIGH-TRUST action — the human never saw one.
        """
        aid = self._approval(approve=True)
        # Strip the scope the fixture recorded, simulating a legacy producer.
        item = self.queue.find_by_id(aid)
        item.details = {"note": "legacy free-form producer"}
        item.payload = {}
        out = self._call({"network": "moltbook", "content": "hi",
                          "approval_id": aid})
        self.assertIn("refused", out)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
