"""Conversation and speech-pattern memory helpers."""

from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List


class ConversationMemory:
    """
    Rolling conversation store that respects a character budget.

    Usage::

        mem = ConversationMemory(max_chars=6000, max_turns=20)
        mem.add("user", "Hello!")
        mem.add("assistant", "Hi there!")
        context_str = mem.render()
    """

    def __init__(self, max_chars: int = 6000, max_turns: int = 20):
        self._max_chars = max_chars
        self._max_turns = max_turns
        self._turns: deque = deque()

    def add(self, role: str, content: str):
        self._turns.append({"role": role, "content": content,
                             "ts": time.time()})
        # Trim to max_turns
        while len(self._turns) > self._max_turns:
            self._turns.popleft()
        # Trim to max_chars
        while self._char_count() > self._max_chars and len(self._turns) > 1:
            self._turns.popleft()

    def _char_count(self) -> int:
        return sum(len(t["content"]) for t in self._turns)

    def render(self, include_timestamps: bool = False) -> str:
        parts = []
        for t in self._turns:
            ts = f"[{datetime.fromtimestamp(t['ts']).strftime('%H:%M')}] " \
                if include_timestamps else ""
            parts.append(f"{ts}{t['role'].upper()}: {t['content']}")
        return "\n".join(parts)

    def as_messages(self) -> List[Dict[str, str]]:
        return [{"role": t["role"], "content": t["content"]}
                for t in self._turns]

    def clear(self):
        self._turns.clear()

    def __len__(self):
        return len(self._turns)


