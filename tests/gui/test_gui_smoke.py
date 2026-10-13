"""
tests/test_gui_smoke.py — GUI smoke tests for tabs not covered by test_earning_gui.py.

Verifies that each major GUI tab/widget builds without crashing when constructed
with minimal/mocked dependencies. These are lightweight smoke tests, not functional
tests — they confirm the UI surface is constructible, not that it works end-to-end.

Follows the pattern established in test_earning_gui.py.
"""

from __future__ import annotations

from unittest.mock import Mock
from types import SimpleNamespace

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
    from gui.panels.approval_panel import ApprovalPanel
    from agents.safety.approval import HumanApprovalQueue

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
    from gui.panels.approval_panel import ApprovalPanel
    from agents.safety.approval import HumanApprovalQueue

    panel = ApprovalPanel(approval_queue=HumanApprovalQueue.instance())
    # After construction the refresh timer fires once; status should be clear.
    assert "pending" not in panel.status_label.text().lower() or \
           panel.status_label.text() == "No pending approvals"


# ── Dialogue Tab ─────────────────────────────────────────────────────────────

def test_dialogue_tab_builds(qt_app):
    from gui.tabs.dialogue_tab import DialogueTab

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
    # Earning agents select a safe default goal until the operator replaces it.
    assert tab.goal == "Earn any amount of money or crypto"


def test_dialogue_tab_set_goal(qt_app):
    from gui.tabs.dialogue_tab import DialogueTab

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
    from gui.tabs.chat_tab import ChatTab

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
    from gui.widgets.provider_config_widget import ProviderConfigWidget

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
    from gui.widgets.provider_config_widget import ProviderConfigWidget

    widget = ProviderConfigWidget()
    # Should have two tabs: Cloud and Local
    assert widget.type_tabs.count() == 2
    assert "Cloud" in widget.type_tabs.tabText(0)
    assert "Local" in widget.type_tabs.tabText(1)


# ── Collaboration Tab ──────────────────────────────────────────────────────

def test_collaboration_tab_builds(qt_app):
    from gui.tabs.collaboration_tab import CollaborationTab
    from agents.core.comms import MessageStatus
    from agents.cognition.coordinator import RunRecord, StageRun, CollaborationStage
    from agents.runtime.dual_brain import BrainRole

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
    from gui.tabs.management_tab import ManagementTab

    tab = ManagementTab()
    assert tab is not None
    # N-brain: one name field per enabled device (>= the two primary personas).
    edits = getattr(tab, "_persona_name_edits", [])
    assert len(edits) >= 2
    # Slots 0/1 persist to the legacy persona-name keys — but only when that
    # slot actually holds the matching TIER. Tier comes from live capability,
    # not from the slot number: on a box whose CPU/RAM pool is big-class
    # (>= 12 GB system RAM) slot 1 hosts a BIG-tier brain, so it persists to
    # BRAIN_SLOT1_NAME and the SMALL_BRAIN_NAME persona simply does not exist.
    # Asserting SMALL_BRAIN_NAME unconditionally made this test pass or fail
    # purely on the machine's RAM (ARCH-ENG-059).
    from agents.runtime import device_registry as dr
    from agents.cognition.speaker_registry import build_speakers
    speakers = build_speakers(dr.brain_placements(dr.resolve_assignments(
        dr.detect_devices(include_cpu=True), dr.load_policy())))
    by_slot = {s.slot: s for s in speakers}
    keys = {slot: key for slot, key, _ in edits}
    if by_slot.get(1) is not None and by_slot[1].tier == "small":
        assert keys.get(0) == "BIG_BRAIN_NAME"
        assert keys.get(1) == "SMALL_BRAIN_NAME"
    else:
        assert keys.get(0) == "BIG_BRAIN_NAME"
        assert keys.get(1) == "BRAIN_SLOT1_NAME"
    assert tab.request_run_cycle is not None
    assert tab.request_force_improve is not None
    assert tab.request_force_rescan is not None


# ── Analytics Tab ──────────────────────────────────────────────────────────

def test_analytics_tab_builds(qt_app):
    from gui.tabs.analytics_tab import AnalyticsTab

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
    from gui.widgets.dual_brain_control import DualBrainControl
    assert DualBrainControl is not None


def test_diagnostics_tab_is_read_only_and_refreshes_health(qt_app):
    from gui.builders.tab_builders import TabBuildersMixin

    runtime = Mock()
    runtime.snapshot.return_value = {
        "big": {
            "display_name": "Edward Hurst",
            "provider": "llamacpp",
            "model": "edward-model",
            "reachable": True,
            "model_status": "available",
            "model_count": 1,
            "latency_ms": 4,
        },
        "small": {
            "display_name": "Jacob Stanley",
            "provider": "ollama",
            "model": "jacob-model",
            "reachable": False,
            "model_status": "server_unavailable",
            "model_count": 0,
            "latency_ms": 12,
        },
    }

    class Harness(TabBuildersMixin):
        pass

    harness = Harness()
    harness.dual_brain_runtime = runtime
    harness.log_signal = Mock()
    harness._composition_root = SimpleNamespace(
        lifecycle=SimpleNamespace(get_all_states=lambda: []),
        portfolio=SimpleNamespace(list_all=lambda: [], get=lambda _: None),
        pipeline=SimpleNamespace(
            evidence_store=SimpleNamespace(for_subject=lambda *_: []),
            accounting=SimpleNamespace(get_profile=lambda _: {"verified_revenue": 0.0}),
        ),
        run_store=SimpleNamespace(list_runs=lambda **_: []),
        reconciliation_report=None,
    )

    widget = harness.create_diagnostics_tab()
    harness.refresh_diagnostics()
    runtime.snapshot.assert_called_with(refresh_health=True)
    assert harness.diagnostics_health_table.rowCount() == 2
    assert harness.diagnostics_health_table.item(1, 4).text() == "server_unavailable"
    assert harness.diagnostics_conflict_table.rowCount() == 0
    assert "read-only" in harness.diagnostics_reconciliation_label.text()
    widget.deleteLater()


# ── Tab Builders mixin (cross-check) ──────────────────────────────────────

def test_tab_builders_mixin_has_create_methods(qt_app):
    from gui.builders.tab_builders import TabBuildersMixin

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
