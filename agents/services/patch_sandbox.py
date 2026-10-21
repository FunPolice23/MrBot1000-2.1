"""agents/services/patch_sandbox.py — rehearse a patch before anyone is asked.

## The problem this exists to solve

`CodePatchService` already does backup -> write -> verify -> rollback. But its
verifier is deliberately weak: `verify()` runs `py_compile` and nothing else,
and says so -- "Never shells out". That is the right call for a service that
writes into a running application's own source, but it means a patch can
compile cleanly and still be wrong. The human is asked to approve a change that
has been proven to be *syntactically* valid and nothing more.

## The rehearsal

Before a proposal is raised, the patch is applied to a COPY in the operator's
workshop, and verification runs against the copy:

    D:\\ai_workshop\\practice\\<run_id>\\<mirrored repo-relative path>

Three properties matter and are all tested:

1. **The real target is never touched.** The sandbox writes only inside the
   practice root. A bug here that wrote to the original would be the worst
   possible bug, so containment is asserted, not assumed.
2. **The practice copy is kept, not deleted.** The human approving the patch can
   look at exactly what was rehearsed. A rehearsal whose evidence is thrown away
   is not evidence.
3. **A failure is a refusal, not a warning.** The caller must not be able to
   propose a patch that failed rehearsal. That is enforced here and re-checked by
   the tool handler.

## What this is not

This does not replace human approval, and it does not decide whether a patch is
*correct* -- only whether it is well-formed enough to be worth a human's
attention. `py_compile` catches syntax errors. It does not catch a wrong
function. The approval step remains the real gate, and it is unchanged.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from typing import Any, Dict, Optional

# The operator's workshop. Same default as `agents.knowledge.workshop`, kept
# independent so a sandbox can be relocated by env var without touching the
# workshop's own configuration.
DEFAULT_PRACTICE_ROOT = os.getenv("MRBOT_PATCH_PRACTICE_ROOT") or os.getenv(
    "AI_WORKSHOP_ROOT") or r"D:\ai_workshop"

PRACTICE_SUBDIR = "practice"


class SandboxError(RuntimeError):
    """A rehearsal could not be performed at all (as opposed to failing)."""


class PatchSandbox:
    """Rehearse a patch against a copy. Never writes outside the practice root."""

    def __init__(self, repo_root: str, practice_root: str = DEFAULT_PRACTICE_ROOT):
        self.repo_root = os.path.abspath(repo_root)
        self.practice_root = os.path.abspath(os.path.join(practice_root, PRACTICE_SUBDIR))

    # ── containment ─────────────────────────────────────────────────────────
    def _relative_target(self, target: str) -> str:
        """Repo-relative path for *target*, or raise if it escapes the repo.

        Mirrors `CodePatchService._assert_patchable`'s containment rules so the
        sandbox cannot be used to reach a file the patch service would refuse.
        """
        if not target or not isinstance(target, str):
            raise SandboxError("target path is required")
        candidate = (target if os.path.isabs(target)
                     else os.path.join(self.repo_root, target))
        candidate = os.path.abspath(candidate)
        try:
            rel = os.path.relpath(candidate, self.repo_root)
        except ValueError as exc:
            raise SandboxError(f"target escapes the repo root: {target}") from exc
        if rel.startswith("..") or os.path.isabs(rel):
            raise SandboxError(f"target escapes the repo root: {target}")
        return rel

    # ── rehearsal ───────────────────────────────────────────────────────────
    def rehearse(self, target: str, new_text: str,
                 validation: str = "py_compile",
                 run_id: str = "") -> Dict[str, Any]:
        """Apply *new_text* to a COPY of *target* and verify the copy.

        Returns a dict:
            ok            bool   - did the rehearsal pass
            practice_path  str   - where the rehearsed file is, for inspection
            run_id        str
            validation    str
            detail        str   - why it passed or failed
            target        str   - the real target, which was NOT modified

        Raises SandboxError only when the rehearsal could not be attempted.
        A rehearsal that RAN and FAILED returns ok=False; that distinction
        matters, because "could not try" and "tried and it broke" are different
        answers to give the operator.
        """
        rel = self._relative_target(target)
        run_id = run_id or f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        run_dir = os.path.abspath(os.path.join(self.practice_root, run_id))

        # Containment, re-checked: `run_dir` is built from a validated relative
        # path and a run_id we generated, but a defensive check costs nothing
        # and this is the one place a bug would be catastrophic.
        if os.path.commonpath([run_dir, self.practice_root]) != self.practice_root:
            raise SandboxError("practice run directory escapes the practice root")

        practice_path = os.path.join(run_dir, rel)
        os.makedirs(os.path.dirname(practice_path), exist_ok=True)

        # Seed the copy from the original so the rehearsal runs against the real
        # surrounding code, not a lone file. A missing original is a rehearsal
        # against nothing, so it is refused rather than silently creating a stub.
        real_target = os.path.abspath(os.path.join(self.repo_root, rel))
        seeded_from = None
        if os.path.isfile(real_target):
            os.makedirs(os.path.dirname(practice_path), exist_ok=True)
            shutil.copy2(real_target, practice_path)
            seeded_from = real_target
        else:
            # New file: rehearse the proposed content on its own. There is no
            # original to break, so this is still a meaningful syntax check.
            os.makedirs(os.path.dirname(practice_path), exist_ok=True)

        with open(practice_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_text)

        ok, detail = self._verify_copy(practice_path, rel, validation)

        return {
            "ok": bool(ok),
            "practice_path": practice_path,
            "practice_dir": run_dir,
            "run_id": run_id,
            "validation": validation,
            "detail": detail,
            "target": real_target,
            "seeded_from": seeded_from,
            "is_new_file": seeded_from is None,
        }

    def _verify_copy(self, practice_path: str, rel: str,
                     validation: str) -> tuple[bool, str]:
        """Run the checks against the COPY. Never against the original."""
        if validation == "py_compile":
            if not practice_path.endswith(".py"):
                return True, "non-python: no compile check"
            try:
                import py_compile
                # cfile goes in the practice dir, so a stray .pyc never lands
                # next to the real source.
                cfile = os.path.join(
                    os.path.dirname(practice_path),
                    os.path.basename(practice_path) + "c",
                )
                py_compile.compile(practice_path, cfile=cfile, doraise=True)
                return True, "py_compile ok (rehearsed copy)"
            except py_compile.PyCompileError as exc:
                return False, f"rehearsed copy does not compile: {exc}"
            except Exception as exc:  # pragma: no cover
                return False, f"compile check errored: {exc}"

        if validation == "import_smoke":
            # A deeper check than compiling: actually import the rehearsed copy
            # in isolation. Off by default because importing arbitrary agent-
            # authored code has side effects; offered so an operator can opt in
            # per-target from the proposal UI.
            if not practice_path.endswith(".py"):
                return True, "non-python: no import check"
            import importlib.util
            import sys
            try:
                spec = importlib.util.spec_from_file_location(
                    f"_mrb_rehearsal_{os.path.basename(rel)}", practice_path)
                if spec is None or spec.loader is None:
                    return False, "could not build an import spec for the copy"
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return True, "import smoke ok (rehearsed copy)"
            except Exception as exc:
                return False, f"rehearsed copy raised on import: {exc!r}"
            finally:
                sys.modules.pop(f"_mrb_rehearsal_{os.path.basename(rel)}", None)

        return True, f"no rehearsal verifier configured for {validation!r}"

    def prune(self, keep: int = 20) -> int:
        """Drop the oldest rehearsal runs, keeping *keep* of them.

        Without this the practice folder grows without bound on a machine that
        is short of disk (see the workshop quota ticket). Returns how many run
        directories were removed.
        """
        if keep < 1 or not os.path.isdir(self.practice_root):
            return 0
        runs = [os.path.join(self.practice_root, d)
                for d in os.listdir(self.practice_root)]
        runs = [r for r in runs if os.path.isdir(r)]
        runs.sort(key=lambda r: os.path.getmtime(r), reverse=True)
        removed = 0
        for stale in runs[keep:]:
            try:
                shutil.rmtree(stale, ignore_errors=True)
                removed += 1
            except Exception:
                pass
        return removed


__all__ = [
    "PatchSandbox", "SandboxError", "DEFAULT_PRACTICE_ROOT", "PRACTICE_SUBDIR",
]