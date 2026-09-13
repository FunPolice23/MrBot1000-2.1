"""Bridge between Opportunities portfolio and Dialogue.

Gives Edward and Jacob real-time access to the opportunity portfolio so they can:
- See all opportunities (not just one)
- Evaluate, compare, and choose which to pursue
- Reject/scam-mark opportunities (persistent blacklist)
- Reflect their dialogue decisions back to the portfolio

This replaces the old single-goal dialogue with portfolio-aware evaluation.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Set


# ── Blacklist (persistent scam/reject filter) ────────────────────────────────
# Opportunities the personas reject get written here so they're never shown again.

_BLACKLIST_DB: Optional[sqlite3.Connection] = None
_BLACKLIST_LOCK = threading.Lock()


def _get_blacklist_db() -> sqlite3.Connection:
    global _BLACKLIST_DB
    if _BLACKLIST_DB is not None:
        return _BLACKLIST_DB
    with _BLACKLIST_LOCK:
        if _BLACKLIST_DB is not None:
            return _BLACKLIST_DB
        db_path = os.path.join(
            os.path.expanduser("~"), ".mrbot1000", "opportunity_blacklist.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                opportunity_id TEXT PRIMARY KEY,
                title TEXT,
                reason TEXT,
                rejected_by TEXT,
                ts REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dialogue_opinion (
                opportunity_id TEXT PRIMARY KEY,
                persona TEXT NOT NULL,
                verdict TEXT NOT NULL,
                reason TEXT,
                ts REAL NOT NULL
            )
        """)
        conn.commit()
        _BLACKLIST_DB = conn
        return _BLACKLIST_DB


