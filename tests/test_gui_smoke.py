"""
tests/test_gui_smoke.py — GUI smoke tests for tabs not covered by test_earning_gui.py.

Verifies that each major GUI tab/widget builds without crashing when constructed
with minimal/mocked dependencies. These are lightweight smoke tests, not functional
tests — they confirm the UI surface is constructible, not that it works end-to-end.

Follows the pattern established in test_earning_gui.py.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

import sys
sys.path.insert(0, ".")


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qt_app():
    """Provide a QApplication instance for GUI tests (session-scoped)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_brain_mock(model: str = "test-model", base_url: str = "http://127.0.0.1:1234/v1"):
    """Return a minimal mock that satisfies DialogueTab/ChatTab constructor needs."""
    m = Mock()
    m.model = model
    m.base_url = base_url
    m.chat = Mock(return_value="mock reply")
    m.analyze_with_tools = Mock(return_value="mock analysis")
    return m


# ── Approval Panel ───────────────────────────────────────────────────────────

def test_approval_panel_builds(qt_app):
    from gui.approval_panel import ApprovalPanel
    from agents.approval_queue import HumanApprovalQueue

    panel = ApprovalPanel(approval_queue=HumanApprovalQueue.instance())
    assert panel is not None
    assert panel.list_widget is not None
    assert panel.status_label is not None
    assert panel.approve_btn is not None
    assert panel.deny_btn is not None
    assert panel.defer_btn is not None
    # Initial state: no pending items
    assert panel.status_label.text() == "No pending approvals"


def test_approval_panel_refresh_clears_after_init(qt_app):
    from gui.approval_panel import ApprovalPanel
    from agents.approval_queue import HumanApprovalQueue

    panel = ApprovalPanel(approval_queue=HumanApprovalQueue.instance())
    # After construction the refresh timer fires once; status should be clear.
    assert "pending" not in panel.status_label.text().lower() or \
           panel.status_label.text() == "No pending approvals"


# ── Dialogue Tab ─────────────────────────────────────────────────────────────

def test_dialogue_tab_builds(qt_app):
    from gui.dialogue_tab import DialogueTab

    tab = DialogueTab(
        small_brain=_make_brain_mock("small-model"),
        big_brain=_make_brain_mock("big-model"),
    )
    assert tab is not None
    assert tab.chat_display is not None
    assert tab.goal_input is not None
    assert tab.auto_btn is not None
    assert tab.live_btn is not None
    assert tab.step_btn is not None
    assert tab.reset_btn is not None
    assert tab.help_btn is not None
    assert tab.input is not None
    assert tab.send_btn is not None
    # Goal field empty initially
    assert tab.goal == ""


def test_dialogue_tab_set_goal(qt_app):
    from gui.dialogue_tab import DialogueTab

    tab = DialogueTab(
        small_brain=_make_brain_mock(),
        big_brain=_make_brain_mock(),
    )
    tab.set_goal("Test earning goal")
    assert tab.goal == "Test earning goal"
    assert tab.goal_input.text() == "Test earning goal"
    # Phase should reset
    assert tab._phase_index == 0


# ── Chat Tab ────────────────────────────────────────────────────────────────

def test_chat_tab_builds(qt_app):
    from gui.chat_tab import ChatTab

    tab = ChatTab(
        small_brain=_make_brain_mock("small"),
        big_brain=_make_brain_mock("big"),
    )
    assert tab is not None
    assert tab.chat_display is not None
    assert tab.input is not None
    assert tab.send_btn is not None
    assert tab.thinking_toggle_btn is not None


# ── Provider Config Widget ──────────────────────────────────────────────────

def test_provider_config_widget_builds(qt_app):
    from gui.provider_config_widget import ProviderConfigWidget

    widget = ProviderConfigWidget()
    assert widget is not None
    assert widget.type_tabs is not None
    assert widget.active_cloud is not None
    assert widget.active_local is not None
    assert widget.big_brain_name is not None
    assert widget.small_brain_name is not None
    assert widget.status_label is not None
    # Initial status
    assert widget.status_label.text() == "Ready"


def test_provider_config_widget_cloud_local_tabs(qt_app):
    from gui.provider_config_widget import ProviderConfigWidget

    widget = ProviderConfigWidget()
    # Should have two tabs: Cloud and Local
    assert widget.type_tabs.count() == 2
    assert "Cloud" in widget.type_tabs.tabText(0)
    assert "Local" in widget.type_tabs.tabText(1)


# ── Collaboration Tab ──────────────────────────────────────────────────────

def test_collaboration_tab_builds(qt_app):
    from gui.collaboration_tab import CollaborationTab
    from agents.comms import MessageStatus
    from agents.dual_brain_coordinator import RunRecord, StageRun, CollaborationStage
    from agents.dual_brain_runtime import BrainRole

    run = RunRecord(
        run_id="test-run-001",
        goal="test goal",
        correlation_id="corr-001",
        status=MessageStatus.DONE,
        stages=[
            StageRun(stage=CollaborationStage.PLAN, role=BrainRole.BIG, model="test", prompt="plan prompt"),
            StageRun(stage=CollaborationStage.RESEARCH, role=BrainRole.SMALL, model="test", prompt="research prompt"),
        ],
    )
    mock_coordinator = Mock()
    mock_coordinator.collaborate = Mock(return_value=run)
    mock_coordinator.list_runs = Mock(return_value=[run])

    tab = CollaborationTab(coordinator=mock_coordinator)
    assert tab is not None
    assert tab.goal_input is not None
    assert tab.run_btn is not None
    assert tab.runs_table is not None
    assert tab.runs_table.columnCount() == 5
    # refresh() ran during init — table should have 1 row
    assert tab.runs_table.rowCount() == 1


# ── Management Tab ─────────────────────────────────────────────────────────

def test_management_tab_builds(qt_app):
    from gui.management_tab import ManagementTab

    tab = ManagementTab()
    assert tab is not None
    assert tab.big_brain_name is not None
    assert tab.small_brain_name is not None
    assert tab.request_run_cycle is not None
    assert tab.request_force_improve is not None
    assert tab.request_force_rescan is not None


# ── Analytics Tab ──────────────────────────────────────────────────────────

def test_analytics_tab_builds(qt_app):
    from gui.analytics_tab import AnalyticsTab

    tab = AnalyticsTab()
    assert tab is not None
    assert tab.crypto_combo is not None
    assert tab.crypto_price is not None
    assert tab.crypto_change is not None
    assert tab.strategy_table is not None
    assert tab.run_backtest_btn is not None
    assert tab.refresh_crypto_btn is not None


# ── Dual Brain Control (lightweight check) ────────────────────────────────

def test_dual_brain_control_import(qt_app):
    """DualBrainControl is large and has heavy dependencies; verify it imports cleanly."""
    from gui.dual_brain_control import DualBrainControl
    assert DualBrainControl is not None


# ── Tab Builders mixin (cross-check) ──────────────────────────────────────

def test_tab_builders_mixin_has_create_methods(qt_app):
    from gui.tab_builders import TabBuildersMixin

    mixin = TabBuildersMixin()
    # Verify the key create methods exist
    assert hasattr(mixin, "create_chat_tab")
    assert hasattr(mixin, "create_dialogue_tab")
    assert hasattr(mixin, "create_providers_gpu_tab")
    assert hasattr(mixin, "create_collaboration_tab")
    assert hasattr(mixin, "create_management_tab")
    assert hasattr(mixin, "create_approval_tab")
    assert hasattr(mixin, "create_earnings_tab")
    assert hasattr(mixin, "create_insights_tab")
    assert hasattr(mixin, "create_analytics_tab")
