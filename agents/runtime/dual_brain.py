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
    SMALL_* ... same keys, device "1", port "1235".
    SMALL_BRAIN_CPU_MODEL (optional preferred model path/ID for CPU fallback)
    SMALL_BRAIN_DECISION_SUPPORT (default "false")
        CPU fallback enables decision-support mode at runtime. When
        SMALL_BRAIN_GPU_LAYERS=0 and context/batch are not explicitly set, the
        CPU-safe defaults are 4096 context tokens and batch 256.
"""

from __future__ import annotations

import json
import os
import re
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
CPU_SMALL_MODEL_MAX_B = 2.0


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
        "context": 64768,
        "gpu_layers": None,
        "display_name": "Edward Hurst",
        "gpu_label": "GPU 0 (detected hardware)",
        "kv_cache": "f16",
        "split_mode": "none",
        "threads": 8,
        "batch": 2048,
        "temperature": 0.5,
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
        "temperature": 0.5,
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
    decision_support_only: bool = False

    # ── llama.cpp performance flags (v2.1.9) ────────────────────────────────
    # Empty/None means "not set" -> the flag is omitted so llama.cpp keeps its
    # own default. That keeps behaviour identical to before for anyone who
    # never touches the new controls.
    flash_attn: str = ""          # on|off|auto  (--flash-attn)
    cache_reuse: Optional[int] = None   # --cache-reuse N
    ctx_checkpoints: Optional[int] = None  # --ctx-checkpoints N
    kv_offload: Optional[bool] = None      # False -> --no-kv-offload
    show_perf: bool = True                 # True -> --perf (print token/prompt timings)
    n_cpu_moe: Optional[int] = None        # --n-cpu-moe N (MoE experts to CPU)
    cpu_moe: Optional[bool] = None         # True -> --cpu-moe
    n_cpu_ffn: Optional[int] = None        # --n-cpu-ffn N (dense FFN to CPU)

    # ── llama.cpp sampling flags (v2.1.9) ───────────────────────────────────
    top_k: Optional[int] = None            # --top-k N
    top_p: Optional[float] = None          # --top-p N
    min_p: Optional[float] = None          # --min-p N
    repeat_penalty: Optional[float] = None  # --repeat-penalty N
    presence_penalty: Optional[float] = None  # --presence-penalty N
    frequency_penalty: Optional[float] = None  # --frequency-penalty N
    dry_multiplier: Optional[float] = None  # --dry-multiplier N (0 = off)
    dry_base: Optional[float] = None        # --dry-base N
    dry_allowed_length: Optional[int] = None  # --dry-allowed-length N
    dry_penalty_last_n: Optional[int] = None  # --dry-penalty-last-n N
    xtc_probability: Optional[float] = None  # --xtc-probability N (0 = off)
    xtc_threshold: Optional[float] = None    # --xtc-threshold N

    # ── llama.cpp reasoning flags (v2.1.9) ──────────────────────────────────
    reasoning_budget: Optional[int] = None   # --reasoning-budget N (-1 unrestricted)
    reasoning_format: str = ""               # none|auto|deepseek|... (--reasoning-format)

    # ── multimodal projector (v2.1.9) ───────────────────────────────────────
    # Path to an mmproj-*.gguf companion file. Empty -> omit --mmproj entirely so
    # llama.cpp uses its built-in projector if the GGUF carries one (many vision
    # models embed it) or stays text-only otherwise.
    mmproj: str = ""
    mmproj_offload: Optional[bool] = None   # False -> --no-mmproj-offload

    # ── N-brain identity (device registry) ──────────────────────────────────
    # slot: ordinal position in the runtime's ordered slot list (0-based). Only
    # the first two slots map to the BIG/SMALL roles. device_id: stable device
    # identifier from the registry (GPU UUID / "gpu<idx>" / "cpu"); empty means
    # "not tied to a detected device" (the classic 2-role env config).
    slot: int = -1
    device_id: str = ""

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

        # ── Performance flags (v2.1.9). Each is omitted when unset so llama.cpp
        # keeps its own default; the command is byte-identical to before for an
        # untouched config. ───────────────────────────────────────────────────
        if self.flash_attn:
            cmd += ["--flash-attn", str(self.flash_attn)]
        if self.cache_reuse is not None and self.cache_reuse > 0:
            # Reuse a KV prefix across turns via KV shifting. Big win for the
            # Dialogue tab, where every turn re-sends a long shared prefix.
            cmd += ["--cache-reuse", str(self.cache_reuse)]
        if self.ctx_checkpoints is not None and self.ctx_checkpoints >= 0:
            cmd += ["--ctx-checkpoints", str(self.ctx_checkpoints)]
        if self.kv_offload is False:
            # Keep the KV cache in system RAM instead of VRAM.
            cmd += ["--no-kv-offload"]
        # v2.1.37 (ARCH-ENG-044): print per-request prompt-eval + token-generation
        # timings to the console so the operator watching a visible console sees
        # live generation (tokens, tok/s) instead of only the load banner. This
        # is the "--perf" timing flag; it only affects stderr output, never the
        # served responses. Default on; set show_perf=False to silence it.
        if self.show_perf:
            cmd += ["--perf"]
        # MoE placement: these are the levers that make a big MoE model fit a
        # small card by parking expert weights in system RAM.
        if self.cpu_moe:
            cmd += ["--cpu-moe"]
        elif self.n_cpu_moe is not None and self.n_cpu_moe > 0:
            cmd += ["--n-cpu-moe", str(self.n_cpu_moe)]
        if self.n_cpu_ffn is not None and self.n_cpu_ffn > 0:
            cmd += ["--n-cpu-ffn", str(self.n_cpu_ffn)]

        # ── Sampling flags (v2.1.9). DRY and XTC are the anti-repetition
        # samplers: they suppress the loops the Dialogue tab used to fall into. ─
        if self.top_k is not None and self.top_k >= 0:
            cmd += ["--top-k", str(self.top_k)]
        if self.top_p is not None and 0.0 < self.top_p <= 1.0:
            cmd += ["--top-p", str(self.top_p)]
        if self.min_p is not None and self.min_p > 0.0:
            cmd += ["--min-p", str(self.min_p)]
        if self.repeat_penalty is not None and self.repeat_penalty != 1.0:
            cmd += ["--repeat-penalty", str(self.repeat_penalty)]
        if self.presence_penalty is not None and self.presence_penalty != 0.0:
            cmd += ["--presence-penalty", str(self.presence_penalty)]
        if self.frequency_penalty is not None and self.frequency_penalty != 0.0:
            cmd += ["--frequency-penalty", str(self.frequency_penalty)]
        if self.dry_multiplier is not None and self.dry_multiplier > 0.0:
            cmd += ["--dry-multiplier", str(self.dry_multiplier)]
            if self.dry_base is not None:
                cmd += ["--dry-base", str(self.dry_base)]
            if self.dry_allowed_length is not None:
                cmd += ["--dry-allowed-length", str(self.dry_allowed_length)]
            if self.dry_penalty_last_n is not None:
                cmd += ["--dry-penalty-last-n", str(self.dry_penalty_last_n)]
        if self.xtc_probability is not None and self.xtc_probability > 0.0:
            cmd += ["--xtc-probability", str(self.xtc_probability)]
            if self.xtc_threshold is not None:
                cmd += ["--xtc-threshold", str(self.xtc_threshold)]

        # ── Reasoning flags (v2.1.9) ─────────────────────────────────────────
        if self.reasoning_budget is not None:
            cmd += ["--reasoning-budget", str(self.reasoning_budget)]
        if self.reasoning_format:
            cmd += ["--reasoning-format", str(self.reasoning_format)]

        # ── Multimodal projector (v2.1.9) ────────────────────────────────────
        if self.mmproj:
            cmd += ["--mmproj", self.mmproj]
            if self.mmproj_offload is False:
                cmd += ["--no-mmproj-offload"]

        # Check if model template uses raise_exception and provide fallback
        if model and self._model_needs_raise_exception(model):
            fallback_template = self._get_fallback_template(model)
            if fallback_template:
                cmd += ["--chat-template", fallback_template]
        
        return cmd
    
    def get_template_info(self, model_path: str) -> dict:
        """Get template info for logging purposes."""
        try:
            from agents.providers.gguf_meta import read_metadata
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
        """Check if a model's chat template uses raise_exception().

        Reads ONLY the chat-template key (scalar metadata) — a full
        read_metadata() would materialise the ~128k-token vocab on the GUI
        thread and freeze the window for seconds on every Start click.
        """
        try:
            from agents.providers.gguf_meta import read_scalar_metadata
            meta = read_scalar_metadata(model_path, ("tokenizer.chat_template",))
            template = meta.get("tokenizer.chat_template", "")
            return isinstance(template, str) and "raise_exception" in template
        except Exception:
            return False
    
    @staticmethod
    def _get_fallback_template(model_path: str) -> str:
        """Get a compatible built-in chat template for models with broken templates."""
        try:
            from agents.providers.gguf_meta import read_scalar_metadata
            meta = read_scalar_metadata(model_path, ("general.architecture",))
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
            "decision_support_only": self.decision_support_only,
        }


def estimate_model_size_b(model_name: str) -> Optional[float]:
    """Estimate total parameter size from a model filename or identifier."""
    name = os.path.basename(str(model_name or "")).lower()
    matches = [float(value) for value in re.findall(
        r"(?<![0-9.])(\d+(?:\.\d+)?)b\b", name)]
    return max(matches) if matches else None


def is_cpu_decision_model(model_name: str, max_params_b: float = CPU_SMALL_MODEL_MAX_B) -> bool:
    """Return whether a model is small enough for CPU decision support."""
    size = estimate_model_size_b(model_name)
    return size is not None and size <= max_params_b


def choose_cpu_decision_model(configured: str, candidates: List[str]) -> str:
    """Choose a configured or smallest discovered model for CPU fallback."""
    if configured and is_cpu_decision_model(configured):
        return configured
    eligible = [candidate for candidate in candidates if is_cpu_decision_model(candidate)]
    eligible.sort(key=lambda value: (estimate_model_size_b(value) or 999.0, str(value).lower()))
    return eligible[0] if eligible else ""


def build_slot_config(placement: Dict[str, Any], slot: int,
                      role: "BrainRole") -> BrainConfig:
    """Build a BrainConfig for one device placement (N-brain slot 2+).

    ``placement`` is a dict from ``device_registry.brain_placements()``:
    {role, device_id, kind, index, name, memory_gb, is_cpu, port, label}.
    ``role`` is the BrainRole this placement maps to (BIG or SMALL). Slots 0/1
    are NOT built here — they are the role configs themselves; this is only for
    extra enabled devices beyond the first two.
    """
    is_cpu = bool(placement.get("is_cpu"))
    device_index = int(placement.get("index", -1))
    port = int(placement.get("port", 1234 + slot))
    defaults = ROLE_DEFAULTS[role]
    # A GPU-hosted brain offloads by default (gpu_layers None = auto); a CPU
    # pool brain is system-RAM only (gpu_layers 0). Big brains get the big
    # context/threads defaults, small brains the small ones.
    gpu_layers = 0 if is_cpu else None
    context = defaults["context"] if role is BrainRole.BIG else 4096 if is_cpu else defaults["context"]
    return BrainConfig(
        role=role,
        provider=PROVIDER_LLAMACPP,
        endpoint=f"http://127.0.0.1:{port}/v1",
        model="",
        device=(device_index if not is_cpu else 0),
        port=port,
        context=context,
        gpu_layers=gpu_layers,
        display_name=defaults["display_name"],
        gpu_label=placement.get("label") or placement.get("name", ""),
        enabled=True,
        kv_cache=defaults.get("kv_cache", "f16"),
        split_mode=defaults.get("split_mode", "none"),
        threads=defaults.get("threads", 8),
        batch=defaults.get("batch", 2048),
        decision_support_only=is_cpu,
        slot=slot,
        device_id=str(placement.get("device_id", "")),
    )


def _apply_saved_settings(cfg: "BrainConfig", saved: Dict[str, object]) -> None:
    """Apply a persisted per-device settings dict onto a slot's BrainConfig.

    Only known keys are applied; unknown/malformed values are ignored so a
    hand-edited settings.json can't corrupt a slot. Never raises.
    """
    def _int(key, attr):
        try:
            v = saved.get(key)
            if v is not None:
                setattr(cfg, attr, int(v))
        except (TypeError, ValueError):
            pass

    _int("context", "context")
    _int("threads", "threads")
    _int("batch", "batch")
    # gpu_layers: None means auto (omit the flag); 0 means CPU-only.
    try:
        gl = saved.get("gpu_layers")
        if gl is not None:
            cfg.gpu_layers = int(gl)
    except (TypeError, ValueError):
        pass
    for key, attr in (("kv_cache", "kv_cache"), ("split_mode", "split_mode")):
        v = saved.get(key)
        if isinstance(v, str) and v:
            setattr(cfg, attr, v)


def apply_hardware_fallback(config: BrainConfig, gpu_indexes: set[int]) -> BrainConfig:
    """Normalize a role config against detected GPUs without inventing hardware.

    Two directions:
    - **Fallback to CPU**: a llamacpp Small Brain whose target device is NOT
      detected drops to ``gpu_layers=0`` (system RAM) rather than launching
      against a missing CUDA device.
    - **Recover the GPU**: a Small Brain that was previously forced to CPU
      (``gpu_layers==0``, e.g. persisted while the second GPU was unplugged)
      but whose target device IS now detected again is restored to auto-offload
      (``gpu_layers=None``). Without this the brain stayed stuck on CPU forever
      after the GPU came back, because the stale ``SMALL_BRAIN_GPU_LAYERS=0`` in
      .env is indistinguishable from a deliberate choice on reload. The user can
      re-lock CPU at any time from the GUI (which writes an explicit value the
      next time the device is missing).

    Never touches the Big Brain (device 0 is assumed present) or non-llamacpp
    providers.
    """
    if config.role is BrainRole.SMALL and config.provider == PROVIDER_LLAMACPP:
        if config.device not in gpu_indexes:
            if config.gpu_layers != 0:
                config.gpu_layers = 0
                config.gpu_label = "CPU / System RAM"
                config.decision_support_only = True
        else:
            # Target GPU is present. Undo a stale CPU-only lock so the brain can
            # use the hardware again; clear the fallback marker too. Restore to
            # the GUI's "Auto" sentinel (-1) to match an untouched config.
            if config.gpu_layers == 0:
                config.gpu_layers = -1
            config.decision_support_only = False
    return config


def build_config(role: BrainRole, env: Optional[Dict[str, str]] = None) -> BrainConfig:
    """Build a ``BrainConfig`` for a role from environment (or an injected map).

    ``env`` is the environment mapping (defaults to ``os.environ``). This
    indirection keeps tests hermetic without mutating the real environment.
    """
    e = env if env is not None else os.environ
    if not hasattr(e, "get"):
        raise TypeError("env must be a mapping with string keys")
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

    # ── Optional llama.cpp flags (v2.1.9). Each returns None when the env key is
    # absent so build_llama_command omits the flag and llama.cpp keeps its own
    # default — an untouched config produces exactly the old command. ─────────
    def _opt_int(name: str) -> Optional[int]:
        raw = _g(name, "")
        if not raw:
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    def _opt_float(name: str) -> Optional[float]:
        raw = _g(name, "")
        if not raw:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _opt_bool(name: str) -> Optional[bool]:
        raw = _g(name, "").lower()
        if not raw:
            return None
        return raw in ("1", "true", "yes", "on")

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
        decision_support_only=_b("DECISION_SUPPORT", False),
        # performance
        flash_attn=_g("FLASH_ATTN", ""),
        cache_reuse=_opt_int("CACHE_REUSE"),
        ctx_checkpoints=_opt_int("CTX_CHECKPOINTS"),
        kv_offload=_opt_bool("KV_OFFLOAD"),
        show_perf=_b("SHOW_PERF", True),
        n_cpu_moe=_opt_int("N_CPU_MOE"),
        cpu_moe=_opt_bool("CPU_MOE"),
        n_cpu_ffn=_opt_int("N_CPU_FFN"),
        # sampling
        top_k=_opt_int("TOP_K"),
        top_p=_opt_float("TOP_P"),
        min_p=_opt_float("MIN_P"),
        repeat_penalty=_opt_float("REPEAT_PENALTY"),
        presence_penalty=_opt_float("PRESENCE_PENALTY"),
        frequency_penalty=_opt_float("FREQUENCY_PENALTY"),
        dry_multiplier=_opt_float("DRY_MULTIPLIER"),
        dry_base=_opt_float("DRY_BASE"),
        dry_allowed_length=_opt_int("DRY_ALLOWED_LENGTH"),
        dry_penalty_last_n=_opt_int("DRY_PENALTY_LAST_N"),
        xtc_probability=_opt_float("XTC_PROBABILITY"),
        xtc_threshold=_opt_float("XTC_THRESHOLD"),
        # reasoning
        reasoning_budget=_opt_int("REASONING_BUDGET"),
        reasoning_format=_g("REASONING_FORMAT", ""),
        # multimodal
        mmproj=_g("MMPROJ", ""),
        mmproj_offload=_opt_bool("MMPROJ_OFFLOAD"),
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
        # Ordered brain slots. Slots 0/1 are the SAME objects as the BIG/SMALL
        # role configs (so config(role) and slot_config(0/1) never diverge).
        # Slots 2+ are added only when more devices are enabled via the device
        # registry (see sync_slots). This is the N-brain generalization: the
        # GUI/launcher iterate slots(), the dialogue layer still uses roles.
        self._slots: List[BrainConfig] = [
            self._configs[BrainRole.BIG],
            self._configs[BrainRole.SMALL],
        ]
        self._health_cache: Dict[BrainRole, Dict[str, Any]] = {}

    # ── Factories ────────────────────────────────────────────────────────────
    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "DualBrainRuntime":
        return cls(big=build_config(BrainRole.BIG, env),
                   small=build_config(BrainRole.SMALL, env))

    @staticmethod
    def provider_diagnostics(
            env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Return redacted normalized provider settings for operator diagnostics."""
        from agents.core.configuration import redacted_configuration
        return redacted_configuration(os.environ if env is None else env)

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

    # ── N-brain slot access ─────────────────────────────────────────────────
    def slots(self) -> List[BrainConfig]:
        """Ordered brain slots (>= 2). Slots 0/1 are the BIG/SMALL role configs.

        The GUI/launcher iterate this to render/start one brain per enabled
        device. Safe to call from any thread (returns a shallow copy).
        """
        with self._lock:
            return list(self._slots)

    def slot_config(self, slot: int) -> Optional[BrainConfig]:
        """Return the config for slot ``slot`` (0-based), or None if out of range."""
        with self._lock:
            if 0 <= slot < len(self._slots):
                return self._slots[slot]
            return None

    def slot_for_device(self, device_id: str) -> Optional[BrainConfig]:
        """Return the slot config bound to ``device_id`` (registry stable id)."""
        if not device_id:
            return None
        with self._lock:
            for cfg in self._slots:
                if cfg.device_id == device_id:
                    return cfg
            return None

    def sync_slots(self, placements: List[Dict[str, Any]]) -> List[BrainConfig]:
        """Resize the slot list to match detected device placements.

        Slots 0/1 keep pointing at the BIG/SMALL role configs (their device is
        re-seeded from the placement so the GUI label/launch target stay correct,
        but the object identity is preserved so the dialogue layer never sees a
        swap). Slots 2+ are (re)built from the extra placements. Returns the
        resulting slot list. Never raises.
        """
        try:
            with self._lock:
                new_slots: List[BrainConfig] = []
                # Map role string -> BrainRole for placements.
                role_map = {"big": BrainRole.BIG, "small": BrainRole.SMALL}
                # Per-device model + settings choices (N-brain store in
                # settings.json). A slot adopts its device's saved model/settings
                # unless it already has one (e.g. the operator just picked it).
                try:
                    from agents.runtime import device_registry as _dr
                    _policy = _dr.load_policy()
                    _policy_models = _policy.models
                    _policy_settings = _policy.settings
                except Exception:
                    _policy_models = {}
                    _policy_settings = {}
                for i, placement in enumerate(placements):
                    if i < 2:
                        cfg = self._slots[i] if i < len(self._slots) else \
                            self._configs[BrainRole.BIG if i == 0 else BrainRole.SMALL]
                        cfg.slot = i
                        cfg.device_id = str(placement.get("device_id", ""))
                        # Re-seed device + port from the placement so the launch
                        # target follows detected hardware, but keep every other
                        # field the operator set in the GUI.
                        cfg.port = int(placement.get("port", cfg.port))
                        if not placement.get("is_cpu"):
                            cfg.device = int(placement.get("index", cfg.device))
                        label = placement.get("label") or placement.get("name", "")
                        if label:
                            cfg.gpu_label = label
                        new_slots.append(cfg)
                    else:
                        role = role_map.get(str(placement.get("role", "")), BrainRole.SMALL)
                        cfg = build_slot_config(placement, i, role)
                        # Adopt the device's saved model (slot 2+ has no .env key).
                        saved = _policy_models.get(cfg.device_id, "")
                        if saved:
                            cfg.model = saved
                        # Adopt the device's saved llama.cpp settings.
                        saved_settings = _policy_settings.get(cfg.device_id, {})
                        if saved_settings:
                            _apply_saved_settings(cfg, saved_settings)
                        new_slots.append(cfg)
                # Never drop below the two role configs.
                if len(new_slots) < 2:
                    new_slots = [
                        self._configs[BrainRole.BIG],
                        self._configs[BrainRole.SMALL],
                    ]
                self._slots = new_slots
                return list(self._slots)
        except Exception:
            with self._lock:
                return list(self._slots)

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
            selected_model_available = any(
                self._model_ids_match(selected_model, model) for model in models
            )
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

    @staticmethod
    def _model_ids_match(selected: str, reported: str) -> bool:
        def variants(value: str) -> set[str]:
            text = str(value or "").strip().replace("\\", "/").casefold()
            if not text:
                return set()
            base = text.rsplit("/", 1)[-1]
            return {text, base, base.removesuffix(".gguf")}

        return bool(variants(selected) & variants(reported))

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
    "build_slot_config",
    "default_contract",
    "SUPPORTED_PROVIDERS",
    "PROVIDER_LLAMACPP",
    "PROVIDER_OLLAMA",
    "PROVIDER_LMSTUDIO",
    "CPU_SMALL_MODEL_MAX_B",
    "estimate_model_size_b",
    "is_cpu_decision_model",
    "choose_cpu_decision_model",
    "apply_hardware_fallback",
]
