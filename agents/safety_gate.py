"""
Safety gate for Big Brain tool calling.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple


class SafetyDecision(str, Enum):
    ALLOWED = "allowed"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"


@dataclass
class SafetyRule:
    """A safety rule for a tool."""
    tool_name: str
    decision: SafetyDecision
    reason: str
    requires_human: bool = False


# Safety rules
_RULES = [
    # Read-only tools are always allowed
    SafetyRule("read_file", SafetyDecision.ALLOWED, "Read-only"),
    SafetyRule("list_directory", SafetyDecision.ALLOWED, "Read-only"),
    SafetyRule("web_search", SafetyDecision.ALLOWED, "Read-only"),
    SafetyRule("analyze_document", SafetyDecision.ALLOWED, "Read-only"),
    SafetyRule("query_database", SafetyDecision.ALLOWED, "Read-only, limited to 50 rows"),
    
    # Write tools need approval
    SafetyRule("write_file", SafetyDecision.NEEDS_APPROVAL, "Writes/modifies files", requires_human=True),
    
    # Command execution is risky
    SafetyRule("run_command", SafetyDecision.NEEDS_APPROVAL, "Executes shell commands", requires_human=True),
]


class SafetyGate:
    """Safety gate for tool execution."""
    
    def __init__(self, auto_approve_readonly: bool = True):
        self.auto_approve_readonly = auto_approve_readonly
        self._rules = {r.tool_name: r for r in _RULES}
    
    def check(self, tool_name: str, arguments: Dict) -> Tuple[bool, str, SafetyDecision]:
        """Check if a tool call is safe.
        
        Returns:
            (allowed, reason, decision)
        """
        rule = self._rules.get(tool_name)
        
        if not rule:
            return False, f"Unknown tool: {tool_name}", SafetyDecision.BLOCKED
        
        if rule.decision == SafetyDecision.ALLOWED:
            return True, rule.reason, SafetyDecision.ALLOWED
        
        if rule.decision == SafetyDecision.NEEDS_APPROVAL:
            return False, rule.reason, SafetyDecision.NEEDS_APPROVAL
        
        return False, rule.reason, SafetyDecision.BLOCKED
    
    def get_pending_approvals(self) -> list:
        """Get list of pending approval requests."""
        # TODO: integrate with approval queue
        return []
    
    def approve(self, tool_name: str, arguments: Dict) -> bool:
        """Approve a pending tool call."""
        # TODO: implement approval queue
        return False
