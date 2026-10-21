"""Explicit feature boundaries for optional and high-risk capabilities."""

from __future__ import annotations

import os
from typing import Mapping


_FEATURE_ENV = {
    "live_trading": "MRBOT_ENABLE_LIVE_TRADING",
    "crypto_operations": "MRBOT_ENABLE_CRYPTO",
    "airdrop_claiming": "MRBOT_ENABLE_AIRDROPS",
    "defi_scanning": "MRBOT_ENABLE_DEFI",
    "social_automation": "MRBOT_ENABLE_SOCIAL_AUTOMATION",
    "self_improvement": "MRBOT_ENABLE_SELF_IMPROVEMENT",
    "autonomous_learning": "MRBOT_ENABLE_AUTONOMOUS_LEARNING",
}

_LEGACY_ENV = {
    "live_trading": "ENABLE_LIVE_TRADING",
    "crypto_operations": "ENABLE_CRYPTO",
    "airdrop_claiming": "ENABLE_AIRDROPS",
    "defi_scanning": "ENABLE_DEFI",
    "social_automation": "ENABLE_SOCIAL_AUTOMATION",
    "self_improvement": "PIPELINE_ALLOW_SELF_IMPROVE",
    "autonomous_learning": "ENABLE_AUTONOMOUS_LEARNING",
}


def _truthy(value: str) -> bool:
    """ARCH-ENG-203: delegate to the one canonical env parser.

    This was a fifth independent parser for boolean environment values, and it
    disagreed with the one reading the SAME variable.

    `_LEGACY_ENV` maps `self_improvement` to `PIPELINE_ALLOW_SELF_IMPROVE`, and
    `app/action_pipeline.py` reads that variable with `.lower() == "true"`.
    So for `PIPELINE_ALLOW_SELF_IMPROVE=1`:

        feature_enabled("self_improvement")  ->  True   (this function)
        ActionPipeline.allow_self_improve    ->  False  (== "true")

    Two components disagreed about whether self-improvement was permitted, over
    a spelling an operator would reasonably write. Neither raised; the gate was
    simply open on one path and closed on the other.

    The default is False, which preserves the fail-closed contract documented on
    `feature_enabled`: an unset variable, an empty one, or an unrecognised one
    all leave the feature disabled. Only an explicit true token enables it.
    """
    from app.effects import env_bool

    return env_bool("_truthy_input", False, env={"_truthy_input": value})


def feature_enabled(name: str, env: Mapping[str, str] | None = None) -> bool:
    """Return whether an optional feature is explicitly enabled.

    Unknown features fail closed. The legacy alias is accepted only when the
    new feature variable is absent, so operators can migrate safely.
    """
    normalized = name.strip().lower()
    key = _FEATURE_ENV.get(normalized)
    if key is None:
        return False
    values = os.environ if env is None else env
    if key in values:
        return _truthy(str(values[key]))
    legacy = _LEGACY_ENV[normalized]
    return _truthy(str(values.get(legacy, "")))


def feature_status(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Return safe, non-secret feature state for diagnostics."""
    return {name: feature_enabled(name, env) for name in _FEATURE_ENV}


def feature_env_key(name: str) -> str:
    """Return the canonical environment key for a known feature."""
    normalized = name.strip().lower()
    try:
        return _FEATURE_ENV[normalized]
    except KeyError as exc:
        raise ValueError(f"Unknown feature: {name}") from exc


__all__ = ["feature_enabled", "feature_env_key", "feature_status"]
