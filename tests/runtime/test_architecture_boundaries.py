import os
import unittest

from agents.core.architecture_boundaries import UsageLedger, check_import_boundaries


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE_FILES = [
    "agents/evidence/evidence.py",
    "agents/evidence/evidence_store.py",
    "agents/earning/economic_accounting.py",
    "agents/earning/opportunity_lifecycle.py",
    "agents/services/autonomous_loop.py",
    "agents/services/task_executor.py",
]
FORBIDDEN = {
    path: ("PySide6", "gui", "openai", "anthropic", "ollama", "requests")
    for path in CORE_FILES
}


class TestArchitectureBoundaries(unittest.TestCase):
    def test_core_domain_has_no_gui_or_provider_sdk_imports(self):
        violations = check_import_boundaries(ROOT, CORE_FILES, FORBIDDEN)
        self.assertEqual([], violations)

    def test_application_bootstrap_does_not_eagerly_import_optional_adapters(self):
        violations = check_import_boundaries(
            ROOT,
            ["main.py"],
            {"main.py": (
                "agents.earning.live_trading",
                "agents.earning.paper_trading",
                "agents.integrations.wallet",
                "agents.integrations.wallet_crypto",
                "agents.earning.defi_scanner",
                "agents.earning.airdrop_claimer",
                "agents.earning.social_earning_platform",
            )},
        )
        self.assertEqual([], violations)

    def test_usage_ledger_requires_observed_use_before_removal(self):
        ledger = UsageLedger()
        ledger.record("legacy.provider_registry")
        self.assertEqual(
            ledger.unused(["legacy.provider_registry", "legacy.memory_path"]),
            ["legacy.memory_path"],
        )
        self.assertEqual(ledger.snapshot()["legacy.provider_registry"], 1)


if __name__ == "__main__":
    unittest.main()
