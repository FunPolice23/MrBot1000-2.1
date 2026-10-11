"""Compatibility import for :mod:`agents.safety.policy`."""

from agents.safety.policy import (
    PROJECT_ROOT,
    command_argv,
    resolve_command_cwd,
    resolve_project_path,
)

__all__ = [
    "PROJECT_ROOT",
    "command_argv",
    "resolve_command_cwd",
    "resolve_project_path",
]
