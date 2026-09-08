"""gui/goal_tracker.py — Goal Tracker panel for the Earning tab."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QLineEdit, QDoubleSpinBox, QMessageBox, QSplitter, QFrame,
    QScrollArea, QSizePolicy,
)
from PySide6.QtGui import QFont, QColor

from agents.goal_system import GoalTracker, Goal, EvidenceRow, GoalStatus, GoalPath

logger = logging.getLogger("mrbot.gui.goal_tracker")


class GoalTrackerPanel(QWidget):
    """Goal tracking panel for the Earning tab."""

    goal_selected = Signal(str)  # goal_id
    add_evidence_requested = Signal(str)  # goal_id

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.goal_tracker = GoalTracker.instance()
        self._active_goals: List[Goal] = []
        self._selected_goal: Optional[Goal] = None
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(4000)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Header
        header = QLabel("🎯 Goal Tracker")
        header.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header.setStyleSheet("color: #bb86fc; padding: 6px;")
        root.addWidget(header)

        # Summary row
        summary = QHBoxLayout()
        self.total_label = self._summary_cell("Total Goals", "0", "#2196f3")
        summary.addWidget(self.total_label, stretch=1)
        self.active_label = self._summary_cell("Active", "0", "#4caf50")
        summary.addWidget(self.active_label, stretch=1)
        self.earned_label = self._summary_cell("Earned", "$0.00", "#ff9800")
        summary.addWidget(self.earned_label, stretch=1)
        self.progress_label = self._summary_cell("Progress", "0%", "#9c27b0")
        summary.addWidget(self.progress_label, stretch=1)
        root.addLayout(summary)

        splitter = QSplitter(Qt.Vertical)

        # Goal list
        list_box = QGroupBox("Active Goals")
        list_lay = QVBoxLayout(list_box)
        self.goal_list = QListWidget()
        self.goal_list.setAlternatingRowColors(True)
        self.goal_list.itemSelectionChanged.connect(self._on_goal_selected)
        list_lay.addWidget(self.goal_list, stretch=1)

        # Add goal button
        add_btn = QPushButton("➕ Add Goal")
        add_btn.clicked.connect(self._on_add_goal)
        list_lay.addWidget(add_btn)

        splitter.addWidget(list_box)

        # Goal details
        detail_box = QGroupBox("Goal Details")
        detail_lay = QVBoxLayout(detail_box)

        self.detail_title = QLabel("—")
        self.detail_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        detail_lay.addWidget(self.detail_title)

        self.detail_path = QLabel("Path: —")
        detail_lay.addWidget(self.detail_path)

        self.detail_progress = QLabel("Progress: —")
        detail_lay.addWidget(self.detail_progress)

        self.detail_earnings = QLabel("Earned: $0.00 / $0.00")
        detail_lay.addWidget(self.detail_earnings)

        self.detail_status = QLabel("Status: —")
        detail_lay.addWidget(self.detail_status)

        self.detail_deadline = QLabel("Deadline: —")
        detail_lay.addWidget(self.detail_deadline)

        detail_lay.addStretch(1)

        # Action buttons
        btn_lay = QHBoxLayout()
        self.add_evidence_btn = QPushButton("📎 Add Evidence")
        self.add_evidence_btn.clicked.connect(self._on_add_evidence)
        btn_lay.addWidget(self.add_evidence_btn)

        self.complete_btn = QPushButton("✅ Mark Complete")
        self.complete_btn.clicked.connect(self._on_mark_complete)
        btn_lay.addWidget(self.complete_btn)

        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.clicked.connect(self._on_pause)
        btn_lay.addWidget(self.pause_btn)
        btn_lay.addStretch(1)

        detail_lay.addLayout(btn_lay)
        splitter.addWidget(detail_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, stretch=1)
        self.setLayout(root)

    def _summary_cell(self, label: str, value: str, color: str) -> QLabel:
        lbl = QLabel(f"{label}: {value}")
        lbl.setStyleSheet(
            "QLabel { font-size: 11pt; }"
            "QLabel { font-weight: bold; color: %s; }" % color
        )
        return lbl

    def _refresh(self):
        try:
            summary = self.goal_tracker.summary()
            self.total_label.setText(f"Total Goals: {summary.get('total_goals', 0)}")
            self.active_label.setText(f"Active: {summary.get('active_goals', 0)}")
            self.earned_label.setText(f"Earned: ${summary.get('total_earned', 0):,.2f}")
            self.progress_label.setText(f"Progress: {summary.get('overall_progress', 0):.0f}%")
        except Exception:
            pass

    def _on_goal_selected(self):
        sel = self.goal_list.selectedItems()
        if not sel:
            self._clear_detail()
            return
        goal_id = sel[0].data(Qt.UserRole)
        # TODO: load goal from tracker
        self._clear_detail()

    def _clear_detail(self):
        self._selected_goal = None
        self.detail_title.setText("—")
        self.detail_path.setText("Path: —")
        self.detail_progress.setText("Progress: —")
        self.detail_earnings.setText("Earned: $0.00 / $0.00")
        self.detail_status.setText("Status: —")
        self.detail_deadline.setText("Deadline: —")
        self.add_evidence_btn.setEnabled(False)
        self.complete_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)

    def _on_add_goal(self):
        # TODO: open add-goal dialog
        pass

    def _on_add_evidence(self):
        if self._selected_goal:
            self.add_evidence_requested.emit(self._selected_goal.id)

    def _on_mark_complete(self):
        if self._selected_goal:
            # TODO: mark complete
            pass

    def _on_pause(self):
        if self._selected_goal:
            # TODO: toggle pause
            pass

    def refresh_now(self):
        self._refresh()


__all__ = ["GoalTrackerPanel"]
