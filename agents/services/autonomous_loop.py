"""agents/services/autonomous_loop.py — Phase 2: structured explanations + explanation builder."""

from __future__ import annotations

import time
import os
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agents.evidence.provenance import FactStore

logger = logging.getLogger(__name__)


# ── Stage result ────────────────────────────────────────────────────────────────

@dataclass
class StageResult:
    stage: str
    status: str = "pending"
    opportunity_id: str = ""
    duration_s: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


class StageStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass
class AutonomousResult:
    opportunity_id: str = ""
    run_id: str = ""
    status: str = ""          # "" until _begin_run writes it; then RUNNING/DONE
    success: bool = False
    paid: bool = False
    payment_amount: float = 0.0
    decision: str = ""
    decision_reason: str = ""
    duration_s: float = 0.0
    explanation: str = ""
    stages: List[StageResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    facts: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "run_id": self.run_id,
            "status": self.status,
            "success": self.success,
            "paid": self.paid,
            "payment_amount": self.payment_amount,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "duration_s": self.duration_s,
            "explanation": self.explanation,
            "stages": [{
                "stage": s.stage,
                "status": s.status,
                "data": s.data,
                "duration_s": s.duration_s,
                "error": s.error,
            } for s in self.stages],
            "errors": self.errors,
        }


# ── Explanation builder ─────────────────────────────────────────────────────────

