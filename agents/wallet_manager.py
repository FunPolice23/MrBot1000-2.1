"""
agents/wallet_manager.py — Wallet management for MrBot1000.

Supports Solana and Ethereum wallets with balance checking.
"""

import os
import json
import time
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from pathlib import Path

import requests


# H30: canonical wallet-root resolver. Both the pipeline (which keys the wallet store off the
# earnings DB path) and the GUI (main.py) must read the SAME wallets.json / wallet.key, or a
# wallet added in the GUI is invisible to the pipeline and vice-versa. Priority:
#   1. WALLET_ROOT env (explicit override for packaged/custom deployments)
#   2. the sidecar of the earnings DB (earning.db's parent) when it exists there
#   3. the project root (legacy default, matches __file__ dir at dev time)
# Returns a resolved directory Path.
def resolve_wallet_root(db_path: str = None) -> "Path":
    env = os.getenv("WALLET_ROOT")
    if env:
        return Path(env).resolve()
    if db_path:
        cand = Path(db_path).resolve().parent
        if (cand / "wallets.json").exists() or (cand / "wallet.key").exists():
            return cand
    return Path(__file__).resolve().parent.parent


@dataclass
class WalletBalance:
    chain: str
    token: str
    balance: float
    usd_value: float = 0.0


@dataclass
class Transaction:
    tx_hash: str
    chain: str
    type: str
    amount: float
    token: str
    usd_value: float
    timestamp: float
    status: str


