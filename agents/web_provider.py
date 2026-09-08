"""
MrBot1000/agents/web_provider.py - Configurable web search provider.

The autonomous loop's JobSearchWorker can optionally enrich gig discovery with
general web search. Which provider is used is configurable via .env so the bot
stays local-first by default and can upgrade to a keyed API later without code
changes.

Config (.env):
    WEB_PROVIDER=ddgs           # ddgs (default, free, no key) | tavily | brave | none
    WEB_SEARCH_MAX_RESULTS=5    # how many results to pull per query
    TAVILY_API_KEY=             # only needed if WEB_PROVIDER=tavily
    BRAVE_API_KEY=              # only needed if WEB_PROVIDER=brave

Design notes:
    * All provider libraries are imported LAZILY inside the search call so the
      app always launches even if a provider SDK is not installed.
    * If the configured provider is unavailable (misconfigured / not installed /
      network error), search() returns [] and logs a single clear INFO line -
      it never raises into the heartbeat loop and never emits the old misleading
      "cannot import name 'web_search' from 'library'" WARN.
    * Normalized result shape: list of dicts with keys title/url/snippet so the
      caller (JobSearchWorker) maps them straight into JobRecord objects.
"""

from __future__ import annotations

import os
import itertools
from typing import Dict, List, Optional

_DEFAULT_MAX_RESULTS = 5
# C3: stable round-robin UA counter (genuine rotation across successive calls,
# not tied to a non-stable id()).
_ua_counter = itertools.count()


def _provider_name() -> str:
    return (os.getenv("WEB_PROVIDER") or "ddgs").strip().lower()


def _max_results() -> int:
    try:
        return max(1, int(os.getenv("WEB_SEARCH_MAX_RESULTS", _DEFAULT_MAX_RESULTS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_RESULTS


def _normalize_ddgs(raw: List[dict]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for r in raw or []:
        title = (r.get("title") or "").strip()
        url = (r.get("href") or r.get("url") or "").strip()
        if title and url:
            out.append({
                "title": title[:120],
                "url": url,
                "snippet": _sanitize_snippet(r.get("body") or r.get("snippet") or ""),
            })
    return out


def _normalize_tavily(raw: dict) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for r in (raw or {}).get("results", []) or []:
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        if title and url:
            out.append({
                "title": title[:120],
                "url": url,
                "snippet": _sanitize_snippet(r.get("content") or r.get("snippet") or ""),
            })
    return out


def _normalize_brave(raw: dict) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for r in ((raw or {}).get("web", {}) or {}).get("results", []) or []:
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        if title and url:
            out.append({
                "title": title[:120],
                "url": url,
                "snippet": _sanitize_snippet(r.get("description") or ""),
            })
    return out


def _sanitize_snippet(text: str) -> str:
    """Neutralize prompt-injection patterns in untrusted web snippets (v2.0.24c).

    Web-search result text is attacker-influenced; strip known injection
    patterns before the snippet is stored/summarized by the LLM. Best-effort
    speed bump — pairs with agents/prompt_sanitize at the prompt-assembly layer.
    """
    if not text:
        return ""
    try:
        from agents.prompt_sanitize import neutralize_instructions
        return neutralize_instructions(text)[:800]
    except Exception:
        # Module import failed (unexpected) — fall back to raw truncated text
        # rather than crash the heartbeat. Sanitization is defense-in-depth.
        return text[:800]


def _search_ddgs(query: str, limit: int) -> List[Dict[str, str]]:
    # Lazy import so the app launches without ddgs installed.
    from ddgs import DDGS  # pip install ddgs
    raw = DDGS().text(query, max_results=limit)
    return _normalize_ddgs(raw)


def _search_tavily(query: str, limit: int) -> List[Dict[str, str]]:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("WEB_PROVIDER=tavily but TAVILY_API_KEY is empty")
    from tavily import TavilyClient  # pip install tavily-python
    client = TavilyClient(api_key=key)
    raw = client.search(query=query, max_results=limit)
    return _normalize_tavily(raw)


def _search_brave(query: str, limit: int) -> List[Dict[str, str]]:
    key = os.getenv("BRAVE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("WEB_PROVIDER=brave but BRAVE_API_KEY is empty")
    import requests  # already a dependency of the app
    from agents.scrape_resilience import (
        pick_ua, retry_on_429, CaptchaBlockedError,
    )
    # C3: rotate UA + honor 429/Retry-After via retry_on_429.
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": key,
        "User-Agent": pick_ua(rotate=True, idx=next(_ua_counter)),
    }
    try:
        resp = retry_on_429(
            lambda: requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": limit},
                headers=headers,
                timeout=10,
            )
        )
    except CaptchaBlockedError:
        # Graceful degradation: a captcha from the search API -> no results.
        return []
    resp.raise_for_status()
    return _normalize_brave(resp.json())


# One-shot "we already warned about this provider being unavailable" guard so
# the log isn't spammed every heartbeat.
_warned_providers: set = set()


def search(query: str) -> List[Dict[str, str]]:
    """Return normalized web results for ``query``.

    Returns [] on any misconfiguration / missing SDK / network error. Logs a
    single clear line the first time a provider fails so the operator knows
    exactly why web search is idle. Never raises.
    """
    provider = _provider_name()
    limit = _max_results()

    if provider == "none" or provider == "off" or provider == "":
        return []

    try:
        if provider == "ddgs":
            return _search_ddgs(query, limit)
        if provider == "tavily":
            return _search_tavily(query, limit)
        if provider == "brave":
            return _search_brave(query, limit)
        # Unknown provider name -> treat as disabled, tell the operator once.
        if provider not in _warned_providers:
            _warned_providers.add(provider)
            print(f"[WebProvider] Unknown WEB_PROVIDER='{provider}' - web search disabled. "
                  f"Use ddgs|tavily|brave|none.")
        return []
    except Exception as e:  # noqa: BLE001 - web search must never break the heartbeat
        if provider not in _warned_providers:
            _warned_providers.add(provider)
            print(f"[WebProvider] WEB_PROVIDER='{provider}' unavailable: {e} "
                  f"- web search disabled this run.")
        return []
