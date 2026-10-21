"""
agents/backtesting.py — Strategy backtesting engine (v2.1 Phase 2).

Backtests trading strategies on historical data:
- Load historical price data
- Run strategy simulation
- Calculate performance metrics
- Generate reports
- Compare multiple strategies
"""

import time
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime, timedelta
from enum import Enum


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Trade:
    """Simulated trade."""
    timestamp: float
    symbol: str
    side: str  # buy/sell
    quantity: float
    price: float
    fees: float
    pnl: float = 0.0


@dataclass
class BacktestResult:
    """Results of a backtest run."""
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    initial_balance: float
    final_balance: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    sharpe_ratio: float
    max_drawdown_pct: float
    average_trade_return: float
    profit_factor: float
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[Tuple[float, float]] = field(default_factory=list)


class Strategy:
    """Base class for trading strategies."""
    
    name: str = "base"
    
    def generate_signal(self, data: Dict) -> SignalType:
        """Generate a trading signal from market data."""
        return SignalType.HOLD
    
    def get_parameters(self) -> Dict:
        """Get strategy parameters."""
        return {}
    
    def set_parameters(self, params: Dict):
        """Set strategy parameters."""
        pass


class MovingAverageCrossover(Strategy):
    """Moving Average Crossover strategy."""
    
    name = "ma_crossover"
    
    def __init__(self, fast_period: int = 10, slow_period: int = 30):
        self.fast_period = fast_period
        self.slow_period = slow_period
    
    def generate_signal(self, data: Dict) -> SignalType:
        prices = data.get("prices", [])
        if len(prices) < self.slow_period:
            return SignalType.HOLD
        
        fast_ma = sum(prices[-self.fast_period:]) / self.fast_period
        slow_ma = sum(prices[-self.slow_period:]) / self.slow_period
        
        prev_fast = sum(prices[-self.fast_period-1:-1]) / self.fast_period
        prev_slow = sum(prices[-self.slow_period-1:-1]) / self.slow_period
        
        # Golden cross
        if prev_fast <= prev_slow and fast_ma > slow_ma:
            return SignalType.BUY
        # Death cross
        elif prev_fast >= prev_slow and fast_ma < slow_ma:
            return SignalType.SELL
        
        return SignalType.HOLD
    
    def get_parameters(self) -> Dict:
        return {"fast_period": self.fast_period, "slow_period": self.slow_period}


class RSIStrategy(Strategy):
    """Relative Strength Index strategy."""
    
    name = "rsi"
    
    def __init__(self, period: int = 14, overbought: float = 70, oversold: float = 30):
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
    
    def generate_signal(self, data: Dict) -> SignalType:
        prices = data.get("prices", [])
        if len(prices) < self.period + 1:
            return SignalType.HOLD
        
        # Calculate RSI
        gains = []
        losses = []
        for i in range(-self.period, 0):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / self.period
        avg_loss = sum(losses) / self.period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        if rsi < self.oversold:
            return SignalType.BUY
        elif rsi > self.overbought:
            return SignalType.SELL
        
        return SignalType.HOLD
    
    def get_parameters(self) -> Dict:
        return {"period": self.period, "overbought": self.overbought, "oversold": self.oversold}


