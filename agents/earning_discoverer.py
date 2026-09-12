"""
agents/earning_discoverer.py — Dynamic earning opportunity discovery.

Scans RSS feeds, social media, and public platforms for earning
opportunities that pay $1+ in USD or crypto.
"""

import os
import time
import re
import json
import xml.etree.ElementTree as ET
from typing import List, Optional
from dataclasses import dataclass, field

import requests
try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional dependency fallback
    BeautifulSoup = None


@dataclass
class EarningOpportunity:
    """A generic earning opportunity discovered from the web."""
    id: str
    title: str
    description: str
    platform: str
    url: str
    estimated_usd_value: float = 0.0
    required_action: str = ""  # "signup", "complete", "review", "refer"
    payment_type: str = "usd"  # "usd", "crypto", "token"
    min_amount: float = 1.0  # Minimum expected payout
    risk_level: str = "low"  # "low", "medium", "high"
    source: str = "discoverer"
    found_at: float = field(default_factory=time.time)


class EarningDiscoverer:
    """Discovers earning opportunities dynamically from various sources."""

    # RSS feeds for earning opportunities
    RSS_FEEDS = [
        # Airdrop trackers
        "https://cryptopotential.com/airdrop-feed",
        "https://airdropzy.com/feed",
        "https://www.coinmarketcap.com/rss/airdrops",
        # Freelance job boards
        "https://www.upwork.com/rss",
        "https://www.fiverr.com/rss",
        # Crypto news (often has earning links)
        "https://cointelegraph.com/rss",
        "https://cryptoslate.com/rss",
        # Referral program announcements
        "https://www.reddit.com/r/CryptoCurrency/new/.rss",
    ]

    # Common earning keywords to detect
    EARNING_KEYWORDS = [
        "earn", "get paid", "make money", "cash reward", "cashback",
        "referral", "bonus", "payout", "compensation", "reward",
        "free crypto", "airdrop", "faucet", "bounty", "gig",
        "task", "survey", "microtask", "content", "write", "review",
        "test", "bug bounty", "translate", "design", "coding",
    ]

    def __init__(self, min_amount: float = 1.0):
        self.min_amount = min_amount

    def discover_all(self) -> List[EarningOpportunity]:
        """Discover all earning opportunities from all sources."""
        all_opps = []

        # 1. Reddit r/CryptoCurrency posts
        opps = self._discover_reddit()
        all_opps.extend(opps)
        print(f"[Discover] Found {len(opps)} from Reddit")

        # 2. Twitter crypto earning posts
        opps = self._discover_twitter_crypto()
        all_opps.extend(opps)
        twitter_state = "bearer token not configured" if not os.getenv("TWITTER_BEARER_TOKEN", "").strip() else "API search not implemented"
        print(f"[Discover] Found {len(opps)} from Twitter ({twitter_state})")

        # 3. GitHub bounty programs
        opps = self._discover_github_bounties()
        all_opps.extend(opps)
        print(f"[Discover] Found {len(opps)} from GitHub")

        # 4. Discord bot commands (simulated - check for bot commands)
        opps = self._discover_discord_bots()
        all_opps.extend(opps)
        discord_state = "bot token not configured" if not os.getenv("DISCORD_BOT_TOKEN", "").strip() else "guild search not implemented"
        print(f"[Discover] Found {len(opps)} from Discord bots ({discord_state})")

        # 5. Search for referral programs (opt-in only — disabled by default)
        opps = self._discover_referral_programs()
        all_opps.extend(opps)
        referral_state = "opt-in disabled" if os.getenv("ALLOW_REFERRAL_DISCOVERY", "0").strip().lower() not in ("1", "true", "yes") else "live pages verified"
        print(f"[Discover] Found {len(opps)} from referral programs ({referral_state})")

        # 6. Faucets and micro-payments (opt-in only — disabled by default)
        opps = self._discover_faucets()
        all_opps.extend(opps)
        faucet_state = "opt-in disabled" if os.getenv("ALLOW_FAUCET_DISCOVERY", "0").strip().lower() not in ("1", "true", "yes") else "live pages verified"
        print(f"[Discover] Found {len(opps)} from faucets ({faucet_state})")

        return self._deduplicate(all_opps)

    def _discover_reddit(self) -> List[EarningOpportunity]:
        """Discover earning opportunities from Reddit."""
        opps = []
        try:
            # Check r/WorkOnline subreddit
            url = "https://www.reddit.com/r/WorkOnline/new/.json?limit=50"
            data = self._reddit_json(url)
            if data is None:
                data = self._reddit_rss("https://www.reddit.com/r/WorkOnline/.rss")
            if data is not None:
                for post in data.get("data", {}).get("children", []):
                    post_data = post.get("data", {})
                    title = post_data.get("title", "").lower()

                    if any(kw in title for kw in ["earn", "make money", "gig", "freelance", "cash"]):
                        opp = EarningOpportunity(
                            id=f"reddit_{post_data.get('id')}",
                            title=post_data.get("title", "Work Opportunity"),
                            description=post_data.get("selftext", "")[:500],
                            platform="Reddit r/WorkOnline",
                            url=post_data.get("url", ""),
                            payment_type="usd",
                            min_amount=1.0,
                            required_action="apply",
                        )
                        opps.append(opp)

            # Check r/CryptoCurrency for airdrops/rewards
            url = "https://www.reddit.com/r/CryptoCurrency/new/.json?limit=100"
            data = self._reddit_json(url)
            if data is None:
                data = self._reddit_rss("https://www.reddit.com/r/CryptoCurrency/.rss")
            if data is not None:
                for post in data.get("data", {}).get("children", []):
                    post_data = post.get("data", {})
                    title = post_data.get("title", "").lower()

                    if any(kw in title for kw in ["airdrop", "faucet", "reward", "earn", "free"]):
                        opp = EarningOpportunity(
                            id=f"cryptoreddit_{post_data.get('id')}",
                            title=post_data.get("title", "Crypto Reward"),
                            description=post_data.get("selftext", "")[:500],
                            platform="Reddit r/CryptoCurrency",
                            url=post_data.get("url", ""),
                            payment_type="crypto",
                            min_amount=1.0,
                            required_action="claim",
                            risk_level="medium",
                        )
                        opps.append(opp)

        except Exception as e:
            print(f"  Reddit error: {e}")

        return opps

    @staticmethod
    def _reddit_json(url: str):
        """Safe Reddit JSON fetch: returns parsed dict or None on any failure.

        Reddit rate-limits unauthenticated .json (HTTP 429 -> HTML body), returns
        empty bodies, or blocks the UA. A bare resp.json() on those throws
        'Expecting value: line 1 column 1' and aborts the whole discovery. Here we
        validate status + non-empty body before parsing and degrade to None so the
        caller simply finds 0 Reddit opps for that subreddit instead of crashing.
        """
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if resp.status_code != 200 or not resp.text.strip():
                print(f"  Reddit JSON unavailable ({resp.status_code}); trying RSS")
                return None
            return resp.json()
        except Exception as exc:
            print(f"  Reddit JSON error ({exc}); trying RSS")
            return None

    @staticmethod
    def _reddit_rss(url: str):
        """Return Reddit RSS items in the JSON-shaped structure used above."""
        try:
            resp = requests.get(url, headers={"User-Agent": "MrBot1000-discovery/2.1"}, timeout=10)
            if resp.status_code != 200 or not resp.text.strip():
                print(f"  Reddit RSS unavailable ({resp.status_code})")
                return None
            root = ET.fromstring(resp.text)
            children = []
            for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
                title = entry.findtext("{http://www.w3.org/2005/Atom}title", "")
                link = entry.find("{http://www.w3.org/2005/Atom}link")
                link_url = link.get("href", "") if link is not None else ""
                entry_id = entry.findtext("{http://www.w3.org/2005/Atom}id", link_url)
                children.append({"data": {"id": entry_id, "title": title, "selftext": "", "url": link_url}})
            return {"data": {"children": children}}
        except Exception as exc:
            print(f"  Reddit RSS error ({exc})")
            return None

    def _discover_twitter_crypto(self) -> List[EarningOpportunity]:
        """Discover crypto earning opportunities from Twitter/X.

        v2.0.36p: Twitter/X has NO public unauthenticated API. Previous code returned
        hardcoded static entries (AirdropAlert, FaucetPay, Earnifi) as if they were
        discovered — they were fabricated, never fetched, and identical every run.
        This is the \"repeating hardcoded results\" symptom. Real Twitter discovery
        requires a bearer token (Twitter API v2) which is not configured here.
        Returns [] so the system does not fake findings; enable WebDiscoverySource
        (ALLOW_WEB_DISCOVERY=1, human-reviewed) for real web search instead.
        """
        # Twitter API v2 requires OAuth 2.0 Bearer token; no free unauthenticated
        # endpoint exists for searching tweets. Without TWITTER_BEARER_TOKEN set,
        # we must not fabricate results. Return empty.
        if not os.getenv("TWITTER_BEARER_TOKEN", "").strip():
            return []
        # If a bearer token WERE configured, a real implementation would call
        # https://api.twitter.com/2/search/recent?query=... and parse real tweets.
        # That path is not wired here — leave placeholder for future.
        return []

    def _discover_github_bounties(self) -> List[EarningOpportunity]:
        """Discover GitHub bug bounties and feature requests."""
        opps = []
        try:
            # Search broadly because bounty labels vary by repository and old
            # hardcoded repositories can disappear or rename their labels.
            url = "https://api.github.com/search/issues"
            resp = requests.get(
                url,
                params={"q": "(bounty OR reward OR paid) is:issue is:open", "per_page": 30},
                headers={"Accept": "application/vnd.github+json", "User-Agent": "MrBot1000-discovery/2.1"},
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"  GitHub search unavailable ({resp.status_code})")
                return []
            issues = resp.json().get("items", [])

            if not isinstance(issues, list):
                return []

            for issue in issues:
                if not isinstance(issue, dict) or "pull_request" in issue:
                    continue

                labels = issue.get("labels", [])
                label_names = [str(l if isinstance(l, str) else l.get("name", "")) for l in labels] if isinstance(labels, list) else []
                searchable = f"{issue.get('title', '')} {issue.get('body', '')} {' '.join(label_names)}".lower()
                if not any(term in searchable for term in ("bounty", "reward", "paid")):
                    continue

                title = issue.get("title", "")
                body = (issue.get("body", "") or "")[:300]

                match = re.search(r'\$(\d+(?:\.\d+)?)', body + title)
                bounty = float(match.group(1)) if match else 10.0

                repo = issue.get("repository_url", "").rstrip("/").split("/")[-2:]
                repo_name = "/".join(repo) if len(repo) == 2 else "search"
                opps.append(EarningOpportunity(
                    id=f"github_{issue.get('id', issue.get('number', 'unknown'))}",
                    title=title, description=body, platform=f"GitHub/{repo_name}",
                    url=issue.get("html_url", ""), estimated_usd_value=bounty,
                    min_amount=bounty, payment_type="usd", required_action="submit_pr"))

        except Exception as e:
            print(f"  GitHub error: {e}")

        return opps

    def _discover_discord_bots(self) -> List[EarningOpportunity]:
        """Discover earning opportunities from Discord bots.

        v2.0.36p: Previous code returned hardcoded static entries (FaucetPay, CoinPayments)
        as if they were discovered from Discord — they were fabricated, never fetched from
        any Discord API, and identical every run. Discord bot discovery requires a bot token
        and guild/channel discovery which is not configured here. Returns [] — real faucet/
        referral entries come from _discover_referral_programs (which checks real URLs) or
        WebDiscoverySource (ALLOW_WEB_DISCOVERY=1).
        """
        # Discord bot listing requires a bot token + guild access; no public endpoint.
        # Without DISCORD_BOT_TOKEN set we cannot query any Discord API.
        if not os.getenv("DISCORD_BOT_TOKEN", "").strip():
            return []
        return []

    def _discover_referral_programs(self) -> List[EarningOpportunity]:
        """Discover referral program opportunities.

        v2.0.36p: Previous code returned a hardcoded static list (Coinbase, Binance,
        Crypto.com, Ledger) with fixed $5-10 amounts — fabricated, never fetched from
        any live referral-tracking source, and identical every run. Referral programs
        change over time and their current payouts must be verified against the platform.
        This method now verifies each entry against its live page (HTTP fetch) before
        emitting; unverifiable entries are dropped so the system does not repeatedly
        emit stale/fabricated referral opportunities.

        v2.0.36k: Referral programs are NOT freelance gigs — they don't go into the
        job queue (manager.py line 1524 filters by type=='gig' and source in fiverr/upwork).
        They remain tracked in the EarningPipeline's own DB/lifecycle for the operator
        to review. Only emit them if the operator has explicitly enabled referral discovery
        (ALLOW_REFERRAL_DISCOVERY=1).
        """
        if os.getenv("ALLOW_REFERRAL_DISCOVERY", "0").strip().lower() not in ("1", "true", "yes"):
            return []
        opps = []
        # Known crypto referral programs — but verify they actually exist before emitting.
        programs = [
            {
                "id": "coinbase",
                "title": "Coinbase Referral",
                "description": "Earning $10+ for each referral who trades",
                "url": "https://www.coinbase.com/referrals",
                "min_amount": 10.0,
                "platform": "Coinbase",
            },
            {
                "id": "binance",
                "title": "Binance Referral Program",
                "description": "Earning up to 40% commission on referrals",
                "url": "https://www.binance.com/referral",
                "min_amount": 5.0,
                "platform": "Binance",
            },
            {
                "id": "crypto_com",
                "title": "Crypto.com Referral",
                "description": "Earning $10+ for each referral",
                "url": "https://crypto.com/app/referral",
                "min_amount": 10.0,
                "platform": "Crypto.com",
            },
            {
                "id": "ledger",
                "title": "Ledger Referral Program",
                "description": "Earning $10 for each referral",
                "url": "https://shop.ledger.com/pages/referral-program",
                "min_amount": 10.0,
                "platform": "Ledger",
            },
        ]

        for prog in programs:
            # Verify the URL is reachable before emitting — don't emit stale entries
            # whose pages may have moved or changed. A quick HEAD/GET sanity check.
            try:
                resp = requests.head(prog["url"], timeout=5,
                                      headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code >= 400:
                    continue  # page gone/changed — drop this entry
            except Exception:
                # If we can't verify, err on the side of dropping rather than
                # fabricating. The entry may be stale.
                continue

            opp = EarningOpportunity(
                id=f"referral_{prog['id']}",
                title=prog["title"],
                description=prog["description"],
                platform=prog["platform"],
                url=prog["url"],
                payment_type="usd",
                min_amount=prog["min_amount"],
                required_action="refer",
            )
            opps.append(opp)

        return opps

    def _discover_faucets(self) -> List[EarningOpportunity]:
        """Discover crypto faucet earning opportunities.

        v2.0.36k: Faucet discovery is DISABLED by default (ALLOW_FAUCET_DISCOVERY
        must be set to 1 to enable). Previous code returned a hardcoded static list
        (bitcoinfaucet.uo1.net, ethereumfaucet.com, monerofaucet.xyz) with fixed
        min amounts — fabricated, never fetched from any live faucet-tracking source,
        and identical every run. Faucet sites appear and disappear constantly; a
        static list quickly goes stale. Real faucet discovery requires active
        monitoring of faucet aggregators which is not wired here.
        """
        if os.getenv("ALLOW_FAUCET_DISCOVERY", "0").strip().lower() not in ("1", "true", "yes"):
            return []
        # Known crypto faucet URLs — but verify they actually exist before emitting.
        faucets = [
            {"id": "bitcoin", "title": "Bitcoin Faucet",
             "url": "https://bitcoinfaucet.uo1.net", "min": 0.000001},
            {"id": "ethereum", "title": "Ethereum Faucet",
             "url": "https://ethereumfaucet.com", "min": 0.001},
            {"id": "monero", "title": "Monero Faucet",
             "url": "https://monerofaucet.xyz", "min": 0.1},
        ]

        opps = []
        for f in faucets:
            try:
                resp = requests.head(f["url"], timeout=5,
                                      headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code >= 400:
                    continue
            except Exception:
                continue

            opp = EarningOpportunity(
                id=f"faucet_{f['id']}",
                title=f["title"],
                description=f"Crypto faucet: {f['title']}",
                platform="Crypto Faucet",
                url=f["url"],
                payment_type="crypto",
                min_amount=f["min"],
                required_action="claim",
                risk_level="medium",
            )
            opps.append(opp)

        return opps

    def _deduplicate(self, opps: List[EarningOpportunity]) -> List[EarningOpportunity]:
        """Remove duplicate opportunities."""
        seen_ids = set()
        unique = []
        for opp in opps:
            if opp.id not in seen_ids:
                seen_ids.add(opp.id)
                unique.append(opp)
        return unique


# Quick test
if __name__ == "__main__":
    discoverer = EarningDiscoverer()
    opps = discoverer.discover_all()
    print(f"\nTotal opportunities discovered: {len(opps)}")
    for opp in opps[:5]:
        print(f"  - {opp.title} (${opp.min_amount}+)")