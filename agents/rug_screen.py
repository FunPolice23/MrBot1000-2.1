"""agents/rug_screen.py — DeFi rug/pull screening (B5).

Problem closed: the DeFi scanner hardcoded `risk_level="low"` and had NO rug/pull screening
— a 2-day-old, unaudited, TVL-collapsing farm would pass `filter_by_risk` as "low". Yield
farming is where *capital* (not just gas) is lost, so B5 adds a real gate.

The screen is heuristic on injectable signals until live oracles (on-chain contract age, TVL
history, honeypot sim) are wired — exactly like B3's `eligibility_fn` / B4's gas oracle. The
*gating logic* is real: a failed rug screen cannot pass.
"""

from dataclasses import dataclass, field
from typing import List, Optional

# Well-known protocols treated as audited unless a signal explicitly says otherwise.
TRUSTED_PROTOCOLS = {"lido", "aave", "raydium"}

# Tunable thresholds.
MIN_CONTRACT_AGE_DAYS = 30          # a contract younger than this is a red flag
TVL_DROP_PCT = 0.5                  # recent TVL drop > 50% => collapse
# H34: APY red-flag is chain-aware. Solana yields (LP / treasury farms) routinely exceed
# Ethereum levels, so a single global threshold misfires as a false "unsustainable" flag.
APY_RED_FLAG_PCT = 1000.0           # ETH/other: APY above this is unsustainable
APY_RED_FLAG_PCT_SOLANA = 2000.0    # Solana tolerates higher headline APYs


@dataclass
class RugScreenResult:
    passed: bool
    risk_level: str                 # "low" | "medium" | "high"
    reasons: List[str] = field(default_factory=list)


def _level_from(flags: List[str], fails: List[str]) -> str:
    if fails:
        return "high"
    if flags:
        return "medium"
    return "low"


def screen_opportunity(opp,
                        *,
                        contract_age_days: Optional[float] = None,
                        audit_verified: Optional[bool] = None,
                        tvl_history: Optional[List[float]] = None,
                        honeypot: Optional[bool] = None,
                        override: Optional[RugScreenResult] = None) -> RugScreenResult:
    """Screen one DeFi opportunity for rug/pull risk.

    - `override` wins (tests/callers inject a precise verdict).
    - All other signals are optional: missing = "unknown", handled fail-soft (a non-trusted,
      unaudited opp with no signals is flagged `medium`, never silently `low`).
    """
    if override is not None:
        return override

    protocol = (getattr(opp, "protocol", "") or "").lower()
    apy = float(getattr(opp, "apy_percent", 0.0) or 0.0)
    tvl = float(getattr(opp, "tvl_usd", 0.0) or 0.0)

    fails: List[str] = []
    flags: List[str] = []

    trusted = protocol in TRUSTED_PROTOCOLS

    # Honeypot is a hard fail regardless of trust.
    if honeypot is True:
        fails.append("honeypot detected")

    # Unknown / young contract.
    if contract_age_days is not None and contract_age_days < MIN_CONTRACT_AGE_DAYS:
        fails.append(f"contract age {contract_age_days:.0f}d < {MIN_CONTRACT_AGE_DAYS}d")

    # TVL collapse: compare latest vs peak in the recent history window.
    if tvl_history and len(tvl_history) >= 2:
        peak = max(tvl_history)
        latest = tvl_history[-1]
        if peak > 0 and (peak - latest) / peak > TVL_DROP_PCT:
            drop = (peak - latest) / peak * 100.0
            fails.append(f"tvl collapsed {drop:.0f}%")

    # Unsustainable APY (H34: chain-aware — Solana tolerates higher headline yields).
    chain = (getattr(opp, "chain", "") or "").lower()
    apy_cap = APY_RED_FLAG_PCT_SOLANA if chain == "solana" else APY_RED_FLAG_PCT
    if apy > apy_cap:
        flags.append(f"unsustainable apy {apy:.0f}% (> {apy_cap:.0f}% {chain or 'chain'} cap)")

    # Audit status.
    if trusted:
        if audit_verified is False:
            flags.append("trusted protocol but audit unverified")
    else:
        if audit_verified is False:
            fails.append("unaudited protocol")
        elif audit_verified is None:
            # Unknown protocol with no audit signal -> flag, do not silently pass as low.
            flags.append("unaudited/unverified protocol")

    risk_level = _level_from(flags, fails)
    # A non-trusted opp with no signals at all must never read as "low".
    if risk_level == "low" and not trusted:
        risk_level = "medium"
        flags.append("no verification signals; defaulting to medium")

    return RugScreenResult(passed=not fails, risk_level=risk_level, reasons=flags + fails)
