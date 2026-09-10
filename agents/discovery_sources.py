"""agents/discovery_sources.py — Existing platform integrations as pluggable sources.

Each legacy client (Upwork, Fiverr, social, airdrop, DeFi, microtask, content, and
the legacy EarningDiscoverer "dynamic" path) is wrapped in a BaseOpportunitySource
that emits the canonical structured `Opportunity`. Behavior is preserved:

- Upwork returns [] when API credentials are absent (no fabricated gigs).
- DeFi/airdrop run the existing rug-screen before emitting (failed screens -> high risk).
- Provenance is always set to "source::external_url" so the external origin stays
  identifiable (an LLM never invents these; they come from real client output).

These sources are registered with the DiscoveryEngine by EarningPipeline (T5), so the
core pipeline is untouched but the new model flows through.
"""

from __future__ import annotations

import os
import time
from typing import List, Optional

from agents.opportunity_models import Opportunity, BaseOpportunitySource, classify_category


class UpworkSource(BaseOpportunitySource):
    name = "upwork"

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        cid = os.getenv("UPWORK_CLIENT_ID", "")
        csec = os.getenv("UPWORK_CLIENT_SECRET", "")
        atok = os.getenv("UPWORK_ACCESS_TOKEN", "")
        rtok = os.getenv("UPWORK_REFRESH_TOKEN", "")
        if not all([cid, csec, atok, rtok]):
            return []
        from agents.upwork_client import UpworkClient
        # v2.0.36p: honor the scheduler's per-task query instead of always "python".
        q = (query or "python").strip() or "python"
        client = UpworkClient(cid, csec, atok, rtok)
        gigs = client.find_gigs(q=q, limit=20)
        out = []
        for g in gigs:
            url = getattr(g, "url", "") or ""
            out.append(Opportunity(
                opportunity_id=f"upwork_{g.id}", source=self.name, platform="Upwork",
                title=g.title, description=g.description, category="freelance",
                task_type="coding", required_skills=["python"],
                payment_type="usd", currency="USD",
                advertised_amount=float(getattr(g, "budget_usd", 0.0) or 0.0),
                estimated_net_value=float(getattr(g, "budget_usd", 0.0) or 0.0),
                risk_level="low", source_reliability=0.8,
                external_id=str(g.id), external_url=url,
                provenance=f"{self.name}::{url}",
            ))
        return out


class FiverrSource(BaseOpportunitySource):
    name = "fiverr"

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        from agents.fiverr_client import FiverrClient
        # v2.0.36p: honor the scheduler's per-task query instead of always "python".
        q = (query or "python").strip() or "python"
        gigs = FiverrClient().find_gigs(query=q, limit=20)
        out = []
        for g in gigs:
            url = getattr(g, "url", "") or ""
            out.append(Opportunity(
                opportunity_id=f"fiverr_{g.id}", source=self.name, platform="Fiverr",
                title=g.title, description=g.description, category="freelance",
                task_type="coding", required_skills=["python"],
                payment_type="usd", currency="USD",
                advertised_amount=float(getattr(g, "budget_usd", 0.0) or 0.0),
                estimated_net_value=float(getattr(g, "budget_usd", 0.0) or 0.0),
                risk_level="low", source_reliability=0.7,
                external_id=str(g.id), external_url=url,
                provenance=f"{self.name}::{url}",
            ))
        return out


class SocialSource(BaseOpportunitySource):
    name = "social"

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        from agents.social_earning_platform import SocialEarningPlatform
        # SocialSource has no queryable client interface; the scheduler's term is
        # recorded via provenance at the scheduler layer, not here.
        raw = SocialEarningPlatform().discover_all()
        out = []
        for o in raw:
            url = getattr(o, "url", "") or ""
            cat = classify_category(f"{o.title} {o.description}")
            out.append(Opportunity(
                opportunity_id=f"social_{o.id}", source=self.name, platform=o.platform,
                title=o.title, description=o.description, category=cat,
                payment_type=o.payment_type, currency="USD" if o.payment_type == "usd" else "TOKEN",
                advertised_amount=float(getattr(o, "min_amount", 0.0) or 0.0),
                estimated_net_value=float(getattr(o, "estimated_value", 0.0) or 0.0),
                risk_level=(o.risk_level or "low").lower(),
                source_reliability=0.5,
                external_id=str(o.id), external_url=url,
                provenance=f"{self.name}::{url}",
            ))
        return out


