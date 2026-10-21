"""Static architecture-boundary checks and legacy usage evidence."""

from __future__ import annotations

import ast
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class BoundaryViolation:
    path: str
    line: int
    imported: str
    boundary: str


def _imported_names(tree: ast.AST) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, node.lineno


def check_import_boundaries(
    root: str | Path,
    files: Iterable[str],
    forbidden: dict[str, tuple[str, ...]],
) -> list[BoundaryViolation]:
    """Return forbidden imports for files relative to ``root``.

    ``forbidden`` maps a relative file path to import prefixes that are not
    allowed in that architectural layer.
    """
    root_path = Path(root).resolve()
    violations: list[BoundaryViolation] = []
    for relative in files:
        path = root_path / relative
        prefixes = forbidden.get(relative, ())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported, line in _imported_names(tree):
            for prefix in prefixes:
                if imported == prefix or imported.startswith(prefix + "."):
                    violations.append(BoundaryViolation(
                        relative, line, imported, prefix))
    return violations


class UsageLedger:
    """Thread-safe in-memory evidence for compatibility-path usage."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def record(self, path: str) -> None:
        with self._lock:
            self._counts[path] = self._counts.get(path, 0) + 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def unused(self, paths: Iterable[str]) -> list[str]:
        snapshot = self.snapshot()
        return [path for path in paths if snapshot.get(path, 0) == 0]


usage_ledger = UsageLedger()


__all__ = [
    "BoundaryViolation",
    "UsageLedger",
    "check_import_boundaries",
    "usage_ledger",
]
