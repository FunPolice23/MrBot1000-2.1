"""Application service for discovery orchestration in the earning domain."""

from __future__ import annotations

import time
from typing import Any, Callable, List, Optional

from agents.earning.opportunity_adapters import canonical_to_legacy


class EarningDiscoveryService:
    """Run built-in discovery and project results into the legacy pipeline API."""

    def __init__(
        self,
        *,
        memory: Any,
        log_fn: Callable[[str], None],
        legacy_type: type,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._memory = memory
        self._log = log_fn
        self._legacy_type = legacy_type
        self._sleep = sleep_fn

    def discover(
        self,
        sources: Optional[List[str]] = None,
        on_found: Optional[Callable[[Any], None]] = None,
        page: int = 1,
        query: Optional[str] = None,
    ) -> List[Any]:
        """Discover, persist provenance, and return legacy opportunities."""
        # Registry names only. "content" was removed from the builtin sources
        # (ContentSource is deprecated and yields nothing), so requesting it
        # only produced a "[Discover] Invalid source 'content' blocked" warning.
        requested = sources or [
            "social", "upwork", "fiverr", "airdrop",
            "defi", "microtask", "ugig", "moltbook", "web", "dynamic",
        ]
        from agents.discovery.discovery_port import BuiltinDiscoveryService

        discovery = BuiltinDiscoveryService(log_fn=self._log)
        found, errors, _stats = discovery.discover(requested, page=page, query=query)
        for name, error in errors.items():
            self._log(f"[Discover] Error from {name}: {error}")

        opportunities = []
        for canonical in found:
            self._memory.remember_opportunity(canonical.opportunity_id, {
                "title": canonical.title,
                "description": canonical.description,
                "platform": canonical.platform,
                "type": canonical.category,
                "source": canonical.source,
                "category": canonical.category,
                "subcategory": canonical.subcategory,
                "task_type": canonical.task_type,
                "payment_type": canonical.payment_type,
                "currency": canonical.currency,
                "advertised_amount": canonical.advertised_amount,
                "min_amount": canonical.advertised_amount,
                "provenance": canonical.provenance,
            }, canonical.category)
            adapted = canonical_to_legacy(canonical, self._legacy_type)
            opportunities.append(adapted)
            if on_found is not None:
                on_found(adapted)
            self._log(
                f"[Discover] Found {canonical.title!r} "
                f"({canonical.category}) from {canonical.source}"
            )
            self._sleep(0.2)
        return opportunities


__all__ = ["EarningDiscoveryService"]
