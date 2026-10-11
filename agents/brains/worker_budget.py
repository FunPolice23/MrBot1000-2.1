"""Context-window lookup for the legacy worker compatibility layer."""

from __future__ import annotations

import os
import re
import shutil
import subprocess


def model_context_tokens(
    model: str,
    *,
    ollama_available: bool,
    cache: dict[str, int],
) -> int:
    """Return a model context length with bounded Ollama probing and fallback."""
    if not model:
        return max(1024, int(os.getenv("MAIN_CONTEXT_TOKENS", 128000)))
    if model in cache:
        return cache[model]
    if not ollama_available or not shutil.which("ollama"):
        fallback = max(1024, int(os.getenv("MAIN_CONTEXT_TOKENS", 128000)))
        cache[model] = fallback
        return fallback
    env_override = os.getenv("MAIN_CONTEXT_TOKENS", "").strip()
    try:
        output = subprocess.run(
            ["ollama", "show", model],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        match = re.search(r"context length\s+(\d+)", output)
        if match:
            context = max(1024, int(match.group(1)))
            cache[model] = context
            return context
    except (OSError, subprocess.SubprocessError):
        pass
    fallback = max(1024, int(env_override)) if env_override else 128000
    cache[model] = fallback
    return fallback


__all__ = ["model_context_tokens"]
