"""ARCH-ENG-112 — `sys.modules["requests"]` must keep ONE identity per session.

ARCH-ENG-111 recorded a real suite-level defect: 4 of the 8 tests in
`tests/integrations/test_webcontroller_escalation.py` failed in the full
`pytest` run but passed when the file ran alone. The audit's cause was listed
as an unverified hypothesis list (singleton state, cached session, memoised
Playwright detection, leaking mock.patch). The actual cause is none of those.

`tests/earning/test_social_writer_factory.py` did:

    setUp:      sys.modules["requests"] = <fake module>
    tearDown:   sys.modules.pop("requests", None)

Popping the key removes the REAL `requests` module from `sys.modules`. The
next `import requests` therefore executes the real module again and builds a
**new, distinct module object**. Modules that already ran `import requests` at
their own import time — `agents.integrations.browser` among them — hold a
reference to the ORIGINAL object and are unaffected. But `mock.patch("requests.get", ...)`
resolves the target by importing `"requests"` through `sys.modules`, so it
patches the NEW object. The production code keeps calling `requests.get` on
the ORIGINAL, unpatched object → the mock never fires, the real network is
hit, and `read_page` returns `ok=False`.

Measured before the fix (deterministic, no network):

    >>> browser.requests is re-imported requests   ->  False
    >>> g.called (mock on "requests.get")          ->  False

These tests lock the invariant so the failure class cannot return silently:

  1. `TestRequestsModuleIdentity` pins the mechanism itself: after a pop-based
     teardown, a re-imported `requests` is a different object, and an
     early-bound module (browser) keeps the original.
  2. `TestPatchReachesWebController.test_factory_teardown_leaves_one_requests_identity`
     is THE regression test: it drives the real `TestFactoryWithKey` through a
     full setUp/tearDown/doCleanups cycle and then asserts that a mock on
     `requests.get` actually reaches `WebController.read_page`. It fails on the
     pre-fix source and passes after the fix.
  3. `TestFactoryTestsStillWork` proves the fix did not weaken the ARCH-ENG-086
     behaviour (no key → no writer; with key → a real post).
"""

import sys
import types
import unittest
from unittest import mock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _make_fake_requests():
    """The exact shape test_social_writer_factory uses: a plain ModuleType."""
    mod = types.ModuleType("requests")
    mod.post = lambda url, **kw: None  # type: ignore[attr-defined]
    mod.get = lambda url, **kw: None  # type: ignore[attr-defined]
    return mod


def _factory_with_key_case():
    """The REAL polluting TestCase, imported so the test drives actual code.

    Importing the class (not re-implementing its setUp/tearDown) is what makes
    this a regression test rather than a restatement of the mechanism: if the
    factory module's teardown ever regresses to a bare `pop`, this fails.
    """
    from tests.earning.test_social_writer_factory import TestFactoryWithKey

    return TestFactoryWithKey("test_new_post_uses_title_and_body")


class TestRequestsModuleIdentity(unittest.TestCase):
    """The bug was a split module identity, so assert on identity."""

    def test_importing_requests_after_a_pop_yields_a_different_object(self):
        """Documents the mechanism itself (this is true of Python, by design).

        Not a product assertion — it is the reason the pop-based teardown was
        unsafe, recorded so the next reader does not re-litigate it.
        """
        import requests as real_requests

        self.assertIs(sys.modules["requests"], real_requests)
        original_id = id(sys.modules["requests"])

        # Reproduce the pre-fix teardown exactly.
        sys.modules["requests"] = _make_fake_requests()
        sys.modules.pop("requests", None)

        try:
            import requests as re_imported  # noqa: F811

            self.assertIsNot(re_imported, real_requests)
            self.assertNotEqual(id(re_imported), original_id)
        finally:
            sys.modules["requests"] = real_requests

    def test_early_bound_module_keeps_the_original_object(self):
        """A module that imported requests at import time is NOT re-bound.

        This is why the production code never saw the patched `get`.
        """
        import requests as real_requests
        from agents.integrations import browser

        self.assertIs(browser.requests, real_requests)

        sys.modules["requests"] = _make_fake_requests()
        try:
            # browser.requests still points at the ORIGINAL module object.
            self.assertIs(browser.requests, real_requests)
            self.assertIsNot(browser.requests, sys.modules["requests"])
        finally:
            sys.modules["requests"] = real_requests


