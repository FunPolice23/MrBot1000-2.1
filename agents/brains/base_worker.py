# MrBot1000/agents/brains/base_worker.py — Core LLM integration & worker utilities
"""
WorkerAgent provides base functionality for all MrBot1000 subagents:
- LLM calling with multiple provider fallback (OpenAI -> Anthropic -> Ollama)
- Secure file I/O operations
- Research and file scanning utilities
- Shared context integration via _get_shared_context()
"""

import os
import re
import time
import json
import subprocess
import sqlite3
import mimetypes
import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Any
import shutil

try:
    from groq import Groq as GroqClient
    GROQ_AVAILABLE = True
except (ImportError, ModuleNotFoundError, OSError):
    GROQ_AVAILABLE = False
    GroqClient = None

try:
    import ollama
    OLLAMA_AVAILABLE = True
except (ImportError, ModuleNotFoundError, OSError, Exception):
    OLLAMA_AVAILABLE = False
    ollama = None

try:
    import openai
    OPENAI_AVAILABLE = True
except (ImportError, ModuleNotFoundError, OSError, Exception):
    OPENAI_AVAILABLE = False
    openai = None

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except (ImportError, ModuleNotFoundError, OSError, Exception):
    ANTHROPIC_AVAILABLE = False
    Anthropic = None

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except (ImportError, ModuleNotFoundError, OSError, Exception):
    _REQUESTS_AVAILABLE = False
    _requests = None

ROOT_FOLDER = str(Path(__file__).resolve().parents[2])  # project root (2.0.19)
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB

# Directories that must never be written into by safe_write_file (2.0.19).
WRITE_EXCLUSION_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", "build", "dist", ".mypy_cache",
    # Non-required / external folders the agents must not overwrite:
    ".hermes", "test_results", "github_upload", ".mrbot_backups",
    # Deliverable workspaces are writable but excluded from the planner tree:
    "work",
}

# Backup directory name for safe_write_file() pre-edit copies (2.0.19 safety).
# MUST be defined — safe_write_file/restore_last_backup reference it. Previously
# missing → every backup raised NameError and was silently skipped (no safety).
BACKUP_DIRNAME = ".mrbot_backups"

# App source files that, if truncated/overwritten, prevent the app from launching
# or break the autonomous loop. The Coder worker's full-file-rewrite path
# (analyze_and_fix/refactor) has repeatedly DESTROYED these (e.g. truncated
# action_pipeline.py to 94 lines, or coder.py to 0 bytes) because it shows the LLM
# only the first 3000 chars but asks for the "complete file". safe_write_file
# refuses to overwrite any of these basenames so a bad LLM rewrite can never
# break the running app. For intentional dev edits, use an external editor.
PROTECTED_SOURCE_FILES = {
    "main.py", "manager.py", "ui.py", "theme_config.py", "library.py",
    "database.py", "action_pipeline.py", "earning_pipeline.py",
    "startup_validation.py", "test_earning_pipeline.py",
    "__init__.py", "base_worker.py", "coder.py", "analyst_worker.py",
    "job_search_worker.py", "fiverr_client.py", "upwork_client.py",
    "chat_router.py", "summarizer.py", "shared_context.py",
    "document_scanner.py", "task_workspace.py", "earning_discoverer.py",
    "opportunity_lifecycle.py", "wallet_manager.py", "content_generator.py",
    "workflow_planner.py", "social_earning_platform.py", "microtask_client.py",
    "airdrop_scanner.py", "airdrop_claimer.py", "defi_scanner.py",
}

# Directories excluded from project_file_tree() so the planner only sees real,
# stable source files (2.0.19).
_CODEBASE_INDEX_SKIP_DIRS = WRITE_EXCLUSION_DIRS | {
    ".github", "references", "skills", "scripts", "tests", "docs",
}

# Registry of worker classes by name (populated by manager registration).
WORKER_REGISTRY = {}


from agents.brains.worker_provider import normalize_keep_alive as _normalize_keep_alive


# Security blocklist – filenames that should never be read/written
FILENAME_BLOCKLIST = {
    "config.yaml", "config.yml", ".env", "credentials.json",
    "id_rsa", "id_dsa", ".gitconfig", ".bashrc", ".zshrc",
    "passwd", "shadow", "sudoers", "hosts", "secure",
}

# PROTECTED SOURCE MODULES — the app's own import-critical Python files.
# The Coder agent MUST NEVER truncate/overwrite these. Writing a broken or
# shortened version of any of these makes the application unlaunchable
# (ImportError at startup) or destroys its own source (e.g. coder.py -> 0 bytes,
# action_pipeline.py -> 94 lines). safe_write_file refuses such writes outright.
# This is the hard backstop: even a pathological LLM output cannot break launch.
# Stored as BASENAMES only — safe_write_file matches by Path(filename).name so
# "./coder.py", "agents/coder.py", and absolute paths are all caught.
PROTECTED_SOURCE_FILES = {
    "main.py", "manager.py", "action_pipeline.py", "database.py", "library.py",
    "ui.py", "theme_config.py", "startup_validation.py", "earning_pipeline.py",
    "earning_memory.py", "test_earning_pipeline.py",
    "coder.py", "base_worker.py", "job_search_worker.py", "analyst_worker.py",
    "__init__.py",
}

