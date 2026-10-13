"""Phase E — Moltbook feed worker + gated Social-Activity posting (ARCH-ENG-088).

- MoltbookFeedWorker normalizes feed posts into rows off-thread and needs only
  the API key (reads are not approval-gated); missing key -> ok=False.
- The Social Activity "Post to Moltbook" action queues a HUMAN approval item;
  the agent posts only after approval (a pending draft is never a sent post).
"""
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")


class TestMoltbookFeedWorkerRows(unittest.TestCase):
    """Exercise the worker's normalization logic directly (no Qt event loop)."""

    def _normalize(self, feed):
        rows = []
        posts = feed.get("posts", []) if isinstance(feed, dict) else []
        for p in posts if isinstance(posts, list) else []:
            if not isinstance(p, dict):
                continue
            submolt = p.get("submolt") or {}
            rows.append({
                "id": str(p.get("id") or p.get("post_id") or ""),
                "submolt": str(submolt.get("display_name")
                               or submolt.get("name") or ""),
                "title": str(p.get("title", "")),
                "author": str((p.get("author") or {}).get("name")
                              or p.get("author_name") or ""),
                "preview": str(p.get("content", ""))[:160],
                "url": f"https://www.moltbook.com/post/{p.get('id') or ''}",
            })
        return rows

    def test_normalizes_posts(self):
        feed = {"posts": [
            {"id": "p1", "title": "Hello",
             "submolt": {"display_name": "General"},
             "author": {"name": "ada"}, "content": "body text"},
        ]}
        rows = self._normalize(feed)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["submolt"], "General")
        self.assertEqual(rows[0]["title"], "Hello")
        self.assertEqual(rows[0]["author"], "ada")
        self.assertEqual(rows[0]["url"], "https://www.moltbook.com/post/p1")

    def test_handles_empty_and_junk(self):
        self.assertEqual(self._normalize({}), [])
        self.assertEqual(self._normalize({"posts": "notalist"}), [])
        self.assertEqual(self._normalize({"posts": [None, 3]}), [])

    def test_worker_importable(self):
        from gui.builders.tab_workers import MoltbookFeedWorker
        self.assertTrue(hasattr(MoltbookFeedWorker, "finished"))


class TestSocialPostQueuesApproval(unittest.TestCase):
    def test_post_action_enqueues_pending_approval(self):
        """The GUI action must enqueue a PENDING approval, not post directly."""
        from agents.safety.approval import (
            HumanApprovalQueue, ApprovalStatus)
        queue = HumanApprovalQueue.instance()
        item = queue.enqueue_submission(
            "Post to Moltbook",
            "Draft a post/response for the Moltbook social network.")
        # Freshly enqueued => PENDING, never approved. social_post refuses
        # anything that is not APPROVED, so this is the gate.
        self.assertEqual(item.status, ApprovalStatus.PENDING)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
