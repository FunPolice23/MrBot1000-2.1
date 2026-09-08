"""gui/logging_tab.py — Phase 6: Comprehensive Logging tab.

Structured audit trail across all earning paths.
Reads from AgentDB (sqlite) and displays in a searchable,
filterable table with export to CSV.
"""
from __future__ import annotations

import csv
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLineEdit, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox, QTextEdit, QMessageBox,
    QSplitter, QSpinBox, QDoubleSpinBox, QFileDialog, QDateEdit,
    QDateEdit, QApplication,
)
from PySide6.QtCore import QTimer

logger = logging.getLogger("mrbot.gui.logging_tab")


class LoggingTab(QWidget):
    """Comprehensive logging & audit trail tab.

    Shows all evidence, actions, proposals, payouts, and system
    events in a unified table. Supports filtering by path, date,
    and keyword search. Export to CSV.
    """

    log_signal = Signal(str)

    def __init__(self, parent=None, db_path: Optional[str] = None):
        super().__init__(parent)
        self.main_window = parent
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "earning.db"
        )
        self._filter_path = "all"
        self._filter_date_days = 30
        self._search_query = ""
        self.setup_ui()
        self._auto_refresh_timer = QTimer()
        self._auto_refresh_timer.timeout.connect(self.refresh)
        self._auto_refresh_timer.start(10000)  # refresh every 10s
        self.refresh()

    # ── UI ────────────────────────────────────────────────

    def setup_ui(self):
        root = QVBoxLayout(self)

        header = QLabel("📋 Comprehensive Audit Log")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        root.addWidget(header)

        splitter = QSplitter(Qt.Vertical)

        # Controls row
        controls = QWidget()
        controls_lay = QHBoxLayout(controls)

        # Path filter
        self.path_combo = QComboBox()
        self.path_combo.addItems([
            "all", "freelance", "microtask", "crypto", "autonomy", "payout", "proposal"
        ])
        self.path_combo.currentTextChanged.connect(self._on_filter_changed)
        controls_lay.addWidget(QLabel("Path:"))
        controls_lay.addWidget(self.path_combo)

        # Date range
        controls_lay.addWidget(QLabel("Days:"))
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 365)
        self.days_spin.setValue(30)
        self.days_spin.valueChanged.connect(self._on_filter_changed)
        controls_lay.addWidget(self.days_spin)

        # Search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search keyword…")
        self.search_input.textChanged.connect(self._on_search)
        controls_lay.addWidget(self.search_input)

        # Export
        export_btn = QPushButton("📤 Export CSV")
        export_btn.clicked.connect(self._on_export_csv)
        controls_lay.addWidget(export_btn)

        controls_lay.addStretch(1)
        splitter.addWidget(controls)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ID", "Timestamp", "Path", "Action", "Detail",
            "Revenue", "Status", "Evidence"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        splitter.addWidget(self.table)

        # Log output
        log_group = QGroupBox("Live Log")
        log_lay = QVBoxLayout(log_group)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet("""
            QTextEdit { background:#111; color:#e0e0e0; font-family: Consolas; font-size:11px; }
        """)
        log_lay.addWidget(self.log_edit)
        splitter.addWidget(log_group)

        root.addWidget(splitter, stretch=1)

        self.log_signal.connect(self._append_log)

    # ── Data ───────────────────────────────────────────────

    def _get_rows(self) -> List[dict]:
        """Fetch log rows from AgentDB with current filters."""
        rows: List[dict] = []
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Try evidence table first
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='evidence'")
            if cur.fetchone():
                sql = "SELECT * FROM evidence WHERE 1=1"
                params: list = []
                if self._filter_path != "all":
                    sql += " AND path = ?"
                    params.append(self._filter_path)
                if self._search_query:
                    sql += " AND (detail LIKE ? OR action LIKE ?)"
                    params.extend([f"%{self._search_query}%", f"%{self._search_query}%"])
                sql += " ORDER BY ts DESC LIMIT 200"
                cur.execute(sql, params)
                for r in cur.fetchall():
                    rows.append({
                        "id": r.get("id", ""),
                        "ts": r.get("ts", 0),
                        "path": r.get("path", ""),
                        "action": r.get("action", ""),
                        "detail": r.get("detail", ""),
                        "revenue": r.get("revenue_usd", 0) or 0,
                        "status": r.get("status", ""),
                        "evidence": r.get("evidence_path", ""),
                    })
            else:
                # Fallback: outcomes table
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='outcomes'")
                if cur.fetchone():
                    sql = "SELECT * FROM outcomes WHERE 1=1"
                    params = []
                    if self._filter_path != "all":
                        sql += " AND action LIKE ?"
                        params.append(f"%{self._filter_path}%")
                    if self._search_query:
                        sql += " AND (result LIKE ? OR detail LIKE ?)"
                        params.extend([f"%{self._search_query}%", f"%{self._search_query}%"])
                    sql += " ORDER BY ts DESC LIMIT 200"
                    cur.execute(sql, params)
                    for r in cur.fetchall():
                        rows.append({
                            "id": str(r.get("id", "")),
                            "ts": r.get("ts", 0),
                            "path": self._filter_path,
                            "action": r.get("action", ""),
                            "detail": r.get("result", ""),
                            "revenue": r.get("revenue_usd", 0) or 0,
                            "status": "ok",
                            "evidence": "",
                        })
            conn.close()
        except Exception as e:
            logger.warning("LoggingTab._get_rows error: %s", e)
        return rows

    # ── Display ────────────────────────────────────────────

    def refresh(self):
        rows = self._get_rows()
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            ts = datetime.fromtimestamp(row["ts"] or 0).strftime("%Y-%m-%d %H:%M") if row["ts"] else "—"
            self.table.setItem(i, 0, QTableWidgetItem(str(row.get("id", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(ts))
            self.table.setItem(i, 2, QTableWidgetItem(row.get("path", "")))
            self.table.setItem(i, 3, QTableWidgetItem(row.get("action", "")))
            self.table.setItem(i, 4, QTableWidgetItem(str(row.get("detail", ""))[:80]))
            rev = row.get("revenue", 0)
            self.table.setItem(i, 5, QTableWidgetItem(f"${rev:.2f}" if rev else "—"))
            self.table.setItem(i, 6, QTableWidgetItem(row.get("status", "")))
            self.table.setItem(i, 7, QTableWidgetItem(str(row.get("evidence", ""))[:40]))
        self.table.resizeColumnsToContents()

    # ── Handlers ──────────────────────────────────────────

    def _on_filter_changed(self):
        self._filter_path = self.path_combo.currentText()
        self._filter_date_days = self.days_spin.value()
        self.refresh()

    def _on_search(self, text: str):
        self._search_query = text.strip()
        self.refresh()

    def _on_export_csv(self):
        rows = self._get_rows()
        if not rows:
            QMessageBox.information(self, "Export", "No rows to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Audit Log", "", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["id", "ts", "path", "action", "detail", "revenue", "status", "evidence"])
                writer.writeheader()
                for row in rows:
                    writer.writerow({
                        "id": row.get("id", ""),
                        "ts": datetime.fromtimestamp(row["ts"] or 0).isoformat() if row["ts"] else "",
                        "path": row.get("path", ""),
                        "action": row.get("action", ""),
                        "detail": str(row.get("detail", "")),
                        "revenue": row.get("revenue", 0),
                        "status": row.get("status", ""),
                        "evidence": row.get("evidence", ""),
                    })
            QMessageBox.information(self, "Export", f"Exported {len(rows)} rows to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _append_log(self, msg: str):
        self.log_edit.append(msg)

    # ── Public API ─────────────────────────────────────────

    def append(self, path: str, action: str, detail: str = "", revenue: float = 0.0, status: str = "ok", evidence: str = ""):
        """Append a log entry directly (for external callers)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""INSERT INTO evidence (path, action, detail, revenue_usd, status, evidence_path, ts)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (path, action, detail, revenue, status, evidence, datetime.now().timestamp()))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("LoggingTab.append error: %s", e)
        self.refresh()
