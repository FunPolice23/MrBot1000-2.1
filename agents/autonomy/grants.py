"""Capability-scoped, expiring autonomy grants."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import FrozenSet


@dataclass(frozen=True)
class AutonomyGrant:
    """An operator-issued grant; model output cannot create or extend one."""

    level: int
    capabilities: FrozenSet[str] = frozenset()
    expires_at: float = float("inf")
    scope: str = ""
    reason: str = ""
    issuer: str = "operator"
    policy_version: str = "1"

    def __post_init__(self) -> None:
        if self.level < 0:
            raise ValueError("autonomy level cannot be negative")

    def allows(
        self,
        *,
        required_level: int = 0,
        capability: str | None = None,
        now: float | None = None,
    ) -> bool:
        if required_level < 0:
            raise ValueError("required level cannot be negative")
        if self.level < required_level:
            return False
        if (time.time() if now is None else now) >= self.expires_at:
            return False
        return capability is None or capability in self.capabilities


__all__ = ["AutonomyGrant"]
