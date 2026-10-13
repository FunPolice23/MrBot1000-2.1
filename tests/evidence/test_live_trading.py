import unittest
import time

from agents.earning.live_trading import (
    LiveTradingError, LiveTradingService, MarketSnapshot, PortfolioSnapshot,
    TradeIntent, TradingPolicy,
)


class FakeAdapter:
    exchange_id = "fake"

    def __init__(self):
        self.orders = []

    def fetch_balance(self):
        return {"total": {"USD": 1000.0, "BTC": 0.01}, "free": {"USD": 900.0}}

    def fetch_ticker(self, symbol):
        return {"last": 100.0, "percentage": 4.0, "timestamp": int(time.time() * 1000)}

    def fetch_order_book(self, symbol):
        return {"bids": [[99.0, 10.0]], "asks": [[101.0, 12.0]]}

    def create_order(self, *args):
        self.orders.append(args)
        return {"id": "real-order-1", "status": "open"}


def _intent(asset_class="major", amount=1.0):
    # 1.0 against the adapter's real state (price 100, ~$2202 top-of-book
    # liquidity, 2% spread, $1001 equity) is a needs_approval order. The
    # original 10.0 made it a $1000 notional, which the live re-derivation
    # correctly blocks outright.
    return TradeIntent("fake", "BTC/USD", "buy", amount,
                       strategy_confidence=0.95, expected_profit_pct=2.0,
                       asset_class=asset_class)


def _live(service):
    """Assess against the same live state execute_order re-reads.

    These fixtures previously used an idealised MarketSnapshot (price 10,
    liquidity 10000) that did not match what FakeAdapter serves (price 100,
    ~$2202 top-of-book liquidity). `execute_order` re-derives its verdict from
    LIVE exchange state, so an assessment built from a different snapshot was
    never the decision the executor would act on. Reading the real state keeps
    the assessment and the re-derivation describing the same order.
    """
    return service.sync_portfolio(), service.fetch_market_snapshot("BTC/USD")


