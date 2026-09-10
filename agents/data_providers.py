"""
agents/data_providers.py — Real-time market data provider adapters (v2.1 Phase 2).

Provides a pluggable data provider system with multiple adapters:
- CoinGecko: crypto prices, market data, trending tokens
- Alpaca: stock prices, options chains (paper/live trading)
- NewsAPI: financial news and sentiment
- Tavily: web search with AI extraction
- FRED: economic indicators (interest rates, inflation, etc.)

Each adapter follows the DataProvider ABC interface for consistency.
"""

import json
import time
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError


class DataProvider(ABC):
    """Abstract base for all data providers."""
    
    name: str = "base"
    base_url: str = ""
    api_key_env: str = ""
    rate_limit_per_minute: int = 60
    
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv(self.api_key_env, "")
        self._last_call = 0
        self._call_count = 0
    
    def _rate_limit_wait(self):
        """Wait if needed to respect rate limits."""
        min_interval = 60.0 / self.rate_limit_per_minute
        elapsed = time.time() - self._last_call
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call = time.time()
    
    def _http_get(self, url: str, headers: Dict = None) -> Dict:
        """Make an HTTP GET request."""
        self._rate_limit_wait()
        
        req = Request(url)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        
        try:
            with urlopen(req, timeout=30) as resp:
                return {"ok": True, "data": json.loads(resp.read().decode())}
        except HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def _http_post(self, url: str, data: Dict = None, headers: Dict = None) -> Dict:
        """Make an HTTP POST request."""
        self._rate_limit_wait()
        
        req = Request(url, method="POST")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        
        body = json.dumps(data, default=str).encode() if data else None
        if body:
            req.add_header("Content-Type", "application/json")
        
        try:
            with urlopen(req, data=body, timeout=30) as resp:
                return {"ok": True, "data": json.loads(resp.read().decode())}
        except HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


class CoinGeckoProvider(DataProvider):
    """CoinGecko API adapter for crypto market data."""
    
    name = "coingecko"
    base_url = "https://api.coingecko.com/api/v3"
    rate_limit_per_minute = 50  # Free tier
    
    def get_price(self, coin_id: str, vs_currency: str = "usd") -> Dict:
        """Get current price for a coin."""
        url = f"{self.base_url}/simple/price?ids={coin_id}&vs_currencies={vs_currency}&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true"
        return self._http_get(url)
    
    def get_trending(self) -> Dict:
        """Get trending coins."""
        url = f"{self.base_url}/search/trending"
        return self._http_get(url)
    
    def get_coin_data(self, coin_id: str) -> Dict:
        """Get detailed coin data including market cap, volume, etc."""
        url = f"{self.base_url}/coins/{coin_id}?localization=false&tickers=false&community_data=false&developer_data=false"
        return self._http_get(url)
    
    def get_market_chart(self, coin_id: str, vs_currency: str = "usd", days: int = 7) -> Dict:
        """Get historical market data."""
        url = f"{self.base_url}/coins/{coin_id}/market_chart?vs_currency={usd}&days={days}"
        return self._http_get(url)
    
    def search_coins(self, query: str) -> Dict:
        """Search for coins by name or symbol."""
        url = f"{self.base_url}/search?query={query}"
        return self._http_get(url)
    
    def get_global_data(self) -> Dict:
        """Get global crypto market data."""
        url = f"{self.base_url}/global"
        return self._http_get(url)


class AlpacaProvider(DataProvider):
    """Alpaca Markets API adapter for stocks and options."""
    
    name = "alpaca"
    base_url = "https://data.alpaca.markets/v2"
    paper_url = "https://paper-api.alpaca.markets/v2"
    api_key_env = "ALPACA_API_KEY"
    secret_env = "ALPACA_SECRET_KEY"
    rate_limit_per_minute = 200
    
    def __init__(self, api_key: str = "", secret: str = "", paper: bool = True):
        super().__init__(api_key)
        self.secret = secret or os.getenv(self.secret_env, "")
        self.paper = paper
        self.base_url = self.paper_url if paper else self.base_url
    
    def _get_headers(self) -> Dict:
        """Get auth headers."""
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret,
        }
    
    def get_stock_price(self, symbol: str) -> Dict:
        """Get latest stock price."""
        url = f"{self.base_url}/stocks/{symbol}/trades/latest"
        return self._http_get(url, self._get_headers())
    
    def get_stock_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100) -> Dict:
        """Get historical stock bars."""
        url = f"{self.base_url}/stocks/{symbol}/bars?timeframe={timeframe}&limit={limit}"
        return self._http_get(url, self._get_headers())
    
    def get_options_chain(self, symbol: str, expiration: str = "") -> Dict:
        """Get options chain for a symbol."""
        url = f"{self.base_url}/options/snapshots/{symbol}"
        if expiration:
            url += f"?expiration={expiration}"
        return self._http_get(url, self._get_headers())
    
    def get_news(self, symbols: List[str] = None, limit: int = 10) -> Dict:
        """Get market news."""
        url = f"{self.base_url}/news?limit={limit}"
        if symbols:
            url += f"&symbols={','.join(symbols)}"
        return self._http_get(url, self._get_headers())