# Configuration from environment (with defaults)


# ── Thinking-mode support (v2.0.24) ───────────────────────────────────────────
# Thinking models (e.g. LFM2.5-*Thinking) emit a <think>…</think> reasoning block
# followed by the final answer. We split these apart so the answer is never
# starved by the reasoning tokens and the reasoning can be surfaced separately.
from agents.brains.worker_thinking import read_think_level, split_thinking


def think_budget(level: str, chat: bool) -> int:
    """Thinking (reasoning) token reserve for the current model's context.

    v2.0.24h: the reserve is a FRACTION of the model's real context window
    (see context_tokens), scaled by the THINK level. So a 128k local model and a
    1M cloud model both get a thinking allowance proportional to what they can
    hold — not a hardcoded 2500. Low=15%, Med=30%, High=50% of the output
    budget (which itself is _OUTPUT_FRACTION of the full context).
    """
    ctx = context_tokens(chat)
    output_budget = max(2048, int(ctx * _OUTPUT_FRACTION))
    frac = _LEVEL_THINK_FRAC.get((level or "med").strip().lower(), _LEVEL_THINK_FRAC["med"])
    return max(512, int(output_budget * frac))


def context_tokens(chat: bool) -> int:
    """The ACTUAL context-window size of the model being used, in tokens.

    v2.0.24i: this is the single source of truth for ALL output budgeting, and it
    now reads the REAL context length of whatever model is loaded — not a fixed
    guess. Models vary enormously (your local fleet: qwen3:0.6b=40960,
    llama3.2:1b=131072, gemma4:26b=262144, north-mini-code=500000). We query
    `ollama show <model>` for the true `context length` (cached per model), with
    env override + safe fallback so a missing model / offline Ollama never
    breaks budgeting. thinking+answer are sized as a FRACTION of this, so they
    always fit the model's real window — tiny SLM or 1M-token cloud model alike.
    """
    # v2.0.25: prefer the PRIMARY (first available, user-ordered) provider's
    # real context window. This makes cloud models (Claude 200k, Gemini 1M,
    # OpenRouter 200k, ...) budget correctly instead of the old 128000 fallback.
    try:
        from agents.brains.base_worker import _active_worker
        w = _active_worker
        if w is not None:
            for ad in sorted(w._build_provider_registry(), key=lambda a: a.order):
                if ad.available():
                    if ad.name == "ollama":
                        mdl = (w._chat_ollama_model_override if chat else None) \
                              or (w._chat_model_effective() if chat else None) \
                              or w._ollama_model_override \
                              or os.getenv("OLLAMA_MAIN_MODEL", "").strip() \
                              or os.getenv("OLLAMA_MODEL", "llama3.2")
                        return ad.context_for(mdl)
                    return ad.context_for(ad.default_model or "")
    except Exception:
        pass
    model = _active_models["chat" if chat else "main"]
    if model:
        return model_context_tokens(model)
    if chat:
        v = os.getenv("CHAT_CONTEXT_TOKENS", "").strip()
        if v:
            return max(1024, int(v))
    return max(1024, int(os.getenv("MAIN_CONTEXT_TOKENS", 128000)))


# Registry of the currently-loaded model names, set by WorkerAgent on init so
# context_tokens() can ask Ollama for the REAL context length of each.
_active_models = {"main": None, "chat": None}
# v2.0.25: back-reference to the live WorkerAgent, set in __init__, so
# context_tokens() can ask the primary provider for its real context.
_active_worker = None
# Per-model context-length cache (tokens). Refreshed on model (re)load.
_ctx_cache = {}


from agents.brains.worker_budget import model_context_tokens as _model_context_tokens


def model_context_tokens(model: str) -> int:
    return _model_context_tokens(
        model,
        ollama_available=OLLAMA_AVAILABLE,
        cache=_ctx_cache,
    )


# ── LLM-runtime library (extracted to agents/llm_runtime.py, v2.0.34ah) ────────
# Re-exported here so existing `from agents.brains.base_worker import num_gpu_for,
# model_arch_info, estimate_tokens, fit_prompt_to_ctx` callers keep working.
from agents.runtime.llm import (  # noqa: F401
    model_arch_info,
    num_gpu_for,
    estimate_tokens,
    _trim_to_tokens,
    fit_prompt_to_ctx,
)


# Fraction of the model context we allow thinking+answer to consume.
# reserved for the prompt/input. Keeps even a 250k-token answer off a 1M window
# while still scaling up on large models.
_OUTPUT_FRACTION = 0.25
# How much of the output budget goes to REASONING vs the final answer, by level.
_LEVEL_THINK_FRAC = {"low": 0.15, "med": 0.30, "high": 0.50}


