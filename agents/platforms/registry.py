"""
agents/platforms/registry.py — Platform adapter registry (v2.1 Phase 1).

Central registry for all platform adapters. Provides:
- Auto-discovery of available adapters
- Credential management
- Unified search across all platforms
- Rate limit tracking
"""

from typing import Dict, List, Optional, Type
from .base import PlatformAdapter
from .fiverr import FiverrAdapter
from .upwork import UpworkAdapter
from .prolific import ProlificAdapter
from .github import GitHubAdapter
from .reddit import RedditAdapter


# ── Adapter Registry ──────────────────────────────────────────────────────

ADAPTER_REGISTRY: Dict[str, Type[PlatformAdapter]] = {
    "fiverr": FiverrAdapter,
    "upwork": UpworkAdapter,
    "prolific": ProlificAdapter,
    "github": GitHubAdapter,
    "reddit": RedditAdapter,
}


def get_adapter_class(platform: str) -> Optional[Type[PlatformAdapter]]:
    """Get adapter class by platform name."""
    return ADAPTER_REGISTRY.get(platform.lower())


def list_adapters() -> List[str]:
    """List all available adapter names."""
    return list(ADAPTER_REGISTRY.keys())


def create_adapter(platform: str, gate, boundary=None, *, credentials=None, enabled=False) -> Optional[PlatformAdapter]:
    """Create an adapter instance by platform name."""
    cls = get_adapter_class(platform)
    if cls:
        return cls(gate, boundary, credentials=credentials, enabled=enabled)
    return None


def create_all_adapters(gate, boundary=None, *, credentials=None, enabled=False) -> Dict[str, PlatformAdapter]:
    """Create all available adapters."""
    adapters = {}
    for name, cls in ADAPTER_REGISTRY.items():
        adapters[name] = cls(gate, boundary, credentials=credentials, enabled=enabled)
    return adapters
