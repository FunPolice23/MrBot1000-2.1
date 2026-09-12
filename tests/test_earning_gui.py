"""tests/test_earning_gui.py — GUI smoke test for EarningTab."""
import sys
sys.path.insert(0, ".")

from PySide6.QtWidgets import QApplication
import pytest


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_earning_tab_builds(qt_app):
    from gui.earning_tab import EarningTab
    tab = EarningTab()
    assert tab is not None
    assert tab.log_edit is not None
    assert tab.freelance_table is not None
    assert tab.microtask_table is not None
    assert tab.crypto_wallets_table is not None
    assert tab.autonomy_log is not None
    assert tab._get_wallet_manager() is None  # parent-less


def test_tab_builder_delegates_earning_tab():
    from gui.tab_builders import TabBuildersMixin
    mixin = TabBuildersMixin()
    tab = mixin.create_earnings_tab()
    assert tab is not None


def test_insights_renders_structured_events(qt_app):
    from agents.event_logger import Event
    from gui.earning_insights import EarningInsightsPanel

    panel = EarningInsightsPanel()
    panel.set_events([Event(source="test", message="earning recorded")])
    assert panel.event_list.count() == 1
    assert "earning recorded" in panel.event_list.item(0).text()
