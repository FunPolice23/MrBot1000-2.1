"""Canonical earning-domain services and adapters."""

from .opportunity_adapters import canonical_to_legacy, legacy_to_canonical
from .discovery import EarningDiscoveryService
from .evaluation import evaluate_opportunity
from .intelligence import evaluate_intelligence
from .ranking import rank_opportunities
from .portfolio import sync_to_portfolio
from .submission import record_ramp_submission
from .proposal import submit_gig_proposal
from .execution import execute_opportunity
from .tasks import execute_airdrop, execute_defi, execute_microtask, execute_simple
from .evidence import build_manual_attestation, is_affirmative_verification
from .payment import record_realized_gas, total_realized_gas
from .accounting import accounting_projection
from .got import GraphBudget, OpportunityGraphPlanner, OpportunityGraphRank
from .validator import CapabilityValidator
from .validators import ValidationReport, get_validator
from .capabilities import CapabilityCategory, CapabilityRegistry, CapabilitySpec, get_default_registry
from .spec import (
    Task,
    TaskFeasibility,
    build_task,
    infer_task_requirements,
    set_requirement_inferrer,
    task_from_opportunity,
)
from .executor import (
    ExecutionContext,
    ExecutionNotPossibleError,
    ExecutionPlan,
    ExecutionResult,
    StepStatus,
    TaskExecutor,
)
from .router import classify_task, get_specialization_prompt, get_tools_for_task

__all__ = [
    "EarningDiscoveryService",
    "evaluate_opportunity",
    "evaluate_intelligence",
    "rank_opportunities",
    "sync_to_portfolio",
    "record_ramp_submission",
    "submit_gig_proposal",
    "execute_opportunity",
    "execute_airdrop", "execute_defi", "execute_microtask", "execute_simple",
    "build_manual_attestation", "is_affirmative_verification",
    "record_realized_gas", "total_realized_gas",
    "accounting_projection",
    "GraphBudget", "OpportunityGraphPlanner", "OpportunityGraphRank",
    "CapabilityValidator",
    "ValidationReport",
    "get_validator",
    "CapabilityCategory",
    "CapabilityRegistry",
    "CapabilitySpec",
    "get_default_registry",
    "Task",
    "TaskFeasibility",
    "build_task",
    "infer_task_requirements",
    "set_requirement_inferrer",
    "task_from_opportunity",
    "ExecutionContext",
    "ExecutionNotPossibleError",
    "ExecutionPlan",
    "ExecutionResult",
    "StepStatus",
    "TaskExecutor",
    "classify_task",
    "get_specialization_prompt",
    "get_tools_for_task",
    "canonical_to_legacy",
    "legacy_to_canonical",
]
