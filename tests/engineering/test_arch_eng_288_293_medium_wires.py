"""ARCH-ENG-288..293 — medium-tier reconciliation findings.

Each test class is paired with a vacuity probe: the same detector is shown to
return the *other* answer on a case that should pass. A guard that refuses
everything, or a "wired" path that never changes a result, fails here.
"""

from __future__ import annotations

import ast
import os
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── ARCH-ENG-288 (B-01/B-02): the patch service honours the trust boundary ──


class TestPatchServiceRefusesProtectedSource(unittest.TestCase):
    def _service(self):
        from agents.services.code_patch_service import CodePatchService

        root = tempfile.mkdtemp(prefix="arch288_")
        return CodePatchService(root_dir=root, apply_anyway_for_tests=True), root

    def _patch(self, target: str):
        from agents.services.code_patch_service import CodePatch

        return CodePatch(
            target_path=target,
            authored_by="edward",
            motivation="test",
            detail="test",
            patch_text="x = 1\n",
        )

    def test_the_trust_boundary_is_in_the_protected_set(self):
        from agents.brains.base_worker import PROTECTED_SOURCE_FILES

        for name in (
            "approval.py", "authorization.py", "calling.py",
            "code_patch_service.py", "composition_root.py", "dispatch.py",
            "filesystem.py", "gate.py", "handlers.py", "instructions.py",
            "tools.py", "worker_safety.py",
        ):
            with self.subTest(name=name):
                self.assertIn(
                    name, PROTECTED_SOURCE_FILES,
                    f"{name} defines the trust boundary but is patchable")

    def test_the_patch_service_refuses_each_protected_target(self):
        service, _ = self._service()
        for target in ("main.py", "gate.py", "approval.py",
                       "code_patch_service.py", "config.yaml"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError, msg=target):
                    service.propose(self._patch(target))

    def test_an_ordinary_new_file_still_passes(self):
        """Vacuity probe: a service that refuses every target is not a fix."""
        service, _ = self._service()
        patch = service.propose(self._patch("notes.py"))
        self.assertTrue(patch.target_path.endswith("notes.py"))


# ── ARCH-ENG-289 (G-06): daily-loss has a production producer ───────────────


class _FakeAdapter:
    exchange_id = "fake"

    def __init__(self, equity: float = 1000.0):
        self.equity = equity

    def fetch_balance(self):
        return {
            "total": {"USD": self.equity},
            "free": {"USD": self.equity},
        }


def _order(symbol: str = "BTC/USD"):
    from agents.earning.live_trading import TradeIntent

    return TradeIntent(
        exchange="fake", symbol=symbol, side="buy", quantity=0.01,
        order_type="market", expected_profit_pct=1.0,
        strategy_confidence=0.95, asset_class="stable",
    )


def _market(symbol: str = "BTC/USD"):
    import time
    from agents.earning.live_trading import MarketSnapshot

    return MarketSnapshot(
        symbol=symbol, last_price=100.0, volatility_pct=1.0,
        spread_pct=0.1, liquidity_usd=1_000_000.0, fetched_at=time.time(),
    )


class TestDailyLossHasAProducer(unittest.TestCase):
    def test_tracker_keeps_the_first_observation_for_the_day(self):
        from agents.earning.live_trading import DailyEquityTracker

        path = os.path.join(tempfile.mkdtemp(prefix="arch289_"), "equity.json")
        tracker = DailyEquityTracker(path)
        self.assertEqual(tracker.observe("fake", 1000.0, now=1000), 1000.0)
        self.assertEqual(
            tracker.observe("fake", 900.0, now=2000), 1000.0,
            "a second observation must keep the day's opening balance")
        self.assertEqual(
            tracker.observe("fake", 800.0, now=1000 + 86400), 800.0,
            "a new UTC day must establish a new opening balance")

    def test_sync_portfolio_populates_the_baseline(self):
        from agents.earning.live_trading import LiveTradingService

        path = os.path.join(tempfile.mkdtemp(prefix="arch289b_"), "equity.json")
        adapter = _FakeAdapter(1000.0)
        service = LiveTradingService(adapter, daily_equity_path=path)
        first = service.sync_portfolio()
        self.assertEqual(first.day_start_equity_usd, 1000.0)
        adapter.equity = 900.0
        second = service.sync_portfolio()
        self.assertEqual(second.total_equity_usd, 900.0)
        self.assertEqual(second.day_start_equity_usd, 1000.0)

        verdict = service.assess_order(_order(), second, _market())
        self.assertEqual(verdict.decision, "blocked")
        self.assertIn("daily loss limit reached", verdict.reasons)

    def test_without_a_baseline_the_breaker_is_not_fabricated(self):
        """Vacuity probe: no opening balance means no invented loss."""
        from agents.earning.live_trading import (
            LiveTradingService, PortfolioSnapshot,
        )

        service = LiveTradingService(_FakeAdapter(), live_enabled=True)
        snapshot = PortfolioSnapshot(
            "fake", 900.0, 900.0, day_start_equity_usd=0.0)
        verdict = service.assess_order(_order(), snapshot, _market())
        self.assertNotEqual(verdict.decision, "blocked")
        self.assertNotIn("daily loss limit reached", verdict.reasons)


# ── ARCH-ENG-290 (I-01): the browsing layer enforces the SSRF guard ─────────


def _long_html() -> str:
    body = "Public research page. " * 30
    return f"<html><head><title>ok</title></head><body>{body}</body></html>"


