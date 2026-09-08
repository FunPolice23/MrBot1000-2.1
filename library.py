"""
agents/library.py — Shared utility library for all MrBot1000 agent workers.

Provides:
  - TokenBucket         : rate-limiting helper
  - retry_llm           : decorator for resilient LLM calls
  - ChainOfThought      : structured multi-step reasoning helper
  - PromptBuilder       : fluent prompt construction
  - ResponseParser      : parse structured fields from LLM output
  - ConversationMemory  : rolling conversation context with token budget
  - SpeechPatternBank   : learn and replay user/agent speech styles
  - TaskQueue           : priority task queue with dedup
  - AgentLogger         : structured event logger (wraps DB if present)
  - FileWatcher         : lightweight polling-based file change detector
  - EmbeddingCache      : simple keyword-based semantic similarity cache
  - WorkerRegistry      : central registry for dynamically loaded workers
"""

from __future__ import annotations

import os
import re
import time
import json
import math
import queue
import hashlib
import threading
import functools
import importlib
import importlib.util
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from collections import defaultdict, deque
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
#  TokenBucket  — rate limiting
# ─────────────────────────────────────────────────────────────────────────────
class TokenBucket:
    """
    Thread-safe token-bucket rate limiter.

    Usage::

        limiter = TokenBucket(rate=1.0, capacity=5)   # 1 call/sec, burst 5
        limiter.acquire()                              # blocks until a token is available
    """

    def __init__(self, rate: float = 1.0, capacity: float = 5.0):
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0):
        with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._capacity,
                                   self._tokens + elapsed * self._rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                sleep_for = (tokens - self._tokens) / self._rate
                time.sleep(min(sleep_for, 0.1))


