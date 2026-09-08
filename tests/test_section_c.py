"""Canonical tests for Section C (platform safety & ToS).

Run individually:  python -m unittest tests.test_section_c
Via suite:         python -m tests --test test_section_c

All tests are mock-first / offline (no live network, no credentials).
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class FakeClock:
    """Deterministic clock so TokenBucket tests never really sleep."""
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def advance(self, d):
        self.t += d


class TestPlatformThrottle(unittest.TestCase):
    def setUp(self):
        self.fc = FakeClock()
        self._patchers = [
            patch("library.time", self.fc),
        ]
        for p in self._patchers:
            p.start()
        # Fresh singleton per test.
        import agents.platform_throttle as pt
        pt._THROTTLE = None

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def test_burst_capacity_instant(self):
        from library import TokenBucket
        b = TokenBucket(rate=1.0, capacity=5.0)
        for _ in range(5):
            b.acquire()  # burst of 5 must be immediate
        self.fc.advance(1.0)
        b.acquire()  # refill 1 token after 1s

    def test_env_rate_override(self):
        import agents.platform_throttle as pt
        os.environ["RATE_UPWORK"] = "0.5"
        try:
            pt.get_throttle().reset()
            bk = pt.get_throttle()._bucket("upwork")
            self.assertAlmostEqual(bk._rate, 0.5, places=6)
        finally:
            del os.environ["RATE_UPWORK"]
            pt.get_throttle().reset()

    def test_source_to_platform_mapping(self):
        import agents.platform_throttle as pt
        tb = pt.PlatformThrottle()
        for s in ["upwork", "fiverr", "microtask", "airdrop", "defi", "social"]:
            tb.acquire(s)
        # content/dynamic map to 'web'
        tb.acquire("content")
        tb.acquire("dynamic")
        self.assertIn("web", tb._buckets)

    def test_singleton_shared(self):
        import agents.platform_throttle as pt
        pt._THROTTLE = None
        self.assertIs(pt.get_throttle(), pt.get_throttle())

    def test_unknown_platform_defaults(self):
        import agents.platform_throttle as pt
        tb = pt.PlatformThrottle()
        tb.acquire("totally_unknown_platform_xyz")  # must not raise
        self.assertIn("totally_unknown_platform_xyz", tb._buckets)

    def test_find_gigs_throttled(self):
        """Client find_gigs calls the throttle (mocked) without error."""
        import agents.platform_throttle as pt
        calls = []
        orig = pt.get_throttle

        class FakeThrottle:
            def acquire(self, platform, tokens=1.0):
                calls.append(platform)

        pt.get_throttle = lambda: FakeThrottle()
        try:
            from agents.fiverr_client import FiverrClient
            from unittest.mock import MagicMock
            c = FiverrClient()
            c._parse_search = MagicMock(return_value=[])
            c.find_gigs(query="python")
            self.assertIn("fiverr", calls)
        finally:
            pt.get_throttle = orig


class FakeRepMemory:
    """Minimal EarningMemory stand-in for ramp tests."""
    def __init__(self):
        self.data = {}

    def get_platform_reputation(self, p):
        return self.data.get(
            p, {"success": 0, "failed": 0, "total": 0, "success_rate": 0.0})

    def record_win(self, p, revenue=0.0):
        d = self.data.setdefault(
            p, {"success": 0, "failed": 0, "total": 0, "success_rate": 0.0})
        d["success"] += 1
        d["total"] += 1
        d["success_rate"] = d["success"] / d["total"]

    def record_loss(self, p):
        d = self.data.setdefault(
            p, {"success": 0, "failed": 0, "total": 0, "success_rate": 0.0})
        d["failed"] += 1
        d["total"] += 1
        d["success_rate"] = d["success"] / d["total"]

    def record_attempt(self, p):
        # H39: submission bumps total_attempts WITHOUT a success.
        d = self.data.setdefault(
            p, {"success": 0, "failed": 0, "total": 0, "success_rate": 0.0})
        d["total"] += 1


class TestSubmissionRamp(unittest.TestCase):
    def setUp(self):
        import agents.submission_ramp as sr
        sr._RAMP = None  # fresh singleton

    def test_cold_start_requires_human(self):
        from agents.submission_ramp import SubmissionRamp
        r = SubmissionRamp(memory=FakeRepMemory(),
                           min_submissions=5, win_rate_threshold=0.6)
        self.assertTrue(r.requires_human("Upwork"))

    def test_low_win_rate_stays_human(self):
        from agents.submission_ramp import SubmissionRamp
        mem = FakeRepMemory()
        for _ in range(5):
            mem.record_loss("Upwork")
        r = SubmissionRamp(memory=mem, min_submissions=5,
                           win_rate_threshold=0.6)
        self.assertTrue(r.requires_human("Upwork"))

    def test_unlocked_after_wins(self):
        from agents.submission_ramp import SubmissionRamp
        mem = FakeRepMemory()
        for _ in range(5):
            mem.record_win("Upwork")
        r = SubmissionRamp(memory=mem, min_submissions=5,
                           win_rate_threshold=0.6)
        self.assertFalse(r.requires_human("Upwork"))

    def test_ai_disallowed_forces_human(self):
        from agents.submission_ramp import SubmissionRamp
        mem = FakeRepMemory()
        for _ in range(5):
            mem.record_win("Upwork")
        r = SubmissionRamp(memory=mem, min_submissions=5,
                           win_rate_threshold=0.6)
        self.assertTrue(r.requires_human("Upwork", ai_policy="ai_disallowed"))
        self.assertTrue(r.requires_human("Upwork", ai_policy="human_only"))

    def test_env_overrides(self):
        from agents.submission_ramp import SubmissionRamp
        os.environ["RAMP_MIN_SUBMISSIONS"] = "3"
        os.environ["RAMP_WIN_RATE"] = "0.5"
        try:
            r = SubmissionRamp(memory=FakeRepMemory())
            self.assertEqual(r.min_submissions, 3)
            self.assertAlmostEqual(r.win_rate_threshold, 0.5)
        finally:
            del os.environ["RAMP_MIN_SUBMISSIONS"]
            del os.environ["RAMP_WIN_RATE"]

    def test_record_outcome_persists(self):
        # Deprecated alias: records a SUBMISSION (attempt), not a win.
        from agents.submission_ramp import SubmissionRamp
        mem = FakeRepMemory()
        r = SubmissionRamp(memory=mem)
        before = mem.get_platform_reputation("Upwork")["total"]
        r.record_outcome("Upwork", accepted=True)
        rep = mem.get_platform_reputation("Upwork")
        self.assertEqual(rep["total"], before + 1)
        # H39: a submission does NOT credit a success.
        self.assertEqual(rep["success"], 0)

    def test_h39_submission_is_not_a_win(self):
        """H39 fix: record_submission bumps total but NOT success_rate."""
        from agents.submission_ramp import SubmissionRamp
        mem = FakeRepMemory()
        r = SubmissionRamp(memory=mem)
        for _ in range(5):
            r.record_submission("Upwork")
        rep = mem.get_platform_reputation("Upwork")
        self.assertEqual(rep["total"], 5)
        self.assertEqual(rep["success"], 0)
        # Cold-start still requires human because success_rate == 0.
        self.assertTrue(r.requires_human("Upwork"))

    def test_h39_real_accept_unlocks(self):
        """H39 fix: a real accept (not a submission) is what unlocks auto."""
        from agents.submission_ramp import SubmissionRamp
        mem = FakeRepMemory()
        r = SubmissionRamp(memory=mem, min_submissions=5,
                           win_rate_threshold=0.6)
        for _ in range(5):
            r.record_submission("Upwork")        # 5 submissions (total=5)
        self.assertTrue(r.requires_human("Upwork"))  # still human (0 wins)
        for _ in range(8):
            r.record_accept("Upwork")             # 8 real accepts (total=13, rate~0.62)
        self.assertFalse(r.requires_human("Upwork"))  # now unlocked

    def test_h39_real_reject_counts_loss(self):
        from agents.submission_ramp import SubmissionRamp
        mem = FakeRepMemory()
        r = SubmissionRamp(memory=mem)
        r.record_submission("Upwork")
        r.record_reject("Upwork")
        rep = mem.get_platform_reputation("Upwork")
        self.assertEqual(rep["total"], 2)
        self.assertEqual(rep["failed"], 1)
        self.assertEqual(rep["success"], 0)

    def test_no_memory_is_safe(self):
        from agents.submission_ramp import SubmissionRamp
        r = SubmissionRamp(memory=None)
        self.assertTrue(r.requires_human("Upwork"))


class TestScrapeResilience(unittest.TestCase):
    def setUp(self):
        import time as _t
        self._real_sleep = _t.sleep
        _t.sleep = lambda s: None  # no real waits in tests
        self.addCleanup(lambda: setattr(_t, "sleep", self._real_sleep))

    def test_ua_rotation_differs(self):
        from agents.scrape_resilience import pick_ua
        self.assertNotEqual(pick_ua(rotate=True, idx=0),
                            pick_ua(rotate=True, idx=1))
        self.assertEqual(pick_ua(rotate=False), pick_ua(rotate=False))

    def test_captcha_detection(self):
        from agents.scrape_resilience import detect_captcha
        self.assertTrue(detect_captcha(
            "<html>please verify you are human recaptcha</html>"))
        self.assertFalse(detect_captcha("<html>normal listings</html>"))

    def _fake_resp(self, status, headers=None, text=""):
        class R:
            def __init__(self, s, h, t):
                self.status_code = s
                self.headers = h or {}
                self.text = t
        return R(status, headers, text)

    def test_429_then_success(self):
        from agents.scrape_resilience import retry_on_429
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            if calls["n"] == 1:
                return self._fake_resp(429, {"Retry-After": "2"}, "slow")
            return self._fake_resp(200, {}, "ok")
        out = retry_on_429(fn, max_retries=3)
        self.assertEqual(out.status_code, 200)
        self.assertEqual(calls["n"], 2)

    def test_429_exhaustion_raises(self):
        from agents.scrape_resilience import retry_on_429, RateLimitedError
        def fn():
            return self._fake_resp(429, {"Retry-After": "1"}, "slow")
        with self.assertRaises(RateLimitedError):
            retry_on_429(fn, max_retries=2)

    def test_captcha_body_raises(self):
        from agents.scrape_resilience import retry_on_429, CaptchaBlockedError
        def fn():
            return self._fake_resp(429, {"Retry-After": "1"},
                                    "verify you are human recaptcha")
        with self.assertRaises(CaptchaBlockedError):
            retry_on_429(fn, max_retries=2)

    def test_network_error_reraised(self):
        from agents.scrape_resilience import retry_on_429
        class Boom:
            @property
            def status_code(self):
                raise RuntimeError("down")
        with self.assertRaises(RuntimeError):
            retry_on_429(lambda: Boom(), max_retries=2)

    def test_retry_after_capped(self):
        from agents.scrape_resilience import _parse_retry_after
        v = _parse_retry_after("Mon, 01 Jan 2030 00:00:00 GMT", 5.0)
        self.assertLessEqual(v, 60.0)
        self.assertGreater(v, 0)

    def test_fiverr_captcha_empty(self):
        from agents.fiverr_client import FiverrClient
        from unittest.mock import MagicMock, patch
        c = FiverrClient()
        fake = MagicMock()
        fake.status_code = 200
        fake.text = "please verify you are human recaptcha"
        fake.raise_for_status = MagicMock()
        with patch.object(c.session, "get", return_value=fake):
            self.assertEqual(c._parse_search("python"), [])


class TestThrottleDrawCount(unittest.TestCase):
    """H41 regression: one client discovery must draw at most 2 throttle tokens
    (discover-loop acquire + client find_gigs acquire), not 3."""

    def test_upwork_max_two_draws(self):
        import agents.platform_throttle as pt
        pt._THROTTLE = None
        calls = []
        orig = pt.PlatformThrottle

        class Counting(orig):
            def acquire(self, platform, tokens=1.0):
                calls.append(platform)
                b = self._bucket(platform)
                b._tokens = max(0.0, b._tokens - tokens)

        pt.PlatformThrottle = Counting
        try:
            from unittest.mock import MagicMock, patch
            from agents.upwork_client import UpworkClient
            c = UpworkClient.__new__(UpworkClient)
            fake = MagicMock(); fake.status_code = 200
            fake.json.return_value = {"jobs": []}
            fake.raise_for_status = MagicMock()
            with patch.object(c, "_request", return_value=fake):
                pt.get_throttle().acquire("upwork")  # pipeline discover loop
                c.find_gigs(q="python", limit=5)
            up = [p for p in calls if p == "upwork"]
            self.assertLessEqual(len(up), 2)
        finally:
            pt.PlatformThrottle = orig


if __name__ == "__main__":
    unittest.main()
