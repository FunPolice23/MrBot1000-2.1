"""
agents/platforms/reddit.py — Reddit adapter stub (v2.0.22 S3)

Example of an ai_disallowed platform: Reddit's policies restrict automated
posting. Under ai_disallowed, ALL mutating actions require human-in-the-loop
regardless of model capability. The TrustBoundary enforces this.
"""

from .base import PlatformAdapter


class RedditAdapter(PlatformAdapter):
    platform = "reddit"
    ai_policy = "ai_disallowed"  # automated posting not permitted by policy
    base_url = "https://www.reddit.com"

    def instruction_url(self):
        # A subreddit might ship a SKILL.md-style guide; it would be gated.
        return None

    def list_actions(self):
        return ["search_posts", "read_post", "draft_comment", "post_comment"]

    def _do_action(self, action, payload, *, confirmed_by_human=False):
        if action in ("search_posts", "read_post"):
            return {"ok": True, "note": f"stub: {action}"}
        # draft_comment / post_comment are mutating -> human required by policy
        if action == "draft_comment":
            return {"ok": True, "note": "stub: local draft only"}
        if action == "post_comment":
            if not confirmed_by_human:
                return {"ok": False, "reason": "Reddit ai_disallowed: needs human confirmation"}
            return {"ok": True, "note": "stub: would post (human-confirmed)"}
        return {"ok": False, "reason": f"unknown action {action}"}
