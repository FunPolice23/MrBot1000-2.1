import unittest

from startup_validation import validate_startup_environment


class StartupValidationTests(unittest.TestCase):
    def test_default_dual_brain_counts_as_local_provider(self):
        report = validate_startup_environment({
            "DISABLE_OLLAMA": "true",
            "DISABLE_OPENAI": "true",
            "DISABLE_ANTHROPIC": "true",
        })

        self.assertNotIn("No usable LLM provider configuration found.", report.errors)
        self.assertEqual(report.details["local_brains"], ["BIG_BRAIN", "SMALL_BRAIN"])

    def test_disabled_local_brains_without_cloud_provider_errors(self):
        report = validate_startup_environment({
            "BIG_BRAIN_ENABLED": "false",
            "SMALL_BRAIN_ENABLED": "false",
            "DISABLE_OLLAMA": "true",
            "DISABLE_OPENAI": "true",
            "DISABLE_ANTHROPIC": "true",
        })

        self.assertIn("No usable LLM provider configuration found.", report.errors)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from startup_validation import validate_startup_environment


class TestStartupValidation(unittest.TestCase):
    def test_safe_mode_and_missing_provider_are_reported(self):
        env = {
            "MRBOT_SAFE_MODE": "true",
            "DISABLE_OLLAMA": "true",
            "BIG_BRAIN_ENABLED": "false",
            "SMALL_BRAIN_ENABLED": "false",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "OLLAMA_MAIN_MODEL": "",
            "OLLAMA_CHAT_MODEL": "",
        }

        report = validate_startup_environment(env, log_fn=lambda _: None)

        self.assertTrue(report.safe_mode)
        self.assertEqual(report.status, "warning")
        self.assertTrue(any("safe mode" in item.lower() for item in report.warnings))
        self.assertTrue(any("provider" in item.lower() for item in report.warnings))


if __name__ == "__main__":
    unittest.main()
