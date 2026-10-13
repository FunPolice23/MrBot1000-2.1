"""Phase E — social_writer_factory wires social_post to a real MoltbookPoster
(ARCH-ENG-086).

Invariants:
- No MOLTBOOK_API_KEY -> no writer (social_post then refuses, never fakes).
- With a key + requests, the returned writer posts/responds with
  capability_approved=True (the tool already gated the approval).
- A verification challenge is surfaced, not reported as posted.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _make_requests(payload):
    mod = types.ModuleType("requests")
    calls = []

    def _post(url, **kw):
        calls.append(("POST", url, kw))
        return _Resp(payload)

    mod.post = _post  # type: ignore[attr-defined]
    mod.get = lambda url, **kw: _Resp(payload)  # type: ignore[attr-defined]
    mod._calls = calls  # type: ignore[attr-defined]
    return mod


class TestFactoryNoKey(unittest.TestCase):
    def test_no_writer_without_key(self):
        from agents.earning.social_writer_factory import build_moltbook_writer
        os.environ.pop("MOLTBOOK_API_KEY", None)
        self.assertIsNone(build_moltbook_writer())


class TestFactoryWithKey(unittest.TestCase):
    def setUp(self):
        os.environ["MOLTBOOK_API_KEY"] = "moltbook_test_key"
        self._requests = _make_requests({"post": {"id": "abc123"}})
        sys.modules["requests"] = self._requests

    def tearDown(self):
        os.environ.pop("MOLTBOOK_API_KEY", None)
        sys.modules.pop("requests", None)

    def _writer(self, payload=None):
        from agents.earning.social_writer_factory import build_moltbook_writer
        w = build_moltbook_writer()
        self.assertIsNotNone(w)
        return w

    def test_new_post_uses_title_and_body(self):
        w = self._writer()
        result = w({"network": "moltbook", "content": "My Title\nBody line",
                    "submolt_name": "general"})
        self.assertIn("posted", result)
        self.assertIn("abc123", result)
        method, url, kw = self._requests._calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/api/v1/posts"))
        self.assertEqual(kw["json"]["title"], "My Title")
        self.assertEqual(kw["json"]["content"], "Body line")
        self.assertEqual(kw["json"]["submolt_name"], "general")

    def test_reply_uses_comment_endpoint(self):
        w = self._writer()
        result = w({"network": "moltbook", "content": "I agree",
                    "post_id": "p9"})
        self.assertIn("commented", result)
        method, url, kw = self._requests._calls[0]
        self.assertTrue(url.endswith("/api/v1/posts/p9/comments"))

    def test_verification_surfaced_not_faked(self):
        payload = {"post": {"id": "x"},
                   "verification": {"question": "2+2?", "challenge_id": "c1"}}
        os.environ["MOLTBOOK_API_KEY"] = "k"
        sys.modules["requests"] = _make_requests(payload)
        w = self._writer()
        result = w({"network": "moltbook", "content": "Hi there"})
        self.assertIn("PENDING VERIFICATION", result)
        self.assertNotIn("posted (id", result)

    def test_unsupported_network(self):
        w = self._writer()
        result = w({"network": "twitter", "content": "x"})
        self.assertIn("unsupported network", result)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
