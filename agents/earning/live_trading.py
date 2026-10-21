"""Live portfolio and trading service with deterministic risk controls.

This module is intentionally separate from ``paper_trading``. It reads real
exchange state through the optional ccxt package and can submit real orders only
when the operator explicitly enables live trading and supplies an approved order
decision. Model output may explain or rank an order, but never overrides these
controls.
"""

from __future__ import annotations

import json
import os
import threading
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
    # ARCH-ENG-289 (G-06): the first equity observation for this exchange on
    # the current UTC day. 0.0 means "no producer configured", which keeps the
    # daily-loss breaker inert rather than guessing a baseline.
    day_start_equity_usd: float = 0.0


def default_daily_equity_path() -> str:
    """Where the durable daily-equity baseline lives.

    Mirrors the app-data convention used by the Collaboration tab: never write
    operator state into the source tree.
    """
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "MrBot1000", "live_trading_daily_equity.json")


class DailyEquityTracker:
    """Persist the first equity observation per exchange and UTC day.

    The daily-loss circuit breaker needs an opening balance, but the exchange
    adapter only exposes the *current* balance. This tracker records the first
    observation of the day and returns it for subsequent calls, so
    ``PortfolioSnapshot.day_start_equity_usd`` has a real producer.

    Best-effort by design: a missing, unreadable or unwritable state file must
    not stop a live order assessment. In that case the current equity is used
    as the baseline (loss 0.0), which is the same conservative result as a new
    day -- never a fabricated loss that would block a legitimate order.
    """

    def __init__(self, path: str):
        self.path = str(path or "")
        self._lock = threading.Lock()

    def observe(self, exchange: str, equity_usd: float,
                now: Optional[float] = None) -> float:
        equity = float(equity_usd or 0.0)
        if equity <= 0 or not self.path:
            return 0.0
        day = time.strftime("%Y-%m-%d", time.gmtime(time.time() if now is None else now))
        key = str(exchange or "configured").strip().lower() or "configured"
        with self._lock:
            state: Dict[str, Any] = {}
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    state = loaded
            except (OSError, ValueError):
                state = {}
            entry = state.get(key)
            if isinstance(entry, dict) and entry.get("day") == day:
                try:
                    opening = float(entry.get("opening_equity_usd") or 0.0)
                except (TypeError, ValueError):
                    opening = 0.0
                if opening > 0:
                    return opening
            state[key] = {"day": day, "opening_equity_usd": equity}
            try:
                parent = os.path.dirname(self.path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(state, fh, indent=2, sort_keys=True)
                os.replace(tmp, self.path)
            except OSError:
                pass
            return equity


def compute_daily_loss_pct(opening_equity_usd: float, current_equity_usd: float) -> float:
    """Return the non-negative fraction lost since the opening observation."""
    try:
        opening = float(opening_equity_usd or 0.0)
        current = float(current_equity_usd or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if opening <= 0:
        return 0.0
    return max(0.0, (opening - current) / opening)


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

    ARCH-ENG-295 (G-07): the ``_pct`` suffix was ambiguous. The units are now
    explicit and enforced at construction:

    * fractions (0..1): ``max_position_pct``, ``max_daily_loss_pct``,
      ``min_confidence``;
    * percent points (0..100): ``max_volatility_pct``, ``max_spread_pct``,
      ``min_expected_profit_pct``.

    The historical names stay for API stability, but a mis-entered value (for
    example ``max_daily_loss_pct=2.0`` meaning 2%) is rejected instead of
    silently disabling the breaker.
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

    def __post_init__(self):
        if self.max_order_usd < 0:
            raise ValueError("max_order_usd must be non-negative")
        if not 0.0 < self.max_position_pct <= 1.0:
            raise ValueError(
                "max_position_pct is a fraction (0..1), not a percent; "
                f"got {self.max_position_pct!r}")
        if not 0.0 < self.max_daily_loss_pct <= 1.0:
            raise ValueError(
                "max_daily_loss_pct is a fraction (0..1), not a percent; "
                f"got {self.max_daily_loss_pct!r}")
        if not 0.0 <= self.max_volatility_pct <= 100.0:
            raise ValueError(
                "max_volatility_pct is percent points (0..100); "
                f"got {self.max_volatility_pct!r}")
        if not 0.0 <= self.max_spread_pct <= 100.0:
            raise ValueError(
                "max_spread_pct is percent points (0..100); "
                f"got {self.max_spread_pct!r}")
        if self.min_liquidity_multiple < 0:
            raise ValueError("min_liquidity_multiple must be non-negative")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(
                "min_confidence is a fraction (0..1); "
                f"got {self.min_confidence!r}")
        if not 0.0 <= self.min_expected_profit_pct <= 100.0:
            raise ValueError(
                "min_expected_profit_pct is percent points (0..100); "
                f"got {self.min_expected_profit_pct!r}")
        if self.max_market_data_age_seconds <= 0:
            raise ValueError("max_market_data_age_seconds must be positive")


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
                 live_enabled: Optional[bool] = None,
                 daily_equity_path: Optional[str] = None,
                 daily_equity_tracker: Any = None):
        self.adapter = adapter
        self.policy = policy or TradingPolicy()
        # ARCH-ENG-289 (G-06): production passes a durable path; tests and
        # embedded callers may omit it and keep the breaker inert.
        if daily_equity_tracker is not None:
            self._daily_equity_tracker = daily_equity_tracker
        elif daily_equity_path:
            self._daily_equity_tracker = DailyEquityTracker(daily_equity_path)
        else:
            self._daily_equity_tracker = None
        # ARCH-ENG-283 (G-05/AO-02): the live gate read
        # `MRBOT_LIVE_TRADING_ENABLED`, a variable nothing sets. The documented
        # switch is `MRBOT_ENABLE_LIVE_TRADING` (and its legacy alias
        # `ENABLE_LIVE_TRADING`), which `feature_enabled` owns. Two spellings
        # of the same safety switch is how a disabled operator looks enabled.
        if live_enabled is None:
            from agents.core.feature_flags import feature_enabled
            self.live_enabled = feature_enabled("live_trading")
        else:
            self.live_enabled = bool(live_enabled)
        # Approval ids already submitted. A decided item stays APPROVED
        # forever, so the ledger — not the queue status — enforces
        # once-per-approval.
        self._executed_approval_ids: set = set()
        self._lock = threading.Lock()

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
        exchange = getattr(self.adapter, "exchange_id", "configured")
        day_start = 0.0
        if self._daily_equity_tracker is not None:
            day_start = self._daily_equity_tracker.observe(exchange, total_usd)
        return PortfolioSnapshot(
            exchange=exchange,
            total_equity_usd=total_usd,
            free_cash_usd=free_usd,
            balances=balances,
            day_start_equity_usd=day_start,
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
                     market: MarketSnapshot,
                     daily_loss_pct: Optional[float] = None) -> RiskAssessment:
        self._validate_intent(intent, market)
        # ARCH-ENG-289 (G-06): this parameter used to default to 0.0 and no
        # production caller supplied it, so the breaker could never trip. When
        # omitted, derive it from the snapshot's opening balance (which
        # sync_portfolio produces). An explicit value still wins for tests and
        # callers that have a better baseline.
        if daily_loss_pct is None:
            daily_loss_pct = compute_daily_loss_pct(
                portfolio.day_start_equity_usd, portfolio.total_equity_usd)
        daily_loss_pct = max(0.0, float(daily_loss_pct or 0.0))
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
            # ARCH-ENG-092: the market and portfolio inputs this decision was
            # made from are stored with it. `execute_order` re-derives the
            # assessment at execution time and needs the same numbers the
            # human actually reviewed — a fresh fetch could have moved, which
            # would either refuse a legitimate approval or wave through an
            # order the risk model never saw. These are also what the
            # Approvals panel shows the operator.
            "symbol": intent.symbol,
            "exchange": intent.exchange,
            "last_price": market.last_price,
            "volatility_pct": market.volatility_pct,
            "spread_pct": market.spread_pct,
            "liquidity_usd": market.liquidity_usd,
            "fetched_at": market.fetched_at,
            "total_equity_usd": portfolio.total_equity_usd,
            "free_cash_usd": portfolio.free_cash_usd,
            "balances": dict(portfolio.balances or {}),
        }, tuple(reasons))

    def execute_order(self, intent: TradeIntent, assessment: RiskAssessment,
                      approval_id: str = "") -> Dict[str, Any]:
        """Submit one live order, or refuse.

        Order of the checks matters and each has a distinct job:

        1. If an approval id is offered, verify it names THIS order. Done
           first so a swapped order reports the reason it was really refused
           ("the approved order does not match") rather than an incidental
           error from re-assessing it.
        2. Re-derive the risk verdict from LIVE exchange state. Neither the
           caller's ``decision`` nor its ``factors`` are trusted.
        3. Compare the live verdict against the assessment the human actually
           reviewed, and refuse if the market or the account moved enough to
           change the risk picture.
        4. Require a matching approval when the live verdict says one is
           needed, then consume it so one approval submits at most one order.

        Verification and consumption are deliberately separate:
        ``_require_approval_for`` only VERIFIES (and is called up to twice,
        since the verdict is re-derived between the two calls), while the
        approval is CONSUMED exactly once here, after every gate has passed.
        """
        self._require_adapter()
        if not self.live_enabled:
            raise LiveTradingError("Live trading is disabled; no order was submitted")
        if approval_id:
            self._require_approval_for(intent, approval_id)

        verdict = self._reassess(intent, approval_id)
        if verdict.decision == "blocked":
            raise LiveTradingError("Order blocked: " + "; ".join(verdict.reasons))

        # Keyed on the RE-DERIVED verdict, not the caller's: a caller who
        # claimed "preapproved" for an order the risk model still flags must
        # still produce a matching approval, and with no id that fails closed.
        if verdict.decision == "needs_approval":
            self._require_approval_for(intent, approval_id)

        # Every gate has passed. Consume the approval so this id cannot submit
        # a second order. The item stays APPROVED forever, so without this a
        # re-delivered decision — a duplicated Qt signal, a caller retry loop,
        # a second operator click — replays the same live order against real
        # funds. Keyed on the queue item id so a second, distinct approval
        # still runs.
        if approval_id:
            with self._lock:
                if approval_id in self._executed_approval_ids:
                    raise LiveTradingError(
                        f"Approval {approval_id} has already been executed; "
                        f"one human approval submits at most one live order")
                self._executed_approval_ids.add(approval_id)

        order = self.adapter.create_order(
            intent.symbol, intent.order_type, intent.side, intent.quantity,
            intent.limit_price or None,
        )
        return {"ok": True, "execution_mode": "live", "client_order_id": uuid.uuid4().hex,
                "order": order}

    def _reassess(self, intent: TradeIntent,
                  approval_id: str = "") -> RiskAssessment:
        """Re-derive the risk verdict from LIVE exchange state.

        Neither the caller's ``decision`` nor its ``factors`` are trusted. The
        portfolio and market data are re-fetched from the adapter, so the
        verdict is computed from what the account and the market actually are
        at submission time.

        Trusting the caller's factors was a real defect: a forged
        ``RiskAssessment("preapproved", 0.0, {"last_price": 0.000001,
        "liquidity_usd": 1e12, "total_equity_usd": 1e12, ...})`` makes a
        999999-unit order a $1.00 notional, every policy gate passes, and the
        order reaches the exchange with no approval item at all. Fixing the
        forgery target from ``decision`` to ``factors`` without removing it
        would have been no fix at all.
        """
        try:
            portfolio = self.sync_portfolio()
            market = self.fetch_market_snapshot(intent.symbol)
        except LiveTradingError as exc:
            # Live state cannot be read, so the order cannot be shown to be
            # within policy. Fail closed rather than act on the caller's claim.
            return RiskAssessment("blocked", 1.0, {}, (
                f"live account state could not be read at execution time "
                f"({exc}); no order was submitted",))
        verdict = self.assess_order(intent, portfolio, market)
        # Compare the LIVE verdict against what the operator was shown, so an
        # approval cannot be replayed against a market that has moved.
        self._check_still_matches_what_was_approved(verdict, approval_id)
        return verdict

    def _check_still_matches_what_was_approved(self, verdict: RiskAssessment,
                                               approval_id: str) -> None:
        """Refuse when live conditions no longer match the approved assessment.

        An approval authorizes a specific order against a specific market and
        account. If the market or the balance moved enough to change the risk
        picture, the human's decision no longer covers what would be
        submitted, so the order must be re-assessed and re-approved rather
        than waved through on a stale approval.
        """
        if not approval_id:
            return
        from agents.safety.approval import HumanApprovalQueue
        item = HumanApprovalQueue.instance().find_by_id(approval_id)
        if item is None:
            return
        shown = ((item.details or {}).get("assessment") or {})
        if not isinstance(shown, dict) or not shown:
            # No recorded assessment to compare against (e.g. an item enqueued
            # by hand): the live re-derivation above is the only gate, and it
            # already ran against real state.
            return
        for key in ("notional_usd", "position_pct", "liquidity_multiple",
                    "last_price", "total_equity_usd", "free_cash_usd"):
            if key not in shown or key not in verdict.factors:
                continue
            try:
                before = float(shown[key])
                after = float(verdict.factors[key])
            except (TypeError, ValueError):
                continue
            if before == after:
                continue
            # Relative tolerance: a 1% move in any risk input invalidates the
            # approval. Absolute tolerances are meaningless across symbols
            # quoted from $0.000001 to $100000.
            if abs(after - before) > max(abs(before), abs(after), 1.0) * 0.01:
                raise LiveTradingError(
                    f"The approved risk assessment no longer holds: {key} was "
                    f"{before:g} when approved and is {after:g} now. "
                    f"Re-assess and re-approve the order.")

    def _require_approval_for(self, intent: TradeIntent,
                              approval_id: str) -> None:
        """Fail closed unless a live APPROVED queue item names THIS order.

        Every check here is derived from the queue's own record, never from a
        caller-supplied argument: the payload is what the Approvals panel
        rendered for the human, so it is the only thing that can establish
        what was actually authorized.
        """
        if not approval_id:
            raise LiveTradingError("Human approval is required before live execution")
        from agents.safety.approval import ApprovalStatus, HumanApprovalQueue
        item = HumanApprovalQueue.instance().find_by_id(approval_id)
        if item is None:
            raise LiveTradingError(
                "Approved order not found in the human approval queue; "
                "no order was submitted")
        if item.status != ApprovalStatus.APPROVED:
            raise LiveTradingError("Human approval is required before live execution")

        approved = (item.payload or {}).get("intent")
        if not isinstance(approved, dict):
            raise LiveTradingError(
                "Approval item does not name the order it authorized; "
                "no order was submitted")
        if self._intent_differs(intent, approved):
            raise LiveTradingError(
                "The approved order does not match the order being executed "
                f"(approved {self._describe(approved)}, requested "
                f"{self._describe(intent.__dict__)}); no order was submitted")
        # One approval authorizes one order. The item stays APPROVED forever,
        # so without a ledger a re-delivered decision replays the same live
        # order N times against real funds. The consume itself lives in
        # execute_order so it runs exactly once, after every gate passes.
        return

    @staticmethod
    def _describe(d: Dict[str, Any]) -> str:
        return (f"{d.get('side', '?')} {d.get('quantity', '?')} "
                f"{d.get('symbol', '?')}")

    @staticmethod
    def _intent_differs(intent: TradeIntent, approved: Dict[str, Any]) -> bool:
        """Compare every field that changes what the exchange would receive.

        Only the order-shaping fields are compared. ``reasoning`` and the
        scoring hints (``expected_profit_pct``/``strategy_confidence``) are
        advisory: they inform the risk decision, not the order itself, so a
        refreshed estimate must not invalidate a legitimate approval.
        """
        for key in ("exchange", "symbol", "side", "quantity", "order_type",
                    "limit_price", "asset_class"):
            if key not in approved:
                # An approval payload that omits an order-shaping field cannot
                # be shown to authorize this order, so it authorizes nothing.
                return True
            want = getattr(intent, key)
            got = approved[key]
            try:
                want_n = float(want)
                got_n = float(got)
            except (TypeError, ValueError):
                # Non-numeric fields compare case-insensitively, so an approval
                # recorded as "BTC/USD" authorizes an order written as
                # "btc/usd". Every string field is treated the same way.
                if str(want).strip().lower() != str(got).strip().lower():
                    return True
                continue
            # RELATIVE tolerance: an absolute epsilon is meaningless across
            # instruments quoted from $0.000001 to $100000, where the same
            # absolute difference is noise on one and a different order on
            # another. A quantity or price must match to a part in 1e9.
            if abs(want_n - got_n) > max(abs(want_n), abs(got_n), 1e-12) * 1e-9:
                return True
        return False

    def propose_order(self, intent: TradeIntent, assessment: RiskAssessment) -> Dict[str, Any]:
        """Create an approval item for an order that cannot be preapproved."""
        if assessment.decision == "blocked":
            return {"ok": False, "status": "blocked", "reasons": assessment.reasons}
        if assessment.decision == "preapproved":
            return {"ok": True, "status": "preapproved", "assessment": assessment}
        from agents.safety.approval import ApprovalKind, ApprovalItem, HumanApprovalQueue
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
            from agents.safety.approval import ApprovalStatus, HumanApprovalQueue
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
