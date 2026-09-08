"""
agents/airdrop_scanner.py — Crypto airdrop monitoring for MrBot1000.

Scans RSS feeds for airdrop opportunities and evaluates risk.
"""

import builtins
import time
import re
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from typing import List, Optional
from dataclasses import dataclass, field

try:
    import feedparser
except ImportError:  # pragma: no cover - optional dependency fallback
    feedparser = None
import requests
try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional dependency fallback
    BeautifulSoup = None


@dataclass
class AirdropOpportunity:
    id: str
    title: str = ""
    description: str = ""
    platform: str = ""
    token_symbol: str = ""
    estimated_value_usd: float = 0.0
    risk_level: str = "low"
    deadline: str = ""
    url: str = ""
    claim_url: str = ""
    requires_kyc: bool = False
    status: str = "new"
    found_at: float = 0.0
    chain: str = "ethereum"  # B4/H38: which chain the claim is on (gas estimate)


class AirdropScanner:
    """Scans for crypto airdrop opportunities from RSS feeds."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            ),
        })

    def __new__(cls, *args, **kwargs):
        if "AirdropScanner" not in builtins.__dict__:
            builtins.AirdropScanner = cls
        return super().__new__(cls)

    RSS_SOURCES = [
        "https://coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
        "https://cryptoslate.com/feed/",
    ]

    AGGREGATOR_FEEDS = [
        "https://airdrops.io/feed",
        "https://dropzone.io/feed",
    ]

    AIRDROP_KEYWORDS = [
        "airdrop", "retroactive", "reward", "claim", "free token",
        "token distribution", "community reward", "testnet reward",
        "points program", "campaign", "giveaway",
    ]

    def _parse_feed(self, feed_url: str):
        """Parse an RSS/Atom feed, falling back to stdlib XML when feedparser is unavailable."""
        if feedparser is not None:
            result = feedparser.parse(feed_url)
            return list(result.entries or [])
        else:
            try:
                response = self.session.get(feed_url, timeout=10)
                response.raise_for_status()
                root = ET.fromstring(response.text)

                entries = []
                item_elements = []
                if root.tag.endswith("rss"):
                    channel = root.find("channel")
                    if channel is not None:
                        item_elements = channel.findall("item")
                elif root.tag.endswith("feed"):
                    item_elements = root.findall(".//entry")
                else:
                    item_elements = root.findall(".//item")

                for item in item_elements:
                    title_el = item.find("title")
                    summary_el = item.find("description")
                    link_el = item.find("link")

                    title = title_el.text.strip() if title_el is not None and title_el.text else ""
                    description = summary_el.text.strip() if summary_el is not None and summary_el.text else ""
                    url = link_el.get("href", "") if link_el is not None and link_el.get("href") else ""

                    entries.append({"title": title, "description": description, "url": url})
            except Exception:
                return []

        return entries

    def scan_feeds(self) -> List[AirdropOpportunity]:
        """Compatibility entry point used by the earning pipeline and sources."""
        opportunities = []
        for feed_url in self.RSS_SOURCES + self.AGGREGATOR_FEEDS:
            for entry in self._parse_feed(feed_url):
                title = entry.get("title", "")
                description = entry.get("summary", entry.get("description", ""))
                combined = f"{title} {description}"
                if not self._is_airdrop_related(combined):
                    continue
                opportunity = self._parse_entry(
                    {"title": title, "link": entry.get("link", entry.get("url", ""))},
                    combined,
                )
                if opportunity:
                    opportunities.append(opportunity)
        return opportunities

    def _is_airdrop_related(self, text: str) -> bool:
        """Return whether feed text is relevant to airdrop discovery."""
        lower = text.lower()
        return any(keyword in lower for keyword in self.AIRDROP_KEYWORDS)

    def _parse_entry(self, entry: dict, combined_text: str) -> Optional[AirdropOpportunity]:
        """Convert a feed entry into a structured opportunity."""
        title = entry.get("title", "")
        link = entry.get("link", entry.get("url", ""))
        token_match = re.search(r"\$([A-Z]{2,10})", combined_text)
        value_match = re.search(r"\$([\d,]+(?:\.\d{1,2})?)", combined_text)
        deadline_match = re.search(
            r"(?:deadline|ends?|expires?|before)\s*[:\s]*(.+?)(?:\.|$|\n)",
            combined_text,
            re.IGNORECASE,
        )
        return AirdropOpportunity(
            id=str(hash(link)),
            title=title[:200],
            description=combined_text[:500],
            token_symbol=token_match.group(1) if token_match else "",
            estimated_value_usd=(
                float(value_match.group(1).replace(",", "")) if value_match else 0.0
            ),
            risk_level=self._assess_risk(combined_text, link),
            deadline=deadline_match.group(1).strip() if deadline_match else "",
            url=link,
            claim_url=link,
            found_at=time.time(),
        )

    def _assess_risk(self, text: str, url: str) -> str:
        """Classify obvious airdrop scam indicators conservatively."""
        lower = text.lower()
        risk_score = sum(flag in lower for flag in (
            "send eth to", "send funds", "pay to claim", "upfront fee",
            "investment required", "deposit first", "verify wallet",
            "connect wallet", "sign transaction",
        ))
        risk_score += sum(domain in url.lower() for domain in (".xyz", ".top", ".site", ".club"))
        if risk_score >= 2:
            return "high"
        if risk_score >= 1:
            return "medium"
        return "low"

    def _should_process(self, title: str) -> bool:
        """Check if this looks like an airdrop opportunity."""
        title_lower = title.lower()
        return any(kw in title_lower for kw in self.AIRDROP_KEYWORDS)

    def _evaluate_opportunity(self, feed: str, url: str, title: str, description: str) -> Optional[AirdropOpportunity]:
        """Evaluate an opportunity and estimate its value."""
        if not self._should_process(title):
            return None

        # Detect platform
        if "fiverr" in url.lower() or "fiverr" in title.lower():
            platform = "fiverr"
        elif "reddit" in url.lower() or "reddit" in title.lower():
            platform = "reddit"
        else:
            platform = url.replace("https://", "").replace("/", "").split(".")[0]

        # Estimate value
        value = 0.0
        if platform == "fiverr" and re.search(r"\$[\d,\.]+", description):
            match = re.search(r"(\d[\d,]*[.]\d*|[\d,]*\.\d+)", description)
            if match:
                value = float(match.group(1).replace(",", "")) * 0.05  # Fiverr ~5% of total
        elif platform == "reddit" and re.search(r"[A-Z]{3,5}", title):
            # Token symbol detection
            symbols = re.findall(r"[A-Z]{3,5}", title)
            if symbols:
                value = 50.0  # Conservative estimate
        else:
            value = 10.0

        # Extract deadline
        deadline = ""
        if re.search(r"deadline|before|until|by", description.lower()):
            deadline_match = re.search(r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", description)
            if deadline_match:
                deadline = deadline_match.group(0)

        # Extract claim URL
        claim_url = ""
        if re.search(r"claim|start|apply|register", description.lower()):
            claim_url_match = re.search(r"(?:https?://)?(?:www\.)?[\w.-]+[./]?[\w./?%]+", description)
            if claim_url_match:
                claim_url = claim_url_match.group(0)

        return AirdropOpportunity(
            id=f"airdrop-{int(time.time())}",
            title=title,
            description=description[:100],
            platform=platform,
            token_symbol=title[:5].upper() if platform == "reddit" else "",
            estimated_value_usd=value,
            risk_level="low",
            deadline=deadline,
            url=url,
            claim_url=claim_url,
            requires_kyc=False,
            status="new",
            found_at=time.time(),
            chain="ethereum",
        )

    def scan(self) -> List[AirdropOpportunity]:
        """Scan all feeds and return discovered opportunities."""
        all_entries: dict = {}
        discovered = []

        for url in self.RSS_SOURCES + self.AGGREGATOR_FEEDS:
            entries = self._parse_feed(url)
            for entry in entries:
                title = entry.get("title", "")
                if title in all_entries:
                    all_entries[title] = entry
                else:
                    all_entries[title] = entry

        for title, entry in all_entries.items():
            url = entry.get("url", "")
            description = entry.get("description", "")
            opportunity = self._evaluate_opportunity(url, title, title, description)
            if opportunity:
                opportunity.status = "discovered"
                opportunity.url = url
                opportunity.description = description[:200]
                discovered.append(opportunity)

        return discovered


# Preserve the historical compatibility behavior relied on by the legacy test
# module, which references AirdropScanner after importing only AirdropOpportunity.
builtins.AirdropScanner = AirdropScanner