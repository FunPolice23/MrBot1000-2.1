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
