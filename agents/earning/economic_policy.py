"""Typed economic predictions and deterministic decision policy.

Predictions describe what may happen.  Policies decide whether to pursue an
opportunity under current constraints.  Keeping these records separate makes
the same prediction reusable by different operators and runtime policies.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Mapping


class DecisionAction(str, Enum):
    SELECT = "select"
    DEFER = "defer"
    RESEARCH_MORE = "research_more"
    REJECT = "reject"


@dataclass(frozen=True)
class EconomicPrediction:
    """Versioned, range-friendly inputs for an economic decision."""

    opportunity_id: str
    prediction_version: str = "1"
    payout_amount: float = 0.0
    probability_of_success: float = 0.0
    probability_of_payment: float = 0.0
    startup_cost: float = 0.0
    model_cost: float = 0.0
    api_cost: float = 0.0
    transaction_fees: float = 0.0
    expected_failure_cost: float = 0.0
    expected_rework_cost: float = 0.0
    active_work_hours: float = 0.0
    research_hours: float = 0.0
    human_hours: float = 0.0
    expected_rework_hours: float = 0.0
    elapsed_wait_hours: float = 0.0
    time_to_payment_hours: float = 0.0
    normalized_risk_penalty: float = 0.0
    confidence: float = 0.0
    freshness_timestamp: float = field(default_factory=time.time)
    assumptions: tuple[str, ...] = ()
    currency: str = "USD"

    def __post_init__(self) -> None:
        probabilities = (
            ("probability_of_success", self.probability_of_success),
            ("probability_of_payment", self.probability_of_payment),
            ("normalized_risk_penalty", self.normalized_risk_penalty),
            ("confidence", self.confidence),
        )
        for name, value in probabilities:
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        quantities = (
            ("payout_amount", self.payout_amount),
            ("startup_cost", self.startup_cost),
            ("model_cost", self.model_cost),
            ("api_cost", self.api_cost),
            ("transaction_fees", self.transaction_fees),
            ("expected_failure_cost", self.expected_failure_cost),
            ("expected_rework_cost", self.expected_rework_cost),
            ("active_work_hours", self.active_work_hours),
            ("research_hours", self.research_hours),
            ("human_hours", self.human_hours),
            ("expected_rework_hours", self.expected_rework_hours),
            ("elapsed_wait_hours", self.elapsed_wait_hours),
            ("time_to_payment_hours", self.time_to_payment_hours),
        )
        for name, value in quantities:
            if value < 0.0:
                raise ValueError(f"{name} cannot be negative")

    @property
    def expected_net_value(self) -> float:
        gross = self.payout_amount * self.probability_of_success * self.probability_of_payment
        direct_costs = (
            self.startup_cost
            + self.model_cost
            + self.api_cost
            + self.transaction_fees
        )
        execution_loss = self.expected_failure_cost + self.expected_rework_cost
        return gross - direct_costs - execution_loss

    @property
    def productive_hours(self) -> float:
        return (
            self.active_work_hours
            + self.research_hours
            + self.human_hours
            + self.expected_rework_hours
        )

    @property
    def expected_hourly_return(self) -> float:
        return self.expected_net_value / max(self.productive_hours, 1e-9)

    @property
    def risk_adjusted_return(self) -> float:
        return self.expected_hourly_return * (1.0 - self.normalized_risk_penalty)

    def is_stale(self, *, now: float | None = None, max_age_seconds: float = 86400.0) -> bool:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds cannot be negative")
        current_time = time.time() if now is None else now
        return current_time - self.freshness_timestamp > max_age_seconds

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "prediction_version": self.prediction_version,
            "payout_amount": self.payout_amount,
            "probability_of_success": self.probability_of_success,
            "probability_of_payment": self.probability_of_payment,
            "startup_cost": self.startup_cost,
            "model_cost": self.model_cost,
            "api_cost": self.api_cost,
            "transaction_fees": self.transaction_fees,
            "expected_failure_cost": self.expected_failure_cost,
            "expected_rework_cost": self.expected_rework_cost,
            "active_work_hours": self.active_work_hours,
            "research_hours": self.research_hours,
            "human_hours": self.human_hours,
            "expected_rework_hours": self.expected_rework_hours,
            "elapsed_wait_hours": self.elapsed_wait_hours,
            "time_to_payment_hours": self.time_to_payment_hours,
            "normalized_risk_penalty": self.normalized_risk_penalty,
            "confidence": self.confidence,
            "freshness_timestamp": self.freshness_timestamp,
            "assumptions": list(self.assumptions),
            "currency": self.currency,
            "expected_net_value": self.expected_net_value,
            "productive_hours": self.productive_hours,
            "expected_hourly_return": self.expected_hourly_return,
            "risk_adjusted_return": self.risk_adjusted_return,
        }


@dataclass(frozen=True)
class DecisionPolicy:
    """Operator/runtime constraints applied to a prediction."""

    policy_version: str = "1"
    minimum_expected_net_value: float = 0.0
    minimum_risk_adjusted_hourly_return: float = 0.0
    maximum_payment_delay_hours: float = float("inf")
    minimum_confidence: float = 0.0
    maximum_risk_penalty: float = 1.0
    available_productive_hours: float = float("inf")
    required_autonomy_level: int = 0
    maximum_prediction_age_seconds: float = 86400.0

    # ── Operator configuration ─────────────────────────────────────────────
    #
    # These thresholds are what turn "this opportunity loses money" into a
    # decision instead of a number in a log line. They live here, as data on
    # the policy object, rather than as literals inside a loop stage, so an
    # operator can tighten them without editing the autonomous loop.

    # A negative hourly return is never worth pursuing. `evaluate_prediction`
    # already computes `risk_adjusted_return`, but until the autonomous loop
    # actually consulted a policy there was no threshold to compare it against:
    # `_stage_check_economics` recorded `estimated_hourly: -2.5` and returned
    # COMPLETED (OBSERVED), so a $5 payout costing 200 hours reached execute.
    DEFAULT_MINIMUM_HOURLY: ClassVar[float] = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")
        if not 0.0 <= self.maximum_risk_penalty <= 1.0:
            raise ValueError("maximum_risk_penalty must be between 0 and 1")
        for name in (
            "minimum_expected_net_value",
            "minimum_risk_adjusted_hourly_return",
            "maximum_payment_delay_hours",
            "available_productive_hours",
            "maximum_prediction_age_seconds",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} cannot be negative")
        if self.required_autonomy_level < 0:
            raise ValueError("required_autonomy_level cannot be negative")


@dataclass(frozen=True)
class DecisionResult:
    action: DecisionAction
    opportunity_id: str
    policy_version: str
    reasons: tuple[str, ...]
    expected_net_value: float
    risk_adjusted_hourly_return: float

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "opportunity_id": self.opportunity_id,
            "policy_version": self.policy_version,
            "reasons": list(self.reasons),
            "expected_net_value": self.expected_net_value,
            "risk_adjusted_hourly_return": self.risk_adjusted_hourly_return,
        }


def evaluate_prediction(
    prediction: EconomicPrediction,
    policy: DecisionPolicy,
    *,
    now: float | None = None,
    gates: Mapping[str, bool] | None = None,
    available_autonomy_level: int | None = None,
) -> DecisionResult:
    """Apply deterministic gates and thresholds without changing the prediction."""

    reasons: list[str] = []
    gate_values = dict(gates or {})
    for gate_name in ("legality", "capability", "identity", "evidence"):
        if gate_name in gate_values and not gate_values[gate_name]:
            reasons.append(f"{gate_name}_gate_failed")

    if prediction.is_stale(
        now=now,
        max_age_seconds=policy.maximum_prediction_age_seconds,
    ):
        reasons.append("prediction_stale")
    if prediction.confidence < policy.minimum_confidence:
        reasons.append("confidence_below_policy")
    if prediction.normalized_risk_penalty > policy.maximum_risk_penalty:
        reasons.append("risk_above_policy")
    if prediction.time_to_payment_hours > policy.maximum_payment_delay_hours:
        reasons.append("payment_delay_above_policy")
    if prediction.productive_hours > policy.available_productive_hours:
        reasons.append("productive_time_above_policy")
    if (
        available_autonomy_level is not None
        and available_autonomy_level < policy.required_autonomy_level
    ):
        reasons.append("autonomy_level_below_policy")

    if reasons:
        action = (
            DecisionAction.RESEARCH_MORE
            if reasons == ["confidence_below_policy"]
            else DecisionAction.REJECT
        )
    elif prediction.expected_net_value < policy.minimum_expected_net_value:
        action = DecisionAction.DEFER
        reasons.append("expected_net_value_below_policy")
    elif prediction.risk_adjusted_return < policy.minimum_risk_adjusted_hourly_return:
        action = DecisionAction.DEFER
        reasons.append("risk_adjusted_return_below_policy")
    else:
        action = DecisionAction.SELECT
        reasons.append("all_policy_gates_passed")

    return DecisionResult(
        action=action,
        opportunity_id=prediction.opportunity_id,
        policy_version=policy.policy_version,
        reasons=tuple(reasons),
        expected_net_value=prediction.expected_net_value,
        risk_adjusted_hourly_return=prediction.risk_adjusted_return,
    )


def _settings_file() -> str:
    """Return the settings.json path, honoring the test-isolation override.

    Mirrors ``device_registry.policy_path``: without
    ``MRBOT_DEVICE_SETTINGS_PATH`` a test run would read (and a careless writer
    would clobber) the operator's LIVE settings.json.
    """
    override = (os.getenv("MRBOT_DEVICE_SETTINGS_PATH") or "").strip()
    if override:
        return override
    return os.path.join(os.getcwd(), "settings.json")


# settings.json key holding the operator's economic thresholds.
SETTINGS_KEY = "economic_policy"

# The numeric thresholds an operator may set. Names match DecisionPolicy
# fields exactly, so a settings key cannot silently configure a field that
# does not exist (a typo would otherwise be ignored forever).
_NUMERIC_FIELDS = (
    "minimum_expected_net_value",
    "minimum_risk_adjusted_hourly_return",
    "maximum_payment_delay_hours",
    "minimum_confidence",
    "maximum_risk_penalty",
    "available_productive_hours",
    "required_autonomy_level",
    "maximum_prediction_age_seconds",
)


def load_policy() -> DecisionPolicy:
    """Build the effective DecisionPolicy from settings.json.

    ARCH-ENG-155: this module was imported by NOTHING in production
    (OBSERVED: repo-wide grep for an import of ``economic_policy`` outside
    tests/ returned 0 hits), so the deterministic gates it defines were dead
    code while the autonomous loop's own ``check_economics`` stage recorded
    ``estimated_hourly: -2.5`` and returned COMPLETED. An opportunity that
    loses money on every axis reached ``execute``.

    The thresholds now come from settings.json so an operator can tighten them
    without a code change, and every value is validated through the same
    ``DecisionPolicy.__post_init__`` that a hand-built policy passes — so an
    out-of-range setting raises here, at load time, rather than silently
    inverting a gate mid-run.

    Absent/partial/corrupt settings -> the module defaults, which are
    deliberately permissive (a policy that rejects everything would stop the
    loop from running at all). This function never raises: a broken
    settings.json must not be able to halt the autonomous loop, so a bad value
    falls back to the default rather than propagating.
    """
    overrides: dict = {}
    try:
        with open(_settings_file(), encoding="utf-8") as f:
            data = json.load(f)
        block = data.get(SETTINGS_KEY)
        if isinstance(block, dict):
            for name in _NUMERIC_FIELDS:
                if name not in block:
                    continue
                value = block[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue  # a bool is an int in Python; reject both
                # Validate through DecisionPolicy itself: an out-of-range value
                # raises here and keeps the default, so a bad setting can never
                # invert a gate mid-run.
                try:
                    DecisionPolicy(**{name: float(value)})
                except (ValueError, TypeError):
                    continue
                overrides[name] = float(value)
            version = block.get("policy_version")
            if isinstance(version, str) and version:
                overrides["policy_version"] = version
    except Exception:
        pass  # missing/corrupt/unreadable -> defaults
    return DecisionPolicy(**overrides)


__all__ = [
    "DecisionAction",
    "DecisionPolicy",
    "DecisionResult",
    "EconomicPrediction",
    "evaluate_prediction",
    "load_policy",
    "SETTINGS_KEY",
]
