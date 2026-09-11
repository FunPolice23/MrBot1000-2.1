"""Shared safety policy for model-invoked local tools."""

from __future__ import annotations

import re
import shlex
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
_SHELL_OPERATORS = re.compile(r"[&|<>;`\n\r]")


def resolve_project_path(raw_path: str, *, allow_missing: bool = False) -> Path:
    """Resolve a tool path and require it to remain inside the project root."""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("path is outside the project workspace") from exc
    if not allow_missing and not resolved.exists():
        raise FileNotFoundError(raw_path)
    return resolved


def command_argv(command: str) -> list[str]:
    """Parse a command without invoking a shell or shell metacharacters."""
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    if _SHELL_OPERATORS.search(command) or "$(" in command:
        raise ValueError("shell operators are not allowed")
    try:
        argv = shlex.split(command, posix=False)
    except ValueError as exc:
        raise ValueError("command could not be parsed safely") from exc
    if not argv:
        raise ValueError("command must contain an executable")
    return argv


def resolve_command_cwd(raw_cwd: str | None) -> Path:
    """Resolve an optional command working directory inside the workspace."""
    return resolve_project_path(raw_cwd or ".")