class WalletManager:
    """Manages crypto wallets for MrBot1000.

    B1: private keys are encrypted at rest in `wallets.json` (Fernet, via
    `agents.wallet_crypto`). The secret is only ever recovered through
    `get_private_key(name)` — callers must never place the returned value into LLM
    context. Empty keys are stored as plaintext "" (nothing to encrypt).
    """

    def __init__(self, root_folder: str = ".", encryption_key: str = None):
        self.root = Path(root_folder).resolve()
        self.wallets_file = self.root / "wallets.json"
        self._key_path = self.root / "wallet.key"
        self.wallets: Dict[str, dict] = {}
        # H28: gas-ledger total cache (see total_realized_gas_usd). None = not yet computed.
        self._gas_total_cache: Optional[float] = None
        # Resolve the Fernet key (env WALLET_ENC_KEY preferred, else auto-gen file).
        # A key failure means encryption is unavailable; we mark it and the store
        # methods will then store plaintext AND surface a warning (no silent leak).
        self._key = None
        self._encryption_error: Optional[str] = None
        try:
            from agents.wallet_crypto import load_or_create_key, _validate_key
            if encryption_key:
                # An explicitly-passed key MUST be validated too (don't bypass the
                # same check load_or_create_key applies to the env key / key file).
                self._key = _validate_key(encryption_key)
            else:
                self._key = load_or_create_key(self._key_path)
        except Exception as e:  # cryptography missing or invalid key
            self._encryption_error = str(e)
            self._key = None
        self._load_wallets()

    def _store_secret(self, private_key: str) -> dict:
        """Return the wallet dict with the private key encrypted (or "" if empty).

        If encryption is unavailable (no key / cryptography missing) we will NOT store the
        secret in cleartext. We log loudly (logging survives `-W ignore`, unlike
        `warnings.warn`) and raise — callers must surface the failure to the UI and refuse
        to add the wallet (H37). Empty keys are fine (nothing to encrypt).
        """
        if not private_key or not private_key.strip():
            return {"private_key": ""}
        if self._key:
            try:
                from agents.wallet_crypto import encrypt_str
                return {"private_key": encrypt_str(self._key, private_key)}
            except Exception:
                pass
        # Encryption unavailable and we have a real key to protect. H37: never persist
        # cleartext — refuse loudly so the wallet add fails closed.
        msg = (
            "WALLET KEY REFUSED (cleartext block): encryption unavailable "
            f"({self._encryption_error or 'no key'}). "
            "Set WALLET_ENC_KEY or ensure cryptography is installed before adding keys."
        )
        logging.error(msg)
        import warnings
        warnings.warn(msg, stacklevel=2)
        raise RuntimeError(msg)

    @property
    def encryption_unavailable(self) -> bool:
        """True when secrets cannot be encrypted at rest (key missing/invalid)."""
        return self._key is None

    def _load_wallets(self):
        if self.wallets_file.exists():
            try:
                data = json.loads(self.wallets_file.read_text())
                self.wallets = data.get("wallets", {})
            except Exception:
                self.wallets = {}

    def _save_wallets(self):
        # Encrypt any cleartext keys we hold in memory before persisting.
        if self._key:
            try:
                from agents.wallet_crypto import encrypt_if_needed
                for w in self.wallets.values():
                    pk = w.get("private_key", "")
                    if pk:
                        w["private_key"] = encrypt_if_needed(self._key, pk)
            except Exception:
                pass
        data = {"wallets": self.wallets}
        self.wallets_file.write_text(json.dumps(data, indent=2, default=str))

    def add_solana_wallet(self, name: str, address: str,
                          private_key: str = ""):
        entry = {
            "type": "solana",
            "address": address,
            "added_at": time.time(),
        }
        entry.update(self._store_secret(private_key))
        self.wallets[name] = entry
        self._save_wallets()

    def add_ethereum_wallet(self, name: str, address: str,
                            private_key: str = ""):
        entry = {
            "type": "ethereum",
            "address": address,
            "added_at": time.time(),
        }
        entry.update(self._store_secret(private_key))
        self.wallets[name] = entry
        self._save_wallets()

    def get_private_key(self, name: str) -> Optional[str]:
        """Recover the decrypted private key for `name` (or None).

        This is the ONLY accessor for the secret. Never feed the result into any LLM
        prompt or log it.
        """
        w = self.wallets.get(name)
        if not w:
            return None
        pk = w.get("private_key", "")
        if not pk:
            return None
        if self._key:
            try:
                from agents.wallet_crypto import decrypt_if_needed
                return decrypt_if_needed(self._key, pk)
            except Exception:
                return None
        return pk  # degraded plaintext path

    def get_balance(self, wallet_name: str
                    ) -> Optional[WalletBalance]:
        wallet = self.wallets.get(wallet_name)
        if not wallet:
            return None

        if wallet["type"] == "solana":
            return self._get_solana_balance(wallet["address"])
        elif wallet["type"] == "ethereum":
            return self._get_ethereum_balance(wallet["address"])
        return None

    def _get_solana_balance(self, address: str
                            ) -> Optional[WalletBalance]:
        rpc_url = os.getenv(
            "SOLANA_RPC_URL",
            "https://api.mainnet-beta.solana.com",
        )
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address],
        }
        try:
            resp = requests.post(
                rpc_url, json=payload, timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                lamports = data.get("result", {}).get("value", 0)
                sol_amount = lamports / 1_000_000_000
                usd_value = sol_amount * self._get_sol_price()
                return WalletBalance(
                    chain="solana",
                    token="SOL",
                    balance=sol_amount,
                    usd_value=usd_value,
                )
        except Exception:
            pass
        return None

    def _get_ethereum_balance(self, address: str
                              ) -> Optional[WalletBalance]:
        rpc_url = os.getenv(
            "ETHEREUM_RPC_URL",
            "https://eth.llamarpc.com",
        )
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getBalance",
            "params": [address, "latest"],
        }
        try:
            resp = requests.post(
                rpc_url, json=payload, timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                wei = int(data.get("result", "0"), 16)
                eth_amount = wei / 1e18
                usd_value = eth_amount * self._get_eth_price()
                return WalletBalance(
                    chain="ethereum",
                    token="ETH",
                    balance=eth_amount,
                    usd_value=usd_value,
                )
        except Exception:
            pass
        return None

    def _get_sol_price(self) -> float:
        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=solana&vs_currencies=usd",
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get(
                    "solana", {}).get("usd", 0.0)
        except Exception:
            pass
        return 0.0

    def _get_eth_price(self) -> float:
        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=ethereum&vs_currencies=usd",
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get(
                    "ethereum", {}).get("usd", 0.0)
        except Exception:
            pass
        return 0.0

    def list_wallets(self) -> List[dict]:
        return [
            {"name": name, "type": w["type"],
             "address": w["address"]}
            for name, w in self.wallets.items()
        ]

    # --- B4: realized-gas ledger (so net profit reflects actual chain cost) ---
    def record_realized_gas(self, chain: str, usd: float, note: str = "") -> None:
        """Append a realized-gas cost row to `gas_ledger.json`.

        Never raises. A missing/invalid file is treated as empty. This is the chain-cost
        side of the ledger that the A3 net-profit report was missing (was a 0.0 stub).
        """
        try:
            usd = float(usd)
        except (TypeError, ValueError):
            return
        if usd <= 0:
            return
        ledger_path = self.root / "gas_ledger.json"
        rows = []
        if ledger_path.exists():
            try:
                rows = json.loads(ledger_path.read_text()).get("rows", [])
            except Exception:
                rows = []
        import time as _t
        rows.append({"chain": chain, "usd": usd, "note": note, "at": _t.time()})
        # H28: invalidate the cached total so the next read reflects the new row.
        self._gas_total_cache = None
        try:
            ledger_path.write_text(json.dumps({"rows": rows}, indent=2, default=str))
        except Exception:
            pass

    def total_realized_gas_usd(self) -> float:
        """Sum of realized-gas costs (0.0 if none / file missing).

        H28: cached on the instance so repeated `get_revenue_report` calls (UI refresh,
        multiple dashboards) don't re-parse `gas_ledger.json` every time. The cache is
        invalidated by `record_realized_gas`, which is the only writer.
        """
        if self._gas_total_cache is not None:
            return self._gas_total_cache
        ledger_path = self.root / "gas_ledger.json"
        if not ledger_path.exists():
            self._gas_total_cache = 0.0
            return 0.0
        try:
            rows = json.loads(ledger_path.read_text()).get("rows", [])
            self._gas_total_cache = float(
                sum(float(r.get("usd", 0.0)) for r in rows)
            )
        except Exception:
            self._gas_total_cache = 0.0
        return self._gas_total_cache
