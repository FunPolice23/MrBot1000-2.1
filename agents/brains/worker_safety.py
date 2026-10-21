"""Filesystem and content safety helpers for legacy workers."""

from __future__ import annotations

import hashlib
import mimetypes
import os
from datetime import datetime
from pathlib import Path


# ── ARCH-ENG-202: THE ENFORCED FLOOR ────────────────────────────────────────
#
# These two sets are the hardcoded baseline that was defined here before. They
# are now named explicitly as the FLOOR: the minimum that is always enforced,
# and which configuration cannot switch off.
#
# WHY A FLOOR RATHER THAN A PLAIN SETTING
#
# `FILENAME_BLOCKLIST` is editable in the Settings screen and persisted to
# `.env`. Without a floor, the setting would be *absolute*: deleting one entry
# from that text box would un-block that filename, for every worker, silently.
# That is the wrong shape for a safety control -- it makes the security posture
# depend on a comma-separated string being edited correctly, with no indication
# that the edit did anything.
#
# It is not hypothetical. `.env` line 141 already reads
#     FILENAME_BLOCKLIST=config.yaml,.env,credentials.json,id_rsa
# four entries, written by the GUI's own short default. Ten protected filenames
# -- `passwd`, `shadow`, `sudoers`, `id_dsa`, `hosts`, `.bashrc`, `.zshrc`,
# `.gitconfig`, `secure`, `config.yml` -- are absent. That line was inert while
# nothing read it; the moment the setting went live without a floor it would
# have quietly dropped enforcement from 14 entries to 4.
#
# So: the operator's list is an ADDITIVE extension. `os.environ` can add to the
# floor, never subtract from it. Blocking more is always allowed; blocking less
# is not reachable through configuration at all.
#
# The floor is also the fail-secure default. If `.env` is missing, unreadable,
# or loaded after this module, the floor still applies -- the worst case is that
# an operator's additions are not picked up until `refresh_from_env()` runs,
# which is over-blocking, never under-blocking.

FILENAME_BLOCKLIST_FLOOR = frozenset({
    "config.yaml", "config.yml", ".env", "credentials.json",
    "id_rsa", "id_dsa", ".gitconfig", ".bashrc", ".zshrc",
    "passwd", "shadow", "sudoers", "hosts", "secure",
})

BLOCKED_MIME_TYPES_FLOOR = frozenset({
    "application/x-executable",
    "application/x-sharedlib",
    "application/x-object",
    "application/x-dosexec",
})


def _parse_additions(raw: str | None) -> set[str]:
    """Split a comma-separated settings value into normalised entries."""
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _apply_floor(floor: frozenset[str], raw: str | None) -> set[str]:
    """Floor plus operator additions. Subtractions are structurally impossible."""
    return set(floor) | _parse_additions(raw)


FILENAME_BLOCKLIST = _apply_floor(
    FILENAME_BLOCKLIST_FLOOR, os.getenv("FILENAME_BLOCKLIST"))
BLOCKED_MIME_TYPES = _apply_floor(
    BLOCKED_MIME_TYPES_FLOOR, os.getenv("BLOCKED_MIME_TYPES"))


def refresh_from_env() -> None:
    """Recompute the effective sets after `.env` is loaded or reloaded.

    Module import may happen before `load_dotenv()` (main.py does it at line
    218, but a worker can be constructed by a test or a script that never
    imports main). Without this the operator's additions would be silently
    ignored -- over-blocking, so not a safety hole, but still wrong.

    MUTATES IN PLACE rather than rebinding the module global. This is
    deliberate and was a bug in the first version of this function: `base_worker`
    does `from ...worker_safety import FILENAME_BLOCKLIST`, which binds the
    object by value. Rebinding the global here would update enforcement (which
    reads the module global at call time) while leaving every existing importer
    pointing at the stale set -- so the name a caller sees and the set actually
    enforced would silently disagree, which is the exact failure mode
    ARCH-ENG-201 was filed for. Mutating keeps one object and one truth.
    """
    FILENAME_BLOCKLIST.clear()
    FILENAME_BLOCKLIST.update(_apply_floor(
        FILENAME_BLOCKLIST_FLOOR, os.getenv("FILENAME_BLOCKLIST")))
    BLOCKED_MIME_TYPES.clear()
    BLOCKED_MIME_TYPES.update(_apply_floor(
        BLOCKED_MIME_TYPES_FLOOR, os.getenv("BLOCKED_MIME_TYPES")))


def effective_blocklist_text() -> str:
    """What is ACTUALLY blocked, as the Settings screen should display it.

    The GUI used to show its own hardcoded four-entry default while the runtime
    enforced fourteen, so the screen understated the protection by ten files.
    Reading the real effective set is the only way the displayed value can be
    trusted to describe the enforced one.
    """
    return ",".join(sorted(FILENAME_BLOCKLIST))


def effective_mime_text() -> str:
    return ",".join(sorted(BLOCKED_MIME_TYPES))


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
    "BLOCKED_MIME_TYPES_FLOOR",
    "FILENAME_BLOCKLIST",
    "FILENAME_BLOCKLIST_FLOOR",
    "effective_blocklist_text",
    "effective_mime_text",
    "fingerprint",
    "is_safe_filename",
    "is_safe_mime",
    "is_safe_path",
    "refresh_from_env",
    "ts_now",
]
