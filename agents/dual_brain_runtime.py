"""
agents/dual_brain_runtime.py — Canonical dual-brain runtime & configuration (v2.1).

Single source of truth for the MrBot1000 dual-brain GPU/model contract:

    Big Brain   → available primary GPU or configured provider
    Small Brain → secondary GPU, CPU/system RAM, or configured provider

Every component (adapters, GUI, legacy workers) reads its endpoint/model/device
from this runtime so the application never operates with contradictory role→GPU
assignments. This module is dependency-light (stdlib only) so it can be imported
anywhere without pulling in Qt, openai, or provider clients.

Design invariants
-----------------
- Model output is never authoritative for actions; the runtime only resolves
  WHERE to call a model, never WHAT the model may do.
- Role→GPU isolation is explicit and verifiable (``validate_isolation``).
- Health probes are bounded and NEVER raise; they degrade to "offline" instead.
- Provider selection follows enabled configuration; no local provider is
    assumed when all local routes are disabled.

Environment contract (all optional; defaults match the llama-server scripts)
-----------------------------------------------------------------------------
  BIG_BRAIN_PROVIDER   (default "llamacpp")  llamacpp | ollama | lmstudio
  BIG_BRAIN_URL        (default http://127.0.0.1:1234/v1)
  BIG_BRAIN_MODEL      (default "")          auto-detected from the server
    BIG_BRAIN_DEVICE     (default "0")         CUDA device index
  BIG_BRAIN_PORT       (default "1234")
  BIG_BRAIN_CONTEXT    (default "32768")     context length in tokens
  BIG_BRAIN_GPU_LAYERS (default "")          ""/auto → server decides
  BIG_BRAIN_ENABLED    (default "true")
    SMALL_* ... same keys, device "1", port "1235". When
        SMALL_BRAIN_GPU_LAYERS=0 and context/batch are not explicitly set, the
        CPU-safe defaults are 4096 context tokens and batch 256.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class BrainRole(str, Enum):
    BIG = "big"
    SMALL = "small"


# Provider kinds the runtime understands. Each role's enabled provider selects
# its endpoint and controls.
PROVIDER_LLAMACPP = "llamacpp"
PROVIDER_OLLAMA = "ollama"
PROVIDER_LMSTUDIO = "lmstudio"
PROVIDER_VLLM = "vllm"
PROVIDER_KOBOLDCPP = "koboldcpp"
SUPPORTED_PROVIDERS = {
    PROVIDER_LLAMACPP, PROVIDER_OLLAMA, PROVIDER_LMSTUDIO, PROVIDER_VLLM,
    PROVIDER_KOBOLDCPP,
}

# llama-server binary (v2.1 fix). The WindowsApps `llama.exe` (MSVC 0.3.0 build)
# has NO CUDA kernel for sm_75 (GTX 1660 Super), so `--device CUDA1` crashes on
# the Small Brain. The Clang 0.4.0 build in /d/llama.cpp ships kernels for both
# GPUs and is the verified-working binary. Override per-brain with
# BIG/SMALL_BRAIN_SERVER, or globally with LLAMA_SERVER_BIN.
DEFAULT_LLAMA_SERVER_BIN = r"D:\llama.cpp\llama-server.exe"


def _server_bin(prefix: str = "") -> str:
    if prefix:
        v = os.getenv(f"{prefix}_SERVER", "").strip()
        if v:
            return v
    v = os.getenv("LLAMA_SERVER_BIN", "").strip()
    if v:
        return v
    return DEFAULT_LLAMA_SERVER_BIN


# Default device/port pairing — MUST mirror the intended hardware assignment.
ROLE_DEFAULTS: Dict[BrainRole, Dict[str, Any]] = {
    BrainRole.BIG: {
        "provider": PROVIDER_LLAMACPP,
        "endpoint": "http://127.0.0.1:1234/v1",
        "device": 0,
        "port": 1234,
        "context": 32768,
        "gpu_layers": None,
        "display_name": "Edward Hurst",
        "gpu_label": "RTX 5060 Ti 16 GB",
        "kv_cache": "f16",
        "split_mode": "none",
        "threads": 8,
        "batch": 2048,
    },
    BrainRole.SMALL: {
        "provider": PROVIDER_LLAMACPP,
        "endpoint": "http://127.0.0.1:1235/v1",
        "device": 1,
        "port": 1235,
        "context": 32768,
        "gpu_layers": None,
        "display_name": "Jacob Stanley",
        "gpu_label": "CPU / System RAM",
        "kv_cache": "f16",
        "split_mode": "none",
        "threads": 4,
        "batch": 2048,
    },
}


@dataclass
class BrainConfig:
    """Resolved, validated configuration for one brain role."""

    role: BrainRole
    provider: str = PROVIDER_LLAMACPP
    endpoint: str = ""
    model: str = ""
    device: int = 0
    port: int = 1234
    context: int = 32768
    gpu_layers: Optional[int] = None
    display_name: str = ""
    gpu_label: str = ""
    enabled: bool = True
    kv_cache: str = "f16"
    split_mode: str = "none"
    threads: int = 8
    batch: int = 2048

    def __post_init__(self) -> None:
        defaults = ROLE_DEFAULTS[self.role]
        self._env_prefix = "BIG_BRAIN" if self.role is BrainRole.BIG else "SMALL_BRAIN"
        if not self.endpoint:
            self.endpoint = defaults["endpoint"]
        if not self.display_name:
            self.display_name = defaults["display_name"]
        if not self.gpu_label:
            self.gpu_label = defaults["gpu_label"]
        if self.provider not in SUPPORTED_PROVIDERS:
            self.provider = PROVIDER_LLAMACPP
        if not self.kv_cache:
            self.kv_cache = defaults.get("kv_cache", "f16")
        if not self.split_mode:
            self.split_mode = defaults.get("split_mode", "none")
        if not self.threads:
            self.threads = defaults.get("threads", 8)
        if not self.batch:
            self.batch = defaults.get("batch", 2048)

    # ── Convenience ──────────────────────────────────────────────────────────
    @property
    def models_path(self) -> str:
        """HTTP path for listing models for this provider kind."""
        if self.provider == PROVIDER_OLLAMA:
            base = self.endpoint.removesuffix("/v1")
            return f"{base}/api/tags"
        if self.provider == PROVIDER_KOBOLDCPP:
            return f"{self.endpoint.rstrip('/')}/api/v1/model"
        # OpenAI-compatible (llama-server, LM Studio) expose /v1/models.
        return f"{self.endpoint}/models"

    def build_llama_command(self, model_path: str = "") -> List[str]:
        """Build the llama-server launch command for this role.

        Honors context, gpu_layers, split_mode, threads, batch, and kv_cache
        so the GUI Start buttons and any launcher share one source of truth
        (v2.1 llama.cpp customization).

        v2.1 fix: uses the verified-working llama-server binary (Clang build,
        /d/llama.cpp) which ships sm_75 kernels for the 1660 Super, and passes
        the device by NAME (``CUDA0``/``CUDA1``) — this llama.cpp line rejects
        numeric indices (``--device 1`` -> "invalid device") and the WindowsApps
        MSVC build can't run the 1660 Super at all.
        
        v2.1.1 fix: detects models with Jinja templates that use
        ``raise_exception()`` (e.g., Ministral, Qwen3.5+, Gemma 4) and uses
        a compatible built-in chat template as fallback since llama.cpp
        doesn't provide that function.
        """
        model = model_path or self.model
        bin_path = _server_bin(self._env_prefix)
        cmd = [bin_path,
               "--host", "127.0.0.1",
               "--port", str(self.port),
               "--ctx-size", str(self.context),
               "--threads", str(self.threads),
               "--batch-size", str(self.batch),
               "--split-mode", self.split_mode or "none",
               "--cache-type-k", self.kv_cache if self.kv_cache != "auto" else "f16",
               "--cache-type-v", self.kv_cache if self.kv_cache != "auto" else "f16",
               "--model", model]
        if self.gpu_layers == 0:
            # CPU-only mode must not reference a missing CUDA device. llama.cpp
            # uses the absence of --device plus zero GPU layers for system RAM.
            cmd += ["--n-gpu-layers", "0"]
        else:
            cmd[cmd.index("--model"):cmd.index("--model")] = [
                "--device", f"CUDA{self.device}"]
        if self.gpu_layers is not None and self.gpu_layers != 0:
            cmd += ["--n-gpu-layers", str(self.gpu_layers)]
        
        # Check if model template uses raise_exception and provide fallback
        if model and self._model_needs_raise_exception(model):
            fallback_template = self._get_fallback_template(model)
            if fallback_template:
                cmd += ["--chat-template", fallback_template]
        
        return cmd
    
    def get_template_info(self, model_path: str) -> dict:
        """Get template info for logging purposes."""
        try:
            from agents.gguf_meta import read_metadata
            meta = read_metadata(model_path)
            template = meta.get("tokenizer.chat_template", "")
            needs_fallback = "raise_exception" in template
            return {
                "needs_fallback": needs_fallback,
                "fallback_template": self._get_fallback_template(model_path) if needs_fallback else None,
                "template_len": len(template)
            }
        except Exception as e:
            return {"needs_fallback": False, "fallback_template": None, "error": str(e)}
    
    @staticmethod
    def _model_needs_raise_exception(model_path: str) -> bool:
        """Check if a model's chat template uses raise_exception()."""
        try:
            from agents.gguf_meta import read_metadata
            meta = read_metadata(model_path)
            template = meta.get("tokenizer.chat_template", "")
            return "raise_exception" in template
        except Exception:
            return False
    
    @staticmethod
    def _get_fallback_template(model_path: str) -> str:
        """Get a compatible built-in chat template for models with broken templates."""
        try:
            from agents.gguf_meta import read_metadata
            meta = read_metadata(model_path)
            arch = meta.get("general.architecture", "")

            # Gemma 4 ships a new canonical template. The older built-in
            # ``gemma`` template silently corrupts its output (binary-looking
            # tokens and training boilerplate), so never substitute it here.
            if arch == "gemma4":
                return ""
            
            # Map architectures to compatible built-in templates
            arch_template_map = {
                "llama": "chatml",
                "qwen2": "chatml",
                "qwen3": "chatml",
                "gemma": "gemma",
                "gemma2": "gemma",
                "gemma3": "gemma",
                "gemma4": "gemma",
                "mistral": "chatml",
                "mixtral": "chatml",
                "phi3": "phi3",
                "phi4": "phi4",
                "falcon": "falcon3",
                "starcoder": "chatml",
                "bert": "chatml",
            }
            
            # Try architecture-specific template
            if arch in arch_template_map:
                return arch_template_map[arch]
            
            # Fallback: try to detect from filename
            fname = os.path.basename(model_path).lower()
            if "gemma-4" in fname or "gemma4" in fname:
                return ""
            if "qwen" in fname:
                return "chatml"
            if "gemma" in fname:
                return "gemma"
            if "mistral" in fname or "ministral" in fname:
                return "chatml"
            if "llama" in fname:
                return "chatml"
            if "phi" in fname:
                return "phi3"
            if "falcon" in fname:
                return "falcon3"
            
            # Default fallback
            return "chatml"
        except Exception:
            return "chatml"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "model": self.model,
            "device": self.device,
            "port": self.port,
            "context": self.context,
            "gpu_layers": self.gpu_layers,
            "display_name": self.display_name,
            "gpu_label": self.gpu_label,
            "enabled": self.enabled,
            "kv_cache": self.kv_cache,
            "split_mode": self.split_mode,
            "threads": self.threads,
            "batch": self.batch,
        }


