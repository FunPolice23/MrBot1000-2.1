"""
comms_log.py — Durable log of in-flight messages for the EventBus.

Why: the redesign requires (a) correlation-id tracking across restarts,
(b) cancellation/retry bookkeeping, and (c) "application restart does not
corrupt persistent state". A single append-oriented SQLite table of messages
keyed by message_id gives us that. On boot we mark any message left in
PENDING/IN_FLIGHT as CANCELLED/ERROR so a crash mid-flight never silently
re-executes a task and never corrupts authoritative stores (which the bus never
touches directly — it only logs).

This is a SEPARATE module/file from database.py on purpose: database.py's
table-creation uses a large triple-quoted executescript that the patch tool
corrupts, so the comms log lives here with its own simple, robust schema.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

from agents.comms import Message, MessageStatus


class MessageLog:
    """Append-oriented, thread-safe log of bus messages keyed by message_id."""

    def __init__(self, path: str = ":memory:"):
        self._path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                message_id       TEXT PRIMARY KEY,
                correlation_id  TEXT,
                message_type    TEXT,
                source          TEXT,
                destination     TEXT,
                status          TEXT,
                priority        INTEGER,
                parent_message_id TEXT,
                payload_json    TEXT,
                error           TEXT,
                created_at      REAL,
                updated_at      REAL
            )
            """
        )
        self._conn.commit()

    # ── record / update ────────────────────────────────────────────────────
    def record(self, msg: Message) -> None:
        with self._lock:
            now = time.time()
            self._conn.execute(
                """
                INSERT OR REPLACE INTO messages
                (message_id, correlation_id, message_type, source, destination,
                 status, priority, parent_message_id, payload_json, error,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.message_id,
                    msg.correlation_id,
                    msg.message_type.value,
                    msg.source,
                    msg.destination,
                    msg.status.value,
                    int(msg.priority),
                    msg.parent_message_id,
                    json.dumps(msg.payload, default=str),
                    msg.error,
                    now,
                    now,
                ),
            )
            self._conn.commit()

    def update_status(self, message_id: str, status: MessageStatus,
                      error: Optional[str] = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE messages SET status=?, error=?, updated_at=? WHERE message_id=?",
                (status.value, error, time.time(), message_id),
            )
            self._conn.commit()

    def get(self, message_id: str) -> Optional[Dict[str, str]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT message_id, correlation_id, message_type, source, "
                "destination, status, priority, parent_message_id, payload_json, "
                "error FROM messages WHERE message_id=?",
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        cols = ["message_id", "correlation_id", "message_type", "source",
                "destination", "status", "priority", "parent_message_id",
                "payload_json", "error"]
        rec = dict(zip(cols, row))
        try:
            rec["payload"] = json.loads(rec["payload_json"] or "{}")
        except Exception:
            rec["payload"] = {}
        return rec

    def all(self) -> List[Dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT message_id, correlation_id, message_type, source, "
                "destination, status, priority, parent_message_id, payload_json, "
                "error FROM messages ORDER BY created_at"
            ).fetchall()
        cols = ["message_id", "correlation_id", "message_type", "source",
                "destination", "status", "priority", "parent_message_id",
                "payload_json", "error"]
        out = []
        for r in rows:
            rec = dict(zip(cols, r))
            try:
                rec["payload"] = json.loads(rec["payload_json"] or "{}")
            except Exception:
                rec["payload"] = {}
            out.append(rec)
        return out

    # ── restart safety ─────────────────────────────────────────────────────
    def mark_orphans_cancelled(self, terminal_status: MessageStatus =
                               MessageStatus.CANCELLED) -> int:
        """
        On application boot, any message left PENDING or IN_FLIGHT was interrupted
        by a restart/crash. Mark it terminal so it is never silently re-executed.
        Returns the number of messages transitioned.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT message_id FROM messages "
                "WHERE status IN ('PENDING','IN_FLIGHT')"
            )
            ids = [r[0] for r in cur.fetchall()]
            if ids:
                now = time.time()
                self._conn.executemany(
                    "UPDATE messages SET status=?, updated_at=? WHERE message_id=?",
                    [(terminal_status.value, now, mid) for mid in ids],
                )
                self._conn.commit()
            return len(ids)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # convenience for tests / debugging
    def count(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM messages").fetchone()[0]
