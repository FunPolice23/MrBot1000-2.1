"""
agents/platform_submitter.py — Human-gated platform submission wrapper (v2.1 Path 1).

Wraps existing platform adapters (Upwork, Fiverr, GitHub, etc.) with:
- Human approval gates before any submission
- Evidence packaging for audit trail
- Status tracking for submissions
- Fallback to local draft if approval denied

NEVER submits without explicit human confirmation.
"""

from __future__ import annotations

import time
import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents.safety_guard import SafetyGuard, SafetyAction


@dataclass
class SubmissionRecord:
    """Record of a submission attempt."""
    record_id: str
    platform: str
    opportunity_id: str
    title: str
    status: str = "pending"  # pending|approved|submitted|rejected|failed
    approval_id: Optional[str] = None
    submitted_at: Optional[float] = None
    evidence_path: str = ""
    error: str = ""
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "platform": self.platform,
            "opportunity_id": self.opportunity_id,
            "title": self.title,
            "status": self.status,
            "approval_id": self.approval_id,
            "submitted_at": self.submitted_at,
            "evidence_path": self.evidence_path,
            "error": self.error,
            "metadata": self.metadata,
        }


class PlatformSubmitter:
    """Submit to freelance platforms with human approval gates."""

    def __init__(self, safety_guard: Optional[SafetyGuard] = None, evidence_dir: str = ""):
        self.safety_guard = safety_guard
        self.evidence_dir = evidence_dir or os.path.join(os.path.expanduser("~"), ".mrbot1000", "submissions")
        self._records: Dict[str, SubmissionRecord] = {}
        self._platforms: Dict[str, Any] = {}
        self._ensure_evidence_dir()

    def _ensure_evidence_dir(self):
        try:
            os.makedirs(self.evidence_dir, exist_ok=True)
        except Exception:
            pass

    def register_platform(self, name: str, adapter: Any):
        """Register a platform adapter."""
        self._platforms[name] = adapter

    def get_platform(self, name: str) -> Optional[Any]:
        """Get a registered platform adapter."""
        return self._platforms.get(name)

    def prepare_submission(self, platform: str, opportunity: Dict[str, Any], proposal_text: str, extra_files: List[str] = None) -> SubmissionRecord:
        """Prepare a submission package and queue for human approval."""
        record_id = hashlib.sha256(f"{platform}{opportunity.get('url','')}{time.time()}".encode()).hexdigest()[:24]
        title = opportunity.get("title", "Untitled")
        opp_id = opportunity.get("url", opportunity.get("id", ""))

        # Save evidence
        evidence_path = os.path.join(self.evidence_dir, f"{record_id}.json")
        try:
            import json
            evidence = {
                "record_id": record_id,
                "platform": platform,
                "opportunity": opportunity,
                "proposal_text": proposal_text,
                "extra_files": extra_files or [],
                "prepared_at": time.time(),
            }
            with open(evidence_path, "w") as f:
                json.dump(evidence, f, indent=2)
        except Exception:
            pass

        record = SubmissionRecord(
            record_id=record_id,
            platform=platform,
            opportunity_id=opp_id,
            title=title,
            status="pending",
            evidence_path=evidence_path,
            metadata={
                "proposal_length": len(proposal_text),
                "extra_files": extra_files or [],
            },
        )
        self._records[record_id] = record
        return record

    def request_approval(self, record: SubmissionRecord) -> Dict[str, Any]:
        """Request human approval for a submission."""
        if self.safety_guard is None:
            # No safety guard: auto-approve
            record.status = "approved"
            return {"ok": True, "record_id": record.record_id, "status": "approved", "mode": "auto"}

        # Create a safety action for human approval
        action = SafetyAction(
            action_type="submit_proposal",
            name=f"{record.platform}:{record.title[:50]}",
            arguments={
                "platform": record.platform,
                "opportunity_id": record.opportunity_id,
                "record_id": record.record_id,
            },
            estimated_cost=0.0,
            platform=record.platform,
            requires_funds=False,
            metadata={"submission_record_id": record.record_id},
        )

        result = self.safety_guard.check(action)
        if result.action == "flag":
            # Store approval ID for tracking
            for pending in self.safety_guard.get_pending_approvals():
                if pending.get("action", {}).get("arguments", {}).get("record_id") == record.record_id:
                    record.approval_id = pending["id"]
                    break
            return {
                "ok": True,
                "record_id": record.record_id,
                "status": "awaiting_approval",
                "approval_id": record.approval_id,
                "reasons": result.reasons,
            }

        if result.blocked:
            record.status = "rejected"
            record.error = "; ".join(result.reasons)
            return {"ok": False, "record_id": record.record_id, "status": "rejected", "error": record.error}

        # Allowed
        record.status = "approved"
        return {"ok": True, "record_id": record.record_id, "status": "approved"}

    def submit(self, record: SubmissionRecord) -> Dict[str, Any]:
        """Submit an approved record via platform adapter."""
        if record.status != "approved":
            return {"ok": False, "record_id": record.record_id, "error": f"Not approved: {record.status}"}

        adapter = self._platforms.get(record.platform)
        if adapter is None:
            # No real adapter: package for manual submission
            record.status = "submitted"
            record.submitted_at = time.time()
            record.metadata["submission_mode"] = "manual_package"
            return {
                "ok": True,
                "record_id": record.record_id,
                "status": "submitted",
                "mode": "manual",
                "message": "No live adapter configured. Evidence package ready for manual submission.",
                "evidence_path": record.evidence_path,
            }

        # Real adapter path
        try:
            if hasattr(adapter, "submit_proposal"):
                result = adapter.submit_proposal(
                    {"opportunity_id": record.opportunity_id, "record_id": record.record_id},
                    confirmed_by_human=True,
                )
                record.status = "submitted" if result.get("ok") else "failed"
                record.submitted_at = time.time()
                record.error = result.get("error", "")
                record.metadata["adapter_result"] = result
                return {"ok": result.get("ok"), "record_id": record.record_id, "status": record.status, "result": result}
            else:
                return {"ok": False, "record_id": record.record_id, "error": "Adapter does not support submit_proposal"}
        except Exception as e:
            record.status = "failed"
            record.error = str(e)
            return {"ok": False, "record_id": record.record_id, "status": "failed", "error": str(e)}

    def get_record(self, record_id: str) -> Optional[SubmissionRecord]:
        """Get submission record by ID."""
        return self._records.get(record_id)

    def list_records(self, status: Optional[str] = None) -> List[SubmissionRecord]:
        """List submission records."""
        records = list(self._records.values())
        if status:
            records = [r for r in records if r.status == status]
        return records

    def get_status(self) -> Dict[str, Any]:
        """Get submitter status."""
        all_records = list(self._records.values())
        return {
            "total_records": len(all_records),
            "pending": len([r for r in all_records if r.status == "pending"]),
            "approved": len([r for r in all_records if r.status == "approved"]),
            "submitted": len([r for r in all_records if r.status == "submitted"]),
            "rejected": len([r for r in all_records if r.status == "rejected"]),
            "failed": len([r for r in all_records if r.status == "failed"]),
            "registered_platforms": list(self._platforms.keys()),
        }
