"""agents/discovery_engine.py — Orchestration for pluggable opportunity discovery.

The DiscoveryEngine is the single place that:
- holds a registry of OpportunitySource instances (pluggable: add your own without
  touching the pipeline),
- runs each source with per-source throttling (via platform_throttle) so no platform
  is spammed,
- deduplicates across sources using normalized identity fingerprinting,
- isolates a failing source (its error is recorded, others still run),
- tags provenance on every returned opportunity,
- returns (opportunities, errors, stats) so callers can audit what happened.

It deliberately does NOT evaluate or validate here — DISCOVERY is one stage; VALIDATION
and EVALUATION are separate (see opportunity_models.validate_opportunity and the
pipeline's evaluate()). A discovered listing is never "verified" merely by being found.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from agents.opportunity_models import (
    Opportunity, OpportunitySource, OpportunityDeduplicator,
)


@dataclass
class DiscoveryStats:
    sources: int = 0
    raw: int = 0
    deduped: int = 0
    errors: int = 0
    duration_s: float = 0.0
    by_category: Dict[str, int] = field(default_factory=dict)
    by_source: Dict[str, int] = field(default_factory=dict)


class DiscoveryEngine:
    """Runs registered sources, dedups, isolates failures, reports stats."""

    def __init__(self, sources: List[OpportunitySource] = None,
                 throttle: bool = True):
        self._registry: List[OpportunitySource] = list(sources or [])
        self._throttle = throttle
        self._dedup = OpportunityDeduplicator()

    def add_source(self, src: OpportunitySource) -> "DiscoveryEngine":
        """Register an additional source WITHOUT modifying core pipeline code."""
        self._registry.append(src)
        return self

    def sources(self) -> List[OpportunitySource]:
        return list(self._registry)

    def discover_all(self) -> Tuple[List[Opportunity], Dict[str, str], DiscoveryStats]:
        stats = DiscoveryStats(sources=len(self._registry))
        start = time.time()
        results: List[Opportunity] = []
        errors: Dict[str, str] = {}

        for src in self._registry:
            if not src.is_enabled():
                continue
            try:
                if self._throttle:
                    self._acquire(src.name)
                found = src.discover()
            except Exception as e:  # noqa: BLE001 - isolate one bad source
                errors[src.name] = str(e)
                stats.errors += 1
                continue

            stats.raw += len(found)
            stats.by_source[src.name] = stats.by_source.get(src.name, 0) + len(found)
            for o in found:
                # Ensure provenance always identifies the external origin.
                if not o.provenance:
                    o.provenance = f"{src.name}::{o.external_url or o.title}"
                if not self._dedup.seen(o):
                    self._dedup.add(o)
                    results.append(o)
                    cat = o.category or "other"
                    stats.by_category[cat] = stats.by_category.get(cat, 0) + 1

        stats.deduped = len(results)
        stats.duration_s = round(time.time() - start, 3)
        return results, errors, stats

    def reset_dedup(self) -> None:
        self._dedup.reset()

    @staticmethod
    def _acquire(name: str) -> None:
        try:
            from agents.platform_throttle import get_throttle
            get_throttle().acquire(name)
        except Exception:
            # Throttle is a best-effort guard; never block discovery on its failure.
            pass
