"""gui/approval_panel.py — In-app human-approval queue panel (Phase 6).

Shows pending submissions, payments, and gate clearances from
``agents.approval_queue``, with Approve / Deny / Defer actions.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QMessageBox, QComboBox, QSplitter, QFrame, QSizePolicy,
)
from PySide6.QtGui import QFont, QColor

logger = logging.getLogger("mrbot.gui.approval_panel")

from agents.approval_queue import (
    HumanApprovalQueue, ApprovalKind, ApprovalItem, ApprovalStatus,
)


class ApprovalPanel(QWidget):
    """In-app panel listing pending approvals with Approve / Deny / Defer."""

    item_decided = Signal(str, ApprovalStatus, str)  # item_id, status, notes

    def __init__(self, parent: Optional[QWidget] = None,
                 approval_queue: Optional[HumanApprovalQueue] = None):
        super().__init__(parent)
        self.approval_queue = approval_queue or HumanApprovalQueue.instance()
        self._pending: List[ApprovalItem] = []
        self._selected_item: Optional[ApprovalItem] = None
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2500)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        header = QLabel("🛡️ Human Approval Queue")
        header.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header.setStyleSheet("color: #bb86fc; padding: 6px;")
        root.addWidget(header)

        self.status_label = QLabel("No pending approvals")
        self.status_label.setStyleSheet("color: #88aaff; font-weight: bold;")
        root.addWidget(self.status_label)

        splitter = QSplitter(Qt.Vertical)

        # List of pending items
        list_box = QGroupBox("Pending Items")
        list_lay = QVBoxLayout(list_box)
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        list_lay.addWidget(self.list_widget, stretch=1)
        splitter.addWidget(list_box)

        # Detail / action panel
        detail_box = QGroupBox("Item Details")
        detail_lay = QVBoxLayout(detail_box)

        self.detail_title = QLabel("—")
        self.detail_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        detail_lay.addWidget(self.detail_title)

        self.detail_desc = QLabel("—")
        self.detail_desc.setWordWrap(True)
        detail_lay.addWidget(self.detail_desc)

        self.detail_kind = QLabel("Kind: —")
        detail_lay.addWidget(self.detail_kind)

        self.detail_req = QLabel("Requested by: —")
        detail_lay.addWidget(self.detail_req)

        self.detail_time = QLabel("Requested at: —")
        detail_lay.addWidget(self.detail_time)

        detail_lay.addStretch(1)

        btn_lay = QHBoxLayout()
        self.approve_btn = QPushButton("✅ Approve")
        self.approve_btn.setMinimumHeight(36)
        self.approve_btn.clicked.connect(self._on_approve)
        btn_lay.addWidget(self.approve_btn)

        self.deny_btn = QPushButton("❌ Deny")
        self.deny_btn.setMinimumHeight(36)
        self.deny_btn.clicked.connect(self._on_deny)
        btn_lay.addWidget(self.deny_btn)

        self.defer_btn = QPushButton("⏸️ Defer")
        self.defer_btn.setMinimumHeight(36)
        self.defer_btn.clicked.connect(self._on_defer)
        btn_lay.addWidget(self.defer_btn)
        btn_lay.addStretch(1)

        self.notes_label = QLabel("Notes (optional):")
        self.notes_label.setStyleSheet("color: #88aaff;")
        self.notes_input = QLabel("")  # placeholder
        detail_lay.addLayout(btn_lay)
        detail_lay.addWidget(self.notes_label)
        detail_lay.addWidget(self.notes_input)

        splitter.addWidget(detail_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, stretch=1)

        root.addStretch(1)
        self.setLayout(root)

    # ── Signals / refresh ────────────────────────────────────────────────────

    def _refresh(self):
        try:
            self._pending = self.approval_queue.pending()
            self.list_widget.clear()
            if not self._pending:
                self.status_label.setText("No pending approvals")
                self.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
                self._clear_detail()
                return
            self.status_label.setText(
                f"{len(self._pending)} pending approval(s)"
            )
            self.status_label.setStyleSheet("color: #ff9800; font-weight: bold;")
            for it in self._pending:
                # Color by kind
                color = {
                    ApprovalKind.SUBMISSION: "#2196f3",
                    ApprovalKind.PAYMENT: "#4caf50",
                    ApprovalKind.GATE: "#ff9800",
                    ApprovalKind.ACTION: "#9c27b0",
                }.get(it.kind, "#e0e0e0")
                item = QListWidgetItem(
                    f"[{it.kind.value}] {it.title}"
                )
                item.setForeground(QColor(color))
                item.setData(Qt.UserRole, it.id)
                self.list_widget.addItem(item)
        except Exception as e:
            logger.warning("approval panel refresh failed: %s", e)

    def _on_selection_changed(self):
        sel = self.list_widget.selectedItems()
        if not sel:
            self._clear_detail()
            return
        item_id = sel[0].data(Qt.UserRole)
        it = self.approval_queue.find_by_id(item_id)
        if it is None:
            self._clear_detail()
            return
        self._selected_item = it
        self.detail_title.setText(it.title)
        self.detail_desc.setText(it.description)
        self.detail_kind.setText(f"Kind: {it.kind.value}")
        self.detail_req.setText(f"Requested by: {it.requested_by}")
        self.detail_time.setText(f"Requested at: {it.requested_at:.0f}")
        # enable buttons only if still pending
        is_pending = it.status == ApprovalStatus.PENDING
        self.approve_btn.setEnabled(is_pending)
        self.deny_btn.setEnabled(is_pending)
        self.defer_btn.setEnabled(is_pending)

    def _clear_detail(self):
        self._selected_item = None
        self.detail_title.setText("—")
        self.detail_desc.setText("—")
        self.detail_kind.setText("Kind: —")
        self.detail_req.setText("Requested by: —")
        self.detail_time.setText("Requested at: —")
        self.approve_btn.setEnabled(False)
        self.deny_btn.setEnabled(False)
        self.defer_btn.setEnabled(False)
        self.notes_input.setText("")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_approve(self):
        it = self._selected_item
        if it is None:
            return
        # In a real GUI, open a notes dialog. For now, approve with empty notes.
        QMessageBox.information(
            self, "Approve", f"Approve '{it.title}'?"
        )
        if self.approval_queue.approve(it.id, notes="Approved from GUI"):
            self.item_decided.emit(it.id, ApprovalStatus.APPROVED, "Approved from GUI")
            self._refresh()

    def _on_deny(self):
        it = self._selected_item
        if it is None:
            return
        reason, ok = QInputDialog.getText(
            self, "Deny", f"Deny '{it.title}'. Reason (optional):"
        )
        if not ok:
            return
        if self.approval_queue.deny(it.id, notes=reason or "Denied from GUI"):
            self.item_decided.emit(it.id, ApprovalStatus.DENIED,
                                   reason or "Denied from GUI")
            self._refresh()

    def _on_defer(self):
        it = self._selected_item
        if it is None:
            return
        reason, ok = QInputDialog.getText(
            self, "Defer", f"Defer '{it.title}'. Reason (optional):"
        )
        if not ok:
            return
        if self.approval_queue.defer(it.id, notes=reason or "Deferred from GUI"):
            self.item_decided.emit(it.id, ApprovalStatus.DEFERRED,
                                   reason or "Deferred from GUI")
            self._refresh()

    # ── Public ────────────────────────────────────────────────────────────────

    def refresh_now(self):
        self._refresh()


# Needed import for the defer dialog
from PySide6.QtWidgets import QInputDialog


__all__ = ["ApprovalPanel"]
