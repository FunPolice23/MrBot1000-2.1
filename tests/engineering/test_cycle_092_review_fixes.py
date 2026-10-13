"""Verify the ARCH-ENG-092 review findings are closed.

The independent adversarial review returned CHANGES REQUIRED with two MAJOR
findings against the first cut of the live-trading fix:

F1 — `_reassess` rebuilt its portfolio/market inputs from the CALLER's
     `assessment.factors`, so a forged-but-plausible RiskAssessment still
     reached the exchange: `last_price=0.000001, liquidity_usd=1e12,
     total_equity_usd=1e12` made a 999999-unit order a $1.00 notional, every
     policy gate passed, and the order went out with zero queue items. The fix
     had moved the forgery target from `decision` to `factors` without
     removing it.

F2 — no consumed-once guard, so one human approval replayed a live order N
     times (5 calls -> 5 orders against real funds), even though the sibling
     ACTION path in main.py got exactly that guard in the same change set.

These tests drive a recording adapter, so a regression is an observed order
reaching the exchange rather than an assertion about code shape.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from agents.earning.live_trading import (  # noqa: E402
    LiveTradingError, LiveTradingService, MarketSnapshot, PortfolioSnapshot,
    RiskAssessment, TradeIntent, TradingPolicy,
)
from agents.safety.approval import HumanApprovalQueue  # noqa: E402


class FakeAdapter:
    """Records every order that reaches the exchange, and serves live state."""

    exchange_id = "fake"

    def __init__(self, total_usd=1000.0, free_usd=900.0, last_price=100.0,
                 balances=None, liquidity_usd=100000.0):
        self.orders = []
        self.total_usd = total_usd
        self.free_usd = free_usd
        self.last_price = last_price
        self.liquidity_usd = liquidity_usd
        self.balances = balances or {"USD": 900.0, "BTC": 0.01}

    def fetch_balance(self):
        return {"total": dict(self.balances, USD=self.total_usd),
                "free": dict(self.balances, USD=self.free_usd)}

    def fetch_ticker(self, symbol):
        return {"last": self.last_price, "percentage": 4.0,
                "timestamp": int(time.time() * 1000)}

    def fetch_order_book(self, symbol):
        return {"bids": [[self.last_price * 0.99, 10.0]],
                "asks": [[self.last_price * 1.01, 12.0]]}

    def create_order(self, *args):
        self.orders.append(args)
        return {"id": "real-order-1", "status": "open"}


def _intent(asset_class="major", quantity=1.0, side="buy", symbol="BTC/USD"):
    return TradeIntent("fake", symbol, side, quantity,
                       strategy_confidence=0.95, expected_profit_pct=2.0,
                       asset_class=asset_class)


class TestReviewFindingsClosed(unittest.TestCase):
    def setUp(self):
        HumanApprovalQueue.reset_singleton()
        self.queue = HumanApprovalQueue.instance()
        self.queue.clear_all()
        self.adapter = FakeAdapter()
        self.service = LiveTradingService(
            self.adapter, live_enabled=True,
            policy=TradingPolicy(preapproval_enabled=False))

    def tearDown(self):
        self.queue.clear_all()
        HumanApprovalQueue.reset_singleton()

    # ── F1: a forged-but-plausible factors dict must not reach the exchange ──

    def test_forged_plausible_factors_do_not_reach_the_exchange(self):
        """THE F1 attack, verbatim: plausible forged market data.

        last_price=0.000001 makes a 999999-unit order a $1.00 notional, so
        every policy gate passes and the verdict comes back 'preapproved'.
        """
        forged = RiskAssessment("preapproved", 0.0, {
            "symbol": "BTC/USD", "exchange": "fake",
            "last_price": 0.000001, "volatility_pct": 0.0, "spread_pct": 0.0,
            "liquidity_usd": 1e12, "fetched_at": time.time(),
            "total_equity_usd": 1e12, "free_cash_usd": 1e12,
            "balances": {"USD": 1e12},
        }, ())
        intent = TradeIntent("fake", "BTC/USD", "buy", 999999.0,
                             strategy_confidence=0.99,
                             expected_profit_pct=5.0, asset_class="major")
        self.service.policy = TradingPolicy(preapproval_enabled=True)
        with self.assertRaises(LiveTradingError):
            self.service.execute_order(intent, forged)
        self.assertEqual(self.adapter.orders, [],
                         "999999-unit order must never reach the exchange")

    def test_forged_factors_cannot_claim_a_verdict_the_live_data_refuses(self):
        """The verdict comes from live state, not from the caller's numbers."""
        forged = RiskAssessment("preapproved", 0.0, {
            "symbol": "BTC/USD", "exchange": "fake", "last_price": 100.0,
            "volatility_pct": 0.0, "spread_pct": 0.0, "liquidity_usd": 1e12,
            "fetched_at": time.time(), "total_equity_usd": 1e9,
            "free_cash_usd": 1e9, "balances": {"USD": 1e9},
        }, ())
        with self.assertRaises(LiveTradingError) as ctx:
            self.service.execute_order(_intent(quantity=500.0), forged)
        self.assertIn("blocked", str(ctx.exception).lower())
        self.assertEqual(self.adapter.orders, [])

    def test_unreadable_live_state_fails_closed(self):
        """If the account cannot be read, the order does not go out."""
        class BrokenAdapter(FakeAdapter):
            def fetch_balance(self):
                raise LiveTradingError("exchange unreachable")

        service = LiveTradingService(
            BrokenAdapter(), live_enabled=True,
            policy=TradingPolicy(preapproval_enabled=True))
        with self.assertRaises(LiveTradingError) as ctx:
            service.execute_order(_intent(), _assessment_for(_intent()))
        self.assertIn("could not be read", str(ctx.exception))
        self.assertEqual(service.adapter.orders, [])

    # ── F1b: an approval is invalidated when the market moves under it ──────

    def test_approval_is_refused_when_the_market_moves_underneath_it(self):
        intent = _intent()
        assessment = self.service.assess_order(intent, *_live(self.adapter))
        proposal = self.service.propose_order(intent, assessment)
        self.queue.approve(proposal["approval_id"])
        # The price doubles between approval and execution: the notional the
        # human reviewed no longer describes what would be submitted.
        self.adapter.last_price = 250.0
        with self.assertRaises(LiveTradingError) as ctx:
            self.service.execute_order(intent, assessment,
                                       approval_id=proposal["approval_id"])
        self.assertIn("no longer holds", str(ctx.exception))
        self.assertEqual(self.adapter.orders, [])

    def test_stable_market_does_not_invalidate_a_genuine_approval(self):
        """The staleness check must not refuse a legitimate approval."""
        intent = _intent()
        assessment = self.service.assess_order(intent, *_live(self.adapter))
        proposal = self.service.propose_order(intent, assessment)
        self.queue.approve(proposal["approval_id"])
        result = self.service.execute_order(intent, assessment,
                                            approval_id=proposal["approval_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.adapter.orders), 1)

    # ── F2: one approval submits at most one live order ─────────────────────

    def test_one_approval_submits_at_most_one_live_order(self):
        """THE F2 attack, verbatim: replay the same approval five times."""
        intent = _intent()
        assessment = self.service.assess_order(intent, *_live(self.adapter))
        proposal = self.service.propose_order(intent, assessment)
        self.queue.approve(proposal["approval_id"])

        first = self.service.execute_order(intent, assessment,
                                           approval_id=proposal["approval_id"])
        self.assertTrue(first["ok"])
        for attempt in range(4):
            with self.assertRaises(LiveTradingError) as ctx:
                self.service.execute_order(intent, assessment,
                                           approval_id=proposal["approval_id"])
            self.assertIn("already been executed", str(ctx.exception),
                          f"replay {attempt + 1} must be refused")
        self.assertEqual(len(self.adapter.orders), 1,
                         "one human approval must submit exactly one order")

    def test_a_second_distinct_approval_still_submits(self):
        """The consumed-once ledger must not block a genuinely new approval."""
        intent = _intent()
        first = self.service.propose_order(
            intent, self.service.assess_order(intent, *_live(self.adapter)))
        self.queue.approve(first["approval_id"])
        self.assertTrue(self.service.execute_order(
            intent, self.service.assess_order(intent, *_live(self.adapter)),
            approval_id=first["approval_id"])["ok"])

        second = self.service.propose_order(
            intent, self.service.assess_order(intent, *_live(self.adapter)))
        self.queue.approve(second["approval_id"])
        self.assertNotEqual(first["approval_id"], second["approval_id"])
        self.assertTrue(self.service.execute_order(
            intent, self.service.assess_order(intent, *_live(self.adapter)),
            approval_id=second["approval_id"])["ok"])
        self.assertEqual(len(self.adapter.orders), 2)

    # ── F6: numeric comparison is relative, strings are case-insensitive ───

    def test_case_differences_do_not_invalidate_an_approval(self):
        """An approval recorded 'BTC/USD' authorizes an order written 'btc/usd'."""
        intent = _intent()
        assessment = self.service.assess_order(intent, *_live(self.adapter))
        proposal = self.service.propose_order(intent, assessment)
        self.queue.approve(proposal["approval_id"])
        lower = TradeIntent("FAKE", "btc/usd", "BUY", 1.0,
                            strategy_confidence=0.95, expected_profit_pct=2.0,
                            asset_class="MAJOR")
        self.assertFalse(self.service._intent_differs(lower, intent.__dict__))

    def test_a_real_quantity_change_is_still_detected(self):
        intent = _intent(quantity=1.0)
        self.assertTrue(self.service._intent_differs(
            _intent(quantity=1.0 + 1e-6), intent.__dict__))

    def test_a_meaningful_price_change_is_still_detected(self):
        intent = _intent()
        intent = TradeIntent("fake", "BTC/USD", "buy", 1.0,
                             limit_price=100.0)
        self.assertTrue(self.service._intent_differs(
            TradeIntent("fake", "BTC/USD", "buy", 1.0, limit_price=101.0),
            intent.__dict__))

    # ── the legitimate paths must still work ───────────────────────────────

    def test_legitimate_approved_order_executes(self):
        intent = _intent()
        assessment = self.service.assess_order(intent, *_live(self.adapter))
        proposal = self.service.propose_order(intent, assessment)
        self.queue.approve(proposal["approval_id"])
        result = self.service.execute_order(intent, assessment,
                                            approval_id=proposal["approval_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.adapter.orders), 1)

    def test_preapproved_low_risk_order_still_runs_without_a_human(self):
        """The guards must not turn every order into a manual approval.

        The fixture is deliberately built to sit INSIDE every policy gate
        (tight spread, deep liquidity, small position): a preapproved verdict
        is only reachable when the risk model genuinely clears the order, so
        this test fails if the live re-derivation can no longer return one.
        """
        adapter = FakeAdapter(total_usd=1_000_000.0, free_usd=1_000_000.0,
                              balances={"USD": 1_000_000.0, "BTC": 0.01},
                              liquidity_usd=5_000_000.0)
        service = LiveTradingService(
            adapter, live_enabled=True,
            policy=TradingPolicy(preapproval_enabled=True))
        low = TradeIntent("fake", "BTC/USD", "buy", 1.0,
                          strategy_confidence=0.99, expected_profit_pct=5.0,
                          asset_class="major")
        assessment = service.assess_order(low, *_live(adapter))
        self.assertEqual(assessment.decision, "preapproved",
                         f"fixture must clear policy, got {assessment.reasons}")
        self.assertTrue(service.execute_order(low, assessment)["ok"])
        self.assertEqual(len(adapter.orders), 1)
        self.assertEqual(self.queue.pending(), [])


def _live(adapter):
    """Assess against the same live state execute_order will re-read."""
    service = LiveTradingService(adapter)
    return service.sync_portfolio(), service.fetch_market_snapshot("BTC/USD")


def _assessment_for(intent):
    return RiskAssessment("needs_approval", 0.9, {
        "symbol": intent.symbol, "exchange": intent.exchange,
        "last_price": 100.0, "volatility_pct": 0.0, "spread_pct": 0.0,
        "liquidity_usd": 100000.0, "fetched_at": time.time(),
        "total_equity_usd": 1000.0, "free_cash_usd": 900.0,
        "balances": {"USD": 900.0, "BTC": 0.01},
    }, ())


if __name__ == "__main__":
    unittest.main()
