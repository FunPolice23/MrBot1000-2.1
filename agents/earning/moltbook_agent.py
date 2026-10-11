"""Moltbook agent identity onboarding.

Moltbook is agent-operated: the agent reads the official SKILL.md and creates
its own registration request. The human later claims/verifies the agent. This
module keeps those roles separate and never stores the returned API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


MOLTBOOK_SKILL_URL = "https://www.moltbook.com/skill.md"
MOLTBOOK_REGISTER_URL = "https://www.moltbook.com/api/v1/agents/register"


@dataclass(frozen=True)
class MoltbookRegistrationPlan:
    """A reviewable plan for an agent-owned Moltbook registration."""

    agent_name: str
    description: str
    skill_url: str = MOLTBOOK_SKILL_URL
    registration_url: str = MOLTBOOK_REGISTER_URL
    skill_status: str = "not_read"
    human_follow_up: str = "Claim and verify the agent using Moltbook's claim link."
    missing: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.agent_name.strip() and self.description.strip()
                    and self.skill_status == "allowed" and not self.missing)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "description": self.description,
            "skill_url": self.skill_url,
            "registration_url": self.registration_url,
            "skill_status": self.skill_status,
            "human_follow_up": self.human_follow_up,
            "missing": list(self.missing),
            "ready": self.ready,
        }


class MoltbookAgentCapability:
    """Read, review, and optionally submit an agent-owned registration request.

    ``register`` is deliberately explicit because it creates an external
    account. It returns the claim URL but discards the API key immediately;
    callers must keep secrets in an operator-controlled secret store.
    """

    def __init__(self, instruction_gate: Any, http_client: Any = None):
        self.instruction_gate = instruction_gate
        self.http_client = http_client

    def read_skill(self):
        return self.instruction_gate.fetch_instruction(
            MOLTBOOK_SKILL_URL, kind="skill.md", title="Moltbook SKILL.md"
        )

    def plan_registration(self, agent_name: str, description: str,
                          skill_status: str = "not_read") -> MoltbookRegistrationPlan:
        missing = []
        if not agent_name.strip():
            missing.append("agent_name")
        if not description.strip():
            missing.append("description")
        return MoltbookRegistrationPlan(
            agent_name=agent_name.strip(), description=description.strip(),
            skill_status=skill_status, missing=missing,
        )

    def register(self, plan: MoltbookRegistrationPlan,
                 *, capability_approved: bool = False) -> Dict[str, Any]:
        """Register the agent, only after the capability has been approved.

        The approval authorizes the agent's registration call; it does not
        authorize the human claim/verification step or any later posting.
        """
        if not plan.ready:
            return {"ok": False, "status": "blocked", "reason": "registration plan is not ready"}
        if not capability_approved:
            return {"ok": False, "status": "awaiting_approval",
                    "reason": "agent registration requires explicit capability approval"}
        if self.http_client is None:
            return {"ok": False, "status": "blocked", "reason": "no HTTP client configured"}
        response = self.http_client.post(
            MOLTBOOK_REGISTER_URL,
            json={"name": plan.agent_name, "description": plan.description},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        agent = payload.get("agent", {}) if isinstance(payload, dict) else {}
        return {
            "ok": True,
            "status": "registered",
            "agent_name": plan.agent_name,
            "claim_url": agent.get("claim_url", ""),
            "verification_code": agent.get("verification_code", ""),
            "api_key_discarded": True,
            "human_follow_up": plan.human_follow_up,
        }


__all__ = [
    "MOLTBOOK_SKILL_URL", "MOLTBOOK_REGISTER_URL",
    "MoltbookRegistrationPlan", "MoltbookAgentCapability",
]
