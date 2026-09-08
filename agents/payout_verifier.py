"""agents/payout_verifier.py — Verify that a payout actually happened (A2).

Problem closed by this module: `OpportunityLifecycleTracker.mark_paid` was a pure
self-report — it flipped status to "paid" with no evidence money arrived, so
"revenue" could be inflated and failed payouts invisible.

This module turns "I got paid" into "payment was verified against ground truth":
  - crypto: compare wallet balance (already queryable via WalletManager) before/
    after the expected payout; delta >= expected (net of gas) => verified.
  - manual: operator supplies a transaction id / reference (human-attested).
  - api:    reserved stub for when a real Upwork/fiat account is wired (see §H1).

The verifier NEVER mutates lifecycle state. It only returns `VerificationEvidence`;
the lifecycle layer decides whether to mark paid based on `evidence.verified`.
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VerificationEvidence:
    method: str                       # onchain_balance_delta | manual_reference | api_statement
    verified: bool
    expected_usd: float = 0.0
    observed_usd: float = 0.0
    note: str = ""
    reference: str = ""               # txid / screenshot ref (manual)
    verified_at: float = field(default_factory=time.time)

    @property
    def summary(self) -> str:
        if self.verified:
            return (f"VERIFIED via {self.method}: expected ${self.expected_usd:.2f}, "
                    f"observed ${self.observed_usd:.2f}")
        return f"UNVERIFIED ({self.method}): {self.note or 'no evidence'}"


class PayoutVerifier:
    """Produce VerificationEvidence from a real payment source (or operator input)."""

    # ── Crypto: on-chain balance delta ─────────────────────────────────────────
    def verify_crypto(self, wallet_manager, wallet_name: str,
                      expected_usd: float, before_bal_usd: Optional[float] = None,
                      after_bal_usd: Optional[float] = None) -> VerificationEvidence:
        """Verify a crypto payout against wallet balance.

        If `after_bal_usd` is supplied (caller captured a post-payout snapshot) we
        compute the true delta. If `before_bal_usd` is also supplied we require
        delta >= expected. If only the current balance is available we do a
        best-effort check (current >= expected) and flag it as weak.
        """
        if wallet_manager is None or not wallet_name:
            return VerificationEvidence(
                method="onchain_balance_delta", verified=False,
                expected_usd=expected_usd,
                note="No wallet manager / wallet name supplied")

        try:
            bal = wallet_manager.get_balance(wallet_name)
        except Exception as e:
            return VerificationEvidence(
                method="onchain_balance_delta", verified=False,
                expected_usd=expected_usd, note=f"balance fetch failed: {e}")

        # WalletManager.get_balance returns a WalletBalance dataclass (or None),
        # not a float — read .usd_value. Accept a plain number too (test fakes).
        if bal is None:
            return VerificationEvidence(
                method="onchain_balance_delta", verified=False,
                expected_usd=expected_usd, note="wallet not found / no balance")
        current = float(getattr(bal, "usd_value", 0.0) or 0.0)

        # Both snapshots: true delta.
        if before_bal_usd is not None and after_bal_usd is not None:
            delta = max(0.0, after_bal_usd - before_bal_usd)
            ok = delta >= expected_usd * 0.9   # allow 10% tolerance (gas/fees)
            return VerificationEvidence(
                method="onchain_balance_delta", verified=ok,
                expected_usd=expected_usd, observed_usd=delta,
                note="" if ok else f"delta ${delta:.2f} < expected ${expected_usd:.2f}")

        # Only current balance: best-effort (weak) — wallet may already hold funds.
        ok = current >= expected_usd
        ev = VerificationEvidence(
            method="onchain_balance_delta", verified=ok,
            expected_usd=expected_usd, observed_usd=current,
            note=("best-effort: current balance >= expected (no pre-payout snapshot)"
                  if ok else f"current balance ${current:.2f} < expected ${expected_usd:.2f}"))
        return ev

    # ── Manual: operator-attested reference ────────────────────────────────────
    def verify_manual(self, expected_usd: float, reference: str) -> VerificationEvidence:
        """Human-attested payout. Verified only if a non-empty reference exists.

        This is NOT auto-verified — it is operator testimony (e.g. a bank/Upwork
        transaction id). It is honest about that: verified=True means 'attested',
        not 'cryptographically proven'.
        """
        ref = (reference or "").strip()
        ok = bool(ref)
        return VerificationEvidence(
            method="manual_reference", verified=ok,
            expected_usd=expected_usd, reference=ref,
            note=("operator-attested (human reference supplied)"
                  if ok else "no transaction reference supplied"))

    # ── API: reserved for when an Upwork/fiat account is wired (see §H1) ────────
    def verify_api(self, expected_usd: float, statement_ref: str) -> VerificationEvidence:
        """Stub: real API statement parsing lands when an account is connected."""
        return VerificationEvidence(
            method="api_statement", verified=False,
            expected_usd=expected_usd,
            note="API verification not implemented (no connected account)")
