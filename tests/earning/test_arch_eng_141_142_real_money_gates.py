"""ARCH-ENG-141/142 — the real-money gates that could not actually block.

Three defects, each reproduced by execution before the fix and locked here so
they cannot silently return.

1. RUG SCREEN (capital loss). `rug_screen`'s two HARD-FAIL signals —
   `honeypot` and `contract_age_days < MIN_CONTRACT_AGE_DAYS` — were
   keyword-only and BOTH production callers (`discovery_sources.py:195`,
   `earning_pipeline.py:602`) invoke `screen_rug_pull(opps)` with no signals,
   so neither could ever fire. Verified by execution pre-fix: a 2-day-old
   honeypot farm at 50000% APY screened `risk=medium, passed=True` and
   survived `filter_by_risk("medium")`. An unknown contract age now FAILS
   CLOSED for any protocol outside `TRUSTED_PROTOCOLS` (an operator-side
   hardcoded allowlist, not an attacker-settable field), which is what keeps
   the only protocol that can emit today (Lido) discoverable.

2. BACKTEST FILL (analytics + any live-trade gate). `quantity = balance /
   price` made `cost = quantity*price + fees = balance*(1+fee_pct) >
   balance` STRUCTURALLY true, so at the default `fee_pct=0.001` the engine
   could never open a position. The GUI's only caller
   (`gui/tabs/analytics_tab.py:194`) uses the default, so the shipped
   analytics backtest always reported zero trades.

3. BACKTEST PnL (accounting integrity). NOTE — corrected on review: the
   pre-fix `trades[-1].price` entry expression was NOT a reachable bug. A SELL
   only runs while `position > 0`, and after a SELL `position = 0`, so the next
   SELL cannot fire until a BUY appends a trade; `trades[-1]` at any SELL is
   therefore always the buy that opened the position (verified over 6
   alternating round trips: 0 sells preceded by a non-buy). The explicit
   `_entry_price` tracking is retained for clarity only.
   What WAS reachable and is fixed: `ZeroDivisionError` on `close: 0.0`, on a
   bar with neither `close` nor `price`, and on `initial_balance=0` crashed the
   GUI tab instead of degrading to "backtest unavailable"; and a zero-price bar
   could liquidate a position for $0.

4. ROSTER PLACEMENT (VRAM collision). `_auto_device`'s tier branch was dead
   (`if tier=="big" and gpus: return gpus[0]` then `if gpus: return
   gpus[0]`), so a 1-big + 1-small roster placed BOTH brains on the SAME GPU
   — two llama.cpp servers on one card, the collision the device registry
   exists to prevent. `BrainSlot.port` was also parsed and then ignored.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.earning.backtesting import BacktestEngine, SignalType
from agents.earning.rug_screen import (MIN_CONTRACT_AGE_DAYS, TRUSTED_PROTOCOLS,
                                       screen_opportunity)
from agents.earning.defi_scanner import DeFiScanner, DeFiOpportunity
from agents.runtime.brain_roster import BrainRoster, BrainSlot


class _Opp:
    """Minimal stand-in for a DeFiOpportunity."""

    def __init__(self, protocol="QuickSwapV2", apy=50000.0, tvl=1000.0,
                 chain="ethereum", oid="farm_1"):
        self.id = oid
        self.protocol = protocol
        self.apy_percent = apy
        self.tvl_usd = tvl
        self.chain = chain
        self.risk_level = "low"


class _Dev:
    def __init__(self, id, kind, index=0, memory_gb=0.0):
        self.id, self.kind, self.index = id, kind, index
        self.name, self.memory_gb = id, memory_gb

    @property
    def is_gpu(self):
        return self.kind == "gpu"

    @property
    def is_cpu(self):
        return self.kind == "cpu"

    def capability_class(self):
        return "big" if self.memory_gb >= 16 else "small"

    def label(self):
        return self.id


class _Strategy:
    """Cycles the given signal list, so [BUY, SELL] alternates round trips."""

    def __init__(self, name="probe", signals=None):
        self.name = name
        self._signals = list(signals or [])
        self._i = 0

    def generate_signal(self, data):
        if not self._signals:
            return SignalType.HOLD
        sig = self._signals[self._i % len(self._signals)]
        self._i += 1
        return sig

    def get_parameters(self):
        return {}


def _bars(closes):
    return [{"date": f"d{i}", "close": c, "timestamp": i}
            for i, c in enumerate(closes)]


# ── 1. the rug screen can actually block ──────────────────────────────────
class RugScreenUnreachableHardFailsTest(unittest.TestCase):
    """The gate that guards capital must be able to say no."""

    def test_unknown_contract_age_fails_closed(self):
        """A protocol whose deployment date cannot be verified is not investable."""
        res = screen_opportunity(_Opp())          # production: no signals at all
        self.assertFalse(res.passed,
                         "unknown age must not pass on a capital-loss gate")
        self.assertEqual(res.risk_level, "high")

    def test_the_reported_honeypot_farm_no_longer_survives(self):
        """The exact pre-fix reproduction: 2-day-old farm, 50000% APY."""
        opp = DeFiOpportunity(id="farm_evil_1", protocol="QuickSwapV2",
                              apy_percent=50000.0, tvl_usd=1000.0,
                              chain="ethereum", risk_level="low")
        kept = DeFiScanner().filter_by_risk([opp], max_risk="medium")
        self.assertEqual([], [o.id for o in kept],
                         "a honeypot farm must not survive filter_by_risk('medium')")

    def test_trusted_protocol_carve_out_still_passes(self):
        """Lido is the only protocol that can emit today; it must stay discoverable."""
        self.assertIn("lido", TRUSTED_PROTOCOLS)
        res = screen_opportunity(_Opp(protocol="Lido", apy=3.4, oid="lido_eth"))
        self.assertTrue(res.passed)
        self.assertEqual(res.risk_level, "low")

    def test_trusted_list_is_operator_side_not_attacker_settable(self):
        """The carve-out is only safe because it is a hardcoded allowlist."""
        from agents.earning import rug_screen
        src = open(rug_screen.__file__, encoding="utf-8").read()
        # No code path may add to the set from an opportunity/API field.
        self.assertNotIn("TRUSTED_PROTOCOLS.add", src)
        self.assertNotIn("TRUSTED_PROTOCOLS.update", src)

    def test_explicit_age_signals_still_apply(self):
        """A real age reading still decides, and a young contract still hard-fails."""
        old = screen_opportunity(_Opp(), contract_age_days=90)
        self.assertTrue(old.passed)
        self.assertEqual(old.risk_level, "medium")
        young = screen_opportunity(_Opp(), contract_age_days=2)
        self.assertFalse(young.passed)
        self.assertEqual(young.risk_level, "high")

    def test_boundary_age_30_passes(self):
        """`< MIN_CONTRACT_AGE_DAYS` is strict: exactly 30 is old enough."""
        self.assertTrue(screen_opportunity(_Opp(), contract_age_days=30).passed)

    def test_honeypot_hard_fail_survives_the_rewrite(self):
        res = screen_opportunity(_Opp(), honeypot=True)
        self.assertFalse(res.passed)
        self.assertEqual(res.risk_level, "high")

    def test_no_signals_is_never_low_for_unknown_protocol(self):
        """The B5 headline invariant, unchanged."""
        self.assertNotEqual(screen_opportunity(_Opp()).risk_level, "low")


# ── 2/3. the backtest engine can fill, and its accounting is honest ───────
class BacktestFillAndAccountingTest(unittest.TestCase):
    def test_default_fee_pct_can_open_a_position(self):
        """Pre-fix this was structurally impossible: 0 trades, always."""
        res = BacktestEngine().run(
            _Strategy("always_buy", [SignalType.BUY]), _bars([100.0] * 5))
        self.assertGreater(len(res.trades), 0,
                           "default fee_pct=0.001 must still allow a fill")
        self.assertLess(res.final_balance, 10000.0, "fees must actually be charged")

    def test_repeated_round_trips_fill_at_default_fee(self):
        res = BacktestEngine().run(
            _Strategy("alt", [SignalType.BUY, SignalType.SELL]), _bars([100.0] * 5))
        self.assertGreaterEqual(len(res.trades), 3)

    def test_exact_break_even_price_still_fills(self):
        """Float fragility: qty*price can land 1 ulp above the balance."""
        for price in (100.0, 110.0, 7.0, 3.0, 1000.0):
            res = BacktestEngine(fee_pct=0.0).run(
                _Strategy("b", [SignalType.BUY]), _bars([price]))
            self.assertGreater(len(res.trades), 0,
                               f"price {price} refused a fill it could afford")

    def test_second_round_trip_pnl_measures_against_its_own_entry(self):
        """PnL across repeated round trips is measured per position.

        NOTE (corrected claim): the pre-fix `trades[-1].price` expression is NOT
        a live bug. A SELL only runs while `position > 0`, and after a SELL
        `position = 0`, so the next SELL cannot fire until a BUY appends a trade
        — meaning `trades[-1]` at any SELL is always the buy that opened the
        current position. Verified by execution over 6 alternating round trips:
        0 sells were preceded by a non-buy. The explicit `_entry_price` tracking
        is kept for clarity, not to fix a reachable defect.
        """
        engine = BacktestEngine(fee_pct=0.0)
        res = engine.run(_Strategy("alt", [SignalType.BUY, SignalType.SELL]),
                         _bars([100.0, 200.0, 150.0, 300.0]))
        sells = [t for t in res.trades if t.side == "sell"]
        self.assertEqual(len(sells), 2)
        # buy 100 units @100 -> sell @200 = +10000
        # buy 133.33 units @150 -> sell @300 = +20000
        self.assertEqual(sells[0].pnl, 10000.0)
        self.assertEqual(sells[1].pnl, 20000.0)
        self.assertEqual(res.winning_trades, 2)
        self.assertEqual(res.losing_trades, 0)
        for idx, t in enumerate(res.trades):
            if t.side == "sell" and idx > 0:
                self.assertEqual(res.trades[idx - 1].side, "buy",
                                 "a sell must be preceded by its opening buy")

    def test_zero_price_bar_does_not_crash_or_liquidate_for_free(self):
        res = BacktestEngine().run(
            _Strategy("b", [SignalType.BUY]), _bars([0.0]))
        self.assertEqual(len(res.trades), 0, "a zero price is never tradable")

    def test_missing_close_and_price_does_not_crash(self):
        res = BacktestEngine().run(
            _Strategy("b", [SignalType.BUY]), [{"other": 1, "timestamp": 1}])
        self.assertEqual(len(res.trades), 0)

    def test_zero_initial_balance_does_not_crash(self):
        res = BacktestEngine(initial_balance=0.0).run(
            _Strategy("b", [SignalType.BUY]), _bars([100.0] * 3))
        self.assertEqual(res.total_return_pct, 0.0)

    def test_zero_price_sell_does_not_liquidate_the_position(self):
        """A malformed bar must not dump the position for $0."""
        engine = BacktestEngine(fee_pct=0.0)
        res = engine.run(_Strategy("bs", [SignalType.BUY, SignalType.SELL]),
                         _bars([100.0, 0.0]))
        self.assertEqual([t for t in res.trades if t.side == "sell"], [])


# ── 4. the roster must not stack two servers on one GPU ───────────────────
class BrainRosterPlacementTest(unittest.TestCase):
    def setUp(self):
        self.devs = [_Dev("gpu0", "gpu", 0, 16.0), _Dev("gpu1", "gpu", 1, 6.0),
                     _Dev("cpu", "cpu", -1, 32.0)]

    def test_operator_port_pin_is_honoured(self):
        """Pre-fix a pin of 8080 silently became 1234."""
        roster = BrainRoster(
            big=[BrainSlot(tier="big", port=8080, device_id="gpu0")],
            small=[BrainSlot(tier="small", port=8081, device_id="gpu1")])
        ports = [p["port"] for p in roster.to_placements(self.devs)]
        self.assertEqual(ports, [8080, 8081])

    def test_auto_placement_never_reuses_a_device(self):
        """Two llama.cpp servers on one GPU is the collision we prevent."""
        roster = BrainRoster(big=[BrainSlot(tier="big", device_id="")],
                             small=[BrainSlot(tier="small", device_id="")])
        ids = [p["device_id"] for p in roster.to_placements(self.devs)]
        self.assertEqual(len(set(ids)), len(ids), f"collision on {ids}")
        self.assertEqual(ids, ["gpu0", "gpu1"])

    def test_two_big_plus_small_all_distinct(self):
        roster = BrainRoster(big=[BrainSlot(tier="big", device_id="")] * 2,
                             small=[BrainSlot(tier="small", device_id="")])
        ids = [p["device_id"] for p in roster.to_placements(self.devs)]
        self.assertEqual(len(set(ids)), len(ids), f"collision on {ids}")

    def test_single_gpu_box_falls_back_to_cpu(self):
        roster = BrainRoster(big=[BrainSlot(tier="big", device_id="")],
                             small=[BrainSlot(tier="small", device_id="")])
        ids = [p["device_id"] for p in
               roster.to_placements(self.devs[:1] + [self.devs[2]])]
        self.assertEqual(ids, ["gpu0", "cpu"])

    def test_big_slot_prefers_a_big_capability_device(self):
        """A 4 GB card listed first must not host the big brain."""
        devs = [_Dev("tiny", "gpu", 0, 4.0), _Dev("big", "gpu", 1, 24.0),
                _Dev("cpu", "cpu", -1, 32.0)]
        roster = BrainRoster(big=[BrainSlot(tier="big", device_id="")],
                             small=[BrainSlot(tier="small", device_id="")])
        ids = [p["device_id"] for p in roster.to_placements(devs)]
        self.assertEqual(ids[0], "big", f"big brain landed on {ids[0]}")


if __name__ == "__main__":
    unittest.main()
