"""
Test suite for MrBot1000 Earning Pipeline.

Run with: python test_earning_pipeline.py
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestUpworkClient(unittest.TestCase):
    """Tests for Upwork API client."""

    def test_import(self):
        from agents.upwork_client import UpworkClient, UpworkGig
        self.assertIsNotNone(UpworkClient)
        self.assertIsNotNone(UpworkGig)

    def test_gig_dataclass(self):
        from agents.upwork_client import UpworkGig
        gig = UpworkGig(
            id="gig-456",
            title="Python Developer",
            description="Build a fast API",
            budget_usd=500.0,
            skills=["Python", "FastAPI"],
            url="https://www.upwork.com/jobs/gig-456",
        )
        d = gig.to_dict()
        self.assertEqual(d["job_id"], "gig-456")
        self.assertEqual(d["budget"], 500.0)


class TestFiverrClient(unittest.TestCase):
    """Tests for Fiverr client."""

    def test_import(self):
        from agents.fiverr_client import FiverrClient, FiverrGig
        self.assertIsNotNone(FiverrClient)
        self.assertIsNotNone(FiverrGig)


class TestAirdropScanner(unittest.TestCase):
    """Tests for airdrop scanner."""

    def test_import(self):
        from agents.airdrop_scanner import AirdropScanner, AirdropOpportunity
        self.assertIsNotNone(AirdropScanner)
        self.assertIsNotNone(AirdropOpportunity)

    def test_evaluate_risk_low(self):
        from agents.airdrop_scanner import AirdropOpportunity
        scanner = AirdropScanner()

        # Safe airdrop - no red flags
        result = scanner._assess_risk(
            "Free token airdrop for community members",
            "https://safe-airdrop.com",
        )
        self.assertEqual(result, "low")

    def test_evaluate_risk_high(self):
        from agents.airdrop_scanner import AirdropOpportunity
        scanner = AirdropScanner()

        # High-risk airdrop - red flags
        result = scanner._assess_risk(
            "Send ETH to claim free tokens",
            "https://sketchy-airdrop.xyz",
        )
        self.assertEqual(result, "high")


class TestDefiScanner(unittest.TestCase):
    """Tests for DeFi scanner."""

    def test_import(self):
        from agents.defi_scanner import DeFiScanner, DeFiOpportunity
        self.assertIsNotNone(DeFiScanner)
        self.assertIsNotNone(DeFiOpportunity)


class TestWalletManager(unittest.TestCase):
    """Tests for wallet manager."""

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="hermes-test-"))
        from agents.wallet_manager import WalletManager
        self.wm = WalletManager(root_folder=str(self.tmp_dir))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_solana_wallet(self):
        self.wm.add_solana_wallet("test_sol", "SolAddress123")
        wallets = self.wm.list_wallets()
        self.assertEqual(len(wallets), 1)
        self.assertEqual(wallets[0]["type"], "solana")
        self.assertEqual(wallets[0]["name"], "test_sol")

    def test_add_ethereum_wallet(self):
        self.wm.add_ethereum_wallet("test_eth", "EthAddress456")
        wallets = self.wm.list_wallets()
        self.assertEqual(len(wallets), 1)
        self.assertEqual(wallets[0]["type"], "ethereum")

    def test_get_balance_unknown_wallet(self):
        bal = self.wm.get_balance("nonexistent")
        self.assertIsNone(bal)

    # --- B1: encrypt wallet keys at rest ---
    def test_private_key_encrypted_on_disk(self):
        SECRET = "5Kb8kLf9zgWQnogidDA76MzPL6TsZZY36hWXMssSzNk"
        self.wm.add_ethereum_wallet("eth1", "0xABC", private_key=SECRET)
        raw = (self.tmp_dir / "wallets.json").read_text(encoding="utf-8")
        self.assertNotIn(SECRET, raw, "private key must NOT be stored in cleartext")
        self.assertIn("fernet:", raw, "private key must be stored as an encrypted token")
        # accessors recover it; list_wallets never exposes it
        self.assertEqual(self.wm.get_private_key("eth1"), SECRET)
        self.assertTrue(all("private_key" not in w for w in self.wm.list_wallets()))

    def test_reload_recovers_key(self):
        SECRET = "9yH7kLm2qWr5tZ8xVb3nC4jF6gH1dS0aP"
        self.wm.add_solana_wallet("sol1", "SolAddr", private_key=SECRET)
        # fresh manager in same dir: key recovered via wallet.key
        from agents.wallet_manager import WalletManager
        wm2 = WalletManager(root_folder=self.tmp_dir)
        self.assertEqual(wm2.get_private_key("sol1"), SECRET)

    def test_empty_key_stays_empty(self):
        self.wm.add_solana_wallet("sol1", "SolAddr")
        self.assertIsNone(self.wm.get_private_key("sol1"))
        raw = (self.tmp_dir / "wallets.json").read_text(encoding="utf-8")
        self.assertNotIn("fernet:", raw, "empty key must not be encrypted to a token")

    def test_invalid_env_key_refuses_cleartext_add(self):
        # H37: when encryption is unavailable, adding a NON-EMPTY key must FAIL CLOSED
        # (raise), never store cleartext. logging.error + warnings.warn both fire.
        import logging, warnings, os, tempfile, shutil
        d = tempfile.mkdtemp(prefix="hermes-test-invkey-")
        logged = {}
        class _Cap(logging.Handler):
            def emit(self, rec):
                logged["msg"] = rec.getMessage()
        _cap = _Cap()
        logging.getLogger().addHandler(_cap)
        try:
            os.environ["WALLET_ENC_KEY"] = "not-a-valid-fernet-key"
            from agents.wallet_manager import WalletManager
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                wm = WalletManager(root_folder=d,
                                   encryption_key=os.environ["WALLET_ENC_KEY"])
                raised = False
                try:
                    wm.add_ethereum_wallet("e", "0x1", private_key="SECRETKEEPME")
                except RuntimeError as e:
                    raised = True
                    self.assertIn("REFUSED", str(e))
                self.assertTrue(raised, "degraded-mode add must refuse cleartext (fail closed)")
                warned = any("REFUSED" in str(x.message) for x in w)
                self.assertTrue(warned, "cleartext block must also warn")
            # nothing persisted in cleartext
            raw = (Path(d) / "wallets.json").read_text(encoding="utf-8") \
                if (Path(d) / "wallets.json").exists() else ""
            self.assertNotIn("SECRETKEEPME", raw, "key must NOT be stored in cleartext")
            self.assertTrue(logged.get("msg", "").startswith("WALLET KEY REFUSED"),
                            "must log the refusal via logging (survives -W ignore)")
        finally:
            logging.getLogger().removeHandler(_cap)
            del os.environ["WALLET_ENC_KEY"]
            shutil.rmtree(d, ignore_errors=True)


class TestContentGenerator(unittest.TestCase):
    """Tests for content generator."""

    def test_import(self):
        from agents.content_generator import ContentGenerator
        self.assertIsNotNone(ContentGenerator)

    def test_find_opportunities(self):
        from agents.content_generator import ContentGenerator
        gen = ContentGenerator(worker=None)
        opps = gen.find_content_opportunities()
        self.assertGreater(len(opps), 0)
        platforms = [o["platform"] for o in opps]
        self.assertIn("Mirror.xyz", platforms)
        self.assertIn("Hive", platforms)
        self.assertIn("Gitcoin", platforms)


class TestMicrotaskClient(unittest.TestCase):
    """Tests for microtask client."""

    def test_import(self):
        from agents.microtask_client import MicrotaskClient, MicrotaskGig
        self.assertIsNotNone(MicrotaskClient)
        self.assertIsNotNone(MicrotaskGig)


class TestEarningPipeline(unittest.TestCase):
    """Tests for the core earning pipeline engine."""

    def setUp(self):
        self.tmp_db = tempfile.mktemp(suffix=".db", prefix="hermes-test-")
        self._pipelines = []

    def _track(self, pipeline):
        self._pipelines.append(pipeline)
        return pipeline

    def tearDown(self):
        for pipeline in self._pipelines:
            close = getattr(pipeline, "close", None)
            if callable(close):
                close()
        if os.path.exists(self.tmp_db):
            import gc
            gc.collect()
            try:
                os.unlink(self.tmp_db)
            except PermissionError:
                import time
                time.sleep(0.1)
                os.unlink(self.tmp_db)

    def test_instantiation(self):
        from earning_pipeline import EarningPipeline
        pipe = self._track(EarningPipeline(db_path=self.tmp_db))
        self.assertIsNotNone(pipe)

    def test_discover_empty_sources(self):
        from earning_pipeline import EarningPipeline
        pipe = self._track(EarningPipeline(db_path=self.tmp_db))
        opps = pipe.discover(sources=[])
        self.assertIsInstance(opps, list)

    def test_discover_airdrops(self):
        from earning_pipeline import EarningPipeline
        pipe = self._track(EarningPipeline(db_path=self.tmp_db))
        opps = pipe.discover(sources=["airdrop"])
        # Should work even without network (may be empty)
        self.assertIsInstance(opps, list)

    def test_filter_by_risk(self):
        from earning_pipeline import EarningPipeline, Opportunity
        pipe = self._track(EarningPipeline(db_path=self.tmp_db))

        opps = [
            Opportunity(id=f"test-{i}", source="test", type="test",
                          estimated_usd_value=100.0, risk_level=["low", "medium", "high"][i % 3])
            for i in range(3)
        ]

        filtered_low = pipe.filter(opps, max_risk="low")
        self.assertEqual(len(filtered_low), 1)  # Only one low risk

        filtered_med = pipe.filter(opps, max_risk="medium")
        self.assertEqual(len(filtered_med), 2)  # low + medium

        filtered_high = pipe.filter(opps, max_risk="high")
        self.assertEqual(len(filtered_high), 3)  # all

    def test_get_revenue_report(self):
        from earning_pipeline import EarningPipeline
        pipe = self._track(EarningPipeline(db_path=self.tmp_db))
        report = pipe.get_revenue_report(days=30)
        self.assertIsInstance(report, dict)
        self.assertIn("total_revenue_usd", report)
        self.assertIn("total_outcomes", report)
        self.assertIn("avg_revenue_per_outcome", report)

    def test_run_full_cycle_no_error(self):
        from earning_pipeline import EarningPipeline
        pipe = self._track(EarningPipeline(db_path=self.tmp_db))
        result = pipe.run_full_cycle(sources=[], max_risk="medium")
        self.assertIsInstance(result.success, bool)
        self.assertGreater(len(result.message), 0)

    def test_evaluate_parses_embedded_json_scores(self):
        from earning_pipeline import EarningPipeline, Opportunity

        pipe = self._track(EarningPipeline(db_path=self.tmp_db))
        opp = Opportunity(
            id="eval_json_parse",
            source="social",
            type="gig",
            title="Python automation task",
            description="Need AI and data workflow scripting",
            platform="Reddit",
            estimated_usd_value=20.0,
        )

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "message": {
                        "content": (
                            "Here is your evaluation. "
                            "{\"profit\": 6, \"effort\": 3, \"risk\": 2, \"urgency\": 5, \"skill_match\": 7} "
                            "Done."
                        )
                    }
                }

        with patch("httpx.post", return_value=_Response()):
            out = pipe._evaluate_opportunity(opp)

        self.assertEqual(out.status, "evaluated")
        self.assertGreater(out.skill_match, 0)
        self.assertEqual(out.risk_level, "low")

    def test_execute_airdrop_success(self):
        from earning_pipeline import EarningPipeline, Opportunity
        from agents.airdrop_scanner import AirdropOpportunity

        pipe = self._track(EarningPipeline(db_path=self.tmp_db))
        opp = Opportunity(
            id="airdrop_test_success",
            source="airdrop",
            type="airdrop",
            title="Test Airdrop",
            description="Test claim path",
            platform="AirdropHub",
            url="https://example.com/airdrop",
            estimated_usd_value=25.0,
        )

        class _Result:
            success = True
            message = "claimed"

        class _StubClaimer:
            def claim(self, airdrop):
                self.last_arg = airdrop
                return _Result()

        stub = _StubClaimer()

        with patch("earning_pipeline.AirdropClaimer", return_value=stub):
            result = pipe._execute_airdrop(opp)

        self.assertTrue(result.success)
        self.assertEqual(result.action_taken, "claim")
        self.assertEqual(opp.status, "claimed")
        self.assertIsInstance(stub.last_arg, AirdropOpportunity)
        self.assertEqual(stub.last_arg.claim_url, opp.url)

    def test_execute_airdrop_failure(self):
        from earning_pipeline import EarningPipeline, Opportunity

        pipe = self._track(EarningPipeline(db_path=self.tmp_db))
        opp = Opportunity(
            id="airdrop_test_failure",
            source="airdrop",
            type="airdrop",
            title="Test Airdrop",
            description="Test claim path",
            platform="AirdropHub",
            url="https://example.com/airdrop",
            estimated_usd_value=25.0,
        )

        class _Result:
            success = False
            message = "denied"

        class _StubClaimer:
            def claim(self, _url):
                return _Result()

        with patch("earning_pipeline.AirdropClaimer", return_value=_StubClaimer()):
            result = pipe._execute_airdrop(opp)

        self.assertFalse(result.success)
        self.assertEqual(result.action_taken, "claim")
        self.assertEqual(opp.status, "claim_failed")

    def test_execute_airdrop_bool_return_is_supported(self):
        from earning_pipeline import EarningPipeline, Opportunity

        pipe = self._track(EarningPipeline(db_path=self.tmp_db))
        opp = Opportunity(
            id="airdrop_test_bool",
            source="airdrop",
            type="airdrop",
            title="Bool Return Airdrop",
            description="Test bool claim return",
            platform="AirdropHub",
            url="https://example.com/airdrop",
            estimated_usd_value=10.0,
        )

        class _StubClaimer:
            def claim(self, _airdrop):
                return True

        with patch("earning_pipeline.AirdropClaimer", return_value=_StubClaimer()):
            result = pipe._execute_airdrop(opp)

        self.assertTrue(result.success)
        self.assertEqual(result.message, "claimed")
        self.assertEqual(opp.status, "claimed")


class TestIntegration(unittest.TestCase):
    """Integration tests for earning pipeline workflow."""

    def setUp(self):
        self.tmp_db = tempfile.mktemp(suffix=".db", prefix="hermes-int-")
        self._pipeline = None

    def _track(self, pipeline):
        self._pipeline = pipeline
        return pipeline

    def tearDown(self):
        if self._pipeline is not None:
            self._pipeline.close()
        if os.path.exists(self.tmp_db):
            import gc
            gc.collect()
            try:
                os.unlink(self.tmp_db)
            except PermissionError:
                import time
                time.sleep(0.1)
                os.unlink(self.tmp_db)

    def test_full_workflow(self):
        from earning_pipeline import EarningPipeline
        pipe = self._track(EarningPipeline(db_path=self.tmp_db))

        # 1. Discover - use valid sources only
        opps = pipe.discover(sources=["social", "dynamic"])
        self.assertGreater(len(opps), 0, "Should find at least some opportunities")

        # 2. Get report
        report = pipe.get_revenue_report()
        self.assertIsInstance(report["total_revenue_usd"], float)


def run_tests():
    """Run all tests and print results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes (ClawGig tests removed - service discontinued)
    suite.addTests(loader.loadTestsFromTestCase(TestUpworkClient))
    suite.addTests(loader.loadTestsFromTestCase(TestFiverrClient))
    suite.addTests(loader.loadTestsFromTestCase(TestAirdropScanner))
    suite.addTests(loader.loadTestsFromTestCase(TestDefiScanner))
    suite.addTests(loader.loadTestsFromTestCase(TestWalletManager))
    suite.addTests(loader.loadTestsFromTestCase(TestContentGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestMicrotaskClient))
    suite.addTests(loader.loadTestsFromTestCase(TestEarningPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
