# MrBot1000 - Earning Pipeline Agent
"""
MrBot1000: Real-time earning pipeline with multi-tiered memory system.

This package provides:
- Earning discovery from social platforms, freelance sites, airdrops, DeFi
- Multi-tiered memory for opportunity tracking and learning
- Direct pipeline execution: discover → evaluate → filter → execute → track
- Local Ollama integration with optional cloud provider fallback
"""

# Authoritative release version lives in app/version.py. Re-exported here (with
# a static fallback) so `import MrBot1000` reports the real release instead of a
# hand-maintained duplicate that drifts — v2.1.31 fixed a ~30-release drift.
try:
    from app.version import __version__  # noqa: F401
except Exception:  # pragma: no cover - app.version has no dependencies
    __version__ = "2.1.31"
__author__ = "MrBot1000 Team"