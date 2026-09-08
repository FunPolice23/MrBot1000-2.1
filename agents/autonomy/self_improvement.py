"""agents/autonomy/self_improvement.py — Phase 5: Self-Improvement Engine.

Learns from completed opportunity outcomes to adjust scoring weights,
strategy selection, and risk thresholds over time.
"""
from __future__ import annotations

import json
import logging
import os
import pickle
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mrbot.autonomy.self_improvement")


# ── Data types ──────────────────────────────────────────────────────────

class Outcome(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    ABANDONED = "abandoned"


@dataclass
class OutcomeRecord:
    opportunity_id: str = ""
    strategy: str = ""
    platform: str = ""
    outcome: str = Outcome.FAILURE.value
    revenue: float = 0.0
    cost: float = 0.0
    effort_hours: float = 0.0
    risk_level: str = "unknown"
    success_probability: float = 0.0
    tags: List[str] = field(default_factory=list)
    timestamp: float = 0.0


@dataclass
class StrategyWeights:
    """Learned weights for a strategy's scoring factors."""

    payout_potential: float = 0.3
    success_probability: float = 0.3
    time_efficiency: float = 0.2
    skill_match: float = 0.1
    platform_reliability: float = 0.1

    def as_dict(self) -> Dict[str, float]:
        return {
            "payout_potential": self.payout_potential,
            "success_probability": self.success_probability,
            "time_efficiency": self.time_efficiency,
            "skill_match": self.skill_match,
            "platform_reliability": self.platform_reliability,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> "StrategyWeights":
        return cls(**{k: float(d.get(k, v)) for k, v in cls().as_dict().items()})


@dataclass
class LearningState:
    """Accumulated learning state for the self-improvement engine."""

    outcomes: List[OutcomeRecord] = field(default_factory=list)
    strategy_weights: Dict[str, StrategyWeights] = field(default_factory=dict)
    platform_reliability: Dict[str, float] = field(default_factory=dict)
    tag_success_rates: Dict[str, float] = field(default_factory=dict)
    total_outcomes: int = 0
    total_successes: int = 0

    @property
    def overall_success_rate(self) -> float:
        if self.total_outcomes == 0:
            return 0.0
        return self.total_successes / self.total_outcomes

    @property
    def net_roi(self) -> float:
        revenue = sum(o.revenue for o in self.outcomes)
        cost = sum(o.cost for o in self.outcomes)
        if cost == 0:
            return 0.0
        return (revenue - cost) / cost


# ── Engine ───────────────────────────────────────────────────────────────

class SelfImprovementEngine:
    """Learns from outcomes to improve future opportunity scoring.

    Learning rules (all conservative, human-gated):
    1. Update platform reliability from outcomes.
    2. Adjust strategy weights toward what worked.
    3. Track tag-level success rates.
    4. Never override a human-set threshold without explicit approval.
    """

    DEFAULT_WEIGHTS = StrategyWeights()
    LEARNING_RATE = 0.1   # how fast weights adapt (conservative)
    MIN_OUTCOMES = 5      # minimum outcomes before adjusting weights
    RELIABILITY_DECAY = 0.95  # platform reliability decay per stale tick

    def __init__(self, state_path: Optional[str] = None):
        self.state = LearningState()
        self.state_path = state_path
        if state_path and os.path.isfile(state_path):
            self.load(state_path)

    # ── Public API ────────────────────────────────────────────────────

    def record_outcome(self, record: OutcomeRecord) -> None:
        """Record a completed opportunity outcome and trigger learning."""
        self.state.outcomes.append(record)
        self.state.total_outcomes += 1
        if record.outcome == Outcome.SUCCESS.value:
            self.state.total_successes += 1

        self._update_platform_reliability(record)
        self._update_tag_rates(record)
        self._adjust_weights()

        if self.state_path:
            self.save(self.state_path)

    def get_strategy_weights(self, strategy: str) -> StrategyWeights:
        return self.state.strategy_weights.get(
            strategy, self.DEFAULT_WEIGHTS
        )

    def get_platform_reliability(self, platform: str) -> float:
        return self.state.platform_reliability.get(platform, 0.5)

    def get_tag_success_rate(self, tag: str) -> float:
        return self.state.tag_success_rates.get(tag, 0.5)

    def get_recommendation(self) -> Dict[str, Any]:
        """Return a recommendation dict for the next opportunity scan.

        Includes preferred strategies, platforms to avoid, and tags
        with high success rates.
        """
        preferred_strategies = sorted(
            self.state.strategy_weights.items(),
            key=lambda kv: self._strategy_score(kv[1]),
            reverse=True,
        ) or [("freelance_bidding", self.DEFAULT_WEIGHTS)]
        reliable_platforms = {
            p: r
            for p, r in self.state.platform_reliability.items()
            if r >= 0.6
        }
        strong_tags = {
            t: r
            for t, r in self.state.tag_success_rates.items()
            if r >= 0.7
        }
        return {
            "preferred_strategies": [
                {"strategy": s, "weights": w.as_dict()}
                for s, w in preferred_strategies[:3]
            ],
            "reliable_platforms": reliable_platforms,
            "strong_tags": strong_tags,
            "overall_success_rate": self.state.overall_success_rate,
            "net_roi": self.state.net_roi,
        }

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {
            "outcomes": [
                {
                    "opportunity_id": o.opportunity_id,
                    "strategy": o.strategy,
                    "platform": o.platform,
                    "outcome": o.outcome,
                    "revenue": o.revenue,
                    "cost": o.cost,
                    "effort_hours": o.effort_hours,
                    "risk_level": o.risk_level,
                    "success_probability": o.success_probability,
                    "tags": o.tags,
                    "timestamp": o.timestamp,
                }
                for o in self.state.outcomes
            ],
            "strategy_weights": {
                s: w.as_dict()
                for s, w in self.state.strategy_weights.items()
            },
            "platform_reliability": self.state.platform_reliability,
            "tag_success_rates": self.state.tag_success_rates,
            "total_outcomes": self.state.total_outcomes,
            "total_successes": self.state.total_successes,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info("SelfImprovementEngine saved %d outcomes to %s", len(data["outcomes"]), path)

    def load(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.state.outcomes = [OutcomeRecord(**o) for o in data.get("outcomes", [])]
        self.state.strategy_weights = {
            s: StrategyWeights.from_dict(w)
            for s, w in data.get("strategy_weights", {}).items()
        }
        self.state.platform_reliability = dict(data.get("platform_reliability", {}))
        self.state.tag_success_rates = dict(data.get("tag_success_rates", {}))
        self.state.total_outcomes = data.get("total_outcomes", 0)
        self.state.total_successes = data.get("total_successes", 0)
        logger.info("SelfImprovementEngine loaded %d outcomes from %s", len(self.state.outcomes), path)

    # ── Internal learning ─────────────────────────────────────────────

    def _update_platform_reliability(self, record: OutcomeRecord) -> None:
        current = self.state.platform_reliability.get(record.platform, 0.5)
        target = 1.0 if record.outcome == Outcome.SUCCESS.value else 0.0
        self.state.platform_reliability[record.platform] = (
            current * self.RELIABILITY_DECAY + target * (1 - self.RELIABILITY_DECAY)
        )

    def _update_tag_rates(self, record: OutcomeRecord) -> None:
        for tag in record.tags:
            current = self.state.tag_success_rates.get(tag, 0.5)
            target = 1.0 if record.outcome == Outcome.SUCCESS.value else 0.0
            self.state.tag_success_rates[tag] = (
                current * 0.9 + target * 0.1
            )

    def _adjust_weights(self) -> None:
        """Adjust strategy weights based on accumulated outcomes.

        Only adjusts when we have enough outcomes (MIN_OUTCOMES) to
        avoid overfitting on sparse data.
        """
        if self.state.total_outcomes < self.MIN_OUTCOMES:
            return

        for strategy, weights in self.state.strategy_weights.items():
            # Calculate average outcome for this strategy
            strategy_outcomes = [
                o for o in self.state.outcomes if o.strategy == strategy
            ]
            if len(strategy_outcomes) < 2:
                continue

            success_rate = sum(
                1 for o in strategy_outcomes if o.outcome == Outcome.SUCCESS.value
            ) / len(strategy_outcomes)
            avg_revenue = sum(o.revenue for o in strategy_outcomes) / len(strategy_outcomes)

            # Nudge weights toward success factors (conservative)
            w = weights
            w.success_probability = min(1.0, w.success_probability + self.LEARNING_RATE * (success_rate - 0.5))
            w.payout_potential = min(1.0, w.payout_potential + self.LEARNING_RATE * (min(avg_revenue / 100, 1.0) - 0.3))

    def _strategy_score(self, weights: StrategyWeights) -> float:
        return (
            weights.payout_potential * 0.3
            + weights.success_probability * 0.3
            + weights.time_efficiency * 0.2
            + weights.skill_match * 0.1
            + weights.platform_reliability * 0.1
        )


__all__ = [
    "Outcome",
    "OutcomeRecord",
    "StrategyWeights",
    "LearningState",
    "SelfImprovementEngine",
]
