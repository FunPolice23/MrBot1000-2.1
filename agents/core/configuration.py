"""Typed, normalized operator configuration for provider integrations.

This layer centralizes parsing of provider environment variables while keeping
secret values out of diagnostics. Existing callers may continue reading their
legacy variables; they can migrate incrementally to this representation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ProviderSettings:
    """Normalized settings shared by provider adapters and diagnostics."""

    name: str
    base_url: str = ""
    model: str = ""
    chat_model: str = ""
    api_key_configured: bool = False
    enabled: bool = True


PROVIDER_ENV: dict[str, tuple[str, str, str, str]] = {
    "ollama": ("OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_CHAT_MODEL", ""),
    "openai": ("OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_CHAT_MODEL", "OPENAI_API_KEY"),
    "openrouter": ("OPENROUTER_BASE_URL", "OPENROUTER_MODEL", "OPENROUTER_CHAT_MODEL", "OPENROUTER_API_KEY"),
    "anthropic": ("ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_CHAT_MODEL", "ANTHROPIC_API_KEY"),
    "gemini": ("GEMINI_BASE_URL", "GEMINI_MODEL", "GEMINI_CHAT_MODEL", "GEMINI_API_KEY"),
    "groq": ("GROQ_BASE_URL", "GROQ_MODEL", "GROQ_CHAT_MODEL", "GROQ_API_KEY"),
    "deepseek": ("DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_CHAT_MODEL", "DEEPSEEK_API_KEY"),
    "mistral": ("MISTRAL_BASE_URL", "MISTRAL_MODEL", "MISTRAL_CHAT_MODEL", "MISTRAL_API_KEY"),
    "together": ("TOGETHER_BASE_URL", "TOGETHER_MODEL", "TOGETHER_CHAT_MODEL", "TOGETHER_API_KEY"),
    "nous": ("NOUS_BASE_URL", "NOUS_MODEL", "NOUS_CHAT_MODEL", "NOUS_API_KEY"),
    "nvidia": ("NVIDIA_BASE_URL", "NVIDIA_MODEL", "NVIDIA_CHAT_MODEL", "NVIDIA_API_KEY"),
    "vllm": ("VLLM_BASE_URL", "VLLM_MODEL", "VLLM_CHAT_MODEL", "VLLM_API_KEY"),
    "lmstudio": ("LM_STUDIO_BASE_URL", "LM_STUDIO_MODEL", "LM_STUDIO_CHAT_MODEL", "LM_STUDIO_API_KEY"),
    "koboldcpp": ("KOBOLDCPP_BASE_URL", "KOBOLDCPP_MODEL", "KOBOLDCPP_CHAT_MODEL", "KOBOLDCPP_API_KEY"),
}


def _value(env: Mapping[str, str], key: str) -> str:
    """Return a cleaned env value (a comment-as-value is treated as empty)."""
    from app.environment import clean_env_value
    return clean_env_value(env.get(key, "") or "")


def provider_settings(name: str, env: Mapping[str, str] | None = None) -> ProviderSettings:
    """Resolve one provider from environment without exposing secret values."""
    env = os.environ if env is None else env
    normalized = name.strip().lower()
    try:
        base_key, model_key, chat_key, api_key_key = PROVIDER_ENV[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider: {name}") from exc
    disable_keys = [f"DISABLE_{normalized.upper()}"]
    if normalized == "lmstudio":
        disable_keys.append("DISABLE_LM_STUDIO")
    disabled = any(
        _value(env, key).lower() in {"1", "true", "yes", "on"}
        for key in disable_keys
    )
    return ProviderSettings(
        name=normalized,
        base_url=_value(env, base_key),
        model=_value(env, model_key),
        chat_model=_value(env, chat_key),
        api_key_configured=bool(_value(env, api_key_key)) if api_key_key else False,
        enabled=not disabled,
    )


def all_provider_settings(env: Mapping[str, str] | None = None) -> dict[str, ProviderSettings]:
    """Return normalized settings for every supported provider."""
    return {name: provider_settings(name, env) for name in PROVIDER_ENV}


def redacted_configuration(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """Return safe diagnostics for provider configuration."""
    return {
        name: {
            "base_url": settings.base_url,
            "model": settings.model,
            "chat_model": settings.chat_model,
            "api_key_configured": settings.api_key_configured,
            "enabled": settings.enabled,
        }
        for name, settings in all_provider_settings(env).items()
    }


__all__ = [
    "ProviderSettings",
    "PROVIDER_ENV",
    "all_provider_settings",
    "provider_settings",
    "redacted_configuration",
]