RESEARCH_MAX_CHARS = int(os.getenv("RESEARCH_MAX_CHARS", 15000))  # v2.0.24: x3 (was 5000) so research context is never cut off
DEEP_READ_MAX_CHARS = int(os.getenv("DEEP_READ_MAX_CHARS", 24000))  # v2.0.24: x3 (was 8000)
# Byte-size cap for a single research file: files larger than this are skipped
# during folder scanning (display is still capped at RESEARCH_MAX_CHARS above).
RESEARCH_MAX_BYTES = int(os.getenv("RESEARCH_MAX_BYTES", 2 * 1024 * 1024))  # v2.0.24: defined
# TOTAL research-text SAFETY ceiling (chars) for a single scan. This is ONLY a
# guard against reading a pathological folder into memory (e.g. 50GB of logs);
# it is deliberately large. The REAL mechanism that lets the model ingest ALL
# research regardless of size is the chunked CEO reasoning in manager.py
# (_ceo_decide_chunked): research is split into per-call-sized chunks and fed
# across multiple gather passes. So do NOT set this low — a low value pre-truncates
# the scan and defeats chunking. Default ~1M tokens; raise freely.
RESEARCH_MAX_TOTAL_CHARS = int(os.getenv("RESEARCH_MAX_TOTAL_CHARS", 4000000))  # ~1M tokens safety ceiling
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 2048))  # v2.0.24: x2 (was 1024); thinking budget overrides per-level anyway
BLOCKED_MIME_TYPES = {"application/x-executable", "application/x-sharedlib",
                      "application/x-object", "application/x-dosexec"}

from agents.brains.worker_safety import (
    BLOCKED_MIME_TYPES, FILENAME_BLOCKLIST, fingerprint,
    is_safe_filename, is_safe_mime, is_safe_path, ts_now,
)
from agents.brains.worker_provider_mixin import WorkerProviderMixin
from agents.brains.worker_llm_mixin import WorkerLLMMixin
from agents.brains.worker_provider_calls import WorkerProviderCallsMixin
from agents.safety.filesystem import WorkerFilesystemMixin


class WorkerAgent(WorkerProviderMixin, WorkerLLMMixin, WorkerProviderCallsMixin, WorkerFilesystemMixin):
    """Base class for MrBot1000 subagents with LLM integration and secure I/O."""

    _ollama_executor = ThreadPoolExecutor(max_workers=2)

    @classmethod
    def shutdown_ollama_executor(cls):
        """Cancel queued legacy Ollama calls during application shutdown."""
        cls._ollama_executor.shutdown(wait=False, cancel_futures=True)
    
    def __init__(self, api_key: str, log_signal, db=None,
                 ollama_model: str | None = None,
                 chat_ollama_model: str | None = None,
                 primary_ollama_model: str | None = None):
        self.api_key = api_key
        self.log_signal = log_signal
        self.db = db
        self.groq = None
        self.research_folder = None
        self.max_file_size = MAX_FILE_SIZE
        self.last_provider = None
        self.last_model = None
        self.chat_model = None
        self._shared_context = None
        self._last_action = ""
        self._running = True
        # Model overrides: instance > env
        self.last_response = {"thinking": "", "answer": "", "raw": "", "provider": None, "model": None, "mode": None}
        self._ollama_model_override = primary_ollama_model or ollama_model
        self._chat_ollama_model_override = chat_ollama_model
        self._max_tokens = int(os.getenv("MAX_TOKENS", 1024))
        self._temperature = float(os.getenv("LLM_TEMPERATURE", 0.7))
        self._top_p = float(os.getenv("LLM_TOP_P", 0.9))
        # v2.0.24i: register the ACTUAL model names so context_tokens() can query
        # Ollama for each model's real context length. Main resolution mirrors
        # _llm_call; chat uses the effective chat model (raw name, no live
        # availability filter — model_context_tokens handles missing models).
        _active_models["main"] = (
            self._ollama_model_override
            or os.getenv("OLLAMA_MAIN_MODEL", "").strip()
            or os.getenv("OLLAMA_MODEL", "").strip()
            or None
        )
        _active_models["chat"] = (
            self._chat_ollama_model_override
            or os.getenv("OLLAMA_CHAT_MODEL", "").strip()
            or None
        )
        # NOTE (v2.0.24j): do NOT prime the context cache here. Context is
        # resolved lazily on the first llm() call (timeout-guarded, cached).
        # v2.0.25: register this worker so context_tokens() can ask the primary
        # provider for its real context window (cloud models budget correctly).
        global _active_worker
        _active_worker = self
        self._provider_registry = None

    def _get_shared_context(self):
        """Lazy-load shared context for cross-model communication"""
        if self._shared_context is None:
            from agents.brains.shared_context import get_shared_context
            self._shared_context = get_shared_context()
        return self._shared_context

from agents.brains.worker_workspace import project_file_tree