class ExplanationBuilder:
    """Builds structured, evidence-based explanations for decisions.

    Produces explanations like:
      "Selected because:
       - strong skill match
       - expected $38/hour net
       - platform acceptance history 24%
       - task category success rate 71%
       - low scam risk
       - low financial exposure
       - estimated 2.5 hours
       - verified payment history for source
       - similar previous tasks succeeded
       Confidence: 0.78"

    Or:
      "Rejected because:
       - estimated $7/hour net
       - historical completion rate 18%
       - high effort
       - payment verification unavailable
       - source reliability poor
       Reason: insufficient expected value."
    """

    def __init__(self, stages: List[StageResult], facts: Any, decision: str, reason: str):
        self.stages = stages
        self.facts = facts
        self.decision = decision
        self.reason = reason

    def build(self) -> str:
        """Build the full explanation string."""
        if self.decision == "proceed":
            return self._build_proceed()
        elif self.decision == "reject":
            return self._build_reject()
        elif self.decision == "await_approval":
            return self._build_await()
        return self.reason

    def _build_proceed(self) -> str:
        """Build explanation for accepted opportunities."""
        lines = ["Selected because:"]

        # Gather data from stages
        eval_data = self._get_stage_data("evaluate")
        econ_data = self._get_stage_data("check_economics")
        risk_data = self._get_stage_data("check_risk")
        rep_data = self._get_stage_data("check_reputation")
        skill_data = self._get_stage_data("check_skill_fit")
        mem_data = self._get_stage_data("check_memory")
        class_data = self._get_stage_data("classify")

        # Skill match
        skill_count = skill_data.get("skill_count", 0)
        if skill_count is not None:
            if skill_count == 0:
                lines.append("- no specific skills required")
            elif skill_count <= 2:
                lines.append(f"- {skill_count} required skill(s) — reasonable match")
            else:
                lines.append(f"- {skill_count} required skills — broad match")

        # Hourly rate
        hourly = econ_data.get("estimated_hourly", 0)
        if hourly and hourly > 0:
            if hourly >= 50:
                lines.append(f"- expected ${hourly:.0f}/hour net — strong return")
            elif hourly >= 20:
                lines.append(f"- expected ${hourly:.0f}/hour net — reasonable")
            elif hourly >= 5:
                lines.append(f"- expected ${hourly:.0f}/hour net — modest")
            else:
                lines.append(f"- expected ${hourly:.0f}/hour net — low")

        # Verdict from evaluation
        verdict_data = eval_data.get("verdict", {})
        if isinstance(verdict_data, dict) and verdict_data:
            verdict = verdict_data.get("verdict", "")
            confidence = verdict_data.get("confidence", 0)
            if verdict:
                lines.append(f"- evaluation verdict: {verdict}")
            if confidence is not None:
                lines.append(f"- confidence: {confidence:.2f}")

        # Platform reputation
        rep = rep_data.get("reputation")
        if rep and isinstance(rep, dict):
            acceptance = rep.get("acceptance_rate")
            completion = rep.get("completion_rate")
            if acceptance is not None:
                if acceptance >= 0.3:
                    lines.append(f"- platform acceptance history {acceptance*100:.0f}%")
                else:
                    lines.append(f"- platform acceptance history {acceptance*100:.0f}% — low")
            if completion is not None:
                if completion >= 0.5:
                    lines.append(f"- platform completion rate {completion*100:.0f}%")
                else:
                    lines.append(f"- platform completion rate {completion*100:.0f}% — low")

        # Risk assessment
        risk_level = risk_data.get("risk_level", "unknown")
        exposure = risk_data.get("financial_exposure", 0)
        if risk_level == "low":
            lines.append("- low scam risk")
        elif risk_level == "medium":
            lines.append("- medium risk — proceed with caution")
        elif risk_level == "high":
            lines.append("- high risk — flagged for review")
        if exposure:
            lines.append(f"- financial exposure: ${exposure:.2f}")

        # Effort
        effort = econ_data.get("estimated_effort", 0)
        if effort and effort > 0:
            lines.append(f"- estimated {effort:.1f} hours")

        # Category/task type success
        category = class_data.get("category", "")
        task_type = class_data.get("task_type", "")
        if category:
            lines.append(f"- category: {category}")
        if task_type:
            lines.append(f"- task type: {task_type}")

        # History
        history_count = mem_data.get("history_count", 0)
        if history_count and history_count > 0:
            lines.append(f"- {history_count} similar previous opportunities in memory")

        # Source verification
        source = class_data.get("source", "")
        if source:
            lines.append(f"- source: {source}")

        # Default if nothing was added
        if len(lines) == 1:
            lines.append("- meets minimum criteria")

        # Confidence line
        verdict_data = eval_data.get("verdict", {})
        if isinstance(verdict_data, dict):
            confidence = verdict_data.get("confidence", 0.5)
            if confidence is not None:
                lines.append(f"Confidence: {confidence:.2f}")

        return "\n".join(lines)

    def _build_reject(self) -> str:
        """Build explanation for rejected opportunities."""
        lines = ["Rejected because:"]

        # Gather data
        eval_data = self._get_stage_data("evaluate")
        econ_data = self._get_stage_data("check_economics")
        risk_data = self._get_stage_data("check_risk")
        rep_data = self._get_stage_data("check_reputation")
        class_data = self._get_stage_data("classify")
        skill_data = self._get_stage_data("check_skill_fit")

        # Low hourly rate
        hourly = econ_data.get("estimated_hourly", 0)
        if hourly is not None and hourly > 0:
            if hourly < 5:
                lines.append(f"- estimated ${hourly:.0f}/hour net — too low")
            elif hourly < 10:
                lines.append(f"- estimated ${hourly:.0f}/hour net — marginal")
        elif hourly == 0:
            lines.append("- no economic value estimated")

        # Low completion rate
        rep = rep_data.get("reputation")
        if rep and isinstance(rep, dict):
            completion = rep.get("completion_rate")
            if completion is not None and completion < 0.3:
                lines.append(f"- historical completion rate {completion*100:.0f}% — poor")
            acceptance = rep.get("acceptance_rate")
            if acceptance is not None and acceptance < 0.1:
                lines.append(f"- platform acceptance rate {acceptance*100:.0f}% — very low")

        # High effort
        effort = econ_data.get("estimated_effort", 0)
        if effort and effort > 10:
            lines.append(f"- high effort: {effort:.1f} hours estimated")

        # Payment verification
        verdict_data = eval_data.get("verdict") or {}
        payment_issues = verdict_data.get("payment_issues", []) if isinstance(verdict_data, dict) else []
        if payment_issues:
            for issue in payment_issues:
                lines.append(f"- payment issue: {issue}")

        # Risk
        risk_level = risk_data.get("risk_level", "unknown")
        if risk_level == "high":
            lines.append("- high scam risk")
        elif risk_level == "medium":
            lines.append("- medium risk — not worth the uncertainty")

        # Source reliability
        source = class_data.get("source", "")
        if source and source in ("unknown", "unverified", ""):
            lines.append("- source reliability unknown")

        # Skill mismatch
        skill_count = skill_data.get("skill_count", 0)
        if skill_count and skill_count > 5:
            lines.append(f"- {skill_count} required skills — heavy skill requirements")

        # Confidence too low
        verdict = eval_data.get("verdict", {}) or {}
        confidence = verdict.get("confidence", 0) if isinstance(verdict, dict) else 0
        if confidence is not None and confidence < 0.3:
            lines.append(f"- low confidence: {confidence:.2f}")

        # Reason
        if self.reason:
            lines.append(f"Reason: {self.reason}")

        if len(lines) == 1:
            lines.append(f"- {self.reason or 'did not meet criteria'}")

        return "\n".join(lines)

    def _build_await(self) -> str:
        """Build explanation for approval-required opportunities."""
        lines = ["Awaiting approval:"]
        econ_data = self._get_stage_data("check_economics")
        risk_data = self._get_stage_data("check_risk")

        payment = econ_data.get("advertised_value", 0)
        if payment:
            lines.append(f"- advertised value: ${payment:.2f} — requires human review")

        risk_level = risk_data.get("risk_level", "unknown")
        if risk_level == "high":
            lines.append("- high risk — human verification required")

        if self.reason:
            lines.append(f"- {self.reason}")

        return "\n".join(lines)

    def _get_stage_data(self, stage_name: str) -> Dict[str, Any]:
        """Get data dict from a specific stage result."""
        for s in self.stages:
            if s.stage == stage_name:
                data = s.data
                if data is None:
                    return {}
                return data
        return {}


# ── Autonomous loop engine ─────────────────────────────────────────────────────

