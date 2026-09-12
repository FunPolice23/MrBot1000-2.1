# MrBot1000/agents/llm_runtime.py — reusable LLM-runtime library.
"""
Standalone, dependency-light helpers for running LLMs across providers. Extracted
from agents/base_worker.py (v2.0.34ah, Section E part B) so other tools/scripts can
reuse the same model-selection, GPU-offload, architecture, and token-budget logic
without pulling in the whole WorkerAgent.

This module must NOT import from base_worker (to avoid a cycle). It only depends on
stdlib + provider_models + optional tiktoken.
"""
import os
from typing import Dict, Optional, Any

# ── Model architecture detection (Section E F4) ────────────────────────────────
def model_arch_info(model: str, *, live: bool = True) -> dict:
    """Return architecture metadata for an Ollama `model` (dense vs MoE, experts, params, context).

    Thin wrapper over `provider_models.get_arch_info` so the rest of the app has
    one import site. NEVER raises — degrades to conservative defaults.
    """
    try:
        from provider_models import get_arch_info
        return get_arch_info(model, live=live)
    except Exception:
        return {"architecture": "", "moe": False, "experts": None,
                "active_experts": None, "params_billion": None, "context": None}


def detect_vram_gb() -> int:
    """Best-effort detection of total GPU VRAM in GB (0 if none / unknown).

    Tries, in order: nvidia-smi (NVIDIA), torch.cuda (any CUDA GPU), then falls
    back to 0. NEVER raises. Used to auto-tune Ollama GPU offload for the
    operator's real hardware (e.g. a GTX 1660S 6GB) instead of guessing.
    """
    # 1) nvidia-smi — most reliable when the NVIDIA driver is present.
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0:
            vals = [int(x.strip()) for x in out.stdout.splitlines() if x.strip().isdigit()]
            if vals:
                # total across GPUs; single-GPU boxes are the norm here.
                return sum(vals) // 1024
    except Exception:
        pass
    # 2) torch.cuda — covers other CUDA vendors and confirms a GPU is present.
    try:
        import torch
        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(0).total_memory
            return int(total // (1024 ** 3))
    except Exception:
        pass
    return 0


# Cached VRAM value so we only shell out once per process.
_VRAM_GB_CACHE: int | None = None

def vram_gb() -> int:
    global _VRAM_GB_CACHE
    if _VRAM_GB_CACHE is None:
        _VRAM_GB_CACHE = detect_vram_gb()
    return _VRAM_GB_CACHE


def num_gpu_for(model: str, chat: bool) -> int | None:
    """v2.0.34ab (Section E F5): resolve `num_gpu` (GPU layers) for an Ollama call.

    Return semantics:
      - explicit int from OLLAMA_MAIN_GPU / OLLAMA_CHAT_GPU  -> that int (incl. -1)
      - env "auto" or unset  -> None  (AUTO: caller omits num_gpu so Ollama's own
        VRAM-aware scheduler offloads as many layers as fit — the safe, fastest
        choice on a small GPU like a 6GB GTX 1660S, and never OOMs).
      - if VRAM detection is unavailable we still return None (Ollama default).

    We deliberately do NOT hardcode a layer count: a fixed count either wastes a
    big GPU or OOMs a small one. Letting the detected-GPU path defer to Ollama is
    correct for "works on any hardware" and never blocks startup.
    """
    env = os.getenv("OLLAMA_CHAT_GPU" if chat else "OLLAMA_MAIN_GPU", "").strip().lower()
    # -1 / "auto" / unset  -> AUTO: omit num_gpu, let Ollama's VRAM-aware
    # scheduler offload what fits. Only a positive explicit integer forces a
    # specific layer count (0 = force CPU-only).
    if env in ("auto", "", "-1"):
        return None
    if env.lstrip("-+").isdigit():
        val = int(env)
        if val < 0:
            return None
        return val
    return None


# ── Token budgeting (v2.0.25) ────────────────────────────────────────────────────
def estimate_tokens(text, provider=None):
    """Rough token count for a prompt string. OpenAI uses tiktoken; else chars/4."""
    if not text:
        return 0
    if provider == "openai":
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def _trim_to_tokens(text, budget_tokens, provider=None):
    """Keep the TAIL (most recent content); cut from the front when over budget."""
    if estimate_tokens(text, provider) <= budget_tokens:
        return text
    chars = budget_tokens * 4
    if len(text) <= chars:
        return text
    return "...[truncated]\n" + text[-chars:]


def fit_prompt_to_ctx(system, user, budget_tokens, provider=None):
    """Defensively truncate (system, user) so est_tokens(system+user) <= budget."""
    sys_t = estimate_tokens(system or "", provider)
    usr_t = estimate_tokens(user or "", provider)
    if sys_t + usr_t <= budget_tokens:
        return system, user
    if sys_t > budget_tokens:
        system = _trim_to_tokens(system, max(0, budget_tokens - 64), provider)
        return system, ""
    user = _trim_to_tokens(user, budget_tokens - sys_t, provider)
    return system, user
