"""Provider probing and model lifecycle operations independent of Qt."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request


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
    def check_endpoint(url, timeout=10):
        try:
            req = urllib.request.Request(url)
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
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq llama.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return "llama.exe" in result.stdout
        except Exception:
            return False


__all__ = ["ProviderStatusChecker"]
