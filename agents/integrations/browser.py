"""
agents/web_controller.py — Unified web controller with search, browsing, scraping (v2.1 Phase 2/3).

Combines DuckDuckGo search, Playwright browsing, and BeautifulSoup scraping
into a single interface that personas/tools can call directly.

Public API:
  search(query, max_results)
  read_page(url)
  browse(url)
  scrape(url)              -> structured dict with metadata/headings/links/text
  extract_emails(text)
  extract_prices(text)
  extract_phones(text)
  check_site(url)
  screenshot(url)
  ddgr_fallback(query)
"""

from __future__ import annotations

import re
import time
import tempfile
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


class WebController:
    def __init__(self, headless: bool = True, timeout: int = 30):
        self.headless = headless
        self.timeout = timeout
        self._browser = None
        self._playwright = None

    # ── search ─────────────────────────────────────────────────────────────

    def search(self, query: str, max_results: int = 8) -> Dict[str, Any]:
        try:
            from ddgs import DDGS
            results: List[Dict[str, str]] = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
            return {
                "ok": True,
                "query": query,
                "results": results,
                "count": len(results),
            }
        except Exception as e:
            return {"ok": False, "query": query, "error": str(e), "results": [], "count": 0}

    def search_news(self, query: str, max_results: int = 8) -> Dict[str, Any]:
        try:
            from ddgs import DDGS
            results: List[Dict[str, str]] = []
            with DDGS() as ddgs:
                for r in ddgs.news(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("body", ""),
                        "date": r.get("date", ""),
                        "source": r.get("source", ""),
                    })
            return {
                "ok": True,
                "query": query,
                "results": results,
                "count": len(results),
            }
        except Exception as e:
            return {"ok": False, "query": query, "error": str(e), "results": [], "count": 0}

    def ddgr_fallback(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Fallback search using duckduckgo-search if ddgs is missing."""
        try:
            from duckduckgo_search import DDGS
            results: List[Dict[str, str]] = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
            return {"ok": True, "query": query, "results": results, "count": len(results), "backend": "duckduckgo_search"}
        except Exception as e:
            return {"ok": False, "query": query, "error": str(e), "results": [], "count": 0}

    # ── read_page / scrape ─────────────────────────────────────────────────

    def read_page(self, url: str) -> Dict[str, Any]:
        """Read a page with requests+BeautifulSoup. Returns text, title, links."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            resp.raise_for_status()

            # Save final URL after redirects
            final_url = resp.url
            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove non-content
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
                tag.decompose()

            title = ""
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)

            text = soup.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean_text = "\n".join(lines)

            links: List[Dict[str, str]] = []
            for a in soup.find_all("a", href=True):
                link_text = a.get_text(strip=True)
                href = a["href"]
                if link_text and href.startswith("http"):
                    links.append({"text": link_text[:120], "url": href})

            return {
                "ok": True,
                "url": url,
                "final_url": final_url,
                "title": title,
                "text": clean_text[:12000],
                "text_length": len(clean_text),
                "links": links[:50],
                "html_length": len(resp.text),
                "status_code": resp.status_code,
            }
        except Exception as e:
            return {"ok": False, "url": url, "error": str(e)}

    def scrape(self, url: str) -> Dict[str, Any]:
        """Scrape a URL and return structured data."""
        page = self.read_page(url)
        if not page.get("ok"):
            return page

        text = page.get("text", "")
        headings: List[str] = []
        try:
            resp = requests.get(url, timeout=self.timeout, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "html.parser")
            for h in soup.find_all(["h1", "h2", "h3"]):
                headings.append(h.get_text(strip=True))
        except Exception:
            pass

        return {
            "ok": True,
            "url": page.get("url"),
            "final_url": page.get("final_url"),
            "title": page.get("title"),
            "text": page.get("text"),
            "headings": headings[:40],
            "links": page.get("links", [])[:30],
            "emails": self.extract_emails(text),
            "phones": self.extract_phones(text),
            "prices": self.extract_prices(text),
            "socials": self.extract_socials(page.get("text", "")),
        }

    # ── browser ────────────────────────────────────────────────────────────

    async def _ensure_browser(self):
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=self.headless)
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": True}

    async def browse(self, url: str) -> Dict[str, Any]:
        launch = await self._ensure_browser()
        if not launch.get("ok"):
            return launch
        try:
            page = await self._browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)

            title = await page.title()
            text = await page.inner_text("body")
            html = await page.content()

            links = await page.eval_on_selector_all(
                "a[href]",
                """elements => elements.map(a => ({
                    text: (a.innerText || a.textContent || '').trim(),
                    href: a.href || ''
                })).filter(l => l.href && l.text).slice(0, 50)"""
            )

            await page.close()
            return {
                "ok": True,
                "url": url,
                "title": title,
                "text": text[:8000],
                "html": html[:20000],
                "links": links,
            }
        except Exception as e:
            return {"ok": False, "url": url, "error": str(e)}

    async def screenshot(self, url: str) -> Dict[str, Any]:
        launch = await self._ensure_browser()
        if not launch.get("ok"):
            return launch
        try:
            page = await self._browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
            path = os.path.join(tempfile.gettempdir(), "web_controller_screenshot.png")
            await page.screenshot(path=path, full_page=False)
            await page.close()
            return {"ok": True, "url": url, "screenshot": path}
        except Exception as e:
            return {"ok": False, "url": url, "error": str(e)}

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass

    # ── utilities ──────────────────────────────────────────────────────────

    def check_site(self, url: str) -> Dict[str, Any]:
        try:
            start = time.time()
            resp = requests.head(url, timeout=15, allow_redirects=True)
            elapsed = round(time.time() - start, 3)
            return {
                "ok": True,
                "url": url,
                "status_code": resp.status_code,
                "response_time": elapsed,
                "server": resp.headers.get("Server", "unknown"),
                "content_type": resp.headers.get("Content-Type", "unknown"),
                "online": resp.status_code < 400,
            }
        except Exception as e:
            return {"ok": False, "url": url, "online": False, "error": str(e)}

    def get_domain_info(self, url: str) -> Dict[str, str]:
        parsed = urlparse(url)
        return {
            "ok": True,
            "domain": parsed.netloc,
            "scheme": parsed.scheme,
            "path": parsed.path,
            "query": parsed.query,
        }

    @staticmethod
    def extract_emails(text: str) -> List[str]:
        pattern = r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'
        return list(set(re.findall(pattern, text)))

    @staticmethod
    def extract_phones(text: str) -> List[str]:
        patterns = [
            r'\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
            r'\+?\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',
        ]
        found = []
        for p in patterns:
            found.extend(re.findall(p, text))
        return list(set(found))

    @staticmethod
    def extract_prices(text: str) -> List[str]:
        pattern = r'\$[\d,]+(?:\.\d{2})?|€[\d,]+(?:\.\d{2})?|£[\d,]+(?:\.\d{2})?'
        return list(set(re.findall(pattern, text)))

    @staticmethod
    def extract_socials(text: str) -> List[str]:
        pattern = r'(?:https?://)?(?:www\.)?(?:twitter|x|facebook|instagram|linkedin|github|reddit)\.com/[A-Za-z0-9_\-./]+'
        return list(set(re.findall(pattern, text)))

    def format_search(self, data: Dict[str, Any]) -> str:
        if not data.get("ok"):
            return f"Search failed: {data.get('error')}"
        parts = [f"**Search: {data.get('query')}** ({data.get('count')} results)"]
        for i, r in enumerate(data.get("results", []), 1):
            parts.append(f"{i}. **{r.get('title','')}**")
            parts.append(f"   URL: {r.get('url','')}")
            parts.append(f"   {r.get('snippet','')[:180]}")
            parts.append("")
        return "\n".join(parts)

    def format_page(self, page: Dict[str, Any]) -> str:
        if not page.get("ok"):
            return f"Page read failed: {page.get('error')}"
        parts = [f"**{page.get('title','')}**", f"URL: {page.get('url','')}", ""]
        text = page.get("text", "")
        parts.append(text[:4000])
        links = page.get("links", [])
        if links:
            parts.append("\n**Links:**")
            for l in links[:10]:
                parts.append(f"- {l.get('text','')[:60]} -> {l.get('url','')}")
        return "\n".join(parts)
