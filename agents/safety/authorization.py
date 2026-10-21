"""Canonical authorization boundary for state-changing operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from agents.autonomy.grants import AutonomyGrant
from agents.safety.gate import SafetyDecision, SafetyGate, is_known_tool


@dataclass(frozen=True)
class AuthorizationResult:
    allowed: bool
    decision: SafetyDecision
    reason: str


class AuthorizedActionDispatcher:
    """Authorize an operation once, then optionally invoke its implementation."""

    def __init__(self, safety_gate: SafetyGate | None = None) -> None:
        self.safety_gate = safety_gate or SafetyGate()

    def authorize(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        approved: bool = False,
        approval_id: str | None = None,
        grant: AutonomyGrant | None = None,
        required_level: int = 0,
        capability: str | None = None,
    ) -> AuthorizationResult:
        """Authorize one operation.

        ARCH-ENG-165 — `approved=True` WAS A BARE BOOLEAN.

        When the gate returned NEEDS_APPROVAL, a truthy `approved` upgraded the
        decision straight to ALLOWED with the reason "Explicit approval
        supplied". Nothing consulted `HumanApprovalQueue` and nothing called
        `assert_approval_covers`, so the caller's assertion was the whole
        authorization. The HIGH-TRUST handlers (`record_payment`, `social_post`,
        the crypto send) re-check the queue themselves and were never exposed —
        but a mutating tool with no internal check (`file_write`, `run_command`,
        `workshop_payment`) executed on a bare boolean.

        There are now two distinct paths, and the reason string says which:

        * `approval_id` GIVEN — VERIFIED. The item is resolved from the shared
          queue and `assert_approval_covers(item, name, arguments)` must return
          None. That binds the approval to this exact tool and these exact
          arguments (ARCH-ENG-129), so an approval for `$10` cannot execute a
          `$10,000` payment, and an approval that was never APPROVED, or that
          records no tool scope, authorizes nothing. A refusal does NOT upgrade
          the decision: the original NEEDS_APPROVAL stands and the caller
          re-enqueues, so the operator sees the pending request.

        * `approval_id` ABSENT — UNVERIFIED, caller-asserted. Behaviour is
          unchanged for compatibility, but the reason now says plainly that no
          scope was checked, so it cannot be mistaken for the verified path.
          Production callers should always pass the id; `main.py` does.
        """
        if not is_known_tool(name):
            return AuthorizationResult(False, SafetyDecision.BLOCKED, f"Unknown tool: {name}")
        if grant is not None and not grant.allows(
            required_level=required_level,
            capability=capability,
        ):
            return AuthorizationResult(
                False,
                SafetyDecision.BLOCKED,
                "Autonomy grant does not cover this capability or has expired",
            )
        allowed, reason, decision = self.safety_gate.check(name, arguments)

        if decision == SafetyDecision.NEEDS_APPROVAL and approved:
            if approval_id:
                return self._authorize_verified(name, arguments, approval_id,
                                               decision, reason)
            return AuthorizationResult(
                True, SafetyDecision.ALLOWED,
                "Explicit approval supplied by the caller (UNVERIFIED: no "
                "approval_id was passed, so no tool scope or argument scope was "
                "checked)",
            )
        return AuthorizationResult(allowed, decision, reason)

    @staticmethod
    def _authorize_verified(name: str, arguments: Dict[str, Any],
                            approval_id: str, decision: SafetyDecision,
                            reason: str) -> AuthorizationResult:
        """Upgrade NEEDS_APPROVAL -> ALLOWED only on a queue-verified approval.

        ARCH-ENG-165. Any failure here returns the ORIGINAL NEEDS_APPROVAL
        decision, never ALLOWED: a refusal must leave the action pending rather
        than silently block it, so the operator still sees the request.
        """
        try:
            from agents.safety.approval import (
                ApprovalStatus, HumanApprovalQueue, assert_approval_covers,
            )
            item = HumanApprovalQueue.instance().find_by_id(approval_id)
            if item is None:
                return AuthorizationResult(
                    False, decision,
                    f"approval {approval_id} was not found in the queue; "
                    f"{name} was not executed ({reason})")
            refusal = assert_approval_covers(item, name, arguments)
            if refusal:
                return AuthorizationResult(
                    False, decision, f"{refusal}; {name} was not executed")
            return AuthorizationResult(
                True, SafetyDecision.ALLOWED,
                f"approval {approval_id} ({item.status.value}) verified to cover "
                f"{name} and these arguments",
            )
        except Exception as exc:
            # A queue/policy error must never read as an authorization.
            return AuthorizationResult(
                False, decision,
                f"approval verification failed for {approval_id}: {exc}; "
                f"{name} was not executed")

    def dispatch(
        self,
        name: str,
        arguments: Dict[str, Any],
        handler: Callable[[object], str],
        *,
        approved: bool = False,
        approval_id: str | None = None,
        grant: AutonomyGrant | None = None,
        required_level: int = 0,
        capability: str | None = None,
    ) -> str:
        result = self.authorize(
            name,
            arguments,
            approved=approved,
            approval_id=approval_id,
            grant=grant,
            required_level=required_level,
            capability=capability,
        )
        if not result.allowed:
            if result.decision == SafetyDecision.NEEDS_APPROVAL:
                return f"[PENDING APPROVAL] {name} was not executed: {result.reason}"
            return f"[BLOCKED] {result.reason}"
        return handler(result)


__all__ = ["AuthorizedActionDispatcher", "AuthorizationResult"]
