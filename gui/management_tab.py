"""
gui/management_tab.py — Management Control Center for the dual-brain architecture.

Administrative-only controls. Brain start/stop/restart and model selection
live exclusively in the Providers & GPU tab — this tab no longer duplicates
them (v2.1 fix: Management was sharing Providers_GPU's brain controls).

Sections:
  1. Earnings Pipeline        — run cycle, status, recent outcomes
  2. Research                 — folder selection, force rescan
  3. Gig Proposals (Upwork)   — review gate + human-confirmed submit
  4. Payout Verification      — verify then mark paid
  5. System Actions           — force self-improvement, clear cache
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox, QGridLayout, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QListWidget, QWidget, QMessageBox,
)


class ManagementTab(QWidget):
    """Management Control Center — administrative-only edition.
    
    Emits signals that the main window connects to:
      - request_run_cycle()
      - request_force_improve()
      - request_force_rescan()
      - request_select_research_folder()
      - request_review_proposal(job_id, job_desc, draft)
      - request_submit_proposal(job_id, job_desc, draft)
      - request_verify_paid(opp_id, amount, wallet, ref)
    """
    
    request_run_cycle = Signal()
    request_force_improve = Signal()
    request_force_rescan = Signal()
    request_select_research_folder = Signal()
    request_review_proposal = Signal(str, str, str)  # job_id, job_desc, draft
    request_submit_proposal = Signal(str, str, str)  # job_id, job_desc, draft
    request_verify_paid = Signal(str, str, str, str)  # opp_id, amount, wallet, ref

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pipeline_status = "Idle"
        self._research_folder = ""
        self.setup_ui()

    # ── UI ──────────────────────────────────────────────────────────────────
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("🎛️ Management Control Center")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setStyleSheet("color: #ffb300;")
        layout.addWidget(title)

        # ── Section 1: Earnings Pipeline ──────────────────────────────────
        pipeline_group = QGroupBox("Earnings Pipeline")
        pipeline_group.setStyleSheet("""
            QGroupBox {
                background: #1a1a1a;
                border: 2px solid #00ff88;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
            }
        """)
        pipeline_layout = QVBoxLayout(pipeline_group)

        pipe_ctrl = QHBoxLayout()
        run_cycle_btn = QPushButton("▶ Run Full Cycle")
        run_cycle_btn.setStyleSheet("background: #1a3a1a; color: #00ff88; font-weight: bold; padding: 8px;")
        run_cycle_btn.clicked.connect(self.request_run_cycle.emit)
        pipe_ctrl.addWidget(run_cycle_btn)

        self.pipeline_status_label = QLabel("Status: Idle")
        self.pipeline_status_label.setStyleSheet("color: #888; font-size: 11px;")
        pipe_ctrl.addWidget(self.pipeline_status_label, 1)

        pipeline_layout.addLayout(pipe_ctrl)

        # Recent outcomes
        pipeline_layout.addWidget(QLabel("Recent Outcomes:"))
        self.outcomes_list = QListWidget()
        self.outcomes_list.setMaximumHeight(100)
        pipeline_layout.addWidget(self.outcomes_list)

        layout.addWidget(pipeline_group)

        # ── Section 2: Research ───────────────────────────────────────────
        research_group = QGroupBox("Research")
        research_group.setStyleSheet("""
            QGroupBox {
                background: #1a1a1a;
                border: 2px solid #aa88ff;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
            }
        """)
        research_layout = QHBoxLayout(research_group)

        self.research_folder_label = QLabel("Research folder: not set")
        self.research_folder_label.setStyleSheet("color: #888; font-size: 11px;")
        research_layout.addWidget(self.research_folder_label, 1)

        select_folder_btn = QPushButton("📁 Select Folder")
        select_folder_btn.clicked.connect(self.request_select_research_folder.emit)
        research_layout.addWidget(select_folder_btn)

        force_rescan_btn = QPushButton("🔄 Force Re-scan")
        force_rescan_btn.clicked.connect(self.request_force_rescan.emit)
        research_layout.addWidget(force_rescan_btn)

        layout.addWidget(research_group)

        # ── Section 3: Gig Proposals (Upwork) ─────────────────────────────
        prop_group = QGroupBox("Gig Proposals (Upwork)")
        prop_group.setStyleSheet("""
            QGroupBox {
                background: #1a1a1a;
                border: 2px solid #ffaa44;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
            }
        """)
        prop_layout = QGridLayout(prop_group)
        prop_layout.setSpacing(8)

        self.proposal_job_id = QLineEdit()
        self.proposal_job_id.setPlaceholderText("Upwork job_id (e.g. ~01abcd1234)")
        prop_layout.addWidget(self.proposal_job_id, 0, 0, 1, 2)

        self.proposal_job_desc = QPlainTextEdit()
        self.proposal_job_desc.setPlaceholderText(
            "Paste the job description / stated requirements here.")
        self.proposal_job_desc.setMaximumHeight(60)
        prop_layout.addWidget(self.proposal_job_desc, 1, 0, 1, 2)

        self.proposal_draft = QPlainTextEdit()
        self.proposal_draft.setPlaceholderText(
            "Paste/load the cover letter draft. It is reviewed before submission.")
        self.proposal_draft.setMaximumHeight(80)
        prop_layout.addWidget(self.proposal_draft, 2, 0, 1, 2)

        review_btn = QPushButton("🔍 Review Draft")
        review_btn.clicked.connect(self._on_review_proposal)
        prop_layout.addWidget(review_btn, 3, 0)

        submit_btn = QPushButton("📨 Submit (review + confirm)")
        submit_btn.clicked.connect(self._on_submit_proposal)
        prop_layout.addWidget(submit_btn, 3, 1)

        self.proposal_status = QLabel("Proposal: idle")
        self.proposal_status.setStyleSheet("font-size: 11px; color: #888;")
        prop_layout.addWidget(self.proposal_status, 4, 0, 1, 2)

        self.proposals_list = QListWidget()
        self.proposals_list.setMaximumHeight(80)
        prop_layout.addWidget(self.proposals_list, 5, 0, 1, 2)

        layout.addWidget(prop_group)

        # ── Section 4: Payout Verification ────────────────────────────────
        pay_group = QGroupBox("Verify Payout")
        pay_group.setStyleSheet("""
            QGroupBox {
                background: #1a1a1a;
                border: 2px solid #ff8844;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
            }
        """)
        pay_layout = QGridLayout(pay_group)
        pay_layout.setSpacing(8)

        self.pay_opp_id = QLineEdit()
        self.pay_opp_id.setPlaceholderText("Opportunity id (e.g. J3)")
        pay_layout.addWidget(self.pay_opp_id, 0, 0)

        self.pay_amount = QLineEdit()
        self.pay_amount.setPlaceholderText("Expected USD (e.g. 250)")
        pay_layout.addWidget(self.pay_amount, 0, 1)

        self.pay_wallet = QLineEdit()
        self.pay_wallet.setPlaceholderText("Wallet name (crypto) or leave blank")
        pay_layout.addWidget(self.pay_wallet, 1, 0)

        self.pay_ref = QLineEdit()
        self.pay_ref.setPlaceholderText("Txn reference (manual attest) or blank")
        pay_layout.addWidget(self.pay_ref, 1, 1)

        verify_pay_btn = QPushButton("✅ Mark Paid (verify first)")
        verify_pay_btn.clicked.connect(self._on_verify_paid)
        pay_layout.addWidget(verify_pay_btn, 2, 0, 1, 2)

        self.pay_status = QLabel("Payout: idle")
        self.pay_status.setStyleSheet("font-size: 11px; color: #888;")
        pay_layout.addWidget(self.pay_status, 3, 0, 1, 2)

        layout.addWidget(pay_group)

        # ── Section 5: System Actions ─────────────────────────────────────
        system_group = QGroupBox("System Actions")
        system_group.setStyleSheet("""
            QGroupBox {
                background: #1a1a1a;
                border: 2px solid #888;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
            }
        """)
        system_layout = QGridLayout(system_group)
        system_layout.setSpacing(8)

        force_improve_btn = QPushButton("⚡ Force Self-Improvement")
        force_improve_btn.clicked.connect(self.request_force_improve.emit)
        system_layout.addWidget(force_improve_btn, 0, 0)

        clear_cache_btn = QPushButton("🗑 Clear File Cache")
        clear_cache_btn.clicked.connect(self._on_clear_cache)
        system_layout.addWidget(clear_cache_btn, 0, 1)

        layout.addWidget(system_group)

        layout.addStretch()

    # ── Public API (called by main window) ──────────────────────────────────

    def set_pipeline_status(self, status: str):
        """Update the pipeline status label."""
        self._pipeline_status = status
        self.pipeline_status_label.setText(f"Status: {status}")

    def add_outcome(self, text: str):
        """Add an entry to the recent outcomes list."""
        self.outcomes_list.addItem(text)
        # Keep only last 20 items
        while self.outcomes_list.count() > 20:
            self.outcomes_list.takeItem(0)

    def set_research_folder(self, folder: str):
        """Update the research folder display."""
        self._research_folder = folder
        self.research_folder_label.setText(f"Research folder: {folder}")

    def set_proposal_status(self, text: str):
        """Update the proposal status label."""
        self.proposal_status.setText(text)

    def add_proposal(self, text: str):
        """Add an entry to the proposals list."""
        self.proposals_list.addItem(text)

    def set_pay_status(self, text: str):
        """Update the payout status label."""
        self.pay_status.setText(text)

    # ── Private slots ───────────────────────────────────────────────────────

    def _on_review_proposal(self):
        job_id = self.proposal_job_id.text().strip()
        job_desc = self.proposal_job_desc.toPlainText().strip()
        draft = self.proposal_draft.toPlainText().strip()
        if not job_id or not draft:
            QMessageBox.warning(self, "Missing Data", "Please enter a job_id and cover letter draft.")
            return
        self.request_review_proposal.emit(job_id, job_desc, draft)

    def _on_submit_proposal(self):
        job_id = self.proposal_job_id.text().strip()
        job_desc = self.proposal_job_desc.toPlainText().strip()
        draft = self.proposal_draft.toPlainText().strip()
        if not job_id or not draft:
            QMessageBox.warning(self, "Missing Data", "Please enter a job_id and cover letter draft.")
            return
        self.request_submit_proposal.emit(job_id, job_desc, draft)

    def _on_verify_paid(self):
        opp_id = self.pay_opp_id.text().strip()
        amount = self.pay_amount.text().strip()
        wallet = self.pay_wallet.text().strip()
        ref = self.pay_ref.text().strip()
        if not opp_id or not amount:
            QMessageBox.warning(self, "Missing Data", "Please enter an opportunity id and amount.")
            return
        self.request_verify_paid.emit(opp_id, amount, wallet, ref)

    def _on_clear_cache(self):
        reply = QMessageBox.question(
            self, "Clear Cache",
            "Delete all cached file contents?",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            # Signal to main window to clear cache
            pass
