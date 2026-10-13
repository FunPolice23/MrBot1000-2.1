"""Thinking-response helpers for the legacy worker compatibility layer."""

from __future__ import annotations


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def split_thinking(content: str):
    """Return ``(thinking, answer)`` from a model response."""
    if not content or _THINK_OPEN not in content:
        return "", content or ""
    start = content.index(_THINK_OPEN) + len(_THINK_OPEN)
    close_idx = content.find(_THINK_CLOSE, start)
    if close_idx == -1:
        return content[start:], ""
    return (
        content[start:close_idx].strip(),
        content[close_idx + len(_THINK_CLOSE):].strip(),
    )


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
    "model_emits_reasoning", "record_model_reasoning",
]
