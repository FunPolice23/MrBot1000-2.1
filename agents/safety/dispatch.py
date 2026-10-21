"""Authorized tool dispatch boundary.

Handler implementations remain in ``agents.tool_calling`` during migration;
this module owns the single authorization and routing entry point.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict


def _accepts_authorization(handler: Any) -> bool:
    """True when a tool handler declares the dispatch ``authorization`` kwarg.

    Only the mutating handlers do; the read-only ones take a single positional
    ``args``. Passing ``authorization=`` to a handler that does not declare it
    raises TypeError, which would take out every read-only tool — exactly the
    ones the gate auto-allows.
    """
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):
        return False
    for param in sig.parameters.values():
        if param.name == "authorization" and param.kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False


def execute_tool(name: str, arguments: Dict[str, Any],
                 approved: bool = False,
                 approval_id: str | None = None) -> str:
    """Authorize and dispatch one tool without bypassing safety policy.

    ``approved`` is the human's decision for a tool the gate returned as
    NEEDS_APPROVAL: the caller must have obtained it from the approval queue,
    never assume it. It only upgrades a NEEDS_APPROVAL decision; a BLOCKED tool
    stays blocked.

    ARCH-ENG-165: pass ``approval_id`` as well. With an id, the approval is
    VERIFIED against the shared queue via `assert_approval_covers`, so it must
    name THIS tool and these exact arguments — an approval for one amount or
    path cannot execute another. Without an id the upgrade is caller-asserted
    and unverified; the authorization reason says so, and only the tools that
    re-check the queue themselves are safe on that path.
    """
    from agents.safety import calling as runtime
    if not runtime.is_known_tool(name):
        return f"[Unknown tool: {name}]"

    # Resolve documented aliases ONCE, up front. ``is_known_tool`` and
    # ``SafetyGate`` both accept an alias and classify it by its canonical
    # target, but the handler table below is keyed on canonical names only —
    # so an alias passed the gate, was queued for approval, and then died at
    # the handler lookup with "[Unknown tool: write_file]". The operator
    # approved an action that could never run. Reproduced:
    # execute_tool("write_file", ..., approved=True) -> "[Unknown tool:
    # write_file]" even though the identical file_write call succeeded.
    name = runtime.canonical_tool_name(name)

    authorization = runtime._get_action_dispatcher().authorize(
        name, arguments, approved=approved, approval_id=approval_id)
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
        # ARCH-ENG-248 (AY-01): the typed surface was implemented and dead.
        "workshop_proposal_list": runtime._tool_workshop_proposal_list,
        "workshop_proposal_get": runtime._tool_workshop_proposal_get,
        "workshop_proposal_status": runtime._tool_workshop_proposal_status,
        "workshop_research": runtime._tool_workshop_research,
        "workshop_research_read": runtime._tool_workshop_research_read,
        "workshop_research_list": runtime._tool_workshop_research_list,
        "workshop_script": runtime._tool_workshop_script,
        "workshop_script_read": runtime._tool_workshop_script_read,
        "workshop_script_list": runtime._tool_workshop_script_list,
        "workshop_application": runtime._tool_workshop_application,
        "workshop_application_list": runtime._tool_workshop_application_list,
        "workshop_account_get": runtime._tool_workshop_account_get,
        "workshop_account_list": runtime._tool_workshop_account_list,
        "workshop_account_remove": runtime._tool_workshop_account_remove,
        "workshop_payment_get": runtime._tool_workshop_payment_get,
        "workshop_payment_list": runtime._tool_workshop_payment_list,
        "workshop_deliverable": runtime._tool_workshop_deliverable,
        "workshop_deliverable_list": runtime._tool_workshop_deliverable_list,
        "workshop_note": runtime._tool_workshop_note,
        "workshop_note_list": runtime._tool_workshop_note_list,
        "propose_code_patch": runtime._tool_propose_code_patch,
        "file_read": runtime._tool_file_read,
        "file_write": runtime._tool_file_write,
        "file_list": runtime._tool_file_list,
        "run_command": runtime._tool_run_command,
        "query_db": runtime._tool_query_db,
        "record_payment": runtime._tool_record_payment,
        "social_post": runtime._tool_social_post,
    }
    handler = handlers.get(name)
    if handler is None:
        return f"[Unknown tool: {name}]"
    try:
        # The gate above is the authorization. Hand it to the handler as the
        # dispatch capability so mutating tools (which refuse any call that did
        # not come through here) can run. Read-only handlers do not take the
        # kwarg, so only pass it where it is declared — passing it
        # unconditionally raises TypeError for every read-only tool.
        if _accepts_authorization(handler):
            return handler(arguments, authorization=runtime._DISPATCH_CAPABILITY)
        return handler(arguments)
    except Exception as exc:
        return f"[Tool error: {exc}]"


__all__ = ["execute_tool"]
