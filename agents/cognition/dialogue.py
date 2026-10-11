"""Natural dual-brain conversation records separate from GoT and authority.

The full spoken turn is retained for human-like dialogue and UI rendering.
Small, deterministic annotations make questions, proposals, and decisions
queryable without pretending that conversation itself authorizes an action.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List


class DialogueIntent(str, Enum):
    QUESTION = "question"
    PROPOSAL = "proposal"
    CHALLENGE = "challenge"
    DECISION = "decision"
    ACTION = "action"
    UPDATE = "update"


_QUESTION_RE = re.compile(r"[^.!?\n]*\?")
_ACTION_RE = re.compile(
    r"\b(?:ACTION|NEXT STEP|TODO|I(?:'|’)LL|LET(?:'|’)S|WE SHOULD|PROCEED)\b"
    r"[^.!?\n]*",
    re.IGNORECASE,
)
_DECISION_RE = re.compile(
    r"\b(?:APPROVED|BLOCKED|REJECTED|DECISION|AGREE|DISAGREE|UNKNOWN)\b"
    r"[^.!?\n]*",
    re.IGNORECASE,
)


def _clean_matches(matches: Iterable[str]) -> tuple[str, ...]:
    return tuple(" ".join(match.split()).strip() for match in matches if match.strip())


@dataclass(frozen=True)
class DialogueTurn:
    """One complete natural-language turn plus queryable annotations."""

    speaker: str
    text: str
    intents: tuple[DialogueIntent, ...] = ()
    questions: tuple[str, ...] = ()
    action_intents: tuple[str, ...] = ()
    decision_markers: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    got_node_id: str = ""
    turn_id: str = field(default_factory=lambda: "dialogue_" + uuid.uuid4().hex[:20])
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "turn_id": self.turn_id,
            "speaker": self.speaker,
            "text": self.text,
            "intents": [intent.value for intent in self.intents],
            "questions": list(self.questions),
            "action_intents": list(self.action_intents),
            "decision_markers": list(self.decision_markers),
            "evidence_ids": list(self.evidence_ids),
            "got_node_id": self.got_node_id,
            "created_at": self.created_at,
        }


class NaturalDialogue:
    """Bounded transcript that preserves speech while exposing structured cues."""

    def __init__(self, goal: str, *, max_turns: int = 12):
        if not goal.strip():
            raise ValueError("goal is required")
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self.goal = goal.strip()
        self.max_turns = max_turns
        self.turns: List[DialogueTurn] = []

    @property
    def remaining_turns(self) -> int:
        return max(0, self.max_turns - len(self.turns))

    def add_turn(
        self,
        speaker: str,
        text: str,
        *,
        evidence_ids: Iterable[str] = (),
        got_node_id: str = "",
    ) -> DialogueTurn:
        """Retain the exact turn and derive non-authoritative conversation cues."""
        normalized_speaker = " ".join(str(speaker or "").split())
        if not normalized_speaker or not str(text or "").strip():
            raise ValueError("speaker and text are required")
        if len(self.turns) >= self.max_turns:
            raise ValueError("dialogue turn budget exhausted")

        content = str(text).strip()
        questions = _clean_matches(_QUESTION_RE.findall(content))
        actions = _clean_matches(_ACTION_RE.findall(content))
        decisions = _clean_matches(_DECISION_RE.findall(content))
        intents: list[DialogueIntent] = []
        if questions:
            intents.append(DialogueIntent.QUESTION)
        if actions:
            intents.append(DialogueIntent.ACTION)
            if any(word in content.upper() for word in ("SHOULD", "LET'S", "I'LL", "I’LL")):
                intents.append(DialogueIntent.PROPOSAL)
        if decisions:
            intents.append(DialogueIntent.DECISION)
        if not intents:
            intents.append(DialogueIntent.UPDATE)

        turn = DialogueTurn(
            speaker=normalized_speaker,
            text=content,
            intents=tuple(dict.fromkeys(intents)),
            questions=questions,
            action_intents=actions,
            decision_markers=decisions,
            evidence_ids=tuple(dict.fromkeys(str(item) for item in evidence_ids if item)),
            got_node_id=got_node_id,
        )
        self.turns.append(turn)
        return turn

    def transcript(self, *, limit: int | None = None) -> str:
        turns = self.turns if limit is None else self.turns[-max(0, limit):]
        return "\n".join(f"{turn.speaker}: {turn.text}" for turn in turns)

    def to_dict(self) -> dict[str, object]:
        return {
            "goal": self.goal,
            "max_turns": self.max_turns,
            "remaining_turns": self.remaining_turns,
            "turns": [turn.to_dict() for turn in self.turns],
        }


__all__ = ["DialogueIntent", "DialogueTurn", "NaturalDialogue"]
