"""Phase 4 runtime — roster-aware build_config + DualBrainRuntime entry points.

Targets BEHAVIOUR: roster=None keeps the legacy env path byte-identical (the
back-compat guard that keeps the pinned *_MAIN_ENABLED tests green); a supplied
roster drives provider/model/endpoint per role through the SAME endpoint
resolver the legacy path uses. Each test FAILS if the roster path is ignored,
mis-resolves an endpoint, or the legacy path drifts.

Isolation: constructing DualBrainRuntime touches device-registry persistence, so
every test routes .env + settings.json through MRBOT_ENV_PATH /
MRBOT_DEVICE_SETTINGS_PATH (ARCH-ENG-057) into a temp dir — the operator's live
config is never touched.
"""
import os
import sys
import tempfile
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.runtime.dual_brain import (
    BrainRole, build_config, DualBrainRuntime, _resolve_provider_endpoint,
    ROLE_DEFAULTS,
)
from agents.runtime.brain_roster import BrainRoster, BrainSlot


class RosterAwareConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = self._tmp.name
        self._saved = {k: os.environ.get(k) for k in
                       ("MRBOT_ENV_PATH", "MRBOT_DEVICE_SETTINGS_PATH")}
        os.environ["MRBOT_ENV_PATH"] = os.path.join(base, ".env")
        os.environ["MRBOT_DEVICE_SETTINGS_PATH"] = os.path.join(base, "settings.json")

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    # ── back-compat: roster=None -> legacy env path, byte-identical ─────────
    def test_no_roster_uses_legacy_env_path(self):
        cfg = build_config(BrainRole.BIG, env={})  # roster defaults to None
        self.assertEqual(cfg.provider, "llamacpp")
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:1234/v1")

    def test_no_roster_legacy_provider_env_still_honored(self):
        cfg = build_config(BrainRole.BIG, env={"BIG_BRAIN_PROVIDER": "ollama"})
        self.assertEqual(cfg.provider, "ollama")
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:11434/v1")

    # ── roster drives the config ───────────────────────────────────────────
    def test_roster_cloud_slot_drives_provider_model_endpoint(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", provider="openai", model="gpt-x",
                           device_id="gpu0")],
            small=[BrainSlot(tier="small")])
        cfg = build_config(BrainRole.BIG, env={}, roster=roster)
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.model, "gpt-x")
        self.assertEqual(cfg.endpoint, "https://api.openai.com/v1")

    def test_roster_local_slot_drives_model_and_loopback_endpoint(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", provider="llamacpp", model="local-y",
                           device_id="gpu0")],
            small=[])
        cfg = build_config(BrainRole.BIG, env={}, roster=roster)
        self.assertEqual(cfg.provider, "llamacpp")
        self.assertEqual(cfg.model, "local-y")
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:1234/v1")

    def test_roster_disabled_slot_falls_through_to_next_enabled(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", enabled=False, provider="openai",
                           model="gpt"),
                 BrainSlot(tier="big", enabled=True, provider="llamacpp",
                           model="local")],
            small=[])
        cfg = build_config(BrainRole.BIG, env={}, roster=roster)
        self.assertEqual(cfg.provider, "llamacpp", "disabled slot is skipped")

    def test_roster_cloud_endpoint_env_override(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", provider="openai", model="gpt")], small=[])
        cfg = build_config(BrainRole.BIG,
                           env={"OPENAI_BASE_URL": "https://proxy.example/v1"},
                           roster=roster)
        self.assertEqual(cfg.endpoint, "https://proxy.example/v1")

    def test_roster_with_no_enabled_slot_for_role_falls_back_to_legacy(self):
        roster = BrainRoster(big=[], small=[BrainSlot(tier="small")])
        cfg = build_config(BrainRole.BIG, env={}, roster=roster)
        self.assertEqual(cfg.provider, "llamacpp", "no enabled big -> legacy path")
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:1234/v1")

    # ── shared endpoint resolver (no drift between legacy and roster) ──────
    def test_legacy_and_roster_share_endpoint_resolver(self):
        defaults = ROLE_DEFAULTS[BrainRole.BIG]
        legacy_default, _ = _resolve_provider_endpoint("ollama", defaults, {})
        self.assertEqual(legacy_default, "http://127.0.0.1:11434/v1")

    # ── runtime entry points ───────────────────────────────────────────────
    def test_from_roster_builds_both_roles(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", provider="openai", model="gpt")],
            small=[BrainSlot(tier="small", provider="groq", model="m")])
        rt = DualBrainRuntime.from_roster(roster, env={})
        self.assertEqual(rt.config(BrainRole.BIG).provider, "openai")
        self.assertEqual(rt.config(BrainRole.SMALL).provider, "groq")

    def test_from_settings_no_roster_is_legacy(self):
        # No roster persisted (env-isolated settings.json is empty) -> legacy.
        rt = DualBrainRuntime.from_settings(env={})
        self.assertEqual(rt.config(BrainRole.BIG).provider, "llamacpp")
        self.assertEqual(rt.config(BrainRole.BIG).endpoint,
                         "http://127.0.0.1:1234/v1")

    def test_from_settings_with_roster_is_roster_driven(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", provider="openai", model="gpt")],
            small=[BrainSlot(tier="small")])
        self.assertTrue(roster.save())  # -> env-isolated settings.json
        rt = DualBrainRuntime.from_settings(env={})
        self.assertEqual(rt.config(BrainRole.BIG).provider, "openai")
        self.assertEqual(rt.config(BrainRole.BIG).model, "gpt")

    # ── P1/P2 fix: roster path preserves tuned flags + decision_support_only ──
    def test_roster_cpu_small_slot_gets_decision_support(self):
        # A CPU small roster slot (local, no device_id) must get the
        # decision-support posture back (Security's P2 fix) + gpu_layers 0.
        roster = BrainRoster(
            big=[],
            small=[BrainSlot(tier="small", provider="llamacpp", model="s",
                             device_id="")])
        cfg = build_config(BrainRole.SMALL, env={}, roster=roster)
        self.assertTrue(cfg.decision_support_only,
                        "a CPU roster slot must keep the advisory-only posture")
        self.assertEqual(cfg.gpu_layers, 0, "CPU slot is system-RAM only")

    def test_roster_gpu_slot_not_decision_support(self):
        roster = BrainRoster(
            big=[BrainSlot(tier="big", provider="llamacpp", model="b",
                           device_id="gpu0")],
            small=[])
        cfg = build_config(BrainRole.BIG, env={}, roster=roster)
        self.assertFalse(cfg.decision_support_only)

    def test_roster_preserves_operator_tuned_flags(self):
        # The roster path must NOT reset operator-tuned llama.cpp flags to
        # factory (the flags-reset P1): it starts from the legacy env config.
        env = {"BIG_BRAIN_FLASH_ATTN": "1", "BIG_BRAIN_CONTEXT": "9999",
               "BIG_BRAIN_THREADS": "6"}
        roster = BrainRoster(
            big=[BrainSlot(tier="big", provider="llamacpp", model="b",
                           device_id="gpu0")],
            small=[])
        cfg = build_config(BrainRole.BIG, env=env, roster=roster)
        self.assertEqual(cfg.flash_attn, "1", "flash_attn must survive the roster path")
        self.assertEqual(cfg.context, 9999, "context must survive the roster path")
        self.assertEqual(cfg.threads, 6, "threads must survive the roster path")
        # roster-driven identity still applies
        self.assertEqual(cfg.model, "b")


if __name__ == "__main__":
    unittest.main()
