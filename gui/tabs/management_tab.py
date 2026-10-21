"""
gui/management_tab.py — Management Control Center for the dual-brain architecture.

Administrative-only controls. Brain start/stop/restart and model selection
live exclusively in the Providers & GPU tab — this tab no longer duplicates
them (v2.1 fix: Management was sharing Providers_GPU's brain controls).

Sections:
  1. Earnings Pipeline        — run cycle, status, recent outcomes
  2. Earning Goals            — create/pause/delete goals; verified earning
                                events credit them automatically (ARCH-ENG-244)
  3. Research                 — folder selection, force rescan
  4. Gig Proposals (Upwork)   — review gate + human-confirmed submit
  5. Payout Verification      — verify then mark paid
  6. System Actions           — force self-improvement, clear cache
"""

from __future__ import annotations

import os

from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox, QGridLayout, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QPlainTextEdit, QListWidget, QWidget, QMessageBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QComboBox,
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
      - request_reconcile_paid(opp_id, evidence_id, method, note)
    """
    
    request_run_cycle = Signal()
    request_force_improve = Signal()
    request_force_rescan = Signal()
    request_select_research_folder = Signal()
    request_review_proposal = Signal(str, str, str)  # job_id, job_desc, draft
    request_submit_proposal = Signal(str, str, str)  # job_id, job_desc, draft
    request_verify_paid = Signal(str, str, str, str)  # opp_id, amount, wallet, ref
    # ARCH-ENG-287 (Z-01): opp_id, evidence_id (blank = latest unresolved),
    # independent reconciliation method, note/reference.
    request_reconcile_paid = Signal(str, str, str, str)

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

        # ── Persona Names ────────────────────────────────────────────────
        names_group = QGroupBox("Persona Names")
        names_layout = QGridLayout(names_group)
        names_layout.setSpacing(8)

        # ── Persona Names (per enabled device — N-brain) ─────────────────
        # One name field per enabled runtime slot, built from the speaker
        # registry. Slots 0/1 persist to the legacy BIG_BRAIN_NAME /
        # SMALL_BRAIN_NAME keys; slots 2+ persist to BRAIN_SLOT{n}_NAME. Each
        # field shows the device it runs on and its tier. No two enabled brains
        # share a name (the registry enforces uniqueness).
        self._persona_name_edits = []  # list of (slot, env_key, QLineEdit)
        row = 0
        try:
            from agents.runtime.dual_brain import DualBrainRuntime
            from agents.runtime import device_registry as dr
            from agents.cognition.speaker_registry import build_speakers
            runtime = DualBrainRuntime.from_env()
            placements = dr.brain_placements(
                dr.resolve_assignments(dr.detect_devices(include_cpu=True),
                                       dr.load_policy()))
            speakers = build_speakers(placements)
        except Exception:
            speakers = []
        # Always show at least the two primary personas even if detection is
        # unavailable, so the operator can still name Edward/Jacob.
        if not speakers:
            from agents.cognition.speaker_registry import Speaker
            speakers = [
                Speaker(slot=0, key="big_brain", name="Edward Hurst", tier="big",
                        is_primary_big=True),
                Speaker(slot=1, key="small_brain", name="Jacob Stanley",
                        tier="small", is_primary_small=True),
            ]
        for spk in speakers:
            tier_label = "Big Brain" if spk.is_big else "Small Brain"
            dev = spk.device_label or ("CPU / System RAM" if not spk.is_big else "GPU")
            label = f"{tier_label} #{spk.slot} · {dev}:"
            names_layout.addWidget(QLabel(label), row, 0)
            env_key = ("BIG_BRAIN_NAME" if (spk.slot == 0 and spk.is_big)
                       else "SMALL_BRAIN_NAME" if (spk.slot == 1 and spk.is_small)
                       else f"BRAIN_SLOT{spk.slot}_NAME")
            edit = QLineEdit(os.getenv(env_key, "").strip())
            edit.setPlaceholderText(spk.name)
            edit.editingFinished.connect(
                lambda k=env_key, w=edit: self._persist_persona_name(k, w))
            names_layout.addWidget(edit, row, 1)
            self._persona_name_edits.append((spk.slot, env_key, edit))
            row += 1

        self.persona_name_status = QLabel("Names apply to new messages immediately.")
        self.persona_name_status.setStyleSheet("font-size: 11px; color: #888;")
        names_layout.addWidget(self.persona_name_status, row, 0, 1, 2)
        layout.addWidget(names_group)

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

        self.pipeline_status_label = QLabel("Status: —")
        self.pipeline_status_label.setStyleSheet("color: #888; font-size: 11px;")
        pipe_ctrl.addWidget(self.pipeline_status_label, 1)

        pipeline_layout.addLayout(pipe_ctrl)

        # Recent outcomes
        pipeline_layout.addWidget(QLabel("Recent Outcomes:"))
        self.outcomes_list = QListWidget()
        self.outcomes_list.setMaximumHeight(100)
        pipeline_layout.addWidget(self.outcomes_list)

        layout.addWidget(pipeline_group)

        # ── Section 2: Earning Goals (ARCH-ENG-244) ───────────────────────
        # The operator surface for the (now live) GoalTracker: create,
        # pause/resume, delete and view goals. Verified earning events
        # credit goals automatically via the tracker's binding (an explicit
        # details.goal_id, or the platforms declared on the goal here).
        goals_group = QGroupBox("Earning Goals")
        goals_group.setStyleSheet("""
            QGroupBox {
                background: #1a1a1a;
                border: 2px solid #44aaff;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
            }
        """)
        goals_layout = QVBoxLayout(goals_group)
        goals_layout.setSpacing(8)

        self.goals_table = QTableWidget(0, 6)
        self.goals_table.setHorizontalHeaderLabels(
            ["Title", "Path", "Current $", "Target $", "Progress", "Status"])
        self.goals_table.horizontalHeader().setStretchLastSection(True)
        self.goals_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.goals_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.goals_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.goals_table.verticalHeader().setVisible(False)
        self.goals_table.setMaximumHeight(140)
        goals_layout.addWidget(self.goals_table)

        goal_form = QGridLayout()
        goal_form.setSpacing(8)
        self.goal_title_edit = QLineEdit()
        self.goal_title_edit.setPlaceholderText(
            "Goal title (e.g. 'Earn $100 on Upwork this week')")
        goal_form.addWidget(self.goal_title_edit, 0, 0, 1, 3)

        goal_form.addWidget(QLabel("Path:"), 1, 0)
        self.goal_path_combo = QComboBox()
        try:
            from agents.earning.goal_system import GoalPath
            self.goal_path_combo.addItems([p.value for p in GoalPath])
        except Exception:
            self.goal_path_combo.addItems(
                ["freelance", "microtask", "crypto", "bounty", "trading",
                 "content", "other"])
        goal_form.addWidget(self.goal_path_combo, 1, 1)

        self.goal_target_edit = QLineEdit()
        self.goal_target_edit.setPlaceholderText("Target (USD, e.g. 100)")
        goal_form.addWidget(self.goal_target_edit, 1, 2)

        self.goal_platforms_edit = QLineEdit()
        self.goal_platforms_edit.setPlaceholderText(
            "Platforms that count toward this goal (comma-sep, e.g. upwork, "
            "prolific). Only VERIFIED payouts credit a goal — the tracker "
            "never credits an unverified dollar.")
        goal_form.addWidget(self.goal_platforms_edit, 2, 0, 1, 3)
        goals_layout.addLayout(goal_form)

        goal_btns = QHBoxLayout()
        create_goal_btn = QPushButton("➕ Create Goal")
        create_goal_btn.clicked.connect(self._on_goal_create)
        goal_btns.addWidget(create_goal_btn)

        goal_pause_btn = QPushButton("⏯ Pause / Resume")
        goal_pause_btn.clicked.connect(self._on_goal_pause_resume)
        goal_btns.addWidget(goal_pause_btn)

        goal_delete_btn = QPushButton("🗑 Delete")
        goal_delete_btn.clicked.connect(self._on_goal_delete)
        goal_btns.addWidget(goal_delete_btn)

        goal_refresh_btn = QPushButton("🔄 Refresh")
        goal_refresh_btn.clicked.connect(self.refresh_goals)
        goal_btns.addWidget(goal_refresh_btn)
        goals_layout.addLayout(goal_btns)

        self.goals_status = QLabel("Goals: —")
        self.goals_status.setStyleSheet("font-size: 11px; color: #888;")
        goals_layout.addWidget(self.goals_status)

        layout.addWidget(goals_group)
        # Initial populate, deferred so construction never blocks on I/O
        # (tests swap the tracker singleton before this timer fires).
        QTimer.singleShot(0, self.refresh_goals)
        # And follow the app's polling convention (Insights refreshes every
        # 4 s): a credit that lands while the operator is reading shows up
        # without a manual Refresh.
        self._goal_poll = QTimer(self)
        self._goal_poll.setInterval(20000)
        self._goal_poll.timeout.connect(self.refresh_goals)
        self._goal_poll.start()

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

        self.proposal_status = QLabel("Proposal: —")
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

        # ARCH-ENG-287 (Z-01): the only path that may promote a
        # non-affirmative payment record to independently verified. The method
        # list is the evidence policy's allow-list -- manual/local re-assertion
        # cannot reconcile, so it is deliberately not offered here.
        self.pay_evidence_id = QLineEdit()
        self.pay_evidence_id.setPlaceholderText(
            "Evidence id (blank = latest unresolved)")
        pay_layout.addWidget(self.pay_evidence_id, 3, 0)

        self.pay_reconcile_method = QComboBox()
        self.pay_reconcile_method.addItems([
            "external_reconciliation",
            "authenticated_api_response",
            "platform_transaction",
            "blockchain_transaction_receipt",
            "blockchain_balance_delta",
        ])
        pay_layout.addWidget(self.pay_reconcile_method, 3, 1)

        reconcile_pay_btn = QPushButton(
            "🔗 Reconcile Evidence (independent source)")
        reconcile_pay_btn.clicked.connect(self._on_reconcile_paid)
        pay_layout.addWidget(reconcile_pay_btn, 4, 0, 1, 2)

        self.pay_status = QLabel("Payout: —")
        self.pay_status.setStyleSheet("font-size: 11px; color: #888;")
        pay_layout.addWidget(self.pay_status, 5, 0, 1, 2)

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

    # ── Earning Goals (ARCH-ENG-244) ──────────────────────────────────────

    def _goal_tracker(self):
        """The goal tracker singleton, or None (the card degrades to a
        read-only table; a tracker failure must never break the tab)."""
        try:
            from agents.earning.goal_system import GoalTracker
            return GoalTracker.instance()
        except Exception:
            return None

    def refresh_goals(self):
        tracker = self._goal_tracker()
        if tracker is None:
            self.goals_status.setText("Goals: tracker unavailable")
            return
        keep_id = self._selected_goal_id()
        self.goals_table.setRowCount(0)
        for g in tracker.list_all():
            row = self.goals_table.rowCount()
            self.goals_table.insertRow(row)
            pct = (g.current_usd / g.target_usd * 100.0) if g.target_usd > 0 else 0.0
            values = [
                g.title, g.path, f"{g.current_usd:,.2f}",
                f"{g.target_usd:,.2f}", f"{pct:.1f}%", g.status,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.UserRole, g.id)
                self.goals_table.setItem(row, col, item)
        # Re-select the goal that was selected before the rebuild: a
        # pause/resume must not drop the operator's selection mid-review
        # (they would have to re-find their row between every toggle).
        if keep_id:
            for row in range(self.goals_table.rowCount()):
                item = self.goals_table.item(row, 0)
                if item is not None and item.data(Qt.UserRole) == keep_id:
                    self.goals_table.setCurrentCell(row, 0)
                    break
        s = tracker.summary()
        self.goals_status.setText(
            f"Goals: {s['active_goals']} active / {s['completed_goals']} "
            f"completed — earned ${s['total_earned']:,.2f} of "
            f"${s['total_target']:,.2f} ({s['overall_progress']:.1f}%). "
            f"Only VERIFIED payouts credit a goal.")

    def _selected_goal_id(self):
        row = self.goals_table.currentRow()
        if row < 0:
            return None
        item = self.goals_table.item(row, 0)
        return item.data(Qt.UserRole) if item is not None else None

    def _on_goal_create(self):
        tracker = self._goal_tracker()
        if tracker is None:
            return
        title = self.goal_title_edit.text().strip()
        if not title:
            QMessageBox.information(self, "Earning Goals",
                                    "A goal needs a title.")
            return
        try:
            target = abs(float(self.goal_target_edit.text().strip() or "0"))
        except ValueError:
            QMessageBox.information(self, "Earning Goals",
                                    "Target must be a number (USD).")
            return
        platforms = [p.strip() for p in
                     self.goal_platforms_edit.text().split(",") if p.strip()]
        metadata = {"platforms": platforms} if platforms else {}
        from agents.earning.goal_system import Goal
        goal = Goal(title=title, path=self.goal_path_combo.currentText(),
                    target_usd=target, metadata=metadata)
        tracker.create(goal)
        self.goal_title_edit.clear()
        self.goal_target_edit.clear()
        self.goal_platforms_edit.clear()
        self.goals_status.setText(
            f"Goal created ({goal.id[:8]}). Verified payouts on its declared "
            f"platforms credit it automatically; an event binding "
            f"(details.goal_id) routes a single goal instead.")
        self.refresh_goals()

    def _on_goal_pause_resume(self):
        tracker = self._goal_tracker()
        if tracker is None:
            return
        goal_id = self._selected_goal_id()
        if goal_id is None:
            QMessageBox.information(self, "Earning Goals",
                                    "Select a goal first.")
            return
        g = tracker.get(goal_id)
        if g is None:
            return
        from agents.earning.goal_system import GoalStatus
        if g.status == GoalStatus.ACTIVE.value:
            g.status = GoalStatus.PAUSED.value
        elif g.status == GoalStatus.PAUSED.value:
            g.status = GoalStatus.ACTIVE.value
        tracker.update(g)
        self.refresh_goals()

    def _on_goal_delete(self):
        tracker = self._goal_tracker()
        if tracker is None:
            return
        goal_id = self._selected_goal_id()
        if goal_id is None:
            QMessageBox.information(self, "Earning Goals",
                                    "Select a goal first.")
            return
        g = tracker.get(goal_id)
        if g is None:
            return
        ret = QMessageBox.question(
            self, "Delete goal",
            f"Delete goal '{g.title}' and all of its evidence?\n"
            f"This cannot be undone.")
        if ret != QMessageBox.Yes:
            return
        tracker.delete(goal_id)
        self.refresh_goals()

    def _persist_persona_name(self, key: str, widget: QLineEdit):
        """Persist a display name while retaining stable internal role keys."""
        value = widget.text().strip()
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
        try:
            from main import set_env_values
            set_env_values({key: value})
        except Exception:
            pass
        self.persona_name_status.setText(
            "Saved. New messages use the updated name."
            if value else "Cleared. The default persona name will be used.")

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

    def _on_reconcile_paid(self):
        """ARCH-ENG-287 (Z-01): request independent reconciliation.

        Deliberately no modal: the decision is asynchronous and its outcome is
        reported in `pay_status`/the log, so an offscreen or headless run is
        never blocked by a dialog.
        """
        opp_id = self.pay_opp_id.text().strip()
        evidence_id = self.pay_evidence_id.text().strip()
        method = self.pay_reconcile_method.currentText().strip()
        note = self.pay_ref.text().strip()
        if not opp_id:
            self.pay_status.setText("Reconcile: opportunity id required")
            return
        self.pay_status.setText(
            f"Reconcile: requested via {method} (awaiting external check)")
        self.request_reconcile_paid.emit(opp_id, evidence_id, method, note)

    def _on_clear_cache(self):
        reply = QMessageBox.question(
            self, "Clear Cache",
            "Delete all cached file contents?",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            # Signal to main window to clear cache
            pass
