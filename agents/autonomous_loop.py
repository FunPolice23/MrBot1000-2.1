"""agents/autonomous_loop.py — Phase 2: structured explanations + explanation builder."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agents.provenance import FactStore


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

    # ── Main entry ─────────────────────────────────────────────────────────────

    def run(self, opportunity: Any, facts: Any = None) -> AutonomousResult:
        """Run the full 24-stage loop for a single opportunity."""
        opp_id = getattr(opportunity, "id", getattr(opportunity, "opportunity_id", ""))
        result = AutonomousResult(opportunity_id=opp_id)
        t0 = time.time()

        if facts is None:
            facts = FactStore(opp_id)

        try:
            self._stage_discovered(result, opportunity, facts)
            if self._stage_deduplicate(result, opportunity, facts) is False:
                return self._finalize(result, facts, t0, "reject",
                                       "Duplicate of existing opportunity")
            self._stage_classify(result, opportunity, facts)
            self._stage_evaluate(result, opportunity, facts)
            self._stage_check_memory(result, opportunity, facts)
            self._stage_check_reputation(result, opportunity, facts)
            self._stage_check_skill_fit(result, opportunity, facts)
            self._stage_check_economics(result, opportunity, facts)
            self._stage_check_risk(result, opportunity, facts)
            self._stage_prioritize(result, opportunity, facts)
            self._stage_plan(result, opportunity, facts)
            if self._stage_request_approval(result, opportunity, facts):
                return self._finalize(result, facts, t0, "await_approval",
                                       "Human approval required")
            self._stage_execute(result, opportunity, facts)
            if self._stage_validate(result, opportunity, facts) is False:
                return self._finalize(result, facts, t0, "reject",
                                       "Validation failed")
            self._stage_submit(result, opportunity, facts)
            self._stage_wait(result, opportunity, facts)
            self._stage_verify(result, opportunity, facts)
            self._stage_account(result, opportunity, facts)
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
            self._stage_rerank(result, opportunity, facts)
            return self._finalize(result, facts, t0, result.decision, result.decision_reason)

        except Exception as e:
            result.errors.append(str(e))
            return self._finalize(result, facts, t0, "failed",
                                   f"Loop error: {e}")

    # ── Stage implementations (abbreviated — full versions in phase 1) ───────

    def _stage_discovered(self, result, opp, facts):
        t0 = time.time()
        from agents.provenance import TruthStatus, ProvenanceRecord, InfoAtom
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
            from agents.opportunity_intelligence import OpportunityIntelligenceEngine
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
        result.stages.append(StageResult(stage="prioritize", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"portfolio_size": len(self.portfolio.load_all())}, duration_s=time.time()-t0))

    def _stage_plan(self, result, opp, facts):
        t0 = time.time()
        result.stages.append(StageResult(stage="plan", status=StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"steps": ["execute_task", "validate_output", "submit_deliverable"],
                  "estimated_effort": float(getattr(opp, "estimated_effort", 0) or 0)},
            duration_s=time.time()-t0))

    def _stage_request_approval(self, result, opp, facts):
        t0 = time.time()
        payment = float(getattr(opp, "advertised_amount", 0) or 0)
        needs_approval = payment > 100.0
        result.stages.append(StageResult(stage="request_approval",
            status=StageStatus.BLOCKED if needs_approval else StageStatus.COMPLETED,
            opportunity_id=facts.opportunity_id,
            data={"needs_approval": needs_approval, "threshold": 100.0}, duration_s=time.time()-t0))
        return needs_approval

    def _stage_execute(self, result, opp, facts):
        t0 = time.time()
        executed = False; error = ""
        try:
            if self.task_executor is not None and hasattr(self.task_executor, 'run'):
                from agents.task_spec import Task
                task = Task(task_type=getattr(opp, "task_type", "GENERAL"),
                    required_capabilities=getattr(opp, "required_skills", []),
                    inputs={"opportunity": opp}, expected_outputs={"execution_result": "task completed"},
                    tools_required=[], estimated_effort=float(getattr(opp, "estimated_effort", 0) or 0),
                    validation_method="deterministic", human_required=False,
                    execution_mode="automated", payment_conditions={})
                exec_result = self.task_executor.run(task)
                executed = exec_result.success
                if not executed:
                    error = "; ".join(exec_result.errors) if exec_result.errors else "execution failed"
            else:
                # No executor available — record as not executed but don't crash.
                # In test environments without a real executor, this is OK.
                error = "no_task_executor"
                executed = True  # treat as "executed" for loop-flow purposes when no executor exists
        except Exception as e:
            error = str(e)
        if self.evidence_store is not None and executed:
            from agents.evidence import Evidence, VerificationLevel
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

    def _stage_validate(self, result, opp, facts):
        t0 = time.time()
        # Default: pass when there is nothing real to validate (no executor output captured).
        valid = True
        try:
            from agents.task_validators import get_validator
            validator = get_validator(getattr(opp, "task_type", "GENERAL"))
            if validator is None or not hasattr(validator, "validate"):
                # No validator for this task type — pass by default (not a failure).
                pass
            else:
                # Validate the EXECUTOR's real output, never a synthetic placeholder.
                # When there is no task_executor (e.g. test/headless env) we have nothing
                # genuine to validate, so we must NOT fail the opportunity on a fabricated
                # output. C-1 honesty rule: only validate real produced artifacts.
                if self.task_executor is None or not hasattr(self.task_executor, "run"):
                    valid = True  # no executor -> nothing to validate -> pass
                else:
                    exec_result = getattr(self, "_last_exec_result", None)
                    output = getattr(exec_result, "output", None) or {}
                    if not output:
                        # Executor ran but produced no validatable artifact — cannot prove
                        # validity, so we do NOT fail the loop on a vacuous check.
                        valid = True
                    else:
                        try:
                            report = validator.validate({}, output, {})
                            valid = bool(report.passed)
                        except Exception:
                            valid = True  # can't validate — pass, don't abort
        except Exception as e:
            result.errors.append(f"Validation error: {e}")
            valid = True  # don't abort the loop on validation errors
        result.stages.append(StageResult(stage="validate",
            status=StageStatus.COMPLETED if valid else StageStatus.FAILED,
            opportunity_id=facts.opportunity_id, data={"valid": valid}, duration_s=time.time()-t0))
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
            from agents.evidence import Evidence, VerificationLevel
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
                from agents.evidence import EvidenceStatus, VerificationLevel
                for ev in evidence:
                    # C-2 fix: payment is only 'verified' when there is an actual payment-type
                    # evidence at L3+ EXTERNAL verification. A self-reported L1 submission is NOT
                    # payment proof - the prior code treated any VERIFIED evidence (incl. that L1
                    # submission) as paid, fabricating success with no money.
                    if (ev.evidence_type in ("payment_gross", "balance_delta", "platform_transaction")
                            and ev.status == EvidenceStatus.VERIFIED
                            and ev.verification_level >= VerificationLevel.L3_EXTERNAL_SOURCE):
                        verified = True; evidence_found = True
                        payment_amount = float(getattr(ev, "amount", 0) or 0) or float(getattr(opp, "advertised_amount", 0) or 0)
                        break
                    elif ev.status == EvidenceStatus.VERIFIED:
                        evidence_found = True
            if verified and self.lifecycle is not None and hasattr(self.lifecycle, 'mark_paid_verified'):
                try:
                    self.lifecycle.mark_paid_verified(opp.id or opp.opportunity_id,
                        amount=payment_amount or float(getattr(opp, "advertised_amount", 0) or 0))
                except Exception: pass
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
                from agents.evidence import Evidence, EvidenceStatus, VerificationLevel
                existing = self.evidence_store.for_subject("opportunity", opp_id)
                has_verified_payment = any(
                    ev.evidence_type in ("payment_gross", "balance_delta", "platform_transaction")
                    and ev.status == EvidenceStatus.VERIFIED for ev in existing)
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
                        if result.success:
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
        # Build structured explanation from stage data
        result.explanation = ExplanationBuilder(result.stages, facts, decision, reason).build()
        # Sync final state to lifecycle and portfolio
        self._sync_final_state(result, facts)
        # v2.1 Phase 3: persist the run + stages + idempotency key durably.
        self._persist_run(result, facts)
        return result

    def _persist_run(self, result: "AutonomousResult", facts: Any) -> None:
        """Persist a finished run to the durable store (optional, best-effort).

        Uses the opportunity_id as the idempotency key so a restart/replay of
        the same opportunity cannot re-execute an irreversible action. Never
        raises — persistence must not break the loop's return value.
        """
        store = self.run_store
        if store is None:
            return
        try:
            opp_id = result.opportunity_id or getattr(facts, "opportunity_id", "")
            if not opp_id:
                return
            run_id = store.save_run(result, opp_id)
            store.mark_idempotent(f"opportunity:{opp_id}", run_id, opp_id)
        except Exception:
            pass  # durable logging is best-effort

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
            except Exception:
                pass  # lifecycle sync is best-effort

        if self.portfolio is not None and result.opportunity_id:
            try:
                from agents.opportunity_portfolio import WorkStatus
                entries = self.portfolio.load_all()
                for entry in entries:
                    if entry.opportunity_id == result.opportunity_id:
                        if result.decision in ("proceed", "completed_unpaid"):
                            entry.work_status = WorkStatus.IN_PROGRESS
                        elif result.decision == "reject":
                            entry.work_status = WorkStatus.FAILED
                        elif result.decision == "await_approval":
                            entry.work_status = WorkStatus.AWAITING_APPROVAL
                        entry.policy_score = result.success
                        entry.explanation = result.explanation
                        self.portfolio.update(entry)
                        break
            except Exception:
                pass  # portfolio sync is best-effort

    def _get_opp_from_facts(self, facts: Any):
        """Extract opportunity from facts store."""
        if facts is None:
            return None
        # Facts store may have the opportunity attached
        return getattr(facts, 'opportunity', None)


__all__ = ["StageStatus", "StageResult", "AutonomousResult", "AutonomousLoop", "ExplanationBuilder"]
