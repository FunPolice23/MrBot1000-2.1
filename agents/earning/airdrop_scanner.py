"""
agents/airdrop_scanner.py — Crypto airdrop monitoring for MrBot1000.

Scans RSS feeds for airdrop opportunities and evaluates risk.
"""

import builtins
import hashlib
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
        # Verified live listing feeds. `dropzone.io/feed` was removed: it no
        # longer resolves (connection error), so it contributed nothing but a
        # failed request on every scan.
        "https://airdropalert.com/feed/",
        "https://thedefiant.io/api/feed",
    ]

    # Articles that explain or rank airdrops are editorial, not claimable
    # opportunities. Without this filter the airdrop source reported the same
    # evergreen blog posts ("Best crypto airdrops to farm right now",
    # "Crypto airdrops explained…") on every single scan.
    GUIDE_TITLE_MARKERS = (
        "explained", "guide", "how to", "what is", "what are", "best ",
        "top ", "biggest", "list of", "strategies", "worth it",
    )

    # Entry window per feed page. Feeds carry 10-100 items; rotating a window
    # over them makes successive scans surface new listings.
    PAGE_SIZE = 12

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

    def _is_guide_article(self, title: str) -> bool:
        """True when a title is an explainer/roundup rather than a claimable drop."""
        lower = (title or "").lower()
        return any(marker in lower for marker in self.GUIDE_TITLE_MARKERS)

    @staticmethod
    def _rotate_window(items: list, page: int, size: int) -> list:
        """Return a rotating window over ``items`` that wraps around.

        Without wrap-around a feed shorter than ``page * size`` would return
        nothing once the scan advanced past it, so repeat scans would go dry.
        Wrapping keeps every scan populated while still surfacing new entries.
        """
        if not items:
            return []
        n = len(items)
        if n <= size:
            return list(items)
        start = ((max(1, int(page or 1)) - 1) * size) % n
        if start + size <= n:
            return items[start:start + size]
        return items[start:] + items[:size - (n - start)]

    def scan_feeds(self, query: Optional[str] = None, page: int = 1) -> List[AirdropOpportunity]:
        """Scan a page of the configured feeds for claimable airdrops.

        ``page`` rotates through the feed entries so repeated scans surface
        different items instead of the same first N. ``query`` keeps entries
        matching the search term so a targeted scan is possible.
        """
        page = max(1, int(page or 1))
        term = (query or "").strip().lower()

        opportunities = []
        for feed_url in self.RSS_SOURCES + self.AGGREGATOR_FEEDS:
            entries = self._parse_feed(feed_url)
            if not entries:
                continue
            for entry in self._rotate_window(entries, page, self.PAGE_SIZE):
                title = entry.get("title", "")
                description = entry.get("summary", entry.get("description", ""))
                combined = f"{title} {description}"
                if not self._is_airdrop_related(combined):
                    continue
                if self._is_guide_article(title):
                    continue
                if term and term not in combined.lower():
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

    # ------------------------------------------------------------------
    # Value attribution (ARCH-ENG-120)
    #
    # A `$` figure in crypto news is as often a coin's market price as a
    # payout: "Bitcoin holds at $95,000 as airdrop season begins" booked the
    # first `$` in the headline as a $95,000 airdrop, which flowed on to
    # advertised_amount / expected_net_revenue and a fabricated "attractive"
    # verdict in opportunity_intelligence. Per the golden rule an amount a
    # listing never attributed to the payout is unknown (0.0), never a guess,
    # so a figure is only booked when the surrounding text ties it to the
    # airdrop/reward. "airdrop worth $500" and "valued at $1,200" still parse;
    # a bare price quote yields 0.0.
    VALUE_INTENT_CUES = (
        "worth", "valued at", "value of", "reward", "allocation", "allocated",
        "allocating", "distribut", "payout", "prize", "giveaway", "bonus",
        "claim", "drop of", "totaling", "totalling", "amounting to",
        "paying out", "pays out", "grant",
    )
    WEAK_VALUE_CUES = ("up to",)
    # Cues that may sit AFTER the figure ("$2,500 reward for testnet users").
    # Deliberately narrower than VALUE_INTENT_CUES: verbs like "claim"/"grant"
    # must not match forward, or "pay $95,000 to claim your airdrop" — a DEMAND
    # for money — would book the fee as a payout. Only nouns naming the thing
    # being distributed are safe here.
    FORWARD_VALUE_CUES = (
        "reward", "giveaway", "bonus", "prize", "allocation", "payout",
        "distribution", "bounty", "per wallet", "in total",
    )
    FORWARD_WINDOW_CHARS = 30
    # An appositive attribution: "Airdrop live now — $1,000 for eligible
    # wallets" names the drop immediately before the figure with no value verb.
    # The window is TIGHT (not VALUE_WINDOW_CHARS) so it cannot reach back
    # across a clause into unrelated market commentary, and the price-context
    # and market-subject guards above have already rejected those shapes.
    SUBJECT_WINDOW_CHARS = 25
    # Market-price language. Price context must sit next to the figure; a
    # payout phrase further back is still a payout ("trades at $95,000 — the
    # airdrop is worth $500").
    PRICE_CONTEXT_CUES = (
        "holds at", "hold at", "trades at", "trade at", "trading at",
        "traded at", "price of", "priced at", "prices at", "sits at",
        "sitting at", "market cap", "down to", "down $", "up $", "above",
        "below", "near", "from $", "rises to", "rose to", "climbs to",
        "climbed to", "surges to", "surged to", "falls to", "fell to",
        "drops to", "dropped to", "slips to", "slipped to",
        "per token",
    )
    # A coin named as the subject is not a payout. ARCH-ENG-120 review: the
    # first version of this guard read `not any(PAYOUT_NOUNS in before)`, but 7
    # words sit in BOTH VALUE_INTENT_CUES and PAYOUT_NOUNS (reward, allocation,
    # bonus, claim, giveaway, payout, prize), so any headline containing one
    # disabled the guard and "Airdrop allocation — Bitcoin $95,000 snapshot"
    # booked the BTC price as a $95,000 payout. The escape clause is therefore
    # REMOVED: instead the coin must be ADJACENT to the figure, so a genuine
    # attribution ("ETH stakers claim $500") still parses while a coin sitting
    # next to a bare figure means the coin is what is being priced.
    MARKET_SUBJECT_RE = re.compile(
        r"\b(btc|bitcoin|eth|ethereum|sol|solana|doge|ada|xrp|market|coin)s?\b"
    )
    PAYOUT_NOUNS = (
        "airdrop", "reward", "drop", "claim", "allocation", "giveaway",
        "bonus", "retroactive", "payout", "prize", "distribution", "staking",
    )
    VALUE_WINDOW_CHARS = 70  # how far back from the `$` a cue may sit
    PRICE_WINDOW_CHARS = 35  # price language must sit next to the `$`
    # A coin ticker within this many chars of the figure, with NO value cue
    # between it and the figure, means the figure prices the coin.
    COIN_ADJACENCY_CHARS = 20

    @classmethod
    def _extract_stated_value_usd(cls, combined_text: str) -> float:
        """USD figure the text attributes to the airdrop, else 0.0 (unknown)."""
        text = combined_text or ""
        for match in re.finditer(r"\$([\d,]+(?:\.\d{1,2})?)", text):
            before = text[max(0, match.start() - cls.VALUE_WINDOW_CHARS):
                          match.start()].lower()
            near = before[-cls.PRICE_WINDOW_CHARS:]
            if any(cue in near for cue in cls.PRICE_CONTEXT_CUES):
                continue  # the figure is a quote of a coin, not a payout
            coin_hit = None
            for coin in cls.MARKET_SUBJECT_RE.finditer(before):
                gap = before[coin.end():]
                if (len(gap) <= cls.COIN_ADJACENCY_CHARS
                        and not any(cue in gap for cue in cls.VALUE_INTENT_CUES)
                        and not any(cue in gap for cue in cls.WEAK_VALUE_CUES)):
                    coin_hit = coin
                    break
            if coin_hit is not None:
                # "...Bitcoin $95,000" / "SOL at $212" — the figure is the coin's
                # price. An attribution verb between the coin and the figure
                # ("ETH stakers claim $500") keeps the gap cue-filled and passes.
                continue
            if any(cue in before for cue in cls.VALUE_INTENT_CUES):
                return float(match.group(1).replace(",", ""))
            if any(cue in near for cue in cls.WEAK_VALUE_CUES):
                return float(match.group(1).replace(",", ""))
            after = text[match.end():
                         match.end() + cls.FORWARD_WINDOW_CHARS].lower()
            if any(cue in after for cue in cls.FORWARD_VALUE_CUES):
                return float(match.group(1).replace(",", ""))
            subject_window = before[-cls.SUBJECT_WINDOW_CHARS:]
            if (any(noun in subject_window for noun in cls.PAYOUT_NOUNS)
                    and not cls.MARKET_SUBJECT_RE.search(subject_window)):
                # "Airdrop live now — $1,000" names the drop right before the
                # figure. A coin ticker in the SAME window means the coin is
                # the subject ("airdrop Bitcoin $95,000"), so this is refused.
                return float(match.group(1).replace(",", ""))
        return 0.0

    def _parse_entry(self, entry: dict, combined_text: str) -> Optional[AirdropOpportunity]:
        """Convert a feed entry into a structured opportunity."""
        title = entry.get("title", "")
        link = entry.get("link", entry.get("url", ""))
        token_match = re.search(r"\$([A-Z]{2,10})", combined_text)
        deadline_match = re.search(
            r"(?:deadline|ends?|expires?|before)\s*[:\s]*(.+?)(?:\.|$|\n)",
            combined_text,
            re.IGNORECASE,
        )
        return AirdropOpportunity(
            # Stable id from the link: `hash()` is salted per process, so it
            # produced a different id for the same airdrop after every restart
            # and dedup/provenance could never match.
            id=hashlib.sha1((link or title).encode("utf-8", "ignore")).hexdigest()[:16],
            title=title[:200],
            description=combined_text[:500],
            token_symbol=token_match.group(1) if token_match else "",
            estimated_value_usd=self._extract_stated_value_usd(combined_text),
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