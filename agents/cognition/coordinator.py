"""
agents/dual_brain_coordinator.py — Canonical cross-model collaboration (v2.1).

Coordinates the two brain roles through a typed, durable, cycle-safe handoff on
the EventBus, persisting every stage to the MessageLog. The coordinator performs
structured handoffs — plan → research → review → execute — NOT unconstrained
model-to-model chat.

Stage → role (override-able via ``STAGE_ROLES`` for tests / custom routing):
    plan      → Big Brain  (deep planning, multi-step reasoning)
    research  → Small Brain (fast gather / summarise / triage)
    review    → Big Brain  (fact-check, red-flag, feasibility)
    execute   → Small Brain (narrow, pre-approved action)

Design invariants
-----------------
- Deterministic orchestration: the app injects a ``model_fn(role, stage, prompt)``
  callable; the coordinator never talks to a provider directly. In tests this is
  a fake, so the whole protocol is verifiable with no network/model.
- Every stage publishes a typed REQUEST then a typed RESULT on the EventBus and
  persists both to the MessageLog (durable, observable, correlated).
- Loop prevention is inherited from the bus (self-loop + cycle detection + dedup).
- A run ledger records each stage's owner, model, latency, and outcome so a GUI
  Collaboration/Run monitor can render it without reading model internals.

``collaborate(goal)`` returns a RunRecord (with per-stage results). Any stage
failure fails the run and stops the handoff (no fabricated success).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from agents.core.comms import (
    CancellationToken, EventBus, Message, MessageStatus, MessageType,
)
from agents.core.comms_log import MessageLog
from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
from agents.cognition import ThoughtEdge, ThoughtEdgeKind, ThoughtGraph, ThoughtNode, ThoughtNodeKind


class CollaborationStage(str, Enum):
    PLAN = "plan"
    RESEARCH = "research"
    REVIEW = "review"
    EXECUTE = "execute"


# Canonical stage → role routing. Override for tests / custom deployments.
STAGE_ROLES: Dict[CollaborationStage, BrainRole] = {
    CollaborationStage.PLAN: BrainRole.BIG,
    CollaborationStage.RESEARCH: BrainRole.SMALL,
    CollaborationStage.REVIEW: BrainRole.BIG,
    CollaborationStage.EXECUTE: BrainRole.SMALL,
}

STAGE_REQUEST_TYPE: Dict[CollaborationStage, MessageType] = {
    CollaborationStage.PLAN: MessageType.PLAN_REQUEST,
    CollaborationStage.RESEARCH: MessageType.RESEARCH_REQUEST,
    CollaborationStage.REVIEW: MessageType.REVIEW_REQUEST,
    CollaborationStage.EXECUTE: MessageType.EXECUTION_REQUEST,
}

STAGE_RESULT_TYPE: Dict[CollaborationStage, MessageType] = {
    CollaborationStage.PLAN: MessageType.PLAN_RESULT,
    CollaborationStage.RESEARCH: MessageType.RESEARCH_RESULT,
    CollaborationStage.REVIEW: MessageType.REVIEW_RESULT,
    CollaborationStage.EXECUTE: MessageType.EXECUTION_RESULT,
}

# ModelFn: (role, stage, prompt) -> text. Injected by the app; fake in tests.
ModelFn = Callable[[BrainRole, CollaborationStage, str], str]

# Default per-stage prompts (concise, structured).
_STAGE_PROMPTS: Dict[CollaborationStage, str] = {
    CollaborationStage.PLAN:
        "Break this goal into an ordered, verifiable plan with concrete steps.",
    CollaborationStage.RESEARCH:
        "Gather the facts needed to execute the plan. Return concise findings.",
    CollaborationStage.REVIEW:
        "Review the plan and findings for red flags, feasibility, and missing steps.",
    CollaborationStage.EXECUTE:
        "Execute the approved, pre-validated step. Report the concrete outcome.",
}


@dataclass
class StageRun:
    stage: CollaborationStage
    role: BrainRole
    model: str
    prompt: str
    result: str = ""
    success: bool = False
    latency_ms: int = 0
    error: str = ""
    request_id: str = ""
    result_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "role": self.role.value,
            "model": self.model,
            "prompt": self.prompt,
            "result": self.result,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class RunRecord:
    run_id: str
    goal: str
    correlation_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: MessageStatus = MessageStatus.PENDING
    stages: List[StageRun] = field(default_factory=list)
    thought_graph: ThoughtGraph = field(default_factory=ThoughtGraph)
    final_result: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == MessageStatus.DONE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status.value,
            "final_result": self.final_result,
            "error": self.error,
            "stages": [s.to_dict() for s in self.stages],
            "thought_graph": self.thought_graph.to_dict(),
        }


class DualBrainCoordinator:
    """Deterministic, typed, durable handoff orchestrator between the roles."""

    def __init__(self,
                 runtime: Optional[DualBrainRuntime] = None,
                 model_fn: Optional[ModelFn] = None,
                 bus: Optional[EventBus] = None,
                 log: Optional[MessageLog] = None,
                 stage_roles: Optional[Dict[CollaborationStage, BrainRole]] = None):
        self.runtime = runtime or DualBrainRuntime.from_env()
        self.model_fn = model_fn or self._noop_model
        self.bus = bus or EventBus.instance()
        self.log = log or MessageLog(":memory:")
        self.stage_roles = stage_roles or dict(STAGE_ROLES)
        self._lock = threading.RLock()
        self._runs: Dict[str, RunRecord] = {}
        # ARCH-ENG-247 (AN-02): one cancellation token per run, created on
        # demand from the bus. The token is the mechanism the Stop control
        # pulls; `collaborate` consults it before every stage (cooperative
        # cancellation at a safe point -- a stage's model call is
        # synchronous and is not interrupted mid-call).
        self._run_tokens: Dict[str, "CancellationToken"] = {}
        self._active_run_id: Optional[str] = None

    @staticmethod
    def _noop_model(role: BrainRole, stage: CollaborationStage, prompt: str) -> str:
        raise RuntimeError("no model_fn configured for DualBrainCoordinator")

    # ── run ledger ──────────────────────────────────────────────────────────
    def get_run(self, run_id: str) -> Optional[RunRecord]:
        return self._runs.get(run_id)

    def list_runs(self, limit: int = 50) -> List[RunRecord]:
        with self._lock:
            ordered = sorted(self._runs.values(),
                             key=lambda r: r.created_at, reverse=True)
        return ordered[:limit]

    # ── message helpers ─────────────────────────────────────────────────────
    def _record(self, msg: Message, *, cancellable: bool = True) -> None:
        """Persist the message, then publish it on the bus.

        ARCH-ENG-247 (AN-02): this is the bus's first production publisher.
        Before it, the class docstring's claim ("Every stage publishes a
        typed REQUEST then a typed RESULT on the EventBus") was false -- the
        messages were only written to the local MessageLog, so the bus's one
        subscriber (QtEventBridge) and every cancellation token had nothing
        to read. ``cancellable=False`` is used for terminal run updates: an
        operator who cancels still needs to SEE the cancellation.
        """
        try:
            self.log.record(msg)
        except Exception:
            pass  # logging must never break orchestration
        try:
            token = None
            if cancellable:
                with self._lock:
                    token = self._run_tokens.get(msg.correlation_id or "")
            self.bus.publish(msg, token=token)
        except Exception:
            pass  # bus delivery must never break orchestration

    # ── cancellation (ARCH-ENG-247, AN-02) ─────────────────────────────────
    def active_run_id(self) -> Optional[str]:
        with self._lock:
            return self._active_run_id

    def cancel_run(self, run_id: str,
                   reason: str = "cancelled by operator") -> bool:
        """Cancel a run's correlation: remaining deliveries for it are
        refused and ``collaborate`` stops before the next stage.

        Cooperative by design -- a stage's model call is synchronous, so the
        token is consulted at the stage boundary, never mid-call.
        """
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return False
            run.status = MessageStatus.CANCELLED
            run.error = reason
            run.updated_at = time.time()
            correlation_id = run.correlation_id
        self.bus.cancel(correlation_id, reason)
        return True

    def cancel_active_run(self,
                          reason: str = "cancelled by operator") -> bool:
        run_id = self.active_run_id()
        if not run_id:
            return False
        return self.cancel_run(run_id, reason)

    # ── full handoff ────────────────────────────────────────────────────────
    def collaborate(self, goal: str,
                    stages: Optional[List[CollaborationStage]] = None) -> RunRecord:
        """Run the typed plan→research→review→execute handoff for ``goal``.

        Deterministic and cycle-safe: each stage publishes a typed REQUEST +
        RESULT on the bus and persists both. A failed stage fails the run and
        stops the handoff. Returns the run ledger entry (never raises).
        """
        run = RunRecord(
            run_id=uuid.uuid4().hex,
            goal=goal,
            correlation_id=uuid.uuid4().hex,
        )
        run.thought_graph.add_node(
            ThoughtNode("goal", ThoughtNodeKind.GOAL, goal, source="operator")
        )
        token = self.bus.get_token(run.correlation_id)
        with self._lock:
            self._runs[run.run_id] = run
            self._run_tokens[run.correlation_id] = token
            self._active_run_id = run.run_id
        ordered = stages or [s for s in CollaborationStage]
        try:
            for stage in ordered:
                if token.cancelled:
                    # ARCH-ENG-247: cooperative stop at the stage boundary.
                    # The run already carries CANCELLED (cancel_run sets it);
                    # this path also covers a cancel that arrived between
                    # stages, before the next model call would spend money.
                    run.status = MessageStatus.CANCELLED
                    run.error = run.error or "cancelled by operator"
                    run.updated_at = time.time()
                    self._emit(MessageType.AUTONOMOUS_RUN_UPDATE, run)
                    return run
                stage_run = self._run_stage(run, stage)
                run.stages.append(stage_run)
                run.updated_at = time.time()
                if not stage_run.success:
                    run.status = MessageStatus.FAILED
                    run.error = f"{stage.value} stage failed: {stage_run.error or 'unknown error'}"
                    self._emit(MessageType.AUTONOMOUS_RUN_UPDATE, run)
                    return run
            if token.cancelled:
                # A cancel that arrived DURING the last stage has no next
                # boundary to stop at -- but the operator still cancelled the
                # run, and reporting it DONE would overstate the work.
                run.status = MessageStatus.CANCELLED
                run.error = run.error or "cancelled by operator"
                run.updated_at = time.time()
                self._emit(MessageType.AUTONOMOUS_RUN_UPDATE, run)
                return run
            run.status = MessageStatus.DONE
            run.final_result = run.stages[-1].result if run.stages else ""
            run.updated_at = time.time()
            self._emit(MessageType.AUTONOMOUS_RUN_UPDATE, run)
            return run
        finally:
            with self._lock:
                if self._active_run_id == run.run_id:
                    self._active_run_id = None

    def _run_stage(self, run: RunRecord, stage: CollaborationStage) -> StageRun:
        role = self.stage_roles[stage]
        cfg = self.runtime.config(role)
        model = cfg.model or f"{role.value}-model"
        prior_results = []
        for previous in run.stages:
            if previous.success and previous.result:
                prior_results.append(
                    f"[{previous.stage.value.upper()} by {previous.role.value}]\n"
                    f"{previous.result}"
                )
        shared_context = "\n\n".join(prior_results)
        if len(shared_context) > 16000:
            shared_context = shared_context[-16000:]
        handoff = (
            "\n\nSHARED HANDOFF FROM PREVIOUS STAGES:\n" + shared_context
            if shared_context else ""
        )
        prompt = f"{_STAGE_PROMPTS[stage]}\n\nGoal: {run.goal}{handoff}"
        stage_run = StageRun(stage=stage, role=role, model=model, prompt=prompt)
        node_id = f"stage:{stage.value}"
        run.thought_graph.add_node(
            ThoughtNode(node_id, ThoughtNodeKind.CHECK, prompt, source=role.value, status="running")
        )
        if run.stages:
            run.thought_graph.add_edge(ThoughtEdge(
                node_id, f"stage:{run.stages[-1].stage.value}",
                ThoughtEdgeKind.DEPENDS_ON,
                note="current stage depends on prior collaboration handoff",
            ))
        else:
            run.thought_graph.add_edge(ThoughtEdge(
                "goal", node_id, ThoughtEdgeKind.DERIVED_FROM,
                note="stage generated from run goal",
            ))

        req = Message(
            message_type=STAGE_REQUEST_TYPE[stage],
            source="coordinator",
            destination=role.value,
            correlation_id=run.correlation_id,
            payload={
                "run_id": run.run_id, "stage": stage.value,
                "role": role.value, "model": model, "goal": run.goal,
                "prompt": prompt,
            },
        )
        self._record(req)
        stage_run.request_id = req.message_id

        t0 = time.time()
        try:
            text = self.model_fn(role, stage, prompt)
            stage_run.result = text or ""
            stage_run.success = True
        except Exception as exc:  # deterministic failure, not a crash
            stage_run.success = False
            stage_run.error = str(exc)
        run.thought_graph.update_node(
            node_id,
            status="completed" if stage_run.success else "failed",
            text=stage_run.result or stage_run.error or prompt,
        )
        stage_run.latency_ms = int((time.time() - t0) * 1000)

        res = Message(
            message_type=STAGE_RESULT_TYPE[stage],
            source=role.value,
            destination="coordinator",
            correlation_id=run.correlation_id,
            parent_message_id=req.message_id,
            status=MessageStatus.DONE if stage_run.success else MessageStatus.FAILED,
            payload={
                "run_id": run.run_id, "stage": stage.value,
                "role": role.value, "model": model,
                "result": stage_run.result,
                "success": stage_run.success,
                "error": stage_run.error,
                "latency_ms": stage_run.latency_ms,
            },
        )
        self._record(res)
        stage_run.result_id = res.message_id
        return stage_run

    def _emit(self, mtype: MessageType, run: RunRecord) -> None:
        """Publish a terminal/update event about a run (observability).

        Terminal updates are published OUTSIDE the run's cancellation token
        (ARCH-ENG-247): a cancelled run's last word must still reach the
        operator.
        """
        msg = Message(
            message_type=mtype,
            source="coordinator",
            destination="gui",
            correlation_id=run.correlation_id,
            payload={"run": run.to_dict()},
        )
        self._record(msg, cancellable=False)


__all__ = [
    "CollaborationStage",
    "DualBrainCoordinator",
    "RunRecord",
    "StageRun",
    "STAGE_ROLES",
    "STAGE_REQUEST_TYPE",
    "STAGE_RESULT_TYPE",
]
