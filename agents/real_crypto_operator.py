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
import time
from typing import Any, Dict, List, Optional

from agents.crypto_payments import CryptoPayments, CryptoPaymentRequest, CryptoPaymentError
from agents.safety_guard import SafetyGuard, SafetyAction


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
                return {
                    "ok": True,
                    "request_id": request.request_id,
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

    def confirm_and_send(self, request_id: str, rpc_url: str = "", private_key: str = "") -> Dict[str, Any]:
        """Confirm approval and attempt real send if configured."""
        request = self.crypto.get_request(request_id)
        if not request:
            return {"ok": False, "error": "Request not found"}

        # Try real send
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
