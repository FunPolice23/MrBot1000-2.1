"""agents/autonomy/__init__.py — Phase 5: Autonomy subsystem."""
from agents.autonomy.heartbeat import (
    HeartbeatSystem,
    CreditMonitor,
    SurvivalTier,
    CreditSnapshot,
    HeartbeatRecord,
    CRITICAL_THRESHOLD,
    WARNING_THRESHOLD,
    FULL_THRESHOLD,
)
from agents.autonomy.self_improvement import (
    SelfImprovementEngine,
    LearningState,
    OutcomeRecord,
    Outcome,
    StrategyWeights,
)
from agents.autonomy.agent_registry import (
    AgentRegistry,
    AgentSpec,
    AgentStatus,
    CapabilitySpec,
    CapabilityCategory,
)
from agents.autonomy.onchain_identity import (
    OnChainIdentity,
    AgentCard,
    AgentMetadata,
)

__all__ = [
    "HeartbeatSystem",
    "CreditMonitor",
    "SurvivalTier",
    "CreditSnapshot",
    "HeartbeatRecord",
    "CRITICAL_THRESHOLD",
    "WARNING_THRESHOLD",
    "FULL_THRESHOLD",
    "SelfImprovementEngine",
    "LearningState",
    "OutcomeRecord",
    "Outcome",
    "StrategyWeights",
    "AgentRegistry",
    "AgentSpec",
    "AgentStatus",
    "CapabilitySpec",
    "CapabilityCategory",
    "OnChainIdentity",
    "AgentCard",
    "AgentMetadata",
]