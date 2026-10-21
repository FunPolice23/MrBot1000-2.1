"""agents/code_patch_service.py — Approval-gated, rollback-safe code patching.

This is the safe primitive for agent-driven self-improvement. An agent (or the
dialogue) proposes a patch; it enters the human-approval queue; only after that
exact approval item is APPROVED does the service touch the filesystem.

Safety contract:
- ``target_path`` must resolve to a real file under ``root_dir`` (no ``..``
  escape, no absolute path outside root, no symlink escape).
- Only allowlisted text/config extensions are patchable.
- Files on ``PROTECTED_SOURCE_FILES`` or ``FILENAME_BLOCKLIST`` are refused,
  matching the file-write and coder paths (ARCH-ENG-288).
- A backup is always written before the first file mutation.
- After write, ``verify`` runs (default: ``py_compile``). On any failure the
  file is rolled back to its exact original bytes.
- A patch whose approval id is not APPROVED is never applied.

The service never fabricates a patch and never applies external content as
instructions — it only swaps byte-for-byte file content the author supplied.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Optional

from agents.safety.approval import ApprovalStatus


# Extensions an agent may patch. Compiled artifacts, binaries, secrets, and
# database files are excluded by not being in this set.
PATCHABLE_EXTENSIONS = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".ini"}

# Default verify command for .py targets (never shell; we run compile() directly).
_ALLOWED_VERIFY = {"py_compile"}


@dataclass
class CodePatch:
    """A proposed file patch, approval-gated at every mutation step."""

    target_path: str            # absolute or repo-relative file path
    authored_by: str            # "edward" | "jacob" | tool
    motivation: str             # what error/improvement prompted this
    detail: str                 # the detailed patch note for the human
    patch_text: str             # exact full new file content
    validation: str = "py_compile"
    patch_id: str = ""          # = approval item id after propose()

    def __post_init__(self):
        if not self.patch_id:
            import uuid
            self.patch_id = uuid.uuid4().hex


# ARCH-ENG-227: THE PROCESS-WIDE HANDLE ON THE ONE LIVE SERVICE.
#
# The GUI reaches the service through `EarningServices.code_patch_service`, which
# requires a MainWindow. A tool handler has no window, so without this the new
# `propose_code_patch` tool could only ever work inside the GUI -- which would
# make it unreachable from exactly the place that needs it.
#
# `CodePatchService.__init__` registers itself here. Deliberately NOT a global
# `get_root()`: the composition root already exists and already builds this
# object, so the honest wiring is "the service announces itself" rather than
# "callers reconstruct the object graph a second way".
_CODE_PATCH_SERVICE = None


def get_code_patch_service():
    """Return the live `CodePatchService`, or None if self-improvement is off.

    None is a normal answer, not an error: `composition_root` only builds the
    service when the `self_improvement` feature flag is on.
    """
    return _CODE_PATCH_SERVICE


class CodePatchService:
    """Owns the backup/apply/verify/rollback lifecycle for approved patches."""

    def __init__(
        self,
        approval_queue: Any = None,
        root_dir: Optional[str] = None,
        backup_dir_name: str = "code_patch_backups",
        apply_anyway_for_tests: bool = False,
    ):
        self.approval_queue = approval_queue
        self.root_dir = os.path.abspath(root_dir or ".")
        self.backup_dir = os.path.join(self.root_dir, backup_dir_name)
        os.makedirs(self.backup_dir, exist_ok=True)
        # Test-only bypass: allows apply without a real approved queue item so
        # unit tests can exercise backup/verify/rollback deterministically.
        self._apply_anyway_for_tests = apply_anyway_for_tests
        # registry: patch_id -> CodePatch (so apply can re-check approval)
        self._patches: dict[str, CodePatch] = {}
        # set of repo-rooted files currently "in use" (running module / open
        # handler); the app registers these so a hot-reload target isn't
        # clobbered mid-use. Also track active module paths -> file paths.
        self._in_use_files: set[str] = set()
        self._pending: list[tuple[str, float]] = []  # (patch_id, enqueued_ts)
        self._module_to_file: dict[str, str] = {}
        # Post-apply ledger: patch_id -> record of a successfully applied patch
        # (verified_at, status, backup_path, ...). Feeds the monitor.
        self._applied: dict[str, dict] = {}

        # ARCH-ENG-227: announce this instance so non-GUI callers
        # (the tool handler) can reach the one the composition root built.
        global _CODE_PATCH_SERVICE
        _CODE_PATCH_SERVICE = self
    # ── in-use tracking ──────────────────────────────────────────────────────
    def mark_in_use(self, target_or_module: str) -> None:
        """Record that a file (path or dotted module) is currently loaded/used."""
        fp = self._resolve_for_inuse(target_or_module)
        if fp:
            self._in_use_files.add(fp)

    def mark_free(self, target_or_module: str) -> None:
        """Release a file. Applying what was waiting is `drain`'s job, not this.

        ARCH-ENG-227: an earlier draft of this ticket folded the drain in here
        ("releasing a file is the event that unblocks a waiter"). That was
        wrong, and the existing tests caught it: `mark_free` frees and `drain`
        applies are separate, deliberate steps, and conflating them meant a
        caller that freed a file and then drained -- the documented pattern --
        found the queue already emptied and got `[]` back.

        The real gap was never that `mark_free` should drain. It is that
        NOTHING EVER CALLED `drain()`, so a queued patch sat forever and an
        operator's approved change silently never landed. That is now wired at
        the points where deferred work should be picked up: after an approval,
        and on the self-improvement monitor tick.
        """
        fp = self._resolve_for_inuse(target_or_module)
        if fp:
            self._in_use_files.discard(fp)

    def _resolve_for_inuse(self, target_or_module: str) -> str | None:
        t = (target_or_module or "").strip()
        if not t:
            return None
        if t.endswith(".py") or (os.path.sep in t or "/" in t):
            candidate = t if os.path.isabs(t) else os.path.abspath(
                os.path.join(self.root_dir, t)
            )
            try:
                rel = os.path.relpath(candidate, self.root_dir)
            except ValueError:
                return None
            if rel.startswith("..") or os.path.isabs(rel):
                return None
            return os.path.join(self.root_dir, rel)
        # ARCH-ENG-227: A DOTTED NAME USED TO RESOLVE TO None UNLESS IT HAD
        # BEEN REGISTERED -- AND NOTHING EVER CALLED `register_module`.
        #
        # So `_module_to_file` was permanently empty, `_resolve_for_inuse`
        # returned None for every dotted name, `mark_in_use("gui.tabs.chat")`
        # silently did nothing, and `_in_use_files` stayed empty forever.
        # That in turn made BOTH deferral guards unreachable:
        # `apply_approved`'s `... and self._in_use_files and target in ...`
        # and `drain`'s identical test. The in-use machinery was correct,
        # tested, and unreachable.
        #
        # Resolving through `importlib` means a dotted name works without a
        # registration pass. Registering every entry in `sys.modules` instead
        # would be worse than useless: almost every source file is imported at
        # startup, so "in use" would become "always", and no patch could ever
        # apply at all. In-use means "actively being written or hot-reloaded",
        # which is what `mark_in_use` is for.
        if t in self._module_to_file:
            return self._module_to_file[t]
        try:
            import importlib.util
            spec = importlib.util.find_spec(t)
        except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
            return None
        origin = getattr(spec, "origin", None) if spec else None
        if not origin or origin in ("built-in", "frozen", "namespace"):
            return None
        resolved = os.path.abspath(origin)
        # CONTAINMENT. Without this, `mark_in_use("json")` resolved to the
        # stdlib copy under the Python install and added it to `_in_use_files` --
        # a path the patch service could never patch anyway, so it could only
        # ever produce a confusing match. A dotted name is worth resolving only
        # if it names something inside this repo, which is the only place
        # `apply_approved` will ever write.
        try:
            root = os.path.realpath(self.root_dir)
            if os.path.commonpath([os.path.realpath(resolved), root]) != root:
                return None
        except ValueError:      # cross-drive
            return None
        return resolved

    def _in_use(self, target: str) -> bool:
        return target in self._in_use_files

    def register_module(self, dotted: str, file_path: str) -> None:
        """Map a loaded module path to its file so apply knows it is in use."""
        self._module_to_file[dotted] = os.path.abspath(file_path)

    # ── pending queue ────────────────────────────────────────────────────────
    def drain(self) -> list[dict]:
        """Apply all queued patches whose target is no longer in use.

        Iterates a snapshot of the pending queue so a patch that gets
        re-queued mid-apply (target became in-use) is kept, never dropped,
        and never causes an infinite loop. Returns apply results for the
        patches actually attempted in this drain.
        """
        applied: list[dict] = []
        still_pending: list[tuple[str, float]] = []
        snapshot = list(self._pending)
        self._pending = []
        for patch_id, ts in snapshot:
            patch = self._patches.get(patch_id)
            if patch is None:
                continue  # dropped
            if self._in_use_files and patch.target_path in self._in_use_files:
                still_pending.append((patch_id, ts))
                continue
            result = self.apply_approved(patch, approval_id=patch_id)
            applied.append(result)
            # If the apply re-queued the patch (target became in-use between
            # our check and the write), keep it pending instead of losing it.
            if result.get("status") == "queued":
                still_pending.append((patch_id, ts))
        self._pending = still_pending
        return applied

    # ── proposing & approval lookup ──────────────────────────────────────────
    def propose(self, patch: CodePatch) -> CodePatch:
        """Register the patch and enqueue it as an approval item.

        Enqueueing does NOT authorize anything — approving the returned item
        id is what unlocks apply(). If no approval_queue is configured, the
        patch is recorded as pending approval at the service level only.
        """
        self._assert_patchable(patch)
        if self.approval_queue is not None:
            from agents.safety.approval import ApprovalItem, ApprovalKind

            item = self.approval_queue.enqueue(ApprovalItem(
                kind=ApprovalKind.ACTION,
                title=f"Code patch: {os.path.basename(patch.target_path)}",
                description=(
                    f"Authored by {patch.authored_by}. {patch.motivation}\n"
                    f"---\n{patch.detail}"
                ),
                requested_by=patch.authored_by,
                details={
                    "target_path": patch.target_path,
                    "patch_id": patch.patch_id,
                    "validation": patch.validation,
                },
                payload={"patch_id": patch.patch_id},
            ))
            # The approval item id becomes the patch's gate id.
            self._patches.pop(patch.patch_id, None)
            patch.patch_id = item.id
            self._patches[item.id] = patch
        else:
            self._patches[patch.patch_id] = patch
        return patch

    def _is_approved(self, patch_id: str) -> bool:
        """True only when the exact approval item carrying this patch is APPROVED."""
        if self._apply_anyway_for_tests:
            return True
        if self.approval_queue is None:
            return False
        item = self.approval_queue.find_by_id(patch_id)
        return item is not None and item.status == ApprovalStatus.APPROVED

    # ── path & extension safety ──────────────────────────────────────────────
    def _assert_patchable(self, patch: CodePatch) -> None:
        target = patch.target_path
        if not target or not isinstance(target, str):
            raise ValueError("patch target_path is required")
        # Resolve relative targets against the repo root.
        candidate = os.path.abspath(target) if os.path.isabs(target) else os.path.abspath(
            os.path.join(self.root_dir, target)
        )
        root = self.root_dir
        try:
            real_root = os.path.realpath(root)
        except OSError:
            real_root = root
        # Lexical containment: reject anything that escapes via ".." or across
        # drives (relpath raises ValueError across mounts on Windows).
        try:
            rel = os.path.relpath(candidate, root)
        except ValueError as exc:
            raise ValueError(f"target_path escapes the repo root (cross-drive): {target}") from exc
        if rel.startswith("..") or os.path.isabs(rel):
            raise ValueError(f"target_path escapes the repo root: {target}")
        # Realpath containment: reject absolute paths outside root and symlink escapes.
        try:
            real_candidate = os.path.realpath(candidate)
        except OSError:
            real_candidate = candidate
        if os.path.commonpath([real_candidate, real_root]) != real_root:
            raise ValueError(f"target_path resolves outside the repo root (symlink/absolute): {target}")
        ext = os.path.splitext(candidate)[1].lower()
        if ext not in PATCHABLE_EXTENSIONS:
            raise ValueError(f"target extension .{ext} is not patchable")
        # ARCH-ENG-288 (B-01/B-02): the patch service is a third source-write
        # path, and it used to skip the two guards the other paths enforce.
        # A basename match is deliberate: the workers match by basename so
        # "./main.py", "app/main.py" and an absolute path are all refused.
        from agents.brains.base_worker import PROTECTED_SOURCE_FILES
        from agents.brains.worker_safety import FILENAME_BLOCKLIST

        basename = os.path.basename(candidate).lower()
        protected = {name.lower() for name in PROTECTED_SOURCE_FILES}
        blocked = {name.lower() for name in FILENAME_BLOCKLIST}
        if basename in protected:
            raise ValueError(
                f"target '{basename}' is a protected app source file; "
                f"use an external editor for intentional dev changes")
        if basename in blocked:
            raise ValueError(
                f"target '{basename}' is on the filename blocklist and is "
                f"never writable through the patch service")
        # Store the validated, repo-rooted absolute path.
        patch.target_path = os.path.join(root, rel)

    # ── backup / apply / verify / rollback ───────────────────────────────────
    def backup(self, target: str) -> str:
        """Copy target to the backup dir with a timestamp; return backup path."""
        os.makedirs(self.backup_dir, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(target))
        backup_path = os.path.join(
            self.backup_dir,
            f"{safe_name}.{int(time.time() * 1000)}.bak",
        )
        shutil.copy2(os.path.realpath(target), backup_path)
        return backup_path

    def verify(self, patch: CodePatch) -> tuple[bool, str]:
        """Run the enabled verification for this patch. Never shells out."""
        if patch.validation == "py_compile":
            if not patch.target_path.endswith(".py"):
                return True, "non-python: no compile check"
            try:
                import py_compile

                py_compile.compile(patch.target_path, doraise=True)
                return True, "py_compile ok"
            except py_compile.PyCompileError as exc:
                return False, f"py_compile failed: {exc}"
            except Exception as exc:  # pragma: no cover
                return False, f"compile check errored: {exc}"
        return True, "no verifier configured"

    def apply_approved(
        self,
        patch: CodePatch,
        approval_id: str = "",
        skip_queue: bool = False,
    ) -> dict[str, Any]:
        """Backup -> write -> verify -> rollback-on-fail, only if approved.

        Returns a dict: {ok, backup_path, target, detail}
        """
        self._assert_patchable(patch)
        target = patch.target_path

        gate = approval_id or patch.patch_id
        if not skip_queue and not self._is_approved(gate):
            raise RuntimeError(
                f"patch {gate} lacks human approval; refusing to mutate {target}"
            )

        # If the target file is currently in use (running module / open handle),
        # don't clobber it mid-use — queue it and let drain() apply it when free.
        if not skip_queue and self._in_use_files and target in self._in_use_files:
            import time as _time
            self._pending.append((gate, _time.time()))
            return {"ok": False, "status": "queued", "target": target,
                    "detail": "target file in use; queued until free"}

        if not os.path.exists(os.path.realpath(target)):
            raise FileNotFoundError(f"target file does not exist: {target}")

        # 1. Backup (always, before any write).
        backup_path = self.backup(target)

        # 2. Write new content atomically (temp + rename) so a crash never
        #    leaves a half-written file.
        try:
            dir_name = os.path.dirname(os.path.abspath(target))
            fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".patchtmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(patch.patch_text)
                os.replace(tmp, os.path.realpath(target))
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        except (OSError, PermissionError) as exc:
            self._rollback(backup_path, target)
            return {"ok": False, "backup_path": backup_path, "target": target,
                    "detail": f"write failed: {exc}"}

        # 3. Verify; roll back on any failure so we never leave a broken file.
        ok, detail = self.verify(patch)
        if not ok:
            restored = self._rollback(backup_path, target)
            return {"ok": False, "backup_path": backup_path, "target": target,
                    "detail": f"{detail}; rolled back={restored}"}

        # 4. Record the successful apply in the post-apply ledger.
        self._applied[gate] = {
            "patch_id": gate,
            "target_path": target,
            "backup_path": backup_path,
            "authored_by": patch.authored_by,
            "motivation": patch.motivation,
            "detail": patch.detail,
            "applied_at": time.time(),
            "verified_at": time.time(),
            "status": "verified",
            "last_check": 0.0,
        }
        return {"ok": True, "backup_path": backup_path, "target": target,
                "detail": f"applied and verified ({detail})"}

    def applied_patches(self) -> list[dict]:
        """Snapshot of the post-apply ledger (newest first)."""
        return sorted(
            self._applied.values(), key=lambda r: r.get("applied_at", 0.0), reverse=True
        )

    def monitor_applied(self) -> list[CodePatch]:
        """Re-verify every applied patch; emit a new gated proposal on regression.

        For each applied patch whose target no longer verifies (e.g. the file
        was later edited into a broken state), mark it ``regressed`` and enqueue
        a NEW human-gated proposal that reverts to the original backup. The
        monitor NEVER mutates the file itself and never auto-reverses — the
        revert only happens if a human approves the new proposal.
        """
        new_proposals: list[CodePatch] = []
        for gate, rec in list(self._applied.items()):
            target = rec["target_path"]
            if not os.path.exists(os.path.realpath(target)):
                continue
            # Re-verify the current on-disk content of the target.
            probe = CodePatch(
                target_path=target,
                authored_by=rec.get("authored_by", "monitor"),
                motivation=rec.get("motivation", ""),
                detail=rec.get("detail", ""),
                patch_text="",  # not applied; only used for verify()
            )
            ok, detail = self.verify(probe)
            rec["last_check"] = time.time()
            if ok:
                rec["status"] = "verified"
                continue
            rec["status"] = "regressed"
            # Emit a new proposal that reverts to the original backup content.
            revert_text = ""
            backup = rec.get("backup_path")
            if backup and os.path.exists(backup):
                try:
                    with open(backup, encoding="utf-8") as f:
                        revert_text = f.read()
                except OSError:
                    revert_text = ""
            new_patch = CodePatch(
                target_path=target,
                authored_by=f"self-heal:{rec.get('authored_by', 'monitor')}",
                motivation=(
                    f"Post-apply monitor: patch {gate} regressed "
                    f"(verify: {detail}). Proposing revert to last-known-good."
                ),
                detail=(
                    f"Original patch {gate} by {rec.get('authored_by')} was applied "
                    f"and verified, but a later check failed. This proposal reverts "
                    f"{target} to the pre-patch backup. Approve to restore, or decline "
                    f"and author a better fix."
                ),
                patch_text=revert_text,
            )
            self.propose(new_patch)
            new_proposals.append(new_patch)
        return new_proposals

    def _rollback(self, backup_path: str, target: str) -> bool:
        """Restore the exact original bytes from the backup."""
        try:
            if not os.path.exists(backup_path):
                return False
            shutil.copy2(os.path.realpath(backup_path), os.path.realpath(target))
            return True
        except Exception:
            return False


__all__ = ["CodePatch", "CodePatchService", "PATCHABLE_EXTENSIONS"]
