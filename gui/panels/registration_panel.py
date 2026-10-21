"""gui/panels/registration_panel.py — Gated platform sign-up (Phase B).

The GUI trigger for `RegistrationService`. The operator reviews a proposed
registration and drives it entirely from here:

  - Enter the platform + signup URL (+ optional SKILL.md URL) and press
    **Propose** → fetches the playbook QUARANTINED, detects form fields, and
    enqueues a HIGH-TRUST `create_account` approval. Nothing is submitted.
  - Enter credentials into MASKED fields and press **Save to vault** → stored
    ENCRYPTED at rest (Fernet). Secrets are never shown, logged, or sent to a
    model. They exist in cleartext only in this widget's line edits until saved.
  - After the approval is Approved in the Approvals tab, press **Register** →
    reads the credentials from the vault and fills the form. Refuses unless the
    approval is recorded + APPROVED.

The agent never sees a password: it goes operator → masked field → encrypted
vault → browser form.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QPushButton, QLineEdit, QPlainTextEdit, QMessageBox,
)

logger = logging.getLogger("mrbot.gui.registration_panel")

from agents.safety.approval import (
    HumanApprovalQueue, ApprovalItem, ApprovalKind,
)


class RegistrationPanel(QWidget):
    """Operator-driven, approval-gated platform registration."""

    def __init__(self, parent: Optional[QWidget] = None,
                 service=None, vault=None, approval_queue=None):
        super().__init__(parent)
        self._service = service
        self._vault = vault
        self._queue = approval_queue or HumanApprovalQueue.instance()
        self._plan = None
        self._approval_id = None
        self._setup_ui()

    # ── lazy wiring (fail-closed if a dependency is missing) ─────────────────
    def _svc(self):
        if self._service is None:
            from agents.platforms.registration import RegistrationService
            self._service = RegistrationService(approval_queue=self._queue)
        return self._service

    def _vlt(self):
        if self._vault is None:
            from agents.platforms.credential_vault import CredentialVault
            self._vault = CredentialVault()
        return self._vault

    # ── UI ────────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # Target
        tgt = QGroupBox("1 · Target platform")
        tf = QFormLayout(tgt)
        self.platform_edit = QLineEdit()
        self.platform_edit.setPlaceholderText("e.g. ugig, prolific, moltbook")
        self.signup_edit = QLineEdit()
        self.signup_edit.setPlaceholderText("https://…/signup or /register")
        self.skill_edit = QLineEdit()
        self.skill_edit.setPlaceholderText("https://…/skill.md (optional)")
        tf.addRow("Platform", self.platform_edit)
        tf.addRow("Signup URL", self.signup_edit)
        tf.addRow("SKILL.md URL", self.skill_edit)
        root.addWidget(tgt)

        self.propose_btn = QPushButton("Propose (fetch playbook + request approval)")
        self.propose_btn.clicked.connect(self._on_propose)
        root.addWidget(self.propose_btn)

        # Plan preview
        prev = QGroupBox("2 · Review the plan (playbook is UNTRUSTED until approved)")
        pv = QVBoxLayout(prev)
        self.plan_view = QPlainTextEdit()
        self.plan_view.setReadOnly(True)
        self.plan_view.setPlaceholderText("Press Propose to fetch the platform playbook "
                                          "and detect the registration form fields.")
        pv.addWidget(self.plan_view)
        root.addWidget(prev)

        # Credentials (masked)
        cred = QGroupBox("3 · Credentials (encrypted at rest — never shown or logged)")
        cf = QFormLayout(cred)
        self.email_edit = QLineEdit()
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.fullname_edit = QLineEdit()
        cf.addRow("Email", self.email_edit)
        cf.addRow("Username", self.username_edit)
        cf.addRow("Password", self.password_edit)
        cf.addRow("Full name", self.fullname_edit)
        root.addWidget(cred)

        btn_row = QHBoxLayout()
        self.save_vault_btn = QPushButton("Save to encrypted vault")
        self.save_vault_btn.clicked.connect(self._on_save_vault)
        self.vault_status = QLabel("Vault: —")
        btn_row.addWidget(self.save_vault_btn)
        btn_row.addWidget(self.vault_status)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # Register (needs an approved approval)
        self.register_btn = QPushButton("Register (requires APPROVED approval)")
        self.register_btn.setEnabled(False)
        self.register_btn.clicked.connect(self._on_register)
        root.addWidget(self.register_btn)

        self.status = QLabel("Ready.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

    # ── actions ────────────────────────────────────────────────────────────────
    def _platform(self) -> str:
        return self.platform_edit.text().strip()

    def _on_propose(self):
        platform = self._platform()
        signup = self.signup_edit.text().strip()
        if not platform or not signup:
            QMessageBox.warning(self, "Missing", "Enter a platform name and signup URL.")
            return
        skill = self.skill_edit.text().strip() or None
        try:
            out = self._svc().propose(platform, signup, instruction_url=skill)
        except Exception as exc:
            self._fail(f"Propose failed: {exc}")
            return
        if not out.get("ok"):
            self._fail(out.get("reason", "propose failed"))
            return
        self._plan = out["plan"]
        self.plan_view.setPlainText(self._format_plan(self._plan))
        # Enqueue the HIGH-TRUST create_account approval for human review.
        self._enqueue_approval(platform, signup)
        self._refresh_vault_status()
        self.status.setText("Plan ready. Review it, save credentials, then approve "
                            "the request in the Approvals tab and press Register.")

    def _format_plan(self, plan) -> str:
        lines = [
            f"Platform: {plan.platform}",
            f"Signup:   {plan.signup_url}",
            f"Playbook: {plan.instruction_url or '(none)'} "
            f"[status={plan.instruction_status}, trusted={plan.instruction_trusted}]",
            "",
            "Detected fields: " + (", ".join(plan.detected_fields) or "(none detected)"),
            "",
            "Steps:",
        ]
        lines += [f"  {i+1}. {s}" for i, s in enumerate(plan.steps)]
        if plan.warnings:
            lines += ["", "Warnings:"] + [f"  • {w}" for w in plan.warnings]
        if plan.playbook_excerpt:
            lines += ["", "Playbook excerpt (UNTRUSTED — reference only):",
                      plan.playbook_excerpt[:1500]]
        return "\n".join(lines)

    def _enqueue_approval(self, platform: str, signup: str):
        try:
            item = self._queue.enqueue(ApprovalItem(
                kind=ApprovalKind.ACTION,
                title=f"Create account on {platform}",
                description=(f"Register a new account at {signup}. "
                             "HIGH-TRUST: review the plan and approve only if you "
                             "authorize account creation."),
                requested_by="registration_panel",
                details={"platform": platform, "signup_url": signup,
                         "detected_fields": list(self._plan.detected_fields)
                         if self._plan else []},
                payload={"action": "create_account", "platform": platform,
                         "signup_url": signup},
            ))
            self._approval_id = item.id
        except Exception as exc:
            self._fail(f"Could not enqueue approval: {exc}")

    def _on_save_vault(self):
        platform = self._platform()
        if not platform:
            QMessageBox.warning(self, "Missing", "Enter a platform name first.")
            return
        secrets = {}
        if self.email_edit.text().strip():
            secrets["email"] = self.email_edit.text().strip()
        if self.username_edit.text().strip():
            secrets["username"] = self.username_edit.text().strip()
        if self.password_edit.text():           # never strip a password
            secrets["password"] = self.password_edit.text()
        if self.fullname_edit.text().strip():
            secrets["full_name"] = self.fullname_edit.text().strip()
        if not secrets:
            QMessageBox.warning(self, "Nothing to save", "Enter at least one field.")
            return
        try:
            self._vlt().set_many(platform, secrets)
        except Exception as exc:
            self._fail(f"Vault save failed: {exc}")
            return
        # Clear the password field from the widget immediately after saving.
        self.password_edit.clear()
        self._refresh_vault_status()
        self.status.setText(f"Saved {len(secrets)} field(s) to the encrypted vault "
                            f"for {platform}. Password cleared from the form.")

    def _refresh_vault_status(self):
        platform = self._platform()
        try:
            if platform and self._vlt().has_platform(platform):
                fields = ", ".join(self._vlt().fields_for(platform))
                self.vault_status.setText(f"Vault: {platform} has [{fields}]")
                self.register_btn.setEnabled(True)
            else:
                self.vault_status.setText("Vault: no credentials for this platform")
                self.register_btn.setEnabled(False)
        except Exception as exc:
            self.vault_status.setText(f"Vault: unavailable ({exc})")
            self.register_btn.setEnabled(False)

    def _on_register(self):
        platform = self._platform()
        signup = self.signup_edit.text().strip()
        if not platform or not signup:
            QMessageBox.warning(self, "Missing", "Enter a platform name and signup URL.")
            return
        # Map vault field names to CSS selectors. These are best-effort defaults;
        # the operator can adjust after reviewing the real page.
        selectors = {
            "email": "input[type=email], input[name=email]",
            "username": "input[name=username], input[name=user]",
            "password": "input[type=password]",
            "full_name": "input[name=name], input[name=full_name]",
        }
        # Only include selectors for fields the vault actually has.
        have = set(self._vlt().fields_for(platform))
        selectors = {f: s for f, s in selectors.items() if f in have}
        if not selectors:
            self._fail("No vault fields map to a form selector.")
            return
        try:
            out = self._svc().register_with_vault(
                platform, signup, selectors, approval_id=self._approval_id)
        except Exception as exc:
            self._fail(f"Register failed: {exc}")
            return
        ok = bool(out.get("ok"))
        msg = out.get("reason") or out.get("note") or ""
        self.status.setText(("Registered: " if ok else "Registration refused: ") + msg)
        if not ok:
            QMessageBox.information(self, "Registration", msg or "refused")

    def _fail(self, message: str):
        self.status.setText(message)
        logger.warning("registration panel: %s", message)
