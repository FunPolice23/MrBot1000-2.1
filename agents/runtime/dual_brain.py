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
import logging
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ARCH-ENG-222: added so a context clamp is VISIBLE. Silently reducing the
# context an operator configured is exactly the kind of change that must not
# happen quietly -- a brain that suddenly answers from a shorter window looks
# like a model regression, not a safety clamp.
logger = logging.getLogger(__name__)

# ARCH-ENG-307: context-clamp notes already logged this process, keyed by
# (role, reason). build_config runs several times during startup and each run
# used to re-emit the identical INFO line; this keeps the note visible once
# without touching the logging level.
_CONTEXT_NOTES_LOGGED: set = set()


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

# Cloud providers (all OpenAI-compatible). A real API key is resolved at
# client-build time via provider_keys.resolve_provider_api_key (encrypted vault
# -> PROVIDER_API_KEY_<PROVIDER> env -> <ROLE>_API_KEY env -> fail-closed ""); it
# is never stored in config. Each maps to a default OpenAI-compatible base URL,
# overridable with <PROVIDER>_BASE_URL (e.g. OPENAI_BASE_URL) or the per-role
# BIG_BRAIN_URL / SMALL_BRAIN_URL.
PROVIDER_OPENAI = "openai"
PROVIDER_NVIDIA_NIM = "nvidia_nim"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_GROQ = "groq"
PROVIDER_TOGETHER = "together"
CLOUD_PROVIDER_DEFAULT_ENDPOINTS = {
    PROVIDER_OPENAI: "https://api.openai.com/v1",
    PROVIDER_NVIDIA_NIM: "https://integrate.api.nvidia.com/v1",
    PROVIDER_OPENROUTER: "https://openrouter.ai/api/v1",
    PROVIDER_GROQ: "https://api.groq.com/openai/v1",
    PROVIDER_TOGETHER: "https://api.together.xyz/v1",
}
LOCAL_PROVIDERS = {
    PROVIDER_LLAMACPP, PROVIDER_OLLAMA, PROVIDER_LMSTUDIO, PROVIDER_VLLM,
    PROVIDER_KOBOLDCPP,
}
SUPPORTED_PROVIDERS = LOCAL_PROVIDERS | set(CLOUD_PROVIDER_DEFAULT_ENDPOINTS)

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
    context_shift: Optional[bool] = None  # True -> --context-shift, False -> --no-context-shift
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

    # ── Multi-Token Prediction / speculative decoding (Phase G, ARCH-ENG-092) ──
    # "draft-mtp" enables llama.cpp MTP (predicts several tokens per pass using
    # the model's native multi-token head). Only meaningful for models that carry
    # an MTP head — see agents/providers/model_capabilities.detect_mtp. Empty =
    # flag omitted (byte-identical command for untouched configs). The GUI greys
    # the toggle when the selected model has no MTP head.
    spec_type: str = ""                      # "" | "draft-mtp" (--spec-type)
    spec_draft_n_max: Optional[int] = None   # --spec-draft-n-max N (default 3)

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
            # Derive the label from the target device instead of a hardcoded
            # literal. The old defaults baked in the legacy assumptions
            # ("GPU 0 (detected hardware)" for big, "CPU / System RAM" for
            # small), so a small brain that now targets a real GPU still
            # rendered as CPU/RAM until the GUI's _apply_runtime overwrote it —
            # which is why a restored 2nd GPU looked like a duplicate CPU row.
            # This does not detect hardware; it just stops lying about the
            # device the config already names. Detection still owns the truth
            # (dual_brain_control._apply_runtime / apply_hardware_fallback).
            self.gpu_label = (
                f"GPU {self.device}" if self.device >= 0 else "CPU / System RAM")
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
        if self.context_shift is not None:
            # v2.1.64 (ARCH-ENG-075): --context-shift lets llama.cpp roll the
            # context window forward when a conversation exceeds --ctx-size
            # instead of erroring ("context length exceeded") mid-dialogue. It
            # is DISABLED by default in llama.cpp, so without this a long
            # Chat/Dialogue thread dies on the question that overflows the
            # window. Off-by-default in the app too (flag omitted when unset)
            # so an untouched config is byte-identical to before.
            cmd += ["--context-shift" if self.context_shift else "--no-context-shift"]
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

        # Phase G (ARCH-ENG-092): Multi-Token Prediction. Only emitted when the
        # operator enabled it for a model that actually carries an MTP head (the
        # GUI greys the toggle otherwise). Omitted when unset so an untouched
        # config produces a byte-identical command.
        if self.spec_type == "draft-mtp":
            cmd += ["--spec-type", "draft-mtp"]
            if self.spec_draft_n_max is not None and self.spec_draft_n_max > 0:
                cmd += ["--spec-draft-n-max", str(self.spec_draft_n_max)]

        # Check if model template uses raise_exception and decide what to do.
        #
        # ARCH-ENG-270 (X-01): the decision used to be silent; log at the point
        # the fallback is actually applied -- the wrapper told you what the
        # predicate would say; this tells you what the running command did.
        #
        # ARCH-ENG-311: the builtin-substitution fallback is now OPT-IN. The
        # operator's llama.cpp build runs its chat through the Jinja engine
        # (`--jinja` default on) whose evaluator — minja — implements
        # `raise_exception()` itself and renders the model's OWN template, so
        # substituting a bare builtin (e.g. 6-char `chatml` for a Qwen3.5) was
        # actively harmful: it dropped the embedded template's tool-call
        # rendering and thinking delimiters, which the Dialogue tab's
        # tool-calling path (agents/dialogue/chat_completion.py sends
        # `tools` + `tool_choice=auto` to llama-server) depends on. Old llama.cpp
        # builds whose Jinja could not run such templates can restore the legacy
        # behaviour with MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK=1.
        if model and self._model_needs_raise_exception(model):
            legacy = (os.environ.get("MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK", "")
                      .strip().lower() in ("1", "true", "yes", "on"))
            if legacy:
                fallback_template = self._get_fallback_template(model)
                if fallback_template:
                    cmd += ["--chat-template", fallback_template]
                    logger.info(
                        "Chat template for %s contains raise_exception(); "
                        "applying legacy fallback template (%d chars)",
                        model, len(fallback_template))
                else:
                    logger.warning(
                        "Chat template for %s contains raise_exception() but no "
                        "legacy fallback template is available; the server may "
                        "reject every request", model)
            else:
                logger.info(
                    "Chat template for %s contains raise_exception(); left to "
                    "llama.cpp's Jinja engine, which implements raise_exception "
                    "and keeps the model's own tool-call rendering "
                    "(MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK=1 forces the legacy "
                    "builtin substitution)", model)

        return cmd
    
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
        """Legacy builtin chat-template substitution (only restored via
        ``MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK=1``, ARCH-ENG-311)."""
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
    # A cloud placement carries port=None (no local server); treat None as the
    # sequential default so int() never sees NoneType.
    _port = placement.get("port")
    port = int(_port) if _port is not None else (1234 + slot)
    defaults = ROLE_DEFAULTS[role]
    # Roster-driven: BrainRoster.to_placements carries the slot's provider/model.
    # Legacy device placements lack them -> llamacpp (byte-identical to before).
    provider = str(placement.get("provider") or PROVIDER_LLAMACPP)
    model = str(placement.get("model") or "")
    if provider in (PROVIDER_LLAMACPP, PROVIDER_VLLM, PROVIDER_KOBOLDCPP):
        endpoint = f"http://127.0.0.1:{port}/v1"   # per-slot local server
    else:
        endpoint, _ = _resolve_provider_endpoint(provider, defaults, {})  # cloud/shared
    # A GPU-hosted brain offloads by default (gpu_layers None = auto); a CPU
    # pool brain is system-RAM only (gpu_layers 0). Big brains get the big
    # context/threads defaults, small brains the small ones.
    gpu_layers = 0 if is_cpu else None
    context = defaults["context"] if role is BrainRole.BIG else 4096 if is_cpu else defaults["context"]
    return BrainConfig(
        role=role,
        provider=provider,
        endpoint=endpoint,
        model=model,
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
    # Phase G (ARCH-ENG-092): restore MTP / speculative decoding. Only the
    # documented value is honored; anything else is ignored (fail safe).
    st = saved.get("spec_type")
    if isinstance(st, str) and st == "draft-mtp":
        cfg.spec_type = "draft-mtp"
        try:
            n = saved.get("spec_draft_n_max")
            if n is not None:
                cfg.spec_draft_n_max = int(n)
        except (TypeError, ValueError):
            pass


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
            # Target GPU is gone. Force CPU offload AND correct the label
            # unconditionally — the label must not depend on the prior
            # gpu_layers value, or a config that already carried gpu_layers=0
            # (or a pre-seeded "GPU 1" label) keeps the wrong text.
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


def _resolve_provider_endpoint(provider: str, defaults: Dict[str, Any],
                               e: Any) -> "tuple[str, str]":
    """Resolve ``(endpoint_default, provider_endpoint)`` for a provider kind.

    Local providers default to a loopback endpoint overridable with
    ``<PROVIDER>_BASE_URL``; cloud providers use their OpenAI-compatible default
    (``CLOUD_PROVIDER_DEFAULT_ENDPOINTS``), also overridable. Shared by
    ``build_config`` (legacy env path) and the roster path so both resolve
    endpoints identically — one source of truth, no drift.
    """
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
    elif provider in CLOUD_PROVIDER_DEFAULT_ENDPOINTS:
        provider_endpoint = e.get(f"{provider.upper()}_BASE_URL", "").strip().rstrip("/")
        endpoint_default = provider_endpoint or CLOUD_PROVIDER_DEFAULT_ENDPOINTS[provider]
    return endpoint_default, provider_endpoint


def _config_from_roster_slot(role: "BrainRole", roster: Any,
                             e: Any) -> Optional["BrainConfig"]:
    """Build a ``BrainConfig`` from the roster's primary enabled slot for *role*.

    Returns ``None`` when the roster has no enabled slot for the role, so the
    caller falls back to the legacy env path. The slot's provider/model drive the
    config; the endpoint resolves through the SAME ``_resolve_provider_endpoint``
    the legacy path uses. Ports: a local slot keeps the role default port unless
    the operator set one; a cloud slot needs no port.
    """
    slots = roster.big if role is BrainRole.BIG else roster.small
    slot = next((s for s in slots if s.enabled), None)
    if slot is None:
        return None
    defaults = ROLE_DEFAULTS[role]
    # Start from the legacy env config so the operator's tuned llama.cpp flags
    # (context/threads/batch/kv_cache/split_mode + all 9 perf flags:
    # flash_attn/cache_reuse/context_shift/ctx_checkpoints/kv_offload/show_perf/
    # n_cpu_moe/cpu_moe/n_cpu_ffn) are PRESERVED, then override only the
    # roster-driven identity: provider/model/port/device_id/endpoint. This fixes
    # the flags-reset P1 (the roster path used to rebuild from factory defaults).
    cfg = build_config(role, e)   # legacy path (roster=None) - env-tuned fields
    is_cpu_default = role is BrainRole.SMALL and slot.is_local and not slot.device_id
    port = slot.port if slot.port > 0 else cfg.port
    cfg.provider = slot.provider
    cfg.model = slot.model
    cfg.port = port
    cfg.device_id = slot.device_id
    if slot.provider in (PROVIDER_LLAMACPP, PROVIDER_VLLM, PROVIDER_KOBOLDCPP):
        cfg.endpoint = f"http://127.0.0.1:{port}/v1"   # per-slot local server
    else:
        cfg.endpoint, _ = _resolve_provider_endpoint(slot.provider, defaults, e)
    # A CPU roster slot is system-RAM only (gpu_layers 0) AND gets the
    # decision-support posture back (Security's P2 fix: it was hardcoded False,
    # dropping the prompt-level advisory-only guardrail for CPU roster brains).
    if is_cpu_default:
        cfg.gpu_layers = 0
    cfg.decision_support_only = is_cpu_default
    return cfg


# ARCH-ENG-222: fraction of VRAM left for compute, CUDA context, allocator
# fragmentation and the compositor. The rest is what weights + KV may share.
_VRAM_COMPUTE_RESERVE = 0.25

# Fallback context when the model file is unknown, keyed on the device's VRAM.
# Used when there is no GGUF to measure -- e.g. a cloud provider, or a local
# slot whose model name is not a path.
_VRAM_TIER_CONTEXT = ((8.0, 8192), (12.0, 16384), (24.0, 32768))


def _tier_context_for(base_context: int, kv_type_bytes: int) -> int:
    """Scale a tier's f16 context allowance for the actual KV byte width.

    ARCH-ENG-291 (M-03): the fallback path was handed ``kv_type_bytes`` and
    ignored it, so a q8_0 operator got the f16-sized allowance. The tier table
    is calibrated for 2-byte KV entries; a narrower entry fits proportionally
    more context. Never expand beyond the configured default (the caller still
    applies that clamp), and keep the measured path's 256-token granularity.
    """
    try:
        width = float(kv_type_bytes or 2.0)
    except (TypeError, ValueError):
        width = 2.0
    width = max(width, 0.5)
    scaled = int(base_context * (2.0 / width))
    scaled = (scaled // 256) * 256
    return max(4096, scaled)


def _vram_safe_context(default_context: int, role: "BrainRole",
                       device_index: int, gpu_layers: Optional[int],
                       model_path: Optional[str] = None,
                       kv_type_bytes: int = 2) -> Tuple[int, str]:
    """Clamp *default_context* to what the target device's VRAM can actually hold.

    ARCH-ENG-222. `ROLE_DEFAULTS` ships `context: 64768` with `kv_cache: "f16"`.
    For an 8B-class model (36 layers, 8 KV heads, 128 head dim) that is

        2 * 36 * 8 * 128 * 2 bytes * 64768 tokens  =  9.55 GB of KV cache

    before a single weight is loaded. On the operator's GTX 1660 Super (6 GB)
    that is not a slow context, it is a hard allocation failure: CUDA OOM ->
    Windows TDR -> display-driver reset or reboot. On the 16 GB card it leaves
    almost nothing for weights.

    The configured value is still what the operator ASKED for, and this only
    changes the DEFAULT. An explicit `BIG_BRAIN_CONTEXT` in `.env` still wins
    untouched -- a deliberate setting is not second-guessed.

    Measured against the real file when there is one, via
    `gguf_meta.estimate_vram_gb` (already cached). Otherwise falls back to a
    VRAM tier table. Never returns MORE than `default_context`: this narrows a
    risky default, it does not expand one.
    """
    try:
        from agents.runtime import device_registry as dr
        devices = dr.detect_devices(include_cpu=False)
    except Exception:
        return default_context, "device detection failed; keeping the configured default"

    dev = next((d for d in devices if getattr(d, "is_gpu", False)
                and getattr(d, "index", -1) == device_index), None)
    if dev is None:
        return default_context, "target device not detected; keeping the configured default"
    vram_bytes = float(getattr(dev, "memory_gb", 0.0)) * 1e9
    if vram_bytes <= 0:
        return default_context, "detected device reports no VRAM; keeping the configured default"

    budget = vram_bytes * (1.0 - _VRAM_COMPUTE_RESERVE)

    # Measure the real model when we can.
    if model_path and os.path.isfile(model_path):
        try:
            from agents.providers.gguf_meta import estimate_vram_gb
            est = estimate_vram_gb(model_path, context=default_context,
                                   kv_type_bytes=kv_type_bytes)
            if est.get("complete"):
                weights_gb = float(est.get("weights_gb") or 0.0)
                kv_bytes = 2 * est["n_layer"] * est["kv_head"] * est["head_dim"] \
                    * kv_type_bytes
                if kv_bytes <= 0:
                    return default_context, "model reports a zero-byte KV token; keeping default"
                room = budget - weights_gb * 1e9
                if room <= 0:
                    return (_VRAM_TIER_CONTEXT[0][1],
                            f"weights ({weights_gb:.1f} GB) already exceed the "
                            f"{vram_bytes/1e9:.1f} GB budget; clamped to the lowest tier")
                fits = int(room // kv_bytes)
                fits = (fits // 256) * 256          # round down to a 256 multiple
                fits = max(4096, min(fits, default_context))
                fits = min(fits, default_context)
                if fits >= default_context:
                    return default_context, (
                        f"weights {weights_gb:.1f} GB + KV at {default_context} ctx "
                        f"fits the {vram_bytes/1e9:.1f} GB budget; no clamp needed")
                return fits, (f"clamped {default_context} -> {fits}: weights "
                              f"{weights_gb:.1f} GB + KV at {default_context} ctx = "
                              f"{weights_gb + est['kv_gb']:.1f} GB exceeds the "
                              f"{vram_bytes/1e9:.1f} GB budget for this device")
        except Exception:
            pass                                # fall through to the tier table

    for ceiling, ctx in _VRAM_TIER_CONTEXT:
        if vram_bytes < ceiling * 1e9:
            allowed = _tier_context_for(ctx, kv_type_bytes)
            if allowed >= default_context:
                return default_context, "device VRAM is sufficient for the configured default"
            # ARCH-ENG-291 (M-03): report the KV width that produced the
            # allowance so a q8_0/q4_0 operator can see why it differs.
            # ARCH-ENG-307: say WHY the tier table ran. The measured path
            # above reports its own numbers; reaching this line means the
            # model was NOT measurable, which is the operative fact for an
            # operator deciding whether to trust the clamped default.
            why = (f"model at {model_path} was not measurable" if model_path
                   else "no local model file to measure")
            return allowed, (f"{why}; {vram_bytes/1e9:.1f} GB VRAM tier "
                             f"allows {allowed} at {kv_type_bytes}-byte KV, "
                             f"not {default_context}")
    return default_context, "device has ample VRAM for the configured default"


def build_config(role: BrainRole, env: Optional[Dict[str, str]] = None,
                 roster: Any = None) -> BrainConfig:
    """Build a ``BrainConfig`` for a role from environment (or an injected map).

    ``env`` is the environment mapping (defaults to ``os.environ``). This
    indirection keeps tests hermetic without mutating the real environment.
    """
    e = env if env is not None else os.environ
    if not hasattr(e, "get"):
        raise TypeError("env must be a mapping with string keys")
    prefix = "BIG_BRAIN" if role is BrainRole.BIG else "SMALL_BRAIN"
    defaults = ROLE_DEFAULTS[role]

    # Phase 4: when a roster is supplied, the roster's primary enabled slot for
    # this role drives the config; roster=None (the default) keeps the legacy env
    # path byte-identical.
    if roster is not None:
        cfg = _config_from_roster_slot(role, roster, e)
        if cfg is not None:
            return cfg

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
    endpoint_default, provider_endpoint = _resolve_provider_endpoint(provider, defaults, e)
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
    explicit_context = bool((e.get(f"{prefix}_CONTEXT", "") or "").strip())
    if cpu_only:
        context_default = 4096
        context_reason = "CPU-only slot; using the small default context"
    elif explicit_context:
        # ARCH-ENG-307: an explicit CONTEXT in the environment is a deliberate
        # operator setting and wins untouched -- the ARCH-ENG-222 contract.
        # The VRAM clamp narrows only the DEFAULT, so with an override present
        # the clamp result was never used; emitting its note anyway told the
        # operator the context "allows 16384 ... not 32768" while the brain
        # actually ran 32768. Compute nothing, log nothing.
        try:
            context_default = int((e.get(f"{prefix}_CONTEXT", "") or "").strip())
        except (TypeError, ValueError):
            context_default = defaults["context"]
        context_reason = "explicit CONTEXT override; the VRAM default-clamp is not applied"
    else:
        # ARCH-ENG-222: the 64768 default needs ~9.5 GB of KV on an 8B-class
        # model, which cannot fit a 6 GB card. See `_vram_safe_context`.
        context_default, context_reason = _vram_safe_context(
            defaults["context"], role,
            _i("DEVICE", defaults["device"]),
            gpu_layers,
            model_path=_g("MODEL_PATH", "") or None,
            kv_type_bytes=2 if _g("KV_CACHE", defaults.get("kv_cache", "f16")).lower() != "q8_0" else 1,
        )
        if context_default != defaults["context"]:
            # ARCH-ENG-307: build_config runs several times during startup
            # (fresh lookups, roster syncs, settings reloads) and every run
            # re-logged the same tier note -- five identical INFO lines for
            # one decision. Log each distinct note once per process.
            note = (role.value, context_reason)
            if note not in _CONTEXT_NOTES_LOGGED:
                _CONTEXT_NOTES_LOGGED.add(note)
                logger.info("[%s] context %s", role.value, context_reason)

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

    def _opt_bool_no_m(name: str) -> Optional[bool]:
        """ARCH-ENG-315: parse a "Keep X in system RAM" checkbox key.

        The GUI phrase is what the OPERATOR wants; the config field is
        llama.cpp's offload state, where ``False`` emits ``--no-…-offload``.
        Checked ("true") therefore means *keeping it out of VRAM* — an
        explicit `offload disabled` — and unchecked/absent means llama.cpp's
        own default (offload enabled). The old parse read the box as if it
        were the offload state itself, so a checked "Keep KV cache in system
        RAM"/"Keep projector on CPU" box emitted NO flag at all.
        """
        raw = _opt_bool(name)
        if raw is None:
            return None
        return not raw

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
        context_shift=_opt_bool("CONTEXT_SHIFT"),
        ctx_checkpoints=_opt_int("CTX_CHECKPOINTS"),
        # ARCH-ENG-315: KV_OFFLOAD/MMPROJ_OFFLOAD GUI boxes are phrased as the
        # operator's wish ("keep in system RAM"); see _opt_bool_no_m.
        kv_offload=_opt_bool_no_m("KV_OFFLOAD"),
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
        mmproj_offload=_opt_bool_no_m("MMPROJ_OFFLOAD"),
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

    @classmethod
    def from_roster(cls, roster: Any, env: Optional[Dict[str, str]] = None) -> "DualBrainRuntime":
        """Build the runtime from a ``BrainRoster`` (Phase 4).

        Each role's config comes from the roster's primary enabled slot; a role
        with no enabled slot falls back to the legacy env path for that role.
        """
        return cls(big=build_config(BrainRole.BIG, env, roster=roster),
                   small=build_config(BrainRole.SMALL, env, roster=roster))

    @classmethod
    def from_settings(cls, env: Optional[Dict[str, str]] = None,
                      root: Optional[str] = None) -> "DualBrainRuntime":
        """Build the runtime from the persisted roster when present, else legacy.

        This is the Phase 4 entry point that reads the roster instead of the
        legacy ``{prefix}_MAIN_ENABLED`` gates. No ``"roster"`` key in
        settings.json -> legacy env path, byte-identical.
        """
        from agents.runtime.brain_roster import BrainRoster
        roster = BrainRoster.load_or_none(root)
        if roster is not None:
            return cls.from_roster(roster, env)
        return cls.from_env(env)

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
                    is_cpu_placement = bool(placement.get("is_cpu"))
                    if i < 2:
                        cfg = self._slots[i] if i < len(self._slots) else \
                            self._configs[BrainRole.BIG if i == 0 else BrainRole.SMALL]
                        cfg.slot = i
                        cfg.device_id = str(placement.get("device_id", ""))
                        # Re-seed device + port from the placement so the launch
                        # target follows detected hardware, but keep every other
                        # field the operator set in the GUI.
                        cfg.port = int(placement.get("port", cfg.port))
                        if not is_cpu_placement:
                            cfg.device = int(placement.get("index", cfg.device))
                        label = placement.get("label") or placement.get("name", "")
                        if label:
                            cfg.gpu_label = label
                        # v2.1.49 (ARCH-ENG-049): a CPU/RAM pool that lands in
                        # slot 0/1 must be forced system-RAM-only, exactly as a
                        # slot-2+ placement is (build_slot_config). Without this
                        # a single-GPU box kept the role config's GPU defaults —
                        # gpu_layers=None -> full offload and `--device CUDA1`
                        # aimed at a card that does not exist, so the Small Brain
                        # failed to launch and the settings never round-tripped
                        # through the device policy.
                        if is_cpu_placement:
                            cfg.gpu_layers = 0
                            cfg.decision_support_only = True
                            cfg.device = 0
                        else:
                            cfg.decision_support_only = False
                        # Slots 0/1 persist via .env, but a CPU-pool or
                        # extra-device role ALSO has a device-policy entry (the
                        # operator edited it in Per-Device Settings). Adopt the
                        # saved settings after the CPU forcing above so an
                        # operator-chosen context/threads still wins.
                        saved_settings = _policy_settings.get(cfg.device_id, {})
                        if saved_settings:
                            _apply_saved_settings(cfg, saved_settings)
                            if is_cpu_placement:
                                cfg.gpu_layers = 0
                                cfg.decision_support_only = True
                        saved = _policy_models.get(cfg.device_id, "")
                        if saved:
                            cfg.model = saved
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
            # ARCH-ENG-188: THE CACHE NEVER EXPIRED.
            #
            # `checked_at` was RECORDED (line 1140) and never READ. So once a
            # role was cached, `list_models` returned that snapshot forever
            # unless the caller explicitly passed `refresh=True` — and the only
            # in-tree caller is `health(refresh=refresh_health)`, whose
            # `refresh_health` defaults to False.
            #
            # The visible consequence: a server that died kept reporting
            # `reachable: True` with its full model list, indefinitely, while
            # the panel showed it as running. That is the THIRD instance of one
            # recurring defect in this release:
            #
            #   * ARCH-ENG-179 — provider status re-applied the previous snapshot,
            #     so a stopped provider could never be reported stopped.
            #   * ARCH-ENG-185 — `_blocked_personas` was add-only, so a cleared
            #     gate stayed blocking in the live prompt.
            #   * ARCH-ENG-188 — the health cache had a timestamp that nothing
            #     consulted, so a dead server stayed reachable.
            #
            # All three are the same mistake: an OBSERVATION cached and then
            # presented as current fact, with no expiry. The common shape is a
            # field written for exactly this purpose and never read — so the fix
            # is always to consult what was already being recorded.
            #
            # The TTL is deliberately short. This cache exists to stop the UI
            # re-probing on every repaint, not to make a down server look up.
            # The stale entry is left in place until the fresh probe replaces
            # it, so a failing probe does not erase the last known state
            # mid-call and leave a half-populated snapshot behind.
            if cached is not None and not refresh:
                try:
                    ttl = float(os.getenv("DUAL_BRAIN_HEALTH_TTL", "10"))
                except ValueError:
                    ttl = 10.0
                if ttl > 0:
                    try:
                        age = time.time() - float(
                            cached.get("checked_at") or 0.0)
                    except (TypeError, ValueError):
                        age = float("inf")
                    if age <= ttl:
                        return list(cached.get("models", []))
                # Expired, or caching disabled entirely (ttl <= 0 means "do not
                # cache"). The `ttl > 0` test is explicit rather than relying on
                # `age <= ttl`, because Windows' `time.time()` has ~15 ms
                # granularity: an entry written moments ago can measure as
                # exactly 0.0, which would satisfy `0.0 <= 0.0` and serve a cache
                # hit for an operator who asked for no caching at all.
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