# ─────────────────────────────────────────────────────────────────────────────
#  retry_llm  — decorator
# ─────────────────────────────────────────────────────────────────────────────
def retry_llm(max_attempts: int = 3, backoff: float = 1.5, exceptions=(Exception,)):
    """
    Decorator that retries an LLM-calling function with exponential back-off.

    Usage::

        @retry_llm(max_attempts=3)
        def call_model(prompt):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = 1.0
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay)
                    delay *= backoff
        return wrapper
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
#  ChainOfThought  — structured multi-step reasoning
# ─────────────────────────────────────────────────────────────────────────────
class ChainOfThought:
    """
    Accumulate reasoning steps and render them into a single prompt section.

    Usage::

        cot = ChainOfThought()
        cot.step("Identify the problem", "File X has no error handling.")
        cot.step("Propose solution", "Wrap the call in try/except.")
        prompt_section = cot.render()
    """

    def __init__(self):
        self._steps: List[Tuple[str, str]] = []

    def step(self, label: str, content: str) -> "ChainOfThought":
        self._steps.append((label, content))
        return self

    def render(self, numbered: bool = True) -> str:
        parts = []
        for i, (label, content) in enumerate(self._steps, 1):
            prefix = f"{i}. " if numbered else "• "
            parts.append(f"{prefix}**{label}**: {content}")
        return "\n".join(parts)

    def clear(self):
        self._steps.clear()

    def __len__(self):
        return len(self._steps)


# ─────────────────────────────────────────────────────────────────────────────
#  PromptBuilder  — fluent prompt construction
# ─────────────────────────────────────────────────────────────────────────────
class PromptBuilder:
    """
    Fluent helper for building structured prompts.

    Usage::

        prompt = (PromptBuilder()
                  .role("Python expert")
                  .context("File summary: ...")
                  .instruction("Find all bugs")
                  .constraint("Max 200 words")
                  .build())
    """

    def __init__(self):
        self._sections: List[Tuple[str, str]] = []

    def role(self, description: str) -> "PromptBuilder":
        self._sections.append(("ROLE", description))
        return self

    def context(self, text: str, label: str = "CONTEXT") -> "PromptBuilder":
        self._sections.append((label, text))
        return self

    def instruction(self, text: str) -> "PromptBuilder":
        self._sections.append(("INSTRUCTION", text))
        return self

    def constraint(self, text: str) -> "PromptBuilder":
        self._sections.append(("CONSTRAINT", text))
        return self

    def example(self, text: str) -> "PromptBuilder":
        self._sections.append(("EXAMPLE", text))
        return self

    def raw(self, text: str) -> "PromptBuilder":
        self._sections.append(("", text))
        return self

    def build(self, separator: str = "\n\n") -> str:
        parts = []
        for label, content in self._sections:
            if label:
                parts.append(f"[{label}]\n{content}")
            else:
                parts.append(content)
        return separator.join(parts)

    def build_system(self) -> str:
        """Return only ROLE + CONSTRAINT lines — suitable as system prompt."""
        parts = []
        for label, content in self._sections:
            if label in ("ROLE", "CONSTRAINT"):
                parts.append(content)
        return "  ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
#  ResponseParser  — extract structured fields from LLM text
# ─────────────────────────────────────────────────────────────────────────────
class ResponseParser:
    """
    Parse key:value fields and JSON blocks from LLM responses.

    Usage::

        parser = ResponseParser(raw_text)
        action = parser.field("ACTION")
        files  = parser.json_list()
    """

    def __init__(self, text: str):
        self.text = text or ""

    def field(self, key: str, default: str = "") -> str:
        """Extract 'KEY: value' from the text (case-insensitive)."""
        pattern = rf"(?i){re.escape(key)}\s*:\s*(.+)"
        m = re.search(pattern, self.text)
        return m.group(1).strip() if m else default

    def json_list(self) -> List[str]:
        """Extract the first JSON array found in the text."""
        m = re.search(r"\[.*?\]", self.text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        return []

    def json_object(self) -> Dict:
        """Extract the first JSON object found in the text."""
        m = re.search(r"\{.*?\}", self.text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        return {}

    def has_keyword(self, *keywords: str) -> bool:
        lower = self.text.lower()
        return any(kw.lower() in lower for kw in keywords)

    def classify(self, options: Dict[str, List[str]], default: str = "unknown") -> str:
        """
        Classify response by counting keyword matches per option.
        options = {"action": ["fix","improve"], "question": ["what","how"]}
        """
        lower = self.text.lower()
        scores = {opt: sum(1 for kw in kws if kw in lower)
                  for opt, kws in options.items()}
        best_score = max(scores.values())
        if best_score == 0:
            return default
        return max(scores, key=scores.get)


# ─────────────────────────────────────────────────────────────────────────────
#  ConversationMemory  — rolling context with character budget
# ─────────────────────────────────────────────────────────────────────────────
class ConversationMemory:
    """
    Rolling conversation store that respects a character budget.

    Usage::

        mem = ConversationMemory(max_chars=6000, max_turns=20)
        mem.add("user", "Hello!")
        mem.add("assistant", "Hi there!")
        context_str = mem.render()
    """

    def __init__(self, max_chars: int = 6000, max_turns: int = 20):
        self._max_chars = max_chars
        self._max_turns = max_turns
        self._turns: deque = deque()

    def add(self, role: str, content: str):
        self._turns.append({"role": role, "content": content,
                             "ts": time.time()})
        # Trim to max_turns
        while len(self._turns) > self._max_turns:
            self._turns.popleft()
        # Trim to max_chars
        while self._char_count() > self._max_chars and len(self._turns) > 1:
            self._turns.popleft()

    def _char_count(self) -> int:
        return sum(len(t["content"]) for t in self._turns)

    def render(self, include_timestamps: bool = False) -> str:
        parts = []
        for t in self._turns:
            ts = f"[{datetime.fromtimestamp(t['ts']).strftime('%H:%M')}] " \
                if include_timestamps else ""
            parts.append(f"{ts}{t['role'].upper()}: {t['content']}")
        return "\n".join(parts)

    def as_messages(self) -> List[Dict[str, str]]:
        return [{"role": t["role"], "content": t["content"]}
                for t in self._turns]

    def clear(self):
        self._turns.clear()

    def __len__(self):
        return len(self._turns)


# ─────────────────────────────────────────────────────────────────────────────
#  SpeechPatternBank  — learn and apply speech styles
# ─────────────────────────────────────────────────────────────────────────────
class SpeechPatternBank:
    """
    Observe user messages and extract style patterns for adapting responses.

    Tracked features:
      - Vocabulary richness (type-token ratio)
      - Average sentence length
      - Formality score (counts formal vs informal markers)
      - Preferred greeting/sign-off phrases
      - Common question starters
      - Emoji usage frequency
      - Punctuation style (exclamation, ellipsis, comma-heavy)

    Usage::

        bank = SpeechPatternBank()
        bank.observe("Hey! can u help me fix this bug?? lol")
        style = bank.describe()      # returns a style description string
        instruction = bank.as_prompt_instruction()
    """

    FORMAL_MARKERS = {
        "please", "kindly", "regarding", "therefore", "however",
        "furthermore", "consequently", "would you", "could you",
        "i would like", "i would appreciate"
    }
    INFORMAL_MARKERS = {
        "hey", "lol", "haha", "omg", "gonna", "wanna", "gotta",
        "ngl", "tbh", "btw", "idk", "imo", "u ", " ur ", "thx", "ty"
    }
    GREETING_PATTERNS = [
        r"^(hi|hey|hello|good\s+\w+|howdy|sup|yo)\b",
    ]
    QUESTION_STARTERS = [
        "what", "how", "why", "when", "where", "who",
        "can you", "could you", "would you", "is there"
    ]

    def __init__(self, max_samples: int = 200):
        self._max = max_samples
        self._samples: deque = deque(maxlen=max_samples)
        self._word_freq: defaultdict = defaultdict(int)
        self._greetings: List[str] = []
        self._question_starters: defaultdict = defaultdict(int)
        self._emoji_count = 0
        self._exclamation_count = 0
        self._ellipsis_count = 0
        self._formal_score = 0
        self._informal_score = 0
        self._total_words = 0
        self._total_sentences = 0
        self._lock = threading.Lock()

    def observe(self, text: str):
        """Ingest a user message and update style statistics."""
        with self._lock:
            self._samples.append(text)
            lower = text.lower()
            words = re.findall(r"\b\w+\b", lower)
            sentences = re.split(r"[.!?]+", text)
            sentences = [s.strip() for s in sentences if s.strip()]

            self._total_words += len(words)
            self._total_sentences += max(len(sentences), 1)

            for w in words:
                self._word_freq[w] += 1

            # Formality
            for marker in self.FORMAL_MARKERS:
                if marker in lower:
                    self._formal_score += 1
            for marker in self.INFORMAL_MARKERS:
                if marker in lower:
                    self._informal_score += 1

            # Greetings
            for pat in self.GREETING_PATTERNS:
                if re.match(pat, lower):
                    first_word = lower.split()[0] if lower.split() else ""
                    if first_word and first_word not in self._greetings:
                        self._greetings.append(first_word)

            # Question starters
            for qs in self.QUESTION_STARTERS:
                if lower.startswith(qs):
                    self._question_starters[qs] += 1

            # Punctuation style
            self._emoji_count += len(re.findall(
                r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF]", text))
            self._exclamation_count += text.count("!")
            self._ellipsis_count += text.count("...")

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def formality_label(self) -> str:
        total = self._formal_score + self._informal_score
        if total == 0:
            return "neutral"
        ratio = self._formal_score / total
        if ratio > 0.65:
            return "formal"
        elif ratio < 0.35:
            return "casual"
        return "neutral"

    def avg_sentence_length(self) -> float:
        if self._total_sentences == 0:
            return 0.0
        return self._total_words / self._total_sentences

    def describe(self) -> str:
        """Return a human-readable style description."""
        if self.sample_count < 3:
            return "Not enough samples to describe style."
        lines = [
            f"Formality: {self.formality_label()}",
            f"Avg sentence length: {self.avg_sentence_length():.1f} words",
            f"Emoji usage: {'frequent' if self._emoji_count > self.sample_count * 0.3 else 'rare'}",
            f"Exclamation marks: {'heavy' if self._exclamation_count > self.sample_count else 'moderate'}",
            f"Ellipsis usage: {'yes' if self._ellipsis_count > 2 else 'no'}",
        ]
        if self._greetings:
            lines.append(f"Preferred greetings: {', '.join(self._greetings[:3])}")
        if self._question_starters:
            top_qs = sorted(self._question_starters, key=self._question_starters.get, reverse=True)
            lines.append(f"Favourite question starters: {', '.join(top_qs[:3])}")
        return " | ".join(lines)

    def as_prompt_instruction(self) -> str:
        """Return a prompt fragment instructing the LLM to match the user's style."""
        if self.sample_count < 3:
            return ""
        formality = self.formality_label()
        avg_len = self.avg_sentence_length()

        parts = []
        if formality == "casual":
            parts.append("Write in a casual, friendly tone.")
        elif formality == "formal":
            parts.append("Write in a professional, formal tone.")
        else:
            parts.append("Write in a clear, balanced tone.")

        if avg_len < 8:
            parts.append("Keep sentences short and punchy.")
        elif avg_len > 20:
            parts.append("You may use longer, detailed sentences.")

        if self._emoji_count > self.sample_count * 0.3:
            parts.append("Use occasional relevant emoji.")

        if self._exclamation_count > self.sample_count:
            parts.append("Match the user's energetic punctuation style.")

        return "  ".join(parts)

    def top_words(self, n: int = 10) -> List[Tuple[str, int]]:
        """Return the n most frequent non-stopword words."""
        STOPWORDS = {"the", "a", "an", "is", "it", "i", "to", "of",
                     "and", "in", "for", "on", "with", "this", "that",
                     "you", "me", "my", "your", "we", "be", "do", "can"}
        filtered = {w: c for w, c in self._word_freq.items() if w not in STOPWORDS}
        return sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:n]

    def export(self) -> Dict:
        return {
            "sample_count": self.sample_count,
            "formality": self.formality_label(),
            "avg_sentence_length": self.avg_sentence_length(),
            "emoji_count": self._emoji_count,
            "exclamation_count": self._exclamation_count,
            "ellipsis_count": self._ellipsis_count,
            "greetings": self._greetings,
            "top_words": self.top_words(20),
        }

    def import_stats(self, data: Dict):
        """Restore previously exported stats."""
        self._emoji_count = data.get("emoji_count", 0)
        self._exclamation_count = data.get("exclamation_count", 0)
        self._ellipsis_count = data.get("ellipsis_count", 0)
        self._greetings = data.get("greetings", [])
        self._total_words = int(data.get("avg_sentence_length", 10) * 10)
        self._total_sentences = 10


