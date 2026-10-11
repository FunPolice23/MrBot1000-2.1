"""agents/polish/comprehensive_logging.py — Phase 6: Comprehensive Logging.

Structured logging across all subsystems with audit trails,
log rotation, and severity levels.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mrbot.polish.logging")


class Severity(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditEvent:
    """A single structured audit log entry."""

    def __init__(
        self,
        event: str,
        severity: Severity = Severity.INFO,
        source: str = "",
        details: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ):
        self.event = event
        self.severity = severity
        self.source = source
        self.details = details or {}
        self.timestamp = timestamp or datetime.now(timezone.utc).timestamp()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "severity": self.severity.value,
            "source": self.source,
            "details": self.details,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class AuditLogger:
    """Thread-safe structured audit logger with optional file output."""

    def __init__(self, log_path: Optional[str] = None, max_entries: int = 10000):
        self.log_path = log_path
        self.max_entries = max_entries
        self._entries: List[AuditEvent] = []
        self._lock = threading.Lock()

    def log(
        self,
        event: str,
        severity: Severity = Severity.INFO,
        source: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record an audit event. Returns the event for chaining."""
        ev = AuditEvent(event, severity, source, details)
        with self._lock:
            self._entries.append(ev)
            # Trim oldest if over limit
            while len(self._entries) > self.max_entries:
                self._entries.pop(0)
        # Also emit to standard logging
        log_fn = getattr(logger, severity.value, logger.info)
        log_fn("[%s] %s: %s", source, event, json.dumps(details or {}, default=str))
        # Persist to file if configured
        if self.log_path:
            self._persist(ev)
        return ev

    def _persist(self, ev: AuditEvent) -> None:
        try:
            os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(ev.to_json() + "\n")
        except Exception as e:
            logger.error("Failed to persist audit log: %s", e)

    def get_entries(
        self,
        severity: Optional[Severity] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Retrieve entries, newest first, optionally filtered."""
        with self._lock:
            entries = list(self._entries)
        if severity:
            entries = [e for e in entries if e.severity == severity]
        if source:
            entries = [e for e in entries if e.source == source]
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return [e.to_dict() for e in entries[:limit]]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


__all__ = ["Severity", "AuditEvent", "AuditLogger"]
