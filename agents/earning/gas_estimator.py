"""agents/gas_estimator.py — Gas-vs-value estimate for claims (B4).

Problem closed: there was NO gas awareness — a claim could cost more in gas than the
airdrop is worth, and realized chain costs were never subtracted from net profit (the
A3 report's `gas_est` was a 0.0 stub). B4 adds a gas *estimate* + a gas-vs-value decision
+ a realized-gas ledger so net profit reflects actual chain cost.

The estimate is intentionally a coarse, env-configurable constant until a live RPC gas
oracle is wired — but the decision logic and ledger are real and correct, so when a live
estimate is plugged in, skip + accounting work immediately.
"""

import os
from typing import Optional

# Fallback defaults (USD) used only when no env override / live oracle is set. These are
# hard-coded constants here (NOT read from env at import) so a malformed env value can never
# crash module import. Tunable per-chain via EST_GAS_USD_<CHAIN.upper()> at call time.
_DEFAULT_GAS_USD = {
    "ethereum": 0.50,
    "solana": 0.01,
}


def estimate_gas_usd(chain: str = "ethereum", op_type: str = "claim",
                     override: Optional[float] = None) -> float:
    """Estimate the gas cost (USD) of an on-chain op.

    - `override` (if given) wins — lets tests/callers inject a precise value.
    - Else env `EST_GAS_USD_<CHAIN.upper()>` if set (re-read every call, never cached),
      else the built-in default for the chain.
    - Returns 0.0 for unknown chains (don't block on a missing estimate; the caller's
      gas-vs-value check treats 0 gas as "free").
    `EST_GAS_USD_ETH` is intentionally NOT read (the key is `<CHAIN.upper()>` = `ETHEREUM`);
    documented in CHANGELOG/H21.
    """
    if override is not None:
        try:
            return float(override)
        except (TypeError, ValueError):
            return 0.0
    # Re-read env at call time so live config changes are honored (B21). Env var is
    # EST_GAS_USD_ETHEREUM (not _ETH) — see H21.
    env_val = os.getenv(f"EST_GAS_USD_{chain.upper()}", "").strip()
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return float(_DEFAULT_GAS_USD.get(chain.lower(), 0.0))


def gas_exceeds_value(gas_usd: float, expected_usd: float) -> bool:
    """True when the gas estimate is greater than the expected airdrop value.

    Equal is NOT "exceeds" (a break-even claim is allowed; skip only when strictly worse).
    """
    try:
        return float(gas_usd) > float(expected_usd)
    except (TypeError, ValueError):
        return False
