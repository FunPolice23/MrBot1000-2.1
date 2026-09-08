"""agents/chain_verifier.py — On-chain verification for airdrops (B3).

Problem closed: the airdrop scanner's "safe" label is regex-over-feed-text only — a
phishing airdrop with clean copy passes as low-risk. B3 adds REAL on-chain checks:

  1. read_balance(wm, name)         — safe on-chain balance read (never raises).
  2. verify_eligibility(...)         — eligibility confirmed ON-CHAIN, not by the
                                       scanner's untrusted risk label.
  3. verify_claim_receipt(...)       — post-claim balance delta proves value was
                                       actually received (catches "claim did nothing"
                                       and "claim drained the wallet" phishing).

All functions are pure / injectable so they can be unit-tested with fake balances and
run mock-first with no live RPC. Live signing remains gated by B2.
"""

from dataclasses import dataclass
from typing import Optional, Callable

from agents.wallet_manager import WalletBalance


@dataclass
class EligibilityReport:
    on_chain_checked: bool
    eligible: bool
    scanner_risk_untrusted: bool = True   # the scanner label is NEVER sufficient alone
    reason: str = ""


@dataclass
class ReceiptReport:
    before_usd: float
    after_usd: float
    delta_usd: float
    expected_usd: float
    min_ratio: float
    received_usd: float
    verified: bool
    note: str = ""
    # H32: distinguish "balance read failed (RPC down / refused)" from a real "0 balance".
    # A None balance is now surfaced so a down-RPC can't masquerade as "received $0, not a
    # drain". `read_failed=True` on either side forces `verified=False` and a clear note.
    before_read_failed: bool = False
    after_read_failed: bool = False


def read_balance(wm, wallet_name: str) -> Optional[WalletBalance]:
    """Safely read an on-chain balance. Returns None on any failure (no raise).

    Uses `WalletManager.get_balance` (which hits the chain RPC). Callers must never
    feed the resulting value into an LLM without redaction (see wallet_crypto).
    """
    if wm is None or not wallet_name:
        return None
    try:
        return wm.get_balance(wallet_name)
    except Exception:
        return None


def verify_eligibility(
    wm,
    wallet_name: str,
    airdrop=None,
    eligibility_fn: Optional[Callable[[str], bool]] = None,
) -> EligibilityReport:
    """Confirm airdrop eligibility ON-CHAIN.

    - `on_chain_checked` is True only if we actually reached the chain.
    - `eligible` is True only when the chain confirms (or a readable, funded balance
      exists as the minimal signal). The scanner's risk_level is explicitly NOT enough.
    - `eligibility_fn(address) -> bool` lets a real contract `isEligible` view strengthen
      the check; default requires a readable balance whose `usd_value > 0`.
    """
    bal = read_balance(wm, wallet_name)
    if bal is None:
        return EligibilityReport(
            on_chain_checked=False,
            eligible=False,
            scanner_risk_untrusted=True,
            reason="could not read on-chain balance (no wallet / RPC down / refused)",
        )
    # on-chain signal obtained
    if eligibility_fn is not None:
        try:
            ok = bool(eligibility_fn(getattr(bal, "address", "") or ""))
        except Exception:
            ok = False
        return EligibilityReport(
            on_chain_checked=True,
            eligible=ok,
            scanner_risk_untrusted=True,
            reason=("contract isEligible=True" if ok else "contract isEligible=False"),
        )
    # default minimal signal: a funded, readable balance
    funded = float(getattr(bal, "usd_value", 0.0) or 0.0) > 0.0
    return EligibilityReport(
        on_chain_checked=True,
        eligible=funded,
        scanner_risk_untrusted=True,
        reason=("on-chain balance readable & funded" if funded
                else "on-chain balance readable but empty (not eligible by default)"),
    )


def verify_claim_receipt(
    before: Optional[WalletBalance],
    after: Optional[WalletBalance],
    expected_usd: float,
    min_ratio: float = 0.5,
) -> ReceiptReport:
    """Verify a claim actually delivered value, via on-chain balance delta.

    `received_usd = (after.usd_value or 0) - (before.usd_value or 0)`.
    - `verified` iff `received_usd >= expected_usd * min_ratio`.
    - Catches phishing where the claim delivered nothing (or drained the wallet, since
      a negative delta also fails the >= check).
    Missing `before`/`after` (None) are treated as 0 USD (failed receipt). A None that is
    due to a read failure (RPC down) is flagged via `before_read_failed`/`after_read_failed`
    so it isn't confused with a genuine zero balance (H32).
    """
    before_failed = before is None
    after_failed = after is None
    before_usd = float(getattr(before, "usd_value", 0.0) or 0.0)
    after_usd = float(getattr(after, "usd_value", 0.0) or 0.0)
    delta = after_usd - before_usd
    received = max(delta, 0.0)
    # H32: a balance read that FAILED (None because RPC was down, not because balance is 0)
    # must never verify and must explain why, so a down-RPC can't mask a real drain.
    read_failed = before_failed or after_failed
    verified = (not read_failed) and (
        received >= float(expected_usd or 0.0) * float(min_ratio)
    )
    note = ""
    if read_failed:
        note = ("balance read FAILED (RPC down / refused) — cannot confirm receipt; "
                "treat as UNVERIFIED, not as 'received $0'")
    elif delta < 0:
        note = "phishing/slip: wallet balance DECREASED after claim"
    elif received == 0:
        note = "phishing: no value received from claim"
    elif not verified:
        note = (f"received ${received:.2f} < expected "
                f"${float(expected_usd or 0.0):.2f}*min_ratio {min_ratio}")
    return ReceiptReport(
        before_usd=before_usd,
        after_usd=after_usd,
        delta_usd=delta,
        expected_usd=float(expected_usd or 0.0),
        min_ratio=float(min_ratio),
        received_usd=received,
        verified=verified,
        note=note,
        before_read_failed=before_failed,
        after_read_failed=after_failed,
    )
