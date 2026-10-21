"""
agents/real_crypto_operator.py — Human-gated real crypto payment operator (v2.1 Path 3).

Wraps CryptoPayments with explicit approval flow:
1. Agent creates payment request (local, simulated)
2. Human reviews via SafetyGuard approval gate
3. If approved AND real keys/RPC configured -> real on-chain send
4. Otherwise -> stays simulated for manual execution

Safety rules:
- Never auto-send real funds without human approval
- Never store private keys in code/repo
- All real sends require SDK + RPC + key configuration
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional

from agents.core.feature_flags import feature_enabled
from agents.integrations.crypto import CryptoPayments, CryptoPaymentRequest, CryptoPaymentError
from agents.safety.guard import SafetyGuard, SafetyAction
from agents.safety.approval import (
    ApprovalItem, ApprovalKind, HumanApprovalQueue, assert_approval_covers,
)

# The tool name under which a real crypto send is scoped in the approval queue.
# ARCH-ENG-130 binds confirm_and_send to an approval recorded for THIS name and
# the exact destination/amount/currency/chain the human reviewed (the ARCH-ENG-129
# assert_approval_covers contract), so one approval id can never be replayed
# against a different send.
_CRYPTO_SEND_TOOL = "crypto_send"


# ── ARCH-ENG-237 (BB-01): recipient validation at the entry boundary ──────────
# The earning tab once proposed payments to a hardcoded placeholder recipient,
# and the scoped approval faithfully asked the human to authorize a real
# transfer to it. ARCH-ENG-130's scoping guarantees the operator approves
# *precisely what was requested* — it cannot notice that what was requested
# should never have been requested. Validation happens HERE, at the boundary
# where the recipient enters the payment machinery, so every current and future
# caller is protected; a correct mechanism does not launder incorrect input.
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SOLANA_CHAINS = {"solana"}


def _recipient_rejection(chain, to_address: str) -> Optional[str]:
    """Return a refusal reason for an unusable recipient, else None.

    Deliberate policy on the two shapes a recipient can take the same wrong way:
    a syntactically valid but obviously-dummy address (201/... all 40 hex
    characters identical — the classic "0xA*40" placeholder) is also refused.
    No real key would ever collide into 42 identical characters, and on a
    payment surface the burned-to-zero-address case is not spared an explicit
    human-authored destination.
    """
    addr = (to_address or "").strip()
    if not addr:
        return "recipient address is empty"
    chain_value = (getattr(chain, "value", None) or str(chain)).lower()
    if chain_value in _SOLANA_CHAINS:
        if not _SOLANA_ADDRESS_RE.match(addr):
            return (f"recipient '{addr[:20]}…' is not a valid Solana address "
                    "(expecting 32-44 base58 characters)")
        return None
    # EVM family (ethereum / polygon / base and defaults).
    if not _EVM_ADDRESS_RE.match(addr):
        return (f"recipient '{addr[:20]}…' is not a valid EVM address "
                "(expecting 0x + 40 hex characters)")
    if len(set(addr[2:].lower())) == 1:
        return (f"recipient '{addr}' is a placeholder, not a real destination "
                "(all 40 characters are identical)")
    return None


class RealCryptoOperator:
    """Human-gated real crypto payment operator."""

    def __init__(self, wallet_manager, safety_guard: Optional[SafetyGuard] = None):
        self.crypto = CryptoPayments(wallet_manager, human_approval_required=True)
        self.safety_guard = safety_guard
        self._approval_callbacks = []

    def propose_payment(
        self,
        from_address: str,
        to_address: str,
        amount: float,
        currency: str,
        chain,
        memo: str = "",
    ) -> Dict[str, Any]:
        """Propose a payment for human approval."""
        # ARCH-ENG-281 (D-01): `crypto_operations` used to gate NOTHING. The
        # flag was defined and documented, but no crypto entry point read it,
        # so a disabled operator could still create requests and enqueue
        # approvals. The gate belongs at the operator's entry boundary, before
        # any request or approval exists.
        if not feature_enabled("crypto_operations"):
            return {
                "ok": False,
                "request_id": "",
                "status": "disabled",
                "error": ("Crypto operations are disabled "
                          "(set MRBOT_ENABLE_CRYPTO=1 to enable); no payment "
                          "request was created."),
            }

        # ARCH-ENG-237 (BB-01): refuse an unusable recipient BEFORE any request
        # is created or any approval is enqueued — fail closed at content entry.
        rejection = _recipient_rejection(chain, to_address)
        if rejection:
            return {
                "ok": False,
                "request_id": "",
                "status": "invalid_recipient",
                "error": rejection,
            }

        # Create local request
        request = self.crypto.create_payment(from_address, to_address, amount, currency, chain, memo)

        # Safety check
        if self.safety_guard:
            action = SafetyAction(
                action_type="send_payment",
                name=f"{chain.value}:{amount}{currency}->{to_address[:20]}",
                arguments={
                    "request_id": request.request_id,
                    "from": from_address,
                    "to": to_address,
                    "amount": amount,
                    "currency": currency,
                    "chain": chain.value,
                    "memo": memo,
                },
                estimated_cost=0.0,
                platform="crypto",
                requires_funds=True,
            )
            result = self.safety_guard.check(action)
            if result.action == "flag":
                # ARCH-ENG-130: enqueue a SCOPED payment approval so the human
                # reviews the exact destination/amount/currency/chain, and the
                # returned approval_id is what confirm_and_send requires. Scope
                # lives in details with tool="crypto_send" so assert_approval_
                # covers binds a later send to exactly this action (one id can
                # never be replayed against a different amount/destination).
                chain_value = (chain.value if hasattr(chain, "value") else str(chain))
                item = HumanApprovalQueue.instance().enqueue(ApprovalItem(
                    kind=ApprovalKind.PAYMENT,
                    title=f"Crypto payment: {amount}{currency} -> {to_address[:20]}",
                    description=(f"Send {amount} {currency} on {chain_value} to "
                                 f"{to_address}. Approve to authorize the on-chain "
                                 f"send; deny to keep it simulated."),
                    requested_by="real_crypto_operator",
                    details={
                        "tool": _CRYPTO_SEND_TOOL,
                        "arguments": {
                            "request_id": request.request_id,
                            "to": to_address,
                            "amount": amount,
                            "currency": currency,
                            "chain": chain_value,
                        },
                    },
                ))
                return {
                    "ok": True,
                    "request_id": request.request_id,
                    "approval_id": item.id,
                    "status": "awaiting_approval",
                    "reasons": result.reasons,
                    "request": request.to_dict(),
                }
            if result.blocked:
                return {
                    "ok": False,
                    "request_id": request.request_id,
                    "status": "blocked",
                    "error": "; ".join(result.reasons),
                }

        # No safety guard or allowed -> simulate
        sim = self.crypto.simulate_payment(request)
        return {"ok": True, "request_id": request.request_id, "status": "simulated", "simulation": sim, "request": request.to_dict()}

    def confirm_and_send(self, request_id: str, rpc_url: str = "",
                         private_key: str = "",
                         approval_id: str = "") -> Dict[str, Any]:
        """Confirm approval and attempt a REAL on-chain send (ARCH-ENG-130).

        The only thing that ever authorized a real send was the static
        ``human_approval_required=True`` constructor flag on ``CryptoPayments``
        — a method named "confirm" that confirmed nothing. If that flag were
        ever flipped to enable real sends, any caller could move real funds
        with no recorded human decision.

        The gate is now a REAL, scoped approval: the caller must pass the
        ``approval_id`` of an APPROVED queue item whose scope names
        ``crypto_send`` and the exact destination/amount/currency/chain the
        human reviewed (the ARCH-ENG-129 ``assert_approval_covers`` contract).
        It fails CLOSED on every miss — no id, unknown id, wrong scope, wrong
        amount, or an approval restored from a prior run (``find_by_id``
        refuses those) — and NEVER calls ``try_real_payment`` unless a valid,
        scoped approval is present.
        """
        # ARCH-ENG-281 (D-01): a real send is the highest-risk crypto action,
        # so the feature boundary is checked before the request is even read.
        if not feature_enabled("crypto_operations"):
            return {
                "ok": False,
                "status": "disabled",
                "error": ("Crypto operations are disabled "
                          "(set MRBOT_ENABLE_CRYPTO=1 to enable); no funds "
                          "were moved."),
            }

        request = self.crypto.get_request(request_id)
        if not request:
            return {"ok": False, "error": "Request not found"}

        # The exact action the human must have approved, built from the
        # PERSISTED request (not the caller's word) so the reviewed scope and
        # the executed send cannot diverge.
        send_args = {
            "request_id": request_id,
            "to": request.to_address,
            "amount": request.amount,
            "currency": request.currency,
            "chain": (request.chain.value
                      if hasattr(request.chain, "value") else str(request.chain)),
        }

        # Fail-closed human-approval gate. No approval_id, an unknown id, a
        # wrong-scope approval, or a stale (restored-from-disk) decision all
        # refuse here and never reach the send.
        if not approval_id:
            return {
                "ok": False,
                "status": "blocked",
                "error": ("A real send requires a recorded human approval_id; "
                          "none was supplied, so no funds were moved."),
            }
        item = HumanApprovalQueue.instance().find_by_id(approval_id)
        refusal = assert_approval_covers(item, _CRYPTO_SEND_TOOL, send_args)
        if refusal is not None:
            return {"ok": False, "status": "blocked", "error": refusal}

        # Approved and scoped: attempt the real send.
        real_result = self.crypto.try_real_payment(request, rpc_url=rpc_url, private_key=private_key)
        if real_result.get("ok"):
            confirmed = self.crypto.confirm_payment(request_id)
            return {"ok": True, "status": "confirmed", "tx_hash": request.tx_hash, "confirmations": confirmed.get("confirmations")}

        # Real send failed - return simulated
        return {
            "ok": True,
            "status": "simulated_only",
            "request": request.to_dict(),
            "real_attempt": real_result,
            "note": "Real send blocked or failed. Use simulate_payment for local tracking.",
        }

    def get_pending(self) -> List[Dict[str, Any]]:
        """Get pending payment requests."""
        pending = self.crypto.list_payments("pending") + self.crypto.list_payments("simulated")
        return [r.to_dict() for r in pending]

    def get_status(self) -> Dict[str, Any]:
        return self.crypto.get_status()