def build_config(role: BrainRole, env: Optional[Dict[str, str]] = None) -> BrainConfig:
    """Build a ``BrainConfig`` for a role from environment (or an injected map).

    ``env`` is the environment mapping (defaults to ``os.environ``). This
    indirection keeps tests hermetic without mutating the real environment.
    """
    e = env if env is not None else os.environ
    prefix = "BIG_BRAIN" if role is BrainRole.BIG else "SMALL_BRAIN"
    defaults = ROLE_DEFAULTS[role]

    def _g(name: str, default: str = "") -> str:
        return (e.get(f"{prefix}_{name}", "") or "").strip() or default

    def _i(name: str, default: int) -> int:
        try:
            return int((e.get(f"{prefix}_{name}", "") or "").strip() or default)
        except (TypeError, ValueError):
            return default

    def _b(name: str, default: bool = True) -> bool:
        raw = (e.get(f"{prefix}_{name}", "") or "").strip().lower()
        if not raw:
            return default
        return raw in ("1", "true", "yes", "on")

    provider = _g("PROVIDER", defaults["provider"]).lower()
    display_name = _g("NAME", defaults["display_name"])
    if provider not in SUPPORTED_PROVIDERS:
        provider = PROVIDER_LLAMACPP
    endpoint_default = defaults["endpoint"]
    provider_endpoint = ""
    if provider == PROVIDER_OLLAMA:
        provider_endpoint = e.get("OLLAMA_BASE_URL", "").strip().rstrip("/")
        endpoint_default = provider_endpoint or "http://127.0.0.1:11434/v1"
        if provider_endpoint and not endpoint_default.endswith("/v1"):
            endpoint_default += "/v1"
    elif provider == PROVIDER_LMSTUDIO:
        provider_endpoint = e.get("LM_STUDIO_BASE_URL", "").strip().rstrip("/")
        endpoint_default = provider_endpoint or "http://127.0.0.1:1234/v1"
        if provider_endpoint and not endpoint_default.endswith("/v1"):
            endpoint_default += "/v1"
    elif provider == PROVIDER_VLLM:
        provider_endpoint = e.get("VLLM_BASE_URL", "").strip().rstrip("/")
        endpoint_default = provider_endpoint or "http://127.0.0.1:8000/v1"
        if provider_endpoint and not endpoint_default.endswith("/v1"):
            endpoint_default += "/v1"
    elif provider == PROVIDER_KOBOLDCPP:
        provider_endpoint = e.get("KOBOLDCPP_BASE_URL", "").strip().rstrip("/")
        endpoint_default = provider_endpoint or "http://127.0.0.1:5001/v1"
    gpu_raw = _g("GPU_LAYERS", "")
    gpu_layers: Optional[int] = None
    if gpu_raw:
        try:
            gpu_layers = int(gpu_raw)
        except (TypeError, ValueError):
            gpu_layers = None
    cpu_only = role is BrainRole.SMALL and gpu_layers == 0
    threads = _i("THREADS", defaults.get("threads", 8))
    batch = _i("BATCH", 256 if cpu_only else defaults.get("batch", 2048))
    context_default = 4096 if cpu_only else defaults["context"]

    return BrainConfig(
        role=role,
        provider=provider,
        endpoint=(endpoint_default if provider_endpoint else _g("URL", endpoint_default)),
        model=_g("MODEL", ""),
        device=_i("DEVICE", defaults["device"]),
        port=_i("PORT", defaults["port"]),
        context=_i("CONTEXT", context_default),
        gpu_layers=gpu_layers,
        display_name=display_name,
        enabled=_b("ENABLED", True),
        kv_cache=_g("KV_CACHE", defaults.get("kv_cache", "f16")),
        split_mode=_g("SPLIT_MODE", defaults.get("split_mode", "none")),
        threads=threads,
        batch=batch,
    )


