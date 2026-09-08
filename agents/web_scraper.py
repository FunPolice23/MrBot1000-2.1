"""
agents/web_scraper.py — Ethical web scraping fallback (v2.1 Phase 2).

Provides web scraping capabilities for platforms without APIs:
- Rate limiting and politeness
- robots.txt compliance
- User-agent rotation
- Proxy support
- HTML parsing and data extraction
- Structured data extraction (tables, lists, etc.)
"""

import time
import re
import hashlib
from typing import Dict, List, Optional, Any, Callable
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser


class RateLimiter:
    """Rate limiter for polite scraping."""
    
    def __init__(self, requests_per_minute: int = 10):
        self.interval = 60.0 / requests_per_minute
        self._last_request = 0
        self._domains: Dict[str, float] = {}
    
    def wait(self, url: str = ""):
        """Wait if needed to respect rate limits."""
        domain = urlparse(url).netloc if url else "default"
        last = self._domains.get(domain, 0)
        elapsed = time.time() - last
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._domains[domain] = time.time()


class RobotsChecker:
    """Check robots.txt compliance."""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
    
    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Check if scraping is allowed by robots.txt."""
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        if base not in self._cache:
            self._cache[base] = self._fetch_robots(base)
        
        rules = self._cache[base]
        if not rules:
            return True  # No robots.txt means allow all
        
        path = parsed.path or "/"
        for rule in rules:
            if path.startswith(rule):
                return False
        
        return True
    
    def _fetch_robots(self, base: str) -> List[str]:
        """Fetch and parse robots.txt."""
        try:
            robots_url = f"{base}/robots.txt"
            req = Request(robots_url, headers={"User-Agent": "MrBot1000/2.0"})
            with urlopen(req, timeout=10) as resp:
                content = resp.read().decode()
            
            # Simple parsing - extract Disallow rules
            rules = []
            current_agent = None
            for line in content.splitlines():
                line = line.strip()
                if line.lower().startswith("user-agent:"):
                    current_agent = line.split(":", 1)[1].strip()
                elif line.lower().startswith("disallow:") and current_agent in ("*", None):
                    path = line.split(":", 1)[1].strip()
                    if path:
                        rules.append(path)
            
            return rules
        except Exception:
            return []


class HTMLExtractor(HTMLParser):
    """Extract structured data from HTML."""
    
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.links = []
        self.tables = []
        self.current_table = None
        self.current_row = None
        self.skip_tags = {"script", "style", "nav", "footer", "header"}
        self._skip_depth = 0
    
    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self._skip_depth += 1
        
        if tag == "a":
            for attr, value in attrs:
                if attr == "href":
                    self.links.append(value)
        
        elif tag == "table":
            self.current_table = []
        
        elif tag in ("tr",) and self.current_table is not None:
            self.current_row = []
        
        elif tag in ("td", "th") and self.current_row is not None:
            pass  # Text will be captured
    
    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self._skip_depth -= 1
        
        if tag == "table" and self.current_table is not None:
            if self.current_table:
                self.tables.append(self.current_table)
            self.current_table = None
        
        elif tag == "tr" and self.current_row is not None:
            if self.current_row:
                self.current_table.append(self.current_row)
            self.current_row = None
    
    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        
        text = data.strip()
        if text:
            self.text_parts.append(text)
            if self.current_row is not None:
                self.current_row.append(text)
    
    def get_text(self) -> str:
        """Get extracted text."""
        return " ".join(self.text_parts)
    
    def get_all(self) -> Dict:
        """Get all extracted data."""
        return {
            "text": self.get_text(),
            "links": self.links,
            "tables": self.tables,
        }


class WebScraper:
    """Ethical web scraper with rate limiting and robots.txt compliance."""
    
    def __init__(self, requests_per_minute: int = 10, respect_robots: bool = True):
        self.rate_limiter = RateLimiter(requests_per_minute)
        self.robots_checker = RobotsChecker() if respect_robots else None
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        ]
        self._ua_index = 0
    
    def _get_user_agent(self) -> str:
        """Rotate user agents."""
        ua = self.user_agents[self._ua_index % len(self.user_agents)]
        self._ua_index += 1
        return ua
    
    def scrape(self, url: str, extract_tables: bool = False) -> Dict:
        """Scrape a URL and extract data."""
        # Check robots.txt
        if self.robots_checker and not self.robots_checker.is_allowed(url):
            return {"ok": False, "error": "Blocked by robots.txt", "url": url}
        
        # Rate limit
        self.rate_limiter.wait(url)
        
        # Make request
        try:
            req = Request(url, headers={"User-Agent": self._get_user_agent()})
            with urlopen(req, timeout=30) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return {"ok": False, "error": f"Unsupported content type: {content_type}", "url": url}
                
                html = resp.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.code}: {e.reason}", "url": url}
        except URLError as e:
            return {"ok": False, "error": f"URL error: {e.reason}", "url": url}
        except Exception as e:
            return {"ok": False, "error": str(e), "url": url}
        
        # Parse HTML
        extractor = HTMLExtractor()
        try:
            extractor.feed(html)
        except Exception:
            pass  # Partial extraction is fine
        
        result = extractor.get_all()
        result["ok"] = True
        result["url"] = url
        
        if not extract_tables:
            result.pop("tables", None)
        
        return result
    
    def scrape_multiple(self, urls: List[str], extract_tables: bool = False) -> List[Dict]:
        """Scrape multiple URLs."""
        results = []
        for url in urls:
            result = self.scrape(url, extract_tables)
            results.append(result)
        return results
    
    def extract_emails(self, text: str) -> List[str]:
        """Extract email addresses from text."""
        pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        return list(set(re.findall(pattern, text)))
    
    def extract_phones(self, text: str) -> List[str]:
        """Extract phone numbers from text."""
        pattern = r"[\+]?[(]?[0-9]{1,4}[)]?[-\s\./0-9]{7,}"
        return list(set(re.findall(pattern, text)))
    
    def extract_prices(self, text: str) -> List[Dict]:
        """Extract price information from text."""
        pattern = r"[\$€£¥]\s*[\d,]+\.?\d*"
        matches = re.findall(pattern, text)
        return [{"price": m, "currency": m[0]} for m in matches]
    
    def extract_structured_data(self, html: str) -> List[Dict]:
        """Extract JSON-LD structured data from HTML."""
        results = []
        pattern = r'<script type="application/ld\+json">(.*?)</script>'
        for match in re.findall(pattern, html, re.DOTALL):
            try:
                data = json.loads(match)
                results.append(data)
            except json.JSONDecodeError:
                continue
        return results
    
    def extract_open_graph(self, html: str) -> Dict:
        """Extract Open Graph metadata from HTML."""
        og_data = {}
        pattern = r'<meta\s+property="og:([^"]+)"\s+content="([^"]+)"'
        for match in re.findall(pattern, html):
            og_data[match[0]] = match[1]
        return og_data
    
    def extract_meta_tags(self, html: str) -> Dict:
        """Extract all meta tags from HTML."""
        meta = {}
        pattern = r'<meta\s+name="([^"]+)"\s+content="([^"]+)"'
        for match in re.findall(pattern, html):
            meta[match[0]] = match[1]
        return meta
    
    def search_and_extract(self, url: str, keywords: List[str]) -> Dict:
        """Scrape a URL and extract only relevant content based on keywords."""
        result = self.scrape(url)
        if not result.get("ok"):
            return result
        
        text = result.get("text", "")
        
        # Find relevant paragraphs
        relevant = []
        paragraphs = text.split("\n")
        for para in paragraphs:
            para_lower = para.lower()
            if any(kw.lower() in para_lower for kw in keywords):
                relevant.append(para)
        
        result["relevant_text"] = "\n".join(relevant)
        result["keywords_found"] = [kw for kw in keywords if kw.lower() in text.lower()]
        
        return result