def is_blacklisted(opportunity_id: str) -> bool:
    """Check if an opportunity has been blacklisted."""
    try:
        db = _get_blacklist_db()
        row = db.execute(
            "SELECT 1 FROM blacklist WHERE opportunity_id = ?",
            (opportunity_id,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def blacklist_opportunity(
    opportunity_id: str,
    title: str = "",
    reason: str = "",
    rejected_by: str = "",
) -> None:
    """Add an opportunity to the blacklist."""
    try:
        db = _get_blacklist_db()
        db.execute(
            "INSERT OR REPLACE INTO blacklist (opportunity_id, title, reason, rejected_by, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (opportunity_id, title, reason, rejected_by, time.time()),
        )
        db.commit()
    except Exception:
        pass


def get_blacklist() -> List[Dict[str, Any]]:
    """Get all blacklisted opportunities."""
    try:
        db = _get_blacklist_db()
        rows = db.execute(
            "SELECT opportunity_id, title, reason, rejected_by, ts FROM blacklist ORDER BY ts DESC"
        ).fetchall()
        return [
            {
                "opportunity_id": row[0],
                "title": row[1],
                "reason": row[2],
                "rejected_by": row[3],
                "ts": row[4],
            }
            for row in rows
        ]
    except Exception:
        return []


def record_dialogue_opinion(
    opportunity_id: str,
    persona: str,
    verdict: str,
    reason: str = "",
) -> None:
    """Record a persona's opinion of an opportunity during dialogue."""
    try:
        db = _get_blacklist_db()
        db.execute(
            "INSERT OR REPLACE INTO dialogue_opinion (opportunity_id, persona, verdict, reason, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (opportunity_id, persona, verdict, reason, time.time()),
        )
        db.commit()
    except Exception:
        pass


def get_dialogue_opinions(opportunity_id: str) -> List[Dict[str, Any]]:
    """Get all dialogue opinions for an opportunity."""
    try:
        db = _get_blacklist_db()
        rows = db.execute(
            "SELECT persona, verdict, reason, ts FROM dialogue_opinion "
            "WHERE opportunity_id = ? ORDER BY ts DESC",
            (opportunity_id,),
        ).fetchall()
        return [
            {"persona": row[0], "verdict": row[1], "reason": row[2], "ts": row[3]}
            for row in rows
        ]
    except Exception:
        return []


# ── Portfolio Context Builder ─────────────────────────────────────────────────
# Builds the context string that tells the personas about available opportunities.

def build_opportunity_context(
    portfolio,
    max_entries: int = 20,
    status_filter: Optional[Set[str]] = None,
    min_score: float = 0.0,
    source_filter: Optional[str] = None,
) -> str:
    """Build a context string describing available opportunities for dialogue.
    
    Args:
        portfolio: OpportunityPortfolio instance
        max_entries: Max opportunities to include
        status_filter: Only include these statuses (e.g. {"EVALUATING", "QUALIFIED"})
        min_score: Minimum policy score (0-1)
        source_filter: Only include this source (e.g. "upwork")
    
    Returns:
        Formatted string for injection into dialogue context.
    """
    try:
        all_entries = portfolio.list_all()
    except Exception:
        return ""
    
    # Filter
    filtered = []
    for entry in all_entries:
        # Skip blacklisted
        if is_blacklisted(entry.opportunity_id):
            continue
        # Skip terminal states unless explicitly requested
        if status_filter:
            if entry.work_status.value not in status_filter:
                continue
        else:
            # Default: skip terminal/rejected
            if entry.work_status.value in {"PAID", "FAILED", "REJECTED", "EXPIRED", "ABANDONED"}:
                continue
        if entry.policy_score < min_score:
            continue
        if source_filter and entry.platform.lower() != source_filter.lower():
            continue
        filtered.append(entry)
    
    # Sort by score (descending), then by expected value
    filtered.sort(key=lambda e: (-e.policy_score, -e.expected_value))
    filtered = filtered[:max_entries]
    
    if not filtered:
        return ""
    
    lines = ["# AVAILABLE OPPORTUNITIES"]
    for i, entry in enumerate(filtered, 1):
        ref = entry.opportunity_ref or {}
        title = ref.get("title", entry.opportunity_id)
        platform = entry.platform or ref.get("source", "unknown")
        budget = entry.expected_value
        score = entry.policy_score
        status = entry.work_status.value
        opp_id = entry.opportunity_id
        
        # Get dialogue opinions for this opportunity
        opinions = get_dialogue_opinions(opp_id)
        opinion_str = ""
        if opinions:
            parts = [f"{o['persona']}: {o['verdict']}" for o in opinions]
            opinion_str = f" | Opinions: {', '.join(parts)}"
        
        lines.append(
            f"{i}. [{status}] {title} | Platform: {platform} | "
            f"Value: ${budget:,.2f} | Score: {score*100:.0f}% | "
            f"Risk: {entry.risk_level if hasattr(entry, 'risk_level') else 'unknown'}"
            f"{opinion_str} | ID: {opp_id}"
        )
    
    lines.append(f"\nTotal available: {len(filtered)} opportunities")
    lines.append("You can evaluate, compare, and choose which to pursue.")
    lines.append("Say 'EVALUATE <number>' to deep-dive, 'REJECT <number>' to scam-mark,")
    lines.append("or 'APPROVE <number>' to queue for action.")
    
    return "\n".join(lines)


def build_opportunity_summary(portfolio, opportunity_id: str) -> str:
    """Build a detailed summary of a single opportunity."""
    try:
        entry = portfolio.get(opportunity_id)
    except Exception:
        return ""
    
    if not entry:
        return ""
    
    ref = entry.opportunity_ref or {}
    title = ref.get("title", opportunity_id)
    description = ref.get("description", "No description available")
    url = ref.get("url", ref.get("source_url", ""))
    platform = entry.platform or ref.get("source", "unknown")
    
    lines = [
        f"# OPPORTUNITY DETAIL: {title}",
        f"ID: {opportunity_id}",
        f"Platform: {platform}",
        f"Category: {entry.category or ref.get('category', 'unknown')}",
        f"Status: {entry.work_status.value}",
        f"Expected Value: ${entry.expected_value:,.2f}",
        f"Policy Score: {entry.policy_score*100:.0f}%",
        f"URL: {url}",
        "",
        "## Description",
        description[:2000],  # Truncate long descriptions
    ]
    
    # Add dialogue opinions
    opinions = get_dialogue_opinions(opportunity_id)
    if opinions:
        lines.append("\n## Dialogue Opinions")
        for o in opinions:
            lines.append(f"- {o['persona']}: {o['verdict']} — {o['reason']}")
    
    return "\n".join(lines)