# ─────────────────────────────────────────────────────────────────────────────
#  TaskQueue  — priority dedup queue
# ─────────────────────────────────────────────────────────────────────────────
class TaskQueue:
    """
    Priority task queue with deduplication (ignores exact duplicate tasks).

    Priority: 0 = highest, 10 = lowest.

    Usage::

        tq = TaskQueue()
        tq.put("fix bug in proposer.py", priority=0)
        tq.put("run heartbeat", priority=5)
        task, prio = tq.get()
    """

    def __init__(self):
        self._q: List[Tuple[int, float, str]] = []  # (priority, ts, task)
        self._seen: set = set()
        self._lock = threading.Lock()

    def put(self, task: str, priority: int = 5):
        with self._lock:
            key = hashlib.md5(task.encode()).hexdigest()
            if key in self._seen:
                return
            self._seen.add(key)
            import bisect
            bisect.insort(self._q, (priority, time.time(), task))

    def get(self, block: bool = True, timeout: float = 1.0) -> Tuple[str, int]:
        deadline = time.time() + timeout
        while True:
            with self._lock:
                if self._q:
                    prio, _, task = self._q.pop(0)
                    return task, prio
            if not block or time.time() > deadline:
                raise queue.Empty
            time.sleep(0.05)

    def __len__(self):
        with self._lock:
            return len(self._q)

    def clear(self):
        with self._lock:
            self._q.clear()
            self._seen.clear()


