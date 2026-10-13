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

from agents.safety.guard import SafetyGuard, SafetyAction


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
        """Request human approval for a submission.

        Fails CLOSED when no safety guard is configured. This used to
        auto-approve (``record.status = "approved"``, ``mode: "auto"``), and
        ``gui/tabs/earning_tab.py`` constructs ``PlatformSubmitter()`` with no
        guard — so the default configuration turned "approval" into a no-op.
        An unguarded submission is not an approved one.
        """
        if self.safety_guard is None:
            record.status = "blocked"
            return {
                "ok": False,
                "record_id": record.record_id,
                "status": "blocked",
                "mode": "no_guard",
                "error": "no safety guard configured; cannot request approval",
            }

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
            # Store approval ID for tracking. `get_pending_approvals()` returns
            # the layer's raw pending dicts, whose "action" value is a
            # SafetyAction *dataclass*, not a dict — attribute access, not
            # .get(). Using .get() raised AttributeError here, so the one path
            # that actually flags a submission crashed instead of queueing it.
            record.approval_id = ""
            for pending in self.safety_guard.get_pending_approvals():
                pending_action = pending.get("action")
                pending_args = getattr(pending_action, "arguments", None)
                if isinstance(pending_args, dict) and pending_args.get("record_id") == record.record_id:
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

    def submit_if_approved(self, record: SubmissionRecord) -> Dict[str, Any]:
        """Submit a record the human has actually approved.

        The approval path was terminal before this: ``request_approval``
        queued the request and returned ``awaiting_approval``, and nothing
        ever read the decision back — so the operator approved a submission
        in the Approvals tab and it was never sent (the same shape of defect
        as ARCH-ENG-083's approved ACTION item).

        The decision is re-read from HumanApprovalQueue, never from a caller
        argument: the queue is the only component permitted to record a human
        approval. A record whose approval is still PENDING, or was
        DENIED/DEFERRED, is NOT submitted. Fail-closed on any read error.
        """
        if not record.approval_id:
            return {
                "ok": False,
                "record_id": record.record_id,
                "error": "No approval was ever requested for this record",
            }
        try:
            from agents.safety.approval import (
                ApprovalStatus,
                HumanApprovalQueue,
            )
            item = HumanApprovalQueue.instance().find_by_id(record.approval_id)
        except Exception as exc:
            return {
                "ok": False,
                "record_id": record.record_id,
                "status": "blocked",
                "error": f"Approval queue unavailable: {exc}",
            }
        if item is None:
            return {
                "ok": False,
                "record_id": record.record_id,
                "status": "blocked",
                "error": (
                    f"Approval {record.approval_id} is not in the queue; "
                    "cannot confirm a human decision"
                ),
            }
        if item.status == ApprovalStatus.PENDING:
            return {
                "ok": False,
                "record_id": record.record_id,
                "status": "awaiting_approval",
                "approval_id": record.approval_id,
                "error": "Still awaiting human approval",
            }
        if item.status != ApprovalStatus.APPROVED:
            record.status = "rejected"
            record.error = f"Human decision: {item.status.value}"
            return {
                "ok": False,
                "record_id": record.record_id,
                "status": "rejected",
                "error": record.error,
            }
        # The human approved. Refuse to send the same record twice: the queue
        # keeps a decided item APPROVED forever, so without this guard a second
        # call (a retry button, a re-emitted signal, a future caller) would
        # execute the irreversible submission again. Reproduced: two calls with
        # a real adapter registered produced two external submissions.
        if record.status in ("submitted", "failed") or record.submitted_at:
            return {
                "ok": False,
                "record_id": record.record_id,
                "status": record.status,
                "error": (
                    "This submission was already executed "
                    f"(status={record.status}); refusing to send it twice"
                ),
            }
        record.status = "approved"
        return self.submit(record)

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
