"""
gui/earning_tab.py — Unified Earning tab integrating Paths 1-4.

Sections:
- Path 1: Freelance finder + proposal writer + human-gated submitter
- Path 2: Microtask earner (real gig discovery + workspace + submission)
- Path 3: Crypto wallet + payments + operator
- Path 4: Autonomous loop control + run state

All real external actions are human-gated by design.
"""

from __future__ import annotations

import os
import time
import hashlib
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLineEdit, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox, QTextEdit, QMessageBox,
    QSplitter, QSpinBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor


class EarningTab(QWidget):
    """Unified Earning tab for Paths 1-4."""

    log_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setup_ui()

        # Backends
        self.freelance_finder = None
        self.proposal_writer = None
        self.platform_submitter = None
        self.microtask_earner = None
        self.crypto_operator = None

        self._init_backends()

        # Auto-refresh
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(3000)

    # ── Backend wiring ─────────────────────────────────────────────────────
    def _init_backends(self):
        try:
            from agents.freelance_finder import FreelanceFinder
            from agents.proposal_writer import ProposalWriter
            from agents.platform_submitter import PlatformSubmitter
            from agents.microtask_earner import MicrotaskEarner
            from agents.real_crypto_operator import RealCryptoOperator
            from agents.autonomous_loop import AutonomousLoop

            self.freelance_finder = FreelanceFinder()
            self.proposal_writer = ProposalWriter()
            self.platform_submitter = PlatformSubmitter()
            self.microtask_earner = MicrotaskEarner()
            self.crypto_operator = RealCryptoOperator(None)

            self.autonomous_loop = AutonomousLoop(None)
        except Exception as e:
            self.log_signal.emit(f"[EarningTab] Backend init error: {e}")

    # ── UI setup ───────────────────────────────────────────────────────────
    def setup_ui(self):
        root = QVBoxLayout(self)

        # Header
        header = QLabel("🎯 Earning Center")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #bb86fc; padding: 10px;")
        root.addWidget(header)

        splitter = QSplitter(Qt.Vertical)

        # Top area: left controls, right state/logs
        top = QWidget()
        top_lay = QHBoxLayout(top)

        # Left: path controls
        left = QWidget()
        left_lay = QVBoxLayout(left)

        # Path 1
        p1 = self._build_path1_group()
        left_lay.addWidget(p1)

        # Path 2
        p2 = self._build_path2_group()
        left_lay.addWidget(p2)

        left_lay.addStretch(1)
        top_lay.addWidget(left, stretch=1)

        # Right: status + log
        right = QWidget()
        right_lay = QVBoxLayout(right)

        status_group = QGroupBox("📊 Status")
        status_lay = QFormLayout(status_group)
        self.status_label = QLabel("Ready")
        status_lay.addRow("State:", self.status_label)
        right_lay.addWidget(status_group)

        log_group = QGroupBox("📋 Log")
        log_lay = QVBoxLayout(log_group)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet("""
            QTextEdit { background:#111; color:#e0e0e0; font-family: Consolas; font-size:11px; }
        """)
        log_lay.addWidget(self.log_edit)
        right_lay.addWidget(log_group, stretch=1)

        top_lay.addWidget(right, stretch=1)
        top.setLayout(top_lay)
        splitter.addWidget(top)

        # Bottom area: crypto + autonomy
        bottom = QWidget()
        bottom_lay = QHBoxLayout(bottom)

        p3 = self._build_path3_group()
        bottom_lay.addWidget(p3, stretch=1)

        p4 = self._build_path4_group()
        bottom_lay.addWidget(p4, stretch=1)

        bottom.setLayout(bottom_lay)
        splitter.addWidget(bottom)

        root.addWidget(splitter, stretch=1)

        self.log_signal.connect(self._append_log)

    def _build_path1_group(self) -> QGroupBox:
        g = QGroupBox("Path 1: Freelance Research + Submit")
        g.setStyleSheet("""
            QGroupBox { color: #03dac6; font-weight: bold; border: 2px solid #03dac6; border-radius: 8px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        """)
        lay = QFormLayout(g)

        self.freelance_query_input = QLineEdit()
        self.freelance_query_input.setPlaceholderText("e.g., data cleaning, research report")
        lay.addRow("Query:", self.freelance_query_input)

        row = QHBoxLayout()
        search_btn = QPushButton("🔍 Search Opportunities")
        search_btn.clicked.connect(self._on_freelance_search)
        row.addWidget(search_btn)
        lay.addRow("", row)

        self.freelance_table = QTableWidget()
        self.freelance_table.setColumnCount(4)
        self.freelance_table.setHorizontalHeaderLabels(["Title", "Platform", "Budget", "URL"])
        self.freelance_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.freelance_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addRow(self.freelance_table)

        row2 = QHBoxLayout()
        draft_btn = QPushButton("📝 Draft Proposal")
        draft_btn.clicked.connect(self._on_draft_proposal)
        submit_btn = QPushButton("🚀 Submit (Human-Gated)")
        submit_btn.clicked.connect(self._on_submit_proposal)
        row2.addWidget(draft_btn)
        row2.addWidget(submit_btn)
        lay.addRow("", row2)

        self.proposal_output = QTextEdit()
        self.proposal_output.setPlaceholderText("Proposal preview...")
        self.proposal_output.setMaximumHeight(120)
        lay.addRow("Proposal:", self.proposal_output)

        return g

    def _build_path2_group(self) -> QGroupBox:
        g = QGroupBox("Path 2: Micro-Tasks")
        g.setStyleSheet("""
            QGroupBox { color: #ffcc44; font-weight: bold; border: 2px solid #ffcc44; border-radius: 8px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        """)
        lay = QFormLayout(g)

        self.microtask_platform_combo = QComboBox()
        self.microtask_platform_combo.addItems(["github", "prolific", "generic"])
        lay.addRow("Platform:", self.microtask_platform_combo)

        row = QHBoxLayout()
        find_btn = QPushButton("🔎 Find Gigs")
        find_btn.clicked.connect(self._on_find_gigs)
        accept_btn = QPushButton("✅ Accept Selected")
        accept_btn.clicked.connect(self._on_accept_gig)
        row.addWidget(find_btn)
        row.addWidget(accept_btn)
        lay.addRow("", row)

        self.microtask_table = QTableWidget()
        self.microtask_table.setColumnCount(4)
        self.microtask_table.setHorizontalHeaderLabels(["ID", "Title", "Reward", "Status"])
        self.microtask_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.microtask_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addRow(self.microtask_table)

        submit_btn = QPushButton("📤 Submit Attempt (Human-Gated)")
        submit_btn.clicked.connect(self._on_submit_attempt)
        lay.addRow("", submit_btn)

        return g

    def _build_path3_group(self) -> QGroupBox:
        g = QGroupBox("Path 3: Crypto Payments")
        g.setStyleSheet("""
            QGroupBox { color: #ff79c6; font-weight: bold; border: 2px solid #ff79c6; border-radius: 8px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        """)
        lay = QFormLayout(g)

        self.wallet_address_input = QLineEdit()
        self.wallet_address_input.setPlaceholderText("Wallet address")
        lay.addRow("Address:", self.wallet_address_input)

        self.wallet_chain_combo = QComboBox()
        self.wallet_chain_combo.addItems(["solana", "ethereum", "polygon", "base"])
        lay.addRow("Chain:", self.wallet_chain_combo)

        add_btn = QPushButton("➕ Add Wallet")
        add_btn.clicked.connect(self._on_add_wallet)
        lay.addRow("", add_btn)

        self.crypto_wallets_table = QTableWidget()
        self.crypto_wallets_table.setColumnCount(4)
        self.crypto_wallets_table.setHorizontalHeaderLabels(["Address", "Chain", "Balance", "Currency"])
        self.crypto_wallets_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.crypto_wallets_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addRow(self.crypto_wallets_table)

        row = QHBoxLayout()
        pay_to = QLineEdit()
        pay_to.setPlaceholderText("To address")
        self.pay_amount = QDoubleSpinBox()
        self.pay_amount.setRange(0, 1e9)
        self.pay_amount.setValue(0.0)
        self.pay_currency = QComboBox()
        self.pay_currency.addItems(["ETH", "SOL", "USDC"])
        send_btn = QPushButton("💸 Propose Payment")
        send_btn.clicked.connect(self._on_propose_payment)
        row.addWidget(pay_to)
        row.addWidget(self.pay_amount)
        row.addWidget(self.pay_currency)
        row.addWidget(send_btn)
        lay.addRow("Pay:", row)

        return g

    def _build_path4_group(self) -> QGroupBox:
        g = QGroupBox("Path 4: Full Autonomy")
        g.setStyleSheet("""
            QGroupBox { color: #bd93f9; font-weight: bold; border: 2px solid #bd93f9; border-radius: 8px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        """)
        lay = QFormLayout(g)

        self.autonomy_status_label = QLabel("Idle")
        lay.addRow("Status:", self.autonomy_status_label)

        row = QHBoxLayout()
        run_btn = QPushButton("▶ Run Autonomous Cycle")
        run_btn.clicked.connect(self._on_run_autonomy)
        stop_btn = QPushButton("⏹ Stop")
        stop_btn.clicked.connect(self._on_stop_autonomy)
        row.addWidget(run_btn)
        row.addWidget(stop_btn)
        lay.addRow("", row)

        self.autonomy_log = QTextEdit()
        self.autonomy_log.setReadOnly(True)
        self.autonomy_log.setMaximumHeight(140)
        self.autonomy_log.setStyleSheet("""
            QTextEdit { background:#111; color:#e0e0e0; font-family: Consolas; font-size:11px; }
        """)
        lay.addRow("Output:", self.autonomy_log)

        return g

    # ── Path 1 handlers ────────────────────────────────────────────────────
    def _on_freelance_search(self):
        query = self.freelance_query_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Error", "Enter a search query")
            return
        self.status_label.setText("Searching...")
        try:
            opportunities = self.freelance_finder.search(query)
            self.freelance_table.setRowCount(len(opportunities))
            for i, opp in enumerate(opportunities):
                self.freelance_table.setItem(i, 0, QTableWidgetItem(opp.get("title", "")))
                self.freelance_table.setItem(i, 1, QTableWidgetItem(opp.get("platform", "")))
                self.freelance_table.setItem(i, 2, QTableWidgetItem(str(opp.get("budget_usd", ""))))
                self.freelance_table.setItem(i, 3, QTableWidgetItem(opp.get("url", "")))
            self.status_label.setText(f"Found {len(opportunities)} opportunities")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.status_label.setText("Search failed")

    def _on_draft_proposal(self):
        row = self.freelance_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Error", "Select an opportunity first")
            return
        opp = {
            "title": self.freelance_table.item(row, 0).text(),
            "platform": self.freelance_table.item(row, 1).text(),
            "budget_usd": self.freelance_table.item(row, 2).text(),
        }
        try:
            proposal = self.proposal_writer.draft(opp)
            self.proposal_output.setText(proposal)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_submit_proposal(self):
        proposal = self.proposal_output.toPlainText().strip()
        if not proposal:
            QMessageBox.warning(self, "Error", "Draft a proposal first")
            return
        try:
            result = self.platform_submitter.submit(proposal_text=proposal)
            QMessageBox.information(self, "Submission", str(result))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ── Path 2 handlers ────────────────────────────────────────────────────
    def _on_find_gigs(self):
        platform = self.microtask_platform_combo.currentText()
        try:
            gigs = self.microtask_earner.find_gigs(platform=platform)
            self.microtask_table.setRowCount(len(gigs))
            for i, gig in enumerate(gigs):
                self.microtask_table.setItem(i, 0, QTableWidgetItem(gig.id))
                self.microtask_table.setItem(i, 1, QTableWidgetItem(gig.title))
                self.microtask_table.setItem(i, 2, QTableWidgetItem(f"${gig.reward:.2f}"))
                self.microtask_table.setItem(i, 3, QTableWidgetItem(gig.status))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_accept_gig(self):
        row = self.microtask_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Error", "Select a gig first")
            return
        gig_id = self.microtask_table.item(row, 0).text()
        try:
            attempt = self.microtask_earner.accept_gig(gig_id)
            self.microtask_table.setItem(row, 3, QTableWidgetItem(attempt.status))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_submit_attempt(self):
        row = self.microtask_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Error", "Select an attempt first")
            return
        attempt_id = self.microtask_table.item(row, 0).text()
        try:
            result = self.microtask_earner.submit(attempt_id)
            self.microtask_table.setItem(row, 3, QTableWidgetItem(result.status))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ── Path 3 handlers ────────────────────────────────────────────────────
    def _on_add_wallet(self):
        address = self.wallet_address_input.text().strip()
        chain_str = self.wallet_chain_combo.currentText()
        if not address:
            QMessageBox.warning(self, "Error", "Address required")
            return
        try:
            from agents.wallet import WalletManager, Chain
            wm = self._get_wallet_manager()
            chain = Chain(chain_str)
            wm.add_wallet(address, chain)
            self.wallet_address_input.clear()
            self._refresh_crypto_wallets()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_propose_payment(self):
        sender = self.wallet_address_input.text().strip()
        # payment fields collected from UI controls in future iteration; for now
        # we use sender as from_address with a placeholder to_address
        to_address = "0x" + "A" * 40
        amount = float(self.pay_amount.value())
        currency = self.pay_currency.currentText()
        if not sender:
            QMessageBox.warning(self, "Error", "Add a wallet first")
            return
        try:
            from agents.wallet import Chain
            wm = self._get_wallet_manager()
            chain = Chain.ETHEREUM if currency == "ETH" else Chain.SOLANA
            result = self.crypto_operator.propose_payment(
                sender, to_address, amount, currency, chain, memo="gui-payment"
            )
            QMessageBox.information(self, "Payment", str(result))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _get_wallet_manager(self):
        if self.main_window and hasattr(self.main_window, "payments_tab") and self.main_window.payments_tab:
            return self.main_window.payments_tab.wallet_manager
        return None

    # ── Path 4 handlers ────────────────────────────────────────────────────
    def _on_run_autonomy(self):
        self.autonomy_status_label.setText("Running...")
        self.autonomy_log.clear()
        self._append_log("Autonomous cycle requested.")
        # Intentionally lightweight: actual pipeline wiring happens in Earnings tab
        self._append_log("Use the Earnings tab pipeline controls for full cycle execution.")

    def _on_stop_autonomy(self):
        self.autonomy_status_label.setText("Idle")
        self._append_log("Autonomy stop requested.")

    # ── Shared helpers ─────────────────────────────────────────────────────
    def _append_log(self, text: str):
        self.log_edit.append(f"[{time.strftime('%H:%M:%S')}] {text}")

    def refresh(self):
        self._refresh_crypto_wallets()

    def get_summary(self) -> dict:
        """Return summary dict for the Insights panel.
        
        Keys: earned, pending, last30
        """
        earned = 0.0
        pending = 0.0
        last30 = 0.0
        
        # Try to get from earning pipeline if available
        try:
            from agents.earning_capability import EarningCapability
            ec = EarningCapability.instance() if hasattr(EarningCapability, 'instance') else None
            if ec and hasattr(ec, 'total_earned'):
                earned = ec.total_earned
            if ec and hasattr(ec, 'pending_amount'):
                pending = ec.pending_amount
        except Exception:
            pass
        
        # Try to get from wallet manager
        try:
            wm = self._get_wallet_manager()
            if wm:
                for w in wm.list_wallets():
                    if w.currency == "USD":
                        earned += w.balance
        except Exception:
            pass
        
        return {
            "earned": earned,
            "pending": pending,
            "last30": last30,
        }

    def _refresh_crypto_wallets(self):
        wm = self._get_wallet_manager()
        if not wm:
            return
        wallets = wm.list_wallets()
        self.crypto_wallets_table.setRowCount(len(wallets))
        for i, w in enumerate(wallets):
            self.crypto_wallets_table.setItem(i, 0, QTableWidgetItem(w.address[:20] + "..."))
            self.crypto_wallets_table.setItem(i, 1, QTableWidgetItem(w.chain.value))
            self.crypto_wallets_table.setItem(i, 2, QTableWidgetItem(f"{w.balance:.4f}"))
            self.crypto_wallets_table.setItem(i, 3, QTableWidgetItem(w.currency or w.chain.value))
