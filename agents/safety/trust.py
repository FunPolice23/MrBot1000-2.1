"""
agents/trust_boundary.py — High-trust action boundary (v2.0.22 S2)

Defines the set of actions that are dangerous enough to REQUIRE explicit
human confirmation, and a guard that prevents untrusted (non-allowlisted)
instructions from ever triggering them.

This is the second half of the security-first work: even once platform
adapters exist (S3), a discovered remote SKILL.md can NEVER make the agent
create an account, set a password, post content, send funds, or download
and execute a file. Those are gated behind human confirmation.

AI-policy awareness: some platforms forbid AI. If a platform is tagged
ai_disallowed, the agent must stay human-in-the-loop for all mutating
actions regardless of model capability.
"""

from typing import Iterable

# Actions that mutate external state / credentials / money / local exec.
HIGH_TRUST_ACTIONS = frozenset({
    "create_account",
    "set_password",
    "login",
    "post",            # create public content / cross-post
    "send_message",    # outbound contact (e.g. gig proposal to a human)
    "send_funds",
    "download_exec",   # download + run a file
    "submit_proposal", # counts as outbound commitment to a human/client
    "grant_oauth",
})

# Actions that are read-only / safe and may proceed with normal guardrails.
LOW_TRUST_ACTIONS = frozenset({
    "read",
    "search",
    "list",
    "fetch_instructions",  # itself gated by instruction_gate
    "analyze",
    "draft",               # local drafting only, no send
})


class TrustBoundary:
    """Decides whether an action may proceed and whether it needs a human."""

    def __init__(self, *, ai_policy: str = "ai_allowed"):
        # ai_policy: "ai_allowed" | "ai_disallowed" | "human_only"
        self.ai_policy = ai_policy

    @staticmethod
    def is_high_trust(action: str) -> bool:
        return action in HIGH_TRUST_ACTIONS

    def requires_human_confirmation(self, action: str,
                                    instruction_trusted: bool = False) -> bool:
        """True if this action must wait for explicit human confirmation.

        - Any HIGH_TRUST action always requires human confirmation, and an
          untrusted instruction can NEVER satisfy that confirmation.
        - If the platform forbids AI (ai_disallowed/human_only), ALL mutating
          actions require a human regardless of model.
        """
        if self.is_high_trust(action):
            # High-trust actions need a human. An untrusted (quarantined)
            # instruction must not count as the human's go-ahead.
            return True
        # Low-trust but platform says no-AI -> still human-in-the-loop.
        if self.ai_policy in ("ai_disallowed", "human_only"):
            return True
        return False

    def may_auto_execute(self, action: str,
                         instruction_trusted: bool = False) -> tuple[bool, str]:
        """Returns (allowed, reason). `allowed` is strictly for LOW_TRUST
        actions under an AI-allowed policy. High-trust actions are NEVER
        auto-executed, and untrusted instructions can never raise privilege."""
        if self.is_high_trust(action):
            return False, (
                f"action '{action}' is high-trust and requires human confirmation; "
                f"untrusted instructions cannot authorize it"
            )
        if self.ai_policy in ("ai_disallowed", "human_only"):
            return False, f"platform ai_policy='{self.ai_policy}' requires human-in-the-loop"
        if not instruction_trusted:
            # Low-trust, AI allowed, but the instruction came from an untrusted
            # source — still require a human for anything beyond pure local read.
            return False, "instruction not on allowlist; human confirmation required"
        return True, "low-trust action, AI allowed, instruction trusted"
