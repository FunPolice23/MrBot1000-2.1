"""gui/earning_insights.py — Earning Insights dashboard panel (Phase 6).

Provides a compact summary view of:
- Total earned (verified) / pending / last 30 days
- LLM spend vs budget + current survival tier
- Active tasks / pending approvals count
- Recent outcomes (last N)
- Heartbeat status
- Structured event log feed (recent safety / approval / earning events)
- Success metrics row: safety incidents, approval success rate,
  reputation, ROI, uptime
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QGridLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QComboBox,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSizePolicy, QFrame,
)
from PySide6.QtGui import QFont, QColor

logger = logging.getLogger("mrbot.gui.earning_insights")


class EarningInsightsPanel(QWidget):
    """Dashboard panel for the Earning tab / main window."""

    log_signal = Signal(str)
    approval_signal = Signal(str, str, str)  # kind, title, id

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.parent_window = parent
        self._pending_approvals: List[Dict[str, Any]] = []
        self._recent_outcomes: List[Dict[str, Any]] = []
        self._tier: str = "unknown"
        self._llm_spend: float = 0.0
        self._llm_budget: float = 0.0
        self._total_earned: float = 0.0
        self._pending_amount: float = 0.0
        self._last30: float = 0.0
        self._active_tasks: int = 0
        self._heartbeat_running: bool = False
        self._safety_incidents: int = 0
        self._approval_success_rate: float = 1.0
        self._total_outcomes: int = 0
        self._successful_outcomes: int = 0
        self._reputation_score: float = 0.0
        self._uptime_hours: float = 0.0
        self._safety_label: Optional[QLabel] = None
        self._success_rate_label: Optional[QLabel] = None
        self._reputation_label: Optional[QLabel] = None
        self._roi_label: Optional[QLabel] = None
        self._uptime_label: Optional[QLabel] = None
        self._spend_note_label: Optional[QLabel] = None
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(4000)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Top KPIs
        kpis = QHBoxLayout()
        kpis.setContentsMargins(0, 0, 0, 0)

        self.earned_label = self._kpi_cell("💰 Earned", "$0.00", "#4caf50")
        kpis.addWidget(self.earned_label, stretch=1)

        self.pending_label = self._kpi_cell("⏳ Pending", "$0.00", "#ff9800")
        kpis.addWidget(self.pending_label, stretch=1)

        self.last30_label = self._kpi_cell("📅 Last 30d", "$0.00", "#2196f3")
        kpis.addWidget(self.last30_label, stretch=1)

        self.spend_label = self._kpi_cell("🤖 LLM Spend", "$0.00", "#9c27b0")
        kpis.addWidget(self.spend_label, stretch=1)

        self.tier_label = self._kpi_cell("⚡ Tier", "—", "#607d8b")
        kpis.addWidget(self.tier_label, stretch=1)

        root.addLayout(kpis)

        # Middle row: tasks + approvals + heartbeat
        mid = QHBoxLayout()
        tasks_box = QGroupBox("Task Activity")
        tasks_lay = QFormLayout(tasks_box)
        self.tasks_label = QLabel("0 active")
        tasks_lay.addRow("Active tasks:", self.tasks_label)
        self.approvals_label = QLabel("0 pending approval")
        tasks_lay.addRow("Pending approval:", self.approvals_label)
        self.heartbeat_label = QLabel("Heartbeat: stopped")
        tasks_lay.addRow("Heartbeat:", self.heartbeat_label)
        mid.addWidget(tasks_box, stretch=1)

        # Recent outcomes table
        outcomes_box = QGroupBox("Recent Outcomes")
        outcomes_lay = QVBoxLayout(outcomes_box)
        self.outcomes_table = QTableWidget()
        self.outcomes_table.setColumnCount(5)
        self.outcomes_table.setHorizontalHeaderLabels(
            ["Time", "Action", "Platform", "Revenue", "Status"]
        )
        self.outcomes_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self.outcomes_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.outcomes_table.setAlternatingRowColors(True)
        self.outcomes_table.setMaximumHeight(160)
        outcomes_lay.addWidget(self.outcomes_table, stretch=1)
        mid.addWidget(outcomes_box, stretch=1)

        root.addLayout(mid)

        # Success metrics row
        self._build_metrics_grid(root)

        # Event feed
        feed_box = QGroupBox("Event Feed (last 50)")
        feed_lay = QVBoxLayout(feed_box)
        self.event_list = QListWidget()
        self.event_list.setMaximumHeight(180)
        self.event_list.setAlternatingRowColors(True)
        feed_lay.addWidget(self.event_list, stretch=1)

        feed_ctrl = QHBoxLayout()
        self.event_filter = QComboBox()
        self.event_filter.addItems([
            "All", "earning", "approval", "safety",
            "llm_spend", "heartbeat", "system", "evidence",
        ])
        self.event_filter.currentTextChanged.connect(self._refresh_events)
        feed_ctrl.addWidget(self.event_filter, stretch=1)
        feed_lay.addLayout(feed_ctrl)

        root.addWidget(feed_box, stretch=1)

        root.addStretch(1)
        self.setLayout(root)

    def _kpi_cell(self, label: str, value: str, color: str) -> QLabel:
        lbl = QLabel(f"{label}: {value}")
        lbl.setStyleSheet(
            "QLabel { font-size: 11pt; color: #e0e0e0; padding: 4px; }"
            "QLabel { font-weight: bold; color: %s; }" % color
        )
        return lbl

    def _build_metrics_grid(self, root: QVBoxLayout):
        box = QGroupBox("Success Metrics")
        lay = QFormLayout()
        box.setLayout(lay)
        self._safety_label = QLabel("Safety incidents: 0")
        lay.addRow("Safety incidents:", self._safety_label)
        self._success_rate_label = QLabel("Approval success rate: 100%")
        lay.addRow("Approval success rate:", self._success_rate_label)
        self._reputation_label = QLabel("Reputation: —")
        lay.addRow("Reputation:", self._reputation_label)
        self._roi_label = QLabel("ROI: —")
        lay.addRow("ROI:", self._roi_label)
        self._uptime_label = QLabel("Uptime: —")
        lay.addRow("Uptime:", self._uptime_label)
        self._spend_note_label = QLabel("Cloud API cost only — local model usage excluded.")
        self._spend_note_label.setStyleSheet("color: #88aaff; font-size: 9pt;")
        lay.addRow("Spend basis:", self._spend_note_label)
        root.addWidget(box)

    # ── Setters ───────────────────────────────────────────────────────────────

    def set_earnings(self, earned: float, pending: float, last30: float):
        self._total_earned = earned
        self._pending_amount = pending
        self._last30 = last30
        self.earned_label.setText(f"💰 Earned: ${earned:,.2f}")
        self.pending_label.setText(f"⏳ Pending: ${pending:,.2f}")
        self.last30_label.setText(f"📅 Last 30d: ${last30:,.2f}")

    def set_spend(self, spent: float, budget: float):
        self._llm_spend = spent
        self._llm_budget = budget
        color = "#ff5555" if spent > budget and budget > 0 else "#9c27b0"
        self.spend_label.setText(f"🤖 LLM Spend: ${spent:,.2f}")
        self.spend_label.setStyleSheet(
            "QLabel { font-size: 11pt; }"
            "QLabel { font-weight: bold; color: %s; }" % color
        )
        if self._spend_note_label:
            self._spend_note_label.setText(
                "Cloud API cost only — local model usage excluded."
                if budget > 0 else ""
            )

    def set_tier(self, tier: str):
        self._tier = tier
        color = {"FULL": "#4caf50", "REDUCED": "#ff9800",
                 "LOW": "#ff5555", "CRITICAL": "#d50000"}.get(tier, "#607d8b")
        self.tier_label.setText(f"⚡ Tier: {tier}")
        self.tier_label.setStyleSheet(
            "QLabel { font-size: 11pt; }"
            "QLabel { font-weight: bold; color: %s; }" % color
        )

    def set_tasks(self, active: int, pending_approvals: int):
        self._active_tasks = active
        self._pending_approvals = pending_approvals
        self.tasks_label.setText(f"{active} active")
        self.approvals_label.setText(f"{pending_approvals} pending approval")

    def set_heartbeat(self, running: bool):
        self._heartbeat_running = running
        self.heartbeat_label.setText(
            f"Heartbeat: {'running' if running else 'stopped'}"
        )
        color = "#4caf50" if running else "#ff5555"
        self.heartbeat_label.setStyleSheet(
            "QLabel { font-size: 11pt; }"
            "QLabel { color: %s; }" % color
        )

    def set_outcomes(self, outcomes: List[Dict[str, Any]]):
        self._recent_outcomes = outcomes
        self.outcomes_table.setRowCount(0)
        for o in outcomes[-20:]:
            row = self.outcomes_table.rowCount()
            self.outcomes_table.insertRow(row)
            self.outcomes_table.setItem(
                row, 0, QTableWidgetItem(o.get("time", ""))
            )
            self.outcomes_table.setItem(
                row, 1, QTableWidgetItem(o.get("action", ""))
            )
            self.outcomes_table.setItem(
                row, 2, QTableWidgetItem(o.get("platform", ""))
            )
            self.outcomes_table.setItem(
                row, 3, QTableWidgetItem(f"${o.get('revenue', 0):,.2f}")
            )
            status = o.get("status", "")
            item = QTableWidgetItem(status)
            color = {"paid": "#4caf50", "completed": "#2196f3",
                     "rejected": "#ff5555", "pending": "#ff9800"}.get(status, "#607d8b")
            item.setForeground(QColor(color))
            self.outcomes_table.setItem(row, 4, item)

        # Update approval success rate from outcomes
        total = len(outcomes)
        successful = sum(1 for o in outcomes
                         if o.get("status") in ("paid", "completed", "approved"))
        self.set_approval_rate(total, successful)

    def set_events(self, events: List[Dict[str, Any]]):
        self.event_list.clear()
        for ev in events[-50:]:
            if hasattr(ev, "to_dict"):
                ev = ev.to_dict()
            ts = ev.get("ts", 0)
            text = ev.get("message", "")
            lvl = ev.get("level", "")
            src = ev.get("source", "")
            color = {
                "debug": "#607d8b", "info": "#2196f3",
                "warning": "#ff9800", "error": "#ff5555",
                "critical": "#d50000", "approval_required": "#9c27b0",
                "approval_granted": "#4caf50", "approval_denied": "#ff5555",
            }.get(lvl, "#e0e0e0")
            item = QListWidgetItem(
                f"[{src}] {text} "
                f"({__import__('datetime').datetime.fromtimestamp(ts).strftime('%H:%M:%S')})"
            )
            item.setForeground(QColor(color))
            self.event_list.addItem(item)

    # ── Metrics setters ───────────────────────────────────────────────────────

    def set_safety_incidents(self, count: int):
        self._safety_incidents = count
        color = "#ff5555" if count > 0 else "#4caf50"
        if self._safety_label:
            try:
                self._safety_label.setText(f"Safety incidents: {count}")
                self._safety_label.setStyleSheet("color: %s; font-weight: bold;" % color)
            except RuntimeError:
                self._safety_label = None

    def set_approval_rate(self, total: int, successful: int):
        self._total_outcomes = total
        self._successful_outcomes = successful
        rate = (successful / total * 100) if total > 0 else 100.0
        self._approval_success_rate = rate
        if self._success_rate_label:
            try:
                self._success_rate_label.setText(f"Approval success rate: {rate:.0f}%")
                self._success_rate_label.setStyleSheet(
                    "color: %s; font-weight: bold;"
                    % ("#4caf50" if rate >= 80 else "#ff9800" if rate >= 50 else "#ff5555")
                )
            except RuntimeError:
                self._success_rate_label = None

    def set_reputation(self, score: float):
        self._reputation_score = score
        if self._reputation_label:
            try:
                self._reputation_label.setText(f"Reputation: {score:.1f}/100")
                self._reputation_label.setStyleSheet(
                    "color: %s; font-weight: bold;"
                    % ("#4caf50" if score >= 80 else "#ff9800" if score >= 50 else "#ff5555")
                )
            except RuntimeError:
                self._reputation_label = None

    def set_roi(self, roi: float):
        if self._roi_label:
            try:
                self._roi_label.setText(f"ROI: {roi:.0f}%")
                self._roi_label.setStyleSheet(
                    "color: %s; font-weight: bold;"
                    % ("#4caf50" if roi >= 300 else "#ff9800" if roi >= 0 else "#ff5555")
                )
            except RuntimeError:
                self._roi_label = None

    def set_uptime(self, hours: float):
        self._uptime_hours = hours
        if self._uptime_label:
            try:
                self._uptime_label.setText(f"Uptime: {hours:.1f}h")
                self._uptime_label.setStyleSheet("color: #2196f3; font-weight: bold;")
            except RuntimeError:
                self._uptime_label = None

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh(self):
        pass  # called on timer; subclasses / main window wire real data

    def _refresh_events(self):
        pass


class TabAwareInsightsPanel(EarningInsightsPanel):
    """Insights panel that pulls live data from the EarningTab / MainWindow."""

    def __init__(self, parent: Optional[QWidget] = None,
                 earning_tab: Optional[Any] = None,
                 approval_queue: Optional[Any] = None,
                 event_logger: Optional[Any] = None):
        super().__init__(parent)
        self.earning_tab = earning_tab
        self.approval_queue = approval_queue
        self.event_logger = event_logger

    def _refresh(self):
        try:
            # Earnings
            if self.earning_tab and hasattr(self.earning_tab, "get_summary"):
                s = self.earning_tab.get_summary()
                self.set_earnings(
                    s.get("earned", 0.0),
                    s.get("pending", 0.0),
                    s.get("last30", 0.0),
                )
            elif self.earning_tab and hasattr(self.earning_tab, "refresh_pipeline"):
                self.earning_tab.refresh_pipeline()
        except Exception:
            pass

        try:
            if self.approval_queue:
                pending = self.approval_queue.pending()
                self.set_tasks(
                    active=0,  # could derive from task workspace
                    pending_approvals=len(pending),
                )
        except Exception:
            pass

        try:
            if self.event_logger:
                self.set_events(self.event_logger.recent(limit=50))
                earning_events = self.event_logger.recent(
                    event_type="earning", limit=50)
                outcomes = []
                for event in earning_events:
                    item = event.to_dict() if hasattr(event, "to_dict") else event
                    details = item.get("details", {}) or {}
                    outcomes.append({
                        "time": item.get("ts", ""),
                        "action": item.get("message", ""),
                        "platform": details.get("platform", item.get("source", "")),
                        "revenue": details.get("amount", details.get("revenue", 0)),
                        "status": details.get("status", "completed"),
                    })
                self.set_outcomes(outcomes)
        except Exception:
            pass

        # Safety incidents from event logger
        try:
            if self.event_logger:
                safety_events = self.event_logger.query(
                    event_type="safety", level="warning", limit=500
                )
                blocked = sum(1 for e in safety_events
                             if e.details.get("blocked"))
                self.set_safety_incidents(blocked)
                # Approval success rate from outcomes already handled in set_outcomes
                # Reputation from event logger if available
                rep_ev = self.event_logger.last_event_of_type("reputation")
                if rep_ev:
                    self.set_reputation(float(rep_ev.details.get("score", 0.0)))
        except Exception:
            pass

        # ROI: (earned - spent) / spent if spent > 0
        try:
            if self._llm_spend > 0:
                roi = (self._total_earned - self._llm_spend) / self._llm_spend * 100
                self.set_roi(roi)
            else:
                if self._roi_label:
                    self._roi_label.setText("ROI: N/A (no tracked LLM spend)")
                    self._roi_label.setStyleSheet("color: #9e9e9e; font-weight: bold;")
        except Exception:
            pass

        self._refresh_events()

    def _refresh_events(self):
        try:
            if self.event_logger:
                ft = self.event_filter.currentText()
                if ft == "All":
                    self.set_events(self.event_logger.recent(limit=50))
                else:
                    self.set_events(
                        self.event_logger.recent(
                            event_type=ft.lower(), limit=50
                        )
                    )
        except Exception:
            pass

    def refresh_now(self):
        self._refresh()


__all__ = ["EarningInsightsPanel", "TabAwareInsightsPanel"]
