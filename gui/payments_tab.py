# ═══════════════════════════════════════════════════════════════════════════
# PAYMENTS TAB — v2.1 Phase 4
# ═══════════════════════════════════════════════════════════════════════════
# PURPOSE: GUI for wallet management, payments, and escrow.

import os
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLineEdit, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSpinBox, QDoubleSpinBox,
    QComboBox, QTextEdit, QMessageBox, QSplitter
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor


class PaymentsTab(QWidget):
    """Tab for managing wallets, payments, and escrow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.wallet_manager = None
        self.x402 = None
        self.escrow_manager = None
        self.automated_payout = None
        self.setup_ui()
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(3000)

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("💳 Payments & Wallets")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        layout.addWidget(header)

        # Splitter for wallets and transactions
        splitter = QSplitter(Qt.Vertical)

        # Wallets section
        wallets_group = QGroupBox("👛 Wallets")
        wallets_group.setStyleSheet("""
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
        wallets_layout = QVBoxLayout(wallets_group)

        # Add wallet form
        add_wallet_form = QHBoxLayout()
        self.wallet_address_input = QLineEdit()
        self.wallet_address_input.setPlaceholderText("Wallet address")
        add_wallet_form.addWidget(self.wallet_address_input)

        self.wallet_chain_combo = QComboBox()
        self.wallet_chain_combo.addItems(["solana", "ethereum", "polygon", "base"])
        add_wallet_form.addWidget(self.wallet_chain_combo)

        add_wallet_btn = QPushButton("➕ Add Wallet")
        add_wallet_btn.clicked.connect(self._on_add_wallet)
        add_wallet_form.addWidget(add_wallet_btn)

        wallets_layout.addLayout(add_wallet_form)

        # Wallets table
        self.wallets_table = QTableWidget()
        self.wallets_table.setColumnCount(4)
        self.wallets_table.setHorizontalHeaderLabels(["Address", "Chain", "Balance", "Currency"])
        self.wallets_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.wallets_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.wallets_table.setStyleSheet("""
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
        wallets_layout.addWidget(self.wallets_table)

        # Total balance
        self.total_balance_label = QLabel("Total Balance: —")
        self.total_balance_label.setStyleSheet("font-size: 12pt; color: #00ff88;")
        wallets_layout.addWidget(self.total_balance_label)

        splitter.addWidget(wallets_group)

        # Transactions section
        tx_group = QGroupBox("📋 Transactions")
        tx_group.setStyleSheet("""
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
        tx_layout = QVBoxLayout(tx_group)

        self.tx_table = QTableWidget()
        self.tx_table.setColumnCount(6)
        self.tx_table.setHorizontalHeaderLabels(["ID", "From", "To", "Amount", "Currency", "Status"])
        self.tx_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tx_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tx_table.setStyleSheet("""
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
        tx_layout.addWidget(self.tx_table)

        splitter.addWidget(tx_group)

        layout.addWidget(splitter)

        # Status
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

    def refresh(self):
        """Refresh displays."""
        self._refresh_wallets()
        self._refresh_transactions()

    def _refresh_wallets(self):
        """Refresh wallets display."""
        self.wallets_table.setRowCount(0)
        if not self.wallet_manager:
            return

        wallets = self.wallet_manager.list_wallets()
        totals: dict = {}

        for i, w in enumerate(wallets):
            self.wallets_table.insertRow(i)
            self.wallets_table.setItem(i, 0, QTableWidgetItem(w.address[:20] + "..."))
            self.wallets_table.setItem(i, 1, QTableWidgetItem(w.chain.value))
            self.wallets_table.setItem(i, 2, QTableWidgetItem(f"{w.balance:.4f}"))
            self.wallets_table.setItem(i, 3, QTableWidgetItem(w.currency or w.chain.value))

            currency = w.currency or w.chain.value
            totals[currency] = totals.get(currency, 0.0) + w.balance

        total_text = " | ".join(f"{c}: {b:.4f}" for c, b in totals.items())
        self.total_balance_label.setText(f"Total Balance: {total_text or '—'}")

    def _refresh_transactions(self):
        """Refresh transactions display."""
        self.tx_table.setRowCount(0)
        if not self.x402:
            return

        txs = self.x402.get_payments()
        for i, tx in enumerate(txs):
            self.tx_table.insertRow(i)
            self.tx_table.setItem(i, 0, QTableWidgetItem(tx.get("payment_id", "")[:16]))
            self.tx_table.setItem(i, 1, QTableWidgetItem(tx.get("from", "")[:20]))
            self.tx_table.setItem(i, 2, QTableWidgetItem(tx.get("to", "")[:20]))
            self.tx_table.setItem(i, 3, QTableWidgetItem(f"{tx.get('amount', 0):.4f}"))
            self.tx_table.setItem(i, 4, QTableWidgetItem(tx.get("currency", "")))
            self.tx_table.setItem(i, 5, QTableWidgetItem(tx.get("status", "")))

    def _on_add_wallet(self):
        """Add a new wallet."""
        address = self.wallet_address_input.text().strip()
        chain_str = self.wallet_chain_combo.currentText()
        if not address:
            QMessageBox.warning(self, "Error", "Address required")
            return

        try:
            from agents.wallet import Chain
            chain = Chain(chain_str)
            if self.wallet_manager:
                self.wallet_manager.add_wallet(address, chain)
                self.wallet_address_input.clear()
                self.refresh()
                self.status_label.setText(f"Wallet added: {address[:20]}...")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
