"""
agents/platforms/__init__.py — Platform adapter exports (v2.1 Phase 1).
"""

from .base import PlatformAdapter
from .fiverr import FiverrAdapter
from .upwork import UpworkAdapter
from .prolific import ProlificAdapter
from .github import GitHubAdapter
from .reddit import RedditAdapter
from .registry import (
    ADAPTER_REGISTRY,
    get_adapter_class,
    list_adapters,
    create_adapter,
    create_all_adapters,
)

__all__ = [
    "PlatformAdapter",
    "FiverrAdapter",
    "UpworkAdapter",
    "ProlificAdapter",
    "GitHubAdapter",
    "RedditAdapter",
    "ADAPTER_REGISTRY",
    "get_adapter_class",
    "list_adapters",
    "create_adapter",
    "create_all_adapters",
]
