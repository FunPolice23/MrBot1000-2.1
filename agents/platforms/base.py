"""
agents/platforms/base.py — PlatformAdapter ABC (v2.0.22 S3)

The adapter skeleton for platform interaction. Every concrete platform
(Fiverr, Upwork, Reddit, LinkedIn, Discord, airdrop sites, ...) implements
this interface. The security contract:

  * fetch_instructions() MUST go through InstructionGate. A discovered
    SKILL.md / playbook is untrusted data until a human approves it.
  * execute_action() MUST consult TrustBoundary: high-trust actions
    (account creation, posting, sending funds, download+exec, ...) are
    never auto-run; they require human confirmation and cannot be
    authorized by an untrusted instruction.

Credentials are NEVER stored in code or passed in plaintext here. Adapters
read them from a secrets backend (env/.env at runtime) and only when the
human has enabled that platform.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from ..instruction_gate import InstructionGate, QuarantinedInstruction
from ..trust_boundary import TrustBoundary, HIGH_TRUST_ACTIONS


class PlatformAdapter(ABC):
    """Base class for all platform integrations."""

    #: Unique platform key (fiverr, upwork, reddit, ...).
    platform: str = "base"
    #: Whether this platform permits AI agents at all.
    ai_policy: str = "ai_allowed"  # ai_allowed | ai_disallowed | human_only
    #: Base URL used to resolve relative instruction paths (e.g. SKILL.md).
    base_url: str = ""

    def __init__(self, gate: InstructionGate, boundary: Optional[TrustBoundary] = None,
                 *, credentials=None, enabled: bool = False):
        self.gate = gate
        self.boundary = boundary or TrustBoundary(ai_policy=self.ai_policy)
        # Credentials are supplied externally (e.g. from a secrets store),
        # never constructed from constants. None means "not provided".
        self.credentials = credentials
        self.enabled = enabled

    # -- instruction handling (security choke point) -----------------------

    def instruction_url(self) -> Optional[str]:
        """Return the location of this platform's playbook/SKILL.md, if any."""
        return None

    def fetch_instructions(self) -> QuarantinedInstruction:
        """Fetch the platform's instruction file THROUGH the gate.

        Returns a QuarantinedInstruction. Callers must check `.trusted`
        before acting on the content. Untrusted content is never executed.
        """
        url = self.instruction_url()
        if not url:
            # No remote instructions for this platform -> treat as empty, trusted.
            return QuarantinedInstruction(url="", status="allowed", content="",
                                         content_hash="", title=f"{self.platform}:none")
        return self.gate.fetch_instruction(url, kind="skill.md",
                                           title=f"{self.platform} SKILL.md")

    # -- action execution (trust boundary) ---------------------------------

    @abstractmethod
    def list_actions(self) -> List[str]:
        """Return the actions this adapter supports (for UI / planning)."""

    def execute_action(self, action: str, payload: dict | None = None,
                        *, human_confirmed: bool = False) -> dict:
        """Execute a platform action under the trust boundary.

        High-trust actions are refused unless `human_confirmed` is True AND
        the instruction authorizing them is on the allowlist. This makes it
        structurally impossible for an untrusted SKILL.md to drive a
        credential/fund/exec action.
        """
        payload = payload or {}
        if self.boundary.is_high_trust(action):
            if not human_confirmed:
                return {"ok": False,
                        "reason": f"action '{action}' requires human confirmation"}
            # Even with confirmation, an untrusted instruction cannot raise
            # privilege for high-trust acts (the human is the authorizer).
            return self._do_action(action, payload, confirmed_by_human=True)
        # Low-trust: check auto-execute policy.
        allowed, reason = self.boundary.may_auto_execute(action, instruction_trusted=False)
        if not allowed:
            return {"ok": False, "reason": reason}
        return self._do_action(action, payload, confirmed_by_human=human_confirmed)

    @abstractmethod
    def _do_action(self, action: str, payload: dict, *,
                   confirmed_by_human: bool) -> dict:
        """Concrete action implementation. Only called when the boundary allows."""