# ─────────────────────────────────────────────────────────────────────────────
#  AgentLogger  — structured event logger
# ─────────────────────────────────────────────────────────────────────────────
class AgentLogger:
    """
    Thin structured logger.  Writes to an AgentDB if provided, otherwise
    buffers in memory and prints to stdout.

    Usage::

        logger = AgentLogger(db=my_db, source="AnalystWorker")
        logger.info("Scan complete")
        logger.error("LLM timed out")
        logger.event("file_read", {"path": "agents/foo.py", "size": 1234})
    """

    def __init__(self, db=None, source: str = "Agent",
                 signal=None, max_buffer: int = 500):
        self.db = db
        self.source = source
        self.signal = signal          # optional Qt Signal(str)
        self._buffer: deque = deque(maxlen=max_buffer)

    def _emit(self, level: str, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}][{level}][{self.source}] {text}"
        self._buffer.append(entry)
        if self.signal:
            try:
                self.signal.emit(entry)
            except Exception:
                pass
        if self.db:
            try:
                self.db.log_thought(self.source, f"[{level}] {text}")
            except Exception:
                pass

    def info(self, text: str):   self._emit("INFO",  text)
    def warn(self, text: str):   self._emit("WARN",  text)
    def error(self, text: str):  self._emit("ERROR", text)
    def debug(self, text: str):  self._emit("DEBUG", text)

    def event(self, name: str, data: Dict = None):
        payload = json.dumps(data or {}, default=str)
        self._emit("EVENT", f"{name} {payload}")

    def recent(self, n: int = 20) -> List[str]:
        return list(self._buffer)[-n:]


