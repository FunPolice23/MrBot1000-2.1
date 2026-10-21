"""Thinking-response helpers for the legacy worker compatibility layer."""

from __future__ import annotations

import os
import re

# BE-01 (ARCH-ENG-239): THE one matcher for thinking-marker blocks. Four live
# implementations of this match existed with DIFFERENT case rules:
# agents/safety/response.py:173 matched case-insensitively (the main dialogue
# path), response.py's profile branch, chat_tab.py's pattern 3 and this
# module's split_thinking matched lowercase only. A model emitting `<THINK>`
# or `<Think>` had its private reasoning stripped on one path and printed to
# the operator on the others. Every strip/split of think blocks goes through
# this compiled matcher now; the policies that legitimately differ between
# paths (split-vs-strip, unclosed-block handling) are separate from the
# MATCH, which must never differ.
_THINK_BLOCK_RE = re.compile(r"<think>(.*?)</think>", re.IGNORECASE | re.DOTALL)


def strip_think_blocks(text: str) -> str:
    """Remove every closed think block, case-insensitively, from visible text."""
    if not text:
        return ""
    return _THINK_BLOCK_RE.sub("", text).strip()


def split_think_blocks(content: str):
    """Return ``(thinking, answer)`` for CLOSED think blocks.

    The thinking of the first block, with every block removed from the
    answer; ``("", content)`` when no closed block exists. An UNCLOSED block
    is an in-progress stream, not a verdict -- for that policy the legacy
    :func:`split_thinking` remains the contract to call.
    """
    if not content:
        return "", content or ""
    match = _THINK_BLOCK_RE.search(content)
    if match:
        return (
            match.group(1).strip(),
            _THINK_BLOCK_RE.sub("", content).strip(),
        )
    return "", content


_THINK_OPEN_RE = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</think>", re.IGNORECASE)


def split_thinking(content: str):
    """Return ``(thinking, answer)`` from a model response.

    BE-01 (ARCH-ENG-239): the match now goes through the shared canonical
    matcher, so a `<THINK>`/`<Think>` marker splits the same way a lowercase
    one always did. The legacy unclosed-block policy below is deliberately
    PRESERVED: an unclosed block is treated as an in-progress stream (all
    considerate content retained as `thinking`, empty answer) -- changing
    that policy is not what this fix is about.
    """
    if not content:
        return "", content or ""
    match = _THINK_BLOCK_RE.search(content)
    if match:
        return (
            match.group(1).strip(),
            _THINK_BLOCK_RE.sub("", content).strip(),
        )
    # Legacy policy, preserved: an UNCLOSED block -- everything after the
    # opener (if any) counts as thinking, and the answer is empty, so a
    # half-streamed block never leaks into what the operator sees as the
    # answer.
    open_match = _THINK_OPEN_RE.search(content)
    if open_match:
        start = open_match.end()
        close = _THINK_CLOSE_RE.search(content, start)
        if close is None:
            return content[start:].strip(), ""
    return "", content


def read_think_level(chat: bool) -> str:
    import os
    key = "THINK_LEVEL" if chat else "MAIN_THINK_LEVEL"
    return os.getenv(key, os.getenv("THINK_LEVEL", "med")).strip().lower() or "med"


# Models that emit a hidden reasoning channel (a separate ``reasoning_content``
# field or a thinking template) before the visible answer. This is NAME-based
# only as a fallback; the authoritative signal is the runtime ``reasoning_content``
# field a provider returns, which ``record_model_reasoning`` latches on.
_REASONING_NAME_HINTS = (
    "qwen", "deepseek", "nemotron", "thinking", "bonsai", "r1", "reason",
    "glm", "magistral", "ministral", "phi-4-reasoning", "qwq",
)


def model_emits_reasoning(model_name: str) -> bool:
    """Heuristic: does *model_name* look like a reasoning/thinking model?

    v2.1.51 (ARCH-ENG-051): generic, name-agnostic-ish detection so the dialogue
    token budget can give thinking headroom to ANY reasoning model (e.g. a 27B
    Bonsai on the CPU brain), not just a hardcoded few. When a live provider has
    already been seen emitting a ``reasoning_content`` field, that is the
    authoritative signal and is consulted via ``record_model_reasoning``.
    """
    name = str(model_name or "").lower()
    if not name:
        return False
    # Authoritative runtime signal first (set once a provider emits reasoning).
    try:
        from agents.brains.worker_thinking import _RUNTIME_REASONING_MODELS
        if any(tag in name for tag in _RUNTIME_REASONING_MODELS):
            return True
    except Exception:
        pass
    return any(hint in name for hint in _REASONING_NAME_HINTS)


# Populated at runtime when a provider response carries a non-empty
# ``reasoning_content`` / thinking channel for a given model. Lets budget sizing
# learn a reasoning model the name heuristic would miss.
_RUNTIME_REASONING_MODELS: set = set()


def record_model_reasoning(model_name: str) -> None:
    """Remember that *model_name* emitted a reasoning channel at runtime."""
    tag = str(model_name or "").lower()
    if tag:
        _RUNTIME_REASONING_MODELS.add(tag)


__all__ = [
    "read_think_level", "split_thinking",
    "strip_think_blocks", "split_think_blocks",  # BE-01 (ARCH-ENG-239) canonical matchers
    "model_emits_reasoning", "record_model_reasoning",
]
