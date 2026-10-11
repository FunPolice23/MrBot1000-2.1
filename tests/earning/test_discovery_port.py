from agents.discovery.discovery_engine import DiscoveryStats
from agents.discovery.discovery_port import BuiltinDiscoveryService


class _Source:
    name = "fixture"

    def is_enabled(self):
        return True

    def discover(self, page=1):
        return []


class _Engine:
    def __init__(self, sources, throttle):
        assert sources
        assert throttle is False

    def discover_all(self, page=1):
        return [], {}, DiscoveryStats(sources=1)


def test_discovery_service_selects_sources_without_evaluation():
    messages = []
    service = BuiltinDiscoveryService(
        source_factory=lambda: [_Source()],
        engine_factory=_Engine,
        log_fn=messages.append,
    )

    opportunities, errors, stats = service.discover(["fixture", "missing"])

    assert opportunities == []
    assert errors == {}
    assert stats.sources == 1
    assert messages == ["[Discover] Invalid source 'missing' blocked"]
