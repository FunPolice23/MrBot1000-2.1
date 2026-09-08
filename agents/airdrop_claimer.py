"""
agents/airdrop_claimer.py — Simulate-then-confirm airdrop claims for MrBot1000.

B2: claims NEVER auto-execute. `claim()` builds a `ClaimPlan` (simulate) and only
performs the network action when a callable `confirm_cb` explicitly approves it.
`confirm_cb=None` (the default, used by the pipeline) BLOCKS — no action is taken,
the plan is returned for human review. This mirrors the A1 human-review gate.
"""

import time
import re
from dataclasses import dataclass
from typing import List, Callable, Optional

import requests
from bs4 import BeautifulSoup

from agents.airdrop_scanner import AirdropOpportunity


@dataclass
class ClaimPlan:
    """A simulated claim: what *would* happen, before any network action."""
    airdrop_id: str
    title: str
    target_url: str
    action_url: Optional[str]
    risk_level: str
    expected_value_usd: float
    estimated_cost_usd: float = 0.0   # gas estimate (B4); was 0.0 placeholder (H11)
    gas_exceeds_value: bool = False    # B4: gas estimate > expected value => skip
    would_connect_wallet: bool = True
    safe_to_claim: bool = False
    receipt = None  # ReceiptReport (B3) attached after a confirmed claim, else None
    receipt_evidence_id: Optional[str] = None  # v2.0.34aq: EvidenceStore id for the receipt


