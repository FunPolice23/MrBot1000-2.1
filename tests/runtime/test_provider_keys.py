"""Phase 1 — provider_keys: the cloud-provider API-key resolution layer.

Targets BEHAVIOUR (local sentinel, vault/env resolution order, fail-closed "" for
an unconfigured cloud provider, and the never-logs invariant), so each test FAILS
if the resolver leaks a key, sends "local" to a paid endpoint, or guesses.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, r"D:\MrBot1000_2.0")

import agents.runtime.provider_keys as pk
from agents.runtime.provider_keys import resolve_provider_api_key, is_local_provider


class ProviderKeysTest(unittest.TestCase):
    def setUp(self):
        # Isolate from any real vault / ambient env for every test.
        self._env = dict(os.environ)
        for k in list(os.environ):
            if k.startswith("PROVIDER_API_KEY_") or k.endswith("_API_KEY"):
                os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def _no_vault(self):
        return mock.patch.object(pk, "_vault_key", lambda provider: "")

    def test_local_providers_return_local_sentinel(self):
        for p in ("llamacpp", "ollama", "lmstudio", "vllm", "koboldcpp"):
            with self._no_vault():
                self.assertEqual(resolve_provider_api_key(p), "local", p)
        self.assertTrue(is_local_provider("Ollama"))

    def test_local_provider_never_touches_vault(self):
        # A local provider must resolve without any vault/env lookup at all.
        with mock.patch.object(pk, "_vault_key",
                               side_effect=AssertionError("vault touched")):
            self.assertEqual(resolve_provider_api_key("llamacpp"), "local")

    def test_cloud_uses_vault_key_first(self):
        with mock.patch.object(pk, "_vault_key", lambda p: "VAULT_KEY_abc"):
            self.assertEqual(resolve_provider_api_key("openai"), "VAULT_KEY_abc")

    def test_cloud_falls_back_to_provider_env(self):
        with self._no_vault():
            os.environ["PROVIDER_API_KEY_OPENAI"] = "ENV_KEY_xyz"
            self.assertEqual(resolve_provider_api_key("openai"), "ENV_KEY_xyz")

    def test_cloud_falls_back_to_role_env(self):
        with self._no_vault():
            os.environ["BIG_API_KEY"] = "ROLE_KEY_123"
            self.assertEqual(
                resolve_provider_api_key("anthropic", role_prefix="big"),
                "ROLE_KEY_123")

    def test_cloud_without_any_key_fails_closed_to_empty(self):
        with self._no_vault():
            self.assertEqual(resolve_provider_api_key("openai"), "")
            self.assertEqual(
                resolve_provider_api_key("nvidia_nim", role_prefix="small"), "")

    def test_empty_provider_returns_empty(self):
        with self._no_vault():
            self.assertEqual(resolve_provider_api_key(""), "")
            self.assertEqual(resolve_provider_api_key(None), "")

    def test_resolution_never_logs_the_key(self):
        secret = "SUPER_SECRET_KEY_9f3a"
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with mock.patch.object(pk, "_vault_key", lambda p: secret):
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                got = resolve_provider_api_key("openai")
        self.assertEqual(got, secret, "the key is still returned to the caller")
        self.assertNotIn(secret, buf_out.getvalue(), "key must never hit stdout")
        self.assertNotIn(secret, buf_err.getvalue(), "key must never hit stderr")


if __name__ == "__main__":
    unittest.main()
