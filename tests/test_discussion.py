from agents.discussion import (
    BoundedDiscussion,
    DiscussionPurpose,
    DiscussionStatus,
    DiscussionTurn,
)


def test_discussion_requires_new_evidence_for_challenge():
    discussion = BoundedDiscussion("assess listing", max_turns=4)
    assert discussion.add_turn(DiscussionTurn(
        "edward", DiscussionPurpose.PROPOSE, "Pursue it", ["ev-1"]))
    assert not discussion.add_turn(DiscussionTurn(
        "jacob", DiscussionPurpose.CHALLENGE, "I disagree", ["ev-1"]))
    assert discussion.status is DiscussionStatus.ACTIVE
    assert discussion.blocked_reason == "challenge requires new evidence"

    assert discussion.add_turn(DiscussionTurn(
        "jacob", DiscussionPurpose.CHALLENGE, "The source is stale", ["ev-2"]))


def test_discussion_resolves_only_with_explicit_conclusion():
    discussion = BoundedDiscussion("choose platform", max_turns=3)
    assert discussion.add_turn(DiscussionTurn(
        "edward", DiscussionPurpose.PROPOSE, "Use platform A"))
    assert discussion.status is DiscussionStatus.ACTIVE
    assert discussion.add_turn(DiscussionTurn(
        "jacob", DiscussionPurpose.CONCLUDE, "Use platform A pending approval"))
    assert discussion.status is DiscussionStatus.RESOLVED
    assert discussion.resolution.startswith("Use platform A")
    assert not discussion.add_turn(DiscussionTurn(
        "edward", DiscussionPurpose.REVISE, "Change plan"))


def test_discussion_exhausts_budget_without_fabricating_consensus():
    discussion = BoundedDiscussion("compare options", max_turns=2)
    assert discussion.add_turn(DiscussionTurn(
        "edward", DiscussionPurpose.PROPOSE, "Option A"))
    assert discussion.add_turn(DiscussionTurn(
        "jacob", DiscussionPurpose.VERIFY, "Insufficient evidence"))
    assert discussion.status is DiscussionStatus.BUDGET_EXHAUSTED
    assert discussion.resolution == ""