class BacktestEngine:
    """Backtest trading strategies on historical data."""
    
    def __init__(self, initial_balance: float = 10000.0, fee_pct: float = 0.001):
        self.initial_balance = initial_balance
        self.fee_pct = fee_pct
        self.results: List[BacktestResult] = []
        self._entry_price = 0.0    # ARCH-ENG-142: the open position's entry price
    
    def run(self, strategy: Strategy, data: List[Dict], symbol: str = "UNKNOWN") -> BacktestResult:
        """Run a backtest."""
        balance = self.initial_balance
        position = 0.0
        trades = []
        equity_curve = []
        self._entry_price = 0.0    # ARCH-ENG-142: this position's real entry
        
        prices = []
        for i, bar in enumerate(data):
            price = bar.get("close", bar.get("price", 0))
            prices.append(price)
            
            # Prepare data for strategy
            signal_data = {
                "prices": prices[:i+1],
                "current_price": price,
                "bar": bar,
            }
            
            signal = strategy.generate_signal(signal_data)
            
            if signal == SignalType.BUY and balance > 0:
                # Size the position so notional + fees actually fits the balance.
                # ARCH-ENG-142: the old `quantity = balance / price` made
                # `cost = quantity*price + fees = balance*(1 + fee_pct) > balance`
                # STRUCTURALLY always true, so with the default fee_pct=0.001 the
                # engine could never open a position (reproduced: an always-BUY
                # strategy over 5 bars produced 0 trades). Reserving the fee out
                # of the balance first makes the fill affordable at any fee_pct.
                if price <= 0:
                    continue        # a zero/negative price is never tradable
                spendable = balance / (1.0 + self.fee_pct)
                quantity = spendable / price
                fees = spendable * self.fee_pct
                cost = quantity * price + fees

                # ARCH-ENG-142: an epsilon on the affordability check. At exact
                # break-even, `quantity*price + fees` can land 1 ulp above the
                # balance (e.g. price 110.0, balance 1000.0), so the old strict
                # `cost <= balance` silently refused every fill and the engine
                # reported zero trades for a working strategy.
                if cost <= balance + 1e-9:
                    balance -= cost
                    position += quantity
                    self._entry_price = price   # ARCH-ENG-142: track the real entry
                    trades.append(Trade(
                        timestamp=bar.get("timestamp", time.time()),
                        symbol=symbol,
                        side="buy",
                        quantity=quantity,
                        price=price,
                        fees=fees,
                    ))
            
            elif signal == SignalType.SELL and position > 0:
                # ARCH-ENG-142: a zero/negative price is never tradable; without
                # this guard a malformed bar liquidates the position for $0.
                if price <= 0:
                    continue
                # Sell entire position
                proceeds = position * price
                fees = proceeds * self.fee_pct
                # ARCH-ENG-142: PnL must be measured against THIS position's
                # entry price, not `trades[-1].price` — after a prior sell that
                # is the previous SELL price, so a second round trip booked
                # pnl=0 and corrupted win_rate / profit_factor (reproduced).
                entry = self._entry_price if self._entry_price else (
                    trades[-1].price if trades else 0)
                pnl = proceeds - (position * entry) - fees
                
                balance += proceeds - fees
                
                trades.append(Trade(
                    timestamp=bar.get("timestamp", time.time()),
                    symbol=symbol,
                    side="sell",
                    quantity=position,
                    price=price,
                    fees=fees,
                    pnl=pnl,
                ))
                
                position = 0
            
            # Record equity
            current_equity = balance + (position * price)
            equity_curve.append((bar.get("timestamp", time.time()), current_equity))
        
        # Calculate metrics
        final_balance = balance + (position * prices[-1] if prices else 0)
        # ARCH-ENG-142: a zero/absent initial balance or a zero price used to
        # raise ZeroDivisionError out of the GUI tab instead of degrading to a
        # "backtest unavailable" result (reproduced on close:0.0, on a bar with
        # neither close nor price, and on initial_balance=0).
        if self.initial_balance > 0:
            total_return = (final_balance / self.initial_balance - 1) * 100
        else:
            total_return = 0.0
        
        winning = sum(1 for t in trades if t.pnl > 0)
        losing = sum(1 for t in trades if t.pnl < 0)
        win_rate = winning / (winning + losing) if (winning + losing) > 0 else 0
        
        # Sharpe ratio
        returns = []
        for i in range(1, len(equity_curve)):
            prev_eq = equity_curve[i-1][1]
            curr_eq = equity_curve[i][1]
            if prev_eq > 0:
                returns.append((curr_eq - prev_eq) / prev_eq)
        
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = (sum((r - avg_return)**2 for r in returns) / len(returns))**0.5 if returns else 0
        sharpe = avg_return / std_return if std_return > 0 else 0.0
        
        # Ensure sharpe is a valid float (not NaN or inf)
        if not isinstance(sharpe, float) or sharpe != sharpe:  # NaN check
            sharpe = 0.0
        
        # Max drawdown
        peak = self.initial_balance
        max_dd = 0
        for _, eq in equity_curve:
            if eq > peak:
                peak = eq
            # ARCH-ENG-142: a zero peak (initial_balance=0) used to divide by
            # zero here.
            if peak > 0:
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd
        
        # Profit factor
        gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        result = BacktestResult(
            strategy_name=strategy.name,
            symbol=symbol,
            start_date=data[0].get("date", "") if data else "",
            end_date=data[-1].get("date", "") if data else "",
            initial_balance=self.initial_balance,
            final_balance=final_balance,
            total_return_pct=total_return,
            total_trades=len([t for t in trades if t.side == "sell"]),
            winning_trades=winning,
            losing_trades=losing,
            win_rate=win_rate,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd * 100,
            average_trade_return=total_return / len(trades) if trades else 0,
            profit_factor=profit_factor,
            trades=trades,
            equity_curve=equity_curve,
        )
        
        self.results.append(result)
        return result
    
    def compare_strategies(self) -> List[Dict]:
        """Compare all backtested strategies."""
        comparison = []
        for result in self.results:
            comparison.append({
                "strategy": result.strategy_name,
                "symbol": result.symbol,
                "return_pct": result.total_return_pct,
                "sharpe": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown_pct,
                "win_rate": result.win_rate,
                "trades": result.total_trades,
                "profit_factor": result.profit_factor,
            })
        
        # Sort by Sharpe ratio
        comparison.sort(key=lambda x: x["sharpe"], reverse=True)
        return comparison
    
    def get_best_strategy(self) -> Optional[BacktestResult]:
        """Get the best performing strategy by Sharpe ratio."""
        if not self.results:
            return None
        return max(self.results, key=lambda r: r.sharpe_ratio)
    
    def generate_report(self, result: BacktestResult) -> str:
        """Generate a text report for a backtest result."""
        return f"""
╔══════════════════════════════════════════════════════════════╗
║                    BACKTEST RESULTS                         ║
╠══════════════════════════════════════════════════════════════╣
║  Strategy:        {result.strategy_name:<40} ║
║  Symbol:          {result.symbol:<40} ║
║  Period:          {result.start_date} to {result.end_date:<20} ║
╠══════════════════════════════════════════════════════════════╣
║  Initial Balance: ${result.initial_balance:>12,.2f}                  ║
║  Final Balance:   ${result.final_balance:>12,.2f}                  ║
║  Total Return:     {result.total_return_pct:>11.2f}%                  ║
╠══════════════════════════════════════════════════════════════╣
║  Total Trades:     {result.total_trades:>11d}                  ║
║  Winning Trades:   {result.winning_trades:>11d}                  ║
║  Losing Trades:    {result.losing_trades:>11d}                  ║
║  Win Rate:         {result.win_rate*100:>11.1f}%                  ║
╠══════════════════════════════════════════════════════════════╣
║  Sharpe Ratio:     {result.sharpe_ratio:>11.4f}                  ║
║  Max Drawdown:     {result.max_drawdown_pct:>11.2f}%                  ║
║  Profit Factor:    {result.profit_factor:>11.2f}                  ║
╚══════════════════════════════════════════════════════════════╝
"""
