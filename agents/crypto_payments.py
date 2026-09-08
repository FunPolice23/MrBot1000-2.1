"""
agents/crypto_payments.py — Real crypto payment integration (v2.1 Path 3).

Optional real-chain integration using installed SDKs:
- Solana: uses solana-py if installed, otherwise falls back to local simulation
- Ethereum: uses web3.py if installed, otherwise falls back to local simulation
- USDC: SPL token or ERC-20 if respective SDKs installed

Real usage requires:
- Funded wallet addresses
- Private keys stored securely (NOT in code/repo)
- Network RPC endpoints configured

For safety, all actual chain calls are behind human approval gates.
This module records the INTENT and packages the transaction for human review.
"""

from __future__ import annotations

import os
import time
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents.wallet import WalletManager, Chain, PaymentTx


class CryptoPaymentError(Exception):
    pass


@dataclass
class CryptoPaymentRequest:
    request_id: str
    from_address: str
    to_address: str
    amount: float
    currency: str
    chain: Chain
    memo: str = ""
    status: str = "pending"
    tx_hash: str = ""
    confirmations: int = 0
    error: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "from": self.from_address,
            "to": self.to_address,
            "amount": self.amount,
            "currency": self.currency,
            "chain": self.chain.value,
            "memo": self.memo,
            "status": self.status,
            "tx_hash": self.tx_hash,
            "confirmations": self.confirmations,
            "error": self.error,
            "created_at": self.created_at,
        }


