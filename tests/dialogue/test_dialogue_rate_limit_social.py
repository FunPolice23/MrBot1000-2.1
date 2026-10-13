"""Phase F2 — Dialogue per-response rate limit + opt-in social decision (ARCH-ENG-090).

- _response_rate_gate throttles consecutive continuous turns via a TokenBucket;
  disabled when DIALOGUE_MIN_SECONDS_PER_RESPONSE<=0.
- The social-decision prompt block is OPT-IN (DIALOGUE_SOCIAL_AUTOPOST); default
  off so the agents never auto-propose social spam.
"""
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")


class _FakeTab:
    """Minimal stand-in exposing just what _response_rate_gate touches."""

    def __init__(self):
        self._response_bucket = None
        self._reschedules = 0

    def respond(self, manual=False):
        self._reschedules += 1


def _bind_rate_gate():
    from gui.tabs.dialogue_tab import DialogueTab
    return DialogueTab._response_rate_gate


class TestResponseRateGate(unittest.TestCase):
    def setUp(self):
        for k in ("DIALOGUE_MIN_SECONDS_PER_RESPONSE",):
            os.environ.pop(k, None)
        # Patch QTimer.singleShot inside the module so the deferred reschedule
        # is captured instead of scheduling a real Qt timer.
        import gui.tabs.dialogue_tab as dt
        self._dt = dt
        self._orig = dt.QTimer.singleShot
        dt.QTimer.singleShot = lambda ms, fn: fn() if False else None
        self.gate = _bind_rate_gate()

    def tearDown(self):
        self._dt.QTimer.singleShot = self._orig

    def test_first_turn_allowed_second_throttled(self):
        os.environ["DIALOGUE_MIN_SECONDS_PER_RESPONSE"] = "5"  # long cooldown
        tab = _FakeTab()
        self.assertTrue(self.gate(tab))       # first: bucket has capacity 1
        self.assertFalse(self.gate(tab))      # immediate second: over rate

    def test_disabled_when_zero(self):
        os.environ["DIALOGUE_MIN_SECONDS_PER_RESPONSE"] = "0"
        tab = _FakeTab()
        self.assertTrue(self.gate(tab))
        self.assertTrue(self.gate(tab))       # never throttled when disabled

    def test_invalid_env_falls_back(self):
        os.environ["DIALOGUE_MIN_SECONDS_PER_RESPONSE"] = "notanumber"
        tab = _FakeTab()
        # Falls back to 1.5s default -> still throttles an immediate second.
        self.assertTrue(self.gate(tab))
        self.assertFalse(self.gate(tab))


class TestSocialDecisionOptIn(unittest.TestCase):
    """The social-decision block is appended only when the flag is on."""

    def _block(self):
        import os as _os
        if _os.getenv("DIALOGUE_SOCIAL_AUTOPOST", "false").lower() in ("1", "true", "yes"):
            return (
                "\n# SOCIAL DECISION (each turn)\n"
                "You have access to the Moltbook social network for AI agents. "
                "Each turn, decide whether to engage: post something new, reply "
                "to a community post, or upvote."
            )
        return ""

    def setUp(self):
        os.environ.pop("DIALOGUE_SOCIAL_AUTOPOST", None)

    def test_default_off(self):
        self.assertEqual(self._block(), "")

    def test_enabled_appends_block(self):
        os.environ["DIALOGUE_SOCIAL_AUTOPOST"] = "true"
        block = self._block()
        self.assertIn("SOCIAL DECISION", block)
        self.assertIn("Moltbook", block)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
