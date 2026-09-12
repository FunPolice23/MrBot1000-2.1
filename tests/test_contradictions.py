from agents.cognition import Claim
from agents.contradictions import ContradictionStatus, open_contradiction


def test_contradiction_requires_evidence_to_resolve():
    first = Claim("submission is open")
    second = Claim("submission is closed")
    case = open_contradiction("submission status", [first, second])
    assert not case.resolve(first, [])
    assert case.status is ContradictionStatus.OPEN
    assert case.resolve(first, ["ev-current-page"])
    assert case.status is ContradictionStatus.RESOLVED
    assert case.resolution == first.text


def test_blocked_contradiction_cannot_be_reopened_implicitly():
    case = open_contradiction("channel", [Claim("DM"), Claim("comment")])
    case.block("source instructions conflict")
    assert case.status is ContradictionStatus.BLOCKED
    assert not case.resolve(case.claims[0], ["ev-1"])