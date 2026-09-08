"""gui/notifications_tab.py — Phase 6: Notification System tab.

Desktop-native notifications for earnings, human-gate approvals,
safety alerts, and system events. Uses Windows Toast via
win10toast or Windows API fallback.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QPushButton, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox, QMessageBox,
    QSplitter, QCheckBox, QSpinBox,
)
from PySide6.QtGui import QFont, QColor, QIcon

logger = logging.getLogger("mrbot.gui.notifications_tab")


class NotificationManager:
    """Manages desktop notifications.

    Supports multiple backends:
    1. Windows Toast (win10toast or Windows API)
    2. QSystemTrayIcon fallback
    3. Log-only fallback
    """

    def __init__(self, enabled: bool = True, sound: bool = True):
        self.enabled = enabled
        self.sound = sound
        self._notifications: List[Dict[str, Any]] = []
        self._load_history()

    def notify(
        self,
        title: str,
        message: str,
        level: str = "info",
        category: str = "system",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a desktop notification."""
        notif = {
            "id": len(self._notifications) + 1,
            "timestamp": datetime.now().timestamp(),
            "title": title,
            "message": message,
            "level": level,  # info, warning, critical, success
            "category": category,  # earning, safety, system, payment
            "data": data or {},
            "read": False,
        }
        self._notifications.append(notif)

        if self.enabled:
            self._send_desktop(notif)

        self._save_history()
        return notif

    def _send_desktop(self, notif: Dict[str, Any]) -> None:
        """Send via Windows Toast or fallback."""
        try:
            # Try win10toast first
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(
                notif["title"],
                notif["message"],
                duration=10,
                threaded=True,
            )
            return
        except ImportError:
            pass

        try:
            # Windows API fallback via ctypes
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, notif["message"], notif["title"], 0x40
            )
            return
        except Exception:
            pass

        # Log-only fallback
        logger.info("[%s] %s: %s", notif["level"].upper(), notif["title"], notif["message"])

    def get_unread(self) -> List[Dict[str, Any]]:
        return [n for n in self._notifications if not n["read"]]

    def mark_read(self, notif_id: int) -> None:
        for n in self._notifications:
            if n["id"] == notif_id:
                n["read"] = True
        self._save_history()

    def _load_history(self) -> None:
        # In production, load from persistent store
        pass

    def _save_history(self) -> None:
        # In production, save to persistent store
        pass


class NotificationsTab(QWidget):
    """Notification center tab for the PySide6 GUI.

    Displays pending notifications, allows acknowledgment,
    and configures notification preferences.
    """

    log_signal = Signal(str)

    def __init__(self, parent=None, db_path: Optional[str] = None):
        super().__init__(parent)
        self.main_window = parent
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "earning.db"
        )
        self.notif_manager = NotificationManager(enabled=True, sound=True)
        self.setup_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start(5000)  # refresh every 5s
        self.refresh()

    # ── UI ────────────────────────────────────────────

    def setup_ui(self):
        root = QVBoxLayout(self)

        header = QLabel("🔔 Notification Center")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        root.addWidget(header)

        splitter = QSplitter(Qt.Vertical)

        # Summary row
        summary = QWidget()
        summary_lay = QHBoxLayout(summary)
        self.unread_label = QLabel("Unread: 0")
        self.unread_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        summary_lay.addWidget(self.unread_label)
        summary_lay.addStretch(1)

        clear_btn = QPushButton("🗑 Clear Read")
        clear_btn.clicked.connect(self._on_clear_read)
        summary_lay.addWidget(clear_btn)

        test_btn = QPushButton("🧪 Test Notification")
        test_btn.clicked.connect(self._on_test_notification)
        summary_lay.addWidget(test_btn)

        splitter.addWidget(summary)

        # Notification list
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "ID", "Timestamp", "Level", "Title", "Message", "Category"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        splitter.addWidget(self.table)

        # Log output
        log_group = QGroupBox("Notification Log")
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

    # ── Display ───────────────────────────────────────

    def refresh(self):
        notifs = self.notif_manager._notifications
        self.table.setRowCount(len(notifs))
        for i, n in enumerate(notifs):
            ts = datetime.fromtimestamp(n["timestamp"]).strftime("%Y-%m-%d %H:%M") if n["timestamp"] else "—"
            self.table.setItem(i, 0, QTableWidgetItem(str(n["id"])))
            self.table.setItem(i, 1, QTableWidgetItem(ts))
            level_item = QTableWidgetItem(n["level"])
            if n["level"] == "critical":
                level_item.setForeground(QColor("#ff5555"))
            elif n["level"] == "warning":
                level_item.setForeground(QColor("#ffaa00"))
            elif n["level"] == "success":
                level_item.setForeground(QColor("#00ff88"))
            self.table.setItem(i, 2, level_item)
            self.table.setItem(i, 3, QTableWidgetItem(n["title"]))
            self.table.setItem(i, 4, QTableWidgetItem(n["message"][:60]))
            self.table.setItem(i, 5, QTableWidgetItem(n["category"]))
        self.table.resizeColumnsToContents()
        unread = len(self.notif_manager.get_unread())
        self.unread_label.setText(f"Unread: {unread}")

    # ── Handlers ──────────────────────────────────────

    def _on_clear_read(self):
        for n in self.notif_manager._notifications:
            if n["read"]:
                n["read"] = True
        self.refresh()

    def _on_test_notification(self):
        self.notif_manager.notify(
            title="Test Notification",
            message="MrBot1000 notification system is working.",
            level="info",
            category="system",
        )
        self.refresh()
        self.log_signal.emit("Test notification sent")

    def _append_log(self, msg: str):
        self.log_edit.append(msg)

    # ── Public API ────────────────────────────────────

    def send(
        self,
        title: str,
        message: str,
        level: str = "info",
        category: str = "system",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a notification from external code."""
        return self.notif_manager.notify(title, message, level, category, data)
