"""ARCH-ENG-140: the unparented provider-panel path is gone (ledger P1).

`DualBrainControl._build_provider_panels` built 12+ provider QFrames on every
detection-ready callback, **never parented them and never added them to any
layout** — nothing called `layout.addWidget(panel)` for them. They were
constructed and discarded. Worse, their controls were live:
`_on_model_changed` fired on `currentTextChanged` and wrote BOTH
`BIG_BRAIN_MODEL` and `SMALL_BRAIN_MODEL` through `set_env_values`, persisting to
`.env` — so picking one item in an invisible panel rewrote persisted config for
both roles (reproduced by execution before removal: one simulated combo pick
rewrote both `.env` brain-model lines).

It also contained a dead `hasattr(self, 'provider_group')` guard whose body was a
comment plus a stray-indented `pass`, and a SECOND `_on_context_changed` whose
`(provider_name, context_size)` signature was silently shadowed by the live
`(is_big: bool)` one later in the class body.

These tests lock the removal: the dead constructors must stay gone, and the one
real `_on_context_changed` must be the only one.
"""
import inspect
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gui.widgets.dual_brain_control import DualBrainControl  # noqa: E402


class TestDeadPanelPathRemoved(unittest.TestCase):
    def test_build_provider_panels_is_gone(self):
        self.assertFalse(
            hasattr(DualBrainControl, "_build_provider_panels"),
            "the unparented-panel builder must not come back — it wrote .env "
            "from an invisible GUI callback")

    def test_create_provider_panel_is_gone(self):
        self.assertFalse(hasattr(DualBrainControl, "_create_provider_panel"))

    def test_the_env_writing_model_handler_is_gone(self):
        """_on_model_changed(n, text) wrote BIG+SMALL_BRAIN_MODEL to .env."""
        self.assertFalse(
            hasattr(DualBrainControl, "_on_model_changed"),
            "the handler that persisted both brain models from an invisible "
            "panel must stay removed")

    def test_gpu_assignment_handler_is_gone(self):
        self.assertFalse(hasattr(DualBrainControl, "_on_gpu_assignment_changed"))

    def test_panels_built_flag_is_gone(self):
        self.assertFalse(hasattr(DualBrainControl, "_provider_panels_built"))


class TestShadowedHandlerResolved(unittest.TestCase):
    def test_exactly_one_context_changed_definition(self):
        """The dead (provider_name, context_size) twin shadowed the live one."""
        source = inspect.getsource(DualBrainControl)
        self.assertEqual(
            source.count("def _on_context_changed"), 1,
            "a duplicate _on_context_changed is back — one silently shadows "
            "the other, so a signal wired to the dead signature would either "
            "no-op or raise")

    def test_the_surviving_handler_has_the_live_signature(self):
        params = list(
            inspect.signature(DualBrainControl._on_context_changed).parameters)
        self.assertEqual(
            params, ["self", "is_big"],
            "the live per-role handler must win, not the per-provider twin")

    def test_no_orphan_provider_panels_attribute(self):
        """Nothing may read a provider_panels dict that is never built."""
        source = inspect.getsource(DualBrainControl)
        self.assertNotIn(
            "self.provider_panels", source,
            "a provider_panels dict with no builder is an orphan")


class TestLivePathUntouched(unittest.TestCase):
    """The real provider UI must still exist — the removal was of dead code."""

    def test_provider_config_widget_still_has_its_model_handler(self):
        from gui.widgets.provider_config_widget import ProviderConfigWidget
        self.assertTrue(
            hasattr(ProviderConfigWidget, "_on_model_changed"),
            "the LIVE provider UI path must be untouched")

    def test_lifecycle_backend_sync_still_exists(self):
        from gui.workers.provider_lifecycle_backend import (
            ProviderLifecycleBackend)
        self.assertTrue(
            hasattr(ProviderLifecycleBackend, "_sync_adapter_model"),
            "the real adapter-model sync must still exist")


if __name__ == "__main__":
    unittest.main()
