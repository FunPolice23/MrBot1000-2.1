"""ARCH-ENG-320 -- Moltbook reads are public; the key gates WRITES only.

The finding
-----------
Operator report: the Social Activity scan finds/shows nothing and the
Moltbook feed displays nothing, "even if not registered". The live Moltbook
API was probed directly: both the feed read and the semantic search are
PUBLIC (verified against https://www.moltbook.com/api/v1 without any
Authorization header), while writes need an agent key. Our client gated the
READS behind ``MOLTBOOK_API_KEY`` too, so an unregistered operator got a
permanently dead feed tab and a social scan that silently yielded zero.

Fix:
- ``MoltbookPoster`` reads (get_feed / get_post / get_comments) no longer
  require a key, and ``_auth_headers`` only carries Authorization when a key
  actually exists (never an empty Bearer token). Writes keep every gate
  (capability approval + key when configured).
- ``MoltbookFeedWorker`` dropped its hard key gate — reads render keyless.
- ``MoltbookSource._discover`` no longer returns [] when the key is unset;
  the search runs keyless (a configured key is still attached, still scoped
  to moltbook.com).

Tests are behavioural against mock HTTP clients matching the live payloads
observed today.
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.discovery.discovery_sources import MoltbookSource
from agents.earning.moltbook_agent import MOLTBOOK_API_BASE, MoltbookPoster


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _feed_payload():
    # Mirrors the live https://www.moltbook.com/api/v1/posts shape observed
    # 2026-10-21 (unauthenticated).
    return {"posts": [{
        "id": "82ea5300-26b2", "title": "Your Calling Does Not Survive Token Expiry",
        "author": {"name": "neo_konsi_s2bw"},
        "submolt": {"name": "general", "display_name": "General"},
        "content": "post body",
        "upvotes": 201, "comment_count": 2108,
    }], "has_more": True, "next_cursor": "cur"}


class TestArchEng320KeylessMoltbookReads(unittest.TestCase):

    def setUp(self):
        os.environ.pop("MOLTBOOK_API_KEY", None)

    def tearDown(self):
        os.environ.pop("MOLTBOOK_API_KEY", None)

    def test_get_feed_works_without_a_key_and_sends_no_auth(self):
        client = Mock()
        client.get.return_value = _Resp(_feed_payload())
        poster = MoltbookPoster(http_client=client)
        out = poster.get_feed(sort="hot", limit=25)
        self.assertTrue(out["ok"])
        self.assertEqual(out["feed"]["posts"][0]["id"], "82ea5300-26b2")
        self.assertEqual(client.get.call_args.args[0], f"{MOLTBOOK_API_BASE}/posts")
        self.assertNotIn("Authorization", client.get.call_args.kwargs["headers"],
                         "a keyless read must never carry an empty Bearer")

    def test_writes_still_require_key_under_capability_approval(self):
        client = Mock()
        poster = MoltbookPoster(http_client=client)
        out = poster.create_post("general", "Hi", capability_approved=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "blocked")
        self.assertIn("API_KEY", out["reason"])
        client.post.assert_not_called()

    def test_writes_still_require_capability_approval(self):
        client = Mock()
        poster = MoltbookPoster(http_client=client)
        out = poster.create_post("general", "Hi")
        self.assertEqual(out["status"], "awaiting_approval")
        client.post.assert_not_called()

    def test_key_still_attached_when_configured_read_and_write(self):
        os.environ["MOLTBOOK_API_KEY"] = "k-test"
        client = Mock()
        client.get.return_value = _Resp({"posts": []})
        client.post.return_value = _Resp({"post": {"id": "x"}})
        poster = MoltbookPoster(http_client=client)
        self.assertTrue(poster.get_feed()["ok"])
        self.assertEqual(client.get.call_args.kwargs["headers"]["Authorization"],
                         "Bearer k-test")
        out = poster.create_post("general", "Hello", capability_approved=True)
        self.assertTrue(out["ok"])
        self.assertEqual(client.post.call_args.kwargs["headers"]["Authorization"],
                         "Bearer k-test")
        self.assertTrue(client.post.call_args.args[0].startswith(
            "https://www.moltbook.com"))

    def test_get_post_and_comments_work_keyless(self):
        client = Mock()

        def get(url, **kw):
            if url.rsplit("/", 1)[-1] == "comments":
                return _Resp({"comments": [{"id": "c1"}]})
            return _Resp({"post": {"id": url.rsplit("/", 1)[-1]}})

        client.get.side_effect = get
        poster = MoltbookPoster(http_client=client)
        self.assertTrue(poster.get_post("p9")["ok"])
        out = poster.get_comments("p9")
        self.assertTrue(out["ok"])
        # get_comments returns the raw payload (same convention as get_feed's
        # "feed"); the API nests the list under "comments".
        self.assertEqual(out["comments"]["comments"][0]["id"], "c1")

    def test_feed_worker_reports_rows_without_a_key(self):
        """The GUI worker loads the public feed with no MOLTBOOK_API_KEY."""
        from gui.builders.tab_workers import MoltbookFeedWorker

        resp = Mock()
        resp.json.return_value = _feed_payload()
        resp.raise_for_status.return_value = None
        worker = MoltbookFeedWorker(sort="hot", limit=25)
        emitted = []
        worker.finished.connect(emitted.append)  # Signal.emit is read-only
        with patch("requests.get", return_value=resp):
            worker.run()
        self.assertEqual(len(emitted), 1)
        self.assertTrue(emitted[0]["ok"])
        self.assertEqual(emitted[0]["count"], 1)
        self.assertEqual(emitted[0]["rows"][0]["submolt"], "General")
        self.assertEqual(emitted[0]["rows"][0]["author"], "neo_konsi_s2bw")

    def test_feed_worker_source_no_longer_consults_the_env(self):
        """The worker no longer gates the read on MOLTBOOK_API_KEY at all."""
        import pathlib
        repo = pathlib.Path(os.path.dirname(os.path.abspath(__file__))).parents[1]
        source = (repo / "gui" / "builders" / "tab_workers.py").read_text(
            encoding="utf-8")
        start = source.index("class MoltbookFeedWorker")
        end = source.index("\nclass ", start + 10) if "\nclass " in source[start + 10:] else len(source)
        worker_src = source[start:end if end != -1 else len(source)]
        self.assertNotIn("MOLTBOOK_API_KEY", worker_src)

    def test_discovery_source_keyless_still_yields_leads(self):
        payload = {"results": [{
            "type": "post", "id": "paid-k0", "title": "Paid agent task",
            "content": "Client offers a bounty for a scraper.",
            "submolt": {"name": "general", "display_name": "General"},
        }]}
        resp = Mock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        os.environ.pop("MOLTBOOK_API_KEY", None)
        with patch("requests.get", return_value=resp) as get:
            opps = MoltbookSource().discover()
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].external_url,
                         "https://www.moltbook.com/post/paid-k0")
        sent = get.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", sent)


if __name__ == "__main__":
    unittest.main()
