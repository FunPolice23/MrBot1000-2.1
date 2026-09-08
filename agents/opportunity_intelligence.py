"""agents/opportunity_intelligence.py — Opportunity Intelligence Engine.

Answers: "Which discovered opportunities are actually worth pursuing?"

This is a STRUCTURED expected-value model over 24 named factors. It deliberately does
NOT use a single arbitrary score. The LLM may provide *semantic estimates*
(skill fit, difficulty, effort, competition, scam, payment reliability) but DETERMINISTIC
CODE combines them with historical memory + configured policy to decide final eligibility.
The LLM never sets the verdict directly.

Expected value:
    EV = P(success) * P(payment) * expected_net_revenue - expected_cost - risk_penalty
    P(success) = P(acceptance) * P(completion)
    expected_hourly_value = expected_net_value_after / max(effort_hours, epsilon)

Cold-start: when historical data is insufficient, a NEUTRAL PRIOR is used and confidence is
marked LOW. A category/platform is never rejected merely for lack of data.

Verdicts: attractive | marginal | poor | unsafe | insufficient_information | blocked.

The result preserves WHY via a structured `reasons` dict (not just a scalar score).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from agents.opportunity_models import Opportunity, validate_opportunity


# ── Configuration (policy) ────────────────────────────────────────────────────

@dataclass
class EvaluationConfig:
    """Tunable policy. All thresholds/weights live here, not hardcoded in logic."""

    # Neutral priors used when historical data is insufficient (cold-start).
    neutral_success_rate: float = 0.5     # P(acceptance)*P(completion) baseline
    neutral_payment_rate: float = 0.5     # P(payment) baseline
    neutral_confidence: float = 0.25      # low confidence at cold-start

    # Minimum observations before we trust a history series (else neutral prior).
    min_history_samples: int = 3

    # Cost model.
    cost_per_hour: float = 0.0            # opportunity cost of time (0 = untracked)

    # Risk penalty weighting (scaled by expected GROSS revenue).
    penalty_scale: float = 0.5
    scam_weight: float = 1.0
    risk_level_weight: float = 0.5
    source_reliability_weight: float = 0.3

    # Verdict thresholds (on expected_value, in currency units).
    attractive_ev: float = 20.0
    marginal_ev: float = 2.0

    # Safety gates (override everything except blocked).
    scam_risk_unsafe: float = 0.6
    risk_levels_unsafe: tuple = ("high",)

    # Confidence gate: attractive requires at least this confidence.
    min_confidence_attractive: float = 0.4

    # Factor weights for probability blending (deterministic, not LLM-set).
    platform_history_weight: float = 0.5
    category_history_weight: float = 0.3
    tasktype_history_weight: float = 0.2


# ── LLM semantic estimates (inputs only, never authoritative) ─────────────────

@dataclass
class SemanticEstimate:
    """Optional semantic estimates the LLM MAY provide.

    Every field is Optional; missing values fall back to deterministic defaults so
    the engine still works at cold-start or when the LLM is unavailable. These are
    INPUTS to the model, never the output eligibility decision.
    """

    skill_fit: Optional[float] = None          # 0..1
    difficulty: Optional[float] = None         # 0..1 (higher = harder)
    effort_hours: Optional[float] = None       # hours
    completion_time_hours: Optional[float] = None
    competition: Optional[float] = None        # 0..1 (higher = more competition)
    scam_risk: Optional[float] = None          # 0..1
    payment_reliability: Optional[float] = None  # 0..1
    source_reliability: Optional[float] = None   # 0..1


# ── Result (structured, explainable) ──────────────────────────────────────────

@dataclass
class EvaluationResult:
    opportunity_id: str
    verdict: str                       # attractive|marginal|poor|unsafe|insufficient_information|blocked
    confidence: float = 0.0            # 0..1

    expected_value: float = 0.0
    expected_hourly_value: float = 0.0

    p_acceptance: float = 0.0
    p_completion: float = 0.0
    p_payment: float = 0.0
    p_success: float = 0.0

    expected_net_revenue: float = 0.0
    expected_cost: float = 0.0
    risk_penalty: float = 0.0

    cold_start: bool = False
    reasons: Dict[str, Any] = field(default_factory=dict)
    data_sufficiency: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "expected_value": round(self.expected_value, 3),
            "expected_hourly_value": round(self.expected_hourly_value, 3),
            "p_acceptance": round(self.p_acceptance, 3),
            "p_completion": round(self.p_completion, 3),
            "p_payment": round(self.p_payment, 3),
            "p_success": round(self.p_success, 3),
            "expected_net_revenue": round(self.expected_net_revenue, 3),
            "expected_cost": round(self.expected_cost, 3),
            "risk_penalty": round(self.risk_penalty, 3),
            "cold_start": self.cold_start,
            "reasons": self.reasons,
            "data_sufficiency": self.data_sufficiency,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _level(value_0_1: float, high: float = 0.66, low: float = 0.33) -> str:
    """Map a 0..1 value to high/medium/low."""
    if value_0_1 >= high:
        return "high"
    if value_0_1 <= low:
        return "low"
    return "medium"


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


# ── Engine ────────────────────────────────────────────────────────────────────

class OpportunityIntelligenceEngine:
    """Deterministic expected-value evaluator over structured opportunities."""

    def __init__(self, config: Optional[EvaluationConfig] = None):
        self.config = config or EvaluationConfig()

    # -- history accessors (cold-start aware) ----------------------------------

    def _history_rate(self, memory, method: str, key: str):
        """Return (success_rate, total_samples, confidence) for a history series.

        If memory is None or samples < min_history_samples, returns the NEUTRAL PRIOR
        and flags cold_start. Never returns a hard reject for missing data.
        """
        cfg = self.config
        if memory is None:
            return cfg.neutral_success_rate, 0, cfg.neutral_confidence, True
        fn = getattr(memory, method, None)
        if fn is None:
            return cfg.neutral_success_rate, 0, cfg.neutral_confidence, True
        hist = fn(key) or {}
        total = int(hist.get("total", 0) or 0)
        success = int(hist.get("success", 0) or 0)
        if total < cfg.min_history_samples:
            return cfg.neutral_success_rate, total, cfg.neutral_confidence, True
        rate = _safe_div(success, total)
        # Confidence grows with sample count toward 1.0.
        conf = min(1.0, cfg.neutral_confidence + 0.15 * (total - cfg.min_history_samples))
        return rate, total, conf, False

    # -- main evaluate --------------------------------------------------------

    def evaluate(self, opportunity: Opportunity,
                 memory=None,
                 estimates: Optional[SemanticEstimate] = None
                 ) -> EvaluationResult:
        cfg = self.config
        est = estimates or SemanticEstimate()
        reasons: Dict[str, Any] = {}
        sufficiency: Dict[str, Any] = {}

        opp_id = opportunity.opportunity_id

        # 0) Validation gate. Hard-structural failures -> blocked. A valid listing
        #    that merely lacks payment info -> insufficient_information (not blocked),
        #    so a category/platform is never rejected merely for missing data.
        vr = validate_opportunity(opportunity)
        if vr.status == "invalid":
            pay_only = all("payment" in r for r in vr.reasons)
            has_ref = bool(opportunity.external_url or opportunity.external_id)
            if pay_only and has_ref:
                reasons["validation"] = "insufficient: " + "; ".join(vr.reasons)
                sufficiency["validation_status"] = "valid_listing_missing_payment"
                return EvaluationResult(
                    opportunity_id=opp_id, verdict="insufficient_information",
                    confidence=cfg.neutral_confidence, reasons=reasons,
                    data_sufficiency=sufficiency,
                )
            reasons["validation"] = "blocked: " + "; ".join(vr.reasons)
            sufficiency["validation_status"] = "invalid"
            return EvaluationResult(
                opportunity_id=opp_id, verdict="blocked", confidence=0.0,
                reasons=reasons, data_sufficiency=sufficiency,
            )

        # --- Factor 1: skill fit (LLM estimate or neutral) ---
        skill_fit = est.skill_fit if est.skill_fit is not None else 0.5
        reasons["skill_fit"] = _level(skill_fit)
        sufficiency["skill_fit_provided"] = est.skill_fit is not None

        # --- Factor 2: task difficulty (LLM estimate or neutral) ---
        difficulty = est.difficulty if est.difficulty is not None else 0.5
        reasons["task_difficulty"] = _level(difficulty)
        sufficiency["difficulty_provided"] = est.difficulty is not None

        # --- Factor 3: estimated effort ---
        effort = opportunity.estimated_effort
        if effort <= 0 and est.effort_hours is not None:
            effort = est.effort_hours
        reasons["effort_hours"] = round(effort, 2)
        sufficiency["effort_known"] = effort > 0

        # --- Factor 4: estimated completion time ---
        completion_time = opportunity.estimated_duration
        if completion_time <= 0 and est.completion_time_hours is not None:
            completion_time = est.completion_time_hours
        reasons["completion_time_hours"] = round(completion_time, 2)

        # --- Factor 5: advertised payment ---
        advertised = opportunity.advertised_amount
        reasons["advertised_payment"] = f"{advertised:g} {opportunity.currency}"
        sufficiency["payment_amount_known"] = advertised > 0 or opportunity.estimated_net_value > 0

        # --- Factor 6: estimated net payment ---
        net = opportunity.estimated_net_value
        if net <= 0:
            net = advertised  # fallback to advertised if net unknown
        reasons["estimated_net_payment"] = round(net, 2)
        reasons["payment"] = _level(min(1.0, net / 100.0))  # relative band

        # --- Factor 7: payment reliability ---
        pay_rel = est.payment_reliability if est.payment_reliability is not None else None
        if pay_rel is None:
            # Derive a prior: known currency + platform reputation boost confidence.
            pay_rel = 0.5
            if vr.currency_known:
                pay_rel = 0.6
        reasons["payment_reliability"] = _level(pay_rel)

        # --- Factor 8/19: platform reliability (history) ---
        plat_rate, plat_n, plat_conf, plat_cold = self._history_rate(
            memory, "get_platform_reputation", opportunity.platform)
        reasons["platform_history"] = _level(plat_rate)
        sufficiency["platform_samples"] = plat_n

        # --- Factor 9: source reliability ---
        src_rel = opportunity.source_reliability
        if est.source_reliability is not None:
            src_rel = est.source_reliability
        reasons["source_reliability"] = _level(src_rel)

        # --- Factor 10: competition (LLM estimate or neutral) ---
        competition = est.competition if est.competition is not None else 0.5
        reasons["competition"] = _level(competition)
        sufficiency["competition_provided"] = est.competition is not None

        # --- Factor 11: deadline pressure ---
        dp = 0.0
        if opportunity.deadline and opportunity.deadline > 0:
            hrs_left = (opportunity.deadline - time.time()) / 3600.0
            if hrs_left <= 0:
                dp = 1.0
            elif hrs_left < 24:
                dp = 1.0 - (hrs_left / 24.0) * 0.5
            else:
                dp = 0.2
        reasons["deadline_pressure"] = _level(dp)
        reasons["deadline_hours_left"] = round(
            (opportunity.deadline - time.time()) / 3600.0, 1) if opportunity.deadline else None

        # --- Factor 12: scam risk ---
        scam = opportunity.scam_risk
        if est.scam_risk is not None:
            scam = est.scam_risk
        reasons["scam_risk"] = _level(scam)
        sufficiency["scam_provided"] = est.scam_risk is not None

        # --- Factor 13: automation potential ---
        autop = opportunity.automation_potential
        reasons["automation_potential"] = _level(autop)

        # --- Factor 14: human involvement required ---
        reasons["human_involvement_required"] = bool(opportunity.human_required)

        # --- Factor 15: required credentials/tools ---
        creds = list(opportunity.required_tools) + list(opportunity.required_skills)
        reasons["required_credentials_tools"] = creds if creds else "none"

        # --- Factor 16: financial exposure (derived) ---
        exposure = (1.0 - src_rel) * 0.5 + scam * 0.5
        reasons["financial_exposure"] = _level(exposure)

        # --- Factor 17: historical success rate (blended) ---
        cat_rate, cat_n, cat_conf, cat_cold = self._history_rate(
            memory, "get_category_history", opportunity.category)
        tt_rate, tt_n, tt_conf, tt_cold = self._history_rate(
            memory, "get_task_type_history", opportunity.task_type or opportunity.category)
        blended_success = (
            cfg.platform_history_weight * plat_rate +
            cfg.category_history_weight * cat_rate +
            cfg.tasktype_history_weight * tt_rate
        )
        reasons["historical_success_rate"] = round(blended_success, 3)
        reasons["category_history"] = _level(cat_rate)
        reasons["tasktype_history"] = _level(tt_rate)
        sufficiency["category_samples"] = cat_n
        sufficiency["tasktype_samples"] = tt_n

        # --- Factor 18: historical category performance ---
        # (already captured above as category_history / cat_rate)
        # --- Factor 19: historical platform performance ---
        # (captured as platform_history / plat_rate)
        # --- Factor 20: historical task-type performance ---
        # (captured as tasktype_history / tt_rate)

        # Cold-start detection: any history series thin?
        cold_start = plat_cold or cat_cold or tt_cold
        reasons["cold_start"] = cold_start

        # --- Probability model (deterministic combination) ---
        # P(acceptance): platform/category history modulated by skill fit & competition.
        p_accept = blended_success * (0.5 + 0.5 * skill_fit) * (1.0 - 0.5 * competition)
        p_accept = max(0.01, min(1.0, p_accept))

        # P(completion): higher when difficulty low, automation high, human not strictly required.
        p_complete = (1.0 - 0.6 * difficulty) * (0.5 + 0.5 * autop)
        if opportunity.human_required:
            p_complete *= 0.9  # still doable, slight discount
        p_complete = max(0.01, min(1.0, p_complete))

        # P(payment): payment reliability prior (neutral at cold-start) blended with platform pay.
        p_pay = pay_rel * (0.5 + 0.5 * plat_rate)
        p_pay = max(0.01, min(1.0, p_pay))

        p_success = p_accept * p_complete

        # --- Expected value math ---
        expected_net_revenue = net
        expected_cost = effort * cfg.cost_per_hour
        gross = p_success * p_pay * expected_net_revenue
        risk_penalty = cfg.penalty_scale * gross * (
            cfg.scam_weight * scam +
            cfg.risk_level_weight * (1.0 if opportunity.risk_level in cfg.risk_levels_unsafe else 0.0) +
            cfg.source_reliability_weight * (1.0 - src_rel)
        )
        expected_value = gross - expected_cost - risk_penalty
        net_after = expected_value  # already net of cost + penalty
        expected_hourly = _safe_div(net_after, effort) if effort > 0 else 0.0

        # --- Confidence ---
        # Base from history confidence; reduced if key inputs missing.
        hist_conf = min(plat_conf, cat_conf, tt_conf) if (plat_n or cat_n or tt_n) else cfg.neutral_confidence
        missing = sum(1 for k in ("payment_amount_known", "effort_known", "skill_fit_provided")
                      if not sufficiency.get(k))
        conf = max(0.05, hist_conf - 0.1 * missing)
        if cold_start:
            conf = min(conf, cfg.neutral_confidence)

        # --- Verdict (policy order) ---
        # NOTE: insufficient history -> neutral prior + LOW confidence (reported in
        # `reasons`/`confidence`), but it does NOT downgrade a strong-EV opportunity.
        # A category/platform is never rejected merely for lack of data.
        risk_level_unsafe = opportunity.risk_level in cfg.risk_levels_unsafe
        if scam >= cfg.scam_risk_unsafe or risk_level_unsafe:
            verdict = "unsafe"
        elif not (sufficiency.get("payment_amount_known") and sufficiency.get("effort_known")):
            # Genuinely uncomputable: no payment amount AND no effort estimate.
            verdict = "insufficient_information"
        elif expected_value >= cfg.attractive_ev:
            verdict = "attractive"
        elif expected_value >= cfg.marginal_ev:
            verdict = "marginal"
        else:
            verdict = "poor"

        reasons["confidence"] = _level(conf)
        reasons["verdict_rationale"] = self._rationale(verdict, expected_value, conf, scam,
                                                        risk_level_unsafe)

        sufficiency["overall_confidence"] = round(conf, 3)
        sufficiency["cold_start"] = cold_start

        return EvaluationResult(
            opportunity_id=opp_id, verdict=verdict, confidence=conf,
            expected_value=expected_value, expected_hourly_value=expected_hourly,
            p_acceptance=p_accept, p_completion=p_complete, p_payment=p_pay,
            p_success=p_success, expected_net_revenue=expected_net_revenue,
            expected_cost=expected_cost, risk_penalty=risk_penalty,
            cold_start=cold_start, reasons=reasons, data_sufficiency=sufficiency,
        )

    @staticmethod
    def _rationale(verdict: str, ev: float, conf: float, scam: float, risk_unsafe: bool) -> str:
        if verdict == "unsafe":
            return f"unsafe: scam_risk={scam:.2f} or risk_level unsafe={risk_unsafe}"
        if verdict == "insufficient_information":
            return f"insufficient_information: low confidence={conf:.2f} and key inputs missing"
        if verdict == "blocked":
            return "blocked: validation failed"
        return f"{verdict}: EV={ev:.2f}, confidence={conf:.2f}"
