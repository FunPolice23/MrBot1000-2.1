"""
gui/collaboration_tab.py — Collaboration / Run Monitor (v2.1).

Renders the DualBrainCoordinator's run ledger: each collaboration run with its
stages, owning role, model, latency, status, and error. A manual "Run
Collaboration" executes a goal through the coordinator on a background QThread
so the GUI never blocks on inference.

This tab is a *monitor/control surface* for the coordinator; it does NOT
implement its own collaboration logic. The coordinator owns the protocol.
"""

import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)


def _fmt_ms(ms: int) -> str:
    return f"{ms} ms" if ms >= 0 else "—"


class CollaborationWorker(QThread):
    """Run a collaboration goal off the GUI thread via the coordinator."""
    finished = Signal(dict)  # RunRecord.to_dict()

    def __init__(self, coordinator, goal):
        super().__init__()
        self.coordinator = coordinator
        self.goal = goal

    def run(self):
        try:
            run = self.coordinator.collaborate(self.goal)
            self.finished.emit(run.to_dict())
        except Exception as exc:
            self.finished.emit({"error": str(exc)})


class CollaborationTab(QWidget):
    """Monitor + manual trigger for the dual-brain collaboration coordinator."""

    # Emitted when a goal is submitted here so the Dialogue tab can mirror it.
    goal_changed = Signal(str)

    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        self.setup_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start(1500)

    def setup_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel("🤝 Collaboration / Run Monitor")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #4fc3f7; padding: 8px;")
        layout.addWidget(header)

        # Control bar: goal input + run button.
        control = QHBoxLayout()
        control.addWidget(QLabel("Goal:"))
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("e.g. Earn $500 this week")
        self.goal_input.returnPressed.connect(self._run_collaboration)
        control.addWidget(self.goal_input, stretch=1)
        self.run_btn = QPushButton("▶ Run Collaboration")
        self.run_btn.clicked.connect(self._run_collaboration)
        control.addWidget(self.run_btn)
        layout.addLayout(control)

        splitter = QSplitter(Qt.Vertical)

        # Runs table.
        runs_group = QGroupBox("Runs")
        runs_layout = QVBoxLayout(runs_group)
        self.runs_table = QTableWidget(0, 5)
        self.runs_table.setHorizontalHeaderLabels(
            ["Run", "Status", "Goal", "Stages", "Result"])
        self.runs_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.runs_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.runs_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.runs_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
        self.runs_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.runs_table.setSelectionBehavior(QTableWidget.SelectRows)
        runs_layout.addWidget(self.runs_table)
        splitter.addWidget(runs_group)

        # Detail pane.
        detail_group = QGroupBox("Stage Detail")
        detail_layout = QVBoxLayout(detail_group)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(240)
        detail_layout.addWidget(self.detail)
        splitter.addWidget(detail_group)

        splitter.setSizes([320, 240])
        layout.addWidget(splitter)

        self.runs_table.itemSelectionChanged.connect(self._show_selected_detail)
        self.refresh()

    # ── actions ─────────────────────────────────────────────────────────────
    def _run_collaboration(self):
        goal = self.goal_input.text().strip()
        if not goal:
            return
        self.goal_changed.emit(goal)  # mirror to Dialogue
        self.run_btn.setEnabled(False)
        self.run_btn.setText("…")
        self.worker = CollaborationWorker(self.coordinator, goal)
        self.worker.finished.connect(self._on_run_done)
        self.worker.start()

    def _on_run_done(self, _payload):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶ Run Collaboration")
        self.refresh()

    def refresh(self):
        runs = self.coordinator.list_runs()
        self.runs_table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            self.runs_table.setItem(row, 0, QTableWidgetItem(run.run_id[:8]))
            status_item = QTableWidgetItem(run.status.value)
            status_item.setForeground(QColor(
                "#4caf50" if run.ok else "#ff5252" if run.status.value == "FAILED"
                else "#ffb300"))
            self.runs_table.setItem(row, 1, status_item)
            self.runs_table.setItem(row, 2, QTableWidgetItem(run.goal))
            self.runs_table.setItem(
                row, 3, QTableWidgetItem(
                    ",".join(s.stage.value for s in run.stages)))
            self.runs_table.setItem(
                row, 4, QTableWidgetItem(run.final_result[:80] if run.final_result else ""))

    def _show_selected_detail(self):
        sel = self.runs_table.selectionModel().selectedRows()
        if not sel:
            return
        row = sel[0].row()
        runs = self.coordinator.list_runs()
        if row >= len(runs):
            return
        run = runs[row]
        lines = [f"Run: {run.run_id}", f"Goal: {run.goal}",
                 f"Status: {run.status.value}",
                 f"Error: {run.error or '—'}", ""]
        for s in run.stages:
            lines.append(
                f"[{s.stage.value}] {s.role.value} · {s.model} · "
                f"{_fmt_ms(s.latency_ms)} · "
                f"{'✓' if s.success else '✗'}")
            lines.append(f"  {s.result[:200] if s.result else '—'}")
        self.detail.setPlainText("\n".join(lines))


__all__ = ["CollaborationTab", "CollaborationWorker"]
