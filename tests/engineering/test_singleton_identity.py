"""Singleton-identity guard (closes the P0 hot-reload recurrence risk).

The P0 shipped because ProviderHotReload.instance() did `return cls` (the bare
class) instead of `return cls._instance` — a broken singleton that silently
killed the whole provider hot-reload feature. Nothing pinned the invariant, so
it recurred. This test locks it for ALL 8 `instance()` singletons:

  (1) instance() returns an INSTANCE of the class, not the class itself
      (catches `return cls`), and
  (2) instance() is a CACHED singleton — the same object on repeated calls
      (catches `return cls()` without caching).

Reverting any singleton to `return cls` or an uncached `return cls()` fails the
corresponding subTest.
"""
import sys
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _singletons():
    from agents.providers.provider_manager import ProviderManager
    from agents.providers.provider_hot_reload import ProviderHotReload
    from agents.core.notifications import NotificationService
    from agents.core.comms import EventBus
    from agents.core.event_logger import StructuredEventLogger
    from agents.core.alerting import AlertRuleEngine
    from agents.safety.approval import HumanApprovalQueue
    from agents.earning.goal_system import GoalTracker
    return [
        ProviderManager, ProviderHotReload, NotificationService, EventBus,
        StructuredEventLogger, AlertRuleEngine, HumanApprovalQueue, GoalTracker,
    ]


class SingletonIdentityTest(unittest.TestCase):
    def test_every_instance_is_a_cached_singleton(self):
        for cls in _singletons():
            with self.subTest(singleton=cls.__name__):
                # Reset so we exercise the instance() construction path fresh.
                if hasattr(cls, "_instance"):
                    cls._instance = None
                a = cls.instance()
                b = cls.instance()
                # (1) an INSTANCE, not the class (catches `return cls`).
                self.assertIsInstance(
                    a, cls,
                    f"{cls.__name__}.instance() must return an instance, not the class")
                # (2) cached singleton (catches `return cls()` uncached).
                self.assertIs(
                    a, b,
                    f"{cls.__name__}.instance() must return the same cached instance")


if __name__ == "__main__":
    unittest.main()
