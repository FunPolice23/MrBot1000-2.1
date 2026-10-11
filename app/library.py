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
from agents.knowledge.prompt_utils import ChainOfThought, PromptBuilder, ResponseParser


from agents.dialogue.conversation_memory import ConversationMemory, SpeechPatternBank


from agents.runtime.services import (
    AgentLogger, EmbeddingCache, FileWatcher, TaskQueue, WorkerRegistry,
)


from app.text_utils import (
    extract_code_blocks, fingerprint, safe_json_loads, strip_code_fences,
    truncate, ts_now, word_count,
)
