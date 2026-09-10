"""
database.py — SQLite persistence layer for the agent system.
"""
import sqlite3
import json
import time
import os
import threading
from pathlib import Path
from datetime import datetime

ROOT_FOLDER = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT_FOLDER, "agent.db")


class AgentDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _execute(self, sql, params=(), commit=False):
        with self._lock:
            cursor = self._conn.execute(sql, params)
            if commit:
                self._conn.commit()
            return cursor

    def _create_tables(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS thoughts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL    NOT NULL,
                source      TEXT    NOT NULL,
                text        TEXT    NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS llm_calls (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL    NOT NULL,
                model        TEXT    NOT NULL,
                provider     TEXT    NOT NULL,
                trigger      TEXT,
                prompt_chars INTEGER,
                response_chars INTEGER,
                latency_ms   INTEGER,
                error        TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL    NOT NULL,
                event_type  TEXT    NOT NULL,
                source      TEXT    NOT NULL,
                message     TEXT    NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS research_cache (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL    NOT NULL,
                folder_path  TEXT    NOT NULL,
                file_count   INTEGER,
                root_chars   INTEGER,
                research_chars INTEGER,
                payload      TEXT    NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS actions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL    NOT NULL,
                trigger     TEXT    NOT NULL,
                action_text TEXT    NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS decisions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL    NOT NULL,
                trigger      TEXT    NOT NULL,
                full_text    TEXT    NOT NULL,
                action_part  TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS file_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_path TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                content TEXT NOT NULL,
                size INTEGER,
                mtime REAL,
                last_accessed REAL,
                UNIQUE(folder_path, relative_path)
            )""",
            """CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS proposals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL    NOT NULL,
                gig_title    TEXT,
                platform     TEXT,
                budget_usd   REAL,
                draft        TEXT    NOT NULL,
                status       TEXT    DEFAULT 'drafted'
            )""",
            "CREATE INDEX IF NOT EXISTS idx_proposals_ts ON proposals(ts)",
            """CREATE TABLE IF NOT EXISTS instruction_quarantine (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL    NOT NULL,
                url          TEXT    NOT NULL,
                kind         TEXT    DEFAULT 'skill.md',
                title        TEXT,
                content_hash TEXT    NOT NULL,
                content      TEXT    NOT NULL,
                status       TEXT    DEFAULT 'pending'
            )""",
            """CREATE TABLE IF NOT EXISTS instruction_allowlist (
                url          TEXT PRIMARY KEY,
                content_hash TEXT,
                title        TEXT,
                approved_at  REAL    NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS instruction_blacklist (
                url          TEXT PRIMARY KEY,
                content_hash TEXT,
                related      TEXT,
                rejected_at  REAL    NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_inst_q_status ON instruction_quarantine(status)",
            "CREATE INDEX IF NOT EXISTS idx_inst_q_hash   ON instruction_quarantine(content_hash)",
            "CREATE INDEX IF NOT EXISTS idx_thoughts_ts   ON thoughts(ts)",
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_ts  ON llm_calls(ts)",
            "CREATE INDEX IF NOT EXISTS idx_actions_ts    ON actions(ts)",
            "CREATE INDEX IF NOT EXISTS idx_thoughts_source ON thoughts(source)",
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_trigger ON llm_calls(trigger)",
            "CREATE INDEX IF NOT EXISTS idx_actions_trigger ON actions(trigger)",
            "CREATE INDEX IF NOT EXISTS idx_file_cache_path ON file_cache(folder_path, relative_path)",
            """CREATE TABLE IF NOT EXISTS evidence (
                id              TEXT PRIMARY KEY,
                source          TEXT    NOT NULL,
                evidence_type   TEXT    NOT NULL,
                subject_type    TEXT    NOT NULL,
                subject_id      TEXT    NOT NULL,
                external_id     TEXT    NOT NULL DEFAULT '',
                parent_evidence_id TEXT NOT NULL DEFAULT '',
                observed_at     REAL    NOT NULL,
                recorded_at     REAL    NOT NULL,
                status          TEXT    NOT NULL,
                verification_method TEXT NOT NULL DEFAULT 'local_record',
                verification_level INTEGER NOT NULL DEFAULT 1,
                amount          REAL    NOT NULL DEFAULT 0.0,
                currency        TEXT    NOT NULL DEFAULT '',
                gross_amount    REAL    NOT NULL DEFAULT 0.0,
                fees            REAL    NOT NULL DEFAULT 0.0,
                gas             REAL    NOT NULL DEFAULT 0.0,
                tax_expense     REAL    NOT NULL DEFAULT 0.0,
                other_expenses  REAL    NOT NULL DEFAULT 0.0,
                source_reference TEXT    NOT NULL DEFAULT '',
                raw_reference   TEXT    NOT NULL DEFAULT '',
                metadata        TEXT    NOT NULL DEFAULT '{}',
                provenance      TEXT    NOT NULL DEFAULT '{}',
                history         TEXT    NOT NULL DEFAULT '[]'
            )""",
            "CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence(subject_type, subject_id)",
            "CREATE INDEX IF NOT EXISTS idx_evidence_type    ON evidence(evidence_type)",
            "CREATE INDEX IF NOT EXISTS idx_evidence_status  ON evidence(status)",
            "CREATE INDEX IF NOT EXISTS idx_evidence_parent  ON evidence(parent_evidence_id)",
        ]
        for statement in statements:
            try:
                self._conn.execute(statement)
            except sqlite3.OperationalError:
                # Safe for repeated startup, and tolerant of partially-created schemas.
                pass
        self._conn.commit()

        # Migration: add missing columns to legacy databases (idempotent).
        # Uses per-column try/except so it works on any SQLite version.
        for col_def in [
            "prompt_tokens INTEGER DEFAULT 0",
            "completion_tokens INTEGER DEFAULT 0",
            "tokens_per_second REAL DEFAULT 0",
            "cost_usd REAL DEFAULT 0",
        ]:
            try:
                self._conn.execute(f"ALTER TABLE llm_calls ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass  # Column already exists
        self._conn.commit()

    def get_cached_file(self, folder_path: str, relative_path: str,
                        max_chars: int = None, current_mtime: float = None) -> str | None:
        row = self._execute(
            "SELECT content, mtime FROM file_cache WHERE folder_path=? AND relative_path=?",
            (folder_path, relative_path)
        ).fetchone()
        if row and (current_mtime is None or row["mtime"] == current_mtime):
            content = row["content"]
            self._execute(
                "UPDATE file_cache SET last_accessed=? WHERE folder_path=? AND relative_path=?",
                (time.time(), folder_path, relative_path),
                commit=True
            )
            if max_chars and len(content) > max_chars:
                return content[:max_chars]
            return content
        return None

    def save_file_to_cache(self, folder_path: str, relative_path: str,
                           content: str, size: int, mtime: float):
        self._execute(
            """INSERT OR REPLACE INTO file_cache
            (folder_path, relative_path, content, size, mtime, last_accessed)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (folder_path, relative_path, content, size, mtime, time.time()),
            commit=True
        )

    def clear_file_cache(self, folder_path: str = None):
        if folder_path:
            self._execute("DELETE FROM file_cache WHERE folder_path=?", (folder_path,))
        else:
            self._execute("DELETE FROM file_cache")
        self._conn.commit()

    # ------------------------------------------------------------------
    # Thoughts
    # ------------------------------------------------------------------
    def log_thought(self, source: str, text: str):
        self._execute(
            "INSERT INTO thoughts (ts, source, text) VALUES (?, ?, ?)",
            (time.time(), source, text),
            commit=True
        )

    def get_thoughts(self, limit: int = 500, source: str = None) -> list[dict]:
        if source:
            rows = self._execute(
                "SELECT ts, source, text FROM thoughts WHERE source=? ORDER BY ts DESC LIMIT ?",
                (source, limit)
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT ts, source, text FROM thoughts ORDER BY ts DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------
    def log_llm_call(self, model: str, provider: str, trigger: str,
                     prompt_chars: int, response_chars: int,
                     latency_ms: int, error: str = None):
        self._execute(
            """INSERT INTO llm_calls
               (ts, model, provider, trigger, prompt_chars, response_chars, latency_ms, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), model, provider, trigger,
             prompt_chars, response_chars, latency_ms, error),
            commit=True
        )

    def get_llm_stats(self) -> dict:
        row = self._execute("""
            SELECT
                COALESCE(COUNT(*), 0) AS total_calls,
                COALESCE(SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END), 0) AS successes,
                COALESCE(SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END), 0) AS errors,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                COALESCE(SUM(prompt_chars + response_chars), 0) AS total_chars
            FROM llm_calls
        """).fetchone()
        return dict(row) if row else {}

    def get_recent_llm_calls(self, limit: int = 50) -> list[dict]:
        rows = self._execute(
            """SELECT ts, model, provider, trigger, prompt_chars,
                      response_chars, latency_ms, error
               FROM llm_calls ORDER BY ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── A3: LLM cost estimation ────────────────────────────────────────────────
    # llm_calls stores char counts, not tokens. Estimate tokens via the standard
    # chars/4 heuristic (no on-disk tokenizer available). Cost is then priced from
    # provider_models static pricing tables. This is an ESTIMATE, surfaced as such.
    _CHARS_PER_TOKEN = 4.0

    def _est_tokens(self, prompt_chars: int, response_chars: int) -> tuple[float, float]:
        total = (int(prompt_chars or 0) + int(response_chars or 0)) / self._CHARS_PER_TOKEN
        # Rough split: prompts tend to dominate input, completions output. Use 60/40.
        return total * 0.6, total * 0.4  # (in_tokens, out_tokens)

    def get_llm_cost_breakdown(self, days: int = 30) -> list[dict]:
        """A3: estimated LLM spend per (model, provider) over `days`.

        Returns list of {model, provider, calls, prompt_chars, response_chars,
        est_usd} sorted by est_usd desc. Free/unknown models price to $0.
        """
        since = time.time() - (days * 86400)
        try:
            from provider_models import _price_for
        except Exception:
            _price_for = None

        rows = self._execute(
            """SELECT model, provider, COUNT(*),
                      COALESCE(SUM(prompt_chars),0),
                      COALESCE(SUM(response_chars),0)
               FROM llm_calls WHERE ts > ?
               GROUP BY model, provider""",
            (since,),
        ).fetchall()

        out = []
        for model, provider, calls, pc, rc in rows:
            in_t, out_t = self._est_tokens(pc, rc)
            price_in, price_out = (None, None)
            if _price_for is not None:
                try:
                    price_in, price_out = _price_for(model or "")
                except Exception:
                    price_in, price_out = None, None
            if price_in is None and price_out is None:
                est = 0.0
            else:
                inn = price_in or 0.0
                outn = price_out or 0.0
                est = (in_t * inn + out_t * outn) / 1_000_000.0
            out.append({
                "model": model, "provider": provider, "calls": calls,
                "prompt_chars": pc, "response_chars": rc,
                "est_usd": round(est, 4),
            })
        out.sort(key=lambda d: d["est_usd"], reverse=True)
        return out

    def get_llm_cost_usd(self, days: int = 30) -> float:
        """A3: total estimated LLM API spend over `days` (USD)."""
        return round(sum(d["est_usd"] for d in self.get_llm_cost_breakdown(days)), 4)

    # ------------------------------------------------------------------
    # Drafted proposals (v2.0.21 P2#4)
    # ------------------------------------------------------------------
    def add_proposal(self, gig_title: str = None, platform: str = None,
                     budget_usd: float = 0.0, draft: str = "",
                     status: str = "drafted") -> int:
        """Persist a drafted gig proposal so work survives restart and shows in
        DB Stats. Returns the new row id."""
        cur = self._execute(
            """INSERT INTO proposals
               (ts, gig_title, platform, budget_usd, draft, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (time.time(), gig_title, platform, float(budget_usd or 0), draft, status),
            commit=True
        )
        return cur.lastrowid

    def get_proposals(self, limit: int = 100) -> list[dict]:
        rows = self._execute(
            """SELECT id, ts, gig_title, platform, budget_usd, status
               FROM proposals ORDER BY ts DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def count_proposals(self) -> int:
        row = self._execute("SELECT COUNT(*) AS n FROM proposals").fetchone()
        return int(row["n"]) if row else 0

    def proposal_exists(self, gig_title: str, platform: str = None) -> bool:
        """True if a proposal draft already exists for this gig title+platform.

        Used to avoid re-saving duplicate drafts every heartbeat (the job queue
        re-discovers the same Fiverr/Upwork gigs each cycle, and the old save
        path blindly inserted a new row each time). Cheap indexed lookup — we
        match on title + platform where possible, falling back to title alone.
        """
        try:
            if platform:
                row = self._execute(
                    "SELECT 1 FROM proposals WHERE gig_title=? AND platform=? LIMIT 1",
                    (gig_title, platform),
                ).fetchone()
            else:
                row = self._execute(
                    "SELECT 1 FROM proposals WHERE gig_title=? LIMIT 1",
                    (gig_title,),
                ).fetchone()
            return row is not None
        except Exception:
            # On any DB hiccup, treat as "not present" so we don't silently drop
            # a draft — better to save a possible duplicate than lose one.
            return False

    # ------------------------------------------------------------------
    # Instruction provenance gate (v2.0.22 S1): untrusted external playbooks
    # discovered on platforms (e.g. remote SKILL.md). Never executed until a
    # human approves; rejected -> blacklisted (always ignored).
    # ------------------------------------------------------------------
    def in_instruction_allowlist(self, url: str) -> bool:
        row = self._execute(
            "SELECT 1 FROM instruction_allowlist WHERE url=?", (url,)
        ).fetchone()
        return row is not None

    def in_instruction_blacklist(self, url: str) -> bool:
        row = self._execute(
            "SELECT 1 FROM instruction_blacklist WHERE url=?", (url,)
        ).fetchone()
        return row is not None

    def add_quarantined_instruction(self, url: str, kind: str, title: str,
                                    content_hash: str, content: str) -> int:
        cur = self._execute(
            """INSERT INTO instruction_quarantine
               (ts, url, kind, title, content_hash, content, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (time.time(), url, kind, title, content_hash, content),
            commit=True
        )
        return cur.lastrowid

    def find_quarantined_by_hash(self, content_hash: str) -> dict | None:
        row = self._execute(
            "SELECT * FROM instruction_quarantine WHERE content_hash=? "
            "ORDER BY id DESC LIMIT 1",
            (content_hash,)
        ).fetchone()
        return dict(row) if row else None

    def review_instruction(self, quarantine_id: int, approve: bool,
                           url: str = "", content_hash: str = "",
                           related: str = "") -> str:
        """Move a pending instruction to allowed (allowlist) or blocked
        (blacklist). Returns the resulting status string."""
        now = time.time()
        if approve:
            self._execute(
                "UPDATE instruction_quarantine SET status='allowed' WHERE id=?",
                (quarantine_id,), commit=True)
            self._execute(
                """INSERT OR REPLACE INTO instruction_allowlist
                   (url, content_hash, title, approved_at)
                   VALUES (?, ?, '', ?)""",
                (url, content_hash, now), commit=True)
            return "allowed"
        else:
            self._execute(
                "UPDATE instruction_quarantine SET status='blocked' WHERE id=?",
                (quarantine_id,), commit=True)
            self._execute(
                """INSERT OR REPLACE INTO instruction_blacklist
                   (url, content_hash, related, rejected_at)
                   VALUES (?, ?, ?, ?)""",
                (url, content_hash, related, now), commit=True)
            return "blocked"

    def list_pending_instructions(self, limit: int = 100) -> list[dict]:
        rows = self._execute(
            "SELECT id, ts, url, kind, title, content_hash, status "
            "FROM instruction_quarantine WHERE status='pending' "
            "ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def count_instruction_lists(self) -> dict:
        q = self._execute("SELECT COUNT(*) n FROM instruction_quarantine").fetchone()
        a = self._execute("SELECT COUNT(*) n FROM instruction_allowlist").fetchone()
        b = self._execute("SELECT COUNT(*) n FROM instruction_blacklist").fetchone()
        return {"quarantined": int(q["n"]), "allowed": int(a["n"]),
                "blocked": int(b["n"]), "pending": len(self.list_pending_instructions())}

    def save_research_cache(self, research: dict):
        folder = research.get("research_path") or "root_only"
        self._execute(
            """INSERT INTO research_cache
               (ts, folder_path, file_count, root_chars, research_chars, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                folder,
                research.get("research_file_count", 0),
                len(research.get("root", "")),
                len(research.get("research", "")),
                json.dumps(research, default=str),
            ),
            commit=True
        )

    def load_latest_research_cache(self, folder_path: str) -> dict | None:
        row = self._execute(
            """SELECT payload FROM research_cache
               WHERE folder_path=? ORDER BY ts DESC LIMIT 1""",
            (folder_path,)
        ).fetchone()
        if row:
            try:
                return json.loads(row["payload"])
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------
    # Actions & decisions
    # ------------------------------------------------------------------
    def log_action(self, trigger: str, action_text: str):
        self._execute(
            "INSERT INTO actions (ts, trigger, action_text) VALUES (?, ?, ?)",
            (time.time(), trigger, action_text),
            commit=True
        )

    def log_decision(self, trigger: str, full_text: str, action_part: str = None):
        self._execute(
            """INSERT INTO decisions (ts, trigger, full_text, action_part)
               VALUES (?, ?, ?, ?)""",
            (time.time(), trigger, full_text, action_part),
            commit=True
        )

    def get_recent_actions(self, limit: int = 20) -> list[dict]:
        rows = self._execute(
            "SELECT ts, trigger, action_text FROM actions ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    def ts_to_str(self, ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    def close(self):
        self._conn.close()
    
    # ── Events ─────────────────────────────────────────────────────────────
    
    def log_event(self, event_type: str, source: str, message: str):
        """Log an event."""
        import time
        self._execute(
            "INSERT INTO events (ts, event_type, source, message) VALUES (?, ?, ?, ?)",
            (time.time(), event_type, source, message),
            commit=True
        )
    
    def get_recent_events(self, limit: int = 100) -> list[dict]:
        """Get recent events."""
        rows = self._execute(
            "SELECT ts, event_type, source, message FROM events ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    
    # ── Enhanced LLM stats ─────────────────────────────────────────────────
    
    def get_llm_stats(self) -> dict:
        """Get comprehensive LLM statistics."""
        row = self._execute("""
            SELECT
                COALESCE(COUNT(*), 0) AS total_calls,
                COALESCE(SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END), 0) AS successes,
                COALESCE(SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END), 0) AS errors,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                COALESCE(SUM(prompt_chars + response_chars), 0) AS total_chars,
                COALESCE(SUM(cost_usd), 0) AS total_cost,
                COALESCE(AVG(tokens_per_second), 0) AS avg_tokens_per_second,
                COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens
            FROM llm_calls
        """).fetchone()
        
        stats = dict(row) if row else {}
        
        # Get per-provider stats
        provider_rows = self._execute("""
            SELECT provider,
                   COUNT(*) as calls,
                   SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as errors,
                   AVG(latency_ms) as avg_ms,
                   AVG(tokens_per_second) as avg_tok_s
            FROM llm_calls
            GROUP BY provider
        """).fetchall()
        stats["by_provider"] = {r["provider"]: dict(r) for r in provider_rows}
        
        # Get per-model stats
        model_rows = self._execute("""
            SELECT model,
                   COUNT(*) as calls,
                   SUM(prompt_tokens) as tokens_in,
                   SUM(completion_tokens) as tokens_out,
                   AVG(tokens_per_second) as avg_tok_s
            FROM llm_calls
            GROUP BY model
        """).fetchall()
        stats["by_model"] = {r["model"]: dict(r) for r in model_rows}
        
        # Get uptime (time since first call)
        first_call = self._execute("SELECT MIN(ts) as first_ts FROM llm_calls").fetchone()
        if first_call and first_call["first_ts"]:
            import time
            stats["uptime_hours"] = round((time.time() - first_call["first_ts"]) / 3600, 1)
        else:
            stats["uptime_hours"] = 0
        
        # Get DB size
        try:
            import os
            db_path = self._execute("PRAGMA database_list").fetchone()["name"]
            stats["db_size_mb"] = round(os.path.getsize(db_path) / (1024 * 1024), 2)
        except Exception:
            stats["db_size_mb"] = 0
        
        return stats