"""Guarded environment-file persistence for the application layer."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


_PROTECTED_NONEMPTY_KEYS = {"BIG_BRAIN_MODEL", "SMALL_BRAIN_MODEL"}


def _read_env_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().splitlines()
    except Exception:
        return []


class EnvWriteRefused(RuntimeError):
    """Raised when a `.env` write is refused by test isolation policy."""


def env_file_path() -> Path:
    """Return the live `.env` path, honoring the test isolation override."""
    override = (os.getenv("MRBOT_ENV_PATH") or "").strip()
    return Path(override) if override else Path(".env")


def clean_env_value(value: str) -> str:
    """Return an env value with any trailing inline comment removed.

    A `.env` line whose value is EMPTY and which is followed by a comment
    (``CASHAPP_TAG=   # Your Cash App $tag``) is parsed by python-dotenv with the
    COMMENT as the value — the inline-comment strip only applies when a real
    value precedes the ``#``. That silently turned documentation into data:
    the Nous API key became the literal string ``# Optional: Your Nous Research
    API key`` and every request 401'd, and payout/endpoint settings inherited
    the same corruption.

    Only an unquoted value may have its comment stripped; a quoted value keeps
    its content verbatim so a ``#`` inside a real secret is never truncated.
    """
    if value is None:
        return ""
    text = str(value)
    stripped = text.strip()
    if not stripped:
        return ""
    # A value that is entirely a comment is not a value at all.
    if stripped.startswith("#"):
        return ""
    if stripped[0] in ("'", '"'):
        return stripped
    # Drop a trailing inline comment only when preceded by whitespace, matching
    # dotenv's own rule for non-empty values.
    for marker in (" #", "\t#"):
        idx = stripped.find(marker)
        if idx != -1:
            stripped = stripped[:idx]
    return stripped.strip()


def _env_write_refusal() -> str:
    """Return a refusal reason, or an empty string when writes are allowed."""
    if "pytest" in sys.modules and not (os.getenv("MRBOT_ENV_PATH") or "").strip():
        return (
            "refusing to write .env during a test run; set MRBOT_ENV_PATH to a "
            "temporary path to exercise persistence"
        )
    return ""


def set_env_values(values: dict, *, path: Optional[Path] = None) -> bool:
    """Persist values atomically while preserving unknown keys and comments."""
    refusal = _env_write_refusal()
    if refusal:
        raise EnvWriteRefused(refusal)

    env = path or env_file_path()
    lines = _read_env_lines(env)
    keys = {key: (str(value) if value is not None else "")
            for key, value in values.items()}
    # Refuse to persist a value that is really a comment. This is what turned
    # the Nous key into the literal string "# Optional: Your Nous Research API
    # key" (every request then 401'd). An empty value is correct here; a
    # comment is a bug upstream, so drop it rather than bake it in.
    for key in list(keys):
        cleaned = clean_env_value(keys[key])
        if cleaned != keys[key]:
            keys[key] = cleaned
    for key in [
        key for key in keys
        if key in _PROTECTED_NONEMPTY_KEYS and not keys[key].strip()
    ]:
        del keys[key]
    if not keys:
        return False

    output = []
    covered = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            output.append(line)
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in keys:
                covered.add(key)
                output.append(f"{key}={keys[key]}")
                continue
        output.append(line)
    for key, value in keys.items():
        if key not in covered:
            output.append(f"{key}={value}")

    data = "\n".join(output) + ("\n" if output else "")
    for attempt in range(5):
        temporary_path = None
        try:
            fd, temporary_path = tempfile.mkstemp(
                dir=str(env.parent), prefix=".env.tmp_")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, env)
            return True
        except (PermissionError, OSError):
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except Exception:
                    pass
            if attempt == 4:
                raise
            time.sleep(0.15 * (attempt + 1))
        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.unlink(temporary_path)
                except Exception:
                    pass

    return False


__all__ = [
    "EnvWriteRefused",
    "env_file_path",
    "set_env_values",
]