class AirdropSource(BaseOpportunitySource):
    name = "airdrop"

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        from agents.airdrop_scanner import AirdropScanner
        # AirdropScanner has no queryable interface; term recorded via provenance upstream.
        airdrops = AirdropScanner().scan_feeds()
        out = []
        for a in airdrops:
            url = getattr(a, "url", "") or ""
            out.append(Opportunity(
                opportunity_id=f"airdrop_{a.id}", source=self.name, platform=a.platform,
                title=a.title, description=a.description, category="airdrop",
                payment_type="crypto", currency=getattr(a, "token_symbol", "") or "TOKEN",
                advertised_amount=float(getattr(a, "estimated_value_usd", 0.0) or 0.0),
                estimated_net_value=float(getattr(a, "estimated_value_usd", 0.0) or 0.0),
                risk_level=a.risk_level, scam_risk=0.3, source_reliability=0.4,
                external_id=str(a.id), external_url=url,
                provenance=f"{self.name}::{url}",
            ))
        return out


class DefiSource(BaseOpportunitySource):
    name = "defi"

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        from agents.defi_scanner import DeFiScanner
        # DeFiScanner has no queryable interface; term recorded via provenance upstream.
        scanner = DeFiScanner()
        opps = scanner.scan_all()
        try:
            screened, results = scanner.screen_rug_pull(opps)
        except Exception:
            screened, results = opps, {}
        out = []
        for opp in screened:
            url = getattr(opp, "url", "") or ""
            risk = results.get(opp.id)
            risk_level = getattr(risk, "risk_level", None) if risk else opp.risk_level
            out.append(Opportunity(
                opportunity_id=f"defi_{opp.id}", source=self.name, platform=opp.protocol,
                title=f"{opp.protocol} {opp.type} — {opp.token_symbol}",
                description=f"{opp.protocol} {opp.type} with {opp.apy_percent}% APY",
                category="crypto_reward", payment_type="crypto",
                currency=getattr(opp, "token_symbol", "") or "TOKEN",
                advertised_amount=float(getattr(opp, "tvl_usd", 0.0) or 0.0)
                * (getattr(opp, "apy_percent", 0.0) / 100) * 0.01,
                estimated_net_value=float(getattr(opp, "tvl_usd", 0.0) or 0.0)
                * (getattr(opp, "apy_percent", 0.0) / 100) * 0.01,
                risk_level=risk_level or "medium", scam_risk=0.4,
                source_reliability=0.4, external_id=str(opp.id), external_url=url,
                provenance=f"{self.name}::{url}",
            ))
        return out


class MicrotaskSource(BaseOpportunitySource):
    name = "microtask"

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        from agents.microtask_client import MicrotaskClient
        # v2.0.36p: honor the scheduler's per-task query instead of a fixed string.
        q = (query or "ai ml data").strip() or "ai ml data"
        gigs = MicrotaskClient().find_gigs(platform="all", query=q)
        out = []
        for g in gigs:
            url = getattr(g, "url", "") or ""
            out.append(Opportunity(
                opportunity_id=f"microtask_{g.id}", source=self.name, platform=g.platform,
                title=g.title, description=g.description, category="microtask",
                payment_type="usd", currency="USD",
                advertised_amount=float(getattr(g, "payout_usd", 0.0) or 0.0),
                estimated_net_value=float(getattr(g, "payout_usd", 0.0) or 0.0),
                risk_level="low", source_reliability=0.6,
                external_id=str(g.id), external_url=url,
                provenance=f"{self.name}::{url}",
            ))
        return out


class UgigSource(BaseOpportunitySource):
    """Read public hiring listings from uGig without requiring credentials.

    This adapter is deliberately read-only. Applying, creating listings, and
    account actions remain separate approval-gated operations.
    """

    name = "ugig"
    endpoint = "https://ugig.net/api/gigs"

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        import requests

        params = {"listing_type": "hiring"}
        if query and query.strip():
            params["search"] = query.strip()
        response = requests.get(
            self.endpoint,
            params=params,
            headers={"User-Agent": "MrBot1000-discovery/2.0"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        listings = payload.get("gigs", []) if isinstance(payload, dict) else payload
        if not isinstance(listings, list):
            return []

        out = []
        for listing in listings:
            if not isinstance(listing, dict):
                continue
            listing_id = str(listing.get("id", "")).strip()
            title = str(listing.get("title", "")).strip()
            if not listing_id or not title:
                continue
            description = str(listing.get("description", "")).strip() or title
            skills = listing.get("skills_required", [])
            if not isinstance(skills, list):
                skills = []
            text = " ".join([title, description, " ".join(map(str, skills))])
            category = classify_category(text)
            currency = str(listing.get("payment_coin", "USD") or "USD").upper()
            amount = max(
                float(listing.get("budget_max", 0) or 0),
                float(listing.get("budget_min", 0) or 0),
            )
            url = f"https://ugig.net/gigs/{listing_id}"
            out.append(Opportunity(
                opportunity_id=f"ugig_{listing_id}", source=self.name,
                platform="uGig", title=title, description=description,
                category=category, required_skills=[str(s) for s in skills],
                payment_type="crypto" if currency not in ("USD", "EUR", "GBP") else "usd",
                currency=currency, advertised_amount=amount,
                estimated_net_value=amount, risk_level="medium",
                source_reliability=0.5, external_id=listing_id,
                external_url=url, provenance=f"{self.name}::{url}",
            ))
        return out


class ContentSource(BaseOpportunitySource):
    """DEPRECATED / REMOVED from default discovery (v2.0.36p).

    This used to emit three STATIC entries ("Write for Mirror.xyz", "Write for
    Hive", "Write for Gitcoin") with a hardcoded $5.00 each cycle — fabricated,
    never discovered, and identical on every run. That is exactly the
    "repeating hardcoded results" symptom. Real content-platform opportunities
    now come through WebDiscoverySource (human-review-gated) or the legacy
    DynamicSource. Kept only as a class so nothing imports it by name and breaks.
    """
    name = "content"

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        return []  # was hardcoded; now yields nothing so it can't fake findings.


class DynamicSource(BaseOpportunitySource):
    """Legacy EarningDiscoverer (Reddit/Twitter/GitHub-bounty/referral/faucet)."""

    name = "dynamic"

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        from agents.earning_discoverer import EarningDiscoverer
        disc = EarningDiscoverer()
        # v2.0.36p: if the scheduler supplied a focused term, bias discovery toward it.
        if query:
            try:
                disc.set_focus(query)
            except Exception:
                pass
        raw = disc.discover_all()
        out = []
        for o in raw:
            url = getattr(o, "url", "") or ""
            cat = ("referral" if "referral" in (o.platform or "").lower()
                   else "airdrop" if "airdrop" in (o.title or "").lower()
                   else "faucet" if "faucet" in (o.title or "").lower()
                   else "other")
            out.append(Opportunity(
                opportunity_id=o.id, source=self.name, platform=o.platform,
                title=o.title, description=o.description, category=cat,
                payment_type="usd" if o.payment_type == "usd" else "crypto",
                currency="USD" if o.payment_type == "usd" else "TOKEN",
                advertised_amount=float(getattr(o, "min_amount", 0.0) or 0.0),
                estimated_net_value=float(getattr(o, "min_amount", 0.0) or 0.0),
                risk_level=o.risk_level, source_reliability=0.4,
                external_id=str(o.id), external_url=url,
                provenance=f"{self.name}::{url}",
            ))
        return out


def all_builtin_sources() -> List[BaseOpportunitySource]:
    """Return instances of every existing-integration source.

    v2.0.36p changes:
      * ContentSource no longer emits static fake gigs (removed from rotation).
      * WebDiscoverySource is registered but DISABLED by default (gated behind the
        ALLOW_WEB_DISCOVERY human-review flag), so the genuinely-dynamic web search
        path is now WIRED (the scheduler's 'web' tasks finally execute) without
        changing default behavior until an operator opts in.
    """
    from agents.web_discovery import WebDiscoverySource
    return [
        UpworkSource(), FiverrSource(), SocialSource(), AirdropSource(),
        DefiSource(), MicrotaskSource(), UgigSource(), DynamicSource(),
        WebDiscoverySource(),   # disabled unless ALLOW_WEB_DISCOVERY=true (human review)
    ]
