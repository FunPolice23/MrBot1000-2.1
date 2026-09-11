"""Ollama provider adapter (v2.0.25).

Self-contained complete() that mirrors the former WorkerAgent._call_ollama
(incl. hard timeout thread + keep_alive TTL + chat-GPU handling). context_for
resolves live via `ollama show` (model_context_tokens) with a 128000 floor.
"""
import os
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TE

from .context_table import lookup_context


def _normalize_keep_alive(v: str) -> str | int:
    v = (v or "300s").strip()
    if v in ("-1", "-1s"):
        return -1
    if v.isdigit():
        return v + "s"
    return v


class OllamaAdapter:
    _executor = ThreadPoolExecutor(max_workers=2)

    @classmethod
    def shutdown_executor(cls):
        """Cancel queued calls during application shutdown."""
        cls._executor.shutdown(wait=False, cancel_futures=True)

    def __init__(self, name: str = "ollama", *, disabled_env: str = "DISABLE_OLLAMA",
                 order: int = 0, chat_model: str = ""):
        self.name = name
        self.disabled_env = disabled_env
        self.order = order
        self.chat_model = chat_model
        # Set by the worker at registration so we can honor the live model override.
        self._worker = None

    def available(self) -> bool:
        try:
            import ollama  # noqa: F401
        except Exception:
            return False
        if os.getenv(self.disabled_env or "DISABLE_OLLAMA", "false").lower() == "true":
            return False
        return True

    def complete(self, model: str, system: str, user: str, max_tokens: int,
                 chat: bool = False, **kwargs) -> str:
        import ollama
        if not ollama:
            raise RuntimeError("Ollama not available")
        options = {"num_predict": max_tokens}
        if chat:
            chat_gpu = os.getenv("OLLAMA_CHAT_GPU", "").strip()
            if chat_gpu.lstrip("-").isdigit():
                options["num_gpu"] = int(chat_gpu)
            else:
                options["num_gpu"] = 0
        ollama_timeout = float(os.getenv("OLLAMA_TIMEOUT", 180))
        _fut = self._executor.submit(
            lambda: ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                options=options,
                keep_alive=_normalize_keep_alive(os.getenv("OLLAMA_KEEP_ALIVE", "300s")),
            )
        )
        try:
            _raw = _fut.result(timeout=ollama_timeout)
        except _TE:
            raise RuntimeError(f"ollama call timed out after {ollama_timeout}s")
        return _raw["message"]["content"]

    def context_for(self, model: str) -> int:
        # Resolve live via `ollama show`; fallback to the static floor.
        try:
            out = subprocess.run(["ollama", "show", model], capture_output=True,
                                 text=True, timeout=8,
                                 creationflags=subprocess.CREATE_NO_WINDOW).stdout
            import re
            m = re.search(r"context length\s+(\d+)", out)
            if m:
                return max(1024, int(m.group(1)))
        except Exception:
            pass
        return lookup_context("ollama", model, default=128000)
