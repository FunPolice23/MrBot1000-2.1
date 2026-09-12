"""Cloud-provider model discovery + pricing for the Settings tab.

Given a provider + API key (+ optional base_url), fetch the available models
and return them with pricing info so the UI can show a dropdown like
`claude-3-5-sonnet — $3.00 in / $15.00 out` or `model — FREE`.

Design notes
------------
* OpenRouter is the richest source: one key returns models from many vendors
  (OpenAI, Anthropic, Google, Meta, Mistral, DeepSeek, …) WITH real per-token
  pricing in `pricing.prompt` / `pricing.completion` (USD/token).
* OpenAI / Gemini / Groq / DeepSeek / Mistral / Together expose an OpenAI-
  compatible `GET {base}/v1/models` that returns IDs only — pricing comes from a
  small static table keyed by model-id prefix.
* Anthropic has NO public models API, so we ship a curated static list with
  known pricing (clearly a snapshot; the UI notes it).
* Local providers (vLLM / LM Studio / KoboldCpp / Ollama) are not fetched
  remotely — the UI keeps them editable (Ollama already lists local models).

Caching: results are cached in-memory and to `models_cache.json` (keyed by
provider + base_url) so restarts are instant and offline use still works.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ModelInfo:
    id: str
    label: str
    price_in_per_1m: Optional[float] = None   # USD per 1M input tokens
    price_out_per_1m: Optional[float] = None  # USD per 1M output tokens
    context: Optional[int] = None
    free: bool = False
    vendor: str = ""                            # e.g. "OpenAI", "Anthropic"
    # v2.0.34aa (Section E/F4): architecture awareness (dense vs MoE).
    architecture: str = ""                      # e.g. "llama", "qwen3", "gpt-oss"
    moe: bool = False                           # True if a Mixture-of-Experts model
    experts: Optional[int] = None               # total experts (MoE)
    active_experts: Optional[int] = None        # experts active per token (MoE)
    params_billion: Optional[float] = None      # approx total params (billions)
    active_params_billion: Optional[float] = None  # active MoE params, when known
    raw: dict = field(default_factory=dict)

    @property
    def arch_label(self) -> str:
        if self.moe:
            ex = f" · {self.experts}e" if self.experts else ""
            ae = f"/{self.active_experts}a" if self.active_experts else ""
            return f"MoE{ex}{ae}"
        return "dense"

    @property
    def params_label(self) -> str:
        if self.params_billion is None:
            return ""
        p = self.params_billion
        return f"{p:.1f}B" if p < 10 else f"{p:.0f}B"

    @property
    def size_band(self) -> str:
        """Return the runtime-oriented model band used by role guidance."""
        return classify_model_band(
            self.params_billion,
            moe=self.moe,
            active_params_billion=self.active_params_billion,
        )

    @property
    def size_label(self) -> str:
        """Display total size and the active MoE size when they differ."""
        if self.params_billion is None:
            return "unknown size"
        total = self.params_label
        active = self.active_params_billion
        if self.moe and active is not None and active < self.params_billion:
            return f"{total} total / {active:g}B active"
        return total

    @property
    def price_out_display(self) -> str:
        if self.free:
            return "FREE"
        # Unknown price (no static table entry, not flagged free): show "n/a"
        # rather than misleading "FREE" so the operator knows pricing is unset.
        if self.price_in_per_1m is None and self.price_out_per_1m is None:
            return "n/a"
        inn = f"${self.price_in_per_1m:.2f}" if self.price_in_per_1m is not None else "?"
        out = f"${self.price_out_per_1m:.2f}" if self.price_out_per_1m is not None else "?"
        return f"{inn} in / {out} out"

    @property
    def combo_text(self) -> str:
        bits = [self.id]
        if self.params_label:
            bits.append(f" · {self.size_label} · {self.size_band}")
        if self.moe or self.architecture:
            bits.append(f" · {self.arch_label}")
        bits.append(f" — {self.price_out_display}")
        return "".join(bits)

    @property
    def tooltip(self) -> str:
        bits = [f"id: {self.id}"]
        if self.vendor:
            bits.append(f"vendor: {self.vendor}")
        if self.architecture:
            bits.append(f"arch: {self.architecture}")
        bits.append(f"type: {self.arch_label}")
        if self.params_label:
            bits.append(f"params: {self.size_label}")
        bits.append(f"size band: {self.size_band}")
        bits.append(f"price: {self.price_out_display} (per 1M tokens)")
        if self.context:
            bits.append(f"context: {self.context:,} tokens")
        return "\n".join(bits)


# ---------------------------------------------------------------------------
# Static pricing tables (USD per 1M tokens) for providers without pricing API
# ---------------------------------------------------------------------------


def classify_model_band(
    params_billion: Optional[float],
    *,
    moe: bool = False,
    active_params_billion: Optional[float] = None,
) -> str:
    """Classify a model by runtime-relevant parameter count.

    Dense models use total parameters. MoE models use active parameters only
    when that value is explicitly known; total parameters remain the fallback.
    The total size and MoE architecture should still be shown separately to
    avoid presenting a sparse model as equivalent to a dense model of that size.
    """
    effective = active_params_billion if moe and active_params_billion is not None else params_billion
    if effective is None:
        return "unknown"
    if effective < 4:
        return "small"
    if effective < 12:
        return "medium"
    if effective <= 35:
        return "large"
    return "frontier"


def infer_model_parameters(model_id: str) -> tuple[Optional[float], Optional[float]]:
    """Infer total and active MoE parameters from a model identifier.

    Only explicit forms such as ``30B-A3B`` are treated as active-parameter
    metadata. A bare ``30B`` supplies total parameters; ambiguous names remain
    unknown rather than receiving an optimistic runtime classification.
    """
    name = str(model_id or "").lower()
    moe_match = re.search(
        r"(?<![a-z0-9])(?P<total>\d+(?:\.\d+)?)b[-_]?a(?P<active>\d+(?:\.\d+)?)b",
        name,
    )
    if moe_match:
        return float(moe_match.group("total")), float(moe_match.group("active"))
    match = re.search(r"(?<![a-z0-9])(\d+(?:\.\d+)?)b(?![a-z0-9])", name)
    if match:
        return float(match.group(1)), None
    return None, None


def _enrich_size_metadata(models: list[ModelInfo]) -> list[ModelInfo]:
    """Fill missing size metadata from explicit model-id notation."""
    for model in models:
        total, active = infer_model_parameters(model.id)
        if model.params_billion is None:
            model.params_billion = total
        if model.active_params_billion is None:
            model.active_params_billion = active
    return models

# Prefix -> (input $/1M, output $/1M). Longest-prefix match is used.
_STATIC_PRICING = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "o1": (15.00, 60.00),
    "o3": (10.00, 40.00),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Anthropic (curated snapshot)
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-opus": (15.00, 75.00),
    "claude-3-sonnet": (3.00, 15.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-2": (8.00, 24.00),
    # Google Gemini
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
    # Groq
    "llama-3.1-8b": (0.05, 0.08),
    "llama-3.1-70b": (0.59, 0.79),
    "llama3-70b": (0.59, 0.79),
    "mixtral-8x7b": (0.27, 0.27),
    "gemma2-9b": (0.20, 0.20),
    # DeepSeek
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-coder": (0.14, 0.28),
    # Mistral
    "mistral-large": (2.00, 6.00),
    "mistral-small": (0.20, 0.60),
    "mistral-7b": (0.25, 0.25),
    "codestral": (0.30, 0.90),
    "open-mistral-7b": (0.25, 0.25),
    # Together
    "meta-llama/Llama-3.3-70B": (0.88, 0.88),
    "meta-llama/Llama-3.1-8B": (0.18, 0.18),
    "Qwen/Qwen2.5-72B": (0.90, 0.90),
    "deepseek-ai/DeepSeek-V3": (1.25, 1.25),
}

# Anthropic curated model list (no public models API).
_ANTHROPIC_STATIC = [
    ("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet", 3.00, 15.00, 200000),
    ("claude-3-5-haiku-20241022", "Claude 3.5 Haiku", 0.80, 4.00, 200000),
    ("claude-3-opus-20240229", "Claude 3 Opus", 15.00, 75.00, 200000),
    ("claude-3-sonnet-20240229", "Claude 3 Sonnet", 3.00, 15.00, 200000),
    ("claude-3-haiku-20240307", "Claude 3 Haiku", 0.25, 1.25, 200000),
    ("claude-2.1", "Claude 2.1", 8.00, 24.00, 200000),
]


def _price_for(model_id: str) -> tuple[Optional[float], Optional[float]]:
    """Longest-prefix match against the static pricing table."""
    best = None
    best_len = -1
    for prefix, (inn, out) in _STATIC_PRICING.items():
        if model_id.startswith(prefix) and len(prefix) > best_len:
            best = (inn, out)
            best_len = len(prefix)
    return best if best else (None, None)


# ---------------------------------------------------------------------------
# Architecture awareness (v2.0.34aa / Section E F4): dense vs MoE detection.
# ---------------------------------------------------------------------------

# Static MoE/architecture hints for well-known model families. Keyed by id prefix;
# matches the same way _price_for does. `moe=True` marks a Mixture-of-Experts
# architecture (sparse experts -> can run with fewer GPU layers than a dense net
# of similar param count). Values are best-effort public knowledge; the live
# source of truth is `ollama show <model>` when available.
_ARCH_HINTS = {
    "qwen3":        {"architecture": "qwen3", "moe": True,  "experts": 128, "active_experts": 8},
    "qwen2.5":      {"architecture": "qwen2.5", "moe": False},
    "qwen2":        {"architecture": "qwen2", "moe": False},
    "deepseek-v3":  {"architecture": "deepseek-v3", "moe": True, "experts": 671, "active_experts": 37},
    "deepseek-r1":  {"architecture": "deepseek-r1", "moe": True, "experts": 671, "active_experts": 37},
    "llama":        {"architecture": "llama", "moe": False},
    "gemma":        {"architecture": "gemma", "moe": False},
    "mistral":      {"architecture": "mistral", "moe": False},
    "mixtral":      {"architecture": "mixtral", "moe": True, "experts": 8, "active_experts": 2},
    "gpt-oss":      {"architecture": "gpt-oss", "moe": True, "experts": 128, "active_experts": 32},
    "nemotron":     {"architecture": "nemotron", "moe": False},
    "nemotron3":    {"architecture": "nemotron3", "moe": False},
    "nemotron-3":   {"architecture": "nemotron3", "moe": False},
    "nemotron-3.5": {"architecture": "nemotron3", "moe": False},
    "nvidia":       {"architecture": "nemotron", "moe": False},
}

# Per-model architecture cache (model id -> (fetched_at, info dict)). TTL-bounded
# like the pricing cache; never raises.
_ARCH_CACHE: dict[str, tuple[float, dict]] = {}
_ARCH_TTL = float(os.getenv("MODEL_ARCH_TTL", "3600"))


def _arch_hint_for(model_id: str) -> dict:
    """Best-effort static architecture hint from the id prefix."""
    best = {}
    best_len = -1
    for prefix, info in _ARCH_HINTS.items():
        if model_id.startswith(prefix) and len(prefix) > best_len:
            best, best_len = info, len(prefix)
    return dict(best)


def get_arch_info(model_id: str, *, live: bool = True) -> dict:
    """Return architecture metadata for `model_id`.

    Returns a dict: {architecture, moe, experts, active_experts, params_billion,
    context}. Sources, in order: in-memory cache -> `ollama show` (live, when
    available) -> static id-prefix hints -> safe empty defaults. NEVER raises;
    a missing/unknown model degrades to conservative defaults (dense, no experts).
    """
    if not model_id:
        return {"architecture": "", "moe": False, "experts": None,
                "active_experts": None, "params_billion": None, "context": None}
    now = time.time()
    cached = _ARCH_CACHE.get(model_id)
    if cached and (now - cached[0]) < _ARCH_TTL:
        return dict(cached[1])

    info: dict = {
        "architecture": "",
        "moe": False,
        "experts": None,
        "active_experts": None,
        "params_billion": None,
        "context": None,
    }
    # 1) static hint (always available, no I/O)
    info.update(_arch_hint_for(model_id))
    # 2) live Ollama detail (best source for experts/params/context)
    if live:
        try:
            from ollama import show as _ollama_show  # local-only, no network for tags
            det = _ollama_show(model_id)
            params = (det.get("details") or {}) if isinstance(det, dict) else {}
            arch = params.get("architecture") or info.get("architecture") or ""
            fam = str(arch).split(":")[0].lower()
            # Re-derive MoE from the live family if it matches a known MoE family.
            hint = _arch_hint_for(fam) or _arch_hint_for(model_id)
            if hint:
                info.update(hint)
            info["architecture"] = arch or info.get("architecture") or ""
            # parameter_count is e.g. "8.0B" / "671B"
            pc = params.get("parameter_count") or ""
            if pc:
                try:
                    info["params_billion"] = float(str(pc).rstrip("BbMmKk").strip()) * (
                        1.0 if "b" in str(pc).lower() else (1e-3 if "k" in str(pc).lower() else 1e-6))
                except ValueError:
                    pass
            # context length lives in the model family block
            fam_block = det.get("model_family") if isinstance(det, dict) else None
            ctx = None
            if isinstance(fam_block, dict):
                ctx = fam_block.get("context_length")
            if ctx:
                try:
                    info["context"] = int(ctx)
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass  # offline / model absent -> static hint only
    _ARCH_CACHE[model_id] = (now, dict(info))
    return info


def is_moe(model_id: str, *, live: bool = True) -> bool:
    """Convenience: True if the model is a Mixture-of-Experts architecture."""
    return bool(get_arch_info(model_id, live=live).get("moe"))


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
_CACHE_FILE = os.path.join(_CACHE_DIR, "models_cache.json")
_CACHE_TTL = 60 * 60 * 24  # 24h

_MEM_CACHE: dict[str, tuple[float, list[ModelInfo]]] = {}


def _cache_key(provider: str, base_url: str) -> str:
    return f"{provider}|{base_url or ''}"


def _load_cache() -> dict:
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(data: dict) -> None:
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Per-provider fetchers
# ---------------------------------------------------------------------------


def _get_json(url: str, headers: dict, timeout: int = 15) -> Optional[dict]:
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _from_openrouter(base_url: str, api_key: str) -> list[ModelInfo]:
    base = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
    data = _get_json(f"{base}/models",
                     {"Authorization": f"Bearer {api_key}"})
    if not data or "data" not in data:
        return []
    out: list[ModelInfo] = []
    for m in data["data"]:
        pid = m.get("id", "")
        if not pid:
            continue
        pr = m.get("pricing") or {}
        try:
            pin = float(pr.get("prompt", "0")) * 1_000_000
            pout = float(pr.get("completion", "0")) * 1_000_000
        except (TypeError, ValueError):
            pin = pout = None
        ctx = m.get("context_length")
        out.append(ModelInfo(
            id=pid,
            label=m.get("name", pid),
            price_in_per_1m=pin,
            price_out_per_1m=pout,
            context=int(ctx) if ctx else None,
            free=bool(pin == 0 and pout == 0),
            vendor=(m.get("architecture", {}) or {}).get("modality", "") or "",
            raw=m,
        ))
    return out


def _from_openai_compatible(base_url: str, api_key: str,
                            vendor: str = "") -> list[ModelInfo]:
    """Works for OpenAI, Gemini (OpenAI-compat base), Groq, DeepSeek, Mistral,
    Together — all expose GET {base}/v1/models returning {data:[{id:...}]}."""
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    # Gemini's OpenAI-compat path is /v1beta/openai/models
    if "generativelanguage.googleapis.com" in base and "/openai" not in base:
        base = base.rstrip("/") + "/models"
        url = f"{base}?key={api_key}"
        data = _get_json(url, {})
        if not data or "models" not in data:
            return []
        out = []
        for m in data["models"]:
            mid = m.get("name", "").split("/")[-1]
            if not mid:
                continue
            inn, outp = _price_for(mid)
            out.append(ModelInfo(id=mid, label=mid,
                                  price_in_per_1m=inn, price_out_per_1m=outp,
                                  vendor=vendor))
        return out
    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = _get_json(url, headers)
    if not data or "data" not in data:
        return []
    out = []
    for m in data["data"]:
        mid = m.get("id", "")
        if not mid:
            continue
        inn, outp = _price_for(mid)
        # NVIDIA's live /v1/models returns the FULL NIM catalog, most of which
        # is NOT free; we have no price table for it, so flag price as unknown
        # (displayed "n/a") rather than falsely labelling everything FREE. The
        # curated _NVIDIA_FREE fallback is what marks models as truly FREE.
        is_free = (vendor != "NVIDIA") and (inn == 0 and outp == 0)
        out.append(ModelInfo(id=mid, label=mid,
                              price_in_per_1m=inn, price_out_per_1m=outp,
                              free=bool(is_free), vendor=vendor))
    return out


def _from_anthropic() -> list[ModelInfo]:
    out = []
    for mid, label, inn, outp, ctx in _ANTHROPIC_STATIC:
        out.append(ModelInfo(id=mid, label=label,
                              price_in_per_1m=inn, price_out_per_1m=outp,
                              context=ctx, vendor="Anthropic",
                              raw={"note": "curated snapshot (no Anthropic models API)"}))


def _nvidia_free_models() -> list[ModelInfo]:
    """Curated NVIDIA NIM free-tier fallback (build.nvidia.com).

    Used when the live /v1/models fetch is unavailable. Marked FREE so the
    Settings dropdown + cost-aware routing treat them as $0. Architecture is
    best-effort-tagged from the id prefix via the static hints (nemotron, etc.).
    """
    out: list[ModelInfo] = []
    for mid in _NVIDIA_FREE:
        hint = _arch_hint_for(mid)  # module-local static prefix hint
        out.append(ModelInfo(
            id=mid, label=mid,
            price_in_per_1m=0.0, price_out_per_1m=0.0,
            free=True, vendor="NVIDIA",
            architecture=hint.get("architecture", ""),
            moe=hint.get("moe", False),
            experts=hint.get("experts"),
            active_experts=hint.get("active_experts"),
            raw={"note": "curated free-tier snapshot (no live fetch)"},
        ))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# provider key -> (fetcher, default base_url, vendor label)
_PROVIDERS = {
    "OPENROUTER": ("openrouter", "https://openrouter.ai/api/v1", "OpenRouter"),
    "OPENAI": ("openai_compat", "https://api.openai.com/v1", "OpenAI"),
    "GEMINI": ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "Gemini"),
    "GROQ": ("openai_compat", "https://api.groq.com/openai/v1", "Groq"),
    "DEEPSEEK": ("openai_compat", "https://api.deepseek.com/v1", "DeepSeek"),
    "MISTRAL": ("openai_compat", "https://api.mistral.ai/v1", "Mistral"),
    "TOGETHER": ("openai_compat", "https://api.together.xyz/v1", "Together"),
    "NVIDIA": ("nvidia", "https://integrate.api.nvidia.com/v1", "NVIDIA"),
    "ANTHROPIC": ("anthropic", "", "Anthropic"),
}

# v2.0.36: NVIDIA NIM free-tier models (build.nvidia.com). Used as the fallback
# when the live /v1/models fetch is unavailable (no key / offline). Marked FREE
# so the Settings dropdown + cost-aware routing treat them as $0. This is a
# curated snapshot — the UI notes it's a snapshot and the live fetch overrides it
# whenever possible. Verified against build.nvidia.com/models (Aug 2026).
_NVIDIA_FREE = [
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3-ultra-235b-a13b",
    "nvidia/nemotron-3-super-49b",
    "nvidia/nemotron-3-nano-9b",
    "nvidia/nemotron-3-mini-4b",
    "nvidia/nemotron-3-nano-omni",
    "nvidia/llama-3.1-nemotron-nano-8b-v1",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nvidia/glm-5.2",
    "nvidia/qwen3-235b-a22b",
    "nvidia/deepseek-r1-0528",
    "nvidia/mistral-nemo-12b-instruct",
    "nvidia/nv-embedqa-e5-v5-8b",
]


def is_fetchable(provider: str) -> bool:
    return provider.upper() in _PROVIDERS


def fetch_models(provider: str, api_key: str, base_url: str = "",
                 use_cache: bool = True) -> list[ModelInfo]:
    """Return models for a provider. Returns [] on any failure (caller falls
    back to editable text). Cached for 24h."""
    provider = provider.upper()
    if provider not in _PROVIDERS:
        return []
    kind, def_base, vendor = _PROVIDERS[provider]
    base = base_url or def_base
    key = _cache_key(provider, base)

    # memory cache
    if use_cache and key in _MEM_CACHE:
        ts, models = _MEM_CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return models
    # disk cache
    if use_cache:
        disk = _load_cache()
        if key in disk:
            entry = disk[key]
            if time.time() - entry.get("ts", 0) < _CACHE_TTL:
                models = _enrich_size_metadata([ModelInfo(**m) for m in entry["models"]])
                _MEM_CACHE[key] = (entry["ts"], models)
                return models

    models: list[ModelInfo] = []
    try:
        if kind == "openrouter":
            models = _from_openrouter(base, api_key)
        elif kind in ("openai_compat", "nvidia", "gemini"):
            models = _from_openai_compatible(base, api_key, vendor)
        elif kind == "anthropic":
            models = _from_anthropic()
    except Exception:
        models = []

    # v2.0.36: NVIDIA free-tier fallback. NVIDIA's /v1/models returns ALL NIM
    # models (many not free). When the live fetch is empty (no key / offline /
    # rate-limited), fall back to the curated free list so the operator still
    # gets a working dropdown of $0 models. Never overrides a real fetch.
    if not models and kind == "nvidia":
        models = _nvidia_free_models()

    if models:
        models = _enrich_size_metadata(models)
        _MEM_CACHE[key] = (time.time(), models)
        disk = _load_cache()
        disk[key] = {"ts": time.time(),
                     "models": [m.__dict__ for m in models]}
        _save_cache(disk)
    return models


def clear_cache(provider: str = "", base_url: str = "") -> None:
    """Drop cached models (e.g. after a manual refresh)."""
    if provider:
        _MEM_CACHE.pop(_cache_key(provider.upper(), base_url or ""), None)
        disk = _load_cache()
        disk.pop(_cache_key(provider.upper(), base_url or ""), None)
        _save_cache(disk)
    else:
        _MEM_CACHE.clear()
        try:
            os.remove(_CACHE_FILE)
        except OSError:
            pass
