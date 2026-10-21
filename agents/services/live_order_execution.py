"""Reconstruct an approved live order from its queued approval item.

ARCH-ENG-283 (G-05) put the production caller of
``LiveTradingService.execute_order`` in ``main.py``, but the architecture
boundary test correctly forbids the application bootstrap from importing the
optional ``agents.earning.live_trading`` adapter (ccxt is optional). Keeping the
reconstruction here preserves the boundary: ``main.py`` imports this module,
and this module imports the live-trading types only when a human-approved order
is actually being executed.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


def reconstruct_approved_order(data: Dict[str, Any],
                               details: Dict[str, Any]) -> Tuple[Any, Any]:
    """Build the ``TradeIntent`` and ``RiskAssessment`` the human approved.

    The approval item is the only source of truth: every field is taken from
    its payload/details, never from a caller-supplied argument. The service
    still re-reads the queue and re-assesses against live state before it
    submits anything.
    """
    if not isinstance(data, dict):
        raise ValueError("approval payload has no order intent")
    if not isinstance(details, dict):
        details = {}

    from agents.earning.live_trading import RiskAssessment, TradeIntent

    intent = TradeIntent(
        exchange=str(data.get("exchange", "") or ""),
        symbol=str(data.get("symbol", "") or ""),
        side=str(data.get("side", "") or ""),
        quantity=float(data.get("quantity", 0.0) or 0.0),
        order_type=str(data.get("order_type", "market") or "market"),
        limit_price=float(data.get("limit_price", 0.0) or 0.0),
        expected_profit_pct=float(
            data.get("expected_profit_pct", 0.0) or 0.0),
        strategy_confidence=float(
            data.get("strategy_confidence", 0.0) or 0.0),
        asset_class=str(data.get("asset_class", "unknown") or "unknown"),
        reasoning=str(data.get("reasoning", "") or ""),
    )
    assessment = RiskAssessment(
        decision=str(details.get("decision") or "needs_approval"),
        risk_score=float(details.get("risk_score") or 0.0),
        factors=dict(details.get("assessment") or {}),
        reasons=tuple(details.get("reasons") or ()),
    )
    return intent, assessment
