"""discovery_strategies.py — multi-origin search-strategy generation (v2.0.36f).

Generates search strategies from MANY origins (not one static query):
  SKILL, HISTORICAL_CATEGORY, USER_PREFERENCE, EMERGING, PAST_SUCCESS_TERM,
  PAST_FAILED_TERM (avoided), PLATFORM_TERM, EXPLORATION.

Security principle (per MrBot1000): the LLM MAY SUGGEST strategy ideas, but it NEVER performs an
external action. Every output is a validated `SearchStrategy` object that is handed to a VALIDATED
provider interface (DiscoveryEngine sources). If an LLM suggester is registered it is folded in and
MUST fail safe — a crashed LLM call never breaks deterministic generation.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# Strategy origin tokens (also persisted in search_strategy.origin).
ORIGIN_SKILL = "SKILL"
ORIGIN_HISTORICAL_CATEGORY = "HISTORICAL_CATEGORY"
ORIGIN_USER_PREFERENCE = "USER_PREFERENCE"
ORIGIN_EMERGING = "EMERGING"
ORIGIN_PAST_SUCCESS_TERM = "PAST_SUCCESS_TERM"
ORIGIN_PAST_FAILED_TERM = "PAST_FAILED_TERM"
ORIGIN_PLATFORM_TERM = "PLATFORM_TERM"
ORIGIN_EXPLORATION = "EXPLORATION"

# Curated "emerging" categories the system should periodically probe even without history.
DEFAULT_EMERGING_CATEGORIES = [
    "ai_training_data", "rlhf", "synthetic_media", "agent_tasks", "localization",
    "voice_clone_consent", "3d_asset_creation", "prompt_engineering_gigs",
]

# Default platform-specific terminology used to enrich queries per source.
DEFAULT_PLATFORM_TERMS: Dict[str, List[str]] = {
    "upwork": ["hourly", "fixed-price", "scrape", "automation", "script"],
    "fiverr": ["gig", "bundle", "express", "bot", "scraper"],
    "web": [
        "public job listing no account", "agent-compatible task", "bug bounty",
        "open source bounty", "paid study", "microtask", "data labeling",
    ],
    "ugig": ["remote", "freelance", "coding", "research", "data"],
    "microtask": ["annotation", "transcription", "classification", "eval"],
    "airdrop": ["testnet", "faucet", "quest", "galxe"],
    "defi": ["testnet", "liquidity", "audit", "bounty"],
    "social": ["ugc", "moderation", "caption", "engagement"],
    "dynamic": [
        "AI agent task", "autonomous agent marketplace", "public API task",
        "open source bounty", "bug bounty", "paid research study",
    ],
}


@dataclass
class SearchStrategy:
    """A validated, executable search strategy (never an LLM action itself)."""
    strategy_id: str
    origin: str
    query: str
    categories: List[str] = field(default_factory=list)
    source: str = ""                 # target source/platform bucket
    created_at: float = field(default_factory=time.time)
    used_count: int = 0
    success_count: int = 0
    reward_sum: float = 0.0

    def provenance_tag(self) -> str:
        return f"strategy:{self.strategy_id}"


def _make_id(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{parts[0]}_{h}" if parts else h


class SearchStrategyGenerator:
    """Deterministic, offline-by-default generator. Optional LLM suggester (fails safe)."""

    def __init__(self,
                 emerging_categories: Optional[List[str]] = None,
                 platform_terms: Optional[Dict[str, List[str]]] = None):
        self.emerging_categories = list(emerging_categories or DEFAULT_EMERGING_CATEGORIES)
        self.platform_terms = dict(platform_terms or DEFAULT_PLATFORM_TERMS)
        self._suggester: Optional[Callable[[dict], List[str]]] = None

    def set_suggester(self, fn: Callable[[dict], List[str]]) -> None:
        """Optional LLM hook. Receives a context dict, returns suggested query strings.
        MUST raise or return junk gracefully — never trusted as authoritative."""
        self._suggester = fn

    # ── Main generation ──────────────────────────────────────────
    def generate(self, *,
                 known_skills: Optional[List[str]] = None,
                 successful_categories: Optional[List[str]] = None,
                 preferences: Optional[List[str]] = None,
                 successful_terms: Optional[List[str]] = None,
                 failed_terms: Optional[List[str]] = None,
                 sources: Optional[List[str]] = None,
                 memory=None) -> List[SearchStrategy]:
        """Produce a diverse set of candidate strategies across all origins."""
        known_skills = known_skills or []
        successful_categories = successful_categories or []
        preferences = preferences or []
        successful_terms = successful_terms or []
        failed_terms = failed_terms or []
        sources = sources or list(self.platform_terms.keys())
        strategies: List[SearchStrategy] = []

        # 1. SKILL -> one strategy per known skill, queried across relevant sources.
        for skill in known_skills:
            for src in sources:
                strategies.append(SearchStrategy(
                    strategy_id=_make_id(ORIGIN_SKILL, skill, src),
                    origin=ORIGIN_SKILL, query=skill,
                    categories=[skill], source=src))

        # 2. HISTORICAL_CATEGORY -> profitable past categories.
        for cat in successful_categories:
            strategies.append(SearchStrategy(
                strategy_id=_make_id(ORIGIN_HISTORICAL_CATEGORY, cat),
                origin=ORIGIN_HISTORICAL_CATEGORY, query=cat,
                categories=[cat], source=""))

        # 3. USER_PREFERENCE -> user-declared interests.
        for pref in preferences:
            strategies.append(SearchStrategy(
                strategy_id=_make_id(ORIGIN_USER_PREFERENCE, pref),
                origin=ORIGIN_USER_PREFERENCE, query=pref,
                categories=[pref], source=""))

        # 4. EMERGING -> curated new categories to probe (exploration seed).
        for cat in self.emerging_categories:
            strategies.append(SearchStrategy(
                strategy_id=_make_id(ORIGIN_EMERGING, cat),
                origin=ORIGIN_EMERGING, query=cat,
                categories=[cat], source=""))

        # 5. PAST_SUCCESS_TERM -> recycle proven queries (exploitation).
        for term in successful_terms:
            strategies.append(SearchStrategy(
                strategy_id=_make_id(ORIGIN_PAST_SUCCESS_TERM, term),
                origin=ORIGIN_PAST_SUCCESS_TERM, query=term,
                categories=[], source=""))

        # 6. PAST_FAILED_TERM -> AVOID (do not generate executable strategies from these).
        #    We record them as known-negative so the scheduler can penalize; we do NOT create
        #    runnable strategies from failed terms (the user said "failed search terms" feed gen,
        #    but generating the exact failed query again would be malpractice — we exclude them).
        self._failed_terms = set(failed_terms)

        # 7. PLATFORM_TERM -> platform-specific terminology enrichment.
        for src in sources:
            for term in self.platform_terms.get(src, []):
                strategies.append(SearchStrategy(
                    strategy_id=_make_id(ORIGIN_PLATFORM_TERM, src, term),
                    origin=ORIGIN_PLATFORM_TERM, query=term,
                    categories=[], source=src))

        # 8. EXPLORATION -> a few novel combinations to keep the stream fresh.
        for cat in self.emerging_categories[:3]:
            strategies.append(SearchStrategy(
                strategy_id=_make_id(ORIGIN_EXPLORATION, cat, "probe"),
                origin=ORIGIN_EXPLORATION, query=f"new {cat} opportunities",
                categories=[cat], source=""))

        # 9. Optional LLM suggestions (fails safe) -> folded as USER_PREFERENCE-style strategies.
        if self._suggester is not None:
            try:
                ctx = {
                    "known_skills": known_skills, "successful_categories": successful_categories,
                    "preferences": preferences, "successful_terms": successful_terms,
                    "failed_terms": failed_terms, "emerging": self.emerging_categories,
                }
                suggestions = self._suggester(ctx) or []
                for s in suggestions:
                    s = (s or "").strip()
                    if not s or s in self._failed_terms:
                        continue
                    strategies.append(SearchStrategy(
                        strategy_id=_make_id("LLM", s),
                        origin=ORIGIN_USER_PREFERENCE, query=s,
                        categories=[], source=""))
            except Exception:
                # LLM failure must NEVER break deterministic generation.
                pass

        # De-duplicate by strategy_id (keep first), drop failed-term queries.
        seen = set()
        out = []
        for st in strategies:
            if st.query in getattr(self, "_failed_terms", set()):
                continue
            if st.strategy_id in seen:
                continue
            seen.add(st.strategy_id)
            out.append(st)
        return out

    def is_failed_term(self, query: str) -> bool:
        return query in getattr(self, "_failed_terms", set())
