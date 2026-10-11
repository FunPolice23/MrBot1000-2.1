"""Runtime services and telemetry package."""

from .stats import RuntimeStats
from .performance import PerformanceTelemetry, telemetry
from .manager_metrics import (
    heartbeat_summary,
    runtime_snapshot,
    update_lifecycle_metrics,
)
from .manager_queues import put_drop_oldest
from .manager_routing import classify_intent, route_to_worker
from .manager_scheduler import adaptive_sleep, heartbeat_due
from .manager_shutdown import request_shutdown
from .manager_workers import ManagerWorkerRegistry
from .services import AgentLogger, EmbeddingCache, FileWatcher, TaskQueue, WorkerRegistry
from .llm import detect_vram_gb, estimate_tokens, fit_prompt_to_ctx, model_arch_info, num_gpu_for, vram_gb
from .agent import AgentDescriptor, AgentEvent, AgentEventKind, AgentRuntime, AgentState
from .dual_brain import (
    BrainConfig,
    BrainRole,
    DualBrainRuntime,
    apply_hardware_fallback,
    build_config,
)
from .context import build_workspace_context, register_component

__all__ = [
    "PerformanceTelemetry",
    "RuntimeStats",
    "heartbeat_summary",
    "heartbeat_due",
    "ManagerWorkerRegistry",
    "AgentLogger",
    "EmbeddingCache",
    "FileWatcher",
    "TaskQueue",
    "WorkerRegistry",
    "detect_vram_gb",
    "estimate_tokens",
    "fit_prompt_to_ctx",
    "model_arch_info",
    "num_gpu_for",
    "vram_gb",
    "AgentDescriptor",
    "AgentEvent",
    "AgentEventKind",
    "AgentRuntime",
    "AgentState",
    "BrainConfig",
    "BrainRole",
    "DualBrainRuntime",
    "apply_hardware_fallback",
    "build_config",
    "build_workspace_context",
    "register_component",
    "adaptive_sleep",
    "classify_intent",
    "put_drop_oldest",
    "request_shutdown",
    "route_to_worker",
    "runtime_snapshot",
    "telemetry",
    "update_lifecycle_metrics",
]
