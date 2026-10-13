"""Runtime services and telemetry package."""

from .stats import RuntimeStats
from .performance import PerformanceTelemetry, telemetry
from .services import AgentLogger, EmbeddingCache, FileWatcher, TaskQueue
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
    "AgentLogger",
    "EmbeddingCache",
    "FileWatcher",
    "TaskQueue",
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
    "telemetry",
]
