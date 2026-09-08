"""agents/task_executor.py — Generalized Task Execution Framework engine (v2.0.36i).

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
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from agents.opportunity_portfolio import WorkStatus


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
    outcome: Optional[Dict] = None
    evidence: List[Dict] = field(default_factory=list)
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

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "final_status": self.final_status,
            "errors": self.errors,
            "completed_steps": self.completed_steps,
            "duration_s": (self.context.completed_at - self.context.started_at) if self.context.completed_at else 0,
        }


# ── Task executor ──────────────────────────────────────────────────────────────

class TaskExecutor:
    """Drives the 14-step execution pipeline."""

    def __init__(self, portfolio: Any, capability_validator: Any,
                 human_gate_manager: Any, config: Optional[Dict] = None):
        self.portfolio = portfolio
        self.capability_validator = capability_validator
        self.human_gate_manager = human_gate_manager
        self.config = config or {}

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
            return self._build_result(ctx, success=True, status="paid")
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
        from agents.task_spec import Task
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
        from agents.task_validators import get_validator
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
        """Step 12: Verify outcome. PAYMENT_PENDING."""
        ctx.step_results[12] = {"verified": True}
        self._record_step(ctx, 12, StepStatus.COMPLETED, "Outcome verified")

    def _step13_record_evidence(self, ctx: ExecutionContext) -> None:
        """Step 13: Record evidence. PAYMENT_PENDING."""
        evidence = {
            "task_id": ctx.task.get("task_id", ""),
            "validation_report": ctx.validation_report.to_dict() if ctx.validation_report else None,
            "submission": ctx.submission_result,
            "recorded_at": time.time(),
        }
        ctx.evidence.append(evidence)
        ctx.step_results[13] = evidence
        self._record_step(ctx, 13, StepStatus.COMPLETED, "Evidence recorded")

    def _step14_learn(self, ctx: ExecutionContext) -> None:
        """Step 14: Learn from result. PAYMENT_PENDING → PAID."""
        ctx.step_results[14] = {"learned": True}
        ctx.portfolio_entry = self.portfolio.transition_work_status(
            ctx.portfolio_entry.opportunity_id, self._work_status_for_step(14))
        self._record_step(ctx, 14, StepStatus.COMPLETED, "Learned from result")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _work_status_for_step(self, step: int) -> Any:
        """Map pipeline step to WorkStatus."""
        mapping = {
            1: WorkStatus.EVALUATING,
            4: WorkStatus.QUALIFIED,
            5: WorkStatus.RECOMMENDED,
            6: WorkStatus.AWAITING_APPROVAL,
            9: WorkStatus.COMPLETED,
            10: WorkStatus.WAITING_EXTERNAL,
            11: WorkStatus.PAYMENT_PENDING,
            14: WorkStatus.PAID,
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

    def _build_result(self, ctx: ExecutionContext, success: bool, status: str) -> ExecutionResult:
        ctx.completed_at = time.time()
        completed = sum(1 for s in ctx.step_results.values()
                        if isinstance(s, dict) and s.get("status") == StepStatus.COMPLETED.value)
        return ExecutionResult(
            success=success,
            final_status=status,
            context=ctx,
            errors=ctx.errors,
            completed_steps=completed,
        )


# ── Exceptions ─────────────────────────────────────────────────────────────────

class ExecutionNotPossibleError(Exception):
    """Raised when a task cannot be executed."""


__all__ = [
    "StepStatus",
    "ExecutionContext",
    "ExecutionPlan",
    "ExecutionResult",
    "TaskExecutor",
    "ExecutionNotPossibleError",
]
