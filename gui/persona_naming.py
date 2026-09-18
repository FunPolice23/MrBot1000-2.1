"""Persona-aware naming for dialogue.

Uses BIG_BRAIN_NAME / SMALL_BRAIN_NAME env vars (configured by user),
falling back to Edward Hurst / Jacob Stanley defaults.
"""
from __future__ import annotations

import os


def big_brain_name() -> str:
    return os.getenv("BIG_BRAIN_NAME", "Edward Hurst").strip() or "Edward Hurst"


def small_brain_name() -> str:
    return os.getenv("SMALL_BRAIN_NAME", "Jacob Stanley").strip() or "Jacob Stanley"


def _persona_name(speaker: str) -> str:
    """Map legacy/alias speaker keys to canonical persona display names."""
    s = (speaker or "").lower()
    big = big_brain_name()
    small = small_brain_name()
    
    # Match big brain
    if s in ("big", "big brain", "driver", "driver (big)",
             "edward", "edward hurst", "hurst"):
        return big

    # Match small brain
    if s in ("small", "small brain", "navigator", "navigator (small)",
             "jacob", "jacob stanley", "stanley"):
        return small

    if s == "human":
        return "Human"

    return speaker or big


# Colors (kept stable regardless of name)
DRIVER_COLOR = "#4fc3f7"
NAVIGATOR_COLOR = "#03dac6"
HUMAN_COLOR = "#ffb300"
SYS_COLOR = "#9e9e9e"


def _emoji(speaker: str) -> str:
    n = _persona_name(speaker)
    big = big_brain_name()
    small = small_brain_name()
    return {big: "🚀", small: "🧭", "Human": "👤"}.get(n, "💬")


def _color(speaker: str) -> str:
    n = _persona_name(speaker)
    big = big_brain_name()
    small = small_brain_name()
    return {big: DRIVER_COLOR, small: NAVIGATOR_COLOR, "Human": HUMAN_COLOR}.get(n, SYS_COLOR)
