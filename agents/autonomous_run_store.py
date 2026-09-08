"""
agents/autonomous_run_store.py — Durable autonomous-run ledger (v2.1).

SQLite-backed, restart-safe persistence for autonomous planning-loop runs so a
restart never loses loop results (the prior in-memory-only AutonomousResult).

Tables
------
- autonomous_runs: one row per run (run_id, opportunity_id, correlation_id,
  status, decision, success, paid, payment_amount, decision_reason,
  explanation, model_metadata, created_at, updated_at, stages_json, errors_json).
- autonomous_stage_runs: one row per stage (run_id, stage, status, model,
  latency_ms, error, output_summary, started_at, completed_at) for auditing.
- idempotency_keys: replay guard (key -> run_id, opportunity_id, created_at) so
  an irreversible action is never re-executed after a restart/replay.

Restart recovery
----------------
``recover_incomplete()`` marks any run still PENDING/IN_FLIGHT/RUNNING as
FAILED("interrupted by restart") so the ledger is consistent and nothing is
silently re-executed. Idempotency keys are terminal once recorded.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional


class AutonomousRunStore:
    """Thread-safe, append-friendly SQLite ledger for autonomous runs."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS autonomous_runs (
                    run_id          TEXT PRIMARY KEY,
                    opportunity_id  TEXT NOT NULL,
                    correlation_id  TEXT DEFAULT '',
                    status          TEXT NOT NULL,
                    decision        TEXT DEFAULT '',
                    success         INTEGER DEFAULT 0,
                    paid            INTEGER DEFAULT 0,
                    payment_amount  REAL DEFAULT 0.0,
                    decision_reason TEXT DEFAULT '',
                    explanation     TEXT DEFAULT '',
                    model_metadata  TEXT DEFAULT '{}',
                    created_at      REAL,
                    updated_at      REAL,
                    stages_json     TEXT DEFAULT '[]',
                    errors_json     TEXT DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_runs_opp ON autonomous_runs(opportunity_id);
                CREATE INDEX IF NOT EXISTS idx_runs_updated ON autonomous_runs(updated_at);

                CREATE TABLE IF NOT EXISTS autonomous_stage_runs (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id         TEXT NOT NULL,
                    stage          TEXT NOT NULL,
                    status         TEXT NOT NULL,
                    model          TEXT DEFAULT '',
                    latency_ms     INTEGER DEFAULT 0,
                    error          TEXT DEFAULT '',
                    output_summary TEXT DEFAULT '',
                    started_at     REAL,
                    completed_at   REAL
                );
                CREATE INDEX IF NOT EXISTS idx_stage_run ON autonomous_stage_runs(run_id);

                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    key            TEXT PRIMARY KEY,
                    run_id         TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL,
                    created_at     REAL
                );
                """
            )

    # ── write helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _json(obj: Any) -> str:
        return json.dumps(obj, default=str)

    def save_run(self, run: Any, opportunity_id: str,
                 model_metadata: Optional[Dict[str, Any]] = None,
                 correlation_id: str = "") -> str:
        """Persist an AutonomousResult (or any object with a to_dict()/attrs).

        Returns the run_id. Idempotent on run_id (INSERT OR REPLACE keeps the
        latest terminal state). Also upserts each stage into stage_runs.
        """
        d = run.to_dict() if hasattr(run, "to_dict") else run
        run_id = d.get("run_id") or d.get("opportunity_id") or f"run-{int(time.time()*1000)}"
        now = time.time()
        stages = d.get("stages", [])
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO autonomous_runs
                (run_id, opportunity_id, correlation_id, status, decision, success,
                 paid, payment_amount, decision_reason, explanation, model_metadata,
                 created_at, updated_at, stages_json, errors_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id, opportunity_id, correlation_id,
                    d.get("status", "DONE"),
                    d.get("decision", ""),
                    1 if d.get("success") else 0,
                    1 if d.get("paid") else 0,
                    float(d.get("payment_amount", 0.0) or 0.0),
                    d.get("decision_reason", ""),
                    d.get("explanation", ""),
                    self._json(model_metadata or {}),
                    now, now,
                    self._json(stages),
                    self._json(d.get("errors", [])),
                ),
            )
            for s in stages:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO autonomous_stage_runs
                    (run_id, stage, status, model, latency_ms, error,
                     output_summary, started_at, completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id, s.get("stage", ""), s.get("status", ""),
                        s.get("model", ""), int(s.get("duration_s", 0) * 1000),
                        s.get("error", ""),
                        self._summarize(s.get("data", {})),
                        now, now,
                    ),
                )
        return run_id

    def update_run_status(self, run_id: str, status: str,
                          decision: Optional[str] = None,
                          reason: Optional[str] = None) -> None:
        with self._lock, self._conn() as conn:
            sets = ["status=?", "updated_at=?"]
            params: List[Any] = [status, time.time()]
            if decision is not None:
                sets.append("decision=?")
                params.append(decision)
            if reason is not None:
                sets.append("decision_reason=?")
                params.append(reason)
            params.append(run_id)
            conn.execute(f"UPDATE autonomous_runs SET {', '.join(sets)} WHERE run_id=?",
                         params)

    @staticmethod
    def _summarize(data: Any, limit: int = 160) -> str:
        if isinstance(data, dict):
            try:
                return json.dumps(data, default=str)[:limit]
            except Exception:
                return str(data)[:limit]
        return str(data)[:limit]

    # ── idempotency ─────────────────────────────────────────────────────────
    def is_idempotent(self, key: str) -> bool:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM idempotency_keys WHERE key=?", (key,)).fetchone()
        return row is not None

    def mark_idempotent(self, key: str, run_id: str, opportunity_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO idempotency_keys (key, run_id, opportunity_id, created_at) "
                "VALUES (?,?,?,?)",
                (key, run_id, opportunity_id, time.time()),
            )

    # ── read ────────────────────────────────────────────────────────────────
    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM autonomous_runs WHERE run_id=?", (run_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM autonomous_runs ORDER BY updated_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        with self._lock, self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM autonomous_runs").fetchone()[0]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        for key in ("stages_json", "errors_json", "model_metadata"):
            try:
                d[key.replace("_json", "")] = json.loads(d.pop(key) or "[]")
            except (ValueError, TypeError):
                d[key.replace("_json", "")] = []
        d["success"] = bool(d.get("success"))
        d["paid"] = bool(d.get("paid"))
        return d

    # ── restart recovery ────────────────────────────────────────────────────
    def recover_incomplete(self, terminal: str = "FAILED",
                           reason: str = "interrupted by restart") -> int:
        """Mark any non-terminal run as failed (restart safety). Returns count."""
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "SELECT run_id FROM autonomous_runs WHERE status NOT IN "
                "('DONE','FAILED','CANCELLED','COMPLETED')")
            ids = [r[0] for r in cur.fetchall()]
            if ids:
                now = time.time()
                for rid in ids:
                    conn.execute(
                        "UPDATE autonomous_runs SET status=?, decision_reason=?, "
                        "updated_at=? WHERE run_id=?",
                        (terminal, reason, now, rid))
        return len(ids)


__all__ = ["AutonomousRunStore"]