class TestPatchReachesWebController(unittest.TestCase):
    """The user-visible symptom: a mock on requests.get silently not firing."""

    def _fake_response(self, status_code=200, text=""):
        r = mock.Mock()
        r.status_code = status_code
        r.text = text
        r.url = "https://example.com/x"
        r.headers = {"Content-Type": "text/html"}
        return r

    def _read_page_with_mocked_get(self):
        from agents.integrations.browser import WebController

        wc = WebController()
        body = "<html><head><title>T</title></head><body>" + ("<p>job</p>" * 40) + "</body></html>"
        with mock.patch("agents.integrations.browser._robots_checker") as rc, \
             mock.patch("requests.get", return_value=self._fake_response(text=body)) as g:
            rc.return_value.is_allowed.return_value = True
            out = wc.read_page("https://example.com/x")
        return out, g

    def test_mock_on_requests_get_is_actually_called(self):
        """The core regression: g.called must be True.

        Under the pre-fix pollution this was False — the mock patched a
        different module object, `read_page` fell through to the real network
        and returned ok=False, which is exactly the ARCH-ENG-111 failure.
        """
        out, g = self._read_page_with_mocked_get()
        self.assertTrue(g.called, "mock.patch('requests.get') did not reach WebController")
        self.assertTrue(out["ok"])

    def test_factory_teardown_leaves_one_requests_identity(self):
        """THE regression test for ARCH-ENG-112 — drives the real teardown.

        The defect was never inside a single test: it was the pop-based
        teardown of `tests/earning/test_social_writer_factory.py` leaving
        `sys.modules` without the real `requests`, so the NEXT test's
        `mock.patch("requests.get")` resolved a different module object than
        the one `agents.integrations.browser` had already bound.

        So this test must not create its own pollution — it drives the actual
        factory TestCase through a full setUp/tearDown cycle and asserts the
        session-wide invariant survives it:

          * `sys.modules["requests"]` is still the SAME object
            `agents.integrations.browser` holds, and
          * a subsequent `mock.patch("requests.get")` really reaches
            `WebController.read_page`.

        On the pre-fix source (bare assignment + `pop`) the first assertion
        fails. On the fixed source (`mock.patch.dict`) both hold.
        """
        from agents.integrations import browser

        bound = browser.requests
        self.assertIs(sys.modules["requests"], bound,
                      "precondition: browser.requests must be sys.modules['requests']")

        # Drive the real factory test through one full cycle. doCleanups() is
        # required: the patcher is registered with addCleanup, and those
        # callbacks fire from run()/doCleanups(), NOT from tearDown() — calling
        # tearDown() alone would leave the fake module installed.
        case = _factory_with_key_case()
        case.setUp()
        try:
            # Inside the patched window the fake IS sys.modules["requests"].
            self.assertIs(sys.modules["requests"], case._requests)
        finally:
            case.tearDown()
            case.doCleanups()

        # After teardown the real module must be back, byte-identical object.
        self.assertIs(
            sys.modules["requests"], bound,
            "test_social_writer_factory's teardown removed the real 'requests' from "
            "sys.modules — use mock.patch.dict(sys.modules, ...) so the exact prior "
            "entry is restored, or every later mock.patch('requests.get') patches a "
            "different module object than production code calls (ARCH-ENG-112).",
        )

        # And the mock must actually reach the production call site.
        out, g = self._read_page_with_mocked_get()
        self.assertTrue(g.called, "mock.patch('requests.get') did not reach WebController")
        self.assertTrue(out["ok"])
        self.assertIs(sys.modules["requests"], bound, "teardown must be balanced")

    def test_patch_dict_survives_a_module_swap_and_restore(self):
        """mock.patch.dict restores the exact prior entry (the fix's basis)."""
        import requests as real_requests

        before = sys.modules["requests"]
        with mock.patch.dict(sys.modules, {"requests": _make_fake_requests()}):
            self.assertIsNot(sys.modules["requests"], before)
        self.assertIs(sys.modules["requests"], before)
        self.assertIs(sys.modules["requests"], real_requests)


class TestFactoryTestsStillWork(unittest.TestCase):
    """The fix must not weaken the ARCH-ENG-086 behaviour it replaced."""

    def test_factory_uses_the_fake_requests_during_the_test(self):
        """Inside the patched window the fake IS sys.modules['requests']."""
        fake = _make_fake_requests()
        with mock.patch.dict(sys.modules, {"requests": fake}):
            import requests  # noqa: F401

            self.assertIs(sys.modules["requests"], fake)

    def test_factory_module_behaviour_unchanged(self):
        """No key -> no writer; with key -> a writer that posts."""
        import os

        from agents.earning.social_writer_factory import build_moltbook_writer

        os.environ.pop("MOLTBOOK_API_KEY", None)
        try:
            self.assertIsNone(build_moltbook_writer())

            fake = _make_fake_requests()
            calls = []

            class _Resp:
                status_code = 200

                def raise_for_status(self):
                    pass

                def json(self):
                    return {"post": {"id": "abc123"}}

            fake.post = lambda url, **kw: (calls.append(url), _Resp())[1]  # type: ignore[attr-defined]
            os.environ["MOLTBOOK_API_KEY"] = "k"
            with mock.patch.dict(sys.modules, {"requests": fake}):
                w = build_moltbook_writer()
                self.assertIsNotNone(w)
                result = w({"network": "moltbook", "content": "Title\nBody"})
            self.assertIn("abc123", result)
            self.assertTrue(calls and calls[0].endswith("/api/v1/posts"))
        finally:
            os.environ.pop("MOLTBOOK_API_KEY", None)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
