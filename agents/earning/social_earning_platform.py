"""
agents/social_earning_platform.py — Social layer & alternative earning sources.

Replaces ClawGig dependency with:
- Reddit job posts
- Discord communities
- LinkedIn freelance posts
- Twitter/X micro-jobs
- GitHub sponsorships
- Community forums
"""

import re
import time
import json
import os
import hashlib
import httpx
from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class SocialOpportunity:
    """Represents an opportunity from social platforms."""
    id: str
    source: str  # reddit, discord, linkedin, twitter, github, forum
    title: str
    description: str
    platform: str
    payment_type: str  # usd, crypto, token, barter
    type: str = "gig"  # Default after non-defaults
    min_amount: float = 0.0
    estimated_value: float = 0.0
    risk_level: str = "low"
    url: str = ""
    author: str = ""
    posted_at: float = field(default_factory=time.time)


class SocialEarningPlatform:
    """Scans social platforms for earning opportunities."""

    def __init__(self):
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120.0.0.0 Safari/537.36"
        }

    def discover_all(self, page: int = 1,
                     query: Optional[str] = None) -> List[SocialOpportunity]:
        """Discover opportunities from all social sources.

        ``page`` rotates the window over each feed's entries so successive scans
        surface different posts instead of the same first 20. ``query`` keeps
        only posts matching the search term (substring, case-insensitive).
        """
        page = max(1, int(page or 1))
        all_opps = []

        # Reddit job posts
        try:
            opps = self._scan_reddit_jobs(page=page, query=query)
            all_opps.extend(opps)
        except Exception as e:
            print(f"[Social] Reddit scan error: {e}")

        # Twitter/X freelancing
        try:
            opps = self._scan_twitter_jobs()
            all_opps.extend(opps)
        except Exception as e:
            print(f"[Social] Twitter scan error: {e}")

        # LinkedIn (via RSS if available)
        try:
            opps = self._scan_linkedin_jobs()
            all_opps.extend(opps)
        except Exception as e:
            print(f"[Social] LinkedIn scan error: {e}")

        # Community forums (e.g., Kaggle, Stack Overflow)
        try:
            opps = self._scan_forum_jobs()
            all_opps.extend(opps)
        except Exception as e:
            print(f"[Social] Forum scan error: {e}")

        # Remote job boards with public RSS (WeWorkRemotely, etc.)
        try:
            opps = self._scan_remote_job_boards(page=page, query=query)
            all_opps.extend(opps)
        except Exception as e:
            print(f"[Social] Remote-board scan error: {e}")

        return all_opps

    # Entries per feed page. Reddit's RSS returns ~25; rotating a window over
    # them makes repeat scans surface new posts.
    PAGE_SIZE = 20

    def _scan_reddit_jobs(self, page: int = 1,
                          query: Optional[str] = None) -> List[SocialOpportunity]:
        """Scan Reddit r/forhire, r/freelance, r/jobbit."""
        opps = []

        # Use rss2json API or direct RSS feed
        feeds = [
            "https://www.reddit.com/r/forhire/.rss",
            "https://www.reddit.com/r/freelance/.rss",
        ]

        start = (max(1, int(page or 1)) - 1) * self.PAGE_SIZE
        term = (query or "").strip().lower()

        def _window(entries):
            """Rotating window that wraps so repeat scans never go dry."""
            n = len(entries)
            if n == 0:
                return []
            if n <= self.PAGE_SIZE:
                return list(entries)
            s = start % n
            if s + self.PAGE_SIZE <= n:
                return entries[s:s + self.PAGE_SIZE]
            return entries[s:] + entries[:self.PAGE_SIZE - (n - s)]

        for feed_url in feeds:
            try:
                import feedparser
                feed = feedparser.parse(feed_url)
                
                for entry in _window(list(feed.entries)):
                    title = entry.title
                    desc = entry.description[:500] if hasattr(entry, 'description') else ''

                    if term and term not in f"{title} {desc}".lower():
                        continue

                    # Skip if no payment info
                    if not any(x in title.lower() or x in desc.lower() 
                              for x in ['pay', '$', 'usd', 'budget', 'rate']):
                        continue
                    
                    # Parse a real amount from the listing ("$50", "$1,500",
                    # "$80,000 - $95,000"); 0 = not stated, NEVER a default.
                    #
                    # ARCH-ENG-118: this fell back to a hardcoded `50.0` whenever
                    # no `$` figure appeared, and the regex `\$(\d+)` truncated
                    # "$1,500" to "1". Measured: a listing stating no amount at
                    # all was emitted with min_amount=50.0, and a $1,500 project
                    # was emitted with min_amount=1.0. Both are fabricated
                    # revenue at the producer — the same financial-truth
                    # violation fixed for LinkedIn (v2.1.68) and WeWorkRemotely,
                    # which use the comma-aware regex below. Reddit is the only
                    # social source that actually returns entries (LinkedIn's
                    # public feed is empty, forums and Twitter fail closed), so
                    # this was the live fabrication site.
                    #
                    # The fabricated 50.0 was also what made an unpayable
                    # listing structurally VALID: `validate_opportunity` sets
                    # `payment_present = advertised_amount > 0`, so a post that
                    # stated no pay passed validation with no reasons and flowed
                    # into ranking, scoring, and the autonomous loop's economics.
                    dollar_match = re.search(r"\$\s*([\d,]+)(?:\.\d{2})?", title + desc)
                    pay_amount = 0.0
                    if dollar_match:
                        try:
                            pay_amount = float(dollar_match.group(1).replace(",", ""))
                        except ValueError:
                            pay_amount = 0.0
                    
                    opps.append(SocialOpportunity(
                        # Stable id: `hash()` is salted per process, so the same
                        # post got a new id after every restart and never deduped.
                        id="reddit_" + hashlib.sha1(
                            (entry.link or title).encode("utf-8", "ignore")
                        ).hexdigest()[:12],
                        source="reddit",
                        title=title,
                        description=desc,
                        platform="Reddit",
                        payment_type="usd",
                        min_amount=pay_amount,
                        estimated_value=pay_amount,
                        url=entry.link,
                        author=getattr(entry, 'author', 'unknown'),
                    ))
            except Exception as e:
                print(f"[Reddit] Feed error: {e}")
        
        return opps

    def _scan_twitter_jobs(self) -> List[SocialOpportunity]:
        """Scan Twitter for micro-jobs and freelance posts.

        Twitter/X has NO public unauthenticated API. Previous code synthesized
        fake "Twitter Job: ..." entries as if they were discovered — they were
        never fetched from any real source and identical every run. Real Twitter
        discovery requires a TWITTER_BEARER_TOKEN (API v2). Without it, returns [].
        """
        if not os.getenv("TWITTER_BEARER_TOKEN", "").strip():
            return []
        # Real implementation would call Twitter API v2 search endpoint.
        # Placeholder for when bearer token is configured.
        return []

    def _scan_linkedin_jobs(self) -> List[SocialOpportunity]:
        """Scan LinkedIn job posts via public RSS.

        v2.1.68: previously hardcoded min_amount=100 / estimated_value=200 for
        every listing — invented revenue at the producer, which the financial-
        truth rule forbids (a balance/amount is never fabricated). Amounts are
        now parsed from the listing text; 0 = not stated (unknown). Entries with
        no payment signal are skipped so nothing is presented as a paid gig
        without evidence. The public jobs/rss feed currently returns 0 entries,
        so this contributes nothing until LinkedIn exposes a working feed — which
        is correct (fail-closed, never fabricate).
        """
        opps = []

        feeds = [
            "https://www.linkedin.com/jobs/rss",
        ]

        for feed_url in feeds:
            try:
                import feedparser
                feed = feedparser.parse(feed_url)

                for entry in feed.entries[:10]:
                    title = entry.get("title", "") if hasattr(entry, "get") else entry.title
                    desc = ""
                    if hasattr(entry, "description"):
                        desc = entry.description[:300]
                    link = entry.get("link", "") if hasattr(entry, "get") else getattr(entry, "link", "")

                    text = f"{title} {desc}"
                    # Only keep listings that actually mention pay — never invent
                    # an amount to make a posting look like paid work.
                    if not any(x in text.lower() for x in
                               ["$", "salary", "usd", "pay", "budget", "rate", "compensation"]):
                        continue

                    pay_amount = 0.0
                    m = re.search(r"\$\s*([\d,]+)(?:\.\d{2})?", text)
                    if m:
                        try:
                            pay_amount = float(m.group(1).replace(",", ""))
                        except ValueError:
                            pay_amount = 0.0

                    opps.append(SocialOpportunity(
                        id="linkedin_" + hashlib.sha1(
                            (link or title).encode("utf-8", "ignore")
                        ).hexdigest()[:12],
                        source="linkedin",
                        title=title,
                        description=desc,
                        platform="LinkedIn",
                        payment_type="usd",
                        min_amount=pay_amount,
                        estimated_value=pay_amount,
                        url=link,
                    ))
            except Exception as e:
                print(f"[LinkedIn] Feed error: {e}")

        return opps

    def _scan_forum_jobs(self) -> List[SocialOpportunity]:
        """Scan community forums for jobs.

        v2.0.36k: Previous code returned hardcoded static entries (Kaggle,
        GitHub Bounties, Dribbble Jobs) with fabricated descriptions and
        fixed amounts — never fetched from any real forum API, identical
        every run. Real forum discovery requires platform-specific API
        access (Kaggle API token, GitHub API, Dribbble pro access) which
        is not configured here. Returns [] so the system does not emit
        fabricated forum opportunities; the operator can add known-working
        forum sources manually via the EarningPipeline UI.
        """
        # All forum entries below are static — they were never fetched.
        # Without platform-specific API credentials, we must not fabricate.
        return []

    def _scan_remote_job_boards(self, page: int = 1,
                                query: Optional[str] = None) -> List[SocialOpportunity]:
        """Scan remote-job boards that publish public RSS (WeWorkRemotely).

        Real, machine-readable freelance/remote listings — broadens discovery
        beyond the two Reddit gig subs and the crypto/airdrop feeds. Amounts are
        parsed from the listing text; when no salary is stated the amount is 0
        (unknown), NEVER a fabricated default. IDs are stable (sha1 of the link).
        """
        opps: List[SocialOpportunity] = []
        feeds = [
            "https://weworkremotely.com/categories/remote-programming-jobs.rss",
            "https://weworkremotely.com/categories/remote-design-jobs.rss",
            "https://weworkremotely.com/categories/remote-writing-jobs.rss",
            "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        ]
        start = (max(1, int(page or 1)) - 1) * self.PAGE_SIZE
        term = (query or "").strip().lower()

        def _window(entries):
            n = len(entries)
            if n == 0:
                return []
            if n <= self.PAGE_SIZE:
                return list(entries)
            s = start % n
            if s + self.PAGE_SIZE <= n:
                return entries[s:s + self.PAGE_SIZE]
            return entries[s:] + entries[:self.PAGE_SIZE - (n - s)]

        for feed_url in feeds:
            try:
                import feedparser
                feed = feedparser.parse(feed_url)
                for entry in _window(list(feed.entries)):
                    title = entry.get("title", "") if hasattr(entry, "get") else entry.title
                    desc = ""
                    if hasattr(entry, "description"):
                        desc = entry.description[:500]
                    link = entry.get("link", "") if hasattr(entry, "get") else getattr(entry, "link", "")

                    if term and term not in f"{title} {desc}".lower():
                        continue

                    # Parse a real salary from the listing (e.g. "$80,000" or
                    # "$60 - $90 / hour"); 0 = not stated, never invented.
                    pay_amount = 0.0
                    m = re.search(r"\$\s*([\d,]+)(?:\.\d{2})?", f"{title} {desc}")
                    if m:
                        try:
                            pay_amount = float(m.group(1).replace(",", ""))
                        except ValueError:
                            pay_amount = 0.0

                    opps.append(SocialOpportunity(
                        id="wwr_" + hashlib.sha1(
                            (link or title).encode("utf-8", "ignore")
                        ).hexdigest()[:12],
                        source="remote_board",
                        title=title,
                        description=desc,
                        platform="WeWorkRemotely",
                        payment_type="usd",
                        min_amount=pay_amount,
                        estimated_value=pay_amount,
                        url=link,
                        author=getattr(entry, "author", "unknown"),
                    ))
            except Exception as e:
                print(f"[RemoteBoard] Feed error: {e}")

        return opps

    def scan_reddit_jobs(self) -> List[SocialOpportunity]:
        """Public method for Reddit scanning."""
        return self._scan_reddit_jobs()

    def scan_twitter_jobs(self) -> List[SocialOpportunity]:
        """Public method for Twitter scanning."""
        return self._scan_twitter_jobs()


if __name__ == "__main__":
    platform = SocialEarningPlatform()
    print("Scanning social platforms for opportunities...")
    
    opps = platform.discover_all()
    print(f"\nFound {len(opps)} opportunities:")
    
    for opp in opps[:5]:
        print(f"  - [{opp.source}] {opp.title[:60]}...")
        print(f"    Platform: {opp.platform}, Value: ${opp.min_amount}")