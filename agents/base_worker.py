# MrBot1000/agents/base_worker.py — Core LLM integration & worker utilities
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

ROOT_FOLDER = str(Path(__file__).resolve().parent.parent)  # project root (2.0.19)
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


def _normalize_keep_alive(value) -> object:
    """Normalize a keep_alive value into what Ollama 0.6.x accepts.

    Ollama's server rejects bare-number durations ("300" -> status 400
    "missing unit in duration"). Valid forms: int (0, -1) or a unit-suffixed
    string ("300s", "5m", "1h"). We map:
      -1          -> int -1  (keep loaded forever)
      0 / "0"     -> int 0   (unload immediately)
      "300"       -> "300s"  (bare digits get an 's' unit)
      "5m"/"1h"   -> unchanged
      None/""      -> None    (Ollama applies its own default)
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value).strip()
    if s == "":
        return None
    if s in ("-1", "0"):
        return int(s)
    if s.lstrip("-").isdigit():
        return s + "s"
    return s


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
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def split_thinking(content: str):
    """Return (thinking, answer) from a raw model response.

    Handles the common single-<think>…</think> form. If no thinking block is
    present (non-thinking models), returns ("", content). Robust to missing
    close tags (treats the remainder as thinking).
    """
    if not content or _THINK_OPEN not in content:
        return ("", content or "")
    start = content.index(_THINK_OPEN) + len(_THINK_OPEN)
    close_idx = content.find(_THINK_CLOSE, start)
    if close_idx == -1:
        return (content[start:], "")
    thinking = content[start:close_idx].strip()
    answer = content[close_idx + len(_THINK_CLOSE):].strip()
    return (thinking, answer)


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


def read_think_level(chat: bool) -> str:
    key = "THINK_LEVEL" if chat else "MAIN_THINK_LEVEL"
    return os.getenv(key, os.getenv("THINK_LEVEL", "med")).strip().lower() or "med"


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
        from agents.base_worker import _active_worker
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


def model_context_tokens(model: str) -> int:
    """Return the real context length (tokens) of an Ollama model via `ollama show`.

    Parses the 'context length N' line. Cached per model name. Falls back to the
    env override (MAIN/CHAT_CONTEXT_TOKENS) or 128000 if Ollama is unreachable or
    the model unknown. NEVER raises — a budgeting guess is safer than a crash.
    """
    if not model:
        return max(1024, int(os.getenv("MAIN_CONTEXT_TOKENS", 128000)))
    if model in _ctx_cache:
        return _ctx_cache[model]
    # Fast path: if the Ollama client lib never imported, or the `ollama` CLI
    # isn't on PATH, don't even spawn a subprocess — go straight to fallback.
    # (v2.0.24j) This keeps context resolution instant when Ollama is disabled
    # or not installed (cloud-only users), and avoids any startup/call hang.
    if not OLLAMA_AVAILABLE:
        fb = max(1024, int(os.getenv("MAIN_CONTEXT_TOKENS", 128000)))
        _ctx_cache[model] = fb
        return fb
    try:
        import shutil
        if not shutil.which("ollama"):
            fb = max(1024, int(os.getenv("MAIN_CONTEXT_TOKENS", 128000)))
            _ctx_cache[model] = fb
            return fb
    except Exception:
        pass
    # Env override wins (user-knows-best / non-Ollama providers).
    env = os.getenv("MAIN_CONTEXT_TOKENS", "").strip()
    try:
        out = subprocess.run(
            ["ollama", "show", model],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        m = re.search(r"context length\s+(\d+)", out)
        if m:
            ctx = max(1024, int(m.group(1)))
            _ctx_cache[model] = ctx
            return ctx
    except Exception:
        pass
    fallback = max(1024, int(env)) if env else 128000
    _ctx_cache[model] = fallback
    return fallback


# ── LLM-runtime library (extracted to agents/llm_runtime.py, v2.0.34ah) ────────
# Re-exported here so existing `from agents.base_worker import num_gpu_for,
# model_arch_info, estimate_tokens, fit_prompt_to_ctx` callers keep working.
from agents.llm_runtime import (  # noqa: F401
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

# Python 3.9+ for is_relative_to
try:
    def is_safe_path(base: Path, candidate: Path) -> bool:
        """Ensure candidate is inside base and not a symlink pointing outside."""
        try:
            candidate = candidate.resolve()
            base = base.resolve()
            if not candidate.is_relative_to(base):
                return False
            if candidate.is_symlink():
                target = candidate.resolve()
                if not target.is_relative_to(base):
                    return False
            return True
        except Exception:
            return False
except AttributeError:
    # Fallback for Python < 3.9
    def is_safe_path(base: Path, candidate: Path) -> bool:
        try:
            candidate = candidate.resolve()
            base = base.resolve()
            if not str(candidate).startswith(str(base)):
                return False
            if candidate.is_symlink():
                target = candidate.resolve()
                if not str(target).startswith(str(base)):
                    return False
            return True
        except Exception:
            return False


def is_safe_filename(name: str) -> bool:
    """Reject clearly dangerous filenames."""
    lower = name.lower()
    for bad in FILENAME_BLOCKLIST:
        if bad in lower or lower.endswith(bad):
            return False
    return True


def is_safe_mime(file_path: Path) -> bool:
    """Heuristic mime-type check – only allow text-like files."""
    mime, _ = mimetypes.guess_type(str(file_path))
    if mime and mime in BLOCKED_MIME_TYPES:
        return False
    return True


def fingerprint(s: str) -> str:
    """Generate a short unique ID for a string."""
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()[:16]


def ts_now() -> str:
    """Return ISO timestamp."""
    from datetime import datetime
    return datetime.now().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
#  WorkerAgent
# ─────────────────────────────────────────────────────────────────────────────
class WorkerAgent:
    """Base class for MrBot1000 subagents with LLM integration and secure I/O."""
    
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
            from agents.shared_context import get_shared_context
            self._shared_context = get_shared_context()
        return self._shared_context

    def _chat_model_effective(self) -> str | None:
        chat_model = self._chat_ollama_model_override or os.getenv("OLLAMA_CHAT_MODEL", "").strip() or None
        if not chat_model or not OLLAMA_AVAILABLE:
            return chat_model
        try:
            available = self._ollama_model_names()
        except Exception:
            available = []
        if available and chat_model not in available:
            self.log_signal.emit(f"[LLM] chat model not found: {chat_model}; available={available[:5]}")
            return None
        return chat_model

    def _ollama_model_names(self) -> list[str]:
        if not _REQUESTS_AVAILABLE or not _requests:
            return []
        try:
            r = _requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
            r.raise_for_status()
            data = r.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    # ── LLM Methods ────────────────────────────────────────────────────────────

    # ── v2.0.25 provider registry ─────────────────────────────────────────────
    # v2.0.33: per-provider main/chat role control. Each registry adapter carries
    # a `_role_prefix` (env prefix) + `chat_model`. Role filtering happens in
    # `_build_providers`/`_provider_hint` via `_role_allows`.
    _ROLE_PREFIX = {
        "ollama": "OLLAMA", "anthropic": "ANTHROPIC", "openai": "OPENAI",
        "openrouter": "OPENROUTER", "gemini": "GEMINI", "groq": "GROQ",
        "deepseek": "DEEPSEEK", "mistral": "MISTRAL", "together": "TOGETHER",
        "vllm": "VLLM", "lm-studio": "LM_STUDIO", "koboldcpp": "KOBOLDCPP",
    }

    def _role_allows(self, ad: object, chat: bool) -> bool:
        """Whether this provider may serve the given role (main/chat).

        Legacy `DISABLE_<PREFIX>=true` disables both roles. Otherwise each role is
        independently gated by `<PREFIX>_MAIN_ENABLED` / `<PREFIX>_CHAT_ENABLED`
        (default enabled). If NEITHER is explicitly set, the provider is available
        for both (backward-compatible).
        """
        prefix = self._ROLE_PREFIX.get(ad.name, ad.name.upper())
        if os.getenv(f"DISABLE_{prefix}", "false").lower() == "true":
            return False
        main_on = os.getenv(f"{prefix}_MAIN_ENABLED", "").lower()
        chat_on = os.getenv(f"{prefix}_CHAT_ENABLED", "").lower()
        if main_on == "" and chat_on == "":
            # v2.1 dual-brain llama.cpp default: big-brain serves MAIN,
            # small-brain serves CHAT (hardware: 5060 Ti main / 1660S chat).
            if ad.name == "big-brain":
                return not chat
            if ad.name == "small-brain":
                return chat
            return True  # legacy default: enabled for both
        if chat:
            return chat_on != "false"
        return main_on != "false"

    def _build_provider_registry(self) -> list:
        """Return the ordered list of configured provider adapters.

        Built lazily (first call) from adapters/providers + the user's settings/
        env. Order is user-driven (settings.json if present, else a sensible
        default: Ollama first, then cloud). Ollama is default-enabled but never
        forced — it is simply absent if unavailable/disabled. No provider assumes
        another exists.
        """
        if getattr(self, "_provider_registry", None) is not None:
            return self._provider_registry
        try:
            from agents.providers import (
                OllamaAdapter, AnthropicAdapter, OpenAICompatibleAdapter,
            )
        except Exception:
            self._provider_registry = []
            return self._provider_registry
        regs = []
        # Ollama (default-enabled, order 0)
        regs.append(OllamaAdapter(
            name="ollama", order=0,
            chat_model=os.getenv("OLLAMA_CHAT_MODEL", "")))
        # Anthropic
        regs.append(AnthropicAdapter(
            name="anthropic", order=50,
            chat_model=os.getenv("ANTHROPIC_CHAT_MODEL", "")))
        # OpenAI
        regs.append(OpenAICompatibleAdapter(
            name="openai", api_key_env="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1", default_model="gpt-4o-mini",
            disabled_env="DISABLE_OPENAI", order=40,
            chat_model=os.getenv("OPENAI_CHAT_MODEL", "")))
        # OpenRouter (OpenAI-compatible)
        regs.append(OpenAICompatibleAdapter(
            name="openrouter", api_key_env="OPENROUTER_API_KEY",
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            default_model=os.getenv("OPENROUTER_MODEL", ""),
            disabled_env="DISABLE_OPENROUTER", order=60,
            chat_model=os.getenv("OPENROUTER_CHAT_MODEL", "")))
        # Gemini (OpenAI-compatible base_url)
        regs.append(OpenAICompatibleAdapter(
            name="gemini", api_key_env="GEMINI_API_KEY",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            default_model=os.getenv("GEMINI_MODEL", "gemini-1.5-pro"),
            disabled_env="DISABLE_GEMINI", order=55,
            chat_model=os.getenv("GEMINI_CHAT_MODEL", "")))
        # Groq / DeepSeek / Mistral / Together (OpenAI-compatible)
        regs.append(OpenAICompatibleAdapter(
            name="groq", api_key_env="GROQ_API_KEY",
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            default_model=os.getenv("GROQ_MODEL", ""), disabled_env="DISABLE_GROQ", order=70,
            chat_model=os.getenv("GROQ_CHAT_MODEL", "")))
        regs.append(OpenAICompatibleAdapter(
            name="deepseek", api_key_env="DEEPSEEK_API_KEY",
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            default_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            disabled_env="DISABLE_DEEPSEEK", order=70,
            chat_model=os.getenv("DEEPSEEK_CHAT_MODEL", "")))
        regs.append(OpenAICompatibleAdapter(
            name="mistral", api_key_env="MISTRAL_API_KEY",
            base_url=os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1"),
            default_model=os.getenv("MISTRAL_MODEL", ""), disabled_env="DISABLE_MISTRAL", order=70,
            chat_model=os.getenv("MISTRAL_CHAT_MODEL", "")))
        regs.append(OpenAICompatibleAdapter(
            name="together", api_key_env="TOGETHER_API_KEY",
            base_url=os.getenv("TOGETHER_BASE_URL", "https://api.together.xyz/v1"),
            default_model=os.getenv("TOGETHER_MODEL", ""), disabled_env="DISABLE_TOGETHER", order=70,
            chat_model=os.getenv("TOGETHER_CHAT_MODEL", "")))
        # NVIDIA NIM (OpenAI-compatible hosted API) — v2.0.34ap (H70)
        regs.append(OpenAICompatibleAdapter(
            name="nvidia", api_key_env="NVIDIA_API_KEY",
            base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            default_model=os.getenv("NVIDIA_MODEL", ""), disabled_env="DISABLE_NVIDIA", order=72,
            chat_model=os.getenv("NVIDIA_CHAT_MODEL", "")))
        # Local OpenAI-compatible servers (vLLM / LM Studio / KoboldCpp)
        if os.getenv("VLLM_BASE_URL"):
            regs.append(OpenAICompatibleAdapter(
                name="vllm", api_key_env="VLLM_API_KEY",
                base_url=os.getenv("VLLM_BASE_URL"), default_model=os.getenv("VLLM_MODEL", ""),
                disabled_env="DISABLE_VLLM", order=30,
                chat_model=os.getenv("VLLM_CHAT_MODEL", "")))
        if os.getenv("LM_STUDIO_BASE_URL"):
            regs.append(OpenAICompatibleAdapter(
                name="lm-studio", api_key_env="LM_STUDIO_API_KEY",
                base_url=os.getenv("LM_STUDIO_BASE_URL"), default_model=os.getenv("LM_STUDIO_MODEL", ""),
                disabled_env="DISABLE_LM_STUDIO", order=30,
                chat_model=os.getenv("LM_STUDIO_CHAT_MODEL", "")))
        if os.getenv("KOBOLDCPP_BASE_URL"):
            regs.append(OpenAICompatibleAdapter(
                name="koboldcpp", api_key_env="KOBOLDCPP_API_KEY",
                base_url=os.getenv("KOBOLDCPP_BASE_URL"), default_model=os.getenv("KOBOLDCPP_MODEL", ""),
                disabled_env="DISABLE_KOBOLDCPP", order=30,
                chat_model=os.getenv("KOBOLDCPP_CHAT_MODEL", "")))
        # v2.1: dual-brain llama.cpp (llama-server). big-brain -> main,
        # small-brain -> chat by default. Registered when enabled + endpoint and
        # a model is known (env override OR auto-detected from the live server),
        # so an offline server simply yields no adapter (graceful, never a crash).
        try:
            from agents.dual_brain_runtime import (BrainRole, DualBrainRuntime,
                                                   PROVIDER_LLAMACPP)
            from agents.providers import LlamaCppAdapter as _LCA
            _rt = DualBrainRuntime.from_env()
            _big = _rt.config(BrainRole.BIG)
            _small = _rt.config(BrainRole.SMALL)
            for _role, _cfg, _env_model, _is_chat in (
                (BrainRole.BIG, _big, "BIG_BRAIN_MODEL", False),
                (BrainRole.SMALL, _small, "SMALL_BRAIN_MODEL", True),
            ):
                if not (_cfg.provider == PROVIDER_LLAMACPP and _cfg.enabled and _cfg.endpoint):
                    continue
                _model = _cfg.model or os.getenv(_env_model, "").strip()
                if not _model:
                    # Auto-detect the loaded model from the live server. Bounded;
                    # returns [] if offline -> adapter stays unregistered.
                    try:
                        _det = _rt.list_models(_role)
                        if _det:
                            _model = _det[0]
                    except Exception:
                        _model = ""
                if not _model:
                    continue
                _name = "big-brain" if _role is BrainRole.BIG else "small-brain"
                regs.append(_LCA(name=_name, base_url=_cfg.endpoint,
                                 default_model=_model, chat_model=_model if _is_chat else "",
                                 disabled_env="DISABLE_BIG_BRAIN" if _role is BrainRole.BIG else "DISABLE_SMALL_BRAIN",
                                 order=-10))
        except Exception:
            pass
        self._provider_registry = regs
        return regs

    def invalidate_provider_registry(self):
        """v2.0.34ak: drop the cached adapter registry so the NEXT llm() call rebuilds
        it from current env. Needed for live model switching (local or cloud) without
        an app restart — adapters bake their model names from env at build time, so a
        changed <PROVIDER>_MODEL / _CHAT_MODEL in .env only takes effect once the
        cache is invalidated.
        """
        self._provider_registry = None

    def _build_providers(self, chat: bool) -> list:
        """Return (name, func, model_key, default_model) tuples for available adapters.

        User-driven order (by adapter.order; Ollama first by default). The chosen
        model per provider: Ollama resolves main/chat from env/override; cloud
        resolves from its default_model (main) / chat_model (chat). func delegates
        to adapter.complete. Providers whose role doesn't match `chat` are skipped
        (v2.0.33 per-provider main/chat control).

        D3 (v2.0.34x): when LLM_COST_AWARE is enabled (default on), billable
        cloud providers are re-ordered cheapest-first by `_price_for(model)
        .price_out_per_1m` so the first *successful* call is the cheapest adequate
        one. Ollama/local is always first (free). Unknown prices sort last (we
        never starve a configured provider — we only reorder, never drop).
        """
        regs = self._build_provider_registry()
        out = []
        for ad in sorted(regs, key=lambda a: a.order):
            if not ad.available():
                continue
            if not self._role_allows(ad, chat):
                continue
            if ad.name == "ollama":
                model = (self._chat_ollama_model_override if chat else None)                         or (self._chat_model_effective() if chat else None)                         or self._ollama_model_override                         or os.getenv("OLLAMA_MAIN_MODEL", "").strip()                         or os.getenv("OLLAMA_MODEL", "llama3.2")
                fn = lambda m, sys_, u, mt, chat=chat, a=ad, **kw: a.complete(m, sys_, u, mt, chat=chat, **kw)
                # Local/free always stays first; price key None = "free, sort first".
                out.append((0.0, "ollama", fn, "", model))
            elif ad.name in ("big-brain", "small-brain"):
                # v2.1 dual-brain llama.cpp is local/free: price 0.0, sorts first
                # (big-brain before Ollama for main; small-brain for chat).
                model = (ad.chat_model if chat else None) or ad.default_model or ""
                fn = lambda m, sys_, u, mt, chat=chat, a=ad, **kw: a.complete(m, sys_, u, mt, chat=chat, **kw)
                out.append((0.0, ad.name, fn, "", model))
            else:
                model = (ad.chat_model if chat else None) or ad.default_model or ""
                fn = lambda m, sys_, u, mt, chat=chat, a=ad, **kw: a.complete(m, sys_, u, mt, chat=chat, **kw)
                # D3: tag with the out-price (cheapest first). Ollama is 0.0 (free,
                # always first); unknown-price cloud providers sort LAST (inf), so a
                # misconfigured/unknown model never jumps ahead of a priced one.
                price = self._provider_out_price(model)
                sort_key = 0.0 if price == 0.0 else (price if price is not None else float("inf"))
                out.append((sort_key, ad.name, fn, "", model))
        # D3: stable sort by price key (ollama=0.0 first, then cheapest cloud).
        if self._cost_aware_enabled():
            out.sort(key=lambda t: t[0])
        else:
            # Preserve adapter.order grouping (re-extract order not available here,
            # so keep insertion order which already follows adapter.order for non-local).
            pass
        # Return the (name, func, model_key, default_model) shape the rest expects.
        return [(name, fn, mk, dm) for (_price, name, fn, mk, dm) in out]

    def _cost_aware_enabled(self) -> bool:
        return os.getenv("LLM_COST_AWARE", "1").strip().lower() not in ("0", "false", "no", "off")

    def _provider_out_price(self, model: str):
        """D3: out-token price (USD/1M) for `model`, or None if unknown/free."""
        if not model:
            return None
        try:
            from provider_models import _price_for
            inn, outp = _price_for(model)
            return outp
        except Exception:
            return None

    def _provider_hint(self, chat: bool) -> str | None:
        """Primary provider name for this mode (used to pick tokenizer/context hint)."""
        regs = self._build_provider_registry()
        for ad in sorted(regs, key=lambda a: a.order):
            if ad.available() and self._role_allows(ad, chat):
                if ad.name == "ollama":
                    return "ollama"
                return ad.name
        return None

    def llm(self, system: str, user: str, *, chat: bool = False, **kwargs) -> str:
        """Call LLM with retries, multiple providers, and max_tokens."""
        # v2.0.21 P3#6: read MAX_TOKENS live from env (or instance override) so the
        # Settings "Max Tokens" knob applies immediately after Save (no restart).
        # The module-level MAX_TOKENS is only the import-time default.
        if "max_tokens" in kwargs:
            max_tokens = kwargs["max_tokens"]
        elif getattr(self, "_max_tokens", None) is not None:
            max_tokens = self._max_tokens
        else:
            max_tokens = int(os.getenv("MAX_TOKENS", MAX_TOKENS))
        # v2.0.24h: thinking+answer budget is DERIVED from the model's real
        # context window (context_tokens), so it fits whether the model is a tiny
        # 8k local SLM or a 1M-token cloud frontier model. thinking = a level
        # fraction of the output budget; answer = the rest. Everything is capped
        # to the context so we never request more output tokens than the model
        # can hold. An explicit max_tokens kwarg (e.g. planner calls) still wins
        # (and is itself capped to context-100 below); for short direct outputs
        # callers pass think=False so the model spends its whole budget on the
        # answer, not a thinking block.
        think_on = os.getenv("THINKING_ENABLED", "true").strip().lower()
        think_on = think_on not in ("0", "false", "no", "off")
        # Caller may explicitly suppress thinking for a direct short output.
        suppress_think = kwargs.pop("think", None) is False
        ctx = context_tokens(chat)
        # v2.0.25: never overflow the window. Subtract the ACTUAL input size
        # (system+user) and defensively truncate if it cannot fit, so we never
        # hand any provider a prompt longer than its context. headroom is the
        # absolute max output for THIS call.
        provider_hint = self._provider_hint(chat)
        est_input = estimate_tokens(system, provider_hint) + estimate_tokens(user, provider_hint)
        if est_input + 100 > ctx:
            system, user = fit_prompt_to_ctx(system, user, ctx - 100, provider_hint)
            est_input = estimate_tokens(system, provider_hint) + estimate_tokens(user, provider_hint)
            self.log_signal.emit(f"[LLM] prompt truncated to fit ctx={ctx} (est_input={est_input})")
        headroom = max(64, ctx - est_input - 100)
        if think_on and not suppress_think and "max_tokens" not in kwargs:
            level = read_think_level(chat)
            output_budget = max(2048, int(ctx * _OUTPUT_FRACTION))
            think_reserve = think_budget(level, chat)
            answer_reserve = max(512, output_budget - think_reserve)
            max_tokens = min(think_reserve + answer_reserve, headroom)
            self.log_signal.emit(
                f"[Think] level={level} mode={'chat' if chat else 'main'} "
                f"ctx={ctx} num_predict={max_tokens} "
                f"(think~{think_reserve}+answer~{answer_reserve}, {int(_OUTPUT_FRACTION*100)}% of ctx)"
            )
        elif suppress_think:
            # Direct output: make sure the model doesn't waste budget on thinking.
            if "max_tokens" not in kwargs:
                max_tokens = min(int(os.getenv("MAX_TOKENS", MAX_TOKENS)), headroom)
        else:
            # Explicit max_tokens path: still cap it to the model context so we
            # never request more output than the window can hold.
            max_tokens = min(max_tokens, headroom)
            self.log_signal.emit(
                f"[Think] explicit max_tokens={max_tokens} (ctx={ctx})"
            )
        # v2.0.25: build the provider list from the user-configured, available
        # adapter registry (user-driven order; Ollama default-enabled). Each
        # entry is (name, func, model_key, default_model) matching the legacy shape.
        providers = self._build_providers(chat)
        self.log_signal.emit(f"[LLM] providers={[p[0] for p in providers]}")

        # A4: build a daily LLM cost guard (disabled when budget == 0).
        try:
            from agents.cost_guard import CostGuard
            _guard = CostGuard.from_env()
        except Exception:
            _guard = None

        for attempt in range(3):
            for name, func, model_key, default_model in providers:
                # D4 (v2.0.34y): skip a provider whose circuit is open (dead/flaky)
                # so we fail fast to the next provider instead of retrying 500s.
                try:
                    from agents.circuit_breaker import get_breaker
                    if get_breaker().is_open(name):
                        self.log_signal.emit(
                            f"[LLM] circuit OPEN for '{name}' — skipping (fail-fast)")
                        continue
                except Exception:
                    pass
                # A4: once the daily cap is exceeded, skip BILLABLE providers so the
                # loop falls through to the free/local one (prevents net-negative
                # earning). Local providers are never skipped. Guarded: a db error
                # must not block calls.
                if _guard is not None and _guard.should_skip(self.db, name):
                    self.log_signal.emit(
                        f"[Budget] daily cap reached — skipping paid provider '{name}', "
                        f"falling back to local")
                    continue
                try:
                    model = default_model
                    self.last_model = model
                    mode_label = "chat" if chat else "main"
                    self.log_signal.emit(f"[LLM] trying {name} mode={mode_label} model={model}")
                    t0 = time.time()
                    # v2.0.36: forward the thinking flag so reasoning-capable
                    # providers (NVIDIA Nemotron w/ enable_thinking) emit their
                    # thinking stream. Adapters that don't support it ignore it.
                    resp = func(model, system, user, max_tokens, chat=chat,
                                think=think_on)
                    dt_ms = int((time.time() - t0) * 1000)
                    # v2.0.21 P1#2: an empty response (chars=0) is a failure, not
                    # a success. The logs showed the chat model returning empty
                    # bodies, which forced the "heuristic fallback (planner
                    # failed)" path. Treat empty as retryable so a later attempt
                    # (or fallback provider) can produce real output.
                    if not resp or not str(resp).strip():
                        self.log_signal.emit(f"[LLM] {name} returned empty — retrying")
                        try:
                            if self.db is not None:
                                self.db.log_llm_call(
                                    model=model, provider=name,
                                    trigger=getattr(self, "last_trigger", "llm"),
                                    prompt_chars=len(system) + len(user),
                                    response_chars=0, latency_ms=dt_ms,
                                    error="empty response")
                        except Exception:
                            pass
                        # fall through to retry (next provider / attempt)
                        continue
                    # Persist the call so the DB Stats tab can show it (2.0.20e).
                    # Guarded: logging must never break the LLM result.
                    try:
                        if self.db is not None:
                            self.db.log_llm_call(
                                model=model, provider=name,
                                trigger=getattr(self, "last_trigger", "llm"),
                                prompt_chars=len(system) + len(user),
                                response_chars=len(resp or ""),
                                latency_ms=dt_ms, error=None)
                    except Exception as _log_err:
                        self.log_signal.emit(f"[LLM] stats log skipped: {_log_err}")
                    self.last_provider = name
                    # D4: a successful call closes the circuit for this provider.
                    try:
                        from agents.circuit_breaker import get_breaker
                        get_breaker().record_success(name)
                    except Exception:
                        pass
                    return resp
                except Exception as e:
                    self.log_signal.emit(f"[LLM] {name} failed ({e}), trying next...")
                    # D4: record the failure so a persistently-dead provider opens
                    # its circuit and is skipped instead of retried repeatedly.
                    try:
                        from agents.circuit_breaker import get_breaker
                        get_breaker().record_failure(name)
                    except Exception:
                        pass
                    # Log the failed attempt too (error populated).
                    try:
                        if self.db is not None:
                            self.db.log_llm_call(
                                model=default_model, provider=name,
                                trigger=getattr(self, "last_trigger", "llm"),
                                prompt_chars=len(system) + len(user),
                                response_chars=0, latency_ms=0, error=str(e)[:200])
                    except Exception:
                        pass
                    continue

            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            break

        self.last_provider = "error"
        return "ERROR: LLM unavailable"

    def _call_openai(self, model: str, system: str, user: str, max_tokens: int, chat: bool = False) -> str:
        if not OPENAI_AVAILABLE or not openai or not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OpenAI not available")
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
        ).choices[0].message.content

    def _call_anthropic(self, model: str, system: str, user: str, max_tokens: int, chat: bool = False) -> str:
        if not ANTHROPIC_AVAILABLE or not Anthropic or not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("Anthropic not available")
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        return client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": user}
            ],
            system=system,
        ).content[0].text

    def _call_ollama(self, model: str, system: str, user: str, max_tokens: int, chat: bool = False) -> str:
        if not OLLAMA_AVAILABLE or not ollama:
            raise RuntimeError("Ollama not available or pydantic_core issue")
        try:
            options = {"num_predict": max_tokens}
            # v2.0.34ab (Section E F5) + v2.0.36: resolve GPU layers per role.
            # `num_gpu_for` returns None for AUTO (env unset/"auto"/-1) so we OMIT
            # num_gpu and let Ollama's VRAM-aware scheduler offload what fits —
            # the correct, hardware-agnostic choice (6GB GTX 1660S up to big RTX).
            # A non-None value (explicit int; 0 = CPU-only) is passed through.
            ng = num_gpu_for(model, chat)
            if ng is not None:
                options["num_gpu"] = ng
            else:
                # AUTO: surface the discovered VRAM so the operator can see the
                # program is adapting to their real hardware.
                try:
                    from agents.llm_runtime import vram_gb
                    _vram = vram_gb()
                    self.log_signal.emit(
                        f"[LLM] GPU AUTO: detected ~{_vram}GB VRAM — letting Ollama "
                        f"manage offload (num_gpu omitted)")
                except Exception:
                    pass
            self.log_signal.emit(
                f"[LLM] ollama request model={model} mode={'chat' if chat else 'main'} "
                f"options={options}"
            )
            t0 = time.time()
            # v2.0.24e: hard timeout on the Ollama call. The ollama Python client's
            # chat() does NOT accept a per-call timeout kwarg in this version, so a
            # stalled Ollama (common on a 6GB GPU under concurrent chunked calls)
            # would block the calling thread FOREVER — the heartbeat appears to
            # "stop" with no error. We run the call in a worker thread and wait on
            # it with a timeout; on expiry we raise so the retry/fallback path (or
            # the heartbeat try/except) can recover. This is version-agnostic.
            ollama_timeout = float(os.getenv("OLLAMA_TIMEOUT", 180))
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TE
            _exec = ThreadPoolExecutor(max_workers=1)
            _fut = _exec.submit(
                lambda: ollama.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    options=options,
                    # TTL (not permanent pin): let Ollama evict under VRAM pressure.
                    # Fixed in 2.0.16 (Bug B) — keep_alive=-1 pinned the model in
                    # VRAM and caused RuntimeError on a 6GB GPU. Ollama 0.6.x requires
                    # a unit-suffixed duration ("300s", "5m"); a bare number ("300")
                    # is rejected (status 400 "missing unit in duration"). Normalize:
                    # -1 => forever (int), bare digits => append "s", else as-given.
                    keep_alive=_normalize_keep_alive(os.getenv("OLLAMA_KEEP_ALIVE", "300s")),
                )
            )
            try:
                _raw = _fut.result(timeout=ollama_timeout)
            except _TE:
                _fut.cancel()
                _exec.shutdown(wait=False)
                raise RuntimeError(
                    f"Ollama model '{model}' timed out after {ollama_timeout:.0f}s")
            finally:
                _exec.shutdown(wait=False)
            content = _raw['message']['content']
            dt = time.time() - t0
            # v2.0.24: Thinking models emit <think>…</think> blocks. Split the
            # reasoning from the final answer so the answer is never starved and
            # the reasoning can be shown separately in the chat UI / logs.
            thinking, answer = split_thinking(content)
            self.log_signal.emit(
                f"[LLM] ollama response model={model} latency={dt:.2f}s "
                f"chars={len(content)} think_chars={len(thinking)} answer_chars={len(answer)}"
            )
            # Keep the structured parts so callers can access reasoning without
            # re-parsing (e.g. summarizer stores thinking in its DB chat turn).
            self.last_response = {
                "thinking": thinking,
                "answer": answer,
                "raw": content,
                "provider": "ollama",
                "model": model,
                "mode": "chat" if chat else "main",
            }
            # v2.0.24g: RETURN THE ANSWER, not the raw text. Callers (CEO decision
            # parse, chat/summary display) expect the final answer. If the model
            # emitted only thinking (answer empty), fall back to the thinking so
            # callers still receive coherent text instead of an empty string —
            # but the budget fix above makes answer-empty rare. Emitting raw
            # thinking as "the answer" is exactly what produced the
            # "ACTION[JobSearch]: ? No wait per instruction…" garbage decisions.
            if answer:
                return answer
            if thinking:
                # Model thought but produced no answer (e.g. hit num_predict cap).
                # Return the thinking as a last resort so the caller isn't empty.
                return thinking
            return content
        except Exception as e:
            raise RuntimeError(f"Ollama model '{model}' failed: {e}")

    # ── File Operations ───────────────────────────────────────────────────────

    def safe_write_file(self, filename: str, content: str) -> bool:
        """Write a file safely inside ROOT_FOLDER only, with a pre-edit backup.

        2.0.19: backs up any existing target to ROOT_FOLDER/.mrbot_backups/
        before overwriting, and refuses protected/write-excluded directories.
        """
        if not is_safe_filename(filename):
            self.log_signal.emit(f"BLOCKED: filename '{filename}' is on blocklist")
            return False

        # Refuse to overwrite the app's own import-critical source files. The
        # Coder's full-file-rewrite path has repeatedly truncated these (e.g.
        # coder.py -> 0 bytes, action_pipeline.py -> 94 lines) via a bad LLM
        # rewrite; blocking here keeps the running app from being destroyed.
        # Matched by basename so absolute paths and nested copies are also blocked.
        _bn = Path(filename).name
        if _bn in PROTECTED_SOURCE_FILES:
            self.log_signal.emit(
                f"BLOCKED: protected app source '{_bn}' — refusing overwrite "
                f"(use an external editor for intentional dev changes)")
            return False

        root_resolved = Path(ROOT_FOLDER).resolve()
        # Accept absolute paths that live under root; otherwise treat as relative.
        candidate = Path(filename)
        full_path = (candidate if candidate.is_absolute()
                     else (root_resolved / filename)).resolve()

        # Write-excluded directories (VCS, venvs, caches, publish mirror, backups).
        rel_parts = full_path.relative_to(root_resolved).parts if str(full_path).startswith(str(root_resolved)) else ()
        if any(part in WRITE_EXCLUSION_DIRS for part in rel_parts):
            self.log_signal.emit(f"BLOCKED: write to protected dir '{'/'.join(rel_parts)}'")
            return False

        if not is_safe_path(root_resolved, full_path):
            self.log_signal.emit("BLOCKED: Write outside root folder or unsafe symlink")
            return False

        if len(content) > self.max_file_size:
            self.log_signal.emit(f"BLOCKED: File size exceeds {self.max_file_size // 1024 // 1024}MB")
            return False

        _, _, free = shutil.disk_usage(ROOT_FOLDER)
        if free < 100 * 1024 * 1024:
            self.log_signal.emit("BLOCKED: Free space < 100MB")
            return False

        # Backup-before-edit (2.0.19): keep a recoverable copy of the original.
        try:
            backup_root = root_resolved / BACKUP_DIRNAME
            backup_root.mkdir(parents=True, exist_ok=True)
            rel = full_path.relative_to(root_resolved)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_root / f"{rel}.{stamp}.bak"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            if full_path.exists():
                shutil.copy2(full_path, backup_path)
                self.log_signal.emit(f"Backed up -> {backup_path}")
        except Exception as e:
            self.log_signal.emit(f"Backup skipped: {e}")

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            self.log_signal.emit(f"Created safely: {filename}")
            return True
        except Exception as e:
            self.log_signal.emit(f"Write error: {e}")
            return False

    def restore_last_backup(self, filename: str) -> bool:
        """Restore the most recent .bak backup for `filename` (relative to root)."""
        root_resolved = Path(ROOT_FOLDER).resolve()
        rel = Path(filename)
        backup_root = root_resolved / BACKUP_DIRNAME
        prefix = str(rel).replace("\\", "/") + "."
        backups = []
        if backup_root.exists():
            for p in backup_root.iterdir():
                nm = p.name
                if nm.startswith(prefix) and nm.endswith(".bak"):
                    backups.append(p)
        if not backups:
            self.log_signal.emit(f"No backup found for '{filename}'")
            return False
        latest = max(backups, key=lambda p: p.stat().st_mtime)
        target = (root_resolved / rel).resolve()
        try:
            shutil.copy2(latest, target)
            self.log_signal.emit(f"Restored {target} from {latest}")
            return True
        except Exception as e:
            self.log_signal.emit(f"Restore failed: {e}")
            return False

    # ── Research Methods (used by Manager) ────────────────────────────────────

    def research_all(self) -> dict:
        """Scan ROOT_FOLDER (.py files) and user-selected research_folder."""
        root_parts = []
        try:
            # PERF: limit scan to first 30 .py files under root to avoid
            # blocking on large projects. Skip files > 50KB.
            count = 0
            for p in sorted(Path(ROOT_FOLDER).rglob("*.py")):
                if count >= 30:
                    break
                try:
                    size = p.stat().st_size
                    if size >= 50000:
                        continue
                    content = p.read_text(encoding="utf-8", errors="ignore")[:1200]
                    root_parts.append(f"[ROOT/{p.name}] ({size} bytes)\n{content}\n---")
                    count += 1
                except Exception:
                    pass
        except Exception as e:
            self.log_signal.emit(f"Error scanning root files: {e}")

        root_text = "\n".join(root_parts) if root_parts else "(no .py files found in root)"

        rf = self.research_folder
        research_text = ""
        research_file_count = 0
        research_files = []  # v2.0.24f: per-file records so the manager can bundle
                            # research by FILES (a numbered list per bundle) instead
                            # of by raw characters. Each: {"rel","content","chars"}.

        if not rf:
            research_text = "(research folder not set — select one via Management tab)"
        elif not Path(rf).exists():
            research_text = f"(path does not exist: {rf})"
        else:
            allowed_ext = {".py", ".txt", ".md", ".json", ".yaml", ".yml",
                           ".toml", ".cfg", ".ini", ".rst", ".csv"}
            research_parts = []
            skipped_large = []
            skipped_ext = []
            skipped_unsafe = []

            try:
                all_files = sorted(Path(rf).rglob("*"))
                total_chars = 0
                dropped_overflow = 0
                # PERF: cap research folder scan at 50 files to prevent
                # blocking on large directories.
                file_count = 0
                for p in all_files:
                    if file_count >= 50:
                        break
                    if not p.is_file():
                        continue

                    if not is_safe_filename(p.name):
                        skipped_unsafe.append(str(p.relative_to(rf)))
                        continue
                    if not is_safe_mime(p):
                        skipped_ext.append(str(p.relative_to(rf)))
                        continue
                    if p.suffix.lower() not in allowed_ext:
                        skipped_ext.append(str(p.relative_to(rf)))
                        continue

                    size = p.stat().st_size
                    if size >= RESEARCH_MAX_BYTES:
                        skipped_large.append(f"{p.relative_to(rf)} ({size // 1024}KB)")
                        continue

                    rel = p.relative_to(rf)
                    rel_path = rel.as_posix()

                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        display_content = content[:RESEARCH_MAX_CHARS]
                        piece = f"[{rel.as_posix()}] ({size} bytes)\n{display_content}\n---\n"
                        # v2.0.24d: enforce a TOTAL budget so a huge folder can't
                        # overflow the model context. Keep the first N files that
                        # fit; drop the rest (logged).
                        if RESEARCH_MAX_TOTAL_CHARS and total_chars + len(piece) > RESEARCH_MAX_TOTAL_CHARS:
                            dropped_overflow += 1
                            continue
                        research_parts.append(piece)
                        research_files.append({
                            "rel": rel.as_posix(),
                            "content": display_content,
                            "chars": len(display_content),
                        })
                        total_chars += len(piece)
                        research_file_count += 1
                        file_count += 1
                    except Exception as fe:
                        self.log_signal.emit(f"Skipped {p.name}: {fe}")

                if dropped_overflow:
                    self.log_signal.emit(
                        f"Research scan: dropped {dropped_overflow} file(s) over "
                        f"RESEARCH_MAX_TOTAL_CHARS={RESEARCH_MAX_TOTAL_CHARS} budget "
                        f"(increase it to include more)")

                if research_parts:
                    research_text = "\n".join(research_parts)
                    msg = f"Research scan: {research_file_count} file(s) from {rf}"
                    if skipped_unsafe:
                        msg += f" | skipped {len(skipped_unsafe)} unsafe file(s)"
                    if skipped_large:
                        msg += f" | skipped {len(skipped_large)} large file(s)"
                    if skipped_ext:
                        msg += f" | skipped {len(skipped_ext)} unsupported type(s)"
                    self.log_signal.emit(msg)
                else:
                    research_text = (
                        f"(no supported files found in {rf} — "
                        f"supported: {', '.join(sorted(allowed_ext))})"
                    )
                    self.log_signal.emit(f"Research scan: 0 files found in {rf}")
            except Exception as e:
                self.log_signal.emit(f"Error scanning research folder: {e}")

        return {
            "root": root_text,
            "research": research_text,
            "research_path": rf,
            "research_file_count": research_file_count,
            "research_files": research_files,
        }

    def file_index(self) -> str:
        """Return a compact index of all files in the research folder."""
        rf = self.research_folder
        if not rf or not Path(rf).exists():
            return f"(research folder not set or does not exist: {rf})"

        allowed_ext = {".py", ".txt", ".md", ".json", ".yaml", ".yml",
                       ".toml", ".cfg", ".ini", ".rst", ".csv"}
        lines = [f"Research folder: {rf}", "Files (relative path, size):"]
        count = 0
        try:
            for p in sorted(Path(rf).rglob("*")):
                if not p.is_file():
                    continue
                if not is_safe_filename(p.name):
                    continue
                if p.suffix.lower() not in allowed_ext:
                    continue
                try:
                    size = p.stat().st_size
                    rel_path = p.relative_to(rf).as_posix()
                    lines.append(f"{rel_path} ({size} bytes)")
                    count += 1
                except Exception:
                    pass
        except Exception as e:
            self.log_signal.emit(f"Error indexing research folder: {e}")

        return "\n".join(lines) + f"\n\nTotal: {count} files"

    def read_specific_files(self, filenames: list, base_path: str = None) -> str:
        """Read full content of specific files by relative path."""
        base = Path(base_path or self.research_folder or ROOT_FOLDER).resolve()
        parts = []
        folder_path = str(base)

        for name in filenames:
            if not is_safe_filename(name):
                self.log_signal.emit(f"BLOCKED read of unsafe name: {name}")
                continue

            p = (base / name).resolve()
            if not is_safe_path(base, p):
                self.log_signal.emit(f"BLOCKED read outside base: {name}")
                continue

            if not p.exists():
                self.log_signal.emit(f"File not found: {name}")
                parts.append(f"[{name}] ERROR: file not found\n---")
                continue

            if not is_safe_mime(p):
                self.log_signal.emit(f"BLOCKED read of unsafe mime type: {name}")
                continue

            try:
                size = p.stat().st_size
                content = p.read_text(encoding="utf-8", errors="ignore")
                display_content = content[:DEEP_READ_MAX_CHARS]
                parts.append(f"[{name}] ({size} bytes)\n{display_content}\n---")
            except Exception as e:
                parts.append(f"[{name}] ERROR: {e}\n---")

        return "\n".join(parts) if parts else "(no files read)"

    # ── State Management ─────────────────────────────────────────────────────

    def set_research_folder(self, path: str):
        """Set the research folder path."""
        self.research_folder = path

    def stop(self):
        """Signal the worker to stop running."""
        self._running = False

    def is_running(self) -> bool:
        """Check if the worker is still running."""
        return self._running

def project_file_tree(max_files: int = 200) -> str:
    """Return a grounded text tree of real project files for the planner.

    2.0.19: excludes write-excluded / non-required dirs so the Coder/CEO
    planner only references files that actually exist (no hallucinations).
    The deliverable workspace (work/) is excluded so the agent never tries
    to edit its own outputs. Module-level (imported by manager.py).
    """
    try:
        lines = ["Project file tree (rooted at project root):"]
        count = 0
        for pp in sorted(Path(ROOT_FOLDER).rglob("*")):
            try:
                parts = set(pp.parts)
            except Exception:
                continue
            if any(part in _CODEBASE_INDEX_SKIP_DIRS for part in parts):
                continue
            if pp.is_file() and pp.suffix.lower() in {
                ".py", ".md", ".txt", ".json", ".yaml", ".yml"
            }:
                try:
                    rel = pp.relative_to(Path(ROOT_FOLDER))
                except Exception:
                    continue
                lines.append(str(rel).replace("\\", "/"))
                count += 1
                if count >= max_files:
                    break
        return "\n".join(lines)
    except Exception as e:
        return f"[file tree error] {e}"
