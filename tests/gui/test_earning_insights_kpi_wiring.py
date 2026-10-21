"""Phase 4 roster P1: earning_insights KPI cells show real state, not frozen.

The KPI cells (LLM Spend / Uptime) previously rendered at placeholders
forever because their setters had no callers. They are derived from the
event log (the single source accessible to the panel): llm_spend events
carry est_usd, and uptime is session-elapsed.

ARCH-ENG-243 (BD-01): the spend KPI's source became LIVE in production too
-- big/small brains and the worker mixin now emit llm_spend events at LLM
call completion. The heartbeat/tier KPIs were REMOVED with their emitter:
they reported the legacy manager heartbeat the runtime had already
retired, so their rows could never again mean anything.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest  # noqa: E402
import time  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from agents.core.event_logger import StructuredEventLogger  # noqa: E402
from gui.tabs.earning_insights import TabAwareInsightsPanel  # noqa: E402


class TestInsightsKPIWiring(unittest.TestCase):
    def _panel(self, event_logger):
        return TabAwareInsightsPanel(parent=None, earning_tab=None,
                                     approval_queue=None,
                                     event_logger=event_logger)

    def test_kpis_reflect_event_log(self):
        el = StructuredEventLogger.instance()
        el.llm_spend_event(model="gpt-4o-mini", provider="openai",
                           tokens=1000, est_usd=5.0)
        panel = self._panel(el)
        try:
            self._app = _app
            _app.processEvents()
            panel._refresh()
            _app.processEvents()
            time.sleep(0.05)
            self.assertIn("$5.00", panel.spend_label.text(),
                          "LLM Spend must reflect llm_spend est_usd")
            self.assertIsNotNone(panel._uptime_label)
            self.assertIn("h", panel._uptime_label.text(),
                          "Uptime must show session-elapsed hours")
        finally:
            pass

    def test_the_removed_heartbeat_kpi_is_not_rendered(self):
        """ARCH-ENG-243: the legacy heartbeat/tier rows are gone, not
        frozen placeholders that nothing can ever refresh."""
        panel = self._panel(StructuredEventLogger.instance())
        self.assertFalse(hasattr(panel, "heartbeat_label"))
        self.assertFalse(hasattr(panel, "tier_label"))
        self.assertFalse(hasattr(panel, "set_heartbeat"))
        self.assertFalse(hasattr(panel, "set_tier"))


if __name__ == "__main__":
    unittest.main()
