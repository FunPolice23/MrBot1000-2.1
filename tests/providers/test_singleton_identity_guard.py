"""Singleton-identity guard — no ``instance()`` may return the class itself.

Regression (P0): ``ProviderHotReload.instance()`` did
``if cls._instance is None: cls._instance = cls()`` then ``return cls`` — it
built the instance, stored it, and returned the bare CLASS. Every caller got the
class; the first real use (``register_callback`` / ``start``) called an instance
method on the class (missing ``self``) and raised, which main.py's try/except
swallowed into a log line. The entire provider hot-reload feature was silently
dead.

This sweep asserts every ``instance()`` classmethod in the codebase returns an
INSTANCE of its class (not the class) and is idempotent, so the ``return cls``
class cannot recur anywhere. A construction that raises for environment reasons
is skipped (that is not this bug — this bug returns the class, it does not
raise); the identity assertion only runs on a successful return.
"""
from __future__ import annotations

import importlib

import pytest

# Every module that defines a singleton with an ``instance()`` classmethod.
_SINGLETON_MODULES = [
    "agents.core.alerting",
    "agents.core.comms",
    "agents.core.event_logger",
    "agents.core.notifications",
    "agents.earning.goal_system",
    "agents.providers.provider_hot_reload",
    "agents.providers.provider_manager",
    "agents.safety.approval",
]


def _singleton_classes():
    """Yield (module_name, class_name, class) for every instance() singleton."""
    for modname in _SINGLETON_MODULES:
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for name, obj in vars(mod).items():
            if (isinstance(obj, type)
                    and getattr(obj, "instance", None) is not None
                    and callable(getattr(obj, "instance"))):
                yield modname, name, obj


def test_every_instance_returns_an_instance_not_the_class():
    """No singleton's instance() may hand back the class itself (the P0 bug)."""
    checked = 0
    for modname, name, cls in _singleton_classes():
        try:
            result = cls.instance()
        except Exception:
            # Environment-dependent construction failure — not the return-cls bug.
            continue
        assert isinstance(result, cls), (
            f"{modname}.{name}.instance() returned {type(result).__name__}, "
            f"not an instance of {name} — this is the 'return cls' singleton bug")
        assert not isinstance(result, type), (
            f"{modname}.{name}.instance() returned a CLASS, not an instance")
        assert result is cls.instance(), (
            f"{modname}.{name}.instance() is not idempotent")
        checked += 1
    assert checked >= 1, "no singleton classes were exercised"


def test_provider_hot_reload_instance_is_a_working_singleton():
    """The regressed singleton specifically: a real instance whose methods bind."""
    from agents.providers.provider_hot_reload import ProviderHotReload

    inst = ProviderHotReload.instance()
    assert isinstance(inst, ProviderHotReload)
    assert not isinstance(inst, type)
    assert inst is ProviderHotReload.instance()
    # The method that was broken when instance() returned the class: it must
    # bind self and not raise (register_callback touches self._callbacks).
    called = []
    inst.register_callback(lambda changes: called.append(changes))
    assert len(inst._callbacks) >= 1
