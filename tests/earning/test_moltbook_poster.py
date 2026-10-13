"""Phase E — MoltbookPoster real read+write client (ARCH-ENG-086).

Writes are HIGH-TRUST (capability_approved required); reads need only the key.
Posts/comments may return a verification challenge — surfaced verbatim, never
faked as posted. The API key is only ever sent to www.moltbook.com.
"""
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

from agents.earning.moltbook_agent import MoltbookPoster, MOLTBOOK_API_BASE


class _Resp:
    def __init__(self, payload=None, status=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _Client:
    """Records calls; returns a queued response per call."""

    def __init__(self, payload=None, status=200):
        self.calls = []
        self.payload = payload
        self.status = status

    def _record(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return _Resp(self.payload, self.status)

    def get(self, url, **kw):
        return self._record("GET", url, **kw)

    def post(self, url, **kw):
        return self._record("POST", url, **kw)


class TestMoltbookPosterGates(unittest.TestCase):
    def setUp(self):
        os.environ["MOLTBOOK_API_KEY"] = "moltbook_test_key"

    def tearDown(self):
        os.environ.pop("MOLTBOOK_API_KEY", None)

    def test_create_post_requires_approval(self):
        poster = MoltbookPoster(http_client=_Client())
        out = poster.create_post("general", "Hello")
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "awaiting_approval")

    def test_reply_requires_approval(self):
        poster = MoltbookPoster(http_client=_Client())
        out = poster.reply_to_post("p1", "nice")
        self.assertEqual(out["status"], "awaiting_approval")

    def test_upvote_requires_approval(self):
        poster = MoltbookPoster(http_client=_Client())
        self.assertEqual(poster.upvote_post("p1")["status"], "awaiting_approval")
        self.assertEqual(poster.upvote_comment("c1")["status"], "awaiting_approval")

    def test_missing_key_blocks(self):
        os.environ.pop("MOLTBOOK_API_KEY", None)
        poster = MoltbookPoster(http_client=_Client())
        out = poster.create_post("general", "Hi", capability_approved=True)
        self.assertEqual(out["status"], "blocked")
        self.assertIn("API_KEY", out["reason"])

    def test_offline_blocks_cleanly(self):
        poster = MoltbookPoster(http_client=None)
        out = poster.create_post("general", "Hi", capability_approved=True)
        self.assertEqual(out["status"], "blocked")
        self.assertIn("no HTTP client", out["reason"])


class TestMoltbookPosterCalls(unittest.TestCase):
    def setUp(self):
        os.environ["MOLTBOOK_API_KEY"] = "moltbook_test_key"

    def tearDown(self):
        os.environ.pop("MOLTBOOK_API_KEY", None)

    def test_create_post_endpoint_and_auth(self):
        client = _Client(payload={"post": {"id": "x"}})
        poster = MoltbookPoster(http_client=client)
        out = poster.create_post("general", "Hello", "body",
                                 capability_approved=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "posted")
        method, url, kw = client.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, f"{MOLTBOOK_API_BASE}/posts")
        self.assertEqual(kw["json"]["submolt_name"], "general")
        self.assertEqual(kw["json"]["title"], "Hello")
        # Auth header present and host is the allowed one.
        self.assertEqual(kw["headers"]["Authorization"], "Bearer moltbook_test_key")
        self.assertTrue(url.startswith("https://www.moltbook.com"))

    def test_link_post_sets_type(self):
        client = _Client(payload={"post": {"id": "x"}})
        MoltbookPoster(http_client=client).create_post(
            "general", "Link", url="https://example.com", capability_approved=True)
        self.assertEqual(client.calls[0][2]["json"]["type"], "link")
        self.assertEqual(client.calls[0][2]["json"]["url"], "https://example.com")

    def test_verification_challenge_surfaced_not_faked(self):
        challenge = {"question": "3 + 4?", "challenge_id": "c1"}
        client = _Client(payload={"post": {"id": "x"}, "verification": challenge})
        out = MoltbookPoster(http_client=client).create_post(
            "general", "Hi", capability_approved=True)
        # It is NOT "posted" — it is pending verification, and the challenge is
        # returned verbatim so the agent/human can solve it.
        self.assertEqual(out["status"], "pending_verification")
        self.assertEqual(out["verification"], challenge)

    def test_reply_endpoint_and_parent(self):
        client = _Client(payload={"comment": {"id": "y"}})
        out = MoltbookPoster(http_client=client).reply_to_post(
            "p1", "I agree", parent_id="c9", capability_approved=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "commented")
        method, url, kw = client.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, f"{MOLTBOOK_API_BASE}/posts/p1/comments")
        self.assertEqual(kw["json"]["parent_id"], "c9")

    def test_upvote_endpoints(self):
        client = _Client(payload={})
        MoltbookPoster(http_client=client).upvote_post("p1", capability_approved=True)
        self.assertEqual(client.calls[0][1], f"{MOLTBOOK_API_BASE}/posts/p1/upvote")
        MoltbookPoster(http_client=client).upvote_comment("c1", capability_approved=True)
        self.assertEqual(client.calls[1][1], f"{MOLTBOOK_API_BASE}/comments/c1/upvote")

    def test_feed_parse(self):
        feed = {"posts": [{"id": "1", "title": "A"}], "next_cursor": "cur"}
        client = _Client(payload=feed)
        out = MoltbookPoster(http_client=client).get_feed(sort="new", limit=10)
        self.assertTrue(out["ok"])
        self.assertEqual(out["feed"], feed)
        method, url, kw = client.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, f"{MOLTBOOK_API_BASE}/posts")
        self.assertEqual(kw["params"]["sort"], "new")
        self.assertEqual(kw["params"]["limit"], 10)

    def test_feed_needs_no_approval_but_needs_key(self):
        # Reads are NOT approval-gated, only key-gated.
        client = _Client(payload={"posts": []})
        out = MoltbookPoster(http_client=client).get_feed()
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
