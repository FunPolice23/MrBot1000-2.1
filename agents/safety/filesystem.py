"""Filesystem and research mixin for the legacy worker fa?ade."""

from __future__ import annotations

import datetime
import os
import shutil
from pathlib import Path

from agents.brains.base_worker import (
    BACKUP_DIRNAME, DEEP_READ_MAX_CHARS, MAX_FILE_SIZE,
    PROTECTED_SOURCE_FILES, RESEARCH_MAX_BYTES, RESEARCH_MAX_CHARS,
    RESEARCH_MAX_TOTAL_CHARS, ROOT_FOLDER, WRITE_EXCLUSION_DIRS,
    is_safe_filename, is_safe_mime, is_safe_path,
)


class WorkerFilesystemMixin:
    def safe_write_file(self, filename: str, content: str) -> bool:
        """Write a file safely inside ROOT_FOLDER only, with a pre-edit backup.

        2.0.19: backs up any existing target to ROOT_FOLDER/.mrbot_backups/
        before overwriting, and refuses protected/write-excluded directories.
        """
        if not is_safe_filename(filename):
            self.log_signal.emit(f"BLOCKED: filename '{filename}' is on blocklist")
            return False

        # Refuse to overwrite the app's own import-critical source files. The
        # Coder's full-file-rewrite path has repeatedly truncated these (e.g.
        # coder.py -> 0 bytes, action_pipeline.py -> 94 lines) via a bad LLM
        # rewrite; blocking here keeps the running app from being destroyed.
        # Matched by basename so absolute paths and nested copies are also blocked.
        _bn = Path(filename).name
        if _bn in PROTECTED_SOURCE_FILES:
            self.log_signal.emit(
                f"BLOCKED: protected app source '{_bn}' — refusing overwrite "
                f"(use an external editor for intentional dev changes)")
            return False

        root_resolved = Path(ROOT_FOLDER).resolve()
        # Accept absolute paths that live under root; otherwise treat as relative.
        candidate = Path(filename)
        full_path = (candidate if candidate.is_absolute()
                     else (root_resolved / filename)).resolve()

        # Write-excluded directories (VCS, venvs, caches, publish mirror, backups).
        rel_parts = full_path.relative_to(root_resolved).parts if str(full_path).startswith(str(root_resolved)) else ()
        if any(part in WRITE_EXCLUSION_DIRS for part in rel_parts):
            self.log_signal.emit(f"BLOCKED: write to protected dir '{'/'.join(rel_parts)}'")
            return False

        if not is_safe_path(root_resolved, full_path):
            self.log_signal.emit("BLOCKED: Write outside root folder or unsafe symlink")
            return False

        if len(content) > self.max_file_size:
            self.log_signal.emit(f"BLOCKED: File size exceeds {self.max_file_size // 1024 // 1024}MB")
            return False

        _, _, free = shutil.disk_usage(ROOT_FOLDER)
        if free < 100 * 1024 * 1024:
            self.log_signal.emit("BLOCKED: Free space < 100MB")
            return False

        # Backup-before-edit (2.0.19): keep a recoverable copy of the original.
        try:
            backup_root = root_resolved / BACKUP_DIRNAME
            backup_root.mkdir(parents=True, exist_ok=True)
            rel = full_path.relative_to(root_resolved)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_root / f"{rel}.{stamp}.bak"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            if full_path.exists():
                shutil.copy2(full_path, backup_path)
                self.log_signal.emit(f"Backed up -> {backup_path}")
        except Exception as e:
            self.log_signal.emit(f"Backup skipped: {e}")

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            self.log_signal.emit(f"Created safely: {filename}")
            return True
        except Exception as e:
            self.log_signal.emit(f"Write error: {e}")
            return False

    def restore_last_backup(self, filename: str) -> bool:
        """Restore the most recent .bak backup for `filename` (relative to root)."""
        root_resolved = Path(ROOT_FOLDER).resolve()
        rel = Path(filename)
        backup_root = root_resolved / BACKUP_DIRNAME
        prefix = str(rel).replace("\\", "/") + "."
        backups = []
        if backup_root.exists():
            for p in backup_root.iterdir():
                nm = p.name
                if nm.startswith(prefix) and nm.endswith(".bak"):
                    backups.append(p)
        if not backups:
            self.log_signal.emit(f"No backup found for '{filename}'")
            return False
        latest = max(backups, key=lambda p: p.stat().st_mtime)
        target = (root_resolved / rel).resolve()
        try:
            shutil.copy2(latest, target)
            self.log_signal.emit(f"Restored {target} from {latest}")
            return True
        except Exception as e:
            self.log_signal.emit(f"Restore failed: {e}")
            return False

    # ── Research Methods (used by Manager) ────────────────────────────────────

    def research_all(self) -> dict:
        """Scan ROOT_FOLDER (.py files) and user-selected research_folder."""
        root_parts = []
        try:
            # PERF: limit scan to first 30 .py files under root to avoid
            # blocking on large projects. Skip files > 50KB.
            count = 0
            for p in sorted(Path(ROOT_FOLDER).rglob("*.py")):
                if count >= 30:
                    break
                try:
                    size = p.stat().st_size
                    if size >= 50000:
                        continue
                    content = p.read_text(encoding="utf-8", errors="ignore")[:1200]
                    root_parts.append(f"[ROOT/{p.name}] ({size} bytes)\n{content}\n---")
                    count += 1
                except Exception:
                    pass
        except Exception as e:
            self.log_signal.emit(f"Error scanning root files: {e}")

        root_text = "\n".join(root_parts) if root_parts else "(no .py files found in root)"

        rf = self.research_folder
        research_text = ""
        research_file_count = 0
        research_files = []  # v2.0.24f: per-file records so the manager can bundle
                            # research by FILES (a numbered list per bundle) instead
                            # of by raw characters. Each: {"rel","content","chars"}.

        if not rf:
            research_text = "(research folder not set — select one via Management tab)"
        elif not Path(rf).exists():
            research_text = f"(path does not exist: {rf})"
        else:
            allowed_ext = {".py", ".txt", ".md", ".json", ".yaml", ".yml",
                           ".toml", ".cfg", ".ini", ".rst", ".csv"}
            research_parts = []
            skipped_large = []
            skipped_ext = []
            skipped_unsafe = []

            try:
                all_files = sorted(Path(rf).rglob("*"))
                total_chars = 0
                dropped_overflow = 0
                # PERF: cap research folder scan at 50 files to prevent
                # blocking on large directories.
                file_count = 0
                for p in all_files:
                    if file_count >= 50:
                        break
                    if not p.is_file():
                        continue

                    if not is_safe_filename(p.name):
                        skipped_unsafe.append(str(p.relative_to(rf)))
                        continue
                    if not is_safe_mime(p):
                        skipped_ext.append(str(p.relative_to(rf)))
                        continue
                    if p.suffix.lower() not in allowed_ext:
                        skipped_ext.append(str(p.relative_to(rf)))
                        continue

                    size = p.stat().st_size
                    if size >= RESEARCH_MAX_BYTES:
                        skipped_large.append(f"{p.relative_to(rf)} ({size // 1024}KB)")
                        continue

                    rel = p.relative_to(rf)
                    rel_path = rel.as_posix()

                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        display_content = content[:RESEARCH_MAX_CHARS]
                        piece = f"[{rel.as_posix()}] ({size} bytes)\n{display_content}\n---\n"
                        # v2.0.24d: enforce a TOTAL budget so a huge folder can't
                        # overflow the model context. Keep the first N files that
                        # fit; drop the rest (logged).
                        if RESEARCH_MAX_TOTAL_CHARS and total_chars + len(piece) > RESEARCH_MAX_TOTAL_CHARS:
                            dropped_overflow += 1
                            continue
                        research_parts.append(piece)
                        research_files.append({
                            "rel": rel.as_posix(),
                            "content": display_content,
                            "chars": len(display_content),
                        })
                        total_chars += len(piece)
                        research_file_count += 1
                        file_count += 1
                    except Exception as fe:
                        self.log_signal.emit(f"Skipped {p.name}: {fe}")

                if dropped_overflow:
                    self.log_signal.emit(
                        f"Research scan: dropped {dropped_overflow} file(s) over "
                        f"RESEARCH_MAX_TOTAL_CHARS={RESEARCH_MAX_TOTAL_CHARS} budget "
                        f"(increase it to include more)")

                if research_parts:
                    research_text = "\n".join(research_parts)
                    msg = f"Research scan: {research_file_count} file(s) from {rf}"
                    if skipped_unsafe:
                        msg += f" | skipped {len(skipped_unsafe)} unsafe file(s)"
                    if skipped_large:
                        msg += f" | skipped {len(skipped_large)} large file(s)"
                    if skipped_ext:
                        msg += f" | skipped {len(skipped_ext)} unsupported type(s)"
                    self.log_signal.emit(msg)
                else:
                    research_text = (
                        f"(no supported files found in {rf} — "
                        f"supported: {', '.join(sorted(allowed_ext))})"
                    )
                    self.log_signal.emit(f"Research scan: 0 files found in {rf}")
            except Exception as e:
                self.log_signal.emit(f"Error scanning research folder: {e}")

        return {
            "root": root_text,
            "research": research_text,
            "research_path": rf,
            "research_file_count": research_file_count,
            "research_files": research_files,
        }

    def file_index(self) -> str:
        """Return a compact index of all files in the research folder."""
        rf = self.research_folder
        if not rf or not Path(rf).exists():
            return f"(research folder not set or does not exist: {rf})"

        allowed_ext = {".py", ".txt", ".md", ".json", ".yaml", ".yml",
                       ".toml", ".cfg", ".ini", ".rst", ".csv"}
        lines = [f"Research folder: {rf}", "Files (relative path, size):"]
        count = 0
        try:
            for p in sorted(Path(rf).rglob("*")):
                if not p.is_file():
                    continue
                if not is_safe_filename(p.name):
                    continue
                if p.suffix.lower() not in allowed_ext:
                    continue
                try:
                    size = p.stat().st_size
                    rel_path = p.relative_to(rf).as_posix()
                    lines.append(f"{rel_path} ({size} bytes)")
                    count += 1
                except Exception:
                    pass
        except Exception as e:
            self.log_signal.emit(f"Error indexing research folder: {e}")

        return "\n".join(lines) + f"\n\nTotal: {count} files"

    def read_specific_files(self, filenames: list, base_path: str = None) -> str:
        """Read full content of specific files by relative path."""
        base = Path(base_path or self.research_folder or ROOT_FOLDER).resolve()
        parts = []
        folder_path = str(base)

        for name in filenames:
            if not is_safe_filename(name):
                self.log_signal.emit(f"BLOCKED read of unsafe name: {name}")
                continue

            p = (base / name).resolve()
            if not is_safe_path(base, p):
                self.log_signal.emit(f"BLOCKED read outside base: {name}")
                continue

            if not p.exists():
                self.log_signal.emit(f"File not found: {name}")
                parts.append(f"[{name}] ERROR: file not found\n---")
                continue

            if not is_safe_mime(p):
                self.log_signal.emit(f"BLOCKED read of unsafe mime type: {name}")
                continue

            try:
                size = p.stat().st_size
                content = p.read_text(encoding="utf-8", errors="ignore")
                display_content = content[:DEEP_READ_MAX_CHARS]
                parts.append(f"[{name}] ({size} bytes)\n{display_content}\n---")
            except Exception as e:
                parts.append(f"[{name}] ERROR: {e}\n---")

        return "\n".join(parts) if parts else "(no files read)"

    # ── State Management ─────────────────────────────────────────────────────

    def set_research_folder(self, path: str):
        """Set the research folder path."""
        self.research_folder = path

    def stop(self):
        """Signal the worker to stop running."""
        self._running = False

    def is_running(self) -> bool:
        """Check if the worker is still running."""
        return self._running



__all__=["WorkerFilesystemMixin"]