class DualBrainRuntime:
    """Authoritative runtime/configuration owner for both brain roles.

    - Resolves role → endpoint/model/device.
    - Probes model servers with bounded timeouts (never raises).
    - Tracks the currently selected model per role (thread-safe).
    """

    HEALTH_TIMEOUT_S = float(os.getenv("DUAL_BRAIN_HEALTH_TIMEOUT", "3"))

    def __init__(self,
                 big: Optional[BrainConfig] = None,
                 small: Optional[BrainConfig] = None):
        self._lock = threading.RLock()
        self._configs = {
            BrainRole.BIG: big or build_config(BrainRole.BIG),
            BrainRole.SMALL: small or build_config(BrainRole.SMALL),
        }
        self._health_cache: Dict[BrainRole, Dict[str, Any]] = {}

    # ── Factories ────────────────────────────────────────────────────────────
    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "DualBrainRuntime":
        return cls(big=build_config(BrainRole.BIG, env),
                   small=build_config(BrainRole.SMALL, env))

    # ── Role access ──────────────────────────────────────────────────────────
    def config(self, role: BrainRole) -> BrainConfig:
        return self._configs[role]

    def endpoint(self, role: BrainRole) -> str:
        return self._configs[role].endpoint

    def model(self, role: BrainRole) -> str:
        return self._configs[role].model

    def device(self, role: BrainRole) -> int:
        return self._configs[role].device

    def set_model(self, role: BrainRole, model_name: str) -> None:
        with self._lock:
            self._configs[role].model = model_name
            self._health_cache.pop(role, None)

    # ── Isolation check ──────────────────────────────────────────────────────
    def validate_isolation(self) -> Dict[str, Any]:
        """Confirm the canonical role→GPU pairing holds.

        Big Brain must target device 0; Small Brain device 1. Also verifies the
        two roles do NOT share a port (a same-port pair would break isolation).
        Returns a report; never raises.
        """
        big = self._configs[BrainRole.BIG]
        small = self._configs[BrainRole.SMALL]
        big_device_ok = big.device == 0
        small_device_ok = small.gpu_layers == 0 or small.device == 1
        distinct_ports = big.port != small.port
        ok = big_device_ok and small_device_ok and distinct_ports
        return {
            "isolated": bool(ok),
            "big_device": big.device,
            "small_device": small.device,
            "big_device_ok": big_device_ok,
            "small_device_ok": small_device_ok,
            "small_cpu_only": small.gpu_layers == 0,
            "big_port": big.port,
            "small_port": small.port,
            "distinct_ports": distinct_ports,
        }

    # ── Model listing / health (bounded, never raises) ───────────────────────
    def _http_get(self, url: str, timeout: float) -> Optional[str]:
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    def list_models(self, role: BrainRole, refresh: bool = False) -> List[str]:
        """Return model ids available on a role's server. Bounded; [] if offline."""
        cfg = self._configs[role]
        if not cfg.enabled:
            return []
        with self._lock:
            cached = self._health_cache.get(role)
            if cached is not None and not refresh:
                return list(cached.get("models", []))
        payload = self._http_get(cfg.models_path, timeout=self.HEALTH_TIMEOUT_S)
        models: List[str] = []
        if payload:
            try:
                data = json.loads(payload)
                if cfg.provider == PROVIDER_OLLAMA:
                    models = [m.get("name", "") for m in data.get("models", [])]
                elif cfg.provider == PROVIDER_KOBOLDCPP:
                    model = data.get("result", "")
                    models = [model] if model else []
                else:
                    models = [m.get("id", "") for m in data.get("data", [])]
                models = [m for m in models if m]
            except (ValueError, TypeError, AttributeError):
                models = []
        with self._lock:
            self._health_cache[role] = {
                "reachable": bool(models) or payload is not None,
                "models": models,
                "checked_at": time.time(),
            }
        return models

    def health(self, role: BrainRole, refresh: bool = False) -> Dict[str, Any]:
        """Health snapshot for a role. Never raises; reports reachable/offline."""
        cfg = self._configs[role]
        t0 = time.time()
        models = self.list_models(role, refresh=refresh)
        latency_ms = int((time.time() - t0) * 1000)
        selected_model = cfg.model.strip()
        if not selected_model:
            model_status = "unselected"
            selected_model_available = None
        elif models:
            selected_model_available = selected_model in models
            model_status = "available" if selected_model_available else "stale"
        else:
            selected_model_available = None
            model_status = "server_unavailable"
        return {
            "role": role.value,
            "display_name": cfg.display_name,
            "provider": cfg.provider,
            "endpoint": cfg.endpoint,
            "device": cfg.device,
            "model": cfg.model,
            "selected_model_available": selected_model_available,
            "model_status": model_status,
            "enabled": cfg.enabled,
            "reachable": bool(models),
            "model_count": len(models),
            "models": models,
            "latency_ms": latency_ms,
        }

    # ── GUI snapshot ─────────────────────────────────────────────────────────
    def snapshot(self, refresh_health: bool = False) -> Dict[str, Any]:
        """Full runtime snapshot for dashboards (per-role + isolation)."""
        return {
            "isolation": self.validate_isolation(),
            "big": self.health(BrainRole.BIG, refresh=refresh_health),
            "small": self.health(BrainRole.SMALL, refresh=refresh_health),
        }


# ── Module-level canonical contract (for docs/config checks) ──────────────────
def default_contract() -> Dict[str, Any]:
    """Return the canonical default role→GPU/endpoint contract as a dict."""
    return {role.value: dict(ROLE_DEFAULTS[role]) for role in BrainRole}


__all__ = [
    "BrainRole",
    "BrainConfig",
    "DualBrainRuntime",
    "build_config",
    "default_contract",
    "SUPPORTED_PROVIDERS",
    "PROVIDER_LLAMACPP",
    "PROVIDER_OLLAMA",
    "PROVIDER_LMSTUDIO",
]
