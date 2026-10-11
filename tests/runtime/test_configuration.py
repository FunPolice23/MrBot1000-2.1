import unittest
from unittest.mock import patch

from agents.core.configuration import (
    all_provider_settings,
    provider_settings,
    redacted_configuration,
)


class TestConfiguration(unittest.TestCase):
    def test_normalizes_provider_settings(self):
        settings = provider_settings("OpenRouter", {
            "OPENROUTER_BASE_URL": " https://example.test/v1 ",
            "OPENROUTER_MODEL": " model-a ",
            "OPENROUTER_CHAT_MODEL": " chat-a ",
            "OPENROUTER_API_KEY": "secret",
        })
        self.assertEqual(settings.name, "openrouter")
        self.assertEqual(settings.base_url, "https://example.test/v1")
        self.assertEqual(settings.model, "model-a")
        self.assertTrue(settings.api_key_configured)

    def test_disabled_provider_is_normalized(self):
        settings = provider_settings("ollama", {"DISABLE_OLLAMA": "true"})
        self.assertFalse(settings.enabled)
        self.assertFalse(settings.api_key_configured)

    def test_lmstudio_legacy_disable_key_is_normalized(self):
        settings = provider_settings("lmstudio", {"DISABLE_LM_STUDIO": "1"})
        self.assertFalse(settings.enabled)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported provider"):
            provider_settings("not-a-provider", {})

    def test_diagnostics_never_include_secret_value(self):
        diagnostics = redacted_configuration({
            "OPENAI_API_KEY": "super-secret",
            "OPENAI_MODEL": "gpt-test",
        })
        self.assertTrue(diagnostics["openai"]["api_key_configured"])
        self.assertNotIn("super-secret", repr(diagnostics))

    def test_all_supported_providers_are_available(self):
        settings = all_provider_settings({})
        self.assertIn("openrouter", settings)
        self.assertIn("ollama", settings)

    def test_empty_injected_environment_is_not_global_environment(self):
        settings = provider_settings("openai", {})
        self.assertEqual(settings.model, "")
        self.assertFalse(settings.api_key_configured)

    def test_worker_registry_uses_normalized_provider_values(self):
        from agents.brains.base_worker import WorkerAgent

        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_BASE_URL": "https://example.test/v1",
                "OPENROUTER_MODEL": "model-from-config",
                "OPENROUTER_CHAT_MODEL": "chat-from-config",
            },
            clear=False,
        ):
            worker = WorkerAgent("", lambda _message: None)
            adapter = next(
                item for item in worker._build_provider_registry()
                if item.name == "openrouter"
            )
            self.assertEqual(adapter.base_url, "https://example.test/v1")
            self.assertEqual(adapter.default_model, "model-from-config")
            self.assertEqual(adapter.chat_model, "chat-from-config")


if __name__ == "__main__":
    unittest.main()