# ─────────────────────────────────────────────────────────────────────────────
#  FileWatcher  — polling-based change detector
# ─────────────────────────────────────────────────────────────────────────────
class FileWatcher:
    """
    Watch a set of files/directories for changes via mtime polling.

    Usage::

        watcher = FileWatcher(interval=5.0)
        watcher.watch("/path/to/folder")
        changed = watcher.check()   # returns list of changed paths
    """

    def __init__(self, interval: float = 5.0):
        self._interval = interval
        self._mtimes: Dict[str, float] = {}
        self._paths: List[str] = []
        self._last_check = 0.0

    def watch(self, path: str):
        if path not in self._paths:
            self._paths.append(path)

    def check(self) -> List[str]:
        now = time.time()
        if now - self._last_check < self._interval:
            return []
        self._last_check = now
        changed = []
        for p_str in self._paths:
            p = Path(p_str)
            if p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file():
                        self._check_file(str(f), changed)
            elif p.is_file():
                self._check_file(p_str, changed)
        return changed

    def _check_file(self, path: str, changed: List[str]):
        try:
            mtime = Path(path).stat().st_mtime
            if path not in self._mtimes or self._mtimes[path] != mtime:
                if path in self._mtimes:
                    changed.append(path)
                self._mtimes[path] = mtime
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
#  EmbeddingCache  — keyword-based dedup / similarity cache
# ─────────────────────────────────────────────────────────────────────────────
class EmbeddingCache:
    """
    Simple keyword-based cache to avoid repeating very similar LLM calls.

    Uses Jaccard similarity on word sets — no external ML dependency.

    Usage::

        cache = EmbeddingCache(similarity_threshold=0.8, max_size=200)
        hit = cache.get("how do I fix proposer.py errors?")
        if hit is None:
            result = llm(...)
            cache.put("how do I fix proposer.py errors?", result)
    """

    def __init__(self, similarity_threshold: float = 0.8, max_size: int = 200):
        self._threshold = similarity_threshold
        self._max_size = max_size
        self._entries: List[Tuple[frozenset, str, str]] = []  # (words, key, value)
        self._lock = threading.Lock()

    @staticmethod
    def _tokenize(text: str) -> frozenset:
        return frozenset(re.findall(r"\b\w+\b", text.lower()))

    def get(self, query: str) -> Optional[str]:
        q_words = self._tokenize(query)
        with self._lock:
            for words, _key, value in self._entries:
                inter = len(q_words & words)
                union = len(q_words | words)
                if union > 0 and inter / union >= self._threshold:
                    return value
        return None

    def put(self, key: str, value: str):
        words = self._tokenize(key)
        with self._lock:
            self._entries.append((words, key, value))
            if len(self._entries) > self._max_size:
                self._entries.pop(0)

    def clear(self):
        with self._lock:
            self._entries.clear()

    def __len__(self):
        return len(self._entries)