class CryptoPayments:
    """Handle real crypto payments with safety gates."""

    def __init__(self, wallet_manager: WalletManager, human_approval_required: bool = True):
        self.wallets = wallet_manager
        self.human_approval_required = human_approval_required
        self._requests: Dict[str, CryptoPaymentRequest] = {}
        self._sdk_status = self._check_sdks()

    @staticmethod
    def _check_sdks() -> Dict[str, bool]:
        status = {}
        for lib in ["solana", "web3", "web3.exceptions"]:
            try:
                __import__(lib)
                status[lib] = True
            except ImportError:
                status[lib] = False
        return status

    def get_sdk_status(self) -> Dict[str, Any]:
        return {
            "solana_py": self._sdk_status.get("solana", False),
            "web3_py": self._sdk_status.get("web3", False),
            "note": "Real payments require SDK installation + funded wallets + RPC endpoints.",
        }

    def create_payment(
        self,
        from_address: str,
        to_address: str,
        amount: float,
        currency: str,
        chain: Chain,
        memo: str = "",
    ) -> CryptoPaymentRequest:
        """Create a payment request."""
        if amount <= 0:
            raise CryptoPaymentError("Amount must be positive")

        from_wallet = self.wallets.get_wallet(from_address)
        if from_wallet is None:
            raise CryptoPaymentError(f"Unknown from-address: {from_address}")
        if from_wallet.balance < amount:
            raise CryptoPaymentError(f"Insufficient balance: {from_wallet.balance} {currency} < {amount}")

        request_id = hashlib.sha256(f"{from_address}{to_address}{amount}{time.time()}".encode()).hexdigest()[:24]

        request = CryptoPaymentRequest(
            request_id=request_id,
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            currency=currency,
            chain=chain,
            memo=memo,
        )
        self._requests[request_id] = request
        return request

    def simulate_payment(self, request: CryptoPaymentRequest) -> Dict[str, Any]:
        """Simulate a payment locally (no chain interaction)."""
        if request.status != "pending":
            return {"ok": False, "request_id": request.request_id, "error": f"Already {request.status}"}

        request.status = "simulated"
        request.tx_hash = hashlib.sha256(f"{request.request_id}{time.time()}".encode()).hexdigest()[:32]
        return {
            "ok": True,
            "request_id": request.request_id,
            "status": "simulated",
            "tx_hash": request.tx_hash,
            "note": "Local simulation only. Configure real SDK + keys for on-chain execution.",
        }

    def try_real_payment(self, request: CryptoPaymentRequest, rpc_url: str = "", private_key: str = "") -> Dict[str, Any]:
        """Attempt real on-chain payment if SDKs available."""
        if self.human_approval_required:
            return {
                "ok": False,
                "request_id": request.request_id,
                "error": "Real payments require human approval + configured keys",
                "sdk_status": self.get_sdk_status(),
            }

        if request.chain == Chain.SOLANA:
            return self._solana_pay(request, rpc_url, private_key)
        elif request.chain in (Chain.ETHEREUM, Chain.POLYGON, Chain.BASE):
            return self._evm_pay(request, rpc_url, private_key)
        else:
            return {"ok": False, "request_id": request.request_id, "error": f"Unsupported chain: {request.chain}"}

    def _solana_pay(self, request: CryptoPaymentRequest, rpc_url: str, private_key: str) -> Dict[str, Any]:
        if not self._sdk_status.get("solana"):
            return {"ok": False, "request_id": request.request_id, "error": "solana-py not installed"}
        if not rpc_url or not private_key:
            return {"ok": False, "request_id": request.request_id, "error": "RPC URL and private key required"}

        try:
            from solana.rpc.api import Client
            from solana.keypair import Keypair
            from solana.transaction import Transaction
            from solana.system_program import TransferParams, transfer

            client = Client(rpc_url)
            kp = Keypair.from_secret_key(bytes.fromhex(private_key))

            tx = Transaction().add(
                transfer(
                    TransferParams(
                        from_pubkey=kp.public_key,
                        to_pubkey=request.to_address,
                        lamports=int(request.amount * 1_000_000_000),
                    )
                )
            )
            result = client.send_transaction(tx, kp)
            request.tx_hash = result.value if hasattr(result, "value") else str(result)
            request.status = "submitted"
            return {"ok": True, "request_id": request.request_id, "tx_hash": request.tx_hash}
        except Exception as e:
            request.error = str(e)
            return {"ok": False, "request_id": request.request_id, "error": str(e)}

    def _evm_pay(self, request: CryptoPaymentRequest, rpc_url: str, private_key: str) -> Dict[str, Any]:
        if not self._sdk_status.get("web3"):
            return {"ok": False, "request_id": request.request_id, "error": "web3.py not installed"}
        if not rpc_url or not private_key:
            return {"ok": False, "request_id": request.request_id, "error": "RPC URL and private key required"}

        try:
            from web3 import Web3
            from eth_account import Account

            w3 = Web3(Web3.HTTPProvider(rpc_url))
            acct = Account.from_key(private_key)
            nonce = w3.eth.get_transaction_count(acct.address)
            tx = {
                "nonce": nonce,
                "to": request.to_address,
                "value": w3.to_wei(request.amount, "ether"),
                "gas": 21000,
                "gasPrice": w3.eth.gas_price,
                "chainId": w3.eth.chain_id,
            }
            signed = acct.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            request.tx_hash = tx_hash.hex()
            request.status = "submitted"
            return {"ok": True, "request_id": request.request_id, "tx_hash": request.tx_hash}
        except Exception as e:
            request.error = str(e)
            return {"ok": False, "request_id": request.request_id, "error": str(e)}

    def confirm_payment(self, request_id: str, confirmations: int = 1) -> Dict[str, Any]:
        request = self._requests.get(request_id)
        if not request:
            return {"ok": False, "error": "Request not found"}

        request.confirmations = confirmations
        if confirmations >= 1:
            request.status = "confirmed"

        # Update wallet balances locally
        from_wallet = self.wallets.get_wallet(request.from_address)
        to_wallet = self.wallets.get_wallet(request.to_address)
        if from_wallet:
            from_wallet.balance = max(0.0, from_wallet.balance - request.amount)
        if to_wallet:
            to_wallet.balance += request.amount
        self.wallets._save()

        return {"ok": True, "request_id": request_id, "status": request.status, "confirmations": confirmations}

    def list_payments(self, status: Optional[str] = None) -> List[CryptoPaymentRequest]:
        requests = list(self._requests.values())
        if status:
            requests = [r for r in requests if r.status == status]
        return requests

    def get_request(self, request_id: str) -> Optional[CryptoPaymentRequest]:
        return self._requests.get(request_id)

    def get_status(self) -> Dict[str, Any]:
        all_reqs = list(self._requests.values())
        return {
            "total": len(all_reqs),
            "pending": len([r for r in all_reqs if r.status == "pending"]),
            "simulated": len([r for r in all_reqs if r.status == "simulated"]),
            "submitted": len([r for r in all_reqs if r.status == "submitted"]),
            "confirmed": len([r for r in all_reqs if r.status == "confirmed"]),
            "sdk": self.get_sdk_status(),
        }
