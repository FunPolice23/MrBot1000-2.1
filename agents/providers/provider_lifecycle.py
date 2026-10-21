"""Provider probing and model lifecycle operations independent of Qt."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request


def _is_local(provider: str) -> bool:
    """True when ``provider`` runs on this machine and needs no auth.

    Local import (not top-level) so this module stays Qt-free and import-safe
    when ``agents.runtime`` is not yet initialised; any failure degrades to
    ``False`` (treated as cloud -> a probe is simply sent without a header).
    """
    try:
        from agents.runtime.provider_keys import is_local_provider as _f
        return bool(_f(provider))
    except Exception:
        return False


# Public alias used by the class methods below.
is_local_provider_name = _is_local


def _is_cloud(provider: str) -> bool:
    """True when ``provider`` is a known REMOTE (paid) OpenAI-compatible vendor.

    Local import keeps this module Qt-free and import-safe; any failure degrades
    to ``False`` so an unknown provider keeps its existing explicit
    "no model-load API" failure rather than silently becoming a no-op success.
    """
    try:
        from agents.runtime.dual_brain import CLOUD_PROVIDER_DEFAULT_ENDPOINTS
        return (provider or "").strip().lower() in CLOUD_PROVIDER_DEFAULT_ENDPOINTS
    except Exception:
        return False


class ProviderStatusChecker:
    """Probe local and controllable provider endpoints."""

    _cache = {}
    _cache_lock = threading.Lock()
    _cache_ttl = float(os.getenv("DUAL_BRAIN_PROBE_CACHE_S", "2"))

    @staticmethod
    def check_llama_server(port=1234, timeout=10, refresh=False):
        now = time.monotonic()
        if not refresh:
            with ProviderStatusChecker._cache_lock:
                cached = ProviderStatusChecker._cache.get(port)
            if cached and now - cached[0] < ProviderStatusChecker._cache_ttl:
                return cached[1]
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            result = True, ProviderStatusChecker.extract_model_ids(data)
        except Exception:
            result = False, []
        with ProviderStatusChecker._cache_lock:
            ProviderStatusChecker._cache[port] = (time.monotonic(), result)
        return result

    @staticmethod
    def _auth_headers(provider, api_key=None):
        """Bearer header for a cloud provider probe; ``{}`` for local ones.

        A cloud ``/v1/models`` probe without ``Authorization`` gets a 401, so the
        Providers & GPU row would show "Stopped" forever even with a valid key.
        The key is resolved through the single authority (``provider_keys``), so
        this never invents a second credential source, and is never logged.
        """
        if not provider or is_local_provider_name(provider):
            return {}
        try:
            from agents.runtime.provider_keys import resolve_provider_api_key
            key = (api_key or resolve_provider_api_key(provider, "")).strip()
        except Exception:
            key = (api_key or "").strip()
        if not key:
            return {}
        return {"Authorization": f"Bearer {key}"}

    @staticmethod
    def check_endpoint(url, timeout=10, provider="", api_key=None):
        try:
            req = urllib.request.Request(
                url, headers=ProviderStatusChecker._auth_headers(provider, api_key))
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            return True, ProviderStatusChecker.extract_model_ids(data)
        except Exception:
            return False, []

    @staticmethod
    def _provider_root(endpoint):
        return str(endpoint or "").rstrip("/").removesuffix("/v1")

    @classmethod
    def check_loaded_provider(cls, provider, endpoint, timeout=5):
        root = cls._provider_root(endpoint)
        try:
            if provider == "lmstudio":
                url = f"{root}/api/v1/models"
                with urllib.request.urlopen(
                    urllib.request.Request(url), timeout=timeout
                ) as resp:
                    data = json.loads(resp.read().decode())
                return True, [
                    model.get("key", "")
                    for model in data.get("models", [])
                    if model.get("key") and model.get("loaded_instances")
                ]
            if provider == "ollama":
                url = f"{root}/api/ps"
                with urllib.request.urlopen(
                    urllib.request.Request(url), timeout=timeout
                ) as resp:
                    data = json.loads(resp.read().decode())
                return True, [
                    model.get("name") or model.get("model", "")
                    for model in data.get("models", [])
                ]
        except Exception:
            return False, []
        return False, []

    @classmethod
    def load_provider_model(cls, provider, endpoint, model, timeout=30):
        root = cls._provider_root(endpoint)
        if provider == "lmstudio":
            url, body = f"{root}/api/v1/models/load", {"model": model}
        elif provider == "ollama":
            url, body = f"{root}/api/generate", {
                "model": model,
                "stream": False,
            }
        elif _is_cloud(provider):
            # A cloud model is served by the vendor; there is nothing to load
            # locally. Reporting failure here made "Start" on a cloud brain log
            # "❌ Big Brain openai does not expose a model-load API" forever, so
            # the Providers & GPU row could never reach Running. A successful
            # no-op is the truthful answer: the model IS available, remotely.
            return True, f"{provider} serves {model} remotely — nothing to load"
        else:
            return False, f"{provider} does not expose a model-load API"
        return cls._post_json(url, body, timeout)

    @classmethod
    def unload_provider_model(cls, provider, endpoint, model="", timeout=30):
        root = cls._provider_root(endpoint)
        if provider == "lmstudio":
            loaded_ok, loaded = cls.check_loaded_provider(
                provider, endpoint, timeout=5)
            if not loaded_ok:
                return False, "LM Studio loaded-model list is unavailable"
            for instance_id in loaded:
                if not model or instance_id == model:
                    ok, message = cls._post_json(
                        f"{root}/api/v1/models/unload",
                        {"instance_id": instance_id},
                        timeout,
                    )
                    if not ok:
                        return False, message
            return True, "unloaded"
        if provider == "ollama":
            if not model:
                return False, "Ollama requires a model name to unload"
            return cls._post_json(
                f"{root}/api/generate",
                {"model": model, "keep_alive": 0},
                timeout,
            )
        if _is_cloud(provider):
            # Mirror of the load path: a cloud model has no local instance to
            # release, so unload is a truthful no-op rather than a failure.
            return True, f"{provider} model is served remotely — nothing to unload"
        return False, f"{provider} does not expose a model-unload API"

    @staticmethod
    def _post_json(url, body, timeout):
        try:
            payload = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return True, resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def clear_cache(port=None):
        with ProviderStatusChecker._cache_lock:
            if port is None:
                ProviderStatusChecker._cache.clear()
            else:
                ProviderStatusChecker._cache.pop(port, None)

    @staticmethod
    def extract_model_ids(data):
        if isinstance(data.get("result"), str) and data["result"]:
            return [data["result"]]
        raw_models = data.get("data") or data.get("models") or []
        result = []
        for item in raw_models:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                result.append(
                    item.get("id") or item.get("name") or item.get("model") or "unknown"
                )
        return result

    @staticmethod
    def model_ids_match(selected, reported):
        def variants(value):
            text = str(value or "").strip().replace("\\", "/").casefold()
            if not text:
                return set()
            base = text.rsplit("/", 1)[-1]
            return {text, base, base.removesuffix(".gguf")}

        return bool(variants(selected) & variants(reported))

    @staticmethod
    def check_llama_process(port=None):
        """Is a llama.cpp server listening on `port`?

        ARCH-ENG-187 — THIS ALWAYS RETURNED False, AND IT HAS NO CALLERS.

        Two independent reasons it could never be right, and the second one is
        why it survived so long:

        1. It filtered `IMAGENAME eq llama.exe`, but this application spawns
           `llama-server.exe` (`BrainLaunchWorker`). The filter matched nothing,
           so on a machine running four llama-servers this returned False. A
           detector that always says "no" is worse than no detector at all,
           because a reader cannot tell a genuine negative from a broken check.

        2. It accepted a `port` argument and then ignored it entirely — it asked
           "is any llama process running anywhere?" while appearing to answer
           "is the server on THIS port up?". Those are different questions, and
           only the second one is useful.

        It also used `capture_output=True`, the ARCH-ENG-116-broken subprocess
        form, and it had ZERO call sites, so it read as a working safety check
        that nothing happened to use yet.

        Both facts a caller needs — WHO is listening, and WHOSE it is — now come
        from the one shared implementation in `device_registry`. The image-name
        filter is `is_llama_server_image`, the SAME predicate the kill path uses
        (ARCH-ENG-171), so a probe can never disagree with a killer about what
        "ours" means.

        Still no callers. That is recorded rather than hidden: it is a public
        helper on a public class so it stays correct for external callers, but
        nothing in this repository should base a decision on it.
        """
        if port is None:
            # No port given: we cannot answer the question that was asked, and
            # guessing a default would silently report on the wrong server.
            return False
        from agents.runtime.device_registry import llama_server_pids_on
        return bool(llama_server_pids_on(port))


__all__ = ["ProviderStatusChecker"]
