"""
agents/earning_capability.py — First real autonomous earning capability (v2.1 Phase 4).

Implements ONE narrow, verifiable, paper/human-gated earning path:

    research   → evaluate (expected value / risk, existing engine)
    → create a real TaskWorkspace deliverable
    → deterministic validation (task_validators + workspace.verify)
    → human gates (HumanGateManager — never bypassed)
    → local submission package (workspace.submit, NO network upload)
    → evidence + lifecycle/portfolio update (submission, NOT payment)

Hard rules (the "LLM is not the source of truth" discipline):
- Completion is decided by DETERMINISTIC validators, never by the model.
- Any task needing a payment/contract/signature/identity/irreversible/sensitive
  gate STOPS at AWAITING_APPROVAL and does NOT proceed.
- Submission is LOCAL PACKAGING ONLY. No real Fiverr/Upwork/DeFi action.
- Revenue is NEVER recorded here. "Submitted" is not "paid". A verified payment
  must come through the evidence-gated lifecycle path later.

The producer callable (model_fn) is injected so the whole capability is verifiable
mock-first with no network/model. In production it is wired to the dual-brain
adapters through the coordinator/runtime.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agents.task_workspace import TaskWorkspace


# Extension per task type for the single local deliverable.
_DEFAULT_EXT = ".md"
_EXT_BY_TASK_TYPE = {
    "coding": ".py",
    "bug_fix": ".py",
    "research": ".md",
    "writing": ".md",
    "transcription": ".txt",
    "data": ".csv",
    "document": ".md",
    "technical_writing": ".md",
    "proposal": ".md",
    "cover_letter": ".md",
    "virtual_assistance": ".md",
    "software_testing": ".md",
}


@dataclass
class EarningCapabilityResult:
    """Outcome of one earning-capability fulfillment attempt."""

    opportunity_id: str = ""
    platform: str = ""
    job_id: str = ""
    status: str = "pending"           # approved|await_approval|validation_failed|failed
    workspace_dir: str = ""
    files: List[str] = field(default_factory=list)
    validation: Dict[str, Any] = field(default_factory=dict)
    gates: List[Dict[str, Any]] = field(default_factory=list)
    evidence_id: str = ""
    lifecycle_stage: str = ""
    submission_package: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "platform": self.platform,
            "job_id": self.job_id,
            "status": self.status,
            "workspace_dir": self.workspace_dir,
            "files": self.files,
            "validation": self.validation,
            "gates": self.gates,
            "evidence_id": self.evidence_id,
            "lifecycle_stage": self.lifecycle_stage,
            "submission_package": self.submission_package,
            "error": self.error,
        }


# Producer: (opportunity, requirements) -> deliverable text.
Producer = Callable[[Any, List[str]], str]


class EarningCapabilityExecutor:
    """Deterministic, human-gated fulfillment of a single earning opportunity."""

    def __init__(self,
                 portfolio: Any = None,
                 lifecycle: Any = None,
                 evidence_store: Any = None,
                 human_gates: Any = None,
                 root_folder: Optional[str] = None,
                 log_fn: Optional[Callable[[str], None]] = None):
        self.portfolio = portfolio
        self.lifecycle = lifecycle
        self.evidence_store = evidence_store
        self.human_gates = human_gates
        self.root_folder = root_folder
        self._log = log_fn or (lambda msg: None)

    # ── helpers ─────────────────────────────────────────────────────────────
    def _job_id(self, opp: Any) -> str:
        return str(getattr(opp, "id", getattr(opp, "opportunity_id", "opp")) or "opp")

    def _platform(self, opp: Any) -> str:
        return str(getattr(opp, "platform", "unknown") or "unknown")

    def _task_type(self, opp: Any) -> str:
        return str(getattr(opp, "task_type", getattr(opp, "type", "writing")) or "writing")

    def _requirements(self, opp: Any) -> List[str]:
        reqs = list(getattr(opp, "required_skills", []) or [])
        if not reqs:
            reqs = ["deliverable"]
        return [str(r) for r in reqs]

    def _gate_context(self, opp: Any) -> Dict[str, Any]:
        return {"platform": self._platform(opp)}

    # ── main entry ──────────────────────────────────────────────────────────
    def fulfill(self, opp: Any, producer: Producer,
                requirements: Optional[List[str]] = None,
                clear_gates: Optional[List[str]] = None) -> EarningCapabilityResult:
        """Produce + validate + (human-gate) + locally-package an opportunity.

        Returns a result; never raises. ``clear_gates`` is a list of gate-type
        names a human has explicitly approved for THIS call (e.g. the GUI's
        approval dialog). Without it, any required gate → AWAITING_APPROVAL.
        """
        opp_id = self._job_id(opp)
        platform = self._platform(opp)
        task_type = self._task_type(opp)
        reqs = requirements or self._requirements(opp)
        result = EarningCapabilityResult(opportunity_id=opp_id,
                                         platform=platform, job_id=opp_id)

        # 1) Real workspace deliverable.
        try:
            workspace = TaskWorkspace(platform, opp_id, root_folder=self.root_folder)
        except Exception as exc:
            return self._fail(result, f"workspace create failed: {exc}")
        result.workspace_dir = str(workspace.path)

        try:
            content = producer(opp, reqs)
        except Exception as exc:
            return self._fail(result, f"producer failed: {exc}")
        if not content or not str(content).strip():
            return self._fail(result, "producer returned empty deliverable")

        filename = f"deliverable{_EXT_BY_TASK_TYPE.get(task_type, _DEFAULT_EXT)}"
        if not workspace.save(filename, str(content)):
            return self._fail(result, "deliverable save failed")
        result.files = workspace.list_files()

        # 2) Deterministic validation (workspace requirements + validator).
        verification = workspace.verify(requirements=reqs)
        result.validation = verification
        if not verification.get("can_submit"):
            result.status = "validation_failed"
            result.error = "deliverable does not meet requirements"
            workspace.set_status("failed")
            return result

        # 3) Human gates (never bypassed).
        task_dict = {
            "task_id": opp_id,
            "id": opp_id,
            "title": getattr(opp, "title", ""),
            "description": getattr(opp, "description", ""),
            "payment_conditions": getattr(opp, "payment_conditions", {}) or {},
        }
        gate_manager = self.human_gates
        if gate_manager is not None:
            gates = gate_manager.assess(task_dict, self._gate_context(opp))
            result.gates = [g.to_dict() for g in gates]
            pending = [g for g in gates if not g.cleared]
            approved_set = set(clear_gates or [])
            # Clear gates the human explicitly approved this call.
            still_pending = []
            for g in pending:
                if g.gate_type.value in approved_set:
                    g.cleared = True
                else:
                    still_pending.append(g)
            if still_pending:
                result.status = "await_approval"
                result.error = "; ".join(g.description for g in still_pending)
                self._set_portfolio_status(opp_id, "AWAITING_APPROVAL",
                                           blocked_reason=result.error)
                self._record_lifecycle(opp_id, "queued", "awaiting human approval")
                return result

        # 4) Local submission package (no network).
        submission = workspace.submit()
        result.submission_package = submission

        # 5) Evidence: local submission record (NOT payment).
        evidence_id = self._record_submission_evidence(opp, opp_id, result)
        result.evidence_id = evidence_id

        # 6) Lifecycle + portfolio: submitted, NOT paid.
        self._record_lifecycle(opp_id, "submitted", "deliverable packaged locally")
        self._set_portfolio_status(opp_id, "WAITING_EXTERNAL",
                                   waiting_reason="submitted, awaiting response")
        result.status = "approved"
        result.lifecycle_stage = "submitted"
        return result

    # ── side effects (best-effort, never break the return) ──────────────────
    def _fail(self, result: EarningCapabilityResult, message: str) -> EarningCapabilityResult:
        result.status = "failed"
        result.error = message
        self._log(f"[Capability] {message}")
        return result

    def _set_portfolio_status(self, opp_id: str, status: str,
                              blocked_reason: str = "",
                              waiting_reason: str = "") -> None:
        if self.portfolio is None:
            return
        try:
            entry = self.portfolio.get(opp_id)
            if entry is None:
                return
            from agents.opportunity_portfolio import WorkStatus
            entry.work_status = WorkStatus(status)
            entry.updated_at = time.time()
            if blocked_reason:
                entry.blocked_reason = blocked_reason
            if waiting_reason:
                entry.waiting_reason = waiting_reason
            self.portfolio.add(entry)
        except Exception as exc:
            self._log(f"[Capability] portfolio sync failed: {exc}")

    def _record_lifecycle(self, opp_id: str, stage: str, note: str) -> None:
        if self.lifecycle is None:
            return
        try:
            if stage == "submitted":
                self.lifecycle.mark_submitted(opp_id, note=note)
            elif stage == "queued":
                self.lifecycle.mark_queued(opp_id, note=note)
        except Exception as exc:
            self._log(f"[Capability] lifecycle update failed: {exc}")

    def _record_submission_evidence(self, opp: Any, opp_id: str,
                                    result: EarningCapabilityResult) -> str:
        if self.evidence_store is None:
            return ""
        try:
            from agents.evidence import Evidence, VerificationLevel
            ev = Evidence.create(
                source="earning_capability",
                evidence_type="platform_submission",
                subject_type="opportunity",
                subject_id=opp_id,
                external_id=getattr(opp, "external_id", "") or "",
                amount=float(getattr(opp, "advertised_amount", 0.0) or 0.0),
                currency=getattr(opp, "payment_currency", "usd") or "usd",
                verification_method="local_record",
                verification_level=VerificationLevel.L1_SELF_REPORTED,
                provenance={"producer": "earning_capability", "stage": "submit"},
                metadata={
                    "submitted": True,
                    "workspace": result.workspace_dir,
                    "files": result.files,
                    "task_type": self._task_type(opp),
                },
            )
            self.evidence_store.record(ev)
            return ev.id
        except Exception as exc:
            self._log(f"[Capability] evidence record failed: {exc}")
            return ""


__all__ = ["EarningCapabilityExecutor", "EarningCapabilityResult"]
