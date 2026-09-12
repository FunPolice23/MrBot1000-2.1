from agents.cognition import Lesson, Outcome, OutcomeState
from agents.memory_promotion import MemoryPromotionPolicy
from agents.program_knowledge import MemoryDatabase


def _verified_outcome(outcome_id):
    return Outcome(OutcomeState.VERIFIED, "completed", [f"evidence-{outcome_id}"], outcome_id)


def test_unverified_or_unlinked_lessons_are_not_promoted():
    policy = MemoryPromotionPolicy()
    assert not policy.evaluate(Lesson("try again"), []).allowed
    assert not policy.evaluate(Lesson("try again", ["out-1"], verified=False),
                               [_verified_outcome("out-1")]).allowed
    assert not policy.evaluate(Lesson("try again", ["out-unknown"], verified=True),
                               [_verified_outcome("out-1")]).allowed


def test_verified_outcome_lesson_is_persisted_with_provenance(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    policy = MemoryPromotionPolicy()
    outcome = _verified_outcome("out-1")
    lesson = Lesson("Prefer sources with a current submission channel", [outcome.outcome_id], verified=True)

    decision = policy.promote(database, lesson, [outcome])

    assert decision.allowed
    stored = database.get_memories(category="lesson")
    assert stored[0]["source"] == "verified_outcome"
    assert "out-1" in stored[0]["tags"]


def test_unverified_outcome_cannot_update_memory(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    outcome = Outcome(OutcomeState.OBSERVED, "model says it worked", ["evidence-1"], "out-1")
    lesson = Lesson("Assume this worked", [outcome.outcome_id], verified=True)

    decision = MemoryPromotionPolicy().promote(database, lesson, [outcome])

    assert not decision.allowed
    assert database.get_memories(category="lesson") == []