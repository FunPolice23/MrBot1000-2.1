"""
agents/defi_scanner.py — DeFi yield farming scanner for MrBot1000.
"""

import time
from typing import List
from dataclasses import dataclass, field

import requests


@dataclass
class DeFiOpportunity:
    id: str
    protocol: str = ""
    type: str = ""
    token_symbol: str = ""
    apy_percent: float = 0.0
    tvl_usd: float = 0.0
    risk_level: str = "low"
    min_deposit_usd: float = 0.0
    chain: str = "ethereum"
    url: str = ""
    status: str = "new"
    found_at: float = 0.0


class DeFiScanner:
    """Scans DeFi protocols for yield opportunities."""

    PROTOCOLS = {
        "lido": {
            "api": "https://api.lido.fi/v1/staking/apr",
            "chain": "ethereum",
        },
        "aave": {
            "api": "https://api.aave.com/data/protocols",
            "chain": "ethereum",
        },
        "raydium": {
            "api": "https://api.raydium.io/v2/sdk/pools",
            "chain": "solana",
        },
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MrBot1000/1.0",
            "Accept": "application/json",
        })

    def scan_all(self) -> List[DeFiOpportunity]:
        """Scan all configured protocols."""
        opportunities = []

        for name, config in self.PROTOCOLS.items():
            try:
                opps = self._scan_protocol(name, config)
                opportunities.extend(opps)
            except Exception:
                continue
            time.sleep(1)

        return opportunities

    def _scan_protocol(self, name: str, config: dict
                        ) -> List[DeFiOpportunity]:
        opportunities = []

        try:
            resp = self.session.get(
                config["api"], timeout=15,
            )
            if resp.status_code != 200:
                return opportunities

            data = resp.json()

            if name == "lido":
                apr_data = data if isinstance(data, dict) else {}
                for key, value in apr_data.items():
                    if isinstance(value, (int, float)):
                        opportunities.append(DeFiOpportunity(
                            id=f"lido_{key}",
                            protocol="Lido",
                            type="staking",
                            token_symbol=key.upper(),
                            apy_percent=float(value),
                            risk_level="low",
                            chain="ethereum",
                            url=f"https://lido.fi/staking/{key}",
                            found_at=time.time(),
                        ))

        except Exception:
            pass

        return opportunities

    def filter_by_risk(self, opportunities: List[DeFiOpportunity],
                       max_risk: str = "medium", **signals
                       ) -> List[DeFiOpportunity]:
        # B5: also reject anything a rug screen would fail. Signals (contract age / audit /
        # tvl history / honeypot) are forwarded so a caller with live data gets a real gate;
        # without signals the screen is fail-soft (unknown protocols flagged medium, not low).
        screened, _ = self.screen_rug_pull(opportunities, **signals)
        risk_order = {"low": 0, "medium": 1, "high": 2}
        max_val = risk_order.get(max_risk, 1)
        return [
            opp for opp in screened
            if risk_order.get(opp.risk_level, 2) <= max_val
        ]

    def filter_by_min_tvl(self, opportunities: List[DeFiOpportunity],
                          min_tvl_usd: float = 1000
                          ) -> List[DeFiOpportunity]:
        return [
            opp for opp in opportunities
            if opp.tvl_usd >= min_tvl_usd
        ]

    # --- B5: rug/pull screening ---
    def screen_rug_pull(self, opportunities: List[DeFiOpportunity],
                        **signals) -> tuple:
        """Screen opportunities for rug/pull risk. Returns (passed, results).

        `signals` are injectable (contract_age_days / audit_verified / tvl_history /
        honeypot per opp id) — see `agents.rug_screen`. With no signals, screening is a
        pure heuristic on `protocol`/known fields (trusted protocols pass; unknown/unaudited
        are flagged, never silently `low`). The failed set cannot pass `filter_by_risk`.
        """
        from agents.rug_screen import screen_opportunity

        passed = []
        results = {}
        for opp in opportunities:
            sig = {}
            for key in ("contract_age_days", "audit_verified", "tvl_history", "honeypot"):
                if opp.id in signals.get(key, {}):
                    sig[key] = signals[key][opp.id]
            res = screen_opportunity(opp, **sig)
            results[opp.id] = res
            if res.passed:
                # Promote the scanned risk level so the existing risk filter honors it.
                opp.risk_level = res.risk_level
                passed.append(opp)
        return passed, results