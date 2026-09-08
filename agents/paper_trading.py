"""
agents/paper_trading.py — Paper trading engine for safe strategy validation (v2.1 Phase 1).

Simulates trading without real money:
- Virtual portfolio with configurable initial balance
- Real-time market data (when available)
- Order simulation with slippage and fees
- Performance tracking and reporting
- Strategy backtesting on historical data
"""

import time
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    """Simulated order."""
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: float
    price: float
    status: str = "pending"
    filled: float = 0.0
    average_price: float = 0.0
    created_at: float = field(default_factory=time.time)
    filled_at: Optional[float] = None
    fees: float = 0.0


@dataclass
class Position:
    """Portfolio position."""
    symbol: str
    quantity: float
    average_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class Trade:
    """Completed trade."""
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    fees: float
    timestamp: float
    pnl: float = 0.0


class PaperTradingEngine:
    """Paper trading engine with virtual portfolio."""
    
    def __init__(self, initial_balance: float = 10000.0, config_path: str = ""):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.positions: Dict[str, Position] = {}
        self.orders: List[Order] = []
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[float, float]] = []  # (timestamp, equity)
        
        # Configuration
        self.slippage_pct = 0.001  # 0.1% slippage
        self.fee_pct = 0.001  # 0.1% trading fee
        self.min_order_size = 1.0
        
        # Load config if provided
        if config_path and os.path.exists(config_path):
            with open(config_path) as f:
                config = json.load(f)
                self.slippage_pct = config.get("slippage_pct", self.slippage_pct)
                self.fee_pct = config.get("fee_pct", self.fee_pct)
                self.min_order_size = config.get("min_order_size", self.min_order_size)
    
    def get_equity(self) -> float:
        """Calculate total equity (cash + positions)."""
        positions_value = sum(pos.quantity * pos.current_price for pos in self.positions.values())
        return self.cash + positions_value
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a symbol."""
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> List[Position]:
        """Get all positions."""
        return list(self.positions.values())
    
    def update_price(self, symbol: str, price: float):
        """Update current price for a symbol."""
        if symbol in self.positions:
            pos = self.positions[symbol]
            pos.current_price = price
            pos.unrealized_pnl = (price - pos.average_price) * pos.quantity
        
        # Check limit orders
        self._check_limit_orders(symbol, price)
    
    def place_order(self, symbol: str, side: OrderSide, quantity: float,
                    order_type: OrderType = OrderType.MARKET, price: float = 0.0) -> Optional[Order]:
        """Place an order."""
        # Validate
        if quantity < self.min_order_size:
            return None
        
        # For market orders, use current price
        if order_type == OrderType.MARKET:
            pos = self.positions.get(symbol)
            price = pos.current_price if pos else price
        
        # Check buying power
        if side == OrderSide.BUY:
            cost = quantity * price * (1 + self.fee_pct)
            if cost > self.cash:
                return None  # Insufficient funds
        else:
            # Check position exists
            pos = self.positions.get(symbol)
            if not pos or pos.quantity < quantity:
                return None  # Insufficient position
        
        # Create order
        order = Order(
            id=f"paper_{int(time.time()*1000)}",
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
        )
        
        # Execute market orders immediately
        if order_type == OrderType.MARKET:
            self._execute_order(order)
        else:
            self.orders.append(order)
        
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        for order in self.orders:
            if order.id == order_id and order.status == "pending":
                order.status = "cancelled"
                return True
        return False
    
    def _execute_order(self, order: Order):
        """Execute an order."""
        # Apply slippage
        if order.side == OrderSide.BUY:
            fill_price = order.price * (1 + self.slippage_pct)
        else:
            fill_price = order.price * (1 - self.slippage_pct)
        
        # Calculate fees
        fees = order.quantity * fill_price * self.fee_pct
        
        # Update cash
        if order.side == OrderSide.BUY:
            cost = order.quantity * fill_price + fees
            self.cash -= cost
        else:
            proceeds = order.quantity * fill_price - fees
            self.cash += proceeds
        
        # Update position
        if order.symbol not in self.positions:
            self.positions[order.symbol] = Position(
                symbol=order.symbol,
                quantity=0.0,
                average_price=0.0,
                current_price=fill_price,
            )
        
        pos = self.positions[order.symbol]
        
        if order.side == OrderSide.BUY:
            # Update average price
            total_cost = pos.average_price * pos.quantity + fill_price * order.quantity
            pos.quantity += order.quantity
            pos.average_price = total_cost / pos.quantity if pos.quantity > 0 else 0
        else:
            # Calculate PnL
            pnl = (fill_price - pos.average_price) * order.quantity - fees
            pos.realized_pnl += pnl
            pos.quantity -= order.quantity
            
            # Remove position if fully closed
            if pos.quantity <= 0:
                del self.positions[order.symbol]
        
        # Record trade
        trade = Trade(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            fees=fees,
            timestamp=time.time(),
        )
        self.trades.append(trade)
        
        # Update order status
        order.status = "filled"
        order.filled = order.quantity
        order.average_price = fill_price
        order.fees = fees
        order.filled_at = time.time()
        
        # Update equity curve
        self.equity_curve.append((time.time(), self.get_equity()))
    
    def _check_limit_orders(self, symbol: str, price: float):
        """Check and execute limit orders."""
        for order in self.orders:
            if order.status != "pending" or order.symbol != symbol:
                continue
            
            if order.type == OrderType.LIMIT:
                if order.side == OrderSide.BUY and price <= order.price:
                    self._execute_order(order)
                elif order.side == OrderSide.SELL and price >= order.price:
                    self._execute_order(order)
            
            elif order.type == OrderType.STOP:
                if order.side == OrderSide.BUY and price >= order.price:
                    self._execute_order(order)
                elif order.side == OrderSide.SELL and price <= order.price:
                    self._execute_order(order)
    
    def get_performance(self) -> Dict:
        """Get performance metrics."""
        equity = self.get_equity()
        total_return = (equity / self.initial_balance - 1) * 100
        
        # Calculate Sharpe ratio (simplified)
        returns = []
        for i in range(1, len(self.equity_curve)):
            prev_equity = self.equity_curve[i-1][1]
            curr_equity = self.equity_curve[i][1]
            if prev_equity > 0:
                returns.append((curr_equity - prev_equity) / prev_equity)
        
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = (sum((r - avg_return)**2 for r in returns) / len(returns))**0.5 if returns else 0
        sharpe = avg_return / std_return if std_return > 0 else 0
        
        # Calculate max drawdown
        peak = self.initial_balance
        max_drawdown = 0
        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        return {
            "initial_balance": self.initial_balance,
            "current_equity": equity,
            "cash": self.cash,
            "positions_value": equity - self.cash,
            "total_return_pct": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_drawdown * 100,
            "total_trades": len(self.trades),
            "open_positions": len(self.positions),
            "total_fees": sum(t.fees for t in self.trades),
            "realized_pnl": sum(p.realized_pnl for p in self.positions.values()),
            "unrealized_pnl": sum(p.unrealized_pnl for p in self.positions.values()),
        }
    
    def get_report(self) -> str:
        """Generate a text performance report."""
        perf = self.get_performance()
        
        report = f"""
╔══════════════════════════════════════════════════════════════╗
║              PAPER TRADING PERFORMANCE REPORT               ║
╠══════════════════════════════════════════════════════════════╣
║  Initial Balance:    ${perf['initial_balance']:>12,.2f}                  ║
║  Current Equity:     ${perf['current_equity']:>12,.2f}                  ║
║  Total Return:        {perf['total_return_pct']:>11.2f}%                  ║
║  Sharpe Ratio:        {perf['sharpe_ratio']:>11.4f}                  ║
║  Max Drawdown:        {perf['max_drawdown_pct']:>11.2f}%                  ║
╠══════════════════════════════════════════════════════════════╣
║  Total Trades:        {perf['total_trades']:>11d}                  ║
║  Open Positions:      {perf['open_positions']:>11d}                  ║
║  Total Fees:          ${perf['total_fees']:>12,.4f}                  ║
║  Realized PnL:        ${perf['realized_pnl']:>12,.2f}                  ║
║  Unrealized PnL:      ${perf['unrealized_pnl']:>12,.2f}                  ║
╚══════════════════════════════════════════════════════════════╝
"""
        return report
