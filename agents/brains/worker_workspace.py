"""Workspace inspection helpers for legacy worker compatibility."""

from __future__ import annotations

from pathlib import Path


ROOT_FOLDER = str(Path(__file__).resolve().parents[2])
_CODEBASE_INDEX_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", "build", "dist", ".mypy_cache",
    ".hermes", "test_results", "github_upload", ".mrbot_backups",
    "work", ".github", "references", "skills", "scripts", "tests", "docs",
}


def project_file_tree(max_files: int = 200) -> str:
    """Return a grounded text tree of real project files."""
    try:
        lines = ["Project file tree (rooted at project root):"]
        count = 0
        root = Path(ROOT_FOLDER)
        for path in sorted(root.rglob("*")):
            try:
                parts = set(path.parts)
            except Exception:
                continue
            if any(part in _CODEBASE_INDEX_SKIP_DIRS for part in parts):
                continue
            if path.is_file() and path.suffix.lower() in {
                ".py", ".md", ".txt", ".json", ".yaml", ".yml"
            }:
                try:
                    relative = path.relative_to(root)
                except Exception:
                    continue
                lines.append(str(relative).replace("\\", "/"))
                count += 1
                if count >= max_files:
                    break
        return "\n".join(lines)
    except Exception as exc:
        return f"[file tree error] {exc}"


__all__ = ["project_file_tree"]
