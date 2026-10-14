"""agents/runtime/provider_keys.py — provider API-key resolution (Phase 1).

The runtime's brain adapters build an OpenAI-compatible client per role. LOCAL
providers (llamacpp/ollama/lmstudio/vllm/koboldcpp) need no auth, so they keep
the historical ``"local"`` sentinel. CLOUD providers (openai, anthropic,
nvidia_nim, openrouter, ...) need a real key.

Resolution order (the key is NEVER logged, printed, or serialized):
  1. encrypted credential vault -> ``CredentialVault().get(provider, "api_key")``
  2. env ``PROVIDER_API_KEY_<PROVIDER>``   (e.g. PROVIDER_API_KEY_OPENAI)
  3. env ``<ROLE>_API_KEY``                (e.g. BIG_API_KEY) when a role prefix
                                            is supplied

Fail-closed: a cloud provider with no configured key returns ``""`` — the
caller's request then fails auth with a clear error. It never silently sends the
``"local"`` sentinel to a paid endpoint. LOCAL providers always return
``"local"`` and never touch the vault.
"""
from __future__ import annotations

import os

# Providers that run on this machine and need no authentication.
LOCAL_PROVIDERS = {"llamacpp", "ollama", "lmstudio", "vllm", "koboldcpp"}
LOCAL_KEY_SENTINEL = "local"

# Lazy singleton so per-turn client construction doesn't re-read the vault file.
_vault_singleton = None


def is_local_provider(provider: str) -> bool:
    """True for on-machine providers that need no API key."""
    return (provider or "").strip().lower() in LOCAL_PROVIDERS


def _get_vault():
    global _vault_singleton
    if _vault_singleton is None:
        from agents.platforms.credential_vault import CredentialVault
        _vault_singleton = CredentialVault()
    return _vault_singleton


def _vault_key(provider: str) -> str:
    """Fetch the provider's api_key from the encrypted vault; "" when absent.

    Any vault failure degrades to "" (never raises, never cleartext) so a broken
    vault cannot crash a brain turn — the key simply resolves from env or fails
    closed.
    """
    try:
        return (_get_vault().get(provider, "api_key") or "").strip()
    except Exception:
        return ""


def resolve_provider_api_key(provider: str, role_prefix: str = "") -> str:
    """Resolve the API key for a provider role.

    LOCAL provider -> ``"local"``. CLOUD provider -> vault key, else
    ``PROVIDER_API_KEY_<PROVIDER>`` env, else ``<ROLE>_API_KEY`` env, else ``""``
    (fail-closed). The resolved key is returned only to the in-process caller
    that feeds it straight to the HTTP client; it is never logged.
    """
    provider = (provider or "").strip().lower()
    if not provider:
        return ""
    if is_local_provider(provider):
        return LOCAL_KEY_SENTINEL

    key = _vault_key(provider)
    if key:
        return key

    key = os.getenv("PROVIDER_API_KEY_" + provider.upper(), "").strip()
    if key:
        return key

    if role_prefix:
        key = os.getenv(f"{role_prefix.upper()}_API_KEY", "").strip()
        if key:
            return key

    return ""  # fail-closed: cloud provider with no configured key


__all__ = ["resolve_provider_api_key", "is_local_provider",
           "LOCAL_PROVIDERS", "LOCAL_KEY_SENTINEL"]
