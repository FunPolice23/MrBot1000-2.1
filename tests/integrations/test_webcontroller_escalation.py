"""WebController.read_page escalation (Phase A web robustness).

The earning modules (freelance_finder, microtask_earner) call
WebController.read_page, which previously used requests + raise_for_status with
NO escalation: a non-200 or a JS-shell page (thin <200-char extraction) returned
a stub or a hard error, so a model/parser saw nothing useful and could loop. The
Dialogue brains' WebEyes already escalated on the same signals; this test locks
in that WebController now does too.

No network: requests.get and the Playwright path are both mocked.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, r"D:\MrBot1000_2.0")

from agents.integrations.browser import WebController


def _fake_response(status_code=200, text="", headers=None, url="https://example.com/x"):
    r = mock.Mock()
    r.status_code = status_code
    r.text = text
    r.url = url
    r.headers = headers or {"Content-Type": "text/html"}
    return r


class TestReadPageEscalation(unittest.TestCase):
    def setUp(self):
        self.wc = WebController()
        # Default: robots.txt allows everything, so tests isolate the
        # escalation logic. The robots gate itself has dedicated tests below.
        patcher = mock.patch("agents.integrations.browser._robots_checker")
        self._rc = patcher.start()
        self._rc.return_value.is_allowed.return_value = True
        self.addCleanup(patcher.stop)

    def test_rich_page_no_escalation(self):
        """A normal page with real content is returned as-is, browser NOT called."""
        body = "<html><head><title>Job Board</title></head><body>" + (
            "<p>Senior Python developer needed for a 3-month contract. "
            "Pay is competitive. Apply now.</p>" * 5
        ) + "</body></html>"
        with mock.patch("requests.get", return_value=_fake_response(text=body)) as g, \
             mock.patch.object(self.wc, "_read_with_playwright") as pw:
            out = self.wc.read_page("https://example.com/x")
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["text_length"], 200)
        self.assertEqual(out["title"], "Job Board")
        pw.assert_not_called()          # no escalation needed
        g.assert_called_once()

    def test_non_200_escalates_to_browser(self):
        """A 403/503 triggers exactly one Playwright attempt."""
        with mock.patch("requests.get", return_value=_fake_response(status_code=403)), \
             mock.patch.object(
                 self.wc, "_read_with_playwright",
                 return_value={"ok": True, "url": "u", "title": "T",
                               "text": "rendered body content here " * 20,
                               "text_length": 400, "rendered": True}) as pw:
            out = self.wc.read_page("https://example.com/blocked")
        pw.assert_called_once_with("https://example.com/blocked")
        self.assertTrue(out["ok"])
        self.assertTrue(out.get("rendered"))

    def test_non_200_browser_also_fails_marks_human_open(self):
        """When the browser can't get it either, mark human-open-only, not a stub."""
        with mock.patch("agents.integrations.browser._robots_checker") as rc, \
             mock.patch("requests.get", return_value=_fake_response(status_code=403)), \
             mock.patch.object(
                 self.wc, "_read_with_playwright",
                 return_value={"ok": False, "error": "bot wall"}):
            rc.return_value.is_allowed.return_value = True
            out = self.wc.read_page("https://example.com/blocked")
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("human_open_only"))
        self.assertIn("403", out["error"])

    def test_thin_js_shell_escalates(self):
        """A 200 with a near-empty JS shell escalates to the browser."""
        shell = "<html><head><title>Loading…</title></head><body><div id=app></div></body></html>"
        with mock.patch("requests.get", return_value=_fake_response(text=shell)), \
             mock.patch.object(
                 self.wc, "_read_with_playwright",
                 return_value={"ok": True, "url": "u", "title": "Real",
                               "text": "actual rendered content " * 20,
                               "text_length": 400, "rendered": True}) as pw:
            out = self.wc.read_page("https://ugig.net/gigs/1")
        pw.assert_called_once()
        self.assertTrue(out.get("rendered"))

    def test_thin_and_playwright_unavailable_falls_back_to_stub(self):
        """If Playwright is missing ({}), don't crash — return the thin result."""
        shell = "<html><body><div id=app></div></body></html>"
        with mock.patch("requests.get", return_value=_fake_response(text=shell)), \
             mock.patch.object(self.wc, "_read_with_playwright", return_value={}):
            out = self.wc.read_page("https://example.com/spa")
        self.assertTrue(out["ok"])          # still ok, just thin
        self.assertLess(out["text_length"], 200)
        self.assertNotIn("rendered", out)

    def test_playwright_import_error_returns_empty(self):
        """_read_with_playwright returns {} (not a crash) when Playwright is absent."""
        with mock.patch.dict(sys.modules, {"playwright.sync_api": None}):
            out = self.wc._read_with_playwright("https://example.com/x")
        self.assertEqual(out, {})

    def test_robots_disallow_blocks_before_fetch(self):
        """A host whose robots.txt disallows the path is NOT fetched at all —
        returns human_open_only, and requests.get is never called."""
        with mock.patch("agents.integrations.browser._robots_checker") as rc, \
             mock.patch("requests.get") as g:
            rc.return_value.is_allowed.return_value = False
            out = self.wc.read_page("https://reddit.com/r/forhire/x")
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("human_open_only"))
        self.assertIn("robots.txt", out["error"])
        g.assert_not_called()          # never even hit the network

    def test_robots_allow_proceeds(self):
        """When robots.txt allows, the fetch proceeds normally."""
        body = "<html><head><title>T</title></head><body>" + (
            "<p>Real job listing content for a contract role. Apply today.</p>" * 5
        ) + "</body></html>"
        with mock.patch("agents.integrations.browser._robots_checker") as rc, \
             mock.patch("requests.get", return_value=_fake_response(text=body)) as g:
            rc.return_value.is_allowed.return_value = True
            out = self.wc.read_page("https://example.com/jobs")
        self.assertTrue(out["ok"])
        g.assert_called_once()


if __name__ == "__main__":
    raise SystemExit(unittest.main())
