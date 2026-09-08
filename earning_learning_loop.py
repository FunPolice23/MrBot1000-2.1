"""earning_learning_loop.py — Opportunity Learning Loop orchestration + governance (v2.0.36d).

This module turns a *meaningful outcome* into *updated future-decision inputs*. It implements
the 10-step feedback pipeline the user specified and enforces the safety constraints:

    DISCOVERY -> EVALUATION -> DECISION -> EXECUTION -> OUTCOME -> VERIFICATION
    -> LEARNING -> FUTURE EVALUATION

Safety/governance (NON-NEGOTIABLE, enforced in code — not by convention):
- The LEARNING SYSTEM MUST NEVER MODIFY SECURITY POLICY automatically.
- It may adjust opportunity *ranking / recommendation* parameters ONLY within explicitly
  allowed bounds (`LEARNING_BOUNDS`).
- The LLM is NEVER given a path to rewrite its own safety rules. It may only supply
  `SemanticEstimate` inputs (effort/revenue/success guesses); deterministic code does the rest.
- A single bad result MUST NOT permanently blacklist a category/platform/task-type. Suppression
  is bounded and gated by `MIN_SAMPLES` + a failure-rate floor.

Everything here is deterministic (SQL/Python). No LLM call lives in this module.
"""

import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from earning_memory import (
    EarningMemory, LearningMetrics, MIN_SAMPLES, NEUTRAL_CONFIDENCE,
)

# Failure-rate floor above which (and only with enough samples) a dimension may be
# *bounded*-deprioritized. Below this, even a bad run is treated as noise (no suppression).
FAILURE_RATE_FLOOR = 0.8

# ── Learning Governor: the ONLY thing allowed to propose param changes ────────────

# Parameters the learning system is allowed to nudge (recommendation/ranking only).
# Each entry: (min, max, default). The Governor clamps every suggestion into [min, max].
LEARNING_BOUNDS: Dict[str, tuple] = {
    "category_preference_multiplier": (0.5, 1.5, 1.0),
    "platform_trust_adjust": (-0.30, 0.30, 0.0),
    "task_type_preference_adjust": (-0.30, 0.30, 0.0),
    "proposal_variant_weight_adjust": (-0.25, 0.25, 0.0),
}

# Parameters that are SECURITY POLICY and must NEVER be touched by learning.
# Matching is by exact name OR by keyword (so env-var style names are caught).
SECURITY_POLICY_KEYWORDS = (
    "api_key", "secret", "token", "password", "credential",
    "provider", "safe_mode", "safemode", "blocked", "allow_execute",
    "execution", "permission", "rate_limit", "budget", "max_tokens",
    "model_role", "system_prompt", "enabled",
)


def _is_security_policy(param: str) -> bool:
    p = (param or "").lower()
    if p in SECURITY_POLICY_KEYWORDS:
        return True
    return any(kw in p for kw in SECURITY_POLICY_KEYWORDS)


class LearningGovernor:
    """Enforces that learning only adjusts ranking/recommendation params within bounds,
    and NEVER touches security policy. Deterministic and side-effect free (returns decisions;
    it does not write config/files)."""

    def can_adjust(self, param: str) -> bool:
        if _is_security_policy(param):
            return False
        return param in LEARNING_BOUNDS

    def is_security_policy(self, param: str) -> bool:
        return _is_security_policy(param)

    def propose_adjustment(self, param: str, suggested: float,
                           base: Optional[float] = None) -> Dict[str, Any]:
        """Return a clamped, bounded adjustment decision.

        Returns: {"param", "allowed", "value" (clamped), "base", "reason"}.
        If the param is security policy or unknown, `allowed` is False and `value` is None.
        """
        if _is_security_policy(param):
            return {"param": param, "allowed": False, "value": None, "base": base,
                    "reason": "SECURITY_POLICY — learning may not modify this"}
        if param not in LEARNING_BOUNDS:
            return {"param": param, "allowed": False, "value": None, "base": base,
                    "reason": "not in LEARNING_BOUNDS allow-list"}
        lo, hi, default = LEARNING_BOUNDS[param]
        base = default if base is None else base
        clamped = max(lo, min(hi, suggested))
        note = "" if clamped == suggested else f"clamped to [{lo},{hi}]"
        return {"param": param, "allowed": True, "value": clamped, "base": base,
                "reason": note or "within bounds"}

    def propose_suppression(self, dim: str, value: str, failure_rate: float,
                            sample_size: int) -> Dict[str, Any]:
        """Decide whether (and how far) a dimension may be de-prioritized after failures.

        Rule: a single bad result (or low sample count) MUST NOT blacklist. Suppression is only
        permitted when sample_size >= MIN_SAMPLES AND failure_rate >= FAILURE_RATE_FLOOR, and even
        then it is a *bounded* de-prioritization (multiplier floored at 0.5), never "never show".
        """
        if sample_size < MIN_SAMPLES:
            return {"dim": dim, "value": value, "suppress": False,
                    "multiplier": 1.0, "reason": "insufficient samples — no suppression (avoid blacklist from noise)"}
        if failure_rate < FAILURE_RATE_FLOOR:
            return {"dim": dim, "value": value, "suppress": False,
                    "multiplier": 1.0, "reason": "failure rate below floor — treated as noise"}
        # Bounded de-prioritization only.
        multiplier = max(0.5, 1.0 - (failure_rate - FAILURE_RATE_FLOOR))
        return {"dim": dim, "value": value, "suppress": True,
                "multiplier": round(multiplier, 3),
                "reason": "bounded de-prioritization only (never permanent blacklist)"}


