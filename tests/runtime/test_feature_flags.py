import unittest

from agents.core.feature_flags import feature_enabled, feature_env_key, feature_status


class TestFeatureFlags(unittest.TestCase):
    def test_optional_features_fail_closed(self):
        self.assertFalse(feature_enabled("live_trading", {}))
        self.assertFalse(feature_enabled("crypto_operations", {}))
        self.assertFalse(feature_enabled("unknown", {"MRBOT_ENABLE_LIVE_TRADING": "1"}))

    def test_new_flag_takes_precedence_over_legacy_alias(self):
        env = {
            "MRBOT_ENABLE_LIVE_TRADING": "false",
            "ENABLE_LIVE_TRADING": "true",
        }
        self.assertFalse(feature_enabled("live_trading", env))

    def test_legacy_alias_is_supported(self):
        self.assertTrue(feature_enabled("defi_scanning", {"ENABLE_DEFI": "yes"}))

    def test_status_is_non_secret(self):
        status = feature_status({"MRBOT_ENABLE_CRYPTO": "1"})
        self.assertTrue(status["crypto_operations"])
        self.assertNotIn("API_KEY", repr(status))

    def test_canonical_environment_key_is_exposed(self):
        self.assertEqual(
            feature_env_key("live_trading"), "MRBOT_ENABLE_LIVE_TRADING")
        with self.assertRaises(ValueError):
            feature_env_key("not-a-feature")


if __name__ == "__main__":
    unittest.main()