class NewsAPIProvider(DataProvider):
    """NewsAPI adapter for financial news and sentiment."""
    
    name = "newsapi"
    base_url = "https://newsapi.org/v2"
    api_key_env = "NEWS_API_KEY"
    rate_limit_per_minute = 100
    
    def search_news(self, query: str, language: str = "en", sort_by: str = "publishedAt", page_size: int = 20) -> Dict:
        """Search for news articles."""
        url = f"{self.base_url}/everything?q={query}&language={language}&sortBy={sort_by}&pageSize={page_size}&apiKey={self.api_key}"
        return self._http_get(url)
    
    def get_top_headlines(self, category: str = "business", country: str = "us", page_size: int = 20) -> Dict:
        """Get top headlines."""
        url = f"{self.base_url}/top-headlines?category={category}&country={country}&pageSize={page_size}&apiKey={self.api_key}"
        return self._http_get(url)
    
    def get_sources(self, category: str = "business", language: str = "en") -> Dict:
        """Get available news sources."""
        url = f"{self.base_url}/top-headlines/sources?category={category}&language={language}&apiKey={self.api_key}"
        return self._http_get(url)


class TavilyProvider(DataProvider):
    """Tavily API adapter for AI-powered web search and extraction."""
    
    name = "tavily"
    base_url = "https://api.tavily.com"
    api_key_env = "TAVILY_API_KEY"
    rate_limit_per_minute = 60
    
    def search(self, query: str, max_results: int = 5, include_answer: bool = True) -> Dict:
        """Search the web with AI extraction."""
        data = {
            "query": query,
            "max_results": max_results,
            "include_answer": include_answer,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        return self._http_post(f"{self.base_url}/search", data, headers)
    
    def extract(self, url: str, extract_depth: str = "basic") -> Dict:
        """Extract content from a URL."""
        data = {
            "urls": [url],
            "extract_depth": extract_depth,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        return self._http_post(f"{self.base_url}/extract", data, headers)


class FREDProvider(DataProvider):
    """Federal Reserve Economic Data (FRED) API adapter."""
    
    name = "fred"
    base_url = "https://api.stlouisfed.org/fred"
    api_key_env = "FRED_API_KEY"
    rate_limit_per_minute = 120
    
    def get_series(self, series_id: str, observation_start: str = "", observation_end: str = "") -> Dict:
        """Get economic data series."""
        url = f"{self.base_url}/series/observations?series_id={series_id}&api_key={self.api_key}&file_type=json"
        if observation_start:
            url += f"&observation_start={observation_start}"
        if observation_end:
            url += f"&observation_end={observation_end}"
        return self._http_get(url)
    
    def search_series(self, search_text: str, limit: int = 10) -> Dict:
        """Search for economic data series."""
        url = f"{self.base_url}/series/search?search_text={search_text}&api_key={self.api_key}&file_type=json&limit={limit}"
        return self._http_get(url)
    
    def get_categories(self, category_id: int = 0) -> Dict:
        """Get category information."""
        url = f"{self.base_url}/category?category_id={category_id}&api_key={self.api_key}&file_type=json"
        return self._http_get(url)
    
    def get_interest_rate(self, series_id: str = "DFF") -> Dict:
        """Get current interest rate (default: Federal Funds Rate)."""
        return self.get_series(series_id, observation_start="2024-01-01")


# ── Data Provider Registry ───────────────────────────────────────────────

PROVIDER_REGISTRY: Dict[str, type] = {
    "coingecko": CoinGeckoProvider,
    "alpaca": AlpacaProvider,
    "newsapi": NewsAPIProvider,
    "tavily": TavilyProvider,
    "fred": FREDProvider,
}


def create_provider(name: str, **kwargs) -> Optional[DataProvider]:
    """Create a provider instance by name."""
    cls = PROVIDER_REGISTRY.get(name.lower())
    if cls:
        return cls(**kwargs)
    return None


def list_providers() -> List[str]:
    """List available provider names."""
    return list(PROVIDER_REGISTRY.keys())


# ── Unified Data Fetcher ──────────────────────────────────────────────────

class DataFetcher:
    """Fetch data from multiple providers with fallback."""
    
    def __init__(self):
        self._providers: Dict[str, DataProvider] = {}
    
    def register(self, name: str, provider: DataProvider):
        """Register a provider."""
        self._providers[name] = provider
    
    def get_crypto_price(self, coin_id: str) -> Dict:
        """Get crypto price (tries CoinGecko)."""
        if "coingecko" not in self._providers:
            self._providers["coingecko"] = CoinGeckoProvider()
        return self._providers["coingecko"].get_price(coin_id)
    
    def get_stock_price(self, symbol: str) -> Dict:
        """Get stock price (tries Alpaca)."""
        if "alpaca" not in self._providers:
            self._providers["alpaca"] = AlpacaProvider()
        return self._providers["alpaca"].get_stock_price(symbol)
    
    def search_web(self, query: str) -> Dict:
        """Search the web (tries Tavily, falls back to NewsAPI)."""
        if "tavily" in self._providers:
            result = self._providers["tavily"].search(query)
            if result.get("ok"):
                return result
        
        if "newsapi" in self._providers:
            return self._providers["newsapi"].search_news(query)
        
        return {"ok": False, "error": "No search provider available"}
    
    def get_economic_data(self, series_id: str) -> Dict:
        """Get economic data (tries FRED)."""
        if "fred" not in self._providers:
            self._providers["fred"] = FREDProvider()
        return self._providers["fred"].get_series(series_id)
