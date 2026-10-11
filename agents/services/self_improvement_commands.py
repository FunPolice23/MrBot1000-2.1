"""agents/self_improvement_commands.py — Agent-callable, approval-gated patch commands.

These are the ONLY entry points an agent (Edward/Jacob) or the GUI uses to
propose and act on code patches. Every mutation stays behind the
CodePatchService's human-approval gate:

- ``propose_code_patch`` enqueues a proposal (never applies anything).
- ``approve_and_apply`` approves the exact item, then applies + verifies +
  rolls back on failure.
- ``decline_patch`` denies the item (no file touched).

The commands are feature-gated: if self-improvement is disabled, propose()
returns a blocked result and nothing is enqueued.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from agents.core.feature_flags import feature_enabled


def _service_available(service: Any) -> bool:
    return service is not None and hasattr(service, "propose")


def propose_code_patch(
    service: Any,
    *,
    authored_by: str,
    motivation: str,
    detail: str,
    target_path: str,
    patch_text: str,
    validation: str = "py_compile",
) -> dict[str, Any]:
    """Propose a code patch. Enqueues a human-approval item; applies nothing.

    Returns {ok, patch_id, status} or {ok: False, reason} when blocked.
    """
    if not feature_enabled("self_improvement"):
        return {"ok": False, "status": "blocked",
                "reason": "self-improvement is disabled in settings"}
    if not _service_available(service):
        return {"ok": False, "status": "blocked",
                "reason": "self-improvement service unavailable"}
    from agents.services.code_patch_service import CodePatch

    patch = CodePatch(
        target_path=target_path,
        authored_by=authored_by,
        motivation=motivation,
        detail=detail,
        patch_text=patch_text,
        validation=validation,
    )
    try:
        service.propose(patch)
    except ValueError as exc:
        return {"ok": False, "status": "rejected", "reason": str(exc)}
    return {"ok": True, "status": "pending_approval", "patch_id": patch.patch_id}


def approve_and_apply(service: Any, approval_id: str) -> dict[str, Any]:
    """Approve the exact approval item, then apply the patch (backup/verify/rollback).

    Returns the CodePatchService apply result dict.
    """
    if not feature_enabled("self_improvement"):
        return {"ok": False, "status": "blocked",
                "reason": "self-improvement is disabled in settings"}
    if not _service_available(service):
        return {"ok": False, "status": "blocked",
                "reason": "self-improvement service unavailable"}
    queue = getattr(service, "approval_queue", None)
    if queue is None:
        return {"ok": False, "status": "blocked", "reason": "no approval queue"}
    if not queue.approve(approval_id, notes="Approved from self-improvement"):
        return {"ok": False, "status": "not_pending",
                "reason": f"approval item {approval_id} is not pending"}
    patch = service._patches.get(approval_id)
    if patch is None:
        return {"ok": False, "status": "unknown_patch",
                "reason": f"no patch registered for {approval_id}"}
    return service.apply_approved(patch, approval_id=approval_id)


def decline_patch(service: Any, approval_id: str, notes: str = "") -> dict[str, Any]:
    """Deny the approval item; no file is touched."""
    if not feature_enabled("self_improvement"):
        return {"ok": False, "status": "blocked",
                "reason": "self-improvement is disabled in settings"}
    if not _service_available(service):
        return {"ok": False, "status": "blocked",
                "reason": "self-improvement service unavailable"}
    queue = getattr(service, "approval_queue", None)
    if queue is None:
        return {"ok": False, "status": "blocked", "reason": "no approval queue"}
    ok = queue.deny(approval_id, notes=notes or "Declined from self-improvement")
    return {"ok": ok, "status": "declined" if ok else "not_pending"}


__all__ = [
    "propose_code_patch",
    "approve_and_apply",
    "decline_patch",
]
