"""ARCH-ENG-309 — the N-Brain Roster panel is gone from the Providers_GPU tab.

Between Compute Devices and Provider Control the tab rendered the Phase-4
roster UI: per-tier count spinners ("Big Brains" / "Small Brains") plus one
editable provider/model/device row per slot. That was a SECOND model-selection
surface: Provider Control already owns model selection and per-slot settings,
so two editors could disagree about which model a slot launches, and the
count spinners spawned slot rows the operator could not see in Provider
Control at all.

The panel is an editing surface only. The roster DATA (settings.json) still
drives extra slots at launch, cleanup()'s ARCH-ENG-153 flush remains (a safe
no-op with no panel, pinned structurally by
tests/engineering/test_arch_eng_153_roster_debounce_launch_read.py), and
brain_roster_panel.py keep its standalone unit tests.
"""

import inspect
import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])  # noqa: E402

from gui.widgets.dual_brain_control import DualBrainControl  # noqa: E402
from agents.runtime.dual_brain import DualBrainRuntime  # noqa: E402
from agents.providers.provider_manager import ProviderManager  # noqa: E402


def _wait_detected(app, timeout=5):
    deadline = time.time() + timeout
    while not ProviderManager.instance()._detected and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)


class TestTheRosterPanelIsRemoved(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app

    def _widget(self):
        w = DualBrainControl(runtime=DualBrainRuntime.from_env())
        self.app.processEvents()
        _wait_detected(self.app)
        w._apply_runtime()
        self.app.processEvents()
        return w

    def test_construction_no_longer_builds_a_roster_panel(self):
        w = self._widget()
        try:
            self.assertFalse(
                hasattr(w, "brain_roster_panel"),
                "DualBrainControl still builds brain_roster_panel — the "
                "duplicate Big/Small-Brains model-selection surface is back")
        finally:
            w._closing = True

    def test_provider_control_rows_still_render(self):
        """Vacuity probe: removing the panel must not break the real editor."""
        w = self._widget()
        try:
            self.assertGreaterEqual(
                len(w._provider_rows), 2,
                "Provider Control lost its one-click launch rows")
        finally:
            w._closing = True

    def test_the_tab_source_never_instantiates_the_panel(self):
        """Static guard: even a try/except instantiation would be caught."""
        src = inspect.getsource(DualBrainControl)
        self.assertNotIn(
            "BrainRosterPanel(self)", src,
            "DualBrainControl instantiates BrainRosterPanel again (ARCH-ENG-309)")


if __name__ == "__main__":
    unittest.main()