class TestLiveTrading(unittest.TestCase):
    def test_portfolio_reads_adapter_state(self):
        service = LiveTradingService(FakeAdapter())
        snapshot = service.sync_portfolio()
        self.assertEqual(snapshot.total_equity_usd, 1001.0)
        self.assertEqual(snapshot.balances["BTC"], 0.01)

    def test_portfolio_fails_when_crypto_cannot_be_valued(self):
        adapter = FakeAdapter()
        adapter.fetch_ticker = lambda symbol: {}
        with self.assertRaises(LiveTradingError):
            LiveTradingService(adapter).sync_portfolio()

    def test_status_is_disabled_without_adapter_even_when_flagged(self):
        service = LiveTradingService(None, live_enabled=True)
        self.assertEqual(service.status()["execution_mode"], "disabled")

    def test_coinbase_adapter_can_be_constructed_without_sandbox(self):
        from agents.earning.live_trading import CcxtExchangeAdapter
        adapter = CcxtExchangeAdapter("coinbase", sandbox=False)
        self.assertEqual(adapter.exchange_id, "coinbase")

    def test_market_snapshot_uses_ticker_and_order_book(self):
        snapshot = LiveTradingService(FakeAdapter()).fetch_market_snapshot("BTC/USD")
        self.assertEqual(snapshot.last_price, 100.0)
        self.assertAlmostEqual(snapshot.spread_pct, 2.0)
        self.assertEqual(snapshot.liquidity_usd, 2202.0)
        self.assertEqual(snapshot.volatility_pct, 4.0)

    def test_market_snapshot_rejects_incomplete_order_book(self):
        adapter = FakeAdapter()
        adapter.fetch_order_book = lambda symbol: {"bids": [], "asks": []}
        with self.assertRaises(LiveTradingError):
            LiveTradingService(adapter).fetch_market_snapshot("BTC/USD")

    def test_market_snapshot_rejects_crossed_order_book(self):
        adapter = FakeAdapter()
        adapter.fetch_order_book = lambda symbol: {
            "bids": [[102.0, 1.0]], "asks": [[101.0, 1.0]],
        }
        with self.assertRaises(LiveTradingError):
            LiveTradingService(adapter).fetch_market_snapshot("BTC/USD")

    def test_exchange_mismatch_is_rejected(self):
        service = LiveTradingService(FakeAdapter())
        with self.assertRaises(LiveTradingError):
            service.assess_order(
                TradeIntent("kraken", "BTC/USD", "buy", 1),
                PortfolioSnapshot("fake", 1000, 900),
                MarketSnapshot("BTC/USD", 10, liquidity_usd=10000),
            )

    def test_stale_market_data_is_rejected(self):
        service = LiveTradingService(FakeAdapter())
        with self.assertRaises(LiveTradingError):
            service.assess_order(
                _intent(), PortfolioSnapshot("fake", 1000, 900),
                MarketSnapshot("BTC/USD", 10, liquidity_usd=10000,
                               fetched_at=time.time() - 31),
            )

    def test_disabled_service_never_submits(self):
        adapter = FakeAdapter()
        service = LiveTradingService(adapter, live_enabled=False,
                                     policy=TradingPolicy(preapproval_enabled=True))
        assessment = service.assess_order(_intent(), *_live(service))
        with self.assertRaises(LiveTradingError):
            service.execute_order(_intent(), assessment)
        self.assertEqual(adapter.orders, [])

    def test_high_risk_meme_requires_approval(self):
        service = LiveTradingService(FakeAdapter(), live_enabled=True,
                                     policy=TradingPolicy(preapproval_enabled=True))
        assessment = service.assess_order(_intent("meme"), *_live(service))
        self.assertEqual(assessment.decision, "needs_approval")
        with self.assertRaises(LiveTradingError):
            service.execute_order(_intent("meme"), assessment)

    def test_policy_can_preapprove_low_risk_order(self):
        adapter = FakeAdapter()
        service = LiveTradingService(adapter, live_enabled=True,
                                     policy=TradingPolicy(preapproval_enabled=True))
        # A preapprovable order must sit inside every policy gate against the
        # adapter's real state, so the fixture is sized to it rather than to
        # an idealised snapshot the executor never sees.
        service.policy = TradingPolicy(preapproval_enabled=True,
                                       max_order_usd=500.0,
                                       max_position_pct=0.5,
                                       max_spread_pct=5.0)
        low = _intent(amount=1.0)
        assessment = service.assess_order(low, *_live(service))
        self.assertEqual(assessment.decision, "preapproved",
                         f"fixture must clear policy, got {assessment.reasons}")
        result = service.execute_order(low, assessment)
        self.assertTrue(result["ok"])
        self.assertEqual(len(adapter.orders), 1)

    def test_daily_loss_blocks_orders(self):
        service = LiveTradingService(FakeAdapter(), live_enabled=True,
                                     policy=TradingPolicy(preapproval_enabled=True))
        assessment = service.assess_order(
            _intent(), PortfolioSnapshot("fake", 1000, 900),
            MarketSnapshot("BTC/USD", 10, liquidity_usd=10000), daily_loss_pct=0.02,
        )
        self.assertEqual(assessment.decision, "blocked")

    def test_buy_above_free_cash_is_blocked(self):
        service = LiveTradingService(FakeAdapter(), live_enabled=True,
                                     policy=TradingPolicy(preapproval_enabled=True))
        assessment = service.assess_order(
            _intent(amount=100), PortfolioSnapshot("fake", 1000, 10),
            MarketSnapshot("BTC/USD", 10, liquidity_usd=10000),
        )
        self.assertEqual(assessment.decision, "blocked")
        self.assertIn("available quote-asset", assessment.reasons[0])

    def test_sell_above_holdings_is_blocked(self):
        service = LiveTradingService(FakeAdapter(), live_enabled=True,
                                     policy=TradingPolicy(preapproval_enabled=True))
        assessment = service.assess_order(
            TradeIntent("fake", "BTC/USD", "sell", 2,
                        strategy_confidence=0.95, expected_profit_pct=2.0,
                        asset_class="major"),
            PortfolioSnapshot("fake", 1000, 900, {"USD": 900, "BTC": 0.01}),
            MarketSnapshot("BTC/USD", 10, liquidity_usd=10000),
        )
        self.assertEqual(assessment.decision, "blocked")

    def test_order_proposal_uses_approval_queue(self):
        from agents.safety.approval import HumanApprovalQueue
        HumanApprovalQueue.reset_singleton()
        service = LiveTradingService(FakeAdapter(), live_enabled=True,
                                     policy=TradingPolicy(preapproval_enabled=True))
        assessment = service.assess_order(_intent("meme"), *_live(service))
        proposal = service.propose_order(_intent("meme"), assessment)
        self.assertEqual(proposal["status"], "awaiting_approval")
        queue = HumanApprovalQueue.instance()
        item = queue.find_by_id(proposal["approval_id"])
        self.assertTrue(queue.approve(item.id))
        result = service.execute_order(_intent("meme"), assessment,
                                       approval_id=item.id)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()