"""TaskWorkspace — per-task deliverable workspace for MrBot1000.

When the agent wins/accepts a gig, it needs a real place to DO the work and
verify it against the gig's requirements before "submitting" it back. This
module provides a sandboxed, task-scoped workspace:

    work/<platform>/<job_id>/

Design goals (per user direction 2026-08-06):
  • One folder per task, named work/<platform>/<job_id>/.
  • Save deliverables into it (with a pre-overwrite backup, like safe_write_file).
  • Derive / accept the gig's REQUIREMENTS and verify them with
    document_scanner.verify_completion before marking complete.
  • On completion, archive the deliverables to work/<platform>/<job_id>/delivered/
    and record a status.json manifest.
  • The workspace lives under ROOT_FOLDER (so the existing sandbox + backup
    safety applies) and is excluded from project_file_tree (so the Coder planner
    never tries to edit its own deliverables).

No network submission is performed here — that is a deliberate, later plug-in
point. "Submit" = local packaging + status=submitted + archived deliverable.
"""

from __future__ import annotations

import os
import json
import shutil
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from agents.base_worker import ROOT_FOLDER


# Status values tracked in status.json
STATUS_NEW      = "new"
STATUS_WORKING  = "working"
STATUS_DONE     = "done"        # requirements verified
STATUS_SUBMITTED = "submitted"  # packaged / handed back
STATUS_FAILED   = "failed"


