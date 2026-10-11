"""Task 10b — background self-improvement post-apply monitor timer.

Verifies the main-window monitor wiring: gated by the self-improvement feature
flag, interval read from MRBOT_SELF_IMPROVE_MONITOR_MINUTES, and the monitor
runs monitor_applied() and logs when regressions are found.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _harness():
    """A minimal QObject exposing the two monitor methods + needed attrs."""
    import main as main_mod  # noqa: F401  (import triggers load_dotenv)
    from PySide6.QtCore import QObject

    class _H(QObject):
        pass

    h = _H()
    h.log_signal = Mock()
    h._self_improve_monitor_timer = None
    h._earning_services = None
    h._start_self_improve_monitor = main_mod.MainWindow._start_self_improve_monitor.__get__(h)
    h._run_self_improve_monitor = main_mod.MainWindow._run_self_improve_monitor.__get__(h)
    return h


def test_monitor_not_started_when_feature_disabled(qt_app, monkeypatch):
    h = _harness()  # import main first (loads .env)
    monkeypatch.setenv("MRBOT_ENABLE_SELF_IMPROVEMENT", "false")
    h._start_self_improve_monitor()
    assert h._self_improve_monitor_timer is None
    # No log about starting.
    assert not any("post-apply monitor" in str(c) for c in h.log_signal.emit.call_args_list)


def test_monitor_started_when_feature_enabled(qt_app, monkeypatch):
    h = _harness()
    monkeypatch.setenv("MRBOT_ENABLE_SELF_IMPROVEMENT", "true")
    monkeypatch.setenv("MRBOT_SELF_IMPROVE_MONITOR_MINUTES", "7")
    h._start_self_improve_monitor()
    assert h._self_improve_monitor_timer is not None
    assert h._self_improve_monitor_timer.interval() == 7 * 60 * 1000
    assert any("every 7 min" in str(c) for c in h.log_signal.emit.call_args_list)


def test_monitor_interval_clamped(qt_app, monkeypatch):
    h = _harness()
    monkeypatch.setenv("MRBOT_ENABLE_SELF_IMPROVEMENT", "true")
    monkeypatch.setenv("MRBOT_SELF_IMPROVE_MONITOR_MINUTES", "99999")
    h._start_self_improve_monitor()
    assert h._self_improve_monitor_timer.interval() == 1440 * 60 * 1000


def test_monitor_run_calls_service_and_logs_regressions(qt_app, monkeypatch):
    h = _harness()
    monkeypatch.setenv("MRBOT_ENABLE_SELF_IMPROVEMENT", "true")
    svc = Mock()
    svc.monitor_applied.return_value = [object()]  # one regression -> one proposal
    h._earning_services = SimpleNamespace(code_patch_service=svc)
    h._run_self_improve_monitor()
    svc.monitor_applied.assert_called_once()
    assert any("flagged 1 regression" in str(c) for c in h.log_signal.emit.call_args_list)


def test_monitor_run_noop_without_service(qt_app, monkeypatch):
    h = _harness()
    monkeypatch.setenv("MRBOT_ENABLE_SELF_IMPROVEMENT", "true")
    h._earning_services = None
    h._run_self_improve_monitor()  # must not raise
    assert h.log_signal.emit.call_count == 0
