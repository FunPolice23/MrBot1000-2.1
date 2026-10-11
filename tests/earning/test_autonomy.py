from agents.autonomy.grants import AutonomyGrant
from agents.safety.authorization import AuthorizedActionDispatcher
from agents.safety.gate import SafetyDecision


def test_grant_requires_level_capability_and_expiry():
    grant = AutonomyGrant(
        level=2,
        capabilities=frozenset({"write_workspace"}),
        expires_at=100.0,
    )

    assert grant.allows(required_level=2, capability="write_workspace", now=99.0)
    assert not grant.allows(required_level=3, capability="write_workspace", now=99.0)
    assert not grant.allows(required_level=2, capability="send_message", now=99.0)
    assert not grant.allows(required_level=2, capability="write_workspace", now=100.0)


def test_dispatcher_blocks_action_outside_grant():
    dispatcher = AuthorizedActionDispatcher()
    grant = AutonomyGrant(
        level=1,
        capabilities=frozenset({"read_web"}),
        expires_at=float("inf"),
    )

    result = dispatcher.authorize(
        "read_file",
        {"path": "example.txt"},
        grant=grant,
        required_level=2,
        capability="write_workspace",
    )

    assert result.decision is SafetyDecision.BLOCKED
    assert "Autonomy grant" in result.reason
