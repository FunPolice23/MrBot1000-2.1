"""Prompt construction and structured response helpers."""

from __future__ import annotations

import json
import re
from typing import Dict, List, Tuple


class ChainOfThought:
    """
    Accumulate reasoning steps and render them into a single prompt section.

    Usage::

        cot = ChainOfThought()
        cot.step("Identify the problem", "File X has no error handling.")
        cot.step("Propose solution", "Wrap the call in try/except.")
        prompt_section = cot.render()
    """

    def __init__(self):
        self._steps: List[Tuple[str, str]] = []

    def step(self, label: str, content: str) -> "ChainOfThought":
        self._steps.append((label, content))
        return self

    def render(self, numbered: bool = True) -> str:
        parts = []
        for i, (label, content) in enumerate(self._steps, 1):
            prefix = f"{i}. " if numbered else "• "
            parts.append(f"{prefix}**{label}**: {content}")
        return "\n".join(parts)

    def clear(self):
        self._steps.clear()

    def __len__(self):
        return len(self._steps)


# ─────────────────────────────────────────────────────────────────────────────
#  PromptBuilder  — fluent prompt construction
# ─────────────────────────────────────────────────────────────────────────────
class PromptBuilder:
    """
    Fluent helper for building structured prompts.

    Usage::

        prompt = (PromptBuilder()
                  .role("Python expert")
                  .context("File summary: ...")
                  .instruction("Find all bugs")
                  .constraint("Max 200 words")
                  .build())
    """

    def __init__(self):
        self._sections: List[Tuple[str, str]] = []

    def role(self, description: str) -> "PromptBuilder":
        self._sections.append(("ROLE", description))
        return self

    def context(self, text: str, label: str = "CONTEXT") -> "PromptBuilder":
        self._sections.append((label, text))
        return self

    def instruction(self, text: str) -> "PromptBuilder":
        self._sections.append(("INSTRUCTION", text))
        return self

    def constraint(self, text: str) -> "PromptBuilder":
        self._sections.append(("CONSTRAINT", text))
        return self

    def example(self, text: str) -> "PromptBuilder":
        self._sections.append(("EXAMPLE", text))
        return self

    def raw(self, text: str) -> "PromptBuilder":
        self._sections.append(("", text))
        return self

    def build(self, separator: str = "\n\n") -> str:
        parts = []
        for label, content in self._sections:
            if label:
                parts.append(f"[{label}]\n{content}")
            else:
                parts.append(content)
        return separator.join(parts)

    def build_system(self) -> str:
        """Return only ROLE + CONSTRAINT lines — suitable as system prompt."""
        parts = []
        for label, content in self._sections:
            if label in ("ROLE", "CONSTRAINT"):
                parts.append(content)
        return "  ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
#  ResponseParser  — extract structured fields from LLM text
# ─────────────────────────────────────────────────────────────────────────────
class ResponseParser:
    """
    Parse key:value fields and JSON blocks from LLM responses.

    Usage::

        parser = ResponseParser(raw_text)
        action = parser.field("ACTION")
        files  = parser.json_list()
    """

    def __init__(self, text: str):
        self.text = text or ""

    def field(self, key: str, default: str = "") -> str:
        """Extract 'KEY: value' from the text (case-insensitive)."""
        pattern = rf"(?i){re.escape(key)}\s*:\s*(.+)"
        m = re.search(pattern, self.text)
        return m.group(1).strip() if m else default

    def json_list(self) -> List[str]:
        """Extract the first JSON array found in the text."""
        m = re.search(r"\[.*?\]", self.text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        return []

    def json_object(self) -> Dict:
        """Extract the first JSON object found in the text."""
        m = re.search(r"\{.*?\}", self.text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        return {}

    def has_keyword(self, *keywords: str) -> bool:
        lower = self.text.lower()
        return any(kw.lower() in lower for kw in keywords)

    def classify(self, options: Dict[str, List[str]], default: str = "unknown") -> str:
        """
        Classify response by counting keyword matches per option.
        options = {"action": ["fix","improve"], "question": ["what","how"]}
        """
        lower = self.text.lower()
        scores = {opt: sum(1 for kw in kws if kw in lower)
                  for opt, kws in options.items()}
        best_score = max(scores.values())
        if best_score == 0:
            return default
        return max(scores, key=scores.get)


# ─────────────────────────────────────────────────────────────────────────────
#  ConversationMemory  — rolling context with character budget
# ─────────────────────────────────────────────────────────────────────────────


__all__=["ChainOfThought", "PromptBuilder", "ResponseParser"]