class AutonomousLoop:
    """Drives the unified 24-stage planning loop for a single opportunity.

    Each stage records its result, preserves provenance, and distinguishes
    FACT / ESTIMATE / PREDICTION / OBSERVATION / VERIFIED_RESULT.
    """

    def __init__(self, pipeline: Any, run_store: Any = None):
        self.pipeline = pipeline
        self.memory = getattr(pipeline, 'memory', None)
        self.lifecycle = getattr(pipeline, 'lifecycle', None)
        self.portfolio = getattr(pipeline, 'portfolio', None)
        self.evidence_store = getattr(pipeline, 'evidence_store', None)
        self.accounting = getattr(pipeline, 'accounting', None)
        self.task_executor = getattr(pipeline, 'task_executor', None)
        # v2.1 Phase 3: durable run ledger. Optional; the loop works without it
        # (back-compat with the existing in-memory-only tests), but when injected
        # every run + stage is persisted and made idempotency-safe across restarts.
        self.run_store = run_store
        self.max_concurrent_runs = max(
            0, int(os.getenv("MRBOT_AUTONOMY_MAX_CONCURRENT", "0") or 0))
        self.max_run_seconds = max(
            0.0, float(os.getenv("MRBOT_AUTONOMY_MAX_RUN_SECONDS", "0") or 0))
        self._run_slots = (
            threading.BoundedSemaphore(self.max_concurrent_runs)
            if self.max_concurrent_runs else None
        )
        self._cancel_lock = threading.Lock()
        self._cancelled: set[str] = set()

    # ── Main entry ─────────────────────────────────────────────────────────────

    def cancel(self, opportunity_id: str) -> bool:
        """Request cancellation of a queued or running opportunity."""
        with self._cancel_lock:
            self._cancelled.add(str(opportunity_id))
        return True

    def _check_limits(self, opportunity_id: str, started: float) -> None:
        with self._cancel_lock:
            if str(opportunity_id) in self._cancelled:
                self._cancelled.discard(str(opportunity_id))
                raise RuntimeError("Autonomous run cancelled")
        if self.max_run_seconds and time.monotonic() - started > self.max_run_seconds:
            raise TimeoutError(
                f"Autonomous run exceeded {self.max_run_seconds:.1f}s limit")

    def run(self, opportunity: Any, facts: Any = None) -> AutonomousResult:
        """Run one opportunity subject to configured concurrency limits."""
        opp_id = getattr(opportunity, "id", getattr(opportunity, "opportunity_id", ""))
        if self._run_slots is not None and not self._run_slots.acquire(blocking=False):
            return AutonomousResult(
                opportunity_id=opp_id,
                decision="blocked",
                decision_reason="Autonomy concurrency limit reached",
                errors=["Autonomy concurrency limit reached"],
            )
        try:
            return self._run(opportunity, facts)
        finally:
            if self._run_slots is not None:
                self._run_slots.release()

    def _run(self, opportunity: Any, facts: Any = None) -> AutonomousResult:
        """Run the full 24-stage loop for a single opportunity."""
        opp_id = getattr(opportunity, "id", getattr(opportunity, "opportunity_id", ""))
        result = AutonomousResult(opportunity_id=opp_id)
        t0 = time.time()
        started = time.monotonic()

        if facts is None:
            facts = FactStore(opp_id)

        try:
            # Durable ledger BEFORE any irreversible stage. The row used to be
            # written only in _finalize, so a hard kill after _stage_submit
            # left nothing for recover_incomplete() and a restart happily
            # re-ran the same opportunity — submitting twice. Writing the
            # in-flight row here makes the interruption visible and recoverable.
            # The IDEMPOTENCY KEY is deliberately NOT marked here: an
            # await_approval pause, a rejection, and a transient failure are all
            # legitimately re-entry-able (see _stage_deduplicate). It is marked
            # only once an irreversible action has actually been dispatched.
            if self._replay_guard(opp_id):
                return self._finalize(result, facts, t0, "reject",
                                      "Opportunity already executed an irreversible action")
            self._begin_run(result, opp_id)
            self._check_limits(opp_id, started)
            self._stage_discovered(result, opportunity, facts)
            self._check_limits(opp_id, started)
            if self._stage_deduplicate(result, opportunity, facts) is False:
                return self._finalize(result, facts, t0, "reject",
                                       "Duplicate of existing opportunity")
            self._stage_classify(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_evaluate(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_check_memory(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_check_reputation(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_check_skill_fit(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_check_economics(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_check_risk(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_prioritize(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_plan(result, opportunity, facts)
            self._check_limits(opp_id, started)
            if self._stage_request_approval(result, opportunity, facts):
                return self._finalize(result, facts, t0, "await_approval",
                                       "Human approval required")
            if not self._stage_execute(result, opportunity, facts):
                return self._finalize(result, facts, t0, "failed",
                                      "Task execution was not completed")
            self._check_limits(opp_id, started)
            if self._stage_validate(result, opportunity, facts) is False:
                return self._finalize(result, facts, t0, "reject",
                                       "Validation failed")
            self._stage_submit(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_wait(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_verify(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_account(result, opportunity, facts)
            self._check_limits(opp_id, started)
            # C-1 fix: reaching the end of the pipeline is NOT proof of payment. Decide the
            # outcome BEFORE learn/rerank so those stages see the correct success state.
            # `success` = a terminal non-failure (proceed OR completed_unpaid); the separate
            # `paid` flag (set by _stage_verify) is the only thing that proves revenue.
            if result.paid:
                result.decision = "proceed"
                result.decision_reason = f"Payment verified ({result.payment_amount}) - loop completed"
            else:
                result.decision = "completed_unpaid"
                result.decision_reason = "Stages completed but no verified payment evidence found"
            result.success = result.decision in ("proceed", "completed_unpaid")
            self._stage_learn(result, opportunity, facts)
            self._check_limits(opp_id, started)
            self._stage_rerank(result, opportunity, facts)
            return self._finalize(result, facts, t0, result.decision, result.decision_reason)

        except Exception as e:
            result.errors.append(str(e))
            return self._finalize(result, facts, t0, "failed",
                                   f"Loop error: {e}")

    # ── Stage implementations (abbreviated — full versions in phase 1) ───────

    def _stage_discovered(self, result, opp, facts):
        t0 = time.time()
        from agents.evidence.provenance import TruthStatus, ProvenanceRecord, InfoAtom
        facts.add(InfoAtom(value=getattr(opp, "title", ""), status=TruthStatus.OBSERVATION,
                           key="discovered", provenance=ProvenanceRecord(
                               source=getattr(opp, "source", ""), method="discovery"), confidence=0.9))
        result.stages.append(StageResult(stage="discovered", status=StageStatus.COMPLETED,
                                          opportunity_id=facts.opportunity_id, duration_s=time.time()-t0))

    def _stage_deduplicate(self, result, opp, facts):
        t0 = time.time()
        opp_id = getattr(opp, "id", getattr(opp, "opportunity_id", ""))
        # M-2 fix: dedup must be state-aware, not a blanket "any prior history => block",
        # AND it must read the *outcome* history (the real signal). The previous code
        # called get_opportunity_history() which returns a *dict* (the opportunity
        # memory blob), so `for row in existing` iterated dict KEYS (strings) and
        # `row.get("result")` raised AttributeError on real memory. We now use the
        # outcome history (list of {result, ts, ...}) and only fall back to the
        # opportunity-memory dict (extracting its "history" list) when needed.
        #   - A *terminal success* (paid/completed) stays blocked (don't re-process a win).
        #   - A *prior failure/rejection* is RE-ENTRY-able (recurring gig / transient fail).
        #   - Otherwise (first sight, or only neutral/discovery history) => not a duplicate.
        if self.memory is not None and hasattr(self.memory, 'get_outcome_history'):
            existing = self.memory.get_outcome_history(opp_id) or []
        elif self.memory is not None and hasattr(self.memory, 'get_opportunity_history'):
            raw = self.memory.get_opportunity_history(opp_id) or {}
            existing = raw.get('history', []) if isinstance(raw, dict) else (raw or [])
        else:
            existing = []
        TERMINAL_SUCCESS = {"paid", "completed"}
        last_state = ""
        latest_ts = 0.0
        for row in existing:
            if not isinstance(row, dict):
                continue
            st = row.get("result") or row.get("outcome_state") or ""
            ts = float(row.get("ts", 0.0) or 0.0)
            if ts >= latest_ts:
                latest_ts = ts
                last_state = st
        if last_state in TERMINAL_SUCCESS:
            is_dup = True  # finished win — don't re-process
        else:
            is_dup = False  # first sight, or a prior failure/rejection => allow re-entry
        result.stages.append(StageResult(stage="deduplicate",
            status=StageStatus.BLOCKED if is_dup else StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"is_duplicate": is_dup, "existing_count": len(existing),
                  "last_state": last_state,
                  "memory_available": self.memory is not None},
            duration_s=time.time()-t0))
        return not is_dup

    def _stage_classify(self, result, opp, facts):
        t0 = time.time()
        result.stages.append(StageResult(stage="classify", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"category": getattr(opp, "category", ""), "subcategory": getattr(opp, "subcategory", ""),
                  "task_type": getattr(opp, "task_type", ""), "payment_type": getattr(opp, "payment_type", ""),
                  "source": getattr(opp, "source", ""), "platform": getattr(opp, "platform", "")},
            duration_s=time.time()-t0))

    def _stage_evaluate(self, result, opp, facts):
        t0 = time.time()
        verdict = None
        try:
            from agents.earning.opportunity_intelligence import OpportunityIntelligenceEngine
            engine = OpportunityIntelligenceEngine()
            verdict = engine.evaluate(opp, memory=self.memory)
        except Exception as e:
            result.errors.append(f"Evaluation error: {e}")
        result.stages.append(StageResult(stage="evaluate",
            status=StageStatus.COMPLETED if verdict else StageStatus.FAILED,
            opportunity_id=facts.opportunity_id,
            data={"verdict": verdict.to_dict() if verdict else None}, duration_s=time.time()-t0))

    def _stage_check_memory(self, result, opp, facts):
        t0 = time.time()
        if self.memory is not None and hasattr(self.memory, 'get_opportunity_history'):
            history = self.memory.get_opportunity_history(
                opp.opportunity_id if hasattr(opp, 'opportunity_id') else opp.id) or []
        else:
            history = []
        result.stages.append(StageResult(stage="check_memory", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"history_count": len(history), "platform": getattr(opp, "platform", ""),
                  "category": getattr(opp, "category", ""),
                  "memory_available": self.memory is not None}, duration_s=time.time()-t0))

    def _stage_check_reputation(self, result, opp, facts):
        t0 = time.time()
        platform = getattr(opp, "platform", "")
        if self.memory is not None and hasattr(self.memory, 'get_platform_reputation') and platform:
            rep = self.memory.get_platform_reputation(platform)
        else:
            rep = None
        result.stages.append(StageResult(stage="check_reputation", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"reputation": rep, "memory_available": self.memory is not None},
            duration_s=time.time()-t0))

    def _stage_check_skill_fit(self, result, opp, facts):
        t0 = time.time()
        required = getattr(opp, "required_skills", []) or []
        result.stages.append(StageResult(stage="check_skill_fit", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"required_skills": required, "skill_count": len(required)},
            duration_s=time.time()-t0))

    def _stage_check_economics(self, result, opp, facts):
        t0 = time.time()
        advertised = float(getattr(opp, "advertised_amount", 0) or 0)
        estimated = float(getattr(opp, "estimated_net_value", 0) or 0)
        effort = float(getattr(opp, "estimated_effort", 0) or 0)
        hourly = estimated / effort if effort > 0 else 0.0
        result.stages.append(StageResult(stage="check_economics", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"advertised_value": advertised, "estimated_net_value": estimated,
                  "estimated_effort": effort, "estimated_hourly": hourly},
            duration_s=time.time()-t0))

    def _stage_check_risk(self, result, opp, facts):
        t0 = time.time()
        result.stages.append(StageResult(stage="check_risk", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"risk_level": getattr(opp, "risk_level", "medium"),
                  "financial_exposure": float(getattr(opp, "advertised_amount", 0) or 0)},
            duration_s=time.time()-t0))

    def _stage_prioritize(self, result, opp, facts):
        t0 = time.time()
        # A pipeline may legitimately have no portfolio (the constructor takes
        # any object); every other portfolio-touching stage guards with
        # `is not None`. This one did not, so a portfolio-less pipeline raised
        # AttributeError here and the entire run was reported as a generic
        # "Loop error" instead of completing (ARCH-ENG-058).
        try:
            portfolio_size = (len(self.portfolio.load_all())
                              if self.portfolio is not None else 0)
        except Exception:
            portfolio_size = 0
        result.stages.append(StageResult(stage="prioritize", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"portfolio_size": portfolio_size}, duration_s=time.time()-t0))

    def _stage_plan(self, result, opp, facts):
        t0 = time.time()
        result.stages.append(StageResult(stage="plan", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"steps": ["execute_task", "validate_output", "submit_deliverable"],
                  "estimated_effort": float(getattr(opp, "estimated_effort", 0) or 0)},
            duration_s=time.time()-t0))

    def _stage_request_approval(self, result, opp, facts):
        """Pause the loop for opportunities above the financial-exposure threshold.

        Scope: this is a *financial-exposure* pause, NOT the human-approval gate.
        The gate that actually protects a submission lives downstream in
        ``agents/earning/proposal.py`` (``submit_gig_proposal``): when no
        ``confirm_cb`` is supplied it consults ``SubmissionRamp.requires_human``,
        which forces a human on cold-start, on a low win-rate, and whenever the
        platform's AI policy is not ``ai_allowed`` — and it fails closed with
        ``ramp_human_required`` rather than submitting. Verified by execution:
        a $25 Upwork opportunity routed through this loop's submit path with no
        ``confirm_cb`` never reached the platform client.

        So a sub-threshold opportunity is not "ungated execution" — it is
        "execution that still passes the real gate further down". The threshold
        only decides whether the loop stops early for a large advertised payout.
        """
        t0 = time.time()
        payment = float(getattr(opp, "advertised_amount", 0) or 0)
        needs_approval = payment > 100.0
        result.stages.append(StageResult(stage="request_approval",
            status=StageStatus.BLOCKED if needs_approval else StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"needs_approval": needs_approval, "threshold": 100.0,
                  "scope": "financial_exposure_only",
                  "submission_gate": "agents.earning.proposal.SubmissionRamp"},
            duration_s=time.time()-t0))
        return needs_approval

    def _stage_execute(self, result, opp, facts):
        t0 = time.time()
        executed = False; error = ""
        try:
            if self.task_executor is not None and hasattr(self.task_executor, 'run'):
                from agents.earning.spec import Task
                task = Task(task_type=getattr(opp, "task_type", "GENERAL"),
                    required_capabilities=getattr(opp, "required_skills", []),
                    inputs={"opportunity": opp}, expected_outputs={"execution_result": "task completed"},
                    tools_required=[], estimated_effort=float(getattr(opp, "estimated_effort", 0) or 0),
                    validation_method="deterministic", human_required=False,
                    execution_mode="automated", payment_conditions={})
                exec_result = self.task_executor.run(task)
                self._last_exec_result = exec_result
                executed = exec_result.success
                if not executed:
                    error = "; ".join(exec_result.errors) if exec_result.errors else "execution failed"
            else:
                # Missing execution infrastructure must never become a success.
                error = "no_task_executor"
                executed = False
        except Exception as e:
            error = str(e)
        if self.evidence_store is not None and executed:
            from agents.evidence.evidence import Evidence, VerificationLevel
            ev = Evidence.create(source=getattr(opp, "source", "system"),
                evidence_type="execution_record", subject_type="opportunity",
                subject_id=opp.id or opp.opportunity_id, external_id=getattr(opp, "id", ""),
                amount=float(getattr(opp, "advertised_amount", 0) or 0),
                currency=getattr(opp, "payment_currency", "usd"),
                verification_method="local_record", verification_level=VerificationLevel.L1_SELF_REPORTED,
                provenance={"producer": "autonomous_loop", "stage": "execute"},
                metadata={"executed": True, "task_type": getattr(opp, "task_type", "")})
            try: self.evidence_store.record(ev)
            except Exception: pass
        result.stages.append(StageResult(stage="execute",
            status=StageStatus.COMPLETED if executed else StageStatus.FAILED,
            opportunity_id=facts.opportunity_id, data={"executed": executed, "error": error},
            duration_s=time.time()-t0))
        if not executed: result.errors.append(error or "execution failed")
        return executed

    def _stage_validate(self, result, opp, facts):
        t0 = time.time()
        # Validation must prove a real executor artifact. Missing validators,
        # empty output, and validator errors fail closed rather than becoming
        # a synthetic completion.
        valid = False
        validation_error = ""
        try:
            from agents.earning.validators import get_validator
            validator = get_validator(getattr(opp, "task_type", "GENERAL"))
            if validator is None or not hasattr(validator, "validate"):
                validation_error = "no_validator"
            elif self.task_executor is None or not hasattr(self.task_executor, "run"):
                validation_error = "no_task_executor"
            else:
                exec_result = getattr(self, "_last_exec_result", None)
                output = getattr(exec_result, "output", None) or {}
                if not output:
                    validation_error = "no_executor_output"
                else:
                    report = validator.validate({}, output, {})
                    valid = bool(report.passed)
                    if not valid:
                        validation_error = "validator_rejected_output"
        except Exception as e:
            validation_error = f"validator_error: {e}"
        if not valid:
            result.errors.append(validation_error or "validation failed")
        result.stages.append(StageResult(stage="validate",
            status=StageStatus.COMPLETED if valid else StageStatus.FAILED,
            opportunity_id=facts.opportunity_id,
            data={"valid": valid, "error": validation_error},
            duration_s=time.time()-t0))
        return valid

    def _stage_submit(self, result, opp, facts):
        t0 = time.time()
        submitted = False; error = ""
        try:
            if hasattr(self.pipeline, 'submit_gig_proposal') and callable(self.pipeline.submit_gig_proposal):
                if getattr(opp, "task_type", "") in ("freelance", "coding", "writing"):
                    draft = f"Auto-generated submission for {getattr(opp, 'title', 'opportunity')}"
                    sub_result = self.pipeline.submit_gig_proposal(opp, draft)
                    submitted = sub_result.success if sub_result else False
                    if not submitted: error = sub_result.message if sub_result else "submission failed"
            elif hasattr(self.pipeline, 'execute') and callable(self.pipeline.execute):
                if getattr(opp, "source", "") in ("airdrop", "defi", "faucet"):
                    exec_result = self.pipeline.execute(opp)
                    submitted = exec_result.success if exec_result else False
                    if not submitted: error = exec_result.message if exec_result else "execution failed"
            # else: no submission path available — record as not submitted but don't crash
            if not submitted and not error: error = "no_submission_path"
        except Exception as e:
            error = str(e)
        if self.evidence_store is not None and submitted:
            from agents.evidence.evidence import Evidence, VerificationLevel
            ev = Evidence.create(source=getattr(opp, "source", "system"),
                evidence_type="platform_submission", subject_type="opportunity",
                subject_id=opp.id or opp.opportunity_id, external_id=getattr(opp, "id", ""),
                verification_method="local_record", verification_level=VerificationLevel.L1_SELF_REPORTED,
                provenance={"producer": "autonomous_loop", "stage": "submit"},
                metadata={"submitted": True, "task_type": getattr(opp, "task_type", "")})
            try: self.evidence_store.record(ev)
            except Exception: pass
        result.stages.append(StageResult(stage="submit",
            status=StageStatus.COMPLETED if submitted else StageStatus.FAILED,
            opportunity_id=facts.opportunity_id, data={"submitted": submitted, "error": error},
            duration_s=time.time()-t0))
        if not submitted: result.errors.append(error or "submission failed")
        elif self.run_store is not None:
            # An external commitment now exists. Mark it BEFORE the process can
            # be killed, so a restart's _replay_guard refuses to re-run this
            # opportunity instead of submitting the same work twice.
            self._mark_irreversible(result, getattr(opp, "id", getattr(opp, "opportunity_id", "")))

    def _stage_wait(self, result, opp, facts):
        t0 = time.time()
        result.stages.append(StageResult(stage="wait", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id, data={"waited": True}, duration_s=time.time()-t0))

    def _stage_verify(self, result, opp, facts):
        t0 = time.time()
        verified = False; evidence_found = False; payment_amount = 0.0
        try:
            if self.evidence_store is not None and hasattr(self.evidence_store, 'for_subject'):
                evidence = self.evidence_store.for_subject("opportunity", opp.id or opp.opportunity_id)
                from agents.evidence.evidence import EvidenceStatus, VerificationLevel
                from agents.evidence.evidence_policy import is_transition_eligible
                from agents.earning.payment_evidence import TRANSITION_PAYMENT_EVIDENCE_TYPES
                # Payment evidence alone is not enough. The policy owns the complete
                # transition contract, including submission, completion, payment type,
                # and verification level.
                eligible = (
                    is_transition_eligible("SUBMITTED->PAID", evidence)
                    or is_transition_eligible("CLAIMED->REVENUE_REALIZED", evidence)
                )
                for ev in evidence:
                    if ev.evidence_type in TRANSITION_PAYMENT_EVIDENCE_TYPES:
                        externally_verified = (
                            ev.status == EvidenceStatus.VERIFIED
                            and ev.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE
                        )
                        if externally_verified:
                            evidence_found = True
                        if eligible and externally_verified:
                            verified = True
                            payment_amount += float(getattr(ev, "amount", 0) or 0)
                    elif ev.status == EvidenceStatus.VERIFIED:
                        evidence_found = True
            if verified and self.lifecycle is not None and hasattr(self.lifecycle, 'mark_paid_verified'):
                try:
                    lifecycle_state = self.lifecycle.mark_paid_verified(opp.id or opp.opportunity_id,
                        amount=payment_amount)
                    # Fail CLOSED: if the lifecycle did not actually reach "paid" —
                    # including when it returned None or raised — the payment is NOT
                    # verified. Defaulting the getattr to "paid" here previously
                    # booked unverified payouts as wins (ARCH-ENG-060).
                    verified = getattr(lifecycle_state, "status", "") == "paid"
                except Exception as e:
                    # A lifecycle/DB error must never be read as a successful payout.
                    verified = False
                    result.errors.append(f"Lifecycle paid-verification failed: {e}")
            result.paid = verified
            result.payment_amount = payment_amount
        except Exception as e:
            result.errors.append(f"Verification error: {e}")
        result.stages.append(StageResult(stage="verify",
            status=StageStatus.COMPLETED if (verified or evidence_found) else StageStatus.FAILED,
            opportunity_id=facts.opportunity_id,
            data={"verified": verified, "evidence_found": evidence_found, "paid": result.paid,
                  "payment_amount": payment_amount}, duration_s=time.time()-t0))

    def _stage_account(self, result, opp, facts):
        t0 = time.time()
        profile = None; evidence_recorded = False
        try:
            opp_id = opp.id or opp.opportunity_id
            if self.evidence_store is not None and hasattr(self.evidence_store, 'for_subject'):
                from agents.evidence.evidence import Evidence, EvidenceStatus, VerificationLevel
                from agents.earning.payment_evidence import TRANSITION_PAYMENT_EVIDENCE_TYPES
                existing = self.evidence_store.for_subject("opportunity", opp_id)
                has_verified_payment = any(
                    ev.evidence_type in TRANSITION_PAYMENT_EVIDENCE_TYPES
                    and ev.status == EvidenceStatus.VERIFIED
                    and ev.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE
                    for ev in existing)
                if has_verified_payment:
                    expense_ev = Evidence.create(source="system", evidence_type="payment_llm_cost",
                        subject_type="opportunity", subject_id=opp_id, amount=0.0, currency="usd",
                        verification_method="local_record", verification_level=VerificationLevel.L1_SELF_REPORTED,
                        provenance={"producer": "autonomous_loop", "stage": "account"})
                    try: self.evidence_store.record(expense_ev); evidence_recorded = True
                    except Exception: pass
            if self.accounting is not None and hasattr(self.accounting, 'get_profile'):
                profile = self.accounting.get_profile(opp_id)
        except Exception as e:
            result.errors.append(f"Accounting error: {e}")
        result.stages.append(StageResult(stage="account", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"profile": profile.to_dict() if profile else None, "evidence_recorded": evidence_recorded},
            duration_s=time.time()-t0))

    def _stage_learn(self, result, opp, facts):
        t0 = time.time()
        learned = False
        try:
            # Use the real LearningLoop (feeds FUTURE DISCOVERY). `earning_memory` is a
            # top-level module, NOT under `agents/` — the previous import raised
            # ModuleNotFoundError and silently disabled the entire LEARN stage.
            ll = getattr(self.pipeline, 'learning_loop', None)
            if ll is not None and hasattr(ll, 'process_outcome'):
                opp_id = opp.id or opp.opportunity_id
                ll.process_outcome(
                    opp_id,
                    outcome_state="paid" if result.paid else ("completed" if result.success else "failed"),
                    # C-1 fix: revenue is only the verified payment amount; otherwise 0.0 so the
                    # learning loop never records unearned revenue (stops false success signals).
                    revenue=result.payment_amount if result.paid else 0.0,
                    cost=0.0, effort_hours=float(getattr(opp, "estimated_effort", 0) or 0),
                    platform=getattr(opp, "platform", ""), category=getattr(opp, "category", ""),
                    task_type=getattr(opp, "task_type", ""))
                learned = True
        except Exception as e:
            result.errors.append(f"Learning error: {e}")
        result.stages.append(StageResult(stage="learn",
            status=StageStatus.COMPLETED if learned else StageStatus.FAILED,
            opportunity_id=facts.opportunity_id, data={"learned": learned}, duration_s=time.time()-t0))

    def _stage_rerank(self, result, opp, facts):
        t0 = time.time()
        reranked = False
        try:
            # OpportunityPortfolio persists via update()/add() (INSERT OR REPLACE); there is
            # no save() method, so the previous code raised AttributeError and silently no-op'd.
            if self.portfolio is not None and hasattr(self.portfolio, 'update'):
                opp_id = opp.id or opp.opportunity_id
                for entry in self.portfolio.load_all():
                    if entry.opportunity_id == opp_id:
                        # Operational completion is not verified economic success.
                        # Only a verified payment may improve opportunity priority.
                        if result.paid:
                            entry.priority = min(getattr(entry, 'priority', 0) + 1, 100)
                        else:
                            entry.priority = max(getattr(entry, 'priority', 0) - 1, 0)
                        self.portfolio.update(entry)
                        reranked = True; break
            # else: no portfolio or no update — skip gracefully
        except Exception as e:
            result.errors.append(f"Rerank error: {e}")
        result.stages.append(StageResult(stage="rerank",
            status=StageStatus.COMPLETED if reranked else StageStatus.FAILED,
            opportunity_id=facts.opportunity_id, data={"reranked": reranked}, duration_s=time.time()-t0))

    # ── Finalize with structured explanation ──────────────────────────────────

    def _finalize(self, result, facts, t0, decision, reason):
        # success = pipeline reached a terminal non-failure (proceed OR completed_unpaid);
        # the separate `paid` flag proves revenue. C-1 fix.
        result.success = decision in ("proceed", "completed_unpaid")
        result.decision = decision
        result.decision_reason = reason
        result.duration_s = time.time() - t0
        # Terminal ledger state. _begin_run wrote RUNNING; leaving it there would
        # make the next startup's recover_incomplete() report a finished run as
        # interrupted.
        result.status = "DONE" if result.success else "FAILED"
        # Build structured explanation from stage data
        result.explanation = ExplanationBuilder(result.stages, facts, decision, reason).build()
        # Sync final state to lifecycle and portfolio
        self._sync_final_state(result, facts)
        # v2.1 Phase 3: persist the run + stages + idempotency key durably.
        self._persist_run(result, facts)
        return result

    def _persist_run(self, result: "AutonomousResult", facts: Any) -> None:
        """Persist a finished run to the durable store (optional, best-effort).

        Does NOT mark the idempotency key: that is ``_mark_irreversible``'s
        job, at the moment an irreversible action actually goes out. Marking it
        here (at finalize) made every completed run un-replayable, which
        blocked the re-entry ``_stage_deduplicate`` explicitly allows for a
        prior failure, a rejection, and an ``await_approval`` pause.

        Never raises — persistence must not break the loop's return value.
        """
        store = self.run_store
        if store is None:
            return
        try:
            opp_id = result.opportunity_id or getattr(facts, "opportunity_id", "")
            if not opp_id:
                return
            store.save_run(result, opp_id)
        except Exception as exc:
            result.errors.append(f"Run persistence error: {exc}")

    def _replay_guard(self, opp_id: str) -> bool:
        """True when this opportunity already made an irreversible commitment.

        Checked before the first stage. The key is written by
        ``_mark_irreversible`` right after a submission actually goes out, so
        without this guard a process killed mid-run and restarted would
        re-execute that submission.

        Fails CLOSED: if the ledger cannot be read we must not risk a second
        irreversible action, so we refuse the run. The row is already durable
        (``_begin_run``) so a locked ledger also means an interrupted run is
        recoverable — refusing is the safe side, and a transient lock clears.
        """
        store = self.run_store
        if store is None or not opp_id:
            return False
        try:
            return bool(store.is_idempotent(f"opportunity:{opp_id}"))
        except Exception as exc:
            logger.warning(
                "Replay guard could not read the ledger for %s; refusing to "
                "run rather than risk a duplicate irreversible action: %s",
                opp_id, exc)
            return True

    def _begin_run(self, result: "AutonomousResult", opp_id: str) -> None:
        """Write the in-flight run row before stage 1.

        Makes the run visible to ``recover_incomplete()`` (which fails any
        non-terminal row at startup) so a hard kill is recorded as interrupted
        instead of silently vanishing. Does NOT mark the idempotency key —
        marking it here would permanently block re-entry for an
        ``await_approval`` pause or a transient failure, both of which
        ``_stage_deduplicate`` explicitly allows back in.
        """
        store = self.run_store
        if store is None or not opp_id:
            return
        try:
            result.status = "RUNNING"
            if not result.run_id:
                result.run_id = f"run-{opp_id}"
            store.save_run(result, opp_id)
        except Exception as exc:
            result.errors.append(f"Run start persistence error: {exc}")

    def _mark_irreversible(self, result: "AutonomousResult", opp_id: str) -> None:
        """Mark the idempotency key once an irreversible action has been sent.

        Called from ``_stage_submit`` AFTER the external call returns, so the
        window in which a restart could re-submit is as small as the call
        itself. Paired with ``_replay_guard`` this is what stops a
        killed-then-restarted process submitting the same work twice.
        """
        store = self.run_store
        if store is None or not opp_id:
            return
        try:
            run_id = result.run_id or f"run-{opp_id}"
            store.mark_idempotent(f"opportunity:{opp_id}", run_id, opp_id)
        except Exception as exc:
            result.errors.append(f"Idempotency mark error: {exc}")

    def _sync_final_state(self, result: AutonomousResult, facts: Any) -> None:
        """Sync the loop's final decision to the lifecycle and portfolio."""
        if self.lifecycle is not None and result.opportunity_id:
            try:
                if hasattr(self.lifecycle, 'mark_final_outcome') and callable(self.lifecycle.mark_final_outcome):
                    if result.decision == "proceed":
                        # C-1 fix: a real 'paid' outcome requires verified payment evidence. The
                        # loop records the lifecycle as submitted/completed here; the actual 'paid'
                        # state was already set (gated) inside _stage_verify via mark_paid_verified.
                        # We never synthesize a 'paid' event with advertised revenue.
                        self.lifecycle.mark_final_outcome(
                            result.opportunity_id,
                            outcome_state="paid" if result.paid else "completed",
                            revenue=result.payment_amount if result.paid else 0.0,
                            reason=("Payment verified" if result.paid else "Completed without verified payment"))
                    elif result.decision == "reject":
                        self.lifecycle.mark_final_outcome(
                            result.opportunity_id, outcome_state="failed",
                            revenue=0.0, reason="Rejected by autonomous loop")
                    elif result.decision == "await_approval":
                        self.lifecycle.mark_final_outcome(
                            result.opportunity_id, outcome_state="submitted",
                            revenue=0.0, reason="Awaiting human approval")
            except Exception as exc:
                result.errors.append(f"Lifecycle sync error: {exc}")

        if self.portfolio is not None and result.opportunity_id:
            try:
                from agents.earning.opportunity_portfolio import WorkStatus
                entries = self.portfolio.load_all()
                for entry in entries:
                    if entry.opportunity_id == result.opportunity_id:
                        if result.decision in ("proceed", "completed_unpaid"):
                            entry.work_status = WorkStatus.IN_PROGRESS
                        elif result.decision == "reject":
                            entry.work_status = WorkStatus.FAILED
                        elif result.decision == "await_approval":
                            entry.work_status = WorkStatus.AWAITING_APPROVAL
                        # Keep policy scoring truthful: completed-unpaid runs are not
                        # successful paid outcomes.
                        entry.policy_score = result.paid
                        entry.explanation = result.explanation
                        self.portfolio.update(entry)
                        break
            except Exception as exc:
                result.errors.append(f"Portfolio sync error: {exc}")

    def _get_opp_from_facts(self, facts: Any):
        """Extract opportunity from facts store."""
        if facts is None:
            return None
        # Facts store may have the opportunity attached
        return getattr(facts, 'opportunity', None)


__all__ = ["StageStatus", "StageResult", "AutonomousResult", "AutonomousLoop", "ExplanationBuilder"]
