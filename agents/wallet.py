"""
agents/wallet.py — Wallet management for crypto payments (v2.1 Phase 4).

Supports:
- SOL, ETH, USDC wallets
- Balance tracking
- Transaction history
- Address validation
- Multi-chain support
"""

from __future__ import annotations

import json
import os
import time
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class Chain(str, Enum):
    SOLANA = "solana"
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    BASE = "base"


@dataclass
class Wallet:
    address: str
    chain: Chain
    private_key: Optional[str] = None  # Never stored in plain text in production
    balance: float = 0.0
    currency: str = ""
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)


class WalletManager:
    """Manages crypto wallets for the agent system."""

    def __init__(self, state_path: str = ""):
        self.state_path = state_path or os.path.join(os.path.expanduser("~"), ".mrbot1000", "wallets.json")
        self._wallets: Dict[str, Wallet] = {}
        self._load()

    def _load(self):
        """Load wallets from disk."""
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                for addr, w in data.items():
                    self._wallets[addr] = Wallet(
                        address=w["address"],
                        chain=Chain(w["chain"]),
                        balance=w.get("balance", 0.0),
                        currency=w.get("currency", ""),
                        created_at=w.get("created_at", time.time()),
                        last_updated=w.get("last_updated", time.time()),
                        metadata=w.get("metadata", {}),
                    )
        except Exception:
            pass

    def _save(self):
        """Save wallets to disk."""
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            data = {}
            for addr, w in self._wallets.items():
                data[addr] = {
                    "address": w.address,
                    "chain": w.chain.value,
                    "balance": w.balance,
                    "currency": w.currency,
                    "created_at": w.created_at,
                    "last_updated": w.last_updated,
                    "metadata": w.metadata,
                }
            with open(self.state_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def add_wallet(self, address: str, chain: Chain, currency: str = "") -> Wallet:
        """Add a wallet."""
        if not self._validate_address(address, chain):
            raise ValueError(f"Invalid address for {chain.value}: {address}")
        if address in self._wallets:
            return self._wallets[address]
        w = Wallet(address=address, chain=chain, currency=currency or chain.value)
        self._wallets[address] = w
        self._save()
        return w

    def remove_wallet(self, address: str) -> bool:
        """Remove a wallet."""
        if address in self._wallets:
            del self._wallets[address]
            self._save()
            return True
        return False

    def get_wallet(self, address: str) -> Optional[Wallet]:
        """Get wallet by address."""
        return self._wallets.get(address)

    def list_wallets(self, chain: Optional[Chain] = None) -> List[Wallet]:
        """List wallets, optionally filtered by chain."""
        wallets = list(self._wallets.values())
        if chain:
            wallets = [w for w in wallets if w.chain == chain]
        return wallets

    def update_balance(self, address: str, balance: float) -> bool:
        """Update wallet balance."""
        w = self._wallets.get(address)
        if w:
            w.balance = balance
            w.last_updated = time.time()
            self._save()
            return True
        return False

    def get_total_balance(self, chain: Optional[Chain] = None) -> Dict[str, float]:
        """Get total balance across wallets."""
        totals: Dict[str, float] = {}
        for w in self._wallets.values():
            if chain and w.chain != chain:
                continue
            currency = w.currency or w.chain.value
            totals[currency] = totals.get(currency, 0.0) + w.balance
        return totals

    def _validate_address(self, address: str, chain: Chain) -> bool:
        """Basic address validation."""
        if not address or len(address) < 20:
            return False
        if chain == Chain.SOLANA:
            return 32 <= len(address) <= 48 and address.isalnum()
        elif chain == Chain.ETHEREUM:
            return address.startswith("0x") and len(address) == 42
        return True

    def get_status(self) -> Dict:
        """Get wallet manager status."""
        return {
            "total_wallets": len(self._wallets),
            "chains": list(set(w.chain.value for w in self._wallets.values())),
            "total_balance": self.get_total_balance(),
        }


class PaymentTx:
    """Represents a payment transaction."""

    def __init__(self, tx_id: str, from_addr: str, to_addr: str, amount: float, currency: str, chain: Chain):
        self.tx_id = tx_id
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.amount = amount
        self.currency = currency
        self.chain = chain
        self.timestamp = time.time()
        self.status = "pending"
        self.hash = ""
        self.confirmations = 0

    def confirm(self, tx_hash: str, confirmations: int = 1):
        self.hash = tx_hash
        self.confirmations = confirmations
        self.status = "confirmed" if confirmations >= 1 else "pending"

    def to_dict(self) -> Dict:
        return {
            "tx_id": self.tx_id,
            "from": self.from_addr,
            "to": self.to_addr,
            "amount": self.amount,
            "currency": self.currency,
            "chain": self.chain.value,
            "timestamp": self.timestamp,
            "status": self.status,
            "hash": self.hash,
            "confirmations": self.confirmations,
        }
