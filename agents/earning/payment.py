"""Payment-side earning services."""

from __future__ import annotations

from typing import Any


def record_realized_gas(
    *,
    db_path: str,
    chain: str,
    usd: float,
    note: str = "",
) -> None:
    """Record realized blockchain gas without allowing ledger errors to escape."""
    try:
        from agents.integrations.wallet_manager import WalletManager, resolve_wallet_root

        wallet = WalletManager(
            root_folder=str(resolve_wallet_root(db_path))
        )
        wallet.record_realized_gas(chain, usd, note=note)
    except Exception:
        pass


def total_realized_gas(*, db_path: str) -> float:
    """Read realized gas for reporting; unavailable ledgers contribute zero."""
    try:
        from agents.integrations.wallet_manager import WalletManager, resolve_wallet_root

        wallet = WalletManager(
            root_folder=str(resolve_wallet_root(db_path))
        )
        return float(wallet.total_realized_gas_usd() or 0.0)
    except Exception:
        return 0.0


__all__ = ["record_realized_gas", "total_realized_gas"]
