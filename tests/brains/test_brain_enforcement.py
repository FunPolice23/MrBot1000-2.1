"""Brain-adapter enforcement wiring (Security's cost design, Backend's wiring).

The $-budget + call-count gate lives at the brain-adapter entry (big_brain.chat /
small_brain.chat), keyed on the RESOLVED provider (self.provider) — one point
covers all four GUI doors + any future direct caller. Targets BEHAVIOUR: a cloud
brain is skipped at the cap THROUGH the adapter (proving the wiring passes the
resolved provider, not the role label); a local brain is never gated; the
limiter backstop skips when it denies; the 2-brain local path is unchanged.

Heavy __init__ side effects (DB/persona/safety) are stubbed; .env/settings.json
route through MRBOT_ENV_PATH / MRBOT_DEVICE_SETTINGS_PATH (ARCH-ENG-057).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.runtime.dual_brain import BrainConfig, BrainRole
import agents.brains.big_brain as big_mod
import agents.brains.small_brain as small_mod


class _Isolate:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = self._tmp.name
        self._saved = {k: os.environ.get(k) for k in
                       ("MRBOT_ENV_PATH", "MRBOT_DEVICE_SETTINGS_PATH")}
        os.environ["MRBOT_ENV_PATH"] = os.path.join(base, ".env")
        os.environ["MRBOT_DEVICE_SETTINGS_PATH"] = os.path.join(base, "settings.json")

    def close(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()


def _cloud_cfg():
    return BrainConfig(role=BrainRole.BIG, provider="openai",
                       endpoint="https://api.openai.com/v1", model="gpt-x",
                       device=0, context=8192)


def _local_cfg():
    return BrainConfig(role=BrainRole.BIG, provider="llamacpp",
                       endpoint="http://127.0.0.1:1234/v1", model="local-y",
                       device=0, context=8192)


class BrainEnforcementTest(unittest.TestCase):
    def setUp(self):
        self._iso = _Isolate()
        self._patches = [
            mock.patch.object(big_mod, "get_database", mock.MagicMock()),
            mock.patch.object(big_mod, "get_personality_engine", mock.MagicMock()),
            mock.patch.object(big_mod, "get_knowledge_context", mock.MagicMock()),
            mock.patch.object(big_mod, "SafetyGate", mock.MagicMock()),
            mock.patch.object(small_mod, "get_database", mock.MagicMock()),
            mock.patch.object(small_mod, "get_personality_engine", mock.MagicMock()),
            mock.patch.object(small_mod, "get_knowledge_context", mock.MagicMock()),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._iso.close()

    # ── the headline: cloud brain skipped at the cap, via the adapter entry ──
    def test_cloud_big_brain_skipped_at_cap_passes_resolved_provider(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = BigBrainAdapter(config=_cloud_cfg())
        captured = {}

        def fake_skip(provider, db):
            captured["provider"] = provider
            return (True, "daily budget exceeded for billable provider 'openai'")

        with mock.patch("agents.safety.cost.enforcement_skip_decision",
                        side_effect=fake_skip):
            out = a.chat("hello")
        self.assertEqual(captured.get("provider"), "openai",
                         "the gate must pass the RESOLVED provider, not the role")
        self.assertIn("Skipping", out)
        self.assertIn("budget", out)

    # ── the call-count backstop ─────────────────────────────────────────────
    def test_limiter_deny_skips_cloud_brain(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = BigBrainAdapter(config=_cloud_cfg())
        with mock.patch("agents.safety.cost.enforcement_skip_decision",
                        return_value=(False, "")), \
             mock.patch("agents.safety.provider_rate_limiter.get_provider_rate_limiter") as gl:
            gl.return_value.acquire.return_value = {
                "allow": False, "reason": "daily call cap reached for 'openai' (500/day)"}
            out = a.chat("hello")
        self.assertIn("Skipping", out)
        self.assertIn("call cap", out)

    # ── local brain is never gated (2-brain path unchanged) ─────────────────
    def test_local_big_brain_not_gated(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = BigBrainAdapter(config=_local_cfg())
        a.model = ""  # if the gate passes, chat reaches the model check
        captured = {}

        def fake_skip(provider, db):
            captured["provider"] = provider
            return (False, "")  # local never skipped

        with mock.patch("agents.safety.cost.enforcement_skip_decision",
                        side_effect=fake_skip), \
             mock.patch("agents.safety.provider_rate_limiter.get_provider_rate_limiter") as gl:
            gl.return_value.acquire.return_value = {"allow": True, "reason": ""}
            out = a.chat("hello")
        self.assertEqual(captured.get("provider"), "llamacpp")
        self.assertNotIn("Skipping", out, "a local brain must never be gated")
        self.assertIn("No model selected", out, "gate passed -> reached the model check")

    # ── small brain: same gate, resolved provider ───────────────────────────
    def test_cloud_small_brain_skipped_at_cap(self):
        from agents.brains.small_brain import SmallBrainAdapter
        a = SmallBrainAdapter(config=BrainConfig(
            role=BrainRole.SMALL, provider="groq",
            endpoint="https://api.groq.com/openai/v1", model="m",
            device=0, context=4096))
        captured = {}

        def fake_skip(provider, db):
            captured["provider"] = provider
            return (True, "daily budget exceeded for billable provider 'groq'")

        with mock.patch("agents.safety.cost.enforcement_skip_decision",
                        side_effect=fake_skip):
            out = a.chat("hello")
        self.assertEqual(captured.get("provider"), "groq")
        self.assertIn("Skipping", out)

    # ── fail-open: a broken guard must not block a call ─────────────────────
    def test_broken_guard_fails_open(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = BigBrainAdapter(config=_local_cfg())
        a.model = ""
        with mock.patch("agents.safety.cost.enforcement_skip_decision",
                        side_effect=RuntimeError("guard db down")):
            out = a.chat("hello")
        # fails open -> not skipped -> reaches the model check
        self.assertNotIn("Skipping", out)
        self.assertIn("No model selected", out)


if __name__ == "__main__":
    unittest.main()
