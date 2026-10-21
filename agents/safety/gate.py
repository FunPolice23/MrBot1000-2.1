"""
Safety gate for tool calling.

This module is the single source of truth for which tool names may run without
human approval. The classifications below MUST stay aligned with the dispatch
registry in ``agents/tool_calling.py``; that alignment is enforced by
``tests/test_safety_gate_registry_alignment.py``. A previous version of this
table named tools that do not exist (``read_file``, ``list_directory``,
``query_database``, ``write_file``), which silently turned every real read tool
into an "Unknown tool" block and left the SQL validation branch unreachable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, Tuple


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


# Tools that mutate the machine or create an external commitment. A human must
# approve these before they run. ``tool_calling._MUTATING_TOOLS`` is derived from
# this set so the two can never drift apart.
MUTATING_TOOL_NAMES: FrozenSet[str] = frozenset({
    "file_write",
    "workshop_write",
    "workshop_mkdir",
    "workshop_proposal",
    "workshop_account",
    "workshop_payment",
    # ARCH-ENG-248 (AY-01): typing a workshop document into existence is a
    # state change (and `workshop_account_remove` destroys a record), so these
    # keep the human in the loop exactly like the older typed writers.
    "workshop_proposal_status",
    "workshop_research",
    "workshop_script",
    "workshop_application",
    "workshop_account_remove",
    "workshop_deliverable",
    "workshop_note",
    "run_command",
    "record_payment",
    "social_post",
    # ARCH-ENG-227: proposes a change to this program's own source. Classified
    # MUTATING even though it does not itself write the target -- it creates a
    # durable, human-reviewed artifact aimed at the codebase. READONLY would
    # let the SafetyGate ALLOW it with no human in the loop (gate.py:122-128),
    # which is precisely the wrong default for this.
    "propose_code_patch",
})

# Read-only tools: no machine mutation and no external commitment.
READONLY_TOOL_NAMES: FrozenSet[str] = frozenset({
    "web_search",
    "web_read",
    "web_check",
    "workshop_list",
    "workshop_read",
    "workshop_storage",
    "workshop_search",
    # ARCH-ENG-248 (AY-01): the typed READ half. No mutation, no external
    # commitment -- `workshop_account_get`/`_list` mask passwords, so they are
    # safe to auto-approve even though the underlying store is a secret file.
    "workshop_proposal_list",
    "workshop_proposal_get",
    "workshop_research_read",
    "workshop_research_list",
    "workshop_script_read",
    "workshop_script_list",
    "workshop_application_list",
    "workshop_account_get",
    "workshop_account_list",
    "workshop_payment_get",
    "workshop_payment_list",
    "workshop_deliverable_list",
    "workshop_note_list",
    "file_read",
    "file_list",
    "query_db",
})

# Historical names that older prompts, personas, and tests still emit. Each one
# resolves to the decision of the real tool it names; the real registry names
# above are what execute_tool() dispatches on.
_ALIASES: Dict[str, str] = {
    "read_file": "file_read",
    "list_directory": "file_list",
    "write_file": "file_write",
    "query_database": "query_db",
}

# Tools whose arguments carry SQL that must be validated as read-only.
_SQL_TOOL_NAMES: FrozenSet[str] = frozenset({"query_db", "query_database"})

_RULES = tuple(
    [SafetyRule(name, SafetyDecision.ALLOWED, "Read-only")
     for name in sorted(READONLY_TOOL_NAMES)]
    + [SafetyRule(name, SafetyDecision.NEEDS_APPROVAL,
                  "Executes a state-changing action", requires_human=True)
       for name in sorted(MUTATING_TOOL_NAMES)]
    + [SafetyRule(alias, SafetyDecision.BLOCKED, f"Alias for {target}")
       for alias, target in sorted(_ALIASES.items())]
)


def canonical_tool_name(tool_name: str) -> str:
    """Return the real registry name for a tool or one of its aliases."""
    return _ALIASES.get(tool_name, tool_name)


def is_known_tool(tool_name: str) -> bool:
    """True if the name (or a documented alias) resolves to a classified tool."""
    canonical = canonical_tool_name(tool_name)
    return canonical in READONLY_TOOL_NAMES or canonical in MUTATING_TOOL_NAMES


class SafetyGate:
    """Safety gate for tool execution."""

    def __init__(self, auto_approve_readonly: bool = True):
        self.auto_approve_readonly = auto_approve_readonly
        self._rules = {r.tool_name: r for r in _RULES}

    def check(self, tool_name: str, arguments: Dict) -> Tuple[bool, str, SafetyDecision]:
        """Check whether a tool call may run.

        Returns:
            (allowed, reason, decision)
        """
        canonical = canonical_tool_name(tool_name)

        if canonical in _SQL_TOOL_NAMES:
            try:
                from agents.safety.sql import validate_readonly_sql
                from agents.safety.policy import resolve_project_path
                validate_readonly_sql(
                    arguments.get("sql", ""), resolve_project_path("agent.db"))
            except (OSError, TypeError, ValueError, KeyError) as exc:
                return False, f"Unsafe SQL blocked: {exc}", SafetyDecision.BLOCKED

        if canonical in READONLY_TOOL_NAMES:
            if not self.auto_approve_readonly:
                return (False,
                        "Read-only tool requires approval "
                        "(auto_approve_readonly disabled)",
                        SafetyDecision.NEEDS_APPROVAL)
            return True, f"Read-only ({canonical})", SafetyDecision.ALLOWED

        if canonical in MUTATING_TOOL_NAMES:
            return (False, f"{canonical} changes machine or external state",
                    SafetyDecision.NEEDS_APPROVAL)

        return False, f"Unknown tool: {tool_name}", SafetyDecision.BLOCKED

    def get_pending_approvals(self) -> list:
        """Get list of pending approval requests.

        Delegates to the shared HumanApprovalQueue; returns [] if unavailable so
        callers never crash on a missing queue.
        """
        try:
            from agents.safety.approval import HumanApprovalQueue
            return list(HumanApprovalQueue.instance().pending())
        except Exception:
            return []

    def approve(self, tool_name: str, arguments: Dict) -> bool:
        """Approve the pending request that matches this tool call, if any.

        The gate does not hold approvals: it locates the matching queued item and
        delegates the decision to HumanApprovalQueue, which is the only component
        permitted to record a human approval.
        """
        from agents.safety.approval import HumanApprovalQueue
        queue = HumanApprovalQueue.instance()
        for item in queue.pending():
            details = getattr(item, "details", None) or {}
            if (details.get("tool") == tool_name
                    and details.get("arguments") == arguments):
                return queue.approve(item.id)
        return False
