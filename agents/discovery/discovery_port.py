"""Application-facing discovery boundary.

The service owns source selection and discovery orchestration.  Evaluation,
memory persistence, and lifecycle decisions remain outside this boundary.
"""

from __future__ import annotations

from typing import Callable, Iterable

from agents.discovery.discovery_engine import DiscoveryEngine, DiscoveryStats
from agents.earning.opportunity_models import Opportunity


class BuiltinDiscoveryService:
    """Adapt the built-in source registry to a narrow pipeline-facing port."""

    def __init__(
        self,
        *,
        source_factory: Callable[[], Iterable[object]] | None = None,
        engine_factory: Callable[..., DiscoveryEngine] = DiscoveryEngine,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        if source_factory is None:
            from agents.discovery.discovery_sources import all_builtin_sources
            source_factory = all_builtin_sources
        self._source_factory = source_factory
        self._engine_factory = engine_factory
        self._log = log_fn or (lambda _message: None)

    def discover(
        self,
        requested: Iterable[str],
        *,
        page: int = 1,
        query: str | None = None,
    ) -> tuple[list[Opportunity], dict[str, str], DiscoveryStats]:
        sources = list(self._source_factory())
        by_name = {source.name: source for source in sources}
        requested_names = list(requested)
        engine_sources = [
            by_name[name] for name in requested_names if name in by_name
        ]
        for name in requested_names:
            if name not in by_name:
                self._log(f"[Discover] Invalid source '{name}' blocked")
        engine = self._engine_factory(engine_sources, throttle=False)
        try:
            return engine.discover_all(page=max(1, int(page)), query=query)
        except TypeError as exc:
            # Tolerate injected engines implementing the pre-query signature.
            if "query" not in str(exc):
                raise
            return engine.discover_all(page=max(1, int(page)))


__all__ = ["BuiltinDiscoveryService"]
