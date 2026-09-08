"""
agents/summarizer.py — Enhanced SummarizerThread

Improvements over v1:
  ─────────────────────────────────────────────────────
  • Own SQLite database (summarizer.db) — separate from agent.db
  • Conversation history stored & retrieved across sessions
  • Speech pattern learning (SpeechPatternBank from library)
    – Observes every human message
    – Style description shown in UI
    – LLM prompted to match the user's communication style
  • Human ↔ Summarizer chat
    – send_human_message(text)  →  chat_reply Signal(str, str)
    – Full conversation memory with rolling window
    – Quick-action shortcuts
  • Configurable summarization strategy:
    – "brief"   : one-sentence
    – "standard": paragraph
    – "detailed": bullets + next-step
  • EmbeddingCache dedup — skip summarising near-identical thought batches
  • Graceful degradation when LLM unavailable
  • Topic tracking — logs what was discussed per session
  ─────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import json
import queue
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from PySide6.QtCore import QThread, Signal

# ── library imports ────────────────────────────────────────────────────────────
from library import (
    ConversationMemory,
    SpeechPatternBank,
    EmbeddingCache,
    AgentLogger,
    fingerprint,
    ts_now,
)
from agents.chat_router import ChatRouter
from agents.comms import Message, MessageType, EventBus

ROOT_FOLDER  = os.path.dirname(os.path.abspath(__file__))
SUMM_DB_PATH = os.path.join(ROOT_FOLDER, "summarizer.db")


# ═══════════════════════════════════════════════════════════════════════════
#  SummarizerDB  — dedicated persistence layer
# ═══════════════════════════════════════════════════════════════════════════
class SummarizerDB:
    """
    SQLite database dedicated to the summarizer.
    Stores:
      - summaries          : timestamped summaries with topic tags
      - chat_history       : human ↔ summarizer conversation log
      - speech_patterns    : serialised SpeechPatternBank export per session
      - topic_index        : rolling topic frequency table
    """

    def __init__(self, db_path: str = SUMM_DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _execute(self, sql, params=(), commit=False):
        # v2.0.24: ensure chat_history.thinking exists on older DBs
        try:
            cols = [r[1] for r in self._conn.execute(
                "PRAGMA table_info(chat_history)").fetchall()]
            if "thinking" not in cols:
                self._conn.execute(
                    "ALTER TABLE chat_history ADD COLUMN thinking TEXT DEFAULT ''")
                self._conn.commit()
        except Exception:
            pass
        # Always return the cursor so queries can .fetchone()/.fetchall().
        # (The v2.0.24 migration edit had accidentally placed `return cur`
        # inside the except block, causing _execute() to return None on the
        # normal path and crashing load_latest_speech_patterns().)
        with self._lock:
            cur = self._conn.execute(sql, params)
            if commit:
                self._conn.commit()
        return cur

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS summaries (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        REAL    NOT NULL,
                text      TEXT    NOT NULL,
                strategy  TEXT    DEFAULT 'standard',
                topics    TEXT    DEFAULT '',
                fp        TEXT    DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS chat_history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        REAL    NOT NULL,
                role      TEXT    NOT NULL,
                text      TEXT    NOT NULL,
                session   TEXT    DEFAULT '',
                thinking  TEXT    DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS speech_patterns (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        REAL    NOT NULL,
                session   TEXT    NOT NULL,
                payload   TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS topic_index (
                topic     TEXT    PRIMARY KEY,
                count     INTEGER DEFAULT 1,
                last_seen REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_summaries_ts      ON summaries(ts);
            CREATE INDEX IF NOT EXISTS idx_chat_history_ts   ON chat_history(ts);
            CREATE INDEX IF NOT EXISTS idx_topic_count       ON topic_index(count DESC);
            CREATE TABLE IF NOT EXISTS role_memory (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       REAL    NOT NULL,
                role     TEXT    NOT NULL,
                kind     TEXT    DEFAULT 'exchange',
                text     TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS longterm_notes (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       REAL    NOT NULL,
                topic    TEXT    NOT NULL,
                text     TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_role_memory_role_ts ON role_memory(role, ts);
            CREATE INDEX IF NOT EXISTS idx_longterm_topic     ON longterm_notes(topic);
        """)
        self._conn.commit()

    # ── Summaries ─────────────────────────────────────────────────────────────
    def save_summary(self, text: str, strategy: str = "standard",
                     topics: List[str] = None, fp: str = ""):
        self._execute(
            "INSERT INTO summaries (ts, text, strategy, topics, fp) VALUES (?,?,?,?,?)",
            (time.time(), text, strategy, json.dumps(topics or []), fp),
            commit=True
        )

    def get_recent_summaries(self, limit: int = 20) -> List[Dict]:
        rows = self._execute(
            "SELECT ts, text, strategy, topics FROM summaries ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_summary_count(self) -> int:
        return self._execute("SELECT COUNT(*) FROM summaries").fetchone()[0]

    # ── Chat history ──────────────────────────────────────────────────────────
    def save_chat_turn(self, role: str, text: str, session: str = "", thinking: str = ""):
        self._execute(
            "INSERT INTO chat_history (ts, role, text, session, thinking) VALUES (?,?,?,?,?)",
            (time.time(), role, text, session, thinking or ""),
            commit=True
        )

    def get_recent_chat(self, limit: int = 40, session: str = None) -> List[Dict]:
        # ensure thinking column exists before SELECT
        try:
            cols = [r[1] for r in self._conn.execute(
                "PRAGMA table_info(chat_history)").fetchall()]
            if "thinking" not in cols:
                self._conn.execute(
                    "ALTER TABLE chat_history ADD COLUMN thinking TEXT DEFAULT ''")
                self._conn.commit()
        except Exception:
            pass
        if session:
            rows = self._execute(
                "SELECT ts, role, text FROM chat_history "
                "WHERE session=? ORDER BY ts DESC LIMIT ?",
                (session, limit)
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT ts, role, text FROM chat_history ORDER BY ts DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ── v2.0.34ad (Section E G6): per-role memory + long-term notes ────────────
    def add_role_memory(self, role: str, text: str, kind: str = "exchange"):
        """Append a memory entry for a role ('chat' or 'main'/CEO)."""
        if role not in ("chat", "main"):
            role = "main"
        self._execute(
            "INSERT INTO role_memory (ts, role, kind, text) VALUES (?,?,?,?)",
            (time.time(), role, kind, text),
            commit=True
        )

    def get_role_memory(self, role: str, limit: int = 20, include_summaries: bool = True) -> List[Dict]:
        """Return recent memory entries for a role (newest last), optionally
        including the latest rolling summary first."""
        rows = self._execute(
            "SELECT ts, role, kind, text FROM role_memory "
            "WHERE role=? ORDER BY ts DESC LIMIT ?",
            (role, limit)
        ).fetchall()
        out = [dict(r) for r in reversed(rows)]
        if include_summaries:
            # surface the most recent summary as context up top
            summ = self._execute(
                "SELECT text FROM role_memory WHERE role=? AND kind='summary' "
                "ORDER BY ts DESC LIMIT 1",
                (role,)
            ).fetchone()
            if summ:
                out.insert(0, {"ts": 0, "role": role, "kind": "summary", "text": summ["text"]})
        return out

    def summarize_role_memory(self, role: str, keep: int = 8) -> Optional[str]:
        """Compact older exchanges into one summary row; keep `keep` recent rows.
        Returns the new summary text (or None if nothing to summarize)."""
        rows = self._execute(
            "SELECT id, text FROM role_memory WHERE role=? AND kind='exchange' "
            "ORDER BY ts ASC",
            (role,)
        ).fetchall()
        if len(rows) <= keep:
            return None
        to_compact = rows[:-keep]
        compacted_ids = [r["id"] for r in to_compact]
        summary_text = "Summary of earlier exchanges:\n" + "\n".join(
            f"- {r['text'][:240]}" for r in to_compact[-keep:]
        )
        # delete compacted exchange rows, insert one summary
        qmarks = ",".join("?" * len(compacted_ids))
        self._execute(
            f"DELETE FROM role_memory WHERE id IN ({qmarks})", tuple(compacted_ids), commit=True
        )
        self.add_role_memory(role, summary_text, kind="summary")
        return summary_text

    def clear_role_memory(self, role: str):
        self._execute("DELETE FROM role_memory WHERE role=?", (role,), commit=True)

    def add_note(self, topic: str, text: str):
        self._execute(
            "INSERT INTO longterm_notes (ts, topic, text) VALUES (?,?,?)",
            (time.time(), topic, text), commit=True
        )

    def get_notes(self, topic: str = None, limit: int = 50) -> List[Dict]:
        if topic:
            rows = self._execute(
                "SELECT ts, topic, text FROM longterm_notes WHERE topic=? "
                "ORDER BY ts DESC LIMIT ?", (topic, limit)
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT ts, topic, text FROM longterm_notes ORDER BY ts DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def clear_notes(self, topic: str = None):
        if topic:
            self._execute("DELETE FROM longterm_notes WHERE topic=?", (topic,), commit=True)
        else:
            self._execute("DELETE FROM longterm_notes", (), commit=True)

    # ── Speech patterns ───────────────────────────────────────────────────────
    def save_speech_patterns(self, session: str, bank: SpeechPatternBank):
        payload = json.dumps(bank.export())
        self._execute(
            "INSERT INTO speech_patterns (ts, session, payload) VALUES (?,?,?)",
            (time.time(), session, payload),
            commit=True
        )

    def load_latest_speech_patterns(self, session: str = "") -> Optional[Dict]:
        cur = self._execute(
            "SELECT payload FROM speech_patterns ORDER BY ts DESC LIMIT 1"
        )
        row = cur.fetchone() if cur is not None else None
        if row:
            try:
                return json.loads(row["payload"])
            except Exception:
                pass
        return None

    # ── Topics ────────────────────────────────────────────────────────────────
    def update_topics(self, topics: List[str]):
        for topic in topics:
            t = topic.lower().strip()
            if not t:
                continue
            self._execute(
                """INSERT INTO topic_index (topic, count, last_seen) VALUES (?,1,?)
                   ON CONFLICT(topic) DO UPDATE SET
                     count = count + 1, last_seen = excluded.last_seen""",
                (t, time.time()),
                commit=False
            )
        self._conn.commit()

    def get_top_topics(self, limit: int = 10) -> List[Dict]:
        rows = self._execute(
            "SELECT topic, count FROM topic_index ORDER BY count DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()


# ═══════════════════════════════════════════════════════════════════════════
#  SummarizerThread
# ═══════════════════════════════════════════════════════════════════════════
class SummarizerThread(QThread):
    """
    Background thread that:
      1. Watches manager/agent/comms thought streams
      2. Periodically distils them into plain-English summaries
      3. Answers direct human chat messages
      4. Learns the human's speech patterns and mirrors them
    """

    summary_ready   = Signal(str)          # new auto-summary text
    chat_reply      = Signal(str, str, str)  # (label, text, thinking) — thinking may be ""
    status_changed  = Signal(str, str)     # (status, task)
    paused_changed  = Signal(bool)
    style_updated   = Signal(str)          # human-readable style description

    # ── Summarization strategy prompts ──────────────────────────────────────
    _STRATEGY_PROMPTS = {
        "brief": (
            "Summarise what the agents are doing in ONE plain sentence. "
            "No jargon.  Start with a verb."
        ),
        "standard": (
            "Write a short paragraph (3-5 sentences) explaining what is "
            "happening, what was decided, and what the next step is. "
            "Use plain language — no technical jargon."
        ),
        "detailed": (
            "Write a structured summary with three bullet points:\n"
            "• What happened\n"
            "• What was decided\n"
            "• Next steps\n"
            "Keep each bullet to one sentence.  Plain language."
        ),
    }

    _CHAT_SYSTEM = (
            "You are an assistant embedded in MrBot1000, an AI program for real-time earning opportunity discovery. "
            "You watch the agent's work and can explain the system architecture, models, and tasks. "
            "You have access to recent summaries and conversation history. "
            "Be helpful, accurate, and conversational. Max 250 words unless asked for more. "
            "Always explain technical details clearly. Do not invent capabilities or fake earnings. "
            "If asked about technical details, answer accurately based on your knowledge. "
            "When task results are provided they are optional background you MAY cite "
            "if directly relevant to the user's question; never lead with them or with a "
            "fixed 'Latest concrete result:' phrase. "
            "Do not claim a task was completed unless it appears in the provided evidence."
        )

    def __init__(self, worker, db=None, manager=None):
        super().__init__()
        self.worker   = worker
        self.main_db  = db                    # shared agent.db (optional)
        self.manager  = manager               # ManagerThread ref (for task routing)
        self.summ_db  = SummarizerDB()        # own database

        # Session ID for this run
        self._session = datetime.now().strftime("%Y%m%d_%H%M%S")

        # ── Thought queues ─────────────────────────────────────────────────
        self.manager_queue = queue.Queue()
        self.agent_queue   = queue.Queue()
        self.comms_queue   = queue.Queue()
        self._chat_queue   = queue.Queue()    # human → summarizer chat

        # P2 (comms redesign): subscribe this Chat interface to bus messages
        # addressed to "chat". The bus is the structured ingress; legacy
        # send_human_message(text) still works for direct callers.
        try:
            from agents.comms import EventBus
            EventBus.instance().subscribe_destination("chat", self._on_bus_message)
        except Exception:
            pass

        # ── State ─────────────────────────────────────────────────────────
        self.running = True
        self.paused  = False
        self.pending_thoughts: List[str] = []
        self.last_thought_time = time.time()
        self._recent_thoughts: List[Dict] = []
        self._recent_task_results: List[Dict] = []
        self._max_recent_thoughts = 120
        self._max_recent_task_results = 30

        # ── NLP helpers ───────────────────────────────────────────────────
        self._speech_bank    = SpeechPatternBank(max_samples=300)
        self._embedding_cache = EmbeddingCache(similarity_threshold=0.85,
                                               max_size=150)
        self._conversation   = ConversationMemory(max_chars=8000, max_turns=30)
        self._logger         = AgentLogger(db=db, source="Summarizer",
                                           signal=None)
        self._chat_router    = ChatRouter()

        # ── Configuration ─────────────────────────────────────────────────
        # PERF: 5s poll interval (was 2s) — halves wakeups and LLM trigger rate
        self.interval      = 5.0      # poll interval (seconds)
        self.cooldown      = 15.0     # quiet time before summarising (was 5.0)
        self.min_thoughts  = 8        # minimum new thoughts to trigger summary (was 5)
        self.max_tokens    = 250
        self.max_thoughts  = 20
        self.strategy      = "standard"   # "brief" | "standard" | "detailed"

        self.last_summary  = ""
        self._last_summary_fp = ""

        # ── Restore speech patterns from previous session ─────────────────
        saved_patterns = self.summ_db.load_latest_speech_patterns()
        if saved_patterns:
            try:
                self._speech_bank.import_stats(saved_patterns)
            except Exception:
                pass

        # ── Load chat history into conversation memory ─────────────────────
        recent_chat = self.summ_db.get_recent_chat(limit=20)
        for turn in recent_chat:
            self._conversation.add(turn["role"], turn["text"])

    # ─────────────────────────────────────────────────────────────────────────
    #  Public input methods (called from main thread)
    # ─────────────────────────────────────────────────────────────────────────

    def add_manager_thought(self, text: str):
        self._record_thought("manager", text)
        self.manager_queue.put(("manager", text))
        self._thought_arrived()

    def add_agent_thought(self, text: str):
        self._record_thought("agent", text)
        self.agent_queue.put(("agent", text))
        self._thought_arrived()

    def add_comms_thought(self, direction: str, text: str):
        comms_text = f"[{direction}] {text}"
        self._record_thought("comms", comms_text)
        self.comms_queue.put(("comms", comms_text))
        self._thought_arrived()

    def send_human_message(self, text: str):
        """Queue a human chat message for the summarizer to answer."""
        self._chat_queue.put(text)

    # ── Bus integration (P2 comms redesign) ─────────────────────────────────
    def _on_bus_message(self, msg):
        """EventBus callback: enqueue structured messages addressed to chat."""
        from agents.comms import Message, MessageType
        if not isinstance(msg, Message):
            return
        if msg.destination == "chat" and msg.message_type in (
                MessageType.USER_REQUEST, MessageType.TASK_REQUEST,
                MessageType.MODEL_REQUEST):
            # Store the Message object (not just text) so correlation survives.
            self._chat_queue.put(msg)

    def _thought_arrived(self):
        self.last_thought_time = time.time()

    def _record_thought(self, source: str, text: str):
        entry = {
            "ts": time.time(),
            "source": source,
            "text": text,
        }
        self._recent_thoughts.append(entry)
        if len(self._recent_thoughts) > self._max_recent_thoughts:
            self._recent_thoughts = self._recent_thoughts[-self._max_recent_thoughts:]

        task_result = self._extract_task_result(text)
        if task_result:
            self._recent_task_results.append({
                "ts": entry["ts"],
                "source": source,
                "result": task_result,
            })
            if len(self._recent_task_results) > self._max_recent_task_results:
                self._recent_task_results = self._recent_task_results[-self._max_recent_task_results:]

    @staticmethod
    def _extract_task_result(text: str) -> Optional[str]:
        # Match explicit task output markers emitted by worker/manager flow.
        patterns = [
            r"RESULT:\s*(.+)",
            r"\bResult:\s*(.+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if m:
                value = m.group(1).strip()
                return value[:1200]
        return None

    def _latest_task_results_context(self, limit: int = 3) -> str:
        if not self._recent_task_results:
            return "No recent concrete task results captured."
        latest = self._recent_task_results[-limit:]
        lines = []
        for item in latest:
            ts = self._fmt_ts(item["ts"])
            source = item["source"]
            result = item["result"].replace("\n", " ").strip()
            lines.append(f"[{ts}] ({source}) {result[:1500]}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    #  Configuration
    # ─────────────────────────────────────────────────────────────────────────

    def set_paused(self, paused: bool):
        if self.paused != paused:
            self.paused = paused
            self.paused_changed.emit(paused)
            self.status_changed.emit("Paused" if paused else "Idle", "")

    def set_strategy(self, strategy: str):
        """Change summarization depth: 'brief' | 'standard' | 'detailed'"""
        if strategy in self._STRATEGY_PROMPTS:
            self.strategy = strategy
            self.status_changed.emit("Idle", f"Strategy: {strategy}")

    def update_config(self, interval=None, cooldown=None, min_thoughts=None,
                      max_tokens=None, max_thoughts=None, strategy=None):
        if interval     is not None: self.interval     = interval
        if cooldown     is not None: self.cooldown     = cooldown
        if min_thoughts is not None: self.min_thoughts = min_thoughts
        if max_tokens   is not None: self.max_tokens   = max_tokens
        if max_thoughts is not None: self.max_thoughts = max_thoughts
        if strategy     is not None: self.set_strategy(strategy)

    # ─────────────────────────────────────────────────────────────────────────
    #  Main loop
    # ─────────────────────────────────────────────────────────────────────────

    def run(self):
        self.status_changed.emit("Idle", "Watching thoughts…")

        while self.running:
            # 1. Handle direct human chat (always, even when paused)
            try:
                item = self._chat_queue.get_nowait()
                # P2 (comms redesign): a structured Message carries correlation;
                # a plain str is the legacy direct-call path.
                if isinstance(item, Message):
                    self._handle_chat(item.text(), bus_msg=item)
                else:
                    self._handle_chat(item)
            except queue.Empty:
                pass

            if not self.paused:
                # 2. Drain thought queues
                for q in (self.manager_queue, self.agent_queue,
                          self.comms_queue):
                    while True:
                        try:
                            _source, text = q.get_nowait()
                            self.pending_thoughts.append(text)
                        except queue.Empty:
                            break

                # 3. Check summarization trigger
                now = time.time()
                if (len(self.pending_thoughts) >= self.min_thoughts
                        and (now - self.last_thought_time) >= self.cooldown):
                    self._summarize()

            time.sleep(self.interval)

    # ─────────────────────────────────────────────────────────────────────────
    #  Summarization
    # ─────────────────────────────────────────────────────────────────────────

    def _summarize(self):
        if not self.pending_thoughts:
            return

        thoughts_to_use = self.pending_thoughts[-self.max_thoughts:]
        combined = "\n".join(thoughts_to_use)

        # Dedup: skip if very similar to previous batch
        fp = fingerprint(combined)
        if fp == self._last_summary_fp:
            self.pending_thoughts.clear()
            return
        cached = self._embedding_cache.get(combined)
        if cached and cached == self.last_summary:
            self.pending_thoughts.clear()
            return

        count = len(self.pending_thoughts)
        self.status_changed.emit("Summarizing",
                                 f"Processing {count} thoughts [{self.strategy}]")

        strategy_instruction = self._STRATEGY_PROMPTS[self.strategy]
        style_instruction    = self._speech_bank.as_prompt_instruction()

        system = (
            "You are a helpful assistant that simplifies technical AI agent activity.\n"
            f"{strategy_instruction}\n"
            + (f"\nStyle guidance: {style_instruction}" if style_instruction else "")
        )

        user_prompt = (
            f"Thoughts from agents:\n{combined}\n\n"
            f"Simple explanation:"
        )

        try:
            # For chat mode, use the chat model (faster, smaller)
            summary = self.worker.llm(system=system, user=user_prompt,
                                      max_tokens=self.max_tokens, chat=True, think=False)
            if summary and not summary.startswith("ERROR:"):
                # Extract topics (simple keyword extraction)
                topics = self._extract_topics(combined)

                # Persist
                self.summ_db.save_summary(
                    summary, strategy=self.strategy, topics=topics, fp=fp)
                self.summ_db.update_topics(topics)

                # Emit
                if summary != self.last_summary:
                    self.summary_ready.emit(summary)
                    self.last_summary = summary
                    self._last_summary_fp = fp
                    self._embedding_cache.put(combined, summary)

                    # Add to conversation memory so chat can reference it
                    self._conversation.add("system",
                                           f"[Latest summary] {summary}")
        except Exception as e:
            self._logger.error(f"Summarization error: {e}")
        finally:
            self.pending_thoughts.clear()
            self.status_changed.emit("Idle", "Watching thoughts…")

    def _extract_topics(self, text: str) -> List[str]:
        """
        Simple keyword-based topic extraction (no external ML needed).
        Looks for capitalised words and domain keywords.
        """
        DOMAIN_KEYWORDS = {
            "proposer", "evaluator", "manager", "agent", "research",
            "file", "bug", "fix", "refactor", "error", "action",
            "heartbeat", "scan", "improve", "write", "read", "cache",
            "database", "security", "task", "decision", "response"
        }
        words = set(text.lower().split())
        return [kw for kw in DOMAIN_KEYWORDS if kw in words][:8]

    # ─────────────────────────────────────────────────────────────────────────
    #  Human ↔ Summarizer Chat
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_chat(self, human_text: str, bus_msg: Optional[Message] = None):
        """Process a human message and emit a chat reply.

        P2 (comms redesign): when invoked from the bus, `bus_msg` carries the
        correlation_id + parent; the manager-routing and final reply preserve it.
        """
        self.status_changed.emit("Chatting", "Answering…")

        # Observe speech patterns
        self._speech_bank.observe(human_text)
        style_desc = self._speech_bank.describe()
        self.style_updated.emit(style_desc)

        # Persist speech pattern periodically (every 10 messages)
        if self._speech_bank.sample_count % 10 == 0:
            try:
                self.summ_db.save_speech_patterns(self._session,
                                                  self._speech_bank)
            except Exception:
                pass

        # Save to DB
        self.summ_db.save_chat_turn("user", human_text, self._session)

        # Add to in-memory conversation
        self._conversation.add("user", human_text)

        # Build context: recent summaries + conversation history
        recent_summaries = self.summ_db.get_recent_summaries(limit=5)
        summ_context = "\n".join(
            f"[{self._fmt_ts(s['ts'])}] {s['text']}"
            for s in recent_summaries
        )
        top_topics = self.summ_db.get_top_topics(limit=8)
        topics_str = ", ".join(t["topic"] for t in top_topics) or "none yet"
        latest_results_context = self._latest_task_results_context(limit=3)

        # Style instruction
        style_instruction = self._speech_bank.as_prompt_instruction()
        decision = self._chat_router.classify(human_text)
        # v2.0.22b: keep conversation on THIS independent thread (chat model,
        # never blocked by the Manager's main-model heartbeat). Tasks/commands
        # that the router says belong to the Manager are forwarded there.
        if decision.route_to == "manager" and self.manager is not None:
            # P2 (comms redesign): forward as a STRUCTURED TASK_REQUEST on the
            # bus (with correlation) instead of an arbitrary string prompt into
            # the Manager. Never a direct model-to-model prompt loop.
            if bus_msg is not None:
                from agents.comms import EventBus
                EventBus.instance().publish(
                    bus_msg.derive(MessageType.TASK_REQUEST, source="chat",
                                   destination="manager", text=human_text))
                self.chat_reply.emit(
                    "System",
                    "Routed to Manager for task execution (structured request).", "")
            else:
                self.manager.send_human_message(human_text)
                self.chat_reply.emit(
                    "System",
                    "Routed to Manager for task execution (independent of chat).", "")
            self.status_changed.emit("Idle", "Watching thoughts…")
            return
        runtime_context = self._chat_router.build_runtime_context(
            getattr(self.worker, "research_folder", None),
            user_message=human_text,
        )

        system_prompt = (
            f"{self._CHAT_SYSTEM}\n\n"
            f"Frequent topics seen: {topics_str}.\n"
            f"Routing decision: {decision.route_to} | use_main_model={decision.use_main_model}.\n"
            + (f"Adapt your reply style: {style_instruction}" if style_instruction else "")
        )

        conversation_str = self._conversation.render(include_timestamps=False)

        # Decide whether the user's question is about the agent's own activity.
        # If NOT (e.g. "what is a gpu"), we must NOT hijack the reply with task
        # results — answer the question directly. If it IS, include results as
        # *background* the model may cite, never as a forced prefix.
        _AGENT_KW = ("agent", "bot", "manager", "ceo", "worker", "coder", "analyst",
                     "job", "gig", "proposal", "search", "task", "result", "pipeline",
                     "earning", "fiverr", "upwork", "reddit", "status", "running",
                     "doing", "plan", "current", "summary", "discover", "queue")
        ql = human_text.lower()
        agent_related = any(k in ql for k in _AGENT_KW)

        if agent_related:
            latest_results_block = (
                f"LATEST TASK RESULTS (optional background — only cite if it "
                f"directly answers the question):\n{latest_results_context}\n\n"
            )
            results_rule = (
                "If the user is asking about the agent's activity and the TASK "
                "RESULTS above are directly relevant, you may reference them — but "
                "lead with a direct answer to the question, not a fixed phrase. "
                "Otherwise answer from general knowledge."
            )
        else:
            latest_results_block = ""
            results_rule = (
                "This is a general question, NOT about the agent. Answer it directly "
                "from your own knowledge. Do NOT mention task results, gigs, or the "
                "agent's activity unless the user explicitly asks."
            )

        user_prompt = (
            f"{latest_results_block}"
            f"RECENT AGENT SUMMARIES:\n{summ_context}\n\n"
            f"RUNTIME CONTEXT:\n{runtime_context}\n\n"
            f"CONVERSATION SO FAR:\n{conversation_str}\n\n"
            f"Human: {human_text}\n\n"
            f"Instruction: {results_rule} Keep replies concise and natural.\n"
            "Summarizer:"
        )

        try:
            # v2.0.27: think=True so the model emits a reasoning block that we
            # surface as a collapsible "Thinking" section before the answer (via
            # the Show-thinking toggle). max_tokens raised from 350 so the answer
            # is no longer truncated. The llm() budget still caps output to the
            # model context, so this never overflows.
            reply = self.worker.llm(system=system_prompt,
                                    user=user_prompt,
                                    max_tokens=int(os.getenv("CHAT_MAX_TOKENS", 1200)),
                                    chat=True, think=True)
            if not reply or reply.startswith("ERROR:"):
                self.worker.log_signal.emit(
                    f"[Summarizer] LLM chat call failed or empty: {reply}"
                )
                reply = ("I'm having trouble reaching the LLM right now. "
                         "Please check your API connection.")
        except Exception as e:
            self.worker.log_signal.emit(f"[Summarizer] LLM exception: {e}")
            reply = f"Error generating reply: {e}"

        # v2.0.24: capture model reasoning (thinking) separately so it can
        # be shown as a collapsible block in the chat window.
        _thinking = getattr(self.worker, "last_response", {}).get("thinking", "") or ""
        # Persist reply (with thinking) and store in conversation memory
        self.summ_db.save_chat_turn("assistant", reply, self._session, thinking=_thinking)
        self._conversation.add("assistant", reply)

        self.chat_reply.emit("Summarizer", reply, _thinking)
        # P2 (comms redesign): also publish a structured MODEL_RESULT on the bus
        # so any subscriber (GUI, Manager) can correlate this answer to the
        # originating request. Destination follows the request's source when a
        # correlated bus_msg exists, otherwise broadcast to "gui".
        try:
            from agents.comms import EventBus
            bus = EventBus.instance()
            if bus_msg is not None:
                result = bus_msg.derive(MessageType.MODEL_RESULT, source="chat",
                                        destination=bus_msg.source, text=reply,
                                        thinking=_thinking)
            else:
                result = Message(MessageType.MODEL_RESULT, source="chat",
                                 destination="gui", text=reply,
                                 payload={"thinking": _thinking})
            bus.publish(result)
        except Exception:
            pass
        self.status_changed.emit("Idle", "Watching thoughts…")

    @staticmethod
    def _fmt_ts(ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")

    # ─────────────────────────────────────────────────────────────────────────
    #  Public helpers
    # ─────────────────────────────────────────────────────────────────────────

    def get_chat_history(self, limit: int = 40) -> List[Dict]:
        """Return recent chat history from the summarizer DB."""
        return self.summ_db.get_recent_chat(limit=limit)

    def get_top_topics(self, limit: int = 10) -> List[Dict]:
        """Return the most frequently discussed topics."""
        return self.summ_db.get_top_topics(limit=limit)

    def get_style_description(self) -> str:
        """Return a description of the detected speech style."""
        return self._speech_bank.describe()

    def get_summary_stats(self) -> Dict:
        return {
            "total_summaries": self.summ_db.get_summary_count(),
            "speech_samples":  self._speech_bank.sample_count,
            "formality":       self._speech_bank.formality_label(),
            "avg_sentence_len": round(self._speech_bank.avg_sentence_length(), 1),
            "strategy":        self.strategy,
            "top_topics":      self.get_top_topics(5),
        }

    def clear_chat_history(self):
        """Clear in-memory conversation (DB history is kept)."""
        self._conversation.clear()

    def stop(self):
        self.running = False
        try:
            self.summ_db.close()
        except Exception:
            pass