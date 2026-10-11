"""Filesystem and content safety helpers for legacy workers."""

from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path


FILENAME_BLOCKLIST = {
    "config.yaml", "config.yml", ".env", "credentials.json",
    "id_rsa", "id_dsa", ".gitconfig", ".bashrc", ".zshrc",
    "passwd", "shadow", "sudoers", "hosts", "secure",
}
BLOCKED_MIME_TYPES = {
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-object",
    "application/x-dosexec",
}


def is_safe_path(base: Path, candidate: Path) -> bool:
    """Ensure a candidate stays under base and cannot escape via a symlink."""
    try:
        candidate = candidate.resolve()
        base = base.resolve()
        if not candidate.is_relative_to(base):
            return False
        if candidate.is_symlink():
            return candidate.resolve().is_relative_to(base)
        return True
    except (AttributeError, OSError, RuntimeError):
        try:
            candidate = candidate.resolve()
            base = base.resolve()
            if not str(candidate).startswith(str(base)):
                return False
            return not candidate.is_symlink() or str(
                candidate.resolve()).startswith(str(base))
        except (OSError, RuntimeError):
            return False


def is_safe_filename(name: str) -> bool:
    lower = name.lower()
    return not any(bad in lower or lower.endswith(bad)
                   for bad in FILENAME_BLOCKLIST)


def is_safe_mime(file_path: Path) -> bool:
    mime, _ = mimetypes.guess_type(str(file_path))
    return not (mime and mime in BLOCKED_MIME_TYPES)


def fingerprint(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()[:16]


def ts_now() -> str:
    return datetime.now().isoformat()


__all__ = [
    "BLOCKED_MIME_TYPES",
    "FILENAME_BLOCKLIST",
    "fingerprint",
    "is_safe_filename",
    "is_safe_mime",
    "is_safe_path",
    "ts_now",
]