class TaskWorkspace:
    """A sandboxed folder where one gig's deliverables are produced + verified."""

    def __init__(self, platform: str, job_id: str,
                 root_folder: str = None,
                 log_signal=None):
        self.platform = (platform or "unknown").strip().lower()
        self.job_id   = str(job_id or "unknown").strip()
        self.root     = Path(root_folder or ROOT_FOLDER).resolve()
        # work/<platform>/<job_id>/
        self.path     = (self.root / "work" / self.platform / self.job_id).resolve()
        # guard: must stay inside the configured root (which may be a custom
        # sandbox, not the repo ROOT_FOLDER). Validate against self.root.
        if not self._inside_root(self.path, self.root):
            raise ValueError(f"Workspace escapes root: {self.path}")
        self._log = log_signal.emit if log_signal else (lambda *a, **k: None)
        self.ensure()

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _inside_root(p: Path, root: Path = None) -> bool:
        root = (root or Path(ROOT_FOLDER)).resolve()
        try:
            return p.resolve().is_relative_to(root)
        except AttributeError:
            return str(p.resolve()).startswith(str(root) + os.sep)

    def ensure(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    # ── deliverable IO (backup-before-overwrite, sandboxed) ────────────────

    def _safe_file_path(self, filename: str) -> Optional[Path]:
        """Resolve a deliverable filename strictly inside this workspace."""
        filename = filename.replace("\\", "/").strip().lstrip("/")
        # block path traversal
        if ".." in filename.split("/"):
            return None
        full = (self.path / filename).resolve()
        if not self._inside_root(full, self.root):
            return None
        return full

    def save(self, filename: str, content: str) -> bool:
        """Write a deliverable into the workspace (backs up existing first)."""
        full = self._safe_file_path(filename)
        if not full:
            self._log(f"[Workspace] BLOCKED unsafe filename: {filename}")
            return False
        try:
            if full.exists() and full.is_file():
                bak = full.with_suffix(full.suffix + ".bak")
                shutil.copy2(full, bak)
                self._log(f"[Workspace] backed up {filename} -> {bak.name}")
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            self._log(f"[Workspace] saved {filename} ({len(content):,} chars)")
            self.set_status(STATUS_WORKING)
            return True
        except Exception as e:
            self._log(f"[Workspace] write error: {e}")
            return False

    def list_files(self) -> List[str]:
        """Return deliverable file paths (relative to workspace) as strings."""
        if not self.path.exists():
            return []
        out = []
        for p in sorted(self.path.rglob("*")):
            if p.is_file() and p.suffix != ".bak" and p.name != "status.json":
                out.append(str(p.relative_to(self.path)))
        return out

    # ── requirements → verification ────────────────────────────────────────

    @staticmethod
    def infer_requirements(job: Dict[str, Any]) -> List[str]:
        """Derive expected-output hints from a JobRecord dict.

        verify_completion() matches each expected string as a SUBSTRING of an
        actual deliverable filename, so we keep these short, lowercase hints
        (skills + a generic 'deliverable'). Callers may pass explicit, richer
        requirements instead.
        """
        reqs: List[str] = ["deliverable"]
        skills = job.get("skills") or []
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split(",") if s.strip()]
        for s in skills[:6]:
            s = str(s).strip().lower()
            if s and s not in reqs:
                reqs.append(s)
        # pull a couple of noun-ish words from the title as extra hints
        title = (job.get("title") or "").lower()
        for tok in title.replace("-", " ").split():
            if len(tok) > 4 and tok.isalpha() and tok not in reqs:
                reqs.append(tok)
                if len(reqs) >= 8:
                    break
        return reqs

    def verify(self, requirements: Optional[List[str]] = None,
               job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Check the workspace's files satisfy the gig requirements.

        Returns the document_scanner WorkVerification plus a workspace summary.
        """
        if requirements is None and job is not None:
            requirements = self.infer_requirements(job)
        if requirements is None:
            requirements = ["deliverable"]

        files = self.list_files()
        actual_paths = [str(self.path / f) for f in files]

        # Lazy import to avoid a hard dependency at module load.
        from agents.document_scanner import DocumentScanner
        scanner = DocumentScanner()
        verification = scanner.verify_completion(
            work_id=f"{self.platform}:{self.job_id}",
            expected_outputs=requirements,
            actual_files=actual_paths,
        )
        result = {
            "platform": self.platform,
            "job_id": self.job_id,
            "requirements": requirements,
            "files": files,
            "can_submit": bool(getattr(verification, "can_submit", False)),
            "missing_items": list(getattr(verification, "missing_items", [])),
            "quality_score": float(getattr(verification, "quality_score", 0.0)),
            "issues": list(getattr(verification, "issues", [])),
            "recommendations": list(getattr(verification, "recommendations", [])),
        }
        return result

    # ── status manifest ────────────────────────────────────────────────────

    def _status_file(self) -> Path:
        return self.path / "status.json"

    def set_status(self, status: str, extra: Optional[Dict[str, Any]] = None) -> None:
        data = self._read_status()
        data["status"] = status
        data["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        if extra:
            data.update(extra)
        try:
            self._status_file().write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            self._log(f"[Workspace] status write error: {e}")

    def _read_status(self) -> Dict[str, Any]:
        sf = self._status_file()
        if sf.exists():
            try:
                return json.loads(sf.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "platform": self.platform,
            "job_id": self.job_id,
            "status": STATUS_NEW,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

    @property
    def status(self) -> str:
        return self._read_status().get("status", STATUS_NEW)

    # ── completion / submission (local packaging) ─────────────────────────

    def complete(self, requirements: Optional[List[str]] = None,
                 job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Verify requirements; if met, mark done and archive deliverables.

        Returns the verify() result with an added 'completed' flag.
        """
        res = self.verify(requirements=requirements, job=job)
        if res["can_submit"]:
            delivered = self.path / "delivered"
            delivered.mkdir(exist_ok=True)
            for f in res["files"]:
                src = self.path / f
                dst = delivered / f
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            self.set_status(STATUS_DONE, {
                "files": res["files"],
                "quality_score": res["quality_score"],
                "completed_at": datetime.datetime.now().isoformat(timespec="seconds"),
            })
            res["completed"] = True
            res["archive"] = str(delivered)
            self._log(f"[Workspace] COMPLETE {self.platform}:{self.job_id} "
                      f"({len(res['files'])} files, q={res['quality_score']:.2f})")
        else:
            self.set_status(STATUS_WORKING, {
                "missing_items": res["missing_items"],
                "issues": res["issues"],
            })
            res["completed"] = False
            self._log(f"[Workspace] NOT complete {self.platform}:{self.job_id} "
                      f"missing={res['missing_items']}")
        return res

    def submit(self) -> Dict[str, Any]:
        """Hand the work back. Local packaging only (no network upload yet).

        Promotes status to 'submitted' and records the archive location. Real
        platform upload (Fiverr/Upwork) is a later plug-in point.
        """
        data = self._read_status()
        if data.get("status") not in (STATUS_DONE, STATUS_WORKING):
            self.set_status(STATUS_WORKING)
        self.set_status(STATUS_SUBMITTED, {
            "submitted_at": datetime.datetime.now().isoformat(timespec="seconds"),
        })
        archive = self.path / "delivered"
        return {
            "platform": self.platform,
            "job_id": self.job_id,
            "status": STATUS_SUBMITTED,
            "archive": str(archive) if archive.exists() else str(self.path),
            "files": self.list_files(),
        }


def workspace_for(job: Dict[str, Any],
                  root_folder: str = None,
                  log_signal=None) -> TaskWorkspace:
    """Convenience factory from a JobRecord dict (or to_dict())."""
    return TaskWorkspace(
        platform=job.get("platform", "unknown"),
        job_id=job.get("job_id", "unknown"),
        root_folder=root_folder,
        log_signal=log_signal,
    )
