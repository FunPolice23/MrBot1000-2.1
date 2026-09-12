from agents.cognition import ActionIntent, ActionState, CognitionRecord
from agents.discussion import BoundedDiscussion, DiscussionPurpose, DiscussionTurn
from agents.canonical_state import CanonicalCognitionState


def test_discussion_budget_ends_without_unbounded_autonomy():
    discussion = BoundedDiscussion("verify", max_turns=1)
    assert discussion.add_turn(DiscussionTurn("Edward", DiscussionPurpose.PROPOSE, "proposal"))
    assert not discussion.add_turn(DiscussionTurn("Jacob", DiscussionPurpose.CHALLENGE, "retry", ["ev-1"]))
    assert discussion.status.value == "budget_exhausted"


def test_canonical_state_rejects_false_completed_action():
    state = CanonicalCognitionState()
    record = CognitionRecord(
        goal="execute",
        persona="Edward",
        action=ActionIntent("act-1", "read", state=ActionState.COMPLETED),
    )
    try:
        state.record(record)
    except ValueError as error:
        assert "execution proof" in str(error)
    else:
        raise AssertionError("false completion was accepted")