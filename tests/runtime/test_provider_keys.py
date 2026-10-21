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

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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

    def test_cloud_reads_the_standard_provider_env_spelling(self):
        """ARCH-ENG-137: the Settings GUI persists <PROVIDER>_API_KEY.

        Before this, the chain checked only PROVIDER_API_KEY_<PROVIDER> and
        <ROLE>_API_KEY — names NOTHING in the repo writes. The Settings GUI
        (main.py:2705) and provider detection (provider_manager key_env) both
        use the standard <PROVIDER>_API_KEY, so a correctly-configured cloud
        brain failed closed and 401'd on every call, silently.
        """
        with self._no_vault():
            for provider, env_name in (
                ("openai", "OPENAI_API_KEY"),
                ("anthropic", "ANTHROPIC_API_KEY"),
                ("groq", "GROQ_API_KEY"),
                ("openrouter", "OPENROUTER_API_KEY"),
                ("together", "TOGETHER_API_KEY"),
            ):
                os.environ[env_name] = f"KEY_FOR_{provider}"
                with self.subTest(provider=provider):
                    self.assertEqual(
                        resolve_provider_api_key(provider), f"KEY_FOR_{provider}",
                        f"{env_name} is the spelling the GUI writes — it must "
                        "resolve, not fail closed")

    def test_nvidia_spelling_alias_resolves(self):
        """The runtime keys NIM as nvidia_nim; the GUI writes NVIDIA_API_KEY."""
        with self._no_vault():
            os.environ["NVIDIA_API_KEY"] = "NVIDIA_KEY_1"
            for provider in ("nvidia_nim", "nvidia"):
                with self.subTest(provider=provider):
                    self.assertEqual(
                        resolve_provider_api_key(provider), "NVIDIA_KEY_1")

    def test_local_provider_never_consults_the_env_key_chain(self):
        """lmstudio is ON-MACHINE — it returns "local", never an API key.

        This is the invariant my first draft of the alias table violated: adding
        an ``lmstudio -> LM_STUDIO`` entry would have let an on-machine provider
        start presenting a credential it does not need. Local providers short
        circuit before the env chain.
        """
        with self._no_vault():
            os.environ["LM_STUDIO_API_KEY"] = "LMS_KEY_1"
            self.assertEqual(resolve_provider_api_key("lmstudio"), "local")

    def test_per_provider_key_wins_over_role_key(self):
        """A provider-specific key must beat a generic role key."""
        with self._no_vault():
            os.environ["OPENAI_API_KEY"] = "PROVIDER_SPECIFIC"
            os.environ["BIG_API_KEY"] = "GENERIC_ROLE"
            self.assertEqual(
                resolve_provider_api_key("openai", role_prefix="big"),
                "PROVIDER_SPECIFIC")

    def test_still_fails_closed_when_nothing_is_configured(self):
        """The new step must not weaken the fail-closed contract."""
        with self._no_vault():
            for provider in ("openai", "groq", "nvidia_nim", "unknownvendor"):
                with self.subTest(provider=provider):
                    self.assertEqual(
                        resolve_provider_api_key(provider), "",
                        "no key anywhere must still fail closed to empty")

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
