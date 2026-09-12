"""
agents/freelance_finder.py — Real freelance opportunity hunter (v2.1 Path 1).

Searches real freelance platforms for live paying gigs using the web controller.
Does NOT submit or apply — only researches and ranks opportunities.

The default search targets cover freelance, AI-agent, research, bounty, and
crypto-work marketplaces. These are web-search targets, not authenticated
integrations: results remain human-review-only until a separate platform
adapter and approval-gated action exists.
"""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents.web_controller import WebController


@dataclass
class FreelanceOpportunity:
    """A real freelance opportunity found online."""
    title: str
    platform: str
    url: str
    budget: str = ""
    description: str = ""
    skills: List[str] = field(default_factory=list)
    posted_at: str = ""
    source: str = "web_search"
    raw: Dict = field(default_factory=dict)


class FreelanceFinder:
    """Find real freelance opportunities using web search."""

    DEFAULT_PLATFORMS = [
        "upwork", "fiverr", "contra", "freelancer", "toptal", "peopleperhour",
        "reddit", "prolific", "user_testing", "bounty", "ai_agent", "crypto_work",
        "general",
    ]
    TARGETED_SEARCH_TERMS = {
        "ai_agent": (
            "AI agent marketplace agent tasks automation contracts "
            "site:virtuals.io OR site:olas.network OR site:singularitynet.io "
            "OR site:fetch.ai OR site:rentahuman.ai"
        ),
        "crypto_work": (
            "crypto web3 DAO jobs grants bounties "
            "site:laborx.com OR site:cryptotask.org OR site:gitcoin.co "
            "OR site:immunefi.com OR site:code4rena.com OR site:sherlock.xyz"
        ),
        "bounty": (
            "bug bounty open source bounty "
            "site:gitcoin.co OR site:immunefi.com OR site:code4rena.com "
            "OR site:sherlock.xyz OR site:onlydust.com OR site:dorahacks.io"
        ),
        "user_testing": (
            "user testing paid studies "
            "site:usertesting.com OR site:userinterviews.com OR site:prolific.com"
        ),
    }

    def __init__(self, web: Optional[WebController] = None):
        self.web = web or WebController()
        self._cache: Dict[str, List[FreelanceOpportunity]] = {}
        self._cache_ttl = 600  # 10 minutes

    def search(self, query: str, max_results: int = 10, platforms: Optional[List[str]] = None) -> Dict[str, Any]:
        """Search for freelance opportunities."""
        platforms = platforms or list(self.DEFAULT_PLATFORMS)
        results: List[FreelanceOpportunity] = []
        errors: List[str] = []

        # Platform-specific searches
        for platform in platforms:
            try:
                opps = self._search_platform(platform, query, max_results // len(platforms) + 1)
                results.extend(opps)
            except Exception as e:
                errors.append(f"{platform}: {e}")

        # Deduplicate by URL
        seen = set()
        unique = []
        for opp in results:
            if opp.url not in seen:
                seen.add(opp.url)
                unique.append(opp)

        # Sort by recency heuristic
        unique.sort(key=lambda o: len(o.description), reverse=True)

        return {
            "ok": True,
            "query": query,
            "platforms": platforms,
            "results": [self._opp_to_dict(o) for o in unique[:max_results]],
            "count": len(unique[:max_results]),
            "errors": errors,
            "cached": False,
        }

    def _search_platform(self, platform: str, query: str, max_results: int) -> List[FreelanceOpportunity]:
        """Search a specific platform."""
        if platform == "upwork":
            return self._search_upwork(query, max_results)
        elif platform == "fiverr":
            return self._search_fiverr(query, max_results)
        elif platform == "reddit":
            return self._search_reddit(query, max_results)
        elif platform == "prolific":
            return self._search_prolific(query, max_results)
        elif platform == "user_testing":
            return self._search_targeted(
                query, max_results, self.TARGETED_SEARCH_TERMS[platform], "user testing")
        elif platform == "bounty":
            return self._search_targeted(
                query, max_results, self.TARGETED_SEARCH_TERMS[platform], "bounty")
        elif platform == "ai_agent":
            return self._search_targeted(
                query, max_results, self.TARGETED_SEARCH_TERMS[platform], "ai-agent marketplace")
        elif platform == "crypto_work":
            return self._search_targeted(
                query, max_results, self.TARGETED_SEARCH_TERMS[platform], "crypto/web3")
        elif platform in {"contra", "freelancer", "toptal", "peopleperhour"}:
            return self._search_targeted(query, max_results, f"{platform} freelance jobs", platform)
        else:
            return self._search_general(query, max_results)

    def _search_targeted(self, query: str, max_results: int,
                         search_terms: str, platform: str) -> List[FreelanceOpportunity]:
        """Search a marketplace family without pretending it has an API adapter."""
        result = self.web.search(f"{search_terms} {query}", max_results=max_results)
        if not result.get("ok"):
            return []
        return [
            FreelanceOpportunity(
                title=r.get("title", ""), platform=platform, url=r.get("url", ""),
                description=r.get("snippet", ""),
                budget=self._extract_budget(r.get("snippet", "")),
                skills=self._extract_skills(f"{r.get('title', '')} {r.get('snippet', '')}"),
                source="web_search", raw=r,
            )
            for r in result.get("results", [])
            if r.get("title") and r.get("url")
        ]

    def _search_upwork(self, query: str, max_results: int) -> List[FreelanceOpportunity]:
        """Search Upwork via web search."""
        search_query = f"site:upwork.com {query}"
        result = self.web.search(search_query, max_results=max_results)
        if not result.get("ok"):
            return []

        opps = []
        for r in result.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            if "upwork.com" in url and ("/jobs/" in url or "/project/" in url or "/o/" in url):
                opps.append(FreelanceOpportunity(
                    title=title,
                    platform="upwork",
                    url=url,
                    description=snippet,
                    budget=self._extract_budget(snippet),
                    skills=self._extract_skills(f"{title} {snippet}"),
                    source="web_search",
                    raw=r,
                ))
        return opps

    def _search_fiverr(self, query: str, max_results: int) -> List[FreelanceOpportunity]:
        """Search Fiverr via web search."""
        search_query = f"site:fiverr.com {query}"
        result = self.web.search(search_query, max_results=max_results)
        if not result.get("ok"):
            return []

        opps = []
        for r in result.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            if "fiverr.com" in url:
                opps.append(FreelanceOpportunity(
                    title=title,
                    platform="fiverr",
                    url=url,
                    description=snippet,
                    budget=self._extract_budget(snippet),
                    skills=self._extract_skills(f"{title} {snippet}"),
                    source="web_search",
                    raw=r,
                ))
        return opps

    def _search_reddit(self, query: str, max_results: int) -> List[FreelanceOpportunity]:
        """Search Reddit freelance subreddits."""
        search_query = f"site:reddit.com/r/forhire OR site:reddit.com/r/freelance {query}"
        result = self.web.search(search_query, max_results=max_results)
        if not result.get("ok"):
            return []

        opps = []
        for r in result.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            if "reddit.com" in url:
                opps.append(FreelanceOpportunity(
                    title=title,
                    platform="reddit",
                    url=url,
                    description=snippet,
                    budget=self._extract_budget(snippet),
                    skills=self._extract_skills(f"{title} {snippet}"),
                    posted_at=self._extract_time(snippet),
                    source="web_search",
                    raw=r,
                ))
        return opps

    def _search_prolific(self, query: str, max_results: int) -> List[FreelanceOpportunity]:
        """Search Prolific academic studies."""
        search_query = f"site:app.prolific.co {query}"
        result = self.web.search(search_query, max_results=max_results)
        if not result.get("ok"):
            return []

        opps = []
        for r in result.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            if "prolific" in url.lower():
                opps.append(FreelanceOpportunity(
                    title=title,
                    platform="prolific",
                    url=url,
                    description=snippet,
                    budget=self._extract_budget(snippet),
                    skills=self._extract_skills(f"{title} {snippet}"),
                    source="web_search",
                    raw=r,
                ))
        return opps

    def _search_general(self, query: str, max_results: int) -> List[FreelanceOpportunity]:
        """General web search for freelance gigs."""
        search_query = f"freelance {query} gigs pay money"
        result = self.web.search(search_query, max_results=max_results)
        if not result.get("ok"):
            return []

        opps = []
        for r in result.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            opps.append(FreelanceOpportunity(
                title=title,
                platform="web",
                url=url,
                description=snippet,
                budget=self._extract_budget(snippet),
                skills=self._extract_skills(f"{title} {snippet}"),
                source="web_search",
                raw=r,
            ))
        return opps

    @staticmethod
    def _extract_budget(text: str) -> str:
        """Extract budget info from text."""
        patterns = [
            r'\$[\d,]+(?:\.\d{2})?',
            r'€[\d,]+(?:\.\d{2})?',
            r'£[\d,]+(?:\.\d{2})?',
            r'[\d,]+ USD',
            r'[\d,]+ EUR',
            r'\b\d+\s*(?:hrs?|hours?)\b',
        ]
        found = []
        for p in patterns:
            found.extend(re.findall(p, text, re.I))
        return ", ".join(found[:3]) if found else "Not specified"

    @staticmethod
    def _extract_skills(text: str) -> List[str]:
        """Extract skill keywords."""
        common_skills = [
            "python", "javascript", "react", "node", "aws", "docker", "kubernetes",
            "data analysis", "machine learning", "writing", "editing", "design",
            "video", "audio", "transcription", "translation", "research",
            "excel", "sql", "gpt", "llm", "ai", "automation", "scraping",
            "api", "backend", "frontend", "fullstack", "mobile", "ios", "android",
        ]
        text_lower = text.lower()
        return [s for s in common_skills if s in text_lower]

    @staticmethod
    def _extract_time(text: str) -> str:
        """Extract time info."""
        patterns = [
            r'\d+\s*(?:hours?|days?|weeks?|months?)\s*ago',
            r'(?:today|yesterday|\d+h ago)',
        ]
        for p in patterns:
            m = re.search(p, text, re.I)
            if m:
                return m.group(0)
        return ""

    @staticmethod
    def _opp_to_dict(opp: FreelanceOpportunity) -> Dict[str, Any]:
        return {
            "title": opp.title,
            "platform": opp.platform,
            "url": opp.url,
            "budget": opp.budget,
            "description": opp.description[:300],
            "skills": opp.skills,
            "posted_at": opp.posted_at,
            "source": opp.source,
        }