# ─────────────────────────────────────────────────────────────────────────────
#  SpeechPatternBank  — learn and apply speech styles
# ─────────────────────────────────────────────────────────────────────────────
class SpeechPatternBank:
    """
    Observe user messages and extract style patterns for adapting responses.

    Tracked features:
      - Vocabulary richness (type-token ratio)
      - Average sentence length
      - Formality score (counts formal vs informal markers)
      - Preferred greeting/sign-off phrases
      - Common question starters
      - Emoji usage frequency
      - Punctuation style (exclamation, ellipsis, comma-heavy)

    Usage::

        bank = SpeechPatternBank()
        bank.observe("Hey! can u help me fix this bug?? lol")
        style = bank.describe()      # returns a style description string
        instruction = bank.as_prompt_instruction()
    """

    FORMAL_MARKERS = {
        "please", "kindly", "regarding", "therefore", "however",
        "furthermore", "consequently", "would you", "could you",
        "i would like", "i would appreciate"
    }
    INFORMAL_MARKERS = {
        "hey", "lol", "haha", "omg", "gonna", "wanna", "gotta",
        "ngl", "tbh", "btw", "idk", "imo", "u ", " ur ", "thx", "ty"
    }
    GREETING_PATTERNS = [
        r"^(hi|hey|hello|good\s+\w+|howdy|sup|yo)\b",
    ]
    QUESTION_STARTERS = [
        "what", "how", "why", "when", "where", "who",
        "can you", "could you", "would you", "is there"
    ]

    def __init__(self, max_samples: int = 200):
        self._max = max_samples
        self._samples: deque = deque(maxlen=max_samples)
        self._word_freq: defaultdict = defaultdict(int)
        self._greetings: List[str] = []
        self._question_starters: defaultdict = defaultdict(int)
        self._emoji_count = 0
        self._exclamation_count = 0
        self._ellipsis_count = 0
        self._formal_score = 0
        self._informal_score = 0
        self._total_words = 0
        self._total_sentences = 0
        self._lock = threading.Lock()

    def observe(self, text: str):
        """Ingest a user message and update style statistics."""
        with self._lock:
            self._samples.append(text)
            lower = text.lower()
            words = re.findall(r"\b\w+\b", lower)
            sentences = re.split(r"[.!?]+", text)
            sentences = [s.strip() for s in sentences if s.strip()]

            self._total_words += len(words)
            self._total_sentences += max(len(sentences), 1)

            for w in words:
                self._word_freq[w] += 1

            # Formality
            for marker in self.FORMAL_MARKERS:
                if marker in lower:
                    self._formal_score += 1
            for marker in self.INFORMAL_MARKERS:
                if marker in lower:
                    self._informal_score += 1

            # Greetings
            for pat in self.GREETING_PATTERNS:
                if re.match(pat, lower):
                    first_word = lower.split()[0] if lower.split() else ""
                    if first_word and first_word not in self._greetings:
                        self._greetings.append(first_word)

            # Question starters
            for qs in self.QUESTION_STARTERS:
                if lower.startswith(qs):
                    self._question_starters[qs] += 1

            # Punctuation style
            self._emoji_count += len(re.findall(
                r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF]", text))
            self._exclamation_count += text.count("!")
            self._ellipsis_count += text.count("...")

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def formality_label(self) -> str:
        total = self._formal_score + self._informal_score
        if total == 0:
            return "neutral"
        ratio = self._formal_score / total
        if ratio > 0.65:
            return "formal"
        elif ratio < 0.35:
            return "casual"
        return "neutral"

    def avg_sentence_length(self) -> float:
        if self._total_sentences == 0:
            return 0.0
        return self._total_words / self._total_sentences

    def describe(self) -> str:
        """Return a human-readable style description."""
        if self.sample_count < 3:
            return "Not enough samples to describe style."
        lines = [
            f"Formality: {self.formality_label()}",
            f"Avg sentence length: {self.avg_sentence_length():.1f} words",
            f"Emoji usage: {'frequent' if self._emoji_count > self.sample_count * 0.3 else 'rare'}",
            f"Exclamation marks: {'heavy' if self._exclamation_count > self.sample_count else 'moderate'}",
            f"Ellipsis usage: {'yes' if self._ellipsis_count > 2 else 'no'}",
        ]
        if self._greetings:
            lines.append(f"Preferred greetings: {', '.join(self._greetings[:3])}")
        if self._question_starters:
            top_qs = sorted(self._question_starters, key=self._question_starters.get, reverse=True)
            lines.append(f"Favourite question starters: {', '.join(top_qs[:3])}")
        return " | ".join(lines)

    def as_prompt_instruction(self) -> str:
        """Return a prompt fragment instructing the LLM to match the user's style."""
        if self.sample_count < 3:
            return ""
        formality = self.formality_label()
        avg_len = self.avg_sentence_length()

        parts = []
        if formality == "casual":
            parts.append("Write in a casual, friendly tone.")
        elif formality == "formal":
            parts.append("Write in a professional, formal tone.")
        else:
            parts.append("Write in a clear, balanced tone.")

        if avg_len < 8:
            parts.append("Keep sentences short and punchy.")
        elif avg_len > 20:
            parts.append("You may use longer, detailed sentences.")

        if self._emoji_count > self.sample_count * 0.3:
            parts.append("Use occasional relevant emoji.")

        if self._exclamation_count > self.sample_count:
            parts.append("Match the user's energetic punctuation style.")

        return "  ".join(parts)

    def top_words(self, n: int = 10) -> List[Tuple[str, int]]:
        """Return the n most frequent non-stopword words."""
        STOPWORDS = {"the", "a", "an", "is", "it", "i", "to", "of",
                     "and", "in", "for", "on", "with", "this", "that",
                     "you", "me", "my", "your", "we", "be", "do", "can"}
        filtered = {w: c for w, c in self._word_freq.items() if w not in STOPWORDS}
        return sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:n]

    def export(self) -> Dict:
        return {
            "sample_count": self.sample_count,
            "formality": self.formality_label(),
            "avg_sentence_length": self.avg_sentence_length(),
            "emoji_count": self._emoji_count,
            "exclamation_count": self._exclamation_count,
            "ellipsis_count": self._ellipsis_count,
            "greetings": self._greetings,
            "top_words": self.top_words(20),
        }

    def import_stats(self, data: Dict):
        """Restore previously exported stats."""
        self._emoji_count = data.get("emoji_count", 0)
        self._exclamation_count = data.get("exclamation_count", 0)
        self._ellipsis_count = data.get("ellipsis_count", 0)
        self._greetings = data.get("greetings", [])
        self._total_words = int(data.get("avg_sentence_length", 10) * 10)
        self._total_sentences = 10


# ─────────────────────────────────────────────────────────────────────────────
#  TaskQueue  — priority dedup queue
# ─────────────────────────────────────────────────────────────────────────────


__all__=["ConversationMemory", "SpeechPatternBank"]
