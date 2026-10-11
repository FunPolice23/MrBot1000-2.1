"""Background workers used by feature tabs."""

from PySide6.QtCore import QThread, Signal


class DataExplorerWorker(QThread):
    """Run web scraping away from the GUI thread."""

    finished = Signal(dict)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            from agents.integrations.scraper import WebScraper
            result = WebScraper().scrape(self.url, extract_tables=True)
        except Exception as exc:
            result = {"ok": False, "url": self.url, "error": str(exc)}
        self.finished.emit(result)


class LivePortfolioWorker(QThread):
    """Read a live exchange account without blocking the Qt GUI thread."""

    finished = Signal(dict)

    def __init__(self, service):
        super().__init__()
        self.service = service

    def run(self):
        try:
            snapshot = self.service.sync_portfolio()
            self.finished.emit({
                "ok": True,
                "equity": snapshot.total_equity_usd,
                "cash": snapshot.free_cash_usd,
                "balances": len(snapshot.balances),
            })
        except Exception as exc:
            self.finished.emit({"ok": False, "error": str(exc)})


class SocialDiscoveryWorker(QThread):
    """Run the gated social discovery path without blocking the GUI."""

    finished = Signal(dict)

    def __init__(self, pipeline):
        super().__init__()
        self.pipeline = pipeline

    def run(self):
        try:
            if self.pipeline is None:
                raise RuntimeError("earning pipeline unavailable")
            opportunities = self.pipeline.discover(sources=["social"])
            self.finished.emit({
                "ok": True,
                "opportunities": [
                    {
                        "id": getattr(item, "id", ""),
                        "title": getattr(item, "title", ""),
                        "platform": getattr(item, "platform", ""),
                        "amount": getattr(item, "estimated_value", 0.0),
                        "url": getattr(item, "url", ""),
                    }
                    for item in opportunities
                ],
            })
        except Exception as exc:
            self.finished.emit({"ok": False, "error": str(exc)})


__all__ = ["DataExplorerWorker", "LivePortfolioWorker", "SocialDiscoveryWorker"]
