"""agents/services/task_executor.py — Generalized Task Execution Framework engine (v2.0.36i).

Drives a 14-step execution pipeline through deterministic validators and human gates,
moving a PortfolioEntry through WorkStatus transitions. The LLM may suggest; deterministic
validators decide completion.

14-step pipeline:
1  Inspect requirements          NEW → EVALUATING
2  Identify required capabilities EVALUATING
3  Identify available tools      EVALUATING
4  Determine whether execution possible EVALUATING → QUALIFIED
5  Create execution plan         QUALIFIED → RECOMMENDED
6  Identify required human actions RECOMMENDED → AWAITING_APPROVAL (if human needed)
7  Execute authorized operations AWAITING_APPROVAL → READY → IN_PROGRESS
8  Validate output               IN_PROGRESS
9  Prepare deliverables          IN_PROGRESS → COMPLETED
10 Submit through channel        COMPLETED → WAITING_EXTERNAL
11 Wait for acceptance/payment   WAITING_EXTERNAL → PAYMENT_PENDING
12 Verify outcome                PAYMENT_PENDING
13 Record evidence               PAYMENT_PENDING
14 Learn from result             PAYMENT_PENDING → PAID

ARCH-ENG-158 — steps 12/14 could not verify a payment, so they asserted one.

Steps 12 and 14 previously wrote ``step_results[12] = {"verified": True}`` as a
literal and then transitioned the portfolio to ``WorkStatus.PAID`` at step 14 with
no evidence of any kind. The pipeline therefore reported a completed, paid
opportunity for any task that reached step 11 — which is every task with no human
gate. That is precisely the shape `agents/safety/handlers.py::_is_approved` and
`OpportunityLifecycleTracker._is_verified_evidence` were hardened to refuse
(ARCH-ENG-064/118/119/121): the caller asserting its own claim, dressed as a
verification.

Both steps now consult a real `EvidenceStore` and the shared evidence policy. The
portfolio only reaches PAID when a real `Evidence` satisfies the same
`SUBMITTED->PAID` / `CLAIMED->REVENUE_REALIZED` contract that
`AutonomousLoop._stage_verify` enforces, and the satisfying `Evidence` object is
carried on `ExecutionResult.evidence` rather than a boolean.

With no evidence store wired, or no qualifying evidence, the pipeline fails
CLOSED: step 12 records why, step 14 leaves the entry in PAYMENT_PENDING, and the
result reports ``final_status="payment_unverified"``. `WorkStatus.PAID` is no
longer reachable from this module without independent proof of payment.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from agents.earning.opportunity_portfolio import WorkStatus


# ── Step status ────────────────────────────────────────────────────────────────

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


# ── Execution context ──────────────────────────────────────────────────────────

@dataclass
class ExecutionContext:
    """Tracks state through the 14-step pipeline."""
    task: Dict[str, Any] = field(default_factory=dict)
    portfolio_entry: Optional[Any] = None
    capability_verdict: Optional[Any] = None
    execution_plan: Optional["ExecutionPlan"] = None
    human_gates: List[Any] = field(default_factory=list)
    validation_report: Optional[Any] = None
    deliverable: Optional[Dict] = None
    submission_result: Optional[Dict] = None
    # ARCH-ENG-158: the step-12 payment verdict. Populated by `_step12_verify`;
    # `paid` here is the sole licence for a PAID transition.
    outcome: Optional[Dict[str, Any]] = None
    # Real `Evidence` objects only (never hand-built dicts).
    evidence: List[Any] = field(default_factory=list)
    current_step: int = 0
    step_results: Dict[int, Dict] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0


# ── Execution plan ─────────────────────────────────────────────────────────────

@dataclass
class ExecutionPlan:
    """Plan for executing a task."""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    human_actions: List[str] = field(default_factory=list)
    estimated_effort: float = 0.0
    validation_method: str = ""

    def to_dict(self) -> dict:
        return {
            "steps": self.steps,
            "required_capabilities": self.required_capabilities,
            "human_actions": self.human_actions,
            "estimated_effort": self.estimated_effort,
            "validation_method": self.validation_method,
        }


# ── Execution result ───────────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    """Final result of execution."""
    success: bool
    final_status: str
    context: ExecutionContext
    errors: List[str] = field(default_factory=list)
    completed_steps: int = 0
    # ARCH-ENG-158: True only when a real `Evidence` satisfied the payment
    # policy. This is the ONLY field that may license `final_status == "paid"`.
    paid: bool = False
    # The `Evidence` object(s) that satisfied the gate. Empty when unpaid.
    evidence: List[Any] = field(default_factory=list)
    # Human-readable reason the payment gate was or was not satisfied.
    payment_status: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "final_status": self.final_status,
            "paid": self.paid,
            "payment_status": self.payment_status,
            "errors": self.errors,
            "completed_steps": self.completed_steps,
            "duration_s": (self.context.completed_at - self.context.started_at) if self.context.completed_at else 0,
        }


# ── Task executor ──────────────────────────────────────────────────────────────

class TaskExecutor:
    """Drives the 14-step execution pipeline."""

    def __init__(self, portfolio: Any, capability_validator: Any,
                 human_gate_manager: Any, config: Optional[Dict] = None,
                 evidence_store: Any = None):
        self.portfolio = portfolio
        self.capability_validator = capability_validator
        self.human_gate_manager = human_gate_manager
        self.config = config or {}
        # ARCH-ENG-158: the source of truth for step 12. Deliberately optional so
        # existing construction sites keep working — but a missing store can only
        # ever produce an UNVERIFIED outcome (fail closed), never a paid one.
        self.evidence_store = evidence_store

    # ── Main entry ─────────────────────────────────────────────────────────────

    def execute(self, task: Dict[str, Any], entry: Any) -> ExecutionResult:
        """Run the 14-step pipeline for a task."""
        ctx = ExecutionContext(task=task, portfolio_entry=entry)
        ctx.current_step = 1

        try:
            ctx.current_step = 1
            self._step1_inspect_requirements(ctx)
            ctx.current_step = 2
            self._step2_identify_capabilities(ctx)
            ctx.current_step = 3
            self._step3_identify_tools(ctx)
            ctx.current_step = 4
            self._step4_determine_feasibility(ctx)
            ctx.current_step = 5
            self._step5_create_plan(ctx)
            ctx.current_step = 6
            self._step6_identify_human_actions(ctx)
            # If human gates, STOP here
            if ctx.human_gates:
                self._record_step(ctx, 6, StepStatus.BLOCKED, "Human gates required")
                return self._build_result(ctx, success=False, status="awaiting_approval")
            ctx.current_step = 7
            self._step7_execute(ctx)
            ctx.current_step = 8
            self._step8_validate(ctx)
            if ctx.validation_report and not ctx.validation_report.passed:
                self._record_step(ctx, 8, StepStatus.FAILED, "Validation failed")
                return self._build_result(ctx, success=False, status="blocked")
            ctx.current_step = 9
            self._step9_prepare_deliverables(ctx)
            ctx.current_step = 10
            self._step10_submit(ctx)
            ctx.current_step = 11
            self._step11_wait(ctx)
            ctx.current_step = 12
            self._step12_verify(ctx)
            ctx.current_step = 13
            self._step13_record_evidence(ctx)
            ctx.current_step = 14
            self._step14_learn(ctx)
            # ARCH-ENG-158: the terminal status is a function of what step 12
            # actually proved, not of how far the pipeline walked. Reaching step
            # 14 is not evidence of payment. `_step12_verify` already recorded
            # its own status (BLOCKED / FAILED / COMPLETED); do not overwrite it.
            if ctx.outcome and ctx.outcome.get("paid"):
                return self._build_result(ctx, success=True, status="paid")
            reason = (ctx.outcome or {}).get("reason", "no qualifying payment evidence")
            return self._build_result(
                ctx, success=True, status="payment_unverified", detail=reason)
        except Exception as e:
            ctx.errors.append(str(e))
            return self._build_result(ctx, success=False, status="failed")

    # ── Step implementations ───────────────────────────────────────────────────

    def _step1_inspect_requirements(self, ctx: ExecutionContext) -> None:
        """Step 1: Inspect requirements. NEW → EVALUATING."""
        task = ctx.task
        requirements = {
            "task_type": task.get("task_type", ""),
            "description": task.get("description", ""),
            "required_capabilities": task.get("required_capabilities", []),
            "inputs": task.get("inputs", []),
            "expected_outputs": task.get("expected_outputs", []),
        }
        ctx.step_results[1] = {"requirements": requirements}
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, self._work_status_for_step(1))
        self._record_step(ctx, 1, StepStatus.COMPLETED, "Requirements inspected")

    def _step2_identify_capabilities(self, ctx: ExecutionContext) -> None:
        """Step 2: Identify required capabilities."""
        task = ctx.task
        capabilities = task.get("required_capabilities", [])
        ctx.step_results[2] = {"capabilities": capabilities}
        self._record_step(ctx, 2, StepStatus.COMPLETED, f"Capabilities: {capabilities}")

    def _step3_identify_tools(self, ctx: ExecutionContext) -> None:
        """Step 3: Identify available tools."""
        # Tools are derived from the capability registry
        tools = []
        for cap in ctx.task.get("required_capabilities", []):
            spec = self.capability_validator.registry.get(cap)
            if spec and spec.tool:
                tools.append(spec.tool)
        ctx.step_results[3] = {"tools": list(set(tools))}
        self._record_step(ctx, 3, StepStatus.COMPLETED, f"Tools: {tools}")

    def _step4_determine_feasibility(self, ctx: ExecutionContext) -> None:
        """Step 4: Determine whether execution is possible. EVALUATING → QUALIFIED."""
        from agents.earning.spec import Task
        task_obj = Task(
            task_type=ctx.task.get("task_type", ""),
            required_capabilities=ctx.task.get("required_capabilities", []),
        )
        verdict = self.capability_validator.validate(task_obj)
        ctx.capability_verdict = verdict
        ctx.step_results[4] = {"verdict": verdict.verdict, "is_executable": verdict.is_executable}
        if not verdict.is_executable:
            self._record_step(ctx, 4, StepStatus.FAILED, f"Not executable: {verdict.explanation}")
            raise ExecutionNotPossibleError(f"Task not executable: {verdict.explanation}")
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, self._work_status_for_step(4))
        self._record_step(ctx, 4, StepStatus.COMPLETED, f"Feasible: {verdict.verdict}")

    def _step5_create_plan(self, ctx: ExecutionContext) -> None:
        """Step 5: Create execution plan. QUALIFIED → RECOMMENDED."""
        plan = ExecutionPlan(
            required_capabilities=ctx.task.get("required_capabilities", []),
            estimated_effort=ctx.task.get("estimated_effort", 0.0),
            validation_method=ctx.task.get("validation_method", ""),
            steps=[
                {"step": 7, "description": "Execute authorized operations"},
                {"step": 8, "description": "Validate output"},
                {"step": 9, "description": "Prepare deliverables"},
                {"step": 10, "description": "Submit through channel"},
            ],
        )
        ctx.execution_plan = plan
        ctx.step_results[5] = plan.to_dict()
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, self._work_status_for_step(5))
        self._record_step(ctx, 5, StepStatus.COMPLETED, "Execution plan created")

    def _step6_identify_human_actions(self, ctx: ExecutionContext) -> None:
        """Step 6: Identify required human actions. RECOMMENDED → AWAITING_APPROVAL."""
        gates = self.human_gate_manager.assess(ctx.task, {})
        ctx.human_gates = gates
        ctx.step_results[6] = {"gates": [g.to_dict() for g in gates]}
        if gates:
            ctx.portfolio_entry = self.portfolio.transition_work_status(
                ctx.portfolio_entry.opportunity_id, self._work_status_for_step(6))
            self._record_step(ctx, 6, StepStatus.BLOCKED, f"Human gates: {[g.gate_type.value for g in gates]}")
        else:
            self._record_step(ctx, 6, StepStatus.COMPLETED, "No human gates required")

    def _step7_execute(self, ctx: ExecutionContext) -> None:
        """Step 7: Execute authorized operations. AWAITING_APPROVAL → READY → IN_PROGRESS."""
        # Transition through READY to IN_PROGRESS
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, WorkStatus.READY)
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, WorkStatus.IN_PROGRESS)
        ctx.step_results[7] = {"executed": True}
        self._record_step(ctx, 7, StepStatus.COMPLETED, "Operations executed")

    def _step8_validate(self, ctx: ExecutionContext) -> None:
        """Step 8: Validate output. IN_PROGRESS."""
        from agents.earning.validators import get_validator
        validator = get_validator(ctx.task.get("task_type", ""))
        output = ctx.task.get("output", {})
        report = validator.validate(ctx.task, output, {})
        ctx.validation_report = report
        ctx.step_results[8] = report.to_dict()
        status = StepStatus.COMPLETED if report.passed else StepStatus.FAILED
        self._record_step(ctx, 8, status, f"Validation: {'passed' if report.passed else 'failed'}")

    def _step9_prepare_deliverables(self, ctx: ExecutionContext) -> None:
        """Step 9: Prepare deliverables. IN_PROGRESS → COMPLETED."""
        deliverable = {
            "task_type": ctx.task.get("task_type", ""),
            "output": ctx.task.get("output", {}),
            "validation": ctx.validation_report.to_dict() if ctx.validation_report else None,
            "prepared_at": time.time(),
        }
        ctx.deliverable = deliverable
        ctx.step_results[9] = deliverable
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, self._work_status_for_step(9))
        self._record_step(ctx, 9, StepStatus.COMPLETED, "Deliverables prepared")

    def _step10_submit(self, ctx: ExecutionContext) -> None:
        """Step 10: Submit through appropriate channel. COMPLETED → WAITING_EXTERNAL."""
        submission = {
            "channel": ctx.task.get("submission_channel", "default"),
            "submitted_at": time.time(),
            "deliverable_ref": id(ctx.deliverable),
        }
        ctx.submission_result = submission
        ctx.step_results[10] = submission
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, self._work_status_for_step(10))
        self._record_step(ctx, 10, StepStatus.COMPLETED, "Submitted")

    def _step11_wait(self, ctx: ExecutionContext) -> None:
        """Step 11: Wait for external acceptance/payment. WAITING_EXTERNAL → PAYMENT_PENDING."""
        ctx.step_results[11] = {"waited": True}
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, self._work_status_for_step(11))
        self._record_step(ctx, 11, StepStatus.COMPLETED, "Waiting for acceptance")

    def _step12_verify(self, ctx: ExecutionContext) -> None:
        """Step 12: Verify outcome. PAYMENT_PENDING.

        ARCH-ENG-158: this used to write ``{"verified": True}`` unconditionally.
        It now resolves real `Evidence` for this opportunity and applies the
        shared evidence policy — the same `SUBMITTED->PAID` /
        `CLAIMED->REVENUE_REALIZED` contract enforced by
        `AutonomousLoop._stage_verify` and `evidence_policy.is_transition_eligible`.

        Fails CLOSED: a missing store, a query error, or an empty result set all
        resolve to `paid=False` with a recorded reason. Nothing here consults the
        caller, the task dict, or the submission receipt.
        """
        opportunity_id = _entry_id(ctx)
        verdict = {"paid": False, "evidence": [], "reason": "", "amount": 0.0,
                   "opportunity_id": opportunity_id}

        store = self.evidence_store
        if store is None or not hasattr(store, "for_subject"):
            verdict["reason"] = ("no evidence store wired to the executor; "
                                 "payment cannot be verified")
            ctx.outcome = verdict
            ctx.step_results[12] = {"verified": False, "reason": verdict["reason"]}
            self._record_step(ctx, 12, StepStatus.BLOCKED, verdict["reason"])
            return

        try:
            from agents.evidence.evidence import EvidenceStatus, VerificationLevel
            from agents.evidence.evidence_policy import is_transition_eligible
            from agents.earning.payment_evidence import TRANSITION_PAYMENT_EVIDENCE_TYPES

            evidence = list(store.for_subject("opportunity", opportunity_id))
            verdict["evidence_found"] = len(evidence)

            if not evidence:
                verdict["reason"] = "no evidence recorded for this opportunity"
                ctx.outcome = verdict
                ctx.step_results[12] = {"verified": False, "reason": verdict["reason"]}
                self._record_step(ctx, 12, StepStatus.FAILED, verdict["reason"])
                return

            eligible = (
                is_transition_eligible("SUBMITTED->PAID", evidence)
                or is_transition_eligible("CLAIMED->REVENUE_REALIZED", evidence)
            )

            qualifying = []
            for ev in evidence:
                # Status and level must be carried by the record itself. A dict
                # or a bare `{"verified": True}` cannot reach here: `for_subject`
                # only ever returns `Evidence` instances.
                if ev.evidence_type in TRANSITION_PAYMENT_EVIDENCE_TYPES:
                    if (ev.status == EvidenceStatus.VERIFIED
                            and ev.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE):
                        qualifying.append(ev)

            if eligible and qualifying:
                verdict["paid"] = True
                verdict["evidence"] = qualifying
                verdict["amount"] = sum(float(getattr(ev, "amount", 0) or 0)
                                        for ev in qualifying)
                verdict["reason"] = (
                    f"{len(qualifying)} payment evidence record(s) at "
                    f">=L3_EXTERNAL_SOURCE satisfied the SUBMITTED->PAID policy")
            else:
                if not eligible:
                    verdict["reason"] = (
                        "evidence exists but does not satisfy the SUBMITTED->PAID "
                        "policy (missing/under-verified required types)")
                else:
                    verdict["reason"] = (
                        "no payment evidence at VERIFIED and >=L3_EXTERNAL_SOURCE")
                ctx.step_results[12] = {"verified": False, "reason": verdict["reason"]}
                self._record_step(ctx, 12, StepStatus.FAILED, verdict["reason"])
                ctx.outcome = verdict
                return

            ctx.outcome = verdict
            ctx.step_results[12] = {
                "verified": True,
                "reason": verdict["reason"],
                "amount": verdict["amount"],
                "evidence_ids": [getattr(ev, "id", "") for ev in qualifying],
            }
            self._record_step(ctx, 12, StepStatus.COMPLETED, verdict["reason"])

        except Exception as e:  # a policy/store error is never a successful payout
            verdict["paid"] = False
            verdict["reason"] = f"evidence check failed: {e}"
            ctx.outcome = verdict
            ctx.step_results[12] = {"verified": False, "reason": verdict["reason"]}
            self._record_step(ctx, 12, StepStatus.FAILED, verdict["reason"])

    def _step13_record_evidence(self, ctx: ExecutionContext) -> None:
        """Step 13: Record evidence. PAYMENT_PENDING.

        ARCH-ENG-158: this step used to build a hand-rolled dict
        (``{"task_id", "validation_report", "submission", "recorded_at"}``) and
        append it to an in-memory list that nothing ever read. It looked like
        evidence, and a dict is exactly the shape the payment gate refuses
        (`handlers._is_approved`: "a hand-built dict is itself agent-supplied").

        It now records only real `Evidence` objects that already exist, and
        persists anything not yet stored. It never manufactures a payment record.
        """
        recorded: List[Any] = []
        try:
            store = self.evidence_store
            pending = [ev for ev in (ctx.evidence or [])
                       if hasattr(ev, "evidence_type") and hasattr(ev, "dup_key")]
            if pending and store is not None and hasattr(store, "record"):
                for ev in pending:
                    recorded.append(store.record(ev))
            elif pending:
                recorded.extend(pending)
            ctx.evidence = recorded
            ctx.step_results[13] = {
                "recorded_count": len(recorded),
                "evidence_ids": [getattr(ev, "id", "") for ev in recorded],
                "note": ("no new evidence was produced by this run; step 12 "
                         "resolved any pre-existing records from the store"),
            }
            self._record_step(ctx, 13, StepStatus.COMPLETED,
                              f"Recorded {len(recorded)} evidence record(s)")
        except Exception as e:
            ctx.step_results[13] = {"recorded_count": 0, "error": str(e)}
            self._record_step(ctx, 13, StepStatus.FAILED,
                              f"Evidence recording failed: {e}")

    def _step14_learn(self, ctx: ExecutionContext) -> None:
        """Step 14: Learn from result. PAYMENT_PENDING → PAID.

        ARCH-ENG-158: the PAID transition is now conditional on step 12 having
        proved payment with real evidence. Previously this step wrote
        ``{"learned": True}`` and transitioned to PAID regardless, so any task
        that reached step 11 was marked paid. An unverified outcome stays in
        PAYMENT_PENDING, which is the truthful state.
        """
        outcome = ctx.outcome or {}
        paid = bool(outcome.get("paid"))
        ctx.step_results[14] = {
            "learned": True,
            "paid": paid,
            "reason": outcome.get("reason", ""),
        }
        if paid:
            ctx.portfolio_entry = self.portfolio.transition_work_status(
                ctx.portfolio_entry.opportunity_id, WorkStatus.PAID)
            self._record_step(ctx, 14, StepStatus.COMPLETED,
                              f"Learned from verified payment "
                              f"({outcome.get('amount', 0.0)})")
        else:
            self._record_step(
                ctx, 14, StepStatus.COMPLETED,
                f"Learned from unverified outcome; left in "
                f"{WorkStatus.PAYMENT_PENDING.value} — "
                f"{outcome.get('reason', 'payment not verified')}")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _work_status_for_step(self, step: int) -> Any:
        """Map pipeline step to WorkStatus.

        ARCH-ENG-158: step 14 no longer maps to PAID. A blanket step→status
        table made "the pipeline reached step 14" indistinguishable from "payment
        was proven", so the caller could not express the difference. Step 14 now
        picks its status from the step-12 verdict and applies PAID itself.
        """
        mapping = {
            1: WorkStatus.EVALUATING,
            4: WorkStatus.QUALIFIED,
            5: WorkStatus.RECOMMENDED,
            6: WorkStatus.AWAITING_APPROVAL,
            9: WorkStatus.COMPLETED,
            10: WorkStatus.WAITING_EXTERNAL,
            11: WorkStatus.PAYMENT_PENDING,
        }
        return mapping.get(step, WorkStatus.EVALUATING)

    def _record_step(self, ctx: ExecutionContext, step: int, status: StepStatus,
                     detail: str) -> None:
        # Merge with existing step data to avoid overwriting detailed results
        existing = ctx.step_results.get(step, {})
        if isinstance(existing, dict):
            existing["status"] = status.value
            existing["detail"] = detail
            ctx.step_results[step] = existing
        else:
            ctx.step_results[step] = {"status": status.value, "detail": detail}

    def _build_result(self, ctx: ExecutionContext, success: bool, status: str,
                      detail: str = "") -> ExecutionResult:
        ctx.completed_at = time.time()
        completed = sum(1 for s in ctx.step_results.values()
                        if isinstance(s, dict) and s.get("status") == StepStatus.COMPLETED.value)
        outcome = ctx.outcome or {}
        paid = bool(outcome.get("paid")) and status == "paid"
        return ExecutionResult(
            success=success,
            final_status=status,
            context=ctx,
            errors=ctx.errors,
            completed_steps=completed,
            paid=paid,
            evidence=list(outcome.get("evidence") or []),
            payment_status=detail or str(outcome.get("reason", "")),
        )


# ── Exceptions ─────────────────────────────────────────────────────────────────

class ExecutionNotPossibleError(Exception):
    """Raised when a task cannot be executed."""


def _entry_id(ctx: ExecutionContext) -> str:
    """Best-effort opportunity id for the entry under execution.

    The pipeline carries `opportunity_id` on the portfolio entry; the task dict is
    only a fallback. An empty id is legitimate — it simply matches no evidence,
    which fails closed.
    """
    entry = ctx.portfolio_entry
    oid = getattr(entry, "opportunity_id", "") or ""
    if not oid:
        oid = str(ctx.task.get("opportunity_id", "") or "")
    if not oid:
        oid = str(ctx.task.get("task_id", "") or "")
    return oid


__all__ = [
    "StepStatus",
    "ExecutionContext",
    "ExecutionPlan",
    "ExecutionResult",
    "TaskExecutor",
    "ExecutionNotPossibleError",
]
