"""
agents/fiverr_client.py — Fiverr gig discovery for MrBot1000.

Fiverr has no public API, so this client uses RSS feeds and
public category page scraping to discover gigs.
"""

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

FIVERR_BASE = "https://www.fiverr.com"


@dataclass
class FiverrGig:
    id: str
    title: str = ""
    description: str = ""
    budget_usd: float = 0.0
    skills: list = field(default_factory=list)
    url: str = ""
    platform: str = "Fiverr"
    status: str = "new"
    found_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "job_id":      self.id,
            "platform":    self.platform,
            "title":       self.title,
            "description": self.description[:300],
            "budget":      self.budget_usd,
            "skills":      self.skills,
            "url":         self.url,
            "status":      self.status,
            "score":       0.0,
            "notes":       "",
            "found_at":    self.found_at,
            "assigned_to": None,
        }


class FiverrClient:
    """Discover Fiverr gigs via the public search results page.

    NOTE: Fiverr's RSS endpoints (…/rss/gigs/<cat>) return 404 as of 2026 and are
    dead. The working source is the HTML search results page
    (…/search/gigs?query=<q>), which returns gig cards we parse for title + link.
    The gig listing data lives in an embedded JSON blob inside a <script> tag;
    each gig object exposes 'title', 'gig_url', and 'price_i' (base package price
    in USD). We parse those directly so callers get a REAL budget (not 0.0).
    """

    SEARCH_URL = "https://www.fiverr.com/search/gigs"

    def __init__(self):
        self.session = requests.Session()
        self._ua_idx = 0  # C3: stable per-instance rotation counter
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    def _parse_search(self, query: str) -> List[dict]:
        """Fetch the Fiverr search results page and extract gig cards.

        Returns a list of {title, link, price} dicts. The gig listing JSON is in
        an inline <script> blob carrying both 'gig_url' and 'price_i'. We match
        gig objects there for a real budget. If that blob is absent, we fall back
        to a raw HTML link scan (price 0.0). Tolerant: any failure -> [] (honest
        'no results').
        """
        try:
            from agents.scrape_resilience import pick_ua, detect_captcha
            self._ua_idx = (self._ua_idx + 1) % 10**9
            self.session.headers.update({"User-Agent": pick_ua(rotate=True,
                                                               idx=self._ua_idx)})
            resp = self.session.get(
                self.SEARCH_URL, params={"query": query}, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self._last_error = str(e)
            return []
        # C3: if the page is actually a captcha/interstitial, don't parse it as
        # gig data — bail gracefully so discovery can fall back to other sources.
        if detect_captcha(resp.text):
            self._last_error = "captcha/interstitial detected; skipping Fiverr"
            return []
        html = resp.text

        # Locate the gig-listing JSON blob (has gig_url + price_i).
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
        blob = ""
        for s in scripts:
            if '"gig_url"' in s and '"price_i"' in s:
                blob = s
                break

        if not blob:
            # Fallback: raw HTML link scan (no reliable price).
            entries = []
            for m in re.finditer(
                    r'href="(/[^\"?]+/[^\"?]+)\?context_referrer=search_gigs', html):
                path = m.group(1).lstrip("/")
                parts = path.split("/")
                slug = parts[1] if len(parts) > 1 else parts[0]
                if not slug or len(slug) < 4:
                    continue
                entries.append({
                    "title": slug.replace("-", " ").strip().title(),
                    "link": "https://www.fiverr.com/" + path,
                    "price": 0.0,
                })
            seen, uniq = set(), []
            for e in entries:
                if e["link"] in seen:
                    continue
                seen.add(e["link"])
                uniq.append(e)
            return uniq

        # Each gig object carries title, gig_url, price_i (in that order).
        pat = re.compile(
            r'"title":"(?P<title>[^"]+)".*?'
            r'"gig_url":"(?P<url>/[^"]+)".*?'
            r'"price_i":(?P<price>\d+)', re.S)
        entries = []
        seen = set()
        for m in pat.finditer(blob):
            url = "https://www.fiverr.com" + m.group("url")
            if url in seen:
                continue
            seen.add(url)
            try:
                price = float(m.group("price"))
            except (TypeError, ValueError):
                price = 0.0
            entries.append({
                "title": m.group("title").replace("-", " ").strip().title(),
                "link": url,
                "price": price,
            })
        return entries

    def find_gigs(self, query: str = "python",
                  limit: int = 20) -> List[FiverrGig]:
        """Find gigs via the Fiverr search results page (RSS is dead -> 404)."""
        from agents.platform_throttle import get_throttle
        # C1: throttle the Fiverr search call (anti-ban).
        get_throttle().acquire("fiverr")
        gigs = []
        try:
            entries = self._parse_search(query)
        except Exception:
            entries = []
        for entry in entries[:limit]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            if query.lower() not in title.lower():
                continue
            gigs.append(FiverrGig(
                id=str(hash(link)),
                title=title[:200],
                description="",
                # Budget is now scraped from the listing JSON (price_i).
                budget_usd=float(entry.get("price", 0.0) or 0.0),
                skills=[],
                url=link,
                found_at=time.time(),
            ))
        return gigs[:limit]

    def _scrape_gig_page(self, url: str) -> dict:
        """Scrape individual gig page for budget and skills."""
        result = {"budget": 0.0, "skills": [], "description": ""}
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return result

            if BeautifulSoup is not None:
                soup = BeautifulSoup(resp.text, "html.parser")

                # Extract budget
                price_el = soup.select_one(
                    "[data-testid='price'], .price, .gig-price",
                )
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    price_match = re.search(
                        r'[\d,]+(?:\.\d{1,2})?', price_text,
                    )
                    if price_match:
                        result["budget"] = float(
                            price_match.group().replace(",", ""),
                        )

                # Extract skills/tags
                skill_els = soup.select(
                    "[data-testid='skill-tag'], .skill-tag, .tag",
                )
                result["skills"] = [
                    el.get_text(strip=True) for el in skill_els[:10]
                ]

                # Extract description
                desc_el = soup.select_one(
                    "[data-testid='description'], .gig-description",
                )
                if desc_el:
                    result["description"] = (
                        desc_el.get_text(strip=True)[:500]
                    )

        except Exception:
            pass

        return result
