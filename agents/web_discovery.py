"""agents/web_discovery.py — Generic web discovery source (pluggable, gated).

This is a GENERIC source that finds legitimate paid/reward opportunities from the
public web (RSS feeds, search-provider results) and maps them to the canonical
structured `Opportunity`. It is designed to satisfy "the system should also support
generic web discovery where permitted" WITHOUT ever fabricating opportunities.

Hard safety rules (per project security policy):
- DEFAULT DISABLED. `is_enabled()` returns False unless explicitly permitted via the
  ALLOW_WEB_DISCOVERY env flag (which itself should only be set after HUMAN REVIEW).
- MOCK-FIRST. In mock mode it returns deterministic fixture opportunities for tests
  and for safe dry-runs; it never touches the network.
- The LLM is ONLY permitted to CLASSIFY/ENRICH real externally-sourced text
  (e.g. pick a category from a real title). It must NEVER generate new listings
  from its own imagination — that would be manufacturing opportunities, which is
  forbidden. `provenance` always records the real external url.
- Real (non-mock) mode requires BOTH: enabled flag AND a configured provider; it
  still must not invent listings — only parse real fetched items.
"""

from __future__ import annotations

import os
import time
from typing import List

from agents.opportunity_models import Opportunity, BaseOpportunitySource, classify_category


# Default RSS/feed seeds. These are PUBLIC, legitimate aggregators. They are only
# fetched when web discovery is explicitly enabled by a human. Do NOT add private
# or ToS-restricted targets without review.
DEFAULT_FEEDS: List[str] = [
    "https://cryptoslate.com/feed/",
    "https://cointelegraph.com/rss",
    "https://www.reddit.com/r/WorkOnline/.rss",
]

# Mock fixtures: real-looking but synthetic; used for tests/dry-run only. Never
# presented as verified external findings.
_MOCK_OPPS = [
    dict(platform="WorkOnline", title="Data labeling project - $8/hr",
         description="Label images for ML training. Remote.", category="data_labeling",
         payment_type="usd", currency="USD", amount=8.0,
         url="https://example.org/mock/data-labeling"),
    dict(platform="CryptoNews", title="Airdrop: complete tasks for TOKEN",
         description="Legitimate retroactive reward campaign.", category="airdrop",
         payment_type="crypto", currency="TOKEN", amount=25.0,
         url="https://example.org/mock/airdrop"),
    dict(platform="StudyBoard", title="Paid research study on UX",
         description="45-min session, compensated.", category="paid_study",
         payment_type="usd", currency="USD", amount=30.0,
         url="https://example.org/mock/paid-study"),
]


class WebDiscoverySource(BaseOpportunitySource):
    """Generic web discovery. Disabled by default; MOCK-FIRST; human-review gated."""

    name = "web"

    def __init__(self, mock: bool = False, feeds: List[str] = None,
                 allow: bool = None):
        # `allow` overrides the env flag when explicitly passed (tests).
        self._mock = mock
        self._feeds = feeds or list(DEFAULT_FEEDS)
        if allow is None:
            allow = os.getenv("ALLOW_WEB_DISCOVERY", "false").lower() in ("1", "true", "yes")
        self._allowed = bool(allow)

    def is_enabled(self) -> bool:
        # Disabled unless a human explicitly enabled it.
        return self._allowed

    def _mock_discover(self) -> List[Opportunity]:
        out = []
        for i, m in enumerate(_MOCK_OPPS):
            url = m["url"]
            out.append(Opportunity(
                opportunity_id=f"web_mock_{i}", source=self.name, platform=m["platform"],
                title=m["title"], description=m["description"], category=m["category"],
                payment_type=m["payment_type"], currency=m["currency"],
                advertised_amount=m["amount"], estimated_net_value=m["amount"],
                risk_level="low", source_reliability=0.5,
                external_url=url, provenance=f"{self.name}::{url}",
            ))
        return out

    def _real_discover(self, query: Optional[str] = None) -> List[Opportunity]:
        """Fetch real feeds and parse real items. NEVER invents listings.

        v2.0.36p: when the scheduler supplies a focused `query`, also run a real
        web search via the configured provider (web_provider) and map those results
        in — so discovery is genuinely driven by the dynamic strategy term, not just
        the fixed seed feeds. If the provider is unavailable it simply contributes
        nothing (graceful). LLM usage is limited to classify_category() on real
        titles; it cannot create new opportunities. Malformed/empty items skipped.
        """
        import requests
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            BeautifulSoup = None

        out: List[Opportunity] = []
        # 1) Seed RSS/Atom feeds (real, time-varying content).
        for feed in self._feeds:
            try:
                resp = requests.get(feed, headers={"User-Agent": "Mozilla/5.0"},
                                    timeout=10)
                if resp.status_code != 200 or not resp.text.strip():
                    continue
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(resp.text)
                except ET.ParseError:
                    continue
                for item in root.iter():
                    if item.tag.lower() not in ("item", "entry"):
                        continue
                    title = (item.findtext("title") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    if not title:
                        continue
                    cat = classify_category(f"{title}")
                    out.append(Opportunity(
                        opportunity_id=f"web_{abs(hash(link or title)) % 10**10}",
                        source=self.name, platform=feed,
                        title=title, description=title, category=cat,
                        payment_type="usd", currency="USD",
                        advertised_amount=0.0,  # unknown until validated
                        risk_level="medium", source_reliability=0.4,
                        external_url=link, provenance=f"{self.name}::{link or title}",
                    ))
            except Exception:
                continue
        # 2) Query-targeted real web search (only if a term was supplied).
        if query:
            try:
                from agents.web_provider import search as web_search
                for r in web_search(query) or []:
                    title = r.get("title", "").strip()
                    url = r.get("url", "").strip()
                    if not title or not url:
                        continue
                    cat = classify_category(f"{title} {query}")
                    out.append(Opportunity(
                        opportunity_id=f"web_{abs(hash(url)) % 10**10}",
                        source=self.name, platform="web_search",
                        title=title, description=r.get("snippet", "") or title,
                        category=cat, payment_type="usd", currency="USD",
                        advertised_amount=0.0, risk_level="medium",
                        source_reliability=0.4, external_url=url,
                        provenance=f"{self.name}::{url}",
                    ))
            except Exception:
                pass
        return out

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        if self._mock:
            return self._mock_discover()
        if not self.is_enabled():
            return []
        return self._real_discover(query=query)