class TestBrowsingLayerRefusesPrivateTargets(unittest.TestCase):
    def test_webcontroller_read_page_and_scrape_refuse_loopback(self):
        from agents.integrations.browser import WebController

        wc = WebController()
        for fn in (wc.read_page, wc.scrape):
            with self.subTest(fn=fn.__name__):
                out = fn("http://127.0.0.1:9/private")
                self.assertFalse(out["ok"])
                self.assertTrue(out.get("ssrf_blocked"))
                self.assertIn("SSRF", out["error"])

    def test_webeyes_read_page_refuses_loopback(self):
        from agents.integrations.web_eyes import WebEyes

        out = WebEyes().read_page("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("ssrf_blocked"))

    def test_a_public_page_is_still_read(self):
        """Vacuity probe: the guard must not block the ordinary path."""
        from agents.integrations.browser import WebController
        from agents.safety.instructions import InstructionGate

        response = SimpleNamespace(
            status_code=200, text=_long_html(), url="https://example.com/")
        with patch.object(InstructionGate, "_is_safe_fetch_url", return_value=True), \
                patch("agents.integrations.browser._robots_checker") as robots, \
                patch("agents.integrations.browser.requests.get",
                      return_value=response) as get:
            robots.return_value.is_allowed.return_value = True
            out = WebController().read_page("https://example.com/")
        self.assertTrue(out["ok"], out)
        self.assertTrue(get.called)


# ── ARCH-ENG-291 (M-03): the fallback uses the KV width it is handed ───────


class TestVramFallbackUsesKvWidth(unittest.TestCase):
    def test_narrower_kv_allows_at_least_as_much_context(self):
        from agents.runtime import dual_brain as db

        device = SimpleNamespace(is_gpu=True, index=0, memory_gb=6.0)
        with patch("agents.runtime.device_registry.detect_devices",
                   return_value=[device]):
            f16, _ = db._vram_safe_context(
                32768, db.BrainRole.SMALL, 0, None, kv_type_bytes=2)
            q8, _ = db._vram_safe_context(
                32768, db.BrainRole.SMALL, 0, None, kv_type_bytes=1)
        self.assertEqual(f16, db._tier_context_for(8192, 2))
        self.assertGreater(q8, f16,
                           "q8_0 KV still received the f16-sized allowance")

    def test_tier_scaling_is_not_a_constant(self):
        """Vacuity probe: a hardcoded return would pass the direction test."""
        from agents.runtime import dual_brain as db

        self.assertEqual(db._tier_context_for(8192, 2), 8192)
        self.assertEqual(db._tier_context_for(8192, 1), 16384)
        self.assertEqual(db._tier_context_for(8192, 4), 4096)


# ── ARCH-ENG-292 (N-01): one public get_all_tools, the canonical one ───────


class TestOnlyTheCanonicalToolRegistryIsPublic(unittest.TestCase):
    def test_the_earning_router_no_longer_advertises_a_second_registry(self):
        import agents.earning as earning
        from agents.earning import router

        self.assertFalse(hasattr(router, "get_all_tools"))
        self.assertNotIn("get_all_tools", earning.__all__)

    def test_the_canonical_registry_still_exists(self):
        from agents.safety.tools import get_all_tools

        names = {t["function"]["name"] for t in get_all_tools()}
        self.assertIn("web_read", names)
        self.assertIn("propose_code_patch", names)

    def test_the_task_scoped_selector_still_works(self):
        """Vacuity probe: deleting the whole router would pass the first test."""
        from agents.earning.router import get_tools_for_task

        tools = get_tools_for_task("research")
        self.assertTrue(tools)
        self.assertTrue(all("function" in t for t in tools))


# ── ARCH-ENG-293 (P-01): startup validation is actually called ─────────────


class TestStartupValidationIsWired(unittest.TestCase):
    def test_main_runs_validation_before_building_the_window(self):
        tree = ast.parse((REPO / "main.py").read_text(encoding="utf-8"))
        entries = [
            node for node in tree.body
            if isinstance(node, ast.If)
            and "__main__" in ast.unparse(node.test)
        ]
        # main.py has an early argv-only __main__ block; the entrypoint is the
        # later one that constructs MainWindow.
        entry = next(node for node in entries
                     if "MainWindow()" in ast.unparse(node))
        body = ast.unparse(entry)
        self.assertIn("validate_startup_environment", body)
        self.assertIn("startup_validation_report", body)
        self.assertLess(
            body.index("validate_startup_environment"),
            body.index("MainWindow()"),
            "validation must run before the window it reports on",
        )

    def test_the_validator_reports_a_real_error(self):
        from app.startup_validation import validate_startup_environment

        logs = []
        broken = validate_startup_environment(env={
            "BIG_BRAIN_ENABLED": "0",
            "SMALL_BRAIN_ENABLED": "0",
            "DISABLE_OPENAI": "1",
            "DISABLE_ANTHROPIC": "1",
        }, log_fn=logs.append)
        self.assertEqual(broken.status, "error")
        self.assertTrue(broken.errors)
        self.assertTrue(logs, "the validator's log_fn was never called")

    def test_a_configured_runtime_is_not_reported_as_broken(self):
        """Vacuity probe: a validator that always errors is not a fix."""
        from app.startup_validation import validate_startup_environment

        report = validate_startup_environment(
            env={"MRBOT_SAFE_MODE": "1", "BIG_BRAIN_ENABLED": "1"})
        self.assertNotEqual(report.status, "error")


if __name__ == "__main__":
    unittest.main()