class AirdropClaimer:
    """Simulates airdrop claims; requires explicit confirmation to execute."""

    def __init__(self, session: requests.Session = None, evidence_store=None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            ),
        })
        self.claimed: List[str] = []
        self.failed: List[str] = []
        # v2.0.34aq: optional EvidenceStore so on-chain receipts become Evidence
        # (chain_verifier is a natural producer; see blueprint point 10).
        self.evidence_store = evidence_store

    # --- simulate ---
    def plan(self, airdrop: AirdropOpportunity) -> ClaimPlan:
        """Build a claim plan WITHOUT touching the network (pure simulation).

        `safe_to_claim` uses the existing heuristic (risk/KYC/dedup). The plan is
        returned for human review; nothing is executed and NO network call is made
        here (the action URL is only resolved at confirmed-execution time, so a
        malicious `claim_url` can't even be fetched without explicit approval).
        B4: also estimates gas and flags when gas would exceed the expected value.
        """
        from agents.gas_estimator import estimate_gas_usd, gas_exceeds_value

        safe = self.is_safe_to_claim(airdrop)
        expected = float(getattr(airdrop, "estimated_value_usd", 0.0) or 0.0)
        chain = getattr(airdrop, "chain", "ethereum") or "ethereum"
        gas = estimate_gas_usd(chain=chain, op_type="claim")
        return ClaimPlan(
            airdrop_id=airdrop.id,
            title=getattr(airdrop, "title", airdrop.id),
            target_url=airdrop.claim_url,
            action_url=None,
            risk_level=airdrop.risk_level,
            expected_value_usd=expected,
            estimated_cost_usd=gas,
            gas_exceeds_value=gas_exceeds_value(gas, expected),
            would_connect_wallet=True,
            safe_to_claim=safe,
        )

    def is_safe_to_claim(self, airdrop: AirdropOpportunity) -> bool:
        """Determine if an airdrop is safe to auto-claim (heuristic only)."""
        if airdrop.risk_level == "high":
            return False
        if getattr(airdrop, "requires_kyc", False):
            return False
        if airdrop.id in self.claimed:
            return False
        return True

    def _find_action_url(self, airdrop: AirdropOpportunity) -> Optional[str]:
        """Best-effort: extract the claim action URL from the claim page.

        Uses a throwaway GET (read-only, no state change) — safe to call during
        simulation. Returns the action URL or None.
        """
        try:
            resp = self.session.get(airdrop.claim_url, timeout=15)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            claim_btn = soup.find(
                "button", string=re.compile(r"claim|connect|join", re.I),
            )
            if not claim_btn:
                claim_btn = soup.select_one(
                    "[class*='claim'], [id*='claim'], a[href*='claim']",
                )
            if claim_btn:
                return claim_btn.get("formaction") or claim_btn.get("href")
        except Exception:
            return None
        return None

    # --- confirm-then-execute ---
    def claim(self, airdrop: AirdropOpportunity,
              confirm_cb: Optional[Callable[[ClaimPlan], bool]] = None,
              wallet_manager=None,
              wallet_name: Optional[str] = None) -> ClaimPlan:
        """Simulate, then execute ONLY if confirmed.

        - Always returns a ClaimPlan (the simulation).
        - If `confirm_cb is None` → BLOCKED: no network action, plan returned.
        - If `confirm_cb` is callable → it is invoked with the plan; the network
          claim fires only when it returns truthy. Non-callable ⇒ BLOCKED.
        - If a `wallet_manager` + `wallet_name` are supplied, an ON-CHAIN receipt is
          attached (B3): balance read before/after the claim to prove value was
          actually received (catches phishing "claim did nothing" cases). This only
          runs post-confirmation, so no extra attack surface is added.
        """
        from agents.chain_verifier import read_balance, verify_claim_receipt

        plan = self.plan(airdrop)
        if not callable(confirm_cb):
            # Fail-safe: never act without an explicit confirmation callback.
            return plan

        if not confirm_cb(plan):
            self.failed.append(airdrop.id)
            return plan

        if not plan.safe_to_claim:
            self.failed.append(airdrop.id)
            return plan

        # Resolve the actual action URL only now (post-confirmation): a malicious
        # claim_url is never fetched until a human has explicitly approved the plan.
        before_bal = read_balance(wallet_manager, wallet_name) if wallet_manager else None
        action = self._find_action_url(airdrop)
        plan.action_url = action
        target = action or plan.target_url
        try:
            resp = self.session.get(target, timeout=15)
            if resp.status_code == 200:
                self.claimed.append(airdrop.id)
        except Exception:
            self.failed.append(airdrop.id)

        # B3: on-chain receipt — prove value was received (not a phishing no-op/drain).
        if wallet_manager is not None:
            after_bal = read_balance(wallet_manager, wallet_name)
            plan.receipt = verify_claim_receipt(
                before_bal, after_bal, plan.expected_value_usd,
            )
            # v2.0.34aq: turn the receipt into Evidence in the store (chain_verifier -> Evidence).
            if self.evidence_store is not None and plan.receipt is not None:
                try:
                    from agents.evidence_factory import from_receipt_report
                    ev = from_receipt_report(plan.receipt, subject_id=airdrop.id,
                                             wallet_name=wallet_name)
                    self.evidence_store.record(ev)
                    plan.receipt_evidence_id = ev.id
                except Exception:
                    pass
        # B4: record the realized gas estimate into the ledger so net profit reflects
        # the chain cost of this claim (the A3 report reads it). Only after a confirmed
        # claim — never for the blocked/simulate-only path.
        if wallet_manager is not None and plan.estimated_cost_usd > 0:
            try:
                chain = "ethereum"
                if hasattr(wallet_manager, "wallets") and wallet_name in getattr(wallet_manager, "wallets", {}):
                    chain = wallet_manager.wallets[wallet_name].get("type", "ethereum")
                wallet_manager.record_realized_gas(chain, plan.estimated_cost_usd,
                                                    note=f"claim {airdrop.id}")
            except Exception:
                pass
        return plan

    def claim_batch(self, airdrops: List[AirdropOpportunity],
                    confirm_cb: Optional[Callable[[ClaimPlan], bool]] = None
                    ) -> dict:
        """Simulate/claim a batch. Without `confirm_cb`, only plans are produced
        (no execution) and every item is reported as BLOCKED."""
        results = {
            "claimed": 0, "failed": 0, "blocked": 0, "details": [],
            "plans": [],
        }
        for airdrop in airdrops:
            plan = self.claim(airdrop, confirm_cb=confirm_cb)
            results["plans"].append(plan)
            if not callable(confirm_cb):
                results["blocked"] += 1
                results["details"].append(f"BLOCKED: {plan.title[:60]}")
            elif airdrop.id in self.claimed:
                results["claimed"] += 1
                results["details"].append(f"CLAIMED: {plan.title[:60]}")
            else:
                results["failed"] += 1
                results["details"].append(f"FAILED: {plan.title[:60]}")
            time.sleep(2)
        return results
