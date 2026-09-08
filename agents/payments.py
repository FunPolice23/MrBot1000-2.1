"""
agents/payments.py — x402 payment support, escrow, automated payouts (v2.1 Phase 4).

Features:
- x402 protocol payment flow
- Escrow system for milestone-based payments
- Automated payouts when thresholds met
- Multi-chain support (SOL, ETH, USDC)
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

from agents.wallet import WalletManager, Chain, PaymentTx


class PaymentStatus(str, Enum):
    PENDING = "pending"
    ESCROWED = "escrowed"
    RELEASED = "released"
    REFUNDED = "refunded"
    FAILED = "failed"


@dataclass
class Escrow:
    escrow_id: str
    payer: str
    payee: str
    amount: float
    currency: str
    chain: Chain
    milestone: str
    created_at: float = field(default_factory=time.time)
    released_at: Optional[float] = None
    status: PaymentStatus = PaymentStatus.PENDING
    metadata: Dict = field(default_factory=dict)


class X402Payment:
    """x402 protocol payment handler."""

    def __init__(self, wallet_manager: WalletManager):
        self.wallets = wallet_manager
        self._payments: Dict[str, Dict] = {}

    def create_payment(self, from_addr: str, to_addr: str, amount: float, currency: str, chain: Chain, payload: Dict = None) -> Dict:
        """Create an x402 payment."""
        payment_id = hashlib.sha256(f"{from_addr}{to_addr}{amount}{time.time()}".encode()).hexdigest()[:32]

        payment = {
            "payment_id": payment_id,
            "from": from_addr,
            "to": to_addr,
            "amount": amount,
            "currency": currency,
            "chain": chain.value,
            "status": "created",
            "payload": payload or {},
            "created_at": time.time(),
        }

        self._payments[payment_id] = payment
        return payment

    def verify_payment(self, payment_id: str) -> Dict:
        """Verify a payment."""
        payment = self._payments.get(payment_id)
        if not payment:
            return {"ok": False, "error": "Payment not found"}

        # In production, verify on-chain
        return {
            "ok": True,
            "payment_id": payment_id,
            "status": payment["status"],
            "from": payment["from"],
            "to": payment["to"],
            "amount": payment["amount"],
            "currency": payment["currency"],
            "chain": payment["chain"],
        }

    def settle_payment(self, payment_id: str) -> Dict:
        """Settle a payment."""
        payment = self._payments.get(payment_id)
        if not payment:
            return {"ok": False, "error": "Payment not found"}

        payment["status"] = "settled"
        payment["settled_at"] = time.time()

        # Update wallet balances
        from_wallet = self.wallets.get_wallet(payment["from"])
        to_wallet = self.wallets.get_wallet(payment["to"])

        if from_wallet and from_wallet.balance >= payment["amount"]:
            from_wallet.balance -= payment["amount"]
            if to_wallet:
                to_wallet.balance += payment["amount"]
            self.wallets._save()

        return {
            "ok": True,
            "payment_id": payment_id,
            "status": "settled",
            "tx": PaymentTx(
                tx_id=payment_id,
                from_addr=payment["from"],
                to_addr=payment["to"],
                amount=payment["amount"],
                currency=payment["currency"],
                chain=Chain(payment["chain"]),
            ).to_dict(),
        }

    def get_payments(self, status: Optional[str] = None) -> List[Dict]:
        """Get all payments, optionally filtered by status."""
        payments = list(self._payments.values())
        if status:
            payments = [p for p in payments if p["status"] == status]
        return payments


class EscrowManager:
    """Manages escrow payments for milestone-based work."""

    def __init__(self, wallet_manager: WalletManager):
        self.wallets = wallet_manager
        self._escrows: Dict[str, Escrow] = {}

    def create_escrow(self, payer: str, payee: str, amount: float, currency: str, chain: Chain, milestone: str) -> Escrow:
        """Create an escrow for a milestone."""
        escrow_id = hashlib.sha256(f"{payer}{payee}{amount}{milestone}{time.time()}".encode()).hexdigest()[:32]

        escrow = Escrow(
            escrow_id=escrow_id,
            payer=payer,
            payee=payee,
            amount=amount,
            currency=currency,
            chain=chain,
            milestone=milestone,
        )
        self._escrows[escrow_id] = escrow

        # Lock funds from payer
        payer_wallet = self.wallets.get_wallet(payer)
        if payer_wallet and payer_wallet.balance >= amount:
            payer_wallet.balance -= amount
            self.wallets._save()
        
        escrow.status = PaymentStatus.ESCROWED
        return escrow

    def release_escrow(self, escrow_id: str) -> Dict:
        """Release escrow funds to payee."""
        escrow = self._escrows.get(escrow_id)
        if not escrow:
            return {"ok": False, "error": "Escrow not found"}

        if escrow.status != PaymentStatus.ESCROWED:
            return {"ok": False, "error": f"Escrow not in releasable state: {escrow.status}"}

        escrow.status = PaymentStatus.RELEASED
        escrow.released_at = time.time()

        # Transfer to payee
        payee_wallet = self.wallets.get_wallet(escrow.payee)
        if payee_wallet:
            payee_wallet.balance += escrow.amount
            self.wallets._save()

        return {
            "ok": True,
            "escrow_id": escrow_id,
            "status": "released",
            "amount": escrow.amount,
            "to": escrow.payee,
        }

    def refund_escrow(self, escrow_id: str) -> Dict:
        """Refund escrow to payer."""
        escrow = self._escrows.get(escrow_id)
        if not escrow:
            return {"ok": False, "error": "Escrow not found"}

        escrow.status = PaymentStatus.REFUNDED

        # Return to payer
        payer_wallet = self.wallets.get_wallet(escrow.payer)
        if payer_wallet:
            payer_wallet.balance += escrow.amount
            self.wallets._save()

        return {
            "ok": True,
            "escrow_id": escrow_id,
            "status": "refunded",
            "amount": escrow.amount,
            "to": escrow.payer,
        }

    def get_escrow(self, escrow_id: str) -> Optional[Escrow]:
        """Get escrow by ID."""
        return self._escrows.get(escrow_id)

    def list_escrows(self, status: Optional[PaymentStatus] = None) -> List[Escrow]:
        """List escrows, optionally filtered by status."""
        escrows = list(self._escrows.values())
        if status:
            escrows = [e for e in escrows if e.status == status]
        return escrows


class AutomatedPayout:
    """Automated payout system."""

    def __init__(self, wallet_manager: WalletManager, threshold_usd: float = 50.0):
        self.wallets = wallet_manager
        self.threshold_usd = threshold_usd
        self._payouts: List[Dict] = []

    def check_and_payout(self) -> Dict:
        """Check if any wallet exceeds threshold and initiate payout."""
        total = self.wallets.get_total_balance()
        payouts = []

        for currency, balance in total.items():
            if balance >= self.threshold_usd:
                # Payout excess above threshold
                payout_amount = balance - self.threshold_usd
                payout = {
                    "currency": currency,
                    "amount": payout_amount,
                    "timestamp": time.time(),
                    "status": "scheduled",
                }
                payouts.append(payout)
                self._payouts.append(payout)

        return {
            "ok": True,
            "threshold": self.threshold_usd,
            "payouts": payouts,
            "count": len(payouts),
        }

    def get_payout_history(self) -> List[Dict]:
        """Get payout history."""
        return list(self._payouts)

    def set_threshold(self, threshold_usd: float):
        """Update payout threshold."""
        self.threshold_usd = threshold_usd
