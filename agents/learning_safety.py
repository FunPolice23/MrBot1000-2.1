"""Safety boundary between learned preferences and action authorization."""

from agents.trust_boundary import TrustBoundary


class LearningSafetyBoundary:
    """Allow learning to rank options, never to bypass trust controls."""

    def __init__(self, trust_boundary: TrustBoundary | None = None):
        self.trust_boundary = trust_boundary or TrustBoundary()

    def authorize(self, action: str, *, human_approved: bool = False,
                  instruction_trusted: bool = False) -> tuple[bool, str]:
        if self.trust_boundary.requires_human_confirmation(action, instruction_trusted):
            if not human_approved:
                return False, "learned preference cannot replace human approval"
            return True, "human approval satisfied trust boundary"
        return self.trust_boundary.may_auto_execute(action, instruction_trusted)


__all__ = ["LearningSafetyBoundary"]