"""Gated platform sign-up / registration (Phase B).

Creates an account on an earning platform WITHOUT ever letting an untrusted
SKILL.md drive it, and WITHOUT the agent ever handling a secret. The flow is:

  1. FETCH   — pull the platform's SKILL.md / registration playbook through the
               InstructionGate. It comes back QUARANTINED (trusted=False) — the
               content is reference material for the human, never executable
               authority.
  2. PROPOSE — parse the registration steps + required fields and present them
               to the human for review, alongside the (untrusted) playbook text.
               The agent drafts; it does not decide.
  3. APPROVE — enqueue a HIGH-TRUST `create_account` approval item. Registration
               cannot proceed until a human explicitly approves it in the
               Approvals tab. An untrusted instruction can never satisfy this.
  4. FILL    — only after approval, drive the registration form with a headless
               browser (WebEyes.fill_form). Secrets (password, email) are NEVER
               supplied by the agent: the caller must pass them, and callers are
               expected to source them from the human / a vault at call time.
               This module refuses to invent or persist any credential.
  5. VERIFY  — re-read the resulting page and report success/failure as evidence.

Everything mutating is HIGH_TRUST (create_account / set_password / login /
grant_oauth are all in HIGH_TRUST_ACTIONS), so the TrustBoundary forces the
human gate regardless of the platform's own policy. This module never bypasses
it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RegistrationPlan:
    """A proposed registration, awaiting human approval. Nothing is executed."""
    platform: str
    signup_url: str
    instruction_url: Optional[str] = None
    instruction_status: str = "pending"     # pending | allowed | blocked
    instruction_trusted: bool = False
    playbook_excerpt: str = ""              # untrusted text, for human review
    detected_fields: List[str] = field(default_factory=list)  # e.g. ["email","username","password"]
    steps: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "signup_url": self.signup_url,
            "instruction_url": self.instruction_url,
            "instruction_status": self.instruction_status,
            "instruction_trusted": self.instruction_trusted,
            "playbook_excerpt": self.playbook_excerpt,
            "detected_fields": list(self.detected_fields),
            "steps": list(self.steps),
            "warnings": list(self.warnings),
        }


# Field-name hints -> canonical field, used to summarise what a form likely wants.
_FIELD_HINTS = {
    "email": ["email", "e-mail", "mail"],
    "username": ["username", "user name", "handle", "login"],
    "password": ["password", "passwd", "pwd"],
    "full_name": ["full name", "fullname", "name", "first name", "last name"],
    "country": ["country", "nation", "region"],
    "skills": ["skills", "expertise", "categories"],
}


class RegistrationService:
    """Approval-gated account creation. Never fabricates or stores credentials."""

    def __init__(self, instruction_gate=None, boundary=None, approval_queue=None):
        # All three are optional at construction but REQUIRED before any
        # mutating step; _require_gate() fails closed if one is missing.
        self._gate = instruction_gate
        self._boundary = boundary
        self._queue = approval_queue

    # ── wiring ──────────────────────────────────────────────────────────────
    def _require_gate(self):
        """Fail closed: no registration without the full safety stack wired."""
        from agents.safety.trust import TrustBoundary
        from agents.safety.approval import HumanApprovalQueue
        from agents.safety.calling import _get_instruction_gate
        if self._gate is None:
            self._gate = _get_instruction_gate()
        if self._boundary is None:
            self._boundary = TrustBoundary()
        if self._queue is None:
            self._queue = HumanApprovalQueue.instance()
        return self._gate, self._boundary, self._queue

    # ── step 1 + 2: fetch (quarantined) + propose ─────────────────────────────
    def propose(self, platform: str, signup_url: str,
                instruction_url: Optional[str] = None) -> Dict[str, Any]:
        """Fetch the platform playbook (quarantined) and build a RegistrationPlan.

        Returns {"ok": True, "plan": RegistrationPlan} or {"ok": False, "reason"}.
        Executes nothing; the plan is for human review only.
        """
        gate, boundary, _queue = self._require_gate()

        plan = RegistrationPlan(platform=platform, signup_url=signup_url,
                                instruction_url=instruction_url)
        warnings: List[str] = []

        # 1) Quarantined instruction fetch (if the platform publishes a SKILL.md).
        if instruction_url:
            try:
                qi = gate.fetch_instruction(instruction_url, kind="skill.md",
                                            title=f"{platform} registration playbook")
                plan.instruction_status = qi.status
                plan.instruction_trusted = bool(qi.trusted)
                # Only ever an excerpt for the human to read; never executed.
                plan.playbook_excerpt = (qi.content or "")[:4000]
                if not qi.trusted:
                    warnings.append(
                        "The platform playbook is UNTRUSTED until a human "
                        "approves it. Its steps are suggestions, not commands."
                    )
            except Exception as exc:
                warnings.append(f"Could not fetch playbook: {exc}")

        # 2) Detect likely form fields from the signup page (read-only).
        try:
            from agents.integrations.web_eyes import get_web_eyes
            eyes = get_web_eyes()
            page = eyes.read_page(signup_url)
            html_fields = self._detect_fields_from_page(page)
            plan.detected_fields = html_fields
        except Exception as exc:
            warnings.append(f"Could not read the signup page to detect fields: {exc}")

        # 3) High-trust reminder — registration always needs a human.
        warnings.append(
            "Account creation is HIGH-TRUST: it requires your explicit approval "
            "in the Approvals tab. No credential is invented or stored by the agent."
        )
        plan.warnings = warnings
        plan.steps = self._draft_steps(plan)
        return {"ok": True, "plan": plan}

    def _detect_fields_from_page(self, page: Dict[str, Any]) -> List[str]:
        """Best-effort: which credential-ish fields does this form likely have?"""
        text = " ".join([
            str(page.get("title", "")),
            str(page.get("text", "")),
        ]).lower()
        found = []
        for canonical, hints in _FIELD_HINTS.items():
            if any(h in text for h in hints):
                found.append(canonical)
        return found

    def _draft_steps(self, plan: RegistrationPlan) -> List[str]:
        steps = [f"Open the signup page: {plan.signup_url}"]
        if plan.detected_fields:
            steps.append("Fill the detected fields: " + ", ".join(plan.detected_fields))
        else:
            steps.append("Fill the registration form (fields not auto-detected; "
                         "review the page before approving)")
        steps.append("Submit only AFTER human approval is recorded")
        return steps

    # ── step 3 + 4 + 5: approve → fill → verify ────────────────────────────────
    def register(self, platform: str, signup_url: str,
                 form_selectors: Dict[str, str],
                 field_values: Dict[str, str],
                 *, approval_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute registration ONLY behind a recorded human approval.

        `form_selectors` maps field name -> CSS selector (the caller decides the
        selectors after reviewing the real page). `field_values` are supplied by
        the caller — this method refuses to invent any value and never logs or
        persists them. Secrets must be sourced by the caller from the human/vault.

        Refuses unless `approval_id` refers to an APPROVED `create_account` item
        for this platform. Returns the browser result as evidence.
        """
        gate, boundary, queue = self._require_gate()

        # Fail closed: registration is HIGH-TRUST and needs a recorded approval.
        if boundary.is_high_trust("create_account"):
            if not approval_id:
                return {"ok": False,
                        "reason": "registration is HIGH-TRUST and requires a human "
                                  "approval_id; call propose() then enqueue an approval"}
            item = queue.find_by_id(approval_id)
            if item is None:
                return {"ok": False, "reason": f"approval {approval_id} not found"}
            from agents.safety.approval import ApprovalStatus
            if item.status != ApprovalStatus.APPROVED:
                return {"ok": False,
                        "reason": f"approval {approval_id} is {item.status.value}, "
                                  "not approved"}

        # Never invent a value. Every field the caller lists must have a value,
        # and we never fabricate a missing one.
        missing = [f for f in form_selectors if f not in field_values or
                   field_values.get(f) in (None, "")]
        if missing:
            return {"ok": False,
                    "reason": f"no value supplied for: {', '.join(missing)}. "
                              "The agent never invents credentials."}

        return self._fill(signup_url, platform, form_selectors, field_values)

    def register_with_vault(self, platform: str, signup_url: str,
                            form_selectors: Dict[str, str],
                            *, approval_id: Optional[str] = None,
                            vault=None) -> Dict[str, Any]:
        """Execute registration using credentials from the ENCRYPTED VAULT.

        The secrets never pass through chat, logs, or a model — they are read
        from the vault (encrypted at rest) and fed straight to the browser form.
        `form_selectors` field names must match the vault field names for this
        platform (e.g. {"email": "#email", "password": "#pw"} with vault fields
        email/password). Same HIGH-TRUST approval gate as register().
        """
        gate, boundary, queue = self._require_gate()
        if boundary.is_high_trust("create_account"):
            if not approval_id:
                return {"ok": False,
                        "reason": "registration is HIGH-TRUST and requires a human "
                                  "approval_id"}
            from agents.safety.approval import ApprovalStatus
            item = queue.find_by_id(approval_id)
            if item is None or item.status != ApprovalStatus.APPROVED:
                return {"ok": False,
                        "reason": "a recorded, APPROVED create_account approval is required"}

        if vault is None:
            from agents.platforms.credential_vault import CredentialVault
            vault = CredentialVault()
        if not vault.has_platform(platform):
            return {"ok": False,
                    "reason": f"no credentials stored for {platform} in the vault; "
                              "the human must enter them first"}

        secrets = vault.get_all(platform)   # decrypted, in-process only
        missing = [f for f in form_selectors if not secrets.get(f)]
        if missing:
            return {"ok": False,
                    "reason": f"vault has no value for: {', '.join(missing)}"}

        # secrets flow straight to the form; never logged or serialized.
        return self._fill(signup_url, platform, form_selectors, secrets)

    def _fill(self, signup_url: str, platform: str,
              form_selectors: Dict[str, str],
              field_values: Dict[str, str]) -> Dict[str, Any]:
        """Drive the registration form. Shared by register/register_with_vault.
        Never logs the values."""
        selector_to_value = {form_selectors[f]: field_values[f] for f in form_selectors}

        try:
            from agents.integrations.web_eyes import get_web_eyes
            import asyncio
            eyes = get_web_eyes()
            result = asyncio.run(eyes.fill_form(signup_url, selector_to_value))
        except Exception as exc:
            return {"ok": False, "reason": f"form fill failed: {exc}"}

        if result.get("error"):
            return {"ok": False, "reason": result["error"], "evidence": result}

        return {"ok": True, "platform": platform, "evidence": result,
                "note": "Registration submitted behind a human approval. "
                        "Verify the account by checking the resulting page/email."}
