"""Authorized tool dispatch boundary.

Handler implementations remain in ``agents.tool_calling`` during migration;
this module owns the single authorization and routing entry point.
"""

from __future__ import annotations

from typing import Any, Dict


def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """Authorize and dispatch one tool without bypassing safety policy."""
    from agents.safety import calling as runtime
    if not runtime.is_known_tool(name):
        return f"[Unknown tool: {name}]"

    authorization = runtime._get_action_dispatcher().authorize(name, arguments)
    if authorization.decision == runtime.SafetyDecision.BLOCKED:
        return f"[BLOCKED] {authorization.reason}"

    if authorization.decision == runtime.SafetyDecision.NEEDS_APPROVAL:
        try:
            from agents.safety.approval import (
                ApprovalItem,
                ApprovalKind,
                HumanApprovalQueue,
            )
            approval = HumanApprovalQueue.instance().enqueue(ApprovalItem(
                kind=ApprovalKind.ACTION,
                title=f"Chat tool request: {name}",
                description=(
                    f"The chat requested {name}. Review the arguments before "
                    "allowing any machine change or external action."
                ),
                requested_by="dialogue",
                details={"tool": name, "arguments": arguments},
                payload={"tool": name, "arguments": arguments},
            ))
            return (
                f"[PENDING APPROVAL] request_id={approval.id}; {name} was not "
                "executed. Tell the human that this request is awaiting review."
            )
        except Exception as exc:
            return f"[Approval unavailable: {name} was not executed: {exc}]"

    handlers = {
        "web_search": runtime._tool_web_search,
        "web_read": runtime._tool_web_read,
        "web_check": runtime._tool_web_check,
        "workshop_list": runtime._tool_workshop_list,
        "workshop_read": runtime._tool_workshop_read,
        "workshop_write": runtime._tool_workshop_write,
        "workshop_mkdir": runtime._tool_workshop_mkdir,
        "workshop_storage": runtime._tool_workshop_storage,
        "workshop_search": runtime._tool_workshop_search,
        "workshop_proposal": runtime._tool_workshop_proposal,
        "workshop_account": runtime._tool_workshop_account,
        "workshop_payment": runtime._tool_workshop_payment,
        "file_read": runtime._tool_file_read,
        "file_write": runtime._tool_file_write,
        "file_list": runtime._tool_file_list,
        "run_command": runtime._tool_run_command,
        "query_db": runtime._tool_query_db,
    }
    handler = handlers.get(name)
    if handler is None:
        return f"[Unknown tool: {name}]"
    try:
        return handler(arguments)
    except Exception as exc:
        return f"[Tool error: {exc}]"


__all__ = ["execute_tool"]
