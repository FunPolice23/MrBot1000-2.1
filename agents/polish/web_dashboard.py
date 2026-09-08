"""agents/polish/web_dashboard.py — Phase 6: Web Dashboard.

Lightweight web dashboard for MrBot1000 status, agent registry,
heartbeat, audit log, and self-improvement recommendations.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mrbot.polish.web")


class WebDashboard:
    """Web dashboard for MrBot1000.

    Serves a JSON API for status queries. Actual HTTP serving
    is delegated to the host (e.g. Flask/FastAPI app or Hermes
    desktop web view). This module provides the data layer.
    """

    def __init__(
        self,
        registry=None,
        heartbeat=None,
        audit=None,
        self_improvement=None,
        identity=None,
    ):
        self.registry = registry
        self.heartbeat = heartbeat
        self.audit = audit
        self.self_improvement = self_improvement
        self.identity = identity

    # ── API endpoints (data layer) ────────────────────────

    def status(self) -> Dict[str, Any]:
        """Top-level system status."""
        result: Dict[str, Any] = {
            "version": "2.0.0",
            "components": {},
        }
        if self.heartbeat:
            result["components"]["heartbeat"] = {
                "tier": self.heartbeat.survival_tier.value,
                "running": self.heartbeat.running,
                "interval": self.heartbeat.interval,
            }
        if self.registry:
            health = self.registry.check_health()
            result["components"]["agents"] = {
                "total": health.get("total", 0),
                "healthy": len(health.get("healthy", [])),
                "stale": len(health.get("stale", [])),
                "offline": len(health.get("offline", [])),
            }
        if self.audit:
            entries = self.audit.get_entries(limit=5)
            result["components"]["audit"] = {
                "total_entries": len(self.audit._entries),
                "recent": entries,
            }
        if self.self_improvement:
            result["components"]["learning"] = self.self_improvement.get_recommendation()
        if self.identity and self.identity.agent_card:
            result["components"]["identity"] = {
                "agent_id": self.identity.agent_card.agent_id,
                "name": self.identity.agent_card.name,
            }
        return result

    def agents(self) -> List[Dict[str, Any]]:
        """List all registered agents."""
        if not self.registry:
            return []
        return [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "role": a.role,
                "status": a.status,
                "capabilities": [c.name for c in a.capabilities],
                "tasks_completed": a.tasks_completed,
                "tasks_failed": a.tasks_failed,
            }
            for a in self.registry.get_all_agents()
        ]

    def audit_log(
        self,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve audit log entries."""
        if not self.audit:
            return []
        from agents.polish.comprehensive_logging import Severity as Sev

        sev_enum = None
        if severity:
            try:
                sev_enum = Sev(severity)
            except ValueError:
                pass
        return self.audit.get_entries(severity=sev_enum, source=source, limit=limit)

    def learning_report(self) -> Dict[str, Any]:
        """Return self-improvement recommendations."""
        if not self.self_improvement:
            return {"status": "no engine configured"}
        return self.self_improvement.get_recommendation()

    def save_dashboard_html(self, path: str) -> str:
        """Generate a static HTML dashboard and save to disk."""
        status = self.status()
        html = self._render_html(status)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    def _render_html(self, status: Dict[str, Any]) -> str:
        """Render a minimal HTML dashboard from status dict."""
        components = status.get("components", {})
        rows = []
        for name, data in components.items():
            rows.append(f"<tr><td>{name}</td><td><pre>{json.dumps(data, indent=2)}</pre></td></tr>")
        return f"""<!DOCTYPE html>
<html><head><title>MrBot1000 Dashboard</title>
<style>body{{font-family:sans-serif;margin:20px;}}table{{border-collapse:collapse;width:100%;}}th,td{{border:1px solid #ccc;padding:8px;text-align:left;}}th{{background:#eee;}}</style>
</head><body>
<h1>MrBot1000 Dashboard</h1>
<table><tr><th>Component</th><th>Status</th></tr>{''.join(rows)}</table>
</body></html>"""


__all__ = ["WebDashboard"]
