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
    def _blocked_signal(self, message: str) -> bool:
        """Emit the operator BLOCKED signal AND the typed safety_event.

        ARCH-ENG-243 (BD-01): every `safe_write_file` refusal USE to emit
        only the mix-in's log signal, so the Insights panel's "Safety
        incidents" counter (which reads typed `safety` events) never saw
        the write gate's blocks. One helper now reports both; the emission
        is AFTER the refusal is decided and guarded, so telemetry can never
        alter or break the gate.

        Returns False so block sites read `return self._blocked_signal(...)`.
        """
        self.log_signal.emit(message)
        try:
            from agents.core.event_logger import StructuredEventLogger
            StructuredEventLogger.instance().safety_event(
                gate_type="filesystem_write", blocked=True,
                description=message)
        except Exception:
            pass
        return False

    def safe_write_file(self, filename: str, content: str) -> bool:
        """Write a file safely inside ROOT_FOLDER only, with a pre-edit backup.

        2.0.19: backs up any existing target to ROOT_FOLDER/.mrbot_backups/
        before overwriting, and refuses protected/write-excluded directories.
        """
        if not is_safe_filename(filename):
            return self._blocked_signal(
                f"BLOCKED: filename '{filename}' is on blocklist")

        # Refuse to overwrite the app's own import-critical source files. The
        # Coder's full-file-rewrite path has repeatedly truncated these (e.g.
        # coder.py -> 0 bytes, action_pipeline.py -> 94 lines) via a bad LLM
        # rewrite; blocking here keeps the running app from being destroyed.
        # Matched by basename so absolute paths and nested copies are also blocked.
        _bn = Path(filename).name
        if _bn in PROTECTED_SOURCE_FILES:
            return self._blocked_signal(
                f"BLOCKED: protected app source '{_bn}' — refusing overwrite "
                f"(use an external editor for intentional dev changes)")

        root_resolved = Path(ROOT_FOLDER).resolve()
        # Accept absolute paths that live under root; otherwise treat as relative.
        candidate = Path(filename)
        full_path = (candidate if candidate.is_absolute()
                     else (root_resolved / filename)).resolve()

        # Write-excluded directories (VCS, venvs, caches, publish mirror, backups).
        rel_parts = full_path.relative_to(root_resolved).parts if str(full_path).startswith(str(root_resolved)) else ()
        if any(part in WRITE_EXCLUSION_DIRS for part in rel_parts):
            return self._blocked_signal(
                f"BLOCKED: write to protected dir '{'/'.join(rel_parts)}'")

        if not is_safe_path(root_resolved, full_path):
            return self._blocked_signal(
                "BLOCKED: Write outside root folder or unsafe symlink")

        if len(content) > self.max_file_size:
            return self._blocked_signal(
                f"BLOCKED: File size exceeds {self.max_file_size // 1024 // 1024}MB")

        _, _, free = shutil.disk_usage(ROOT_FOLDER)
        if free < 100 * 1024 * 1024:
            return self._blocked_signal("BLOCKED: Free space < 100MB")

        # Backup-before-edit (2.0.19): keep a recoverable copy of the original.
        #
        # ARCH-ENG-204: A FAILED BACKUP NOW BLOCKS THE WRITE.
        #
        # This used to log "Backup skipped: {e}" and fall through to the write.
        # So any transient failure -- a full disk, a locked file, a permissions
        # problem, a path too long for the timestamped name -- silently degraded
        # the guarantee from "a recoverable copy exists before we overwrite" to
        # "we tried, and if that did not work we overwrote anyway".
        #
        # That is the worst possible shape for a safety mechanism, because it
        # reports success. `safe_write_file` returned True, the caller logged
        # "Created safely", and the only record that no backup existed was a log
        # line most callers never surface. An agent rewriting source would
        # destroy the file with nothing to restore from, while every indicator
        # said it was fine.
        #
        # The contract is now the one the operator asked for: NO EDIT WITHOUT A
        # BACKUP. A new file has nothing to back up, so it is not a backup
        # failure -- only an existing target that cannot be copied is.
        try:
            backup_root = root_resolved / BACKUP_DIRNAME
            backup_root.mkdir(parents=True, exist_ok=True)
            rel = full_path.relative_to(root_resolved)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_root / f"{rel}.{stamp}.bak"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            if full_path.exists():
                shutil.copy2(full_path, backup_path)
                # Confirm the copy is actually usable. A truncated or empty
                # backup is not a backup, and would restore the file to nothing.
                if not backup_path.exists() or backup_path.stat().st_size == 0:
                    return self._blocked_signal(
                        f"BLOCKED: backup of '{filename}' is unusable "
                        f"(missing or zero bytes) — refusing to overwrite")
                self.log_signal.emit(f"Backed up -> {backup_path}")
        except Exception as e:
            return self._blocked_signal(
                f"BLOCKED: could not back up '{filename}' ({e}) — "
                f"refusing to overwrite without a recoverable copy")

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

    def _cached_read(self, folder_path: str, relative_path: str, path: Path,
                     size: int, mtime: float) -> str:
        """Read a file through ``file_cache`` (ARCH-ENG-271, AF-02).

        The ``file_cache`` table has been READ by the DB-Stats panel and
        CLEARED by a live "Clear file cache" button since the beginning, but
        nothing ever wrote it -- so the counter was permanently 0 and the
        button cleared nothing. Every research read now goes through it,
        mtime-validated: an unchanged file is served from the cache, an edited
        one is re-read and re-saved.

        Cache failures always degrade to a direct read. A cache must never be
        able to break research.
        """
        db = getattr(self, "db", None)
        if db is not None:
            try:
                cached = db.get_cached_file(
                    folder_path, relative_path, current_mtime=mtime)
                if cached is not None:
                    return cached
            except Exception:
                pass
        content = path.read_text(encoding="utf-8", errors="ignore")
        if db is not None:
            try:
                db.save_file_to_cache(
                    folder_path, relative_path, content, size, mtime)
            except Exception:
                pass
        return content

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
                    st = p.stat()
                    size = st.st_size
                    if size >= 50000:
                        continue
                    rel_root = p.relative_to(ROOT_FOLDER).as_posix()
                    content = self._cached_read(
                        str(ROOT_FOLDER), rel_root, p, size, st.st_mtime)[:1200]
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

                    st = p.stat()
                    size = st.st_size
                    mtime = st.st_mtime
                    if size >= RESEARCH_MAX_BYTES:
                        skipped_large.append(f"{p.relative_to(rf)} ({size // 1024}KB)")
                        continue

                    rel = p.relative_to(rf)
                    rel_path = rel.as_posix()

                    try:
                        content = self._cached_read(
                            str(rf), rel_path, p, size, mtime)
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

        payload = {
            "root": root_text,
            "research": research_text,
            "research_path": rf,
            "research_file_count": research_file_count,
            "research_files": research_files,
        }

        # ARCH-ENG-272 (AF-03): persist the snapshot. `research_cache` had a
        # reader (`load_latest_research_cache`) and a live DB-Stats counter but
        # no writer, so the counter and the "last good snapshot" fallback were
        # both permanently empty. Save first, then publish the compact snapshot
        # that `chat_router` already looks for -- until now nothing called
        # `update_research_snapshot`, so the dialogue's research context always
        # read "(not set)".
        db = getattr(self, "db", None)
        if db is not None:
            try:
                db.save_research_cache(payload)
            except Exception as exc:
                self.log_signal.emit(f"Research snapshot not cached: {exc}")
        try:
            from agents.brains.shared_context import get_shared_context
            get_shared_context().update_research_snapshot(payload)
        except Exception as exc:
            self.log_signal.emit(f"Research snapshot not shared: {exc}")

        return payload

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
                st = p.stat()
                size = st.st_size
                content = self._cached_read(
                    folder_path, name, p, size, st.st_mtime)
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
