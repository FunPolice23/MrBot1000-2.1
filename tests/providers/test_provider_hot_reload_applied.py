"""ARCH-ENG-146 — the provider config handler announced "changes applied" and
applied nothing.

The standing P1 in the findings ledger: `ProviderHotReload.apply_changes`
(`agents/providers/provider_hot_reload.py:123`) is "the only code that pushes new
`.env` values into `os.environ`", and it had ZERO callers. `main.py`'s
`_on_provider_config_changed` therefore only re-detected providers from the
stale `os.environ` and hit a literal `pass` where the UI refresh should be — so
editing `.env` at runtime was detected, announced in the log, and applied to
nothing.

Reproduced by execution before the fix (all four assertions below are the
post-fix contract):

    singleton returns instance, not class : True
    PRE-FIX  os.environ has TEETH_KEY     : False   <- re-detect alone changes nothing
    POST-FIX os.environ has TEETH_KEY     : True
    POST-FIX value pushed                 : sk-simulated
    POST-FIX empty value removes the key  : True

The singleton-identity P0 (`f98dd98`) is asserted here too, because a broken
`instance()` makes every call site below silently re-raise or bind the class.
"""

from __future__ import annotations

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.providers.provider_hot_reload import ProviderHotReload
from agents.providers.provider_manager import ProviderManager


class TestProviderHotReloadIsApplied(unittest.TestCase):

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self._key = "ARCH_ENG_146_TEETH_KEY"
        os.environ.pop(self._key, None)

    def tearDown(self):
        os.environ.pop(self._key, None)

    def test_instance_returns_the_instance_not_the_class(self):
        """The P0 from f98dd98: `return cls` instead of `return cls._instance`."""
        hr = ProviderHotReload.instance()
        self.assertIs(type(hr), ProviderHotReload)
        self.assertIsNot(hr, ProviderHotReload)
        self.assertIs(ProviderHotReload.instance(), hr, "must be a real singleton")

    def test_apply_changes_pushes_values_into_os_environ(self):
        """The defect: without a caller, a detected .env edit changed nothing."""
        self.assertNotIn(self._key, os.environ, "precondition")

        # The PRE-FIX body — re-detect only. This is what used to run.
        ProviderManager.instance().detect_providers()
        self.assertNotIn(
            self._key, os.environ,
            "re-detecting alone must NOT apply a change — that was the bug",
        )

        # The POST-FIX body — actually apply.
        ProviderHotReload.instance().apply_changes({self._key: "sk-simulated"})
        self.assertEqual(os.environ.get(self._key), "sk-simulated")

    def test_apply_changes_removes_a_cleared_value(self):
        """A blank field must clear the key, not blank it (blank still 'works')."""
        os.environ[self._key] = "old-value"
        ProviderHotReload.instance().apply_changes({self._key: ""})
        self.assertNotIn(self._key, os.environ)

    def test_main_window_config_handler_calls_apply_changes(self):
        """The wiring: the GUI handler must reach the applier, not a `pass`."""
        import inspect

        import main

        src = inspect.getsource(main)
        # The handler must call apply_changes ...
        self.assertIn("apply_changes", src, "apply_changes has no caller in main.py")
        # ... and reach it from the provider config-change handler.
        handler = inspect.getsource(main.MainWindow._on_provider_config_changed)
        self.assertIn(
            "apply_changes", handler,
            "the config handler must apply the changes it just announced",
        )
        # The dead UI-refresh placeholder must be gone.
        self.assertNotIn("Refresh current tab if it's a provider-related tab", handler)


if __name__ == "__main__":
    unittest.main()
