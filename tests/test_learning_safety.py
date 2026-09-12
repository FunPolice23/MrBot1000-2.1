from agents.learning_safety import LearningSafetyBoundary
from agents.trust_boundary import TrustBoundary


def test_learning_cannot_authorize_high_trust_action():
    boundary = LearningSafetyBoundary(TrustBoundary())
    assert not boundary.authorize("send_funds", human_approved=False)[0]
    assert boundary.authorize("send_funds", human_approved=True)[0]


def test_learning_cannot_promote_untrusted_instruction():
    boundary = LearningSafetyBoundary(TrustBoundary())
    allowed, reason = boundary.authorize("read", instruction_trusted=False)
    assert not allowed
    assert "human" in reason