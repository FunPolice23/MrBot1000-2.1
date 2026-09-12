"""Layered, freshness-aware retrieval over the existing program memory store."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional


class MemoryLayer(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    POLICY = "policy"


_CATEGORY_LAYERS: Dict[str, MemoryLayer] = {
    "working": MemoryLayer.WORKING,
    "conversation": MemoryLayer.EPISODIC,
    "episode": MemoryLayer.EPISODIC,
    "fact": MemoryLayer.SEMANTIC,
    "knowledge": MemoryLayer.SEMANTIC,
    "procedure": MemoryLayer.PROCEDURAL,
    "workflow": MemoryLayer.PROCEDURAL,
    "lesson": MemoryLayer.POLICY,
    "policy": MemoryLayer.POLICY,
}


@dataclass(frozen=True)
class MemoryEntry:
    id: int
    layer: MemoryLayer
    category: str
    title: str
    content: str
    importance: float
    confidence: float
    source: str
    timestamp: str
    expires_at: str = ""

    def is_expired(self, now: Optional[float] = None) -> bool:
        if not self.expires_at:
            return False
        try:
            import datetime
            expiry = datetime.datetime.fromisoformat(self.expires_at).timestamp()
            return expiry <= (now if now is not None else time.time())
        except (TypeError, ValueError, OverflowError):
            return True

    def is_stale(self, max_age_seconds: Optional[float], now: Optional[float] = None) -> bool:
        if max_age_seconds is None:
            return False
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must not be negative")
        try:
            import datetime
            recorded = datetime.datetime.fromisoformat(self.timestamp).timestamp()
            return (now if now is not None else time.time()) - recorded > max_age_seconds
        except (TypeError, ValueError, OverflowError):
            return True


class LayeredMemoryRetriever:
    """Retrieve memories by layer without promoting or mutating them."""

    def __init__(self, database):
        self.database = database

    @staticmethod
    def layer_for(category: str, source: str = "") -> MemoryLayer:
        normalized = (category or "").strip().lower()
        if normalized in _CATEGORY_LAYERS:
            return _CATEGORY_LAYERS[normalized]
        if "policy" in normalized or "lesson" in normalized:
            return MemoryLayer.POLICY
        if source in ("conversation", "dialogue"):
            return MemoryLayer.EPISODIC
        return MemoryLayer.SEMANTIC

    def retrieve(self, query: str = "", *, layers: Optional[Iterable[MemoryLayer]] = None,
                 limit: int = 10, min_confidence: float = 0.0,
                 now: Optional[float] = None,
                 max_age_seconds: Optional[float] = None) -> List[MemoryEntry]:
        if limit < 1:
            return []
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        allowed = set(layers) if layers is not None else set(MemoryLayer)
        rows = (self.database.search_memories(query, limit=max(limit * 4, 20))
                if query.strip() else self.database.get_memories(limit=max(limit * 4, 20)))
        entries = []
        for row in rows:
            layer = self.layer_for(row.get("category", ""), row.get("source", ""))
            if layer not in allowed:
                continue
            entry = MemoryEntry(
                id=int(row["id"]),
                layer=layer,
                category=row.get("category", ""),
                title=row.get("title", ""),
                content=row.get("content", ""),
                importance=max(0.0, min(1.0, float(row.get("importance", 0.5)))),
                confidence=self._confidence(row),
                source=row.get("source", ""),
                timestamp=row.get("timestamp", ""),
                expires_at=row.get("expires_at") or "",
            )
            if (entry.is_expired(now) or entry.is_stale(max_age_seconds, now)
                    or entry.confidence < min_confidence):
                continue
            entries.append(entry)
        entries.sort(key=lambda entry: (entry.importance, entry.confidence, entry.timestamp), reverse=True)
        return entries[:limit]

    @staticmethod
    def _confidence(row: dict) -> float:
        value = row.get("confidence", row.get("importance", 0.5))
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0


__all__ = ["LayeredMemoryRetriever", "MemoryEntry", "MemoryLayer"]