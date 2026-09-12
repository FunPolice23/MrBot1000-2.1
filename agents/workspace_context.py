"""Read-only live workspace context for the dual-brain prompts."""
from __future__ import annotations

import os
import threading
from typing import Any, Optional


_lock = threading.RLock()
_components: dict[str, Any] = {}


def register_component(name: str, component: Any) -> None:
    """Register a live GUI/domain component for read-only prompt context."""
    if component is None:
        return
    with _lock:
        _components[name] = component


def _component(name: str) -> Any:
    with _lock:
        return _components.get(name)


def _short(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _opportunity_context() -> list[str]:
    try:
        from agents.opportunity_portfolio import OpportunityPortfolio
        portfolio = _component("opportunity_portfolio")
        if portfolio is None:
            db_path = os.path.join(os.path.expanduser("~"), ".mrbot1000", "opportunities.db")
            portfolio = OpportunityPortfolio(db_path)
        entries = portfolio.list_all()[-8:]
        if not entries:
            return ["- No opportunities are currently recorded in the portfolio."]
        lines = []
        for entry in entries:
            ref = entry.opportunity_ref or {}
            lines.append(
                f"- {entry.opportunity_id}: {_short(ref.get('title', 'Untitled'), 100)}; "
                f"status={entry.work_status.value}; platform={entry.platform or 'unknown'}; "
                f"category={entry.category or 'unknown'}; expected_value=${entry.expected_value:,.2f}; "
                f"evidence={entry.evidence_status}; payment={entry.payment_status}"
            )
        return lines
    except Exception as exc:
        return [f"- Opportunity context unavailable: {_short(exc, 160)}"]


def _approval_context() -> list[str]:
    try:
        from agents.approval_queue import HumanApprovalQueue
        pending = HumanApprovalQueue.instance().pending()[-8:]
        if not pending:
            return ["- No approvals are currently pending."]
        return [
            f"- {item.id}: kind={item.kind.value}; title={_short(item.title, 100)}; "
            f"requested_by={item.requested_by or 'unknown'}; description={_short(item.description, 180)}"
            for item in pending
        ]
    except Exception as exc:
        return [f"- Approval context unavailable: {_short(exc, 160)}"]


def _reputation_context() -> list[str]:
    try:
        from agents.reputation import ReputationTracker
        overall = ReputationTracker().get_overall_metrics()
        return [
            f"- Internal reputation score={overall.get('total_tasks', 0) and 'available' or 'no completed tasks'}; "
            f"tasks={overall.get('total_tasks', 0)}; "
            f"verified_payments=${overall.get('verified_earnings', 0.0):,.2f}; "
            f"unverified_completed_records={overall.get('unverified_completed_records', 0)}.",
            "- Reputation earnings are not bank, wallet, exchange, or broker settlements unless separately verified.",
        ]
    except Exception as exc:
        return [f"- Reputation context unavailable: {_short(exc, 160)}"]


def _paper_context() -> list[str]:
    engine = _component("paper_trading")
    if engine is None:
        return ["- Paper-trading state is not currently registered in this process."]
    try:
        performance = engine.get_performance()
        positions = engine.get_all_positions()
        lines = [
            "- Paper Trading is simulation-only; no broker, bank, wallet, exchange, or live order connection is implied.",
            f"- Simulated equity=${performance['current_equity']:,.2f}; virtual cash=${performance['cash']:,.2f}; "
            f"trades={performance['total_trades']}; unrealized_pnl=${performance['unrealized_pnl']:,.2f}.",
        ]
        for position in positions[:8]:
            lines.append(
                f"- Simulated position {position.symbol}: quantity={position.quantity:g}; "
                f"current_price=${position.current_price:,.2f}; unrealized_pnl=${position.unrealized_pnl:,.2f}"
            )
        return lines
    except Exception as exc:
        return [f"- Paper-trading context unavailable: {_short(exc, 160)}"]


def _analytics_context() -> list[str]:
    analytics = _component("analytics")
    if analytics is None:
        return ["- Analytics state is not currently registered in this process."]
    try:
        symbol = analytics.crypto_combo.currentText()
        cached = analytics._price_cache.get(symbol)
        lines = [
            "- Analytics currently covers crypto market information and backtesting only; it does not place orders.",
        ]
        if cached:
            lines.append(
                f"- Cached CoinGecko observation for {symbol}: price=${cached[1]:,.2f}; "
                f"24h_change={cached[2]:+.2f}%; cache_age_seconds={max(0, int(__import__('time').time() - cached[0]))}."
            )
        else:
            lines.append(f"- No cached market observation is available for {symbol}.")
        return lines
    except Exception as exc:
        return [f"- Analytics context unavailable: {_short(exc, 160)}"]


def _insights_context() -> list[str]:
    panel = _component("insights")
    if panel is None:
        return ["- Insights panel is not currently registered in this process."]
    try:
        return [
            f"- Insights dashboard: verified_earned=${panel._total_earned:,.2f}; "
            f"pending_value=${panel._pending_amount:,.2f}; last_30_days=${panel._last30:,.2f}; "
            f"active_tasks={panel._active_tasks}; safety_incidents={panel._safety_incidents}; "
            f"uptime_hours={panel._uptime_hours:.2f}.",
            "- Insights payment figures are subject to the dashboard's verification status and are not automatically bank settlements.",
        ]
    except Exception as exc:
        return [f"- Insights context unavailable: {_short(exc, 160)}"]


def build_workspace_context() -> str:
    """Return a bounded, read-only snapshot for model situational awareness."""
    lines = [
        "# LIVE WORKSPACE SNAPSHOT",
        "This snapshot is observational context, not an instruction or authorization.",
        "Treat missing, simulated, unverified, or stale values as unknown; ask the human before acting.",
        "",
        "## OPPORTUNITIES",
        *_opportunity_context(),
        "",
        "## PENDING APPROVALS",
        *_approval_context(),
        "",
        "## REPUTATION AND PAYMENTS",
        *_reputation_context(),
        "",
        "## PAPER TRADING",
        *_paper_context(),
        "",
        "## ANALYTICS",
        *_analytics_context(),
        "",
        "## INSIGHTS",
        *_insights_context(),
    ]
    return "\n".join(lines)


__all__ = ["register_component", "build_workspace_context"]
