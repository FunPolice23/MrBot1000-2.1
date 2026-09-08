"""agents/human_gates.py — Human-in-the-loop gate manager (v2.0.36i).

Determines when human input is REQUIRED (never bypassed). Categories:
- identity verification
- sensitive information
- contracts / legal agreements
- payments / financial commitments
- signatures
- captchas / bot challenges
- irreversible actions (deletions, publishes)
- platform-specific manual interaction

Rule: If a task requires a human gate, the executor STOPS and sets the portfolio entry
to AWAITING_APPROVAL with blocked_reason describing the gate. It does NOT proceed until
the human clears the gate. The gate is recorded with evidence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Gate types ─────────────────────────────────────────────────────────────────

class HumanGateType(str, Enum):
    IDENTITY_VERIFICATION = "identity_verification"
    SENSITIVE_INFORMATION = "sensitive_information"
    CONTRACTS = "contracts"
    PAYMENTS = "payments"
    SIGNATURES = "signatures"
    CAPTCHA = "captcha"
    IRREVERSIBLE_ACTION = "irreversible_action"
    PLATFORM_MANUAL = "platform_manual"


# ── Gate record ─────────────────────────────────────────────────────────────────

@dataclass
class HumanGateRecord:
    """A single human gate for a task."""
    gate_type: HumanGateType
    description: str
    task_id: str = ""
    cleared: bool = False
    cleared_at: float = 0.0
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "gate_type": self.gate_type.value,
            "description": self.description,
            "task_id": self.task_id,
            "cleared": self.cleared,
            "cleared_at": self.cleared_at,
            "evidence": self.evidence,
        }


# ── Human gate manager ─────────────────────────────────────────────────────────

class HumanGateManager:
    """Determines when human input is required. Never bypasses."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._records: Dict[str, List[HumanGateRecord]] = {}

    # ── Assessment ─────────────────────────────────────────────────────────────

    def assess(self, task: Dict[str, Any], context: Dict[str, Any]) -> List[HumanGateRecord]:
        """Determine which gates apply based on task properties. Returns list of required gates."""
        task_id = task.get("task_id", task.get("id", ""))
        gates: List[HumanGateRecord] = []

        # Payments / financial commitments
        if self._has_payment(task, context):
            gates.append(HumanGateRecord(
                gate_type=HumanGateType.PAYMENTS,
                description="Task involves financial commitment or payment. Human approval required.",
                task_id=task_id,
            ))

        # Contracts / legal
        if self._has_contracts(task, context):
            gates.append(HumanGateRecord(
                gate_type=HumanGateType.CONTRACTS,
                description="Task involves contracts or legal agreements. Human review required.",
                task_id=task_id,
            ))

        # Signatures
        if self._has_signatures(task, context):
            gates.append(HumanGateRecord(
                gate_type=HumanGateType.SIGNATURES,
                description="Task requires a signature. Human action required.",
                task_id=task_id,
            ))

        # Identity verification
        if self._has_identity(task, context):
            gates.append(HumanGateRecord(
                gate_type=HumanGateType.IDENTITY_VERIFICATION,
                description="Task involves identity verification. Human action required.",
                task_id=task_id,
            ))

        # Sensitive information
        if self._has_sensitive(task, context):
            gates.append(HumanGateRecord(
                gate_type=HumanGateType.SENSITIVE_INFORMATION,
                description="Task involves sensitive information. Human review required.",
                task_id=task_id,
            ))

        # Irreversible actions
        if self._has_irreversible(task, context):
            gates.append(HumanGateRecord(
                gate_type=HumanGateType.IRREVERSIBLE_ACTION,
                description="Task involves irreversible actions (deletion, publish). Human approval required.",
                task_id=task_id,
            ))

        # Captcha / bot challenge
        if self._has_captcha(task, context):
            gates.append(HumanGateRecord(
                gate_type=HumanGateType.CAPTCHA,
                description="Task requires solving a captcha or bot challenge. Human action required.",
                task_id=task_id,
            ))

        # Platform-specific manual interaction
        if self._has_platform_manual(task, context):
            gates.append(HumanGateRecord(
                gate_type=HumanGateType.PLATFORM_MANUAL,
                description="Task requires platform-specific manual interaction. Human action required.",
                task_id=task_id,
            ))

        # Store records
        if task_id:
            self._records[task_id] = gates
        return gates

    def requires_human(self, task: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Quick check: does this task require any human gate?"""
        return len(self.assess(task, context)) > 0

    # ── Gate clearance ─────────────────────────────────────────────────────────

    def clear_gate(self, task_id: str, gate_type: HumanGateType, evidence: str = "") -> bool:
        """Record human clearance for a gate. Returns True if found and cleared."""
        records = self._records.get(task_id, [])
        for r in records:
            if r.gate_type == gate_type and not r.cleared:
                r.cleared = True
                r.cleared_at = time.time()
                r.evidence = evidence
                return True
        return False

    def get_pending_gates(self, task_id: str) -> List[HumanGateRecord]:
        """Return uncleared gates for a task."""
        return [r for r in self._records.get(task_id, []) if not r.cleared]

    def get_all_gates(self, task_id: str) -> List[HumanGateRecord]:
        """Return all gates for a task."""
        return self._records.get(task_id, [])

    def all_cleared(self, task_id: str) -> bool:
        """Check if all gates for a task are cleared."""
        records = self._records.get(task_id, [])
        return len(records) > 0 and all(r.cleared for r in records)

    # ── Detection logic (deterministic) ───────────────────────────────────────

    def _has_payment(self, task: Dict, context: Dict) -> bool:
        payment_conditions = task.get("payment_conditions", {})
        if payment_conditions:
            return True
        text = f"{task.get('description', '')} {task.get('title', '')}".lower()
        payment_keywords = ["payment", "pay", "invoice", "financial", "money", "usd", "$", "commit"]
        return any(kw in text for kw in payment_keywords)

    def _has_contracts(self, task: Dict, context: Dict) -> bool:
        text = f"{task.get('description', '')} {task.get('title', '')}".lower()
        contract_keywords = ["contract", "legal", "agreement", "terms", "binding", "nda"]
        return any(kw in text for kw in contract_keywords)

    def _has_signatures(self, task: Dict, context: Dict) -> bool:
        text = f"{task.get('description', '')} {task.get('title', '')}".lower()
        return "signature" in text or "sign" in text

    def _has_identity(self, task: Dict, context: Dict) -> bool:
        text = f"{task.get('description', '')} {task.get('title', '')}".lower()
        identity_keywords = ["identity", "verify", "kyc", "passport", "id verification"]
        return any(kw in text for kw in identity_keywords)

    def _has_sensitive(self, task: Dict, context: Dict) -> bool:
        text = f"{task.get('description', '')} {task.get('title', '')}".lower()
        sensitive_keywords = ["sensitive", "confidential", "private", "personal data", "pii"]
        return any(kw in text for kw in sensitive_keywords)

    def _has_irreversible(self, task: Dict, context: Dict) -> bool:
        text = f"{task.get('description', '')} {task.get('title', '')}".lower()
        irreversible_keywords = ["delete", "remove", "publish", "irreversible", "destroy", "erase"]
        return any(kw in text for kw in irreversible_keywords)

    def _has_captcha(self, task: Dict, context: Dict) -> bool:
        text = f"{task.get('description', '')} {task.get('title', '')}".lower()
        return "captcha" in text or "bot challenge" in text

    def _has_platform_manual(self, task: Dict, context: Dict) -> bool:
        text = f"{task.get('description', '')} {task.get('title', '')}".lower()
        manual_keywords = ["manual", "platform-specific", "interview", "phone call"]
        return any(kw in text for kw in manual_keywords)


__all__ = [
    "HumanGateType",
    "HumanGateRecord",
    "HumanGateManager",
]
