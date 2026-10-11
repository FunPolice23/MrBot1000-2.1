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


__all__ = ["read_think_level", "split_thinking"]
