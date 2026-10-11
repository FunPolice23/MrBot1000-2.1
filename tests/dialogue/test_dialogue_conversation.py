import pytest

from agents.cognition.dialogue import DialogueIntent, NaturalDialogue


def test_preserves_natural_turn_and_extracts_non_authoritative_cues():
    dialogue = NaturalDialogue("choose an earning opportunity", max_turns=3)

    turn = dialogue.add_turn(
        "Edward",
        "I think we should test platform A. What evidence do we still need? "
        "ACTION: run a read-only check.",
        evidence_ids=["ev-1"],
        got_node_id="option:a",
    )

    assert turn.text.startswith("I think we should")
    assert DialogueIntent.QUESTION in turn.intents
    assert DialogueIntent.PROPOSAL in turn.intents
    assert DialogueIntent.ACTION in turn.intents
    assert turn.questions == ("What evidence do we still need?",)
    assert turn.evidence_ids == ("ev-1",)
    assert "Edward: I think we should test platform A." in dialogue.transcript()
    assert turn.got_node_id == "option:a"


def test_decision_markers_do_not_authorize_execution():
    dialogue = NaturalDialogue("choose safely")
    turn = dialogue.add_turn("Jacob", "BLOCKED: payment evidence is stale.")

    assert turn.intents == (DialogueIntent.DECISION,)
    assert turn.decision_markers == ("BLOCKED: payment evidence is stale",)
    assert dialogue.to_dict()["turns"][0]["text"].startswith("BLOCKED")


def test_dialogue_is_bounded_without_silent_truncation():
    dialogue = NaturalDialogue("goal", max_turns=1)
    dialogue.add_turn("Edward", "First complete thought.")

    with pytest.raises(ValueError, match="budget exhausted"):
        dialogue.add_turn("Jacob", "Second complete thought.")
