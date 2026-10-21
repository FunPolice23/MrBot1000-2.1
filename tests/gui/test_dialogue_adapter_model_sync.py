"""ARCH-ENG-139: the adapter-model sync was defined nowhere (ledger P1).

`gui/tabs/dialogue_tab.py` guarded on ``hasattr(self, "_sync_adapter_models")``
in two places — the construction-time ``_sync_and_check_capabilities`` and the
per-turn "Sync adapter models from GUI selection before responding" step — but
the method was DEFINED NOWHERE in the repo. Both guards were permanently False,
so the per-turn sync was a silent no-op on every turn. The real implementation is
singular (``ProviderLifecycleBackend._sync_adapter_model(small)``) and lives on a
different class that a plain ``QWidget`` cannot call.

The adapter's ``.model`` is the id sent in the chat request, so a stale value is
the mechanism behind the 400-model-not-found dialogue errors
(``reports/reality-check-2026-09-17.md:101``).

These tests target the BEHAVIOUR the guard promised: after the sync, each
adapter's model equals the GUI/runtime selection. They fail if the method is
removed or stops writing to the adapters.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gui.tabs.dialogue_tab import DialogueTab  # noqa: E402


class _FakeBrain:
    """Minimal adapter stand-in: records what the sync wrote to it."""

    def __init__(self):
        self.model = "STALE_MODEL.gguf"
        self.set_model_calls = []

    def set_model(self, name):
        self.set_model_calls.append(name)
        self.model = name


class _LegacyBrain:
    """An adapter predating set_model — must still be updated."""

    def __init__(self):
        self.model = "STALE_MODEL.gguf"


def _tab():
    with mock.patch.object(DialogueTab, "__init__", lambda self, *a, **k: None):
        tab = DialogueTab.__new__(DialogueTab)
    tab.small_brain = _FakeBrain()
    tab.big_brain = _FakeBrain()
    return tab


def _cfg(provider="llamacpp", model=""):
    return SimpleNamespace(provider=provider, model=model, enabled=True)


class TestSyncMethodExists(unittest.TestCase):
    """The guard promised a method; prove it is really there."""

    def test_method_is_defined_on_the_class(self):
        self.assertTrue(
            hasattr(DialogueTab, "_sync_adapter_models"),
            "the per-turn sync guard has been guarding a method that does not "
            "exist — it is a permanent no-op")
        self.assertTrue(
            callable(DialogueTab._sync_adapter_models),
            "_sync_adapter_models must be callable")

    def test_the_per_turn_guard_is_satisfied(self):
        """The exact expression at dialogue_tab.py:1215 must now be True."""
        tab = _tab()
        self.assertTrue(
            hasattr(tab, "_sync_adapter_models")
            and callable(getattr(tab, "_sync_adapter_models", None)),
            "the per-turn guard must no longer be permanently False")


class TestSyncPushesSelectionOntoAdapters(unittest.TestCase):
    def test_selected_model_reaches_both_adapters(self):
        tab = _tab()
        big, small = _cfg(model="BIG_NEW.gguf"), _cfg(model="SMALL_NEW.gguf")
        runtime = mock.MagicMock()
        runtime.config.side_effect = lambda role: small if role.value == "small" else big
        with mock.patch(
                "agents.runtime.dual_brain.DualBrainRuntime.from_env",
                return_value=runtime):
            tab._sync_adapter_models()
        self.assertEqual(tab.big_brain.model, "BIG_NEW.gguf")
        self.assertEqual(tab.small_brain.model, "SMALL_NEW.gguf")

    def test_uses_the_adapters_own_switch_path(self):
        """set_model is the adapters' documented switch entry point."""
        tab = _tab()
        runtime = mock.MagicMock()
        runtime.config.side_effect = lambda role: _cfg(model="X.gguf")
        with mock.patch(
                "agents.runtime.dual_brain.DualBrainRuntime.from_env",
                return_value=runtime):
            tab._sync_adapter_models()
        self.assertEqual(tab.big_brain.set_model_calls, ["X.gguf"])
        self.assertEqual(tab.small_brain.set_model_calls, ["X.gguf"])

    def test_adapter_without_set_model_is_still_updated(self):
        """Back-compat: an adapter predating set_model must not be skipped."""
        tab = _tab()
        tab.big_brain = _LegacyBrain()
        runtime = mock.MagicMock()
        runtime.config.side_effect = lambda role: _cfg(model="LEGACY.gguf")
        with mock.patch(
                "agents.runtime.dual_brain.DualBrainRuntime.from_env",
                return_value=runtime):
            tab._sync_adapter_models()
        self.assertEqual(tab.big_brain.model, "LEGACY.gguf")


class TestSyncSafety(unittest.TestCase):
    def test_empty_selection_does_not_erase_a_working_model(self):
        """A blank config must not blank the adapter — that would cause the
        very 400s this fix prevents."""
        tab = _tab()
        runtime = mock.MagicMock()
        runtime.config.side_effect = lambda role: _cfg(model="")
        with mock.patch(
                "agents.runtime.dual_brain.DualBrainRuntime.from_env",
                return_value=runtime):
            tab._sync_adapter_models()
        self.assertEqual(tab.big_brain.model, "STALE_MODEL.gguf")
        self.assertEqual(tab.small_brain.model, "STALE_MODEL.gguf")

    def test_runtime_failure_never_raises(self):
        """This runs on the GUI thread — an exception would kill the turn."""
        tab = _tab()
        with mock.patch(
                "agents.runtime.dual_brain.DualBrainRuntime.from_env",
                side_effect=RuntimeError("no runtime")):
            tab._sync_adapter_models()  # must not raise
        self.assertEqual(tab.big_brain.model, "STALE_MODEL.gguf")

    def test_missing_brain_is_tolerated(self):
        tab = _tab()
        tab.small_brain = None
        runtime = mock.MagicMock()
        runtime.config.side_effect = lambda role: _cfg(model="A.gguf")
        with mock.patch(
                "agents.runtime.dual_brain.DualBrainRuntime.from_env",
                return_value=runtime):
            tab._sync_adapter_models()  # must not raise
        self.assertEqual(tab.big_brain.model, "A.gguf")

    def test_per_brain_failure_does_not_block_the_other(self):
        """One bad slot must not leave the healthy one stale."""
        tab = _tab()

        class _Boom:
            def set_model(self, name):
                raise ValueError("adapter exploded")

        tab.big_brain = _Boom()
        runtime = mock.MagicMock()
        runtime.config.side_effect = lambda role: _cfg(model="OK.gguf")
        with mock.patch(
                "agents.runtime.dual_brain.DualBrainRuntime.from_env",
                return_value=runtime):
            tab._sync_adapter_models()
        self.assertEqual(tab.small_brain.model, "OK.gguf")


if __name__ == "__main__":
    unittest.main()