# ─────────────────────────────────────────────────────────────────────────────
#  WorkerRegistry  — dynamic agent loader
# ─────────────────────────────────────────────────────────────────────────────
class WorkerRegistry:
    """
    Discover and load WorkerAgent subclasses from the agents/ folder.

    Any .py file in agents/ that defines a class inheriting from WorkerAgent
    (or duck-typing it — having an `llm` method) will be registered.

    Usage::

        registry = WorkerRegistry("/path/to/agents")
        registry.scan()
        names = registry.list_workers()          # ["AnalystWorker", ...]
        cls   = registry.get("AnalystWorker")
        inst  = cls(api_key, log_signal, db=db)
    """

    def __init__(self, agents_dir: str = None):
        self._dir = Path(agents_dir or Path(__file__).parent)
        self._workers: Dict[str, type] = {}

    def scan(self) -> List[str]:
        """Scan agents/ folder and load all valid worker classes."""
        found = []
        SKIP = {"__init__", "library", "base_worker"}
        for py in sorted(self._dir.glob("*.py")):
            stem = py.stem
            if stem in SKIP or stem.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"agents.{stem}", py)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for name in dir(mod):
                    obj = getattr(mod, name)
                    if (isinstance(obj, type)
                            and name not in ("WorkerAgent",)
                            and hasattr(obj, "llm")
                            and name not in self._workers):
                        self._workers[name] = obj
                        found.append(name)
            except Exception as e:
                pass   # silently skip broken modules
        return found

    def list_workers(self) -> List[str]:
        return list(self._workers.keys())

    def get(self, name: str) -> Optional[type]:
        return self._workers.get(name)

    def register(self, name: str, cls: type):
        """Manually register a worker class."""
        self._workers[name] = cls


# ─────────────────────────────────────────────────────────────────────────────
#  Convenience helpers
# ─────────────────────────────────────────────────────────────────────────────

def truncate(text: str, max_chars: int, ellipsis: str = "…") -> str:
    """Truncate text to max_chars, appending ellipsis if needed."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - len(ellipsis)] + ellipsis


def fingerprint(text: str) -> str:
    """Return a short MD5-based fingerprint for dedup."""
    return hashlib.md5(text.encode()).hexdigest()[:8]


def ts_now() -> str:
    """Return current timestamp string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def extract_code_blocks(text: str) -> List[str]:
    """Extract fenced code blocks from markdown text."""
    return re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences from a string."""
    return re.sub(r"```(?:\w+)?\n?", "", text).strip()


def safe_json_loads(text: str, default=None):
    """Parse JSON, stripping code fences first.  Returns default on failure."""
    try:
        return json.loads(strip_code_fences(text))
    except Exception:
        return default