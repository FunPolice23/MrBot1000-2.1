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
        grant: AutonomyGrant | None = None,
        required_level: int = 0,
        capability: str | None = None,
    ) -> AuthorizationResult:
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
            return AuthorizationResult(True, SafetyDecision.ALLOWED, "Explicit approval supplied")
        return AuthorizationResult(allowed, decision, reason)

    def dispatch(
        self,
        name: str,
        arguments: Dict[str, Any],
        handler: Callable[[object], str],
        *,
        approved: bool = False,
        grant: AutonomyGrant | None = None,
        required_level: int = 0,
        capability: str | None = None,
    ) -> str:
        result = self.authorize(
            name,
            arguments,
            approved=approved,
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
