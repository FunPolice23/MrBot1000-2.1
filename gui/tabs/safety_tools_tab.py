# ═══════════════════════════════════════════════════════════════════════════
# SAFETY TAB — v2.1 Phase 3
# ═══════════════════════════════════════════════════════════════════════════
# PURPOSE: GUI for the multi-layer safety system.
#          Shows safety status, pending approvals, and configuration.

import os
import sys
import json
import logging
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPushButton, QLabel, QSplitter, QCheckBox, QSpinBox, QFormLayout,
    QTabWidget, QComboBox, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont

from agents.safety.approval import ApprovalKind


SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "settings.json")


# The approval kinds ``main.MainWindow._on_approval_decided`` can actually route
# to an execution path: ACTION -> ``_execute_approved_action``, SUBMISSION ->
# ``_execute_approved_submission``. Those are its only two branches.
#
# An approval of any other kind is recorded in the queue and then goes
# nowhere: the operator sees the request, clicks Approve, watches it turn
# APPROVED, and nothing happens — with no log explaining why (F7).
# ``SafetyGuard`` sets ``kind=PAYMENT`` for any action with ``requires_funds``
# and ``human_gates`` enqueues GATE items, so both were selectable and
# approvable here while no execution path existed for them. Offering an Approve
# button that cannot do anything is the "silently dropped decision" class this
# tab was already changed to fix, so this surface only lists what it can route.
#
# Those requests are NOT hidden from the operator. The Approvals panel
# (``gui/panels/approval_panel.py``, wired in main.py as ``_approval_panel``)
# lists EVERY pending item of every kind with full detail, and every enqueue
# raises a sticky ``approval_required`` notification
# (``HumanApprovalQueue.enqueue``), so a payment request stays fully visible.
# Note that panel has the same unroutable-approval gap (it lists everything and
# routes through the same two-branch handler); that is a separate defect in a
# file this change does not touch. What this filter guarantees is that the
# Safety & Tools table stops offering a button that is a guaranteed no-op.
_ROUTABLE_APPROVAL_KINDS = (ApprovalKind.ACTION, ApprovalKind.SUBMISSION)


