"""Handle EVALUATE/APPROVE/REJECT commands from dialogue.

When Edward or Jacob say things like:
- "EVALUATE 3" — deep-dive into opportunity #3
- "APPROVE 5" — queue opportunity #5 for action
- "REJECT 2" — scam-mark opportunity #2
- "REJECT 2, 5, 8" — scam-mark multiple

This module parses those commands and updates the portfolio + blacklist.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple


def parse_opportunity_command(text: str) -> Tuple[str, List[int]]:
    """Parse EVALUATE/APPROVE/REJECT commands from dialogue text.
    
    Returns:
        Tuple of (command, list_of_indices)
        e.g. ("evaluate", [3]) or ("reject", [2, 5, 8])
    """
    if not text:
        return ("", [])
    
    text_lower = text.lower().strip()
    
    # Match patterns: "evaluate 3", "approve 5", "reject 2, 5, 8"
    patterns = [
        r"(?:evaluate|eval|deep[- ]?dive|investigate)\s*#?(\d+)",
        r"(?:approve|accept|queue|proceed)\s*#?(\d+)",
        r"(?:reject|block|scam|blacklist|skip)\s*#?(\d+)",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            # Extract all numbers (for multi-reject: "reject 2, 5, 8")
            numbers = re.findall(r"\d+", text[match.start():])
            indices = [int(n) for n in numbers]
            
            if "eval" in pattern:
                return ("evaluate", indices)
            elif "approve" in pattern or "accept" in pattern or "queue" in pattern:
                return ("approve", indices)
            else:
                return ("reject", indices)
    
    return ("", [])


def handle_opportunity_command(
    text: str,
    speaker: str,
    portfolio,
    opportunity_list: List[dict],
) -> Optional[str]:
    """Handle an EVALUATE/APPROVE/REJECT command.
    
    Args:
        text: The dialogue text
        speaker: "Edward Hurst" or "Jacob Stanley"
        portfolio: OpportunityPortfolio instance
        opportunity_list: List of available opportunities (from build_opportunity_context)
    
    Returns:
        Response string if command was handled, None if not a command.
    """
    from agents.opportunity_dialogue_bridge import (
        blacklist_opportunity,
        record_dialogue_opinion,
        is_blacklisted,
        build_opportunity_summary,
    )
    
    command, indices = parse_opportunity_command(text)
    
    if not command or not indices:
        return None
    
    responses = []
    
    for idx in indices:
        if idx < 1 or idx > len(opportunity_list):
            responses.append(f"Opportunity #{idx} not found (only {len(opportunity_list)} available).")
            continue
        
        opp = opportunity_list[idx - 1]
        opp_id = opp.get("opportunity_id", "")
        title = opp.get("title", opp_id)
        
        if command == "evaluate":
            # Record opinion
            record_dialogue_opinion(opp_id, speaker, "evaluating", f"Deep-dive requested: {text[:100]}")
            # Build detailed summary
            summary = build_opportunity_summary(portfolio, opp_id)
            if summary:
                responses.append(summary)
            else:
                responses.append(f"Could not find details for opportunity #{idx}.")
        
        elif command == "approve":
            # Record opinion
            record_dialogue_opinion(opp_id, speaker, "approved", f"Approved for action: {text[:100]}")
            # Update portfolio status
            try:
                from agents.opportunity_portfolio import WorkStatus
                portfolio.transition_work_status(opp_id, WorkStatus.QUALIFIED)
                responses.append(f"✅ APPROVED: {title} → QUALIFIED")
            except Exception as e:
                responses.append(f"Could not approve {title}: {e}")
        
        elif command == "reject":
            # Determine if scam or just not interested
            text_lower = text.lower()
            is_scam = any(word in text_lower for word in ["scam", "fake", "fraud", "phishing", "suspicious"])
            reason = "Scam/suspicious" if is_scam else "Not a good fit"
            
            # Blacklist
            blacklist_opportunity(opp_id, title, reason, speaker)
            
            # Record opinion
            record_dialogue_opinion(opp_id, speaker, "rejected", reason)
            
            # Update portfolio
            try:
                from agents.opportunity_portfolio import WorkStatus
                portfolio.transition_work_status(opp_id, WorkStatus.REJECTED)
                responses.append(f"🚫 REJECTED: {title} ({reason}) — blacklisted")
            except Exception as e:
                responses.append(f"Could not reject {title}: {e}")
    
    return "\n\n".join(responses) if responses else None


def extract_opinion_from_text(text: str, speaker: str) -> Optional[Tuple[str, str, str]]:
    """Extract opportunity opinion from natural language dialogue.
    
    When Edward/Jacob say things like:
    - "Robinhood Chain looks like a scam"
    - "I think the Upwork gig is worth pursuing"
    - "That Fiverr job seems too complex"
    
    Returns:
        Tuple of (opportunity_id, verdict, reason) or None
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # Scam indicators
    scam_words = ["scam", "fake", "fraud", "phishing", "suspicious", "too good to be true"]
    # Approval indicators
    approve_words = ["worth", "pursue", "try", "attempt", "go for", "approve", "qualified"]
    # Complexity indicators
    complex_words = ["complex", "complicated", "difficult", "hard", "too much"]
    
    # Try to match to known opportunities
    # This requires the opportunity list to be in context
    # For now, return None (the explicit EVALUATE/APPROVE/REJECT commands handle this)
    return None
