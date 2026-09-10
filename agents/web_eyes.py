"""
agents/web_eyes.py — Web browsing and search capabilities for MrBot1000 personas.

Gives Marcus Rivera and Alex Vega real-time web abilities:
- Web search via DuckDuckGo
- Browser automation via Playwright (headless)
- Read web pages (HTML to text)
- Extract structured data
- Real-time actions (forms, navigation, screenshots)

Used by the dialogue system so personas can actually research and act.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


class WebEyes:
    """Web browsing and search interface for persona agents."""
    
    def __init__(self, headless: bool = True, timeout: int = 30):
        self.headless = headless
        self.timeout = timeout * 1000  # Playwright uses ms
        self._browser = None
        self._playwright = None
    
    # ── Search ─────────────────────────────────────────────────────────────
    
    def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Search the web via DuckDuckGo."""
        try:
            from ddgs import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
            return results
        except Exception as e:
            return [{"error": str(e)}]
    
    def search_news(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Search news via DuckDuckGo."""
        try:
            from ddgs import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.news(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("body", ""),
                        "date": r.get("date", ""),
                        "source": r.get("source", ""),
                    })
            return results
        except Exception as e:
            return [{"error": str(e)}]
    
    # ── Browser Automation ─────────────────────────────────────────────────
    
    async def launch_browser(self):
        """Launch a headless browser."""
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            return True
        except Exception as e:
            return False
    
    async def browse(self, url: str) -> Dict[str, Any]:
        """Browse a URL and return page content."""
        try:
            from playwright.async_api import async_playwright
            
            if self._browser is None:
                await self.launch_browser()
            
            page = await self._browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=self.timeout)
            
            # Get page info
            title = await page.title()
            content = await page.content()
            
            # Extract text content
            text = await page.inner_text("body")
            
            # Get links
            links = await page.eval_on_selector_all("all", """
                elements => elements.map(a => ({
                    text: a.innerText?.trim() || '',
                    href: a.href || ''
                })).filter(l => l.href && l.text)
            """)
            
            await page.close()
            
            return {
                "url": url,
                "title": title,
                "text": text[:5000],  # Limit text
                "links": links[:20],
                "html": content[:10000],
            }
        except Exception as e:
            return {"url": url, "error": str(e)}
    
    async def fill_form(self, url: str, form_data: Dict[str, str]) -> Dict[str, Any]:
        """Fill and submit a form."""
        try:
            if self._browser is None:
                await self.launch_browser()
            
            page = await self._browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=self.timeout)
            
            for selector, value in form_data.items():
                await page.fill(selector, value)
            
            # Try to submit
            await page.click("button[type='submit'], input[type='submit']")
            await page.wait_for_load_state("networkidle")
            
            result = {
                "url": page.url,
                "title": await page.title(),
                "text": (await page.inner_text("body"))[:3000],
            }
            
            await page.close()
            return result
        except Exception as e:
            return {"url": url, "error": str(e)}
    
    async def screenshot(self, url: str) -> Optional[str]:
        """Take a screenshot of a page."""
        try:
            if self._browser is None:
                await self.launch_browser()
            
            page = await self._browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=self.timeout)
            
            screenshot_path = os.path.join(tempfile.gettempdir(), "web_eyes_screenshot.png")
            await page.screenshot(path=screenshot_path, full_page=False)
            
            await page.close()
            return screenshot_path
        except Exception:
            return None
    
    async def close(self):
        """Close the browser."""
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
    
    # ── Read Pages ─────────────────────────────────────────────────────────
    
    def read_page(self, url: str) -> Dict[str, Any]:
        """Read an HTML page or API response and extract usable data."""
        try:
            import requests
            from bs4 import BeautifulSoup
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()

            # API responses need structured parsing. Passing minified JSON
            # through BeautifulSoup turns useful fields into an opaque blob.
            content_type = resp.headers.get("Content-Type", "").lower()
            raw_body = resp.text.strip()
            if "application/json" in content_type or raw_body[:1] in ("{", "["):
                try:
                    json_data = resp.json()
                except (ValueError, json.JSONDecodeError):
                    json_data = json.loads(raw_body)
                return {
                    "url": url,
                    "title": "JSON API response",
                    "content_type": content_type or "application/json",
                    "json": json_data,
                }
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Remove script/style
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            
            # Get title
            title = soup.find("title")
            title_text = title.get_text() if title else ""
            
            # Get main text
            text = soup.get_text(separator="\n", strip=True)
            # Clean up whitespace
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean_text = "\n".join(lines)[:8000]
            
            # Get links
            links = []
            for a in soup.find_all("a", href=True):
                link_text = a.get_text(strip=True)
                href = a["href"]
                if link_text and href.startswith("http"):
                    links.append({"text": link_text[:100], "url": href})
            
            return {
                "url": url,
                "title": title_text,
                "text": clean_text,
                "links": links[:30],
            }
        except Exception as e:
            return {"url": url, "error": str(e)}
    
    # ── Extract Data ───────────────────────────────────────────────────────
    
    def extract_emails(self, text: str) -> List[str]:
        """Extract email addresses from text."""
        pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return list(set(re.findall(pattern, text)))
    
    def extract_urls(self, text: str) -> List[str]:
        """Extract URLs from text."""
        pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        return list(set(re.findall(pattern, text)))
    
    def extract_prices(self, text: str) -> List[str]:
        """Extract price information from text."""
        pattern = r'\$[\d,]+(?:\.\d{2})?|€[\d,]+(?:\.\d{2})?|£[\d,]+(?:\.\d{2})?'
        return list(set(re.findall(pattern, text)))
    
    # ── Real-time Actions ──────────────────────────────────────────────────
    
    def check_website_status(self, url: str) -> Dict[str, Any]:
        """Check if a website is online and get response info."""
        try:
            import requests
            
            start = __import__("time").time()
            resp = requests.head(url, timeout=10, allow_redirects=True)
            elapsed = __import__("time").time() - start
            
            return {
                "url": url,
                "status_code": resp.status_code,
                "response_time": round(elapsed, 3),
                "server": resp.headers.get("Server", "unknown"),
                "content_type": resp.headers.get("Content-Type", "unknown"),
                "online": resp.status_code < 400,
            }
        except Exception as e:
            return {"url": url, "online": False, "error": str(e)}
    
    def get_domain_info(self, url: str) -> Dict[str, str]:
        """Get domain information."""
        parsed = urlparse(url)
        return {
            "domain": parsed.netloc,
            "scheme": parsed.scheme,
            "path": parsed.path,
        }
    
    # ── Utility ────────────────────────────────────────────────────────────
    
    def format_search_results(self, results: List[Dict[str, str]]) -> str:
        """Format search results for display."""
        if not results:
            return "No results found."
        
        parts = []
        for i, r in enumerate(results, 1):
            if "error" in r:
                parts.append(f"Error: {r['error']}")
            else:
                parts.append(f"**{i}. {r.get('title', 'No title')}**")
                parts.append(f"   URL: {r.get('url', '')}")
                parts.append(f"   {r.get('snippet', '')[:150]}")
                parts.append("")
        
        return "\n".join(parts)
    
    def format_page_summary(self, page: Dict[str, Any]) -> str:
        """Format a page summary for display."""
        if "error" in page:
            return f"Error reading page: {page['error']}"

        if "json" in page:
            try:
                formatted_json = json.dumps(
                    page["json"], indent=2, ensure_ascii=True
                )
            except (TypeError, ValueError) as exc:
                return f"JSON API response from {page.get('url', '')} could not be formatted: {exc}"
            return (
                "JSON API response\n"
                f"URL: {page.get('url', '')}\n"
                f"Content-Type: {page.get('content_type', 'application/json')}\n\n"
                "Parsed data:\n"
                f"{formatted_json[:6000]}"
            )
        
        parts = [
            f"**{page.get('title', 'Page')}**",
            f"URL: {page.get('url', '')}",
            "",
            page.get("text", "")[:2000],
        ]
        
        links = page.get("links", [])
        if links:
            parts.append("\n**Links found:**")
            for link in links[:10]:
                if isinstance(link, dict):
                    parts.append(f"- {link.get('text', '')[:60]} → {link.get('url', '')}")
                else:
                    parts.append(f"- {str(link)[:80]}")
        
        return "\n".join(parts)


# ── Singleton ──────────────────────────────────────────────────────────────

_web_eyes = None

def get_web_eyes() -> WebEyes:
    """Get the global WebEyes instance."""
    global _web_eyes
    if _web_eyes is None:
        _web_eyes = WebEyes()
    return _web_eyes


# ── Convenience Functions ──────────────────────────────────────────────────

def search_web(query: str, max_results: int = 5) -> str:
    """Search the web and return formatted results."""
    eyes = get_web_eyes()
    results = eyes.search(query, max_results)
    return eyes.format_search_results(results)


def read_url(url: str) -> str:
    """Read a URL and return formatted summary."""
    eyes = get_web_eyes()
    page = eyes.read_page(url)
    return eyes.format_page_summary(page)


def browse_to(url: str) -> Dict[str, Any]:
    """Browse to a URL (async)."""
    import asyncio
    eyes = get_web_eyes()
    return asyncio.run(eyes.browse(url))


def check_site(url: str) -> Dict[str, Any]:
    """Check if a website is online."""
    eyes = get_web_eyes()
    return eyes.check_website_status(url)


if __name__ == "__main__":
    # Quick test
    print("Testing WebEyes...")
    
    eyes = WebEyes()
    
    # Test search
    print("\n=== SEARCH ===")
    results = eyes.search("Prolific academic research platform", 3)
    print(eyes.format_search_results(results))
    
    # Test page read
    print("\n=== PAGE READ ===")
    page = eyes.read_page("https://www.prolific.com")
    print(eyes.format_page_summary(page)[:500])
