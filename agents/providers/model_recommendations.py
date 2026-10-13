"""Per-model recommended llama.cpp settings (Phase G, ARCH-ENG-095).

A data-driven table of sensible launch defaults per model family / architecture,
joined at runtime with capability detection (MTP) so the app can SUGGEST settings
for the selected model. This is the foundation for a future "Apply recommended
settings" button; today it ships as data + a resolver (``recommend``) plus a doc
(``docs/MODEL_RECOMMENDATIONS.md``) describing how to extend it.

Design rules
------------
- Recommendations are DEFAULTS, never auto-applied. The operator stays in
  control; nothing here changes a running brain without an explicit action.
- Values are conservative and hardware-aware: they assume a single big GPU +
  a CPU/RAM pool. MoE (A3B/A4B) models get guidance that leans on expert offload
  (``--n-cpu-moe`` / partial layers) to fit; dense models lean on full offload.
- ``recommend(path)`` never raises and never fabricates: an unknown family
  falls back to safe generic defaults, and MTP is reported only when the model
  actually carries an MTP head.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Recommended launch settings per family. Keys map to BrainConfig fields where
# they exist; the rest are advisory notes surfaced in the GUI/doc. All values are
# starting points the operator can override.
#
# context      : default context window (tokens)
# gpu_layers   : -1 = auto/full offload, 0 = CPU, N = N layers
# kv_cache     : KV cache data type
# flash_attn   : on|off|auto
# mtp          : True = this family is typically MTP-capable (still confirmed by
#                detect_mtp at runtime)
# spec_draft_n_max : suggested MTP draft tokens when MTP is on
# notes        : short human guidance
RECOMMENDATIONS: Dict[str, Dict[str, Any]] = {
    "gemma": {
        "context": 8192, "gpu_layers": -1, "kv_cache": "f16",
        "flash_attn": "auto", "mtp": False, "spec_draft_n_max": 0,
        "notes": "Dense Gemma. Full GPU offload; f16 KV. Keep context modest "
                 "(8k) unless you have VRAM headroom.",
    },
    "gemma4": {
        "context": 8192, "gpu_layers": -1, "kv_cache": "q8_0",
        "flash_attn": "on", "mtp": False, "spec_draft_n_max": 0,
        "notes": "Gemma 4 (MoE A4B / E-series). q8_0 KV saves VRAM; flash-attn "
                 "on. MoE experts may spill to CPU on a 16 GB card.",
    },
    "qwen3": {
        "context": 32768, "gpu_layers": -1, "kv_cache": "q8_0",
        "flash_attn": "on", "mtp": False, "spec_draft_n_max": 0,
        "notes": "Dense Qwen3 thinking model. 32k context, q8_0 KV, flash-attn "
                 "on. Not MTP in these quants.",
    },
    "qwen3_6": {
        "context": 32768, "gpu_layers": -1, "kv_cache": "q8_0",
        "flash_attn": "on", "mtp": True, "spec_draft_n_max": 3,
        "notes": "Qwen3.6 MoE (A3B). 32k, q8_0 KV, flash-attn on. Some 35B-A3B "
                 "quants carry an MTP head — enable MTP if the toggle is live.",
    },
    "qwen3_8": {
        "context": 32768, "gpu_layers": -1, "kv_cache": "q8_0",
        "flash_attn": "on", "mtp": True, "spec_draft_n_max": 3,
        "notes": "Qwen3.8 dense, MTP-capable. Enable MTP for a throughput boost.",
    },
    "glm": {
        "context": 32768, "gpu_layers": 40, "kv_cache": "q8_0",
        "flash_attn": "on", "mtp": False, "spec_draft_n_max": 0,
        "notes": "GLM MoE. Partial offload (~40 layers) fits a 16 GB card; q8_0 "
                 "KV. This REAP-23B quant has no MTP head.",
    },
    "deepseek": {
        "context": 32768, "gpu_layers": -1, "kv_cache": "q8_0",
        "flash_attn": "on", "mtp": True, "spec_draft_n_max": 3,
        "notes": "DeepSeek. V3/R1 lines are MTP-native — enable MTP if the model "
                 "carries the head. q8_0 KV for long contexts.",
    },
    "nemotron": {
        "context": 32768, "gpu_layers": -1, "kv_cache": "q8_0",
        "flash_attn": "on", "mtp": True, "spec_draft_n_max": 3,
        "notes": "Nemotron (incl. Moe hybrids). Newer 30B-A3B lines carry an MTP "
                 "head — enable MTP when the toggle is live.",
    },
    "lfm": {
        "context": 32768, "gpu_layers": -1, "kv_cache": "f16",
        "flash_attn": "auto", "mtp": False, "spec_draft_n_max": 0,
        "notes": "LFM2.5 small/fast. Good CPU/RAM brain. f16 KV, modest context.",
    },
    "phi": {
        "context": 16384, "gpu_layers": -1, "kv_cache": "f16",
        "flash_attn": "auto", "mtp": False, "spec_draft_n_max": 0,
        "notes": "Phi dense. Full offload, 16k context is plenty.",
    },
    "mistral": {
        "context": 32768, "gpu_layers": -1, "kv_cache": "q8_0",
        "flash_attn": "on", "mtp": False, "spec_draft_n_max": 0,
        "notes": "Mistral / Ministral dense. Full offload, q8_0 KV, 32k context.",
    },
}

# Safe generic fallback for an unknown family.
_GENERIC = {
    "context": 8192, "gpu_layers": -1, "kv_cache": "f16",
    "flash_attn": "auto", "mtp": False, "spec_draft_n_max": 0,
    "notes": "Unknown model family — using safe generic defaults. Full offload, "
             "f16 KV, 8k context. Tune from there.",
}


def _detect_family(model_path: str) -> Optional[str]:
    try:
        from agents.providers.model_profile import detect_model_family
        return detect_model_family(model_path)
    except Exception:
        return None


def recommend(model_path: str) -> Dict[str, Any]:
    """Return recommended settings for a model, joined with live MTP detection.

    Never raises. MTP is reported True only when the family is MTP-typical AND
    the model actually carries an MTP head (detect_mtp) — so a GLM/Qwen3.6-14B
    quant without a head is correctly reported as MTP-off.
    """
    family = _detect_family(model_path)
    base = dict(RECOMMENDATIONS.get(family or "", _GENERIC))
    base["family"] = family or "unknown"
    # Confirm MTP against the real model (fail-safe: unknown -> False).
    mtp_supported = False
    try:
        from agents.providers.model_capabilities import detect_mtp
        mtp_supported = bool(detect_mtp(model_path).get("supported"))
    except Exception:
        mtp_supported = False
    base["mtp"] = bool(base.get("mtp")) and mtp_supported
    base["mtp_head_present"] = mtp_supported
    if not base["mtp"]:
        base["spec_draft_n_max"] = 0
    return base


def summary(model_path: str) -> str:
    """A short human-readable recommendation line for the GUI status."""
    r = recommend(model_path)
    parts = [f"{r['family']}", f"ctx {r['context']}",
             f"gpu_layers {r['gpu_layers']}", f"kv {r['kv_cache']}",
             f"flash {r['flash_attn']}"]
    parts.append("MTP on" if r["mtp"] else "MTP off")
    return " · ".join(parts)


__all__ = ["RECOMMENDATIONS", "recommend", "summary"]
