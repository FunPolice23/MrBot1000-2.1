"""Phase 2 — per-slot adapter config: BigBrainAdapter/SmallBrainAdapter accept a
BrainConfig and seed base_url/model/provider/device/context from it; no config
-> the legacy env path, byte-identical. _get_client already resolves the key
from self.provider (provider_keys), so a cloud config yields the resolved key
and a local config yields "local".

Isolation: adapter __init__ touches DB/persona/device persistence, so .env +
settings.json route through MRBOT_ENV_PATH / MRBOT_DEVICE_SETTINGS_PATH
(ARCH-ENG-057) into a temp dir.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# ARCH-ENG-149: the repo root is derived from THIS file, never hardcoded. The
# literal `D:\MrBot1000_2.0` made a fresh clone import the LIVE repo's modules,
# so conftest's `import main` loaded the live main.py and its load_dotenv pushed
# the operator's real .env (BIG_BRAIN_PROVIDER=lmstudio) into os.environ — the
# legacy-default tests then failed against operator config instead of defaults,
# and only ever passed when run from the original tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.runtime.dual_brain import BrainConfig, BrainRole
import agents.runtime.provider_keys as pk
import agents.brains.big_brain as big_mod
import agents.brains.small_brain as small_mod


class _Isolate:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = self._tmp.name
        # MRBOT_ENV_PATH/MRBOT_DEVICE_SETTINGS_PATH redirect config WRITES, but
        # build_config READS the provider straight from os.environ — and the
        # session-scoped conftest fixture `import main` runs load_dotenv, which
        # seeds BIG/SMALL_BRAIN_PROVIDER from whatever .env is on the path. To
        # make "no config -> legacy defaults" mean the DEFAULTS, those reads are
        # neutralised for the duration and restored byte-for-byte afterwards.
        self._saved = {k: os.environ.get(k) for k in (
            "MRBOT_ENV_PATH", "MRBOT_DEVICE_SETTINGS_PATH",
            "BIG_BRAIN_PROVIDER", "SMALL_BRAIN_PROVIDER",
        )}
        os.environ["MRBOT_ENV_PATH"] = os.path.join(base, ".env")
        os.environ["MRBOT_DEVICE_SETTINGS_PATH"] = os.path.join(base, "settings.json")
        for k in ("BIG_BRAIN_PROVIDER", "SMALL_BRAIN_PROVIDER"):
            os.environ.pop(k, None)

    def close(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()


class AdapterConfigTest(unittest.TestCase):
    def setUp(self):
        self._iso = _Isolate()
        for k in list(os.environ):
            if k.startswith("PROVIDER_API_KEY_") or k.endswith("_API_KEY"):
                os.environ.pop(k, None)
        # Stub the heavy __init__ side effects (DB/persona/safety) so adapter
        # construction is light and never touches operator .env/settings.json.
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

    def _cloud_cfg(self, role=BrainRole.BIG):
        return BrainConfig(role=role, provider="openai",
                           endpoint="https://api.openai.com/v1",
                           model="gpt-x", device=0, context=8192)

    def _local_cfg(self, role=BrainRole.BIG):
        return BrainConfig(role=role, provider="llamacpp",
                           endpoint="http://127.0.0.1:1234/v1",
                           model="local-y", device=0, context=8192)

    # ── config seeds the adapter ───────────────────────────────────────────
    def test_big_adapter_config_seeds_fields(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = BigBrainAdapter(config=self._cloud_cfg())
        self.assertEqual(a.provider, "openai")
        self.assertEqual(a.base_url, "https://api.openai.com/v1")
        self.assertEqual(a.model, "gpt-x")
        self.assertEqual(a.context_length, 8192)

    def test_small_adapter_config_seeds_fields(self):
        from agents.brains.small_brain import SmallBrainAdapter
        a = SmallBrainAdapter(config=self._cloud_cfg())
        self.assertEqual(a.provider, "openai")
        self.assertEqual(a.base_url, "https://api.openai.com/v1")
        self.assertEqual(a.model, "gpt-x")

    def test_explicit_model_arg_overrides_config(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = BigBrainAdapter(model="explicit-m", config=self._cloud_cfg())
        self.assertEqual(a.model, "explicit-m", "an explicit model arg wins")

    # ── _get_client key resolution follows the config's provider ───────────
    def test_cloud_config_get_client_uses_resolved_key(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = BigBrainAdapter(config=self._cloud_cfg())
        with __import__("unittest.mock", fromlist=["mock"]).patch.object(
                pk, "resolve_provider_api_key", return_value="RESOLVED_KEY"):
            client = a._get_client()
        self.assertEqual(client.api_key, "RESOLVED_KEY")

    def test_local_config_get_client_uses_local_sentinel(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = BigBrainAdapter(config=self._local_cfg())
        client = a._get_client()  # local -> "local", no vault
        self.assertEqual(client.api_key, "local")

    # ── back-compat: no config -> legacy env path ──────────────────────────
    def test_no_config_big_is_legacy(self):
        from agents.brains.big_brain import BigBrainAdapter
        a = BigBrainAdapter()  # no config, isolated env -> defaults
        self.assertEqual(a.provider, "llamacpp")
        self.assertEqual(a.base_url, "http://127.0.0.1:1234/v1")

    def test_no_config_small_is_legacy(self):
        from agents.brains.small_brain import SmallBrainAdapter
        a = SmallBrainAdapter()
        self.assertEqual(a.provider, "llamacpp")
        self.assertEqual(a.base_url, "http://127.0.0.1:1235/v1")


if __name__ == "__main__":
    unittest.main()
