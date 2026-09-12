"""Provider selection must follow enabled configuration, not detection order."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from agents.provider_manager import ProviderInfo, ProviderManager
from agents.dual_brain_runtime import BrainRole, build_config
from gui.dual_brain_control import ProviderStatusChecker


class TestProviderSelection(unittest.TestCase):
    def test_normalizes_lm_studio_name(self):
        self.assertEqual(
            ProviderManager.normalize_provider_name("lm_studio"), "lmstudio")
        self.assertEqual(
            ProviderManager.normalize_provider_name("LM Studio"), "lmstudio")

    def test_resolves_enabled_local_provider(self):
        env = {
            "BIG_BRAIN_PROVIDER": "lmstudio",
            "BIG_BRAIN_ENABLED": "true",
            "SMALL_BRAIN_PROVIDER": "lm_studio",
            "SMALL_BRAIN_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            manager = ProviderManager()
            self.assertEqual(manager.resolve_enabled_provider(), "lmstudio")

    def test_returns_none_when_all_roles_are_disabled(self):
        env = {
            "BIG_BRAIN_PROVIDER": "llamacpp",
            "BIG_BRAIN_ENABLED": "false",
            "SMALL_BRAIN_PROVIDER": "llamacpp",
            "SMALL_BRAIN_ENABLED": "false",
        }
        with patch.dict(os.environ, env, clear=True):
            manager = ProviderManager()
            self.assertIsNone(manager.resolve_enabled_provider())

    def test_lm_studio_is_configurable_when_server_is_stopped(self):
        with patch.dict(os.environ, {}, clear=True), patch(
                "agents.provider_manager.urllib.request.urlopen",
                side_effect=OSError("LM Studio is stopped")):
            manager = ProviderManager()
            providers = manager.detect_providers()
        self.assertIn("lm_studio", providers)
        self.assertEqual(
            providers["lm_studio"].base_url,
            "http://127.0.0.1:1234/v1",
        )
        self.assertEqual(providers["lm_studio"].models, [])

    def test_lm_studio_model_refresh_uses_openai_models_endpoint(self):
        manager = ProviderManager()
        manager._providers["lm_studio"] = ProviderInfo(
            name="LM Studio",
            provider_type="lm_studio",
            base_url="http://127.0.0.1:1234/v1",
            is_local=True,
        )
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"data": [{"id": "qwen-small"}]}'
        with patch.dict(os.environ, {}, clear=True), patch(
                "agents.provider_manager.urllib.request.urlopen", return_value=response) as open_url:
            self.assertEqual(manager.refresh_provider_models("lm_studio"), ["qwen-small"])
        self.assertEqual(open_url.call_args.args[0].full_url, "http://127.0.0.1:1234/v1/models")

    def test_role_model_selection_is_read_from_runtime_environment(self):
        env = {
            "BIG_BRAIN_PROVIDER": "lmstudio",
            "BIG_BRAIN_MODEL": "qwen2.5-7b-instruct",
            "SMALL_BRAIN_PROVIDER": "ollama",
            "SMALL_BRAIN_MODEL": "llama3.2:3b",
        }
        with patch.dict(os.environ, env, clear=True):
            big = build_config(BrainRole.BIG)
            small = build_config(BrainRole.SMALL)
        self.assertEqual(big.model, "qwen2.5-7b-instruct")
        self.assertEqual(small.model, "llama3.2:3b")

    def test_lm_studio_loaded_instances_are_detected(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = (
            b'{"models":[{"key":"granite-old","loaded_instances":[]},'
            b'{"key":"granite-new","loaded_instances":[{"id":"granite-new"}]}]}'
        )
        with patch("gui.dual_brain_control.urllib.request.urlopen", return_value=response):
            running, models = ProviderStatusChecker.check_loaded_provider(
                "lmstudio", "http://localhost:1236/v1")
        self.assertTrue(running)
        self.assertEqual(models, ["granite-new"])

    def test_external_model_lifecycle_uses_native_endpoints(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"status":"loaded"}'
        with patch("gui.dual_brain_control.urllib.request.urlopen", return_value=response) as open_url:
            ok, _ = ProviderStatusChecker.load_provider_model(
                "lmstudio", "http://localhost:1236/v1", "granite-new")
        self.assertTrue(ok)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:1236/api/v1/models/load")
        self.assertEqual(json.loads(request.data), {"model": "granite-new"})


if __name__ == "__main__":
    unittest.main()