import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class StartupValidationReport:
    status: str
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    safe_mode: bool = False
    details: Dict[str, object] = field(default_factory=dict)


def validate_startup_environment(env: Optional[Dict[str, str]] = None, log_fn: Optional[Callable[[str], None]] = None) -> StartupValidationReport:
    """Validate runtime prerequisites and return a structured startup report."""
    env = os.environ if env is None else env
    log = log_fn or (lambda _: None)

    warnings: List[str] = []
    errors: List[str] = []
    details: Dict[str, object] = {}

    safe_mode = str(env.get("MRBOT_SAFE_MODE", "")).lower() in {"1", "true", "yes", "on"}
    details["safe_mode"] = safe_mode

    disable_ollama = str(env.get("DISABLE_OLLAMA", "")).lower() in {"1", "true", "yes", "on"}
    disable_openai = str(env.get("DISABLE_OPENAI", "")).lower() in {"1", "true", "yes", "on"}
    disable_anthropic = str(env.get("DISABLE_ANTHROPIC", "")).lower() in {"1", "true", "yes", "on"}

    def enabled(name: str, default: bool = True) -> bool:
        value = str(env.get(name, str(default))).lower()
        return value in {"1", "true", "yes", "on"}

    # The canonical dual-brain runtime is local and OpenAI-compatible. Count
    # enabled brain endpoints as usable even when cloud providers are disabled.
    local_brains = [
        prefix for prefix in ("BIG_BRAIN", "SMALL_BRAIN")
        if enabled(f"{prefix}_ENABLED")
    ]
    details["local_brains"] = local_brains
    local_brain_configured = bool(local_brains)

    if safe_mode:
        warnings.append("Safe mode is enabled; no real actions will be taken.")

    if disable_ollama and not local_brain_configured:
        warnings.append("Ollama is disabled; local LLM features will be unavailable.")

    if disable_openai and disable_anthropic and not local_brain_configured:
        warnings.append("No LLM provider credentials are enabled; chat and analysis features may be limited.")

    if not any([env.get("OPENAI_API_KEY"), env.get("ANTHROPIC_API_KEY")]) and not local_brain_configured:
        warnings.append("No active provider credentials are configured; runtime features may be limited.")

    main_model = str(env.get("OLLAMA_MAIN_MODEL", "") or env.get("OLLAMA_MODEL", "") or "").strip()
    chat_model = str(env.get("OLLAMA_CHAT_MODEL", "") or "").strip()
    details["main_model"] = main_model or None
    details["chat_model"] = chat_model or None

    if not main_model and not chat_model and not local_brain_configured and not safe_mode:
        warnings.append("No Ollama model configured; startup will continue but model-driven workflows may be limited.")

    if not main_model and not chat_model and not any([env.get("OPENAI_API_KEY"), env.get("ANTHROPIC_API_KEY")]) and not local_brain_configured:
        errors.append("No usable LLM provider configuration found.")

    if not safe_mode and errors:
        status = "error"
    elif warnings:
        status = "warning"
    else:
        status = "ok"

    for entry in warnings + errors:
        log(entry)

    return StartupValidationReport(status=status, warnings=warnings, errors=errors, safe_mode=safe_mode, details=details)
