"""Phase 1 (part 2) — cloud providers in the runtime config + adapter key wiring.

Targets BEHAVIOUR: a configured cloud provider is no longer silently coerced to
local llamacpp, its endpoint resolves correctly, and the brain adapters'
_get_client() now sources a real (or fail-closed "") key per provider while
local providers keep the "local" sentinel unchanged. Each test FAILS if a cloud
provider is dropped, mis-endpointed, or sent the "local" sentinel.
"""
import sys
import unittest
from unittest import mock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.runtime.dual_brain import (
    BrainRole, build_config, CLOUD_PROVIDER_DEFAULT_ENDPOINTS,
    SUPPORTED_PROVIDERS, PROVIDER_LLAMACPP,
)
import agents.runtime.provider_keys as pk


class CloudProviderConfigTest(unittest.TestCase):
    # ── build_config: a cloud provider is honoured, not coerced ────────────
    def test_cloud_provider_not_coerced_to_llamacpp(self):
        cfg = build_config(BrainRole.BIG, env={"BIG_BRAIN_PROVIDER": "openai"})
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.endpoint, "https://api.openai.com/v1")

    def test_all_cloud_providers_supported_with_default_endpoints(self):
        for provider, endpoint in CLOUD_PROVIDER_DEFAULT_ENDPOINTS.items():
            self.assertIn(provider, SUPPORTED_PROVIDERS)
            cfg = build_config(BrainRole.BIG, env={"BIG_BRAIN_PROVIDER": provider})
            self.assertEqual(cfg.provider, provider)
            self.assertEqual(cfg.endpoint, endpoint)

    def test_provider_base_url_env_overrides_cloud_default(self):
        cfg = build_config(
            BrainRole.BIG,
            env={"BIG_BRAIN_PROVIDER": "openai",
                 "OPENAI_BASE_URL": "https://my-proxy.example/v1"})
        self.assertEqual(cfg.endpoint, "https://my-proxy.example/v1")

    def test_role_url_overrides_cloud_default(self):
        cfg = build_config(
            BrainRole.SMALL,
            env={"SMALL_BRAIN_PROVIDER": "nvidia_nim",
                 "SMALL_BRAIN_URL": "http://127.0.0.1:9999/v1"})
        self.assertEqual(cfg.provider, "nvidia_nim")
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:9999/v1")

    def test_local_provider_unchanged(self):
        cfg = build_config(BrainRole.BIG, env={})
        self.assertEqual(cfg.provider, PROVIDER_LLAMACPP)
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:1234/v1")


class AdapterClientKeyTest(unittest.TestCase):
    """_get_client() must source the key per provider (via __new__ to skip
    __init__'s DB/persona/safety side effects)."""

    def _adapter(self, cls, provider, base_url):
        a = cls.__new__(cls)
        a.base_url = base_url
        a.provider = provider
        return a

    def test_big_brain_cloud_key_resolved(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = self._adapter(BigBrainAdapter, "openai", "https://api.openai.com/v1")
        with mock.patch.object(pk, "resolve_provider_api_key",
                               return_value="REAL_KEY_abc"):
            client = a._get_client()
        self.assertEqual(client.api_key, "REAL_KEY_abc")

    def test_small_brain_cloud_key_resolved(self):
        from agents.brains.small_brain import SmallBrainAdapter
        a = self._adapter(SmallBrainAdapter, "groq",
                          "https://api.groq.com/openai/v1")
        with mock.patch.object(pk, "resolve_provider_api_key",
                               return_value="REAL_KEY_xyz"):
            client = a._get_client()
        self.assertEqual(client.api_key, "REAL_KEY_xyz")

    def test_local_provider_keeps_local_sentinel(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = self._adapter(BigBrainAdapter, "llamacpp", "http://127.0.0.1:1234/v1")
        client = a._get_client()  # real resolver: local -> "local", no vault
        self.assertEqual(client.api_key, "local")

    def test_cloud_without_key_fails_closed_not_local(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = self._adapter(BigBrainAdapter, "openai", "https://api.openai.com/v1")
        with mock.patch.object(pk, "resolve_provider_api_key", return_value=""):
            client = a._get_client()
        self.assertEqual(client.api_key, "")
        self.assertNotEqual(client.api_key, "local",
                            "a paid endpoint must never get the 'local' sentinel")


if __name__ == "__main__":
    unittest.main()
