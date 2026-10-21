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
    # ARCH-ENG-188: WAS `max_workers=2`.
    #
    # `complete()` submits here and waits with `_fut.result(timeout=...)`. On
    # timeout it raised, but the future kept RUNNING — Python cannot interrupt a
    # thread already executing, so the worker stayed pinned until the underlying
    # `ollama.chat` call finally returned.
    #
    # With a pool of two, two slow calls wedged the adapter permanently: every
    # subsequent request queued behind them and never started, so the operator
    # saw the provider hang with no error rather than the timeout they were told
    # to expect. A timeout that leaves the system LESS able to report the next
    # timeout is worse than no timeout at all — it converts a clear failure into
    # a silent one.
    #
    # The headroom is now sized against the timeout: a stuck call costs one
    # worker for at most OLLAMA_TIMEOUT seconds, so a pool that is only slightly
    # wider than the number of concurrent callers keeps several healthy calls
    # progressing while the stuck ones age out. It is still a BOUNDED pool on
    # purpose — this is a local single-user app, and unbounded threads against a
    # wedged daemon is its own failure mode.
    _executor = ThreadPoolExecutor(
        max_workers=int(os.getenv("OLLAMA_MAX_WORKERS", "4") or 4)
    )

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
        if 'temperature' in kwargs:
            options["temperature"] = kwargs["temperature"]
        if 'top_p' in kwargs:
            options["top_p"] = kwargs["top_p"]
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
            # ARCH-ENG-188: TRY TO GIVE THE WORKER BACK.
            #
            # `Future.cancel()` only succeeds while a task is still QUEUED. If
            # `ollama.chat` had already started it returns False and the worker
            # stays pinned for the remainder of that call — which is why the
            # pool also needed headroom. Cancelling a not-yet-started task is
            # still worth doing: with a burst of calls, the queued majority is
            # released immediately instead of each one waiting out the full
            # timeout in turn.
            _fut.cancel()
            raise RuntimeError(f"ollama call timed out after {ollama_timeout}s")
        return _raw["message"]["content"]

    def context_for(self, model: str) -> int:
        # Resolve live via `ollama show`; fallback to the static floor.
        try:
            out = subprocess.run(
                ["ollama", "show", model], capture_output=True,
                text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                encoding="utf-8", errors="replace",
            ).stdout
            import re
            m = re.search(r"context length\s+(\d+)", out)
            if m:
                return max(1024, int(m.group(1)))
        except Exception:
            pass
        return lookup_context("ollama", model, default=128000)
