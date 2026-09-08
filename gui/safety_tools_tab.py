# ═══════════════════════════════════════════════════════════════════════════
# SAFETY TAB — v2.1 Phase 3
# ═══════════════════════════════════════════════════════════════════════════
# PURPOSE: GUI for the multi-layer safety system.
#          Shows safety status, pending approvals, and configuration.

import os
import sys
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPushButton, QLabel, QSplitter, QCheckBox, QSpinBox, QFormLayout,
    QTabWidget, QComboBox, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont


class SafetyTab(QWidget):
    """Tab for viewing safety status, approvals, and configuration."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Safety guard reference
        self.safety_guard = None
        self.approval_queue = []
        
        # Build UI
        self.setup_ui()
        
        # Refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(2000)
    
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
    
    def _refresh_layers(self):
        """Refresh safety layers display."""
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
        """Refresh pending approvals display."""
        self.approvals_table.setRowCount(0)
        
        # Get pending approvals from safety guard
        if self.safety_guard:
            pending = self.safety_guard.get_pending_approvals()
        else:
            pending = self.approval_queue
        
        for i, approval in enumerate(pending):
            self.approvals_table.insertRow(i)
            self.approvals_table.setItem(i, 0, QTableWidgetItem(approval.get("id", "")))
            self.approvals_table.setItem(i, 1, QTableWidgetItem(str(approval.get("action", ""))))
            self.approvals_table.setItem(i, 2, QTableWidgetItem(str(approval.get("reasons", ""))))
            self.approvals_table.setItem(i, 3, QTableWidgetItem(
                datetime.fromtimestamp(approval.get("requested_at", 0)).strftime("%H:%M:%S")
            ))
    
    def _on_approve(self):
        """Approve selected action."""
        # Get selected approval
        row = self.approvals_table.currentRow()
        if row < 0:
            return
        
        approval_id = self.approvals_table.item(row, 0).text()
        if self.safety_guard:
            self.safety_guard.approve(approval_id)
        self.refresh()
    
    def _on_reject(self):
        """Reject selected action."""
        row = self.approvals_table.currentRow()
        if row < 0:
            return
        
        approval_id = self.approvals_table.item(row, 0).text()
        if self.safety_guard:
            self.safety_guard.reject(approval_id)
        self.refresh()
    
    def _on_save_config(self):
        """Save safety configuration."""
        # TODO: Persist config
        pass
