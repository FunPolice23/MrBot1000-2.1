import unittest
import math
import tempfile
from unittest.mock import patch

from agents.paper_trading import OrderSide, PaperTradingEngine


class TestPaperTradingEngine(unittest.TestCase):
    def test_rejects_zero_price_and_excessive_notional(self):
        engine = PaperTradingEngine(initial_balance=1000.0)
        self.assertIsNone(engine.place_order("TEST", OrderSide.BUY, 1, price=0.0))
        engine.max_order_notional = 50.0
        self.assertIsNone(engine.place_order("TEST", OrderSide.BUY, 1, price=100.0))

    def test_zero_starting_balance_has_safe_performance_metrics(self):
        engine = PaperTradingEngine(initial_balance=0.0)
        performance = engine.get_performance()
        self.assertEqual(performance["total_return_pct"], 0.0)

    def test_closed_position_keeps_realized_pnl_in_performance(self):
        engine = PaperTradingEngine(initial_balance=1000.0)
        buy = engine.place_order("TEST", OrderSide.BUY, 1, price=100.0)
        self.assertIsNotNone(buy)
        engine.update_price("TEST", 110.0)
        sell = engine.place_order("TEST", OrderSide.SELL, 1, price=110.0)
        self.assertIsNotNone(sell)
        self.assertIsNone(engine.get_position("TEST"))
        self.assertGreater(engine.get_performance()["realized_pnl"], 0.0)

    def test_performance_is_explicitly_virtual_and_orders_are_audited(self):
        engine = PaperTradingEngine(initial_balance=1000.0)
        order = engine.place_order("TEST", OrderSide.BUY, 1, price=100.0)
        performance = engine.get_performance()

        self.assertIsNotNone(order)
        self.assertTrue(performance["simulation_only"])
        self.assertEqual(performance["execution_mode"], "virtual")
        self.assertTrue(all(event["simulation_only"] for event in engine.audit_log))
        self.assertIn("order_filled", {event["event"] for event in engine.audit_log})

    def test_invalid_finite_inputs_are_rejected_or_raise(self):
        engine = PaperTradingEngine(initial_balance=1000.0)
        self.assertIsNone(engine.place_order("", OrderSide.BUY, 1, price=100.0))
        self.assertIsNone(engine.place_order("TEST", OrderSide.BUY, math.inf, price=100.0))
        with self.assertRaises(ValueError):
            engine.update_price("TEST", math.nan)
        self.assertIn("order_rejected", {event["event"] for event in engine.audit_log})

    def test_audit_log_survives_engine_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            audit_path = f"{folder}/paper-trading.jsonl"
            engine = PaperTradingEngine(initial_balance=1000.0, audit_path=audit_path)
            engine.place_order("TEST", OrderSide.BUY, 1, price=100.0)
            restored = PaperTradingEngine(initial_balance=1000.0, audit_path=audit_path)

        self.assertGreaterEqual(len(restored.audit_log), 1)
        self.assertTrue(all(event["simulation_only"] for event in restored.audit_log))

    def test_paper_engine_has_no_external_execution_path(self):
        engine = PaperTradingEngine(initial_balance=1000.0)
        with patch("urllib.request.urlopen", side_effect=AssertionError("network access")):
            engine.place_order("TEST", OrderSide.BUY, 1, price=100.0)
            engine.update_price("TEST", 101.0)
        self.assertFalse(engine.EXTERNAL_EXECUTION_ENABLED)


if __name__ == "__main__":
    unittest.main()