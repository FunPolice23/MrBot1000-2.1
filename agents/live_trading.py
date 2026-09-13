"""Live portfolio and trading service with deterministic risk controls.

This module is intentionally separate from ``paper_trading``. It reads real
exchange state through the optional ccxt package and can submit real orders only
when the operator explicitly enables live trading and supplies an approved order
decision. Model output may explain or rank an order, but never overrides these
controls.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class LiveTradingError(RuntimeError):
    """Raised when a live-trading precondition fails."""


@dataclass(frozen=True)
class PortfolioSnapshot:
    exchange: str
    total_equity_usd: float
    free_cash_usd: float
    balances: Dict[str, float] = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    last_price: float
    volatility_pct: float = 0.0
    spread_pct: float = 0.0
    liquidity_usd: float = 0.0
    fetched_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TradeIntent:
    exchange: str
    symbol: str
    side: str
    quantity: float
    order_type: str = "market"
    limit_price: float = 0.0
    expected_profit_pct: float = 0.0
    strategy_confidence: float = 0.0
    asset_class: str = "unknown"  # stable | major | alt | meme | unknown
    reasoning: str = ""


@dataclass(frozen=True)
class RiskAssessment:
    decision: str  # preapproved | needs_approval | blocked
    risk_score: float
    factors: Dict[str, Any]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TradingPolicy:
    """Hard limits for one exchange account.

    ``preapproval_enabled`` allows only the low-risk tier to execute without a
    new approval item. It never bypasses blocked conditions.
    """

    preapproval_enabled: bool = False
    max_order_usd: float = 100.0
    max_position_pct: float = 0.05
    max_daily_loss_pct: float = 0.02
    max_volatility_pct: float = 12.0
    max_spread_pct: float = 1.0
    min_liquidity_multiple: float = 20.0
    min_confidence: float = 0.70
    min_expected_profit_pct: float = 0.25
    max_market_data_age_seconds: float = 30.0


class CcxtExchangeAdapter:
    """Optional ccxt adapter for real exchange reads and order submission."""

    def __init__(self, exchange_id: str, api_key: str = "", secret: str = "",
                 password: str = "", sandbox: bool = False):
        self.exchange_id = exchange_id.lower().strip()
        if not self.exchange_id.replace("_", "").isalnum():
            raise LiveTradingError("Invalid exchange identifier")
        try:
            import ccxt
        except ImportError as exc:
            raise LiveTradingError(
                "Live trading requires optional dependency 'ccxt'"
            ) from exc
        exchange_type = getattr(ccxt, self.exchange_id, None)
        if exchange_type is None:
            raise LiveTradingError(f"Unsupported ccxt exchange: {self.exchange_id}")
        self.client = exchange_type({
            "apiKey": api_key,
            "secret": secret,
            "password": password,
            "enableRateLimit": True,
        })
        if sandbox and hasattr(self.client, "set_sandbox_mode"):
            try:
                self.client.set_sandbox_mode(True)
            except Exception as exc:
                raise LiveTradingError(
                    f"Sandbox mode is unavailable for exchange '{self.exchange_id}'; "
                    "set its sandbox setting to false"
                ) from exc

    def fetch_balance(self) -> Dict[str, Any]:
        return self.client.fetch_balance()

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return self.client.fetch_ticker(symbol)

    def fetch_order_book(self, symbol: str) -> Dict[str, Any]:
        return self.client.fetch_order_book(symbol)

    def create_order(self, symbol: str, order_type: str, side: str,
                     quantity: float, price: Optional[float] = None) -> Dict[str, Any]:
        return self.client.create_order(symbol, order_type, side, quantity, price)


class LiveTradingService:
    """Live account reader and guarded order executor."""

    def __init__(self, adapter: Any = None, policy: Optional[TradingPolicy] = None,
                 live_enabled: Optional[bool] = None):
        self.adapter = adapter
        self.policy = policy or TradingPolicy()
        self.live_enabled = (
            os.getenv("MRBOT_LIVE_TRADING_ENABLED", "false").lower()
            in {"1", "true", "yes"}
            if live_enabled is None else bool(live_enabled)
        )

    def status(self) -> Dict[str, Any]:
        enabled = self.live_enabled and self.adapter is not None
        return {
            "configured": self.adapter is not None,
            "live_enabled": self.live_enabled,
            "execution_mode": "live" if enabled else "disabled",
            "preapproval_enabled": self.policy.preapproval_enabled,
        }

    def sync_portfolio(self) -> PortfolioSnapshot:
        self._require_adapter()
        raw = self.adapter.fetch_balance()
        totals = raw.get("total", {}) or {}
        free = raw.get("free", {}) or {}
        balances = {
            str(asset): float(amount or 0.0)
            for asset, amount in totals.items()
            if float(amount or 0.0) > 0
        }
        price_cache = {}
        total_usd = self._usd_value(raw, "total", price_cache)
        free_usd = self._usd_value(raw, "free", price_cache)
        return PortfolioSnapshot(
            exchange=getattr(self.adapter, "exchange_id", "configured"),
            total_equity_usd=total_usd,
            free_cash_usd=free_usd,
            balances=balances,
        )

    def fetch_market_snapshot(self, symbol: str) -> MarketSnapshot:
        """Build a risk input from fresh ticker and order-book data."""
        self._require_adapter()
        ticker = self.adapter.fetch_ticker(symbol) or {}
        order_book = self.adapter.fetch_order_book(symbol) or {}
        try:
            last_price = float(ticker.get("last") or ticker.get("close") or 0.0)
            bids = self._book_levels(order_book.get("bids"))
            asks = self._book_levels(order_book.get("asks"))
        except (TypeError, ValueError) as exc:
            raise LiveTradingError("Exchange returned malformed market data") from exc
        if last_price <= 0 or not bids or not asks:
            raise LiveTradingError("Exchange returned incomplete market data")
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            raise LiveTradingError("Exchange returned an invalid order book")
        midpoint = (best_bid + best_ask) / 2
        spread_pct = (best_ask - best_bid) / midpoint * 100 if midpoint else 100.0
        liquidity_usd = sum(price * amount for price, amount in (bids[:5] + asks[:5]))
        fetched_at = float(ticker.get("timestamp") or 0.0) / 1000
        if fetched_at <= 0:
            fetched_at = time.time()
        return MarketSnapshot(
            symbol=symbol,
            last_price=last_price,
            volatility_pct=abs(float(ticker.get("percentage") or 0.0)),
            spread_pct=spread_pct,
            liquidity_usd=liquidity_usd,
            fetched_at=fetched_at,
        )

    def assess_order(self, intent: TradeIntent, portfolio: PortfolioSnapshot,
                     market: MarketSnapshot, daily_loss_pct: float = 0.0) -> RiskAssessment:
        self._validate_intent(intent, market)
        adapter_exchange = getattr(self.adapter, "exchange_id", "")
        if adapter_exchange and intent.exchange.lower() != adapter_exchange.lower():
            raise LiveTradingError("Order exchange does not match configured adapter")
        if time.time() - market.fetched_at > self.policy.max_market_data_age_seconds:
            raise LiveTradingError("Market data is stale; refresh before assessing the order")
        notional = intent.quantity * market.last_price
        position_pct = notional / portfolio.total_equity_usd if portfolio.total_equity_usd else 1.0
        liquidity_ratio = market.liquidity_usd / notional if notional else 0.0
        score = 0.0
        reasons = []
        base_asset, quote_asset = self._split_symbol(intent.symbol)
        available_quote = portfolio.balances.get(quote_asset, portfolio.free_cash_usd)
        available_base = portfolio.balances.get(base_asset, 0.0)

        if intent.side.lower() == "buy" and notional > available_quote:
            reasons.append("buy exceeds available quote-asset balance")
            score += 0.50
        if intent.side.lower() == "sell" and intent.quantity > available_base:
            reasons.append("sell exceeds available base-asset balance")
            score += 0.50

        if notional > self.policy.max_order_usd:
            reasons.append("order exceeds maximum notional")
            score += 0.35
        if position_pct > self.policy.max_position_pct:
            reasons.append("order exceeds maximum portfolio allocation")
            score += 0.25
        if daily_loss_pct >= self.policy.max_daily_loss_pct:
            reasons.append("daily loss limit reached")
            score += 0.35
        if market.volatility_pct > self.policy.max_volatility_pct:
            reasons.append("market volatility exceeds policy")
            score += 0.20
        if market.spread_pct > self.policy.max_spread_pct:
            reasons.append("spread exceeds policy")
            score += 0.15
        if liquidity_ratio < self.policy.min_liquidity_multiple:
            reasons.append("market liquidity is insufficient")
            score += 0.20
        if intent.strategy_confidence < self.policy.min_confidence:
            reasons.append("strategy confidence is below policy")
            score += 0.15
        if intent.expected_profit_pct < self.policy.min_expected_profit_pct:
            reasons.append("expected profit does not cover policy threshold")
            score += 0.10
        if intent.asset_class == "meme":
            reasons.append("meme asset requires elevated review")
            score += 0.30
        elif intent.asset_class == "unknown":
            reasons.append("asset classification is unknown")
            score += 0.20

        score = min(1.0, score)
        if (daily_loss_pct >= self.policy.max_daily_loss_pct
            or notional > self.policy.max_order_usd * 2
            or (intent.side.lower() == "buy" and notional > available_quote)
            or (intent.side.lower() == "sell" and intent.quantity > available_base)):
            decision = "blocked"
        elif score >= 0.35 or not self.policy.preapproval_enabled:
            decision = "needs_approval"
        else:
            decision = "preapproved"
        return RiskAssessment(decision, score, {
            "notional_usd": notional,
            "position_pct": position_pct,
            "liquidity_multiple": liquidity_ratio,
            "asset_class": intent.asset_class,
            "daily_loss_pct": daily_loss_pct,
        }, tuple(reasons))

    def execute_order(self, intent: TradeIntent, assessment: RiskAssessment,
                      approval_id: str = "") -> Dict[str, Any]:
        self._require_adapter()
        if not self.live_enabled:
            raise LiveTradingError("Live trading is disabled; no order was submitted")
        if assessment.decision == "blocked":
            raise LiveTradingError("Order blocked: " + "; ".join(assessment.reasons))
        if assessment.decision == "needs_approval" and not self._is_approved(approval_id):
            raise LiveTradingError("Human approval is required before live execution")
        order = self.adapter.create_order(
            intent.symbol, intent.order_type, intent.side, intent.quantity,
            intent.limit_price or None,
        )
        return {"ok": True, "execution_mode": "live", "client_order_id": uuid.uuid4().hex,
                "order": order}

    def propose_order(self, intent: TradeIntent, assessment: RiskAssessment) -> Dict[str, Any]:
        """Create an approval item for an order that cannot be preapproved."""
        if assessment.decision == "blocked":
            return {"ok": False, "status": "blocked", "reasons": assessment.reasons}
        if assessment.decision == "preapproved":
            return {"ok": True, "status": "preapproved", "assessment": assessment}
        from agents.approval_queue import ApprovalKind, ApprovalItem, HumanApprovalQueue
        item = HumanApprovalQueue.instance().enqueue(ApprovalItem(
            kind=ApprovalKind.ACTION,
            title=f"Live {intent.side.upper()} {intent.quantity:g} {intent.symbol}",
            description="Review the deterministic risk factors before live order submission.",
            requested_by="live_trading",
            details={"assessment": assessment.factors, "reasons": list(assessment.reasons)},
            payload={"intent": intent.__dict__},
        ))
        return {"ok": True, "status": "awaiting_approval", "approval_id": item.id,
                "assessment": assessment}

    @staticmethod
    def _is_approved(approval_id: str) -> bool:
        if approval_id:
            from agents.approval_queue import ApprovalStatus, HumanApprovalQueue
            item = HumanApprovalQueue.instance().find_by_id(approval_id)
            return item is not None and item.status == ApprovalStatus.APPROVED
        return False

    def _require_adapter(self) -> None:
        if self.adapter is None:
            raise LiveTradingError("No live exchange adapter is configured")

    @staticmethod
    def _book_levels(levels: Any) -> list[tuple[float, float]]:
        if not isinstance(levels, (list, tuple)):
            return []
        parsed = []
        for level in levels:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue
            price = float(level[0])
            amount = float(level[1])
            if price > 0 and amount > 0:
                parsed.append((price, amount))
        return parsed

    @staticmethod
    def _validate_intent(intent: TradeIntent, market: MarketSnapshot) -> None:
        if intent.side.lower() not in {"buy", "sell"}:
            raise LiveTradingError("Order side must be buy or sell")
        if intent.quantity <= 0 or market.last_price <= 0:
            raise LiveTradingError("Order quantity and market price must be positive")
        if intent.order_type.lower() not in {"market", "limit", "stop", "stop_limit"}:
            raise LiveTradingError("Unsupported order type")
        if intent.symbol != market.symbol:
            raise LiveTradingError("Market snapshot does not match order symbol")

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str, str]:
        parts = symbol.upper().replace("-", "/").split("/")
        if len(parts) != 2 or not all(parts):
            raise LiveTradingError("Trading symbol must use BASE/QUOTE format")
        return parts[0], parts[1]

    def _usd_value(self, raw: Dict[str, Any], bucket: str,
                   price_cache: Dict[str, float]) -> float:
        value = raw.get("info", {}).get(f"{bucket}_usd")
        if value is not None:
            return float(value or 0.0)
        balances = raw.get(bucket, {}) or {}
        total = 0.0
        for asset, amount in balances.items():
            amount = float(amount or 0.0)
            if amount <= 0:
                continue
            asset = str(asset).upper()
            if asset in {"USD", "USDT", "USDC", "DAI"}:
                price = 1.0
            else:
                price = price_cache.get(asset)
                if price is None:
                    price = self._fetch_asset_usd_price(asset)
                    price_cache[asset] = price
            total += amount * price
        return total

    def _fetch_asset_usd_price(self, asset: str) -> float:
        for quote in ("USD", "USDT", "USDC"):
            try:
                ticker = self.adapter.fetch_ticker(f"{asset}/{quote}") or {}
                price = float(ticker.get("last") or ticker.get("close") or 0.0)
            except Exception:
                continue
            if price > 0:
                return price
        raise LiveTradingError(f"No USD valuation price is available for {asset}")


def adapter_from_env(exchange_id: str) -> CcxtExchangeAdapter:
    """Create an adapter from exchange-specific environment variables."""
    prefix = exchange_id.upper().replace("-", "_")
    return CcxtExchangeAdapter(
        exchange_id,
        api_key=os.getenv(f"{prefix}_API_KEY", ""),
        secret=os.getenv(f"{prefix}_API_SECRET", ""),
        password=os.getenv(f"{prefix}_API_PASSWORD", ""),
        sandbox=os.getenv(f"{prefix}_SANDBOX", "false").lower() in {"1", "true", "yes"},
    )
