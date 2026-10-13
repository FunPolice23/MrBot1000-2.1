"""ARCH-ENG-092: the live-trading approval must authorize the order it names.

The defect: ``execute_order`` accepted a bare ``approval_id`` and asked only
whether the queued item was APPROVED. It never compared the intent the human
saw with the intent being executed, and it trusted whatever ``RiskAssessment``
the caller passed. One Approve click on a small BTC buy therefore authorized an
arbitrary sell of any size on any symbol, and a caller-built
``RiskAssessment("preapproved", ...)`` skipped the human entirely with no queue
item at all.

Every test here drives real money-shaped behaviour through a recording adapter,
so a regression is an observed order reaching the adapter rather than an
assertion about code shape.
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
    """Records every order that reaches the exchange, and serves live state.

    `execute_order` re-derives the risk verdict from LIVE exchange state, so
    the adapter must be able to answer balance/ticker/book reads. The numbers
    match PORTFOLIO/_market() so an assessment and the re-derivation agree.
    """

    exchange_id = "fake"

    def __init__(self):
        self.orders = []

    def fetch_balance(self):
        return {"total": {"USD": 1000.0, "BTC": 0.01},
                "free": {"USD": 900.0, "BTC": 0.01}}

    def fetch_ticker(self, symbol):
        return {"last": 100.0, "percentage": 4.0,
                "timestamp": int(time.time() * 1000)}

    def fetch_order_book(self, symbol):
        return {"bids": [[99.0, 10.0]], "asks": [[101.0, 12.0]]}

    def create_order(self, *args):
        self.orders.append(args)
        return {"id": "real-order-1", "status": "open"}


def _intent(asset_class="major", quantity=1.0, side="buy", symbol="BTC/USD"):
    return TradeIntent("fake", symbol, side, quantity,
                       strategy_confidence=0.95, expected_profit_pct=2.0,
                       asset_class=asset_class)


def _live(service):
    """Assess against the same live state execute_order re-reads.

    `execute_order` re-derives its verdict from LIVE exchange state and then
    compares it against the assessment the human reviewed. Building the
    assessment from an idealised snapshot instead means the two never agree
    and every legitimate approval is refused as stale. Fresh per call because
    `assess_order` refuses market data older than
    `max_market_data_age_seconds`.
    """
    return service.sync_portfolio(), service.fetch_market_snapshot("BTC/USD")


class TestLiveTradingApprovalBinding(unittest.TestCase):
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

    def _assessed(self, intent=None):
        intent = intent or _intent()
        assessment = self.service.assess_order(intent, *_live(self.service))
        self.assertEqual(assessment.decision, "needs_approval")
        return intent, assessment

    # ── the authorization is bound to the approved order ────────────────────

    def test_approved_order_cannot_be_swapped_for_another(self):
        """THE core defect: approve a small buy, execute a huge sell."""
        approved_intent, assessment = self._assessed()
        proposal = self.service.propose_order(approved_intent, assessment)
        self.assertTrue(self.queue.approve(proposal["approval_id"]))

        swapped = _intent(quantity=500.0, side="sell", symbol="ETH/USD",
                          asset_class="meme")
        with self.assertRaises(LiveTradingError) as ctx:
            self.service.execute_order(swapped, assessment,
                                       approval_id=proposal["approval_id"])
        self.assertIn("does not match the order being executed",
                      str(ctx.exception))
        self.assertEqual(self.adapter.orders, [],
                         "no order may reach the exchange")

    def test_approval_for_one_symbol_does_not_authorize_another(self):
        _, assessment = self._assessed()
        proposal = self.service.propose_order(_intent(), assessment)
        self.queue.approve(proposal["approval_id"])
        with self.assertRaises(LiveTradingError):
            self.service.execute_order(
                _intent(symbol="DOGE/USD"), assessment,
                approval_id=proposal["approval_id"])
        self.assertEqual(self.adapter.orders, [])

    def test_approval_quantity_must_match_exactly(self):
        _, assessment = self._assessed()
        proposal = self.service.propose_order(_intent(quantity=1.0), assessment)
        self.queue.approve(proposal["approval_id"])
        with self.assertRaises(LiveTradingError):
            self.service.execute_order(
                _intent(quantity=2.0), assessment,
                approval_id=proposal["approval_id"])
        self.assertEqual(self.adapter.orders, [])

    def test_approved_side_cannot_be_flipped(self):
        """A sell approval must not be replayable as a buy."""
        sell = _intent(side="sell", quantity=0.005)  # within the 0.01 BTC held
        assessment = self.service.assess_order(sell, *_live(self.service))
        proposal = self.service.propose_order(sell, assessment)
        self.assertIn("approval_id", proposal,
                      "the sell must actually reach the approval queue")
        self.queue.approve(proposal["approval_id"])
        with self.assertRaises(LiveTradingError):
            self.service.execute_order(_intent(side="buy"), assessment,
                                       approval_id=proposal["approval_id"])
        self.assertEqual(self.adapter.orders, [])

    def test_approval_payload_without_an_intent_authorizes_nothing(self):
        """An item that does not name its order cannot be shown to cover one."""
        from agents.safety.approval import ApprovalItem, ApprovalKind
        item = self.queue.enqueue(ApprovalItem(
            kind=ApprovalKind.ACTION, title="Live BUY 1 BTC/USD",
            description="hand-built with no payload", requested_by="test"))
        self.queue.approve(item.id)
        with self.assertRaises(LiveTradingError) as ctx:
            self.service.execute_order(_intent(), _intent_assessment(),
                                       approval_id=item.id)
        self.assertIn("does not name the order", str(ctx.exception))
        self.assertEqual(self.adapter.orders, [])

    def test_missing_order_shaping_field_makes_the_approval_unusable(self):
        from agents.safety.approval import ApprovalItem, ApprovalKind
        want = _intent().__dict__
        partial = {k: v for k, v in want.items() if k != "quantity"}
        item = self.queue.enqueue(ApprovalItem(
            kind=ApprovalKind.ACTION, title="Live BUY 1 BTC/USD",
            description="payload omits quantity", requested_by="test",
            payload={"intent": partial}))
        self.queue.approve(item.id)
        with self.assertRaises(LiveTradingError):
            self.service.execute_order(_intent(), _intent_assessment(),
                                       approval_id=item.id)
        self.assertEqual(self.adapter.orders, [])

    # ── the decision itself must be live and genuine ────────────────────────

    def test_denied_approval_never_executes(self):
        _, assessment = self._assessed()
        proposal = self.service.propose_order(_intent(), assessment)
        self.assertTrue(self.queue.deny(proposal["approval_id"], notes="no"))
        with self.assertRaises(LiveTradingError) as ctx:
            self.service.execute_order(_intent(), assessment,
                                       approval_id=proposal["approval_id"])
        self.assertIn("Human approval is required", str(ctx.exception))
        self.assertEqual(self.adapter.orders, [])

    def test_unknown_approval_id_never_executes(self):
        _, assessment = self._assessed()
        with self.assertRaises(LiveTradingError):
            self.service.execute_order(_intent(), assessment,
                                       approval_id="not-a-real-id")
        self.assertEqual(self.adapter.orders, [])

    def test_empty_approval_id_never_executes(self):
        _, assessment = self._assessed()
        with self.assertRaises(LiveTradingError):
            self.service.execute_order(_intent(), assessment, approval_id="")
        self.assertEqual(self.adapter.orders, [])

    def test_pending_approval_never_executes(self):
        _, assessment = self._assessed()
        proposal = self.service.propose_order(_intent(), assessment)
        # deliberately not approved
        with self.assertRaises(LiveTradingError):
            self.service.execute_order(_intent(), assessment,
                                       approval_id=proposal["approval_id"])
        self.assertEqual(self.adapter.orders, [])

    # ── a fabricated assessment cannot stand in for a real one ──────────────

    def test_fabricated_preapproved_assessment_is_refused(self):
        """A hand-built 'preapproved' verdict must not bypass the human."""
        fabricated = RiskAssessment("preapproved", 0.0, {}, ())
        self.assertEqual(self.queue.pending(), [], "no item was ever queued")
        with self.assertRaises(LiveTradingError) as ctx:
            self.service.execute_order(_intent(quantity=999999.0), fabricated)
        self.assertIn("blocked", str(ctx.exception).lower())
        self.assertEqual(self.adapter.orders, [],
                         "999999-unit order must never reach the exchange")

    def test_fabricated_assessment_cannot_lower_a_real_verdict(self):
        _, real = self._assessed()
        fabricated = RiskAssessment("preapproved", 0.0, dict(real.factors), ())
        with self.assertRaises(LiveTradingError):
            self.service.execute_order(_intent(), fabricated)
        self.assertEqual(self.adapter.orders, [])

    def test_assessment_factors_carry_the_reviewed_market_data(self):
        """Re-derivation needs the numbers the human actually reviewed."""
        _, assessment = self._assessed()
        for key in ("symbol", "exchange", "last_price", "volatility_pct",
                    "spread_pct", "liquidity_usd", "fetched_at",
                    "total_equity_usd", "free_cash_usd", "balances"):
            self.assertIn(key, assessment.factors,
                          f"{key} must be recorded with the assessment")

    # ── legitimate approvals must still work ────────────────────────────────

    def test_the_approved_order_executes_exactly_once(self):
        intent, assessment = self._assessed()
        proposal = self.service.propose_order(intent, assessment)
        self.queue.approve(proposal["approval_id"])
        result = self.service.execute_order(intent, assessment,
                                            approval_id=proposal["approval_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["execution_mode"], "live")
        self.assertEqual(len(self.adapter.orders), 1)
        symbol, order_type, side, quantity, _ = self.adapter.orders[0]
        self.assertEqual((symbol, order_type, side, quantity),
                         ("BTC/USD", "market", "buy", 1.0))

    def test_advisory_fields_do_not_invalidate_a_real_approval(self):
        """A refreshed confidence estimate must not block an approved order.

        The risk model reads ``strategy_confidence`` and
        ``expected_profit_pct``, but they do not shape the order sent to the
        exchange. Comparing them would make a legitimate approval unusable the
        moment the market moved.
        """
        intent, assessment = self._assessed()
        proposal = self.service.propose_order(intent, assessment)
        self.queue.approve(proposal["approval_id"])
        refreshed = TradeIntent(
            intent.exchange, intent.symbol, intent.side, intent.quantity,
            order_type=intent.order_type, limit_price=intent.limit_price,
            expected_profit_pct=9.9, strategy_confidence=0.5,
            asset_class=intent.asset_class, reasoning="re-estimated")
        result = self.service.execute_order(
            refreshed, assessment, approval_id=proposal["approval_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.adapter.orders), 1)

    def test_preapproved_low_risk_order_still_runs_without_a_human(self):
        """The fix must not turn every order into a manual approval.

        The policy is widened so the fixture sits inside every gate against
        the adapter's real state; a preapprovable order is only reachable when
        the risk model genuinely clears it.
        """
        service = LiveTradingService(
            self.adapter, live_enabled=True,
            policy=TradingPolicy(preapproval_enabled=True,
                                 max_order_usd=500.0, max_position_pct=0.5,
                                 max_spread_pct=5.0))
        low = TradeIntent("fake", "BTC/USD", "buy", 1.0,
                          strategy_confidence=0.99, expected_profit_pct=5.0,
                          asset_class="major")
        assessment = service.assess_order(low, *_live(service))
        self.assertEqual(assessment.decision, "preapproved",
                         f"fixture must clear policy, got {assessment.reasons}")
        result = service.execute_order(low, assessment)
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.adapter.orders), 1)
        self.assertEqual(self.queue.pending(), [])

    def test_disabled_service_still_refuses_everything(self):
        service = LiveTradingService(
            self.adapter, live_enabled=False,
            policy=TradingPolicy(preapproval_enabled=True))
        _, assessment = self._assessed()
        with self.assertRaises(LiveTradingError):
            service.execute_order(_intent(), assessment)
        self.assertEqual(self.adapter.orders, [])

    def test_blocked_order_is_refused_before_any_approval_is_consulted(self):
        intent = _intent(quantity=100.0)
        assessment = self.service.assess_order(
            intent, *_live(self.service))
        self.assertEqual(assessment.decision, "blocked")
        with self.assertRaises(LiveTradingError) as ctx:
            self.service.execute_order(intent, assessment)
        self.assertIn("blocked", str(ctx.exception).lower())
        self.assertEqual(self.adapter.orders, [])


def _intent_assessment():
    """A throwaway needs_approval verdict for hand-built queue items."""
    return RiskAssessment("needs_approval", 0.9, {
        "symbol": "BTC/USD", "exchange": "fake", "last_price": 100.0,
        "volatility_pct": 0.0, "spread_pct": 0.0, "liquidity_usd": 100000.0,
        "fetched_at": time.time(), "total_equity_usd": 1000.0,
        "free_cash_usd": 900.0, "balances": {"USD": 900, "BTC": 0.01},
    }, ())


if __name__ == "__main__":
    unittest.main()