class SafetyTab(QWidget):
    """Tab for viewing safety status, approvals, and configuration."""

    ACTIVE_REFRESH_MS = 2000
    BACKGROUND_REFRESH_MS = 15000
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Safety guard reference
        self.safety_guard = None
        from agents.safety.approval import HumanApprovalQueue
        self.approval_queue = HumanApprovalQueue.instance()
        
        # Build UI
        self.setup_ui()
        self._load_config()
        
        # Refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(self.ACTIVE_REFRESH_MS)
        self.refresh()

    def showEvent(self, event):
        self.refresh()
        self.refresh_timer.setInterval(self.ACTIVE_REFRESH_MS)
        self.refresh_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.refresh_timer.setInterval(self.BACKGROUND_REFRESH_MS)
        self.refresh_timer.start()
        super().hideEvent(event)
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel("🛡️ Safety & Security")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        layout.addWidget(header)
        
        # Tab widget for sub-tabs
        self.sub_tabs = QTabWidget()
        
        # Status sub-tab
        self.sub_tabs.addTab(self._create_status_tab(), "📊 Status")
        
        # Approvals sub-tab
        self.sub_tabs.addTab(self._create_approvals_tab(), "📋 Approvals")

        # Quarantined-instruction review sub-tab (ARCH-ENG-284 / U-01)
        self.sub_tabs.addTab(self._create_quarantine_tab(), "📥 Quarantine")

        # Configuration sub-tab
        self.sub_tabs.addTab(self._create_config_tab(), "⚙️ Config")
        
        layout.addWidget(self.sub_tabs)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(refresh_btn)
    
    def _create_status_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Safety layers status
        layers_group = QGroupBox("🛡️ Safety Layers")
        layers_group.setStyleSheet("""
            QGroupBox {
                color: #03dac6;
                font-weight: bold;
                border: 2px solid #03dac6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        layers_layout = QVBoxLayout(layers_group)
        
        self.layers_table = QTableWidget()
        self.layers_table.setColumnCount(4)
        self.layers_table.setHorizontalHeaderLabels(["Layer", "Status", "Priority", "Description"])
        self.layers_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.layers_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.layers_table.setStyleSheet("""
            QTableWidget {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                font-size: 11px;
            }
            QHeaderView::section {
                background: #2a2a2a;
                color: #e0e0e0;
                padding: 6px;
                border: 1px solid #333;
                font-weight: bold;
            }
        """)
        layers_layout.addWidget(self.layers_table)
        
        layout.addWidget(layers_group)
        
        # Circuit breaker status
        cb_group = QGroupBox("🔌 Circuit Breaker")
        cb_group.setStyleSheet("""
            QGroupBox {
                color: #ffcc44;
                font-weight: bold;
                border: 2px solid #ffcc44;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        cb_layout = QVBoxLayout(cb_group)
        
        self.circuit_breaker_label = QLabel("All providers healthy")
        self.circuit_breaker_label.setStyleSheet("color: #00ff88;")
        cb_layout.addWidget(self.circuit_breaker_label)
        
        layout.addWidget(cb_group)
        
        # Rate limiter status
        rate_group = QGroupBox("⏱️ Rate Limits")
        rate_group.setStyleSheet("""
            QGroupBox {
                color: #88aaff;
                font-weight: bold;
                border: 2px solid #88aaff;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        rate_layout = QVBoxLayout(rate_group)
        
        self.rate_limit_label = QLabel("All within limits")
        self.rate_limit_label.setStyleSheet("color: #00ff88;")
        rate_layout.addWidget(self.rate_limit_label)
        
        layout.addWidget(rate_group)
        
        return widget
    
    def _create_approvals_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Pending approvals
        pending_group = QGroupBox("⏳ Pending Approvals")
        pending_group.setStyleSheet("""
            QGroupBox {
                color: #ffcc44;
                font-weight: bold;
                border: 2px solid #ffcc44;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        pending_layout = QVBoxLayout(pending_group)
        
        self.approvals_table = QTableWidget()
        self.approvals_table.setColumnCount(5)
        self.approvals_table.setHorizontalHeaderLabels(["ID", "Action", "Reasons", "Requested", ""])
        self.approvals_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.approvals_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.approvals_table.setStyleSheet("""
            QTableWidget {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                font-size: 11px;
            }
            QHeaderView::section {
                background: #2a2a2a;
                color: #e0e0e0;
                padding: 6px;
                border: 1px solid #333;
                font-weight: bold;
            }
        """)
        pending_layout.addWidget(self.approvals_table)
        
        # Approval buttons
        btn_row = QHBoxLayout()
        
        self.approve_btn = QPushButton("✅ Approve")
        self.approve_btn.clicked.connect(self._on_approve)
        btn_row.addWidget(self.approve_btn)
        
        self.reject_btn = QPushButton("❌ Reject")
        self.reject_btn.clicked.connect(self._on_reject)
        btn_row.addWidget(self.reject_btn)
        
        btn_row.addStretch()
        pending_layout.addLayout(btn_row)
        
        layout.addWidget(pending_group)
        
        return widget

    def _create_quarantine_tab(self):
        """ARCH-ENG-284 (U-01): the instruction-quarantine review surface.

        `InstructionGate` quarantines every unknown fetched SKILL.md/playbook
        until a human approves or blacklists it, but the MainWindow's
        `_refresh_review_queue` / `_review_selected` methods referenced
        `review_list` and `review_counts_label` widgets that were never
        created. The gate's queue therefore had no review surface at all:
        unknown instructions could only ever stay pending. This tab is the
        surface, wired to the same gate the platform adapters use.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("📥 Quarantined External Instructions")
        group.setStyleSheet("""
            QGroupBox {
                color: #ff8844;
                font-weight: bold;
                border: 2px solid #ff8844;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        group_layout = QVBoxLayout(group)

        self.quarantine_counts_label = QLabel("Instruction gate unavailable")
        self.quarantine_counts_label.setWordWrap(True)
        group_layout.addWidget(self.quarantine_counts_label)

        self.quarantine_table = QTableWidget()
        self.quarantine_table.setColumnCount(4)
        self.quarantine_table.setHorizontalHeaderLabels(
            ["ID", "Title", "Kind", "URL"])
        self.quarantine_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.quarantine_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers)
        self.quarantine_table.setSelectionBehavior(
            QAbstractItemView.SelectRows)
        self.quarantine_table.setSelectionMode(
            QAbstractItemView.SingleSelection)
        self.quarantine_table.setStyleSheet("""
            QTableWidget {
                background: #1a1a1a;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                font-size: 11px;
            }
            QHeaderView::section {
                background: #2a2a2a;
                color: #e0e0e0;
                padding: 6px;
                border: 1px solid #333;
                font-weight: bold;
            }
        """)
        group_layout.addWidget(self.quarantine_table)

        btn_row = QHBoxLayout()
        self.quarantine_approve_btn = QPushButton("✅ Allow")
        self.quarantine_approve_btn.clicked.connect(
            lambda: self._on_quarantine_decision(True))
        btn_row.addWidget(self.quarantine_approve_btn)

        self.quarantine_block_btn = QPushButton("⛔ Blacklist")
        self.quarantine_block_btn.clicked.connect(
            lambda: self._on_quarantine_decision(False))
        btn_row.addWidget(self.quarantine_block_btn)

        self.quarantine_refresh_btn = QPushButton("🔄 Refresh")
        self.quarantine_refresh_btn.clicked.connect(
            self._refresh_quarantine)
        btn_row.addWidget(self.quarantine_refresh_btn)
        btn_row.addStretch()
        group_layout.addLayout(btn_row)

        layout.addWidget(group)
        return widget

    def _instruction_gate(self):
        """Resolve the gate from this tab or its MainWindow parent."""
        gate = getattr(self, "instruction_gate", None)
        if gate is None:
            parent = self.parent()
            gate = getattr(parent, "instruction_gate", None) if parent else None
            if gate is not None:
                self.instruction_gate = gate
        return gate

    def set_instruction_gate(self, gate):
        """Wire the authoritative gate after the MainWindow constructs it."""
        self.instruction_gate = gate
        self._refresh_quarantine()

    def _quarantine_log(self, message: str) -> None:
        parent = self.parent()
        log_signal = getattr(parent, "log_signal", None)
        if log_signal is not None:
            log_signal.emit(message)

    def _refresh_quarantine(self):
        gate = self._instruction_gate()
        buttons = (
            getattr(self, "quarantine_approve_btn", None),
            getattr(self, "quarantine_block_btn", None),
        )
        if gate is None:
            if hasattr(self, "quarantine_counts_label"):
                self.quarantine_counts_label.setText(
                    "Instruction gate unavailable; no quarantined "
                    "instruction can be reviewed.")
            if hasattr(self, "quarantine_table"):
                self.quarantine_table.setRowCount(0)
            for button in buttons:
                if button is not None:
                    button.setEnabled(False)
            return
        try:
            counts = gate.counts()
            pending = list(gate.pending(200))
        except Exception as exc:
            if hasattr(self, "quarantine_counts_label"):
                self.quarantine_counts_label.setText(
                    f"Quarantine read failed: {exc}")
            for button in buttons:
                if button is not None:
                    button.setEnabled(False)
            return

        self.quarantine_counts_label.setText(
            f"Pending: {counts.get('pending', 0)}   "
            f"Allowed: {counts.get('allowed', 0)}   "
            f"Blocked: {counts.get('blocked', 0)}   "
            f"Quarantined: {counts.get('quarantined', 0)}")
        self.quarantine_table.setRowCount(0)
        for row, item in enumerate(pending):
            self.quarantine_table.insertRow(row)
            id_item = QTableWidgetItem(str(item.get("id", "")))
            id_item.setData(Qt.UserRole, dict(item))
            self.quarantine_table.setItem(row, 0, id_item)
            self.quarantine_table.setItem(
                row, 1, QTableWidgetItem(
                    str(item.get("title") or item.get("url") or "")))
            self.quarantine_table.setItem(
                row, 2, QTableWidgetItem(str(item.get("kind", ""))))
            self.quarantine_table.setItem(
                row, 3, QTableWidgetItem(str(item.get("url", ""))))
        for button in buttons:
            if button is not None:
                button.setEnabled(bool(pending))

    def _on_quarantine_decision(self, approve: bool):
        gate = self._instruction_gate()
        if gate is None:
            return
        row = self.quarantine_table.currentRow()
        if row < 0:
            self._quarantine_log(
                "[Review] Select a quarantined instruction first.")
            return
        id_item = self.quarantine_table.item(row, 0)
        record = id_item.data(Qt.UserRole) if id_item is not None else None
        if not isinstance(record, dict) or "id" not in record:
            self._quarantine_log(
                "[Review] Selected row has no quarantine record; refresh "
                "and try again.")
            return
        qid = int(record["id"])
        url = str(record.get("url", "") or "")
        content_hash = str(record.get("content_hash", "") or "")
        kind = str(record.get("kind", "skill.md") or "skill.md")
        related = f"{url} | {kind} | {content_hash}"
        try:
            status = gate.review(
                qid, approve, url=url, content_hash=content_hash,
                related=related)
            self._quarantine_log(
                f"[Review] instruction #{qid} -> {status} "
                f"({'APPROVED' if approve else 'BLACKLISTED'})")
        except Exception as exc:
            self._quarantine_log(f"[Review] error: {exc}")
        self._refresh_quarantine()

    def _create_config_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Cost guard config
        cost_group = QGroupBox("💰 Cost Guard")
        cost_group.setStyleSheet("""
            QGroupBox {
                color: #00ff88;
                font-weight: bold;
                border: 2px solid #00ff88;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        cost_layout = QFormLayout(cost_group)
        
        self.cost_guard_enabled = QCheckBox("Enabled")
        self.cost_guard_enabled.setChecked(True)
        cost_layout.addRow("Enable Cost Guard:", self.cost_guard_enabled)
        
        self.daily_budget_spin = QSpinBox()
        self.daily_budget_spin.setRange(0, 1000)
        self.daily_budget_spin.setValue(10)
        self.daily_budget_spin.setSuffix(" USD")
        cost_layout.addRow("Daily Budget:", self.daily_budget_spin)
        
        layout.addWidget(cost_group)
        
        # Recursion detector config
        recursion_group = QGroupBox("🔄 Recursion Detector")
        recursion_group.setStyleSheet("""
            QGroupBox {
                color: #ff5555;
                font-weight: bold;
                border: 2px solid #ff5555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        recursion_layout = QFormLayout(recursion_group)
        
        self.recursion_enabled = QCheckBox("Enabled")
        self.recursion_enabled.setChecked(True)
        recursion_layout.addRow("Enable Recursion Detection:", self.recursion_enabled)
        
        self.max_depth_spin = QSpinBox()
        self.max_depth_spin.setRange(1, 100)
        self.max_depth_spin.setValue(10)
        recursion_layout.addRow("Max Call Depth:", self.max_depth_spin)
        
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 300)
        self.timeout_spin.setValue(30)
        self.timeout_spin.setSuffix(" seconds")
        recursion_layout.addRow("Timeout:", self.timeout_spin)
        
        layout.addWidget(recursion_group)
        
        # Tool firewall config
        firewall_group = QGroupBox("🔥 Tool Firewall")
        firewall_group.setStyleSheet("""
            QGroupBox {
                color: #ffaa55;
                font-weight: bold;
                border: 2px solid #ffaa55;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        firewall_layout = QFormLayout(firewall_group)
        
        self.firewall_enabled = QCheckBox("Enabled")
        self.firewall_enabled.setChecked(True)
        firewall_layout.addRow("Enable Tool Firewall:", self.firewall_enabled)
        
        layout.addWidget(firewall_group)
        
        # Save button
        save_btn = QPushButton("💾 Save Configuration")
        save_btn.clicked.connect(self._on_save_config)
        layout.addWidget(save_btn)
        
        layout.addStretch()
        return widget
    
    def refresh(self):
        """Refresh all displays."""
        self._refresh_layers()
        self._refresh_approvals()
        self._refresh_quarantine()
    
    def _refresh_layers(self):
        """Refresh safety layers display.

        ARCH-ENG-223: THIS TABLE IS A CONSTANT, AND WAS BEING REBUILT ON EVERY
        TICK.

        The six rows below never change -- they are a hard-coded list, not a
        reading of any live state. Yet the method ran `setRowCount(0)` then
        6 x `insertRow` + 24 x `QTableWidgetItem` every tick: twice a second
        while the tab is visible, every 15 s while hidden, for the life of the
        process. That is 24 item allocations plus a full relayout and repaint of
        a styled table, roughly every tick, to redraw six unchanging strings.

        Populated once. If the layer list ever becomes real state rather than a
        constant, delete the guard -- a stale-by-design table is worse than a
        slow one, so this is deliberately the easy change to undo.
        """
        if getattr(self, "_layers_populated", False):
            return
        self._layers_populated = True
        self.layers_table.setRowCount(0)
        
        layers = [
            ("Cost Guard", "100", "Daily budget enforcement"),
            ("Recursion Detector", "90", "Loop detection & timeout"),
            ("Tool Firewall", "80", "Allow/deny lists"),
            ("Human Approval", "70", "High-value action gates"),
            ("Rate Limiter", "60", "Per-tool rate limiting"),
            ("Circuit Breaker", "50", "Provider fail-fast"),
        ]
        
        for i, (name, priority, desc) in enumerate(layers):
            self.layers_table.insertRow(i)
            self.layers_table.setItem(i, 0, QTableWidgetItem(name))
            self.layers_table.setItem(i, 1, QTableWidgetItem("✅ Active"))
            self.layers_table.setItem(i, 2, QTableWidgetItem(priority))
            self.layers_table.setItem(i, 3, QTableWidgetItem(desc))
    
    def _refresh_approvals(self):
        """Refresh pending approvals display.

        Every PENDING item in ``HumanApprovalQueue`` is listed, not only the
        ones the SafetyGuard raised itself. Guard-owned records carry the
        richer ``action``/``reasons`` shape, so they are used when available
        and the queue item's ``to_dict()`` fills in the rest — otherwise a
        ``run_command`` / ``file_write`` request the chat or the Big Brain
        enqueued directly was invisible here, and an item the operator cannot
        see is an item the operator cannot approve.
        Reproduced: queue.pending()==2 (dispatch-origin items) while the table
        showed 0 rows.

        BUT only for the kinds this surface can actually act on
        (``_ROUTABLE_APPROVAL_KINDS``). ``main.py:_on_approval_decided`` routes
        ACTION and SUBMISSION approvals to an execution path and has no branch
        for anything else, so listing a PAYMENT or GATE request here made it
        selectable and approvable while nothing could ever run it: the click
        turned the row APPROVED and stopped, silently. A filtered item stays
        PENDING and stays visible in the Approvals panel and its sticky
        notification — see the comment on that constant.
        """
        self.approvals_table.setRowCount(0)

        guard_by_id = {}
        if self.safety_guard:
            try:
                for record in self.safety_guard.get_pending_approvals():
                    record_id = record.get("id")
                    if record_id:
                        guard_by_id[record_id] = record
            except Exception:
                guard_by_id = {}

        try:
            pending = list(self.approval_queue.pending())
        except Exception:
            pending = []

        rows = []
        for item in pending:
            if item.kind not in _ROUTABLE_APPROVAL_KINDS:
                continue
            approval = item.to_dict()
            guard_record = guard_by_id.get(item.id)
            if guard_record:
                # The guard owns this request and its record carries the real
                # SafetyAction; merge it over the queue dict but keep the
                # queue's authoritative id so the approve path keys correctly.
                approval.update(guard_record)
                approval["id"] = item.id
            rows.append(approval)

        for i, approval in enumerate(rows):
            self.approvals_table.insertRow(i)
            self.approvals_table.setItem(i, 0, QTableWidgetItem(str(approval.get("id", ""))))
            action = approval.get("action") or approval.get("title", "")
            reason = approval.get("reasons") or approval.get("description", "")
            self.approvals_table.setItem(i, 1, QTableWidgetItem(str(action)))
            self.approvals_table.setItem(i, 2, QTableWidgetItem(str(reason)))
            # requested_at is a float timestamp in both shapes, but neither is
            # guaranteed to have it (a guard record pruned mid-refresh, a queue
            # item restored from a hand-edited log), and a missing key here
            # would raise inside a table refresh and blank the whole panel.
            try:
                requested_at = float(approval.get("requested_at") or 0.0)
            except (TypeError, ValueError):
                requested_at = 0.0
            self.approvals_table.setItem(i, 3, QTableWidgetItem(
                datetime.fromtimestamp(requested_at).strftime("%H:%M:%S")
                if requested_at else ""
            ))

    def _on_approve(self):
        """Approve selected action.

        The decision must then be routed to the same execution path the
        Approvals tab uses. Recording it in the queue alone left this surface
        half-wired: an approved submission showed APPROVED here and was never
        sent, because only ``ApprovalPanel`` emits ``item_decided``.

        The human's click is NEVER dropped. ``SafetyGuard.approve()`` only
        knows the ids it raised itself, so an approval the chat dispatcher or
        the Big Brain enqueued straight into ``HumanApprovalQueue`` made it
        return False — and the item stayed PENDING forever, silently, with no
        log and no error. Reproduced: guard.approve(dispatch_id) -> False, the
        queue item never left 'pending', and ``_route_decision`` never ran.

        The guard is still tried FIRST (it owns its records and mirrors the
        decision into the queue), but the queue is the authority: when the
        guard does not recognise the id, the decision is recorded there
        instead. This cannot fabricate an approval — the id came from a row a
        human selected, and ``_on_approval_decided`` re-reads the queue before
        executing anything.
        """
        # Get selected approval
        row = self.approvals_table.currentRow()
        if row < 0:
            return

        approval_id = self.approvals_table.item(row, 0).text()
        ok = False
        if self.safety_guard:
            ok = self.safety_guard.approve(approval_id)
        if not ok:
            # The guard does not own this id (or already decided it). The queue
            # is the authority for a human decision, so record it there.
            ok = self.approval_queue.approve(
                approval_id, notes="Approved from Safety & Tools")
        if ok:
            self._route_decision(approval_id)
        self.refresh()

    def _on_reject(self):
        """Reject selected action.

        Same never-dropped rule as ``_on_approve``: a rejection the guard does
        not recognise is recorded in the queue instead of being swallowed, so
        an operator who clicks Reject never leaves an irreversible request
        looking pending and re-approvable.
        """
        row = self.approvals_table.currentRow()
        if row < 0:
            return

        approval_id = self.approvals_table.item(row, 0).text()
        ok = False
        if self.safety_guard:
            ok = self.safety_guard.reject(approval_id)
        if not ok:
            ok = self.approval_queue.deny(
                approval_id, notes="Rejected from Safety & Tools")
        self.refresh()

    def _route_decision(self, approval_id):
        """Hand a freshly recorded approval to the app's decision handler.

        Best-effort and fail-safe: this only notifies. It cannot execute
        anything by itself — the handler re-reads the decision from the queue,
        so a decision this tab did not actually record will not run.

        ARCH-ENG-269 (AZ-01): both failure paths used to vanish — a bare
        `return` when no handler is attached, and `except Exception: pass`
        when routing raised. "Recorded but never routed" is the worst state
        an approval can be in: the human clicked Approve, the row is gone
        from the pending list, and nothing will execute. Each path now logs
        and raises an operator warning; the fail-safe behaviour (never crash
        mid-click, never lose the recorded decision) is unchanged.
        """
        handler = getattr(self.parent(), "_on_approval_decided", None)
        if not callable(handler):
            self._report_unrouted(
                approval_id,
                "no decision handler is attached to the application")
            return
        try:
            from agents.safety.approval import ApprovalStatus
            item = self.approval_queue.find_by_id(approval_id)
            if item is None or item.status != ApprovalStatus.APPROVED:
                self._report_unrouted(
                    approval_id,
                    "the decision could not be re-read as APPROVED from the "
                    "approval queue")
                return
            handler(approval_id, ApprovalStatus.APPROVED,
                    "Approved from Safety & Tools")
        except Exception as exc:
            # A routing failure must not lose the recorded decision, and must
            # never surface as a crash in the middle of an approval click.
            self._report_unrouted(approval_id, f"routing raised: {exc}")

    def _report_unrouted(self, approval_id, reason):
        """Make "approved but not executed" visible (ARCH-ENG-269)."""
        logging.getLogger(__name__).warning(
            "Approval %s was recorded but not routed: %s", approval_id, reason)
        try:
            from agents.core.notifications import NotificationService
            NotificationService.instance().warning(
                "Approval recorded, not executed",
                f"Approval {approval_id} was recorded but not routed to the "
                f"executor ({reason}). Review it before relying on it.")
        except Exception:
            pass

    def _on_save_config(self):
        """Save safety configuration."""
        config = {
            "cost_guard_enabled": self.cost_guard_enabled.isChecked(),
            "daily_budget_usd": self.daily_budget_spin.value(),
            "recursion_detector_enabled": self.recursion_enabled.isChecked(),
            "max_depth": self.max_depth_spin.value(),
            "timeout_seconds": self.timeout_spin.value(),
            "tool_firewall_enabled": self.firewall_enabled.isChecked(),
        }
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
                settings = json.load(handle)
        except (OSError, ValueError):
            settings = {}
        settings["safety"] = config
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
                json.dump(settings, handle, indent=2)
            os.environ["LLM_DAILY_BUDGET_USD"] = str(config["daily_budget_usd"])
        except OSError:
            return

    def _load_config(self):
        """Load persisted safety settings without making startup fragile."""
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
                config = json.load(handle).get("safety", {})
        except (OSError, ValueError):
            config = {}
        self.cost_guard_enabled.setChecked(config.get("cost_guard_enabled", True))
        self.daily_budget_spin.setValue(int(config.get("daily_budget_usd", 10)))
        self.recursion_enabled.setChecked(config.get("recursion_detector_enabled", True))
        self.max_depth_spin.setValue(int(config.get("max_depth", 10)))
        self.timeout_spin.setValue(int(config.get("timeout_seconds", 30)))
        self.firewall_enabled.setChecked(config.get("tool_firewall_enabled", True))

    def cleanup(self):
        """Stop the tab-owned refresh timer during application shutdown."""
        if getattr(self, "refresh_timer", None) is not None:
            self.refresh_timer.stop()
