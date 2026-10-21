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


class LiveOrderProposalWorker(QThread):
    """ARCH-ENG-283 (G-05): assess and propose one live order off the GUI thread.

    Reading the exchange and computing the deterministic risk verdict are
    network-bound. The worker only PROPOSES: with the default policy it enqueues
    a scoped ACTION approval and returns its id. A preapproved (low-risk) order
    is submitted through the same `execute_order` gate the approval path uses;
    that gate re-assesses against live state and can still refuse.
    """

    finished = Signal(dict)

    def __init__(self, service, intent):
        super().__init__()
        self.service = service
        self.intent = intent

    def run(self):
        try:
            portfolio = self.service.sync_portfolio()
            market = self.service.fetch_market_snapshot(self.intent.symbol)
            assessment = self.service.assess_order(
                self.intent, portfolio, market)
            proposal = self.service.propose_order(self.intent, assessment)
            result = {
                "ok": bool(proposal.get("ok")),
                "status": proposal.get("status", ""),
                "approval_id": proposal.get("approval_id", ""),
                "decision": assessment.decision,
                "reasons": list(assessment.reasons),
                "factors": dict(assessment.factors),
            }
            if proposal.get("status") == "preapproved":
                execution = self.service.execute_order(
                    self.intent, assessment)
                result["execution"] = execution
                result["status"] = execution.get("execution_mode", "executed")
            elif proposal.get("status") == "blocked":
                result["error"] = "; ".join(
                    proposal.get("reasons") or assessment.reasons)
            self.finished.emit(result)
        except Exception as exc:
            self.finished.emit({
                "ok": False,
                "status": "error",
                "error": str(exc),
            })


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


class MoltbookFeedWorker(QThread):
    """Read the Moltbook feed off the GUI thread (Phase E, ARCH-ENG-088).

    Builds a read-only MoltbookPoster over requests and returns normalized
    rows (submolt / title / author / preview / id) so the Social Activity tab
    can render them without blocking. Reads are public on Moltbook
    (ARCH-ENG-320) — no registration or per-agent credential is needed; only
    WRITES are credentialed + approval-gated. Emits ok=False with a reason on
    network or API errors.
    """

    finished = Signal(dict)

    def __init__(self, sort: str = "hot", limit: int = 25):
        super().__init__()
        self.sort = sort
        self.limit = limit

    def run(self):
        try:
            # ARCH-ENG-320: Moltbook's read API is public — the feed loads
            # without any registration or per-agent credential. Writes still
            # need both the credential and the approval path; reads never did.
            import requests
            from agents.earning.moltbook_agent import MoltbookPoster
            poster = MoltbookPoster(http_client=requests)
            result = poster.get_feed(sort=self.sort, limit=self.limit)
            if not result.get("ok"):
                self.finished.emit({"ok": False,
                                    "error": result.get("reason", "feed error")})
                return
            feed = result.get("feed", {}) or {}
            posts = feed.get("posts", []) if isinstance(feed, dict) else []
            rows = []
            for p in posts if isinstance(posts, list) else []:
                if not isinstance(p, dict):
                    continue
                submolt = p.get("submolt") or {}
                rows.append({
                    "id": str(p.get("id") or p.get("post_id") or ""),
                    "submolt": str(submolt.get("display_name")
                                   or submolt.get("name") or ""),
                    "title": str(p.get("title", "")),
                    "author": str((p.get("author") or {}).get("name")
                                  or p.get("author_name") or ""),
                    "preview": str(p.get("content", ""))[:160],
                    "url": f"https://www.moltbook.com/post/{p.get('id') or ''}",
                })
            self.finished.emit({"ok": True, "rows": rows,
                                "count": len(rows)})
        except Exception as exc:
            self.finished.emit({"ok": False, "error": str(exc)})


__all__ = ["DataExplorerWorker", "LivePortfolioWorker", "SocialDiscoveryWorker",
           "MoltbookFeedWorker"]