@dataclass
class LearningDelta:
    """What changed as a result of processing one outcome (for audit + future-eval handoff)."""
    opportunity_id: str
    outcome_state: str
    recorded: bool = False
    evidence_linked: int = 0
    prediction_accuracy: Dict[str, Any] = field(default_factory=dict)
    metrics_after: Optional[LearningMetrics] = None
    governor_decisions: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class LearningLoop:
    """Orchestrates the 10-step feedback pipeline after a meaningful outcome.

    Deterministic. Never touches security policy. Makes learned info available to future
    evaluation by writing into EarningMemory (which the OpportunityIntelligenceEngine already
    consumes via category/task-type/reputation priors).
    """

    def __init__(self, memory: EarningMemory, governor: Optional[LearningGovernor] = None):
        self.memory = memory
        self.governor = governor or LearningGovernor()

    def process_outcome(self, opportunity_id: str, *, outcome_state: str,
                        predicted: Optional[Dict[str, float]] = None,
                        actual: Optional[Dict[str, float]] = None,
                        predicted_effort_hours: float = 0.0,
                        predicted_revenue: float = 0.0,
                        predicted_success_prob: float = 0.0,
                        platform: str = "", category: str = "", task_type: str = "",
                        revenue: float = 0.0, cost: float = 0.0,
                        effort_hours: float = 0.0, time_spent_hours: float = 0.0,
                        strategy_used: str = "", proposal_variant: str = "",
                        reason: str = "", failure_cause: str = "", success_cause: str = "",
                        evidence_ids: Optional[List[str]] = None,
                        now: Optional[float] = None) -> LearningDelta:
        """Run steps 1-10. Returns a LearningDelta (audit + governance decisions)."""
        predicted = dict(predicted or {})
        # Bare predicted_* kwargs (if supplied) override/augment the predicted dict.
        if predicted_effort_hours: predicted.setdefault("effort_hours", predicted_effort_hours)
        if predicted_revenue: predicted.setdefault("revenue", predicted_revenue)
        if predicted_success_prob: predicted.setdefault("success_prob", predicted_success_prob)
        actual = actual or {}
        delta = LearningDelta(opportunity_id=opportunity_id, outcome_state=outcome_state)

        # 1. RECORD THE OUTCOME (append-only; deterministic fan-out to all memory types)
        oid = self.memory.record_outcome_v2(
            opportunity_id, outcome_state,
            platform=platform, category=category, task_type=task_type,
            revenue=revenue, cost=cost, net_profit=(revenue - cost),
            effort_hours=effort_hours, time_spent_hours=time_spent_hours,
            strategy_used=strategy_used, proposal_variant=proposal_variant,
            reason=reason, failure_cause=failure_cause, success_cause=success_cause,
            predicted_effort_hours=predicted.get("effort_hours", 0.0),
            predicted_revenue=predicted.get("revenue", 0.0),
            predicted_success_prob=predicted.get("success_prob", 0.0),
        )
        delta.recorded = oid is not None
        if not delta.recorded:
            delta.notes.append("outcome rejected (invalid state)")
            return delta

        # 2. ASSOCIATE EVIDENCE (verification results back the outcome)
        for eid in (evidence_ids or []):
            self.memory.link_outcome_evidence(opportunity_id, eid)
        delta.evidence_linked = len(evidence_ids or [])

        # 3. COMPUTE ACTUAL ECONOMICS — derived inside record_outcome_v2 (net_profit).
        #    The loop also exposes it via metrics below.

        # 4 + 5. COMPARE PREDICTED VS ACTUAL + IDENTIFY PREDICTION ERROR
        #    record_outcome_v2 already wrote prediction_accuracy rows (on-read aggregation):
        dim = "category" if category else ("platform" if platform else "global")
        dim_value = category or platform or "global"
        delta.prediction_accuracy = self.memory.get_prediction_accuracy(dim, dim_value)

        # 6-9. UPDATE reputation / statistics / strategy / platform-category-task performance.
        #    All handled by record_outcome_v2 fan-out (deterministic). Nothing else required
        #    here except recomputing the dimension metrics for the handoff.

        # Metrics AFTER learning (so future evaluation can be compared / reported).
        delta.metrics_after = self.memory.compute_opportunity_metrics(dim, dim_value, now=now)

        # 10. MAKE LEARNED INFO AVAILABLE TO FUTURE EVALUATION + bounded ranking proposals.
        #     The memory writes above are already consumed by OpportunityIntelligenceEngine
        #     on the next evaluate() call (category/task-type/reputation priors). Here we only
        #     produce GOVERNED, BOUNDED ranking-adjustment suggestions (never applied to security).
        if category or platform:
            fr = delta.metrics_after.failure_rate if delta.metrics_after else 0.0
            sn = delta.metrics_after.sample_size if delta.metrics_after else 0
            suppress = self.governor.propose_suppression(dim, dim_value, fr, sn)
            delta.governor_decisions.append(suppress)
            # Example bounded recommendation the decision layer MAY use (or ignore):
            if suppress.get("suppress"):
                adj = self.governor.propose_adjustment(
                    "category_preference_multiplier" if category else "platform_trust_adjust",
                    suppress.get("multiplier", 1.0),
                )
                delta.governor_decisions.append(adj)

        delta.notes.append("outcome learned; future evaluations will reflect updated priors")
        return delta

    # Convenience: let a security-policy test confirm learning cannot propose changes there.
    def refuse_security_policy_change(self, param: str, suggested: float = 0.0) -> bool:
        """True if the governor refuses to adjust `param` (security policy / unknown)."""
        return not self.governor.can_adjust(param)
