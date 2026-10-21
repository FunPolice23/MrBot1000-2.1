"""agents/runtime/brain_contention.py — multi-model-per-device contention model (Phase 0).

PREREQUISITE for exposing a "brains per device" control. A bare count spinner is
a footgun: stacking N llama-servers on one GPU/CPU can OOM the desktop (CUDA
allocator failure -> Windows TDR -> crash/reboot). This module is the pure,
deterministic gate that decides whether the box can host one more brain WITHOUT
starving VRAM, system RAM, or CPU cores — and reports how much headroom is left.

It accounts for the three resources a brain actually consumes (per the
maintenance skill):

  * **VRAM**  — offloaded weights (weights x offload_fraction) + KV cache.
  * **RAM**   — NON-offloaded weight layers stay resident in system RAM and are
                computed on CPU; a CPU-only brain keeps its whole footprint + KV
                in RAM. A GPU brain is NOT RAM-isolated (llama.cpp mmaps the
                GGUF), so its non-offloaded share still counts against RAM.
  * **CPU**   — the sum of ``--threads`` across ALL brains must not exceed the
                physical core count.

Design rules:
  * **Conservative / fail-closed.** When a footprint cannot be established
    (unknown weights), ``can_add_brain`` REJECTS with a reason rather than
    guessing — we never OOM the desktop on an estimate.
  * **Pure.** No Qt, no subprocess, no live probing here. The static estimate
    GATES the add; a live nvidia-smi free-VRAM probe can refine it later
    (see the blueprint's risks section) but never overrides a rejection.
  * **Reuse, don't duplicate.** VRAM math delegates to
    ``agents.providers.gguf_meta.estimate_vram_gb`` (the single source of truth
    already used by the launcher). Weight/KV/layer overrides let callers and
    tests supply a known size without a GGUF on disk.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Leave headroom so the estimate itself, the CUDA context, and OS/driver
# overhead never push a "just fits" placement over the edge.
# Reduced from 1.0 GB to 0.5 GB to allow launches with modest VRAM shortfalls
# (the previous margin was overly conservative for many mid‑range GPUs).
VRAM_SAFETY_MARGIN_GB = 0.5
RAM_SAFETY_MARGIN_GB = 2.0

# ARCH-ENG-220: HOST-SIDE MEMORY A GPU BRAIN STILL COSTS.
#
# `estimate_model_ram_gb` used to add KV to system RAM only when
# `gpu_layers == 0`. With full GPU offload the offload fraction is 1.0, so the
# estimate collapsed to exactly 0.0 -- the model claimed a fully-offloaded GPU
# brain consumes NO system RAM at all.
#
# That hides real memory pressure on exactly the machines that need it most. A
# GPU-resident brain still costs host memory for the CUDA context and driver
# allocations, the staging buffers the backend uses to move tensors across PCIe,
# and host-side allocator slack the CUDA caching allocator does not return.
#
# On a 6 GB card (a GTX 1660 Super, say) the KV cache for a large context is the
# part that does NOT fit alongside the weights. llama.cpp spills it to system
# RAM rather than failing, so a brain can look fine on VRAM and still be one
# context increase away from exhausting the host -- the failure mode that shows
# up as a machine that suddenly cannot launch anything.
#
# So: KV that does not fit in VRAM is charged to system RAM.
HOST_OVERHEAD_GB = 0.6


# ── Footprint estimation ────────────────────────────────────────────────────

def _resolve_footprint(model_path: str, gpu_layers: Optional[int], ctx: int,
                       *, weights_gb: Optional[float] = None,
                       n_layer: Optional[int] = None,
                       kv_gb: Optional[float] = None) -> Optional[Dict[str, float]]:
    """Resolve (weights_gb, kv_gb, n_layer) for a model, or None if unknown.

    Prefers the real GGUF via ``estimate_vram_gb``; falls back to explicit
    overrides (used by tests and by callers that already know the size). Returns
    None only when nothing can be established — the caller then fails closed.
    """
    w = weights_gb
    kv = kv_gb
    nl = n_layer
    if w is None and model_path:
        try:
            from agents.providers.gguf_meta import estimate_vram_gb
            est = estimate_vram_gb(model_path, context=int(ctx or 0))
            w = est.get("weights_gb")
            if kv is None:
                kv = est.get("kv_gb")
            if nl is None:
                nl = est.get("n_layer")
        except Exception:
            w = None
    if w is None:
        return None
    return {
        "weights_gb": float(w),
        "kv_gb": float(kv or 0.0),
        "n_layer": float(nl) if nl else 0.0,
    }


def _offload_fraction(gpu_layers: Optional[int], n_layer: float) -> float:
    """Fraction of weights offloaded to the GPU (0..1). Conservative when unsure.

    * ``gpu_layers == 0``  -> CPU-only, 0.0 offloaded.
    * ``gpu_layers is None`` -> "auto" = wants full offload -> 1.0 (worst case
      for VRAM).
    * explicit ``gpu_layers`` with a known ``n_layer`` -> gpu_layers/n_layer.
    * explicit ``gpu_layers`` but UNKNOWN ``n_layer`` -> assume 1.0 (conservative
      for VRAM: we cannot prove a partial offload fits).
    """
    if gpu_layers == 0:
        return 0.0
    if gpu_layers is None:
        return 1.0
    if n_layer and n_layer > 0:
        return max(0.0, min(1.0, float(gpu_layers) / float(n_layer)))
    return 1.0


def estimate_model_vram_gb(model_path: str, gpu_layers: Optional[int], ctx: int,
                           *, weights_gb: Optional[float] = None,
                           n_layer: Optional[int] = None,
                           kv_gb: Optional[float] = None) -> Optional[float]:
    """VRAM (GB) a brain occupies: offloaded weights + KV cache (KV in VRAM by
    default). Returns None when the footprint cannot be established.
    """
    fp = _resolve_footprint(model_path, gpu_layers, ctx,
                            weights_gb=weights_gb, n_layer=n_layer, kv_gb=kv_gb)
    if fp is None:
        return None
    frac = _offload_fraction(gpu_layers, fp["n_layer"])
    return fp["weights_gb"] * frac + fp["kv_gb"]


def estimate_model_ram_gb(model_path: str, gpu_layers: Optional[int], ctx: int,
                          *, weights_gb: Optional[float] = None,
                          n_layer: Optional[int] = None,
                          kv_gb: Optional[float] = None) -> Optional[float]:
    """System RAM (GB) a brain occupies: NON-offloaded weight layers stay
    resident, and a CPU-only brain also keeps its KV in RAM. A GPU brain is not
    RAM-isolated, so its non-offloaded share still counts. Returns None when the
    footprint cannot be established.
    """
    fp = _resolve_footprint(model_path, gpu_layers, ctx,
                            weights_gb=weights_gb, n_layer=n_layer, kv_gb=kv_gb)
    if fp is None:
        return None
    frac = _offload_fraction(gpu_layers, fp["n_layer"])
    ram = fp["weights_gb"] * (1.0 - frac)
    if gpu_layers == 0:
        # CPU-only: the whole KV cache lives in system RAM too.
        ram += fp["kv_gb"]
    return ram


def estimate_kv_spill_gb(weights_vram_gb: float, kv_gb: Optional[float],
                         device_vram_gb: Optional[float]) -> float:
    """ARCH-ENG-220: KV that cannot fit in VRAM and therefore lands in system RAM.

    Weights are placed first -- they are what the device is for -- so whatever
    VRAM remains after them is what KV competes for. Any excess spills to host
    memory, which is how llama.cpp actually behaves rather than a failure mode.

    A `device_vram_gb` of None means "unknown" and yields NO spill. Callers fail
    closed on unknown totals elsewhere; inventing a spill figure from an unknown
    card size would be a guess presented as a measurement.
    """
    if not kv_gb or kv_gb <= 0:
        return 0.0
    if device_vram_gb is None or device_vram_gb <= 0:
        return 0.0
    room = max(0.0, float(device_vram_gb) - float(weights_vram_gb))
    return max(0.0, float(kv_gb) - room)


def brain_ram_footprint_gb(model_path: str, gpu_layers: Optional[int], ctx: int,
                           device_vram_gb: Optional[float] = None,
                           *, weights_gb: Optional[float] = None,
                           n_layer: Optional[float] = None,
                           kv_gb: Optional[float] = None) -> Optional[float]:
    """ARCH-ENG-220: system RAM a brain occupies, GPU brains included.

    Composes three parts:

      * non-offloaded weight layers resident in host memory
      * KV that spilled because the device could not hold it
      * a flat host overhead per brain (CUDA context, staging buffers)

    `estimate_model_ram_gb` is retained unchanged for callers that want the
    weights-only figure; the gates use this one.
    """
    fp = _resolve_footprint(model_path, gpu_layers, ctx,
                            weights_gb=weights_gb, n_layer=n_layer, kv_gb=kv_gb)
    if fp is None:
        return None
    frac = _offload_fraction(gpu_layers, fp["n_layer"])
    ram = fp["weights_gb"] * (1.0 - frac)
    if gpu_layers == 0:
        # CPU-only: the whole KV cache lives in system RAM too.
        ram += fp["kv_gb"]
    else:
        ram += estimate_kv_spill_gb(fp["weights_gb"] * frac, fp["kv_gb"],
                                    device_vram_gb)
        ram += HOST_OVERHEAD_GB
    return ram


# ── Placement accessors (tolerant of dict or object) ────────────────────────

def _get(placement: Any, key: str, default=None):
    if isinstance(placement, dict):
        return placement.get(key, default)
    return getattr(placement, key, default)


def _placement_on_device(placement: Any, device: Any) -> bool:
    """True if a placement targets *device* (by device_id, else by is_cpu kind)."""
    dev_id = getattr(device, "id", None)
    p_dev = _get(placement, "device_id", "")
    if dev_id and p_dev:
        return str(p_dev) == str(dev_id)
    # No explicit id binding: match CPU pool by kind.
    if getattr(device, "is_cpu", False):
        return bool(_get(placement, "is_cpu", False))
    return False


def _cpu_device(devices: Optional[List[Any]]) -> Optional[Any]:
    for d in (devices or []):
        if getattr(d, "is_cpu", False):
            return d
    return None


# ── Headroom + the add-gate ─────────────────────────────────────────────────

def device_headroom(device: Any, placements: List[Any],
                    *, devices: Optional[List[Any]] = None
                    ) -> Dict[str, Optional[float]]:
    """Free VRAM / RAM / cores after the committed *placements*.

    * VRAM headroom is per-*device* (a GPU's own memory_gb minus the VRAM of
      placements bound to it).
    * RAM and cores are SYSTEM-WIDE: sourced from the CPU-pool device when
      present (its memory_gb = total RAM, cores = logical cores), else from the
      target device, else 0 (unknown -> the gate fails closed).
    """
    is_gpu = getattr(device, "is_gpu", False)
    vram_used = 0.0
    ram_used = 0.0
    cores_used = 0
    for p in placements:
        model = _get(p, "model", "") or _get(p, "model_path", "")
        gl = _get(p, "gpu_layers", None)
        ctx = _get(p, "context", _get(p, "ctx", 8192)) or 8192
        w = _get(p, "weights_gb", None)
        nl = _get(p, "n_layer", None)
        kv = _get(p, "kv_gb", None)
        v = estimate_model_vram_gb(model, gl, ctx, weights_gb=w, n_layer=nl, kv_gb=kv)
        on_this_device = is_gpu and _placement_on_device(p, device)
        # ARCH-ENG-220: pass THIS device's VRAM so KV that does not fit is
        # charged to system RAM. Previously the RAM figure was weights-only for a
        # fully-offloaded brain, so a GPU placement consumed 0 GB of host memory
        # no matter how much KV it spilled.
        r = brain_ram_footprint_gb(
            model, gl, ctx,
            device_vram_gb=(device.memory_gb if on_this_device else None),
            weights_gb=w, n_layer=nl, kv_gb=kv)
        if v is not None and on_this_device:
            vram_used += v
        if r is not None:
            ram_used += r
        cores_used += int(_get(p, "threads", 0) or 0)

    cpu = _cpu_device(devices)
    total_ram = (cpu.memory_gb if cpu is not None
                 else (device.memory_gb if getattr(device, "is_cpu", False) else 0.0))
    total_cores = (cpu.cores if cpu is not None
                   else (device.cores if getattr(device, "is_cpu", False) else 0))

    return {
        "vram_free_gb": (device.memory_gb - vram_used) if is_gpu else None,
        "ram_free_gb": (total_ram - ram_used) if total_ram else None,
        "cores_free": (total_cores - cores_used) if total_cores else None,
    }


def can_add_brain(device: Any, placements: List[Any], candidate: Any,
                  *, devices: Optional[List[Any]] = None
                  ) -> Tuple[bool, str]:
    """Decide whether *candidate* can join *placements* on *device*.

    Returns (True, reason) when it fits, (False, reason) when a resource is
    exhausted — the reason ALWAYS names the exhausted resource (never generic),
    so the GUI can show *why* "add brain" is disabled. Fails closed: an
    unestablishable footprint is a rejection, not a guess.
    """
    model = _get(candidate, "model", "") or _get(candidate, "model_path", "")
    gl = _get(candidate, "gpu_layers", None)
    ctx = _get(candidate, "context", _get(candidate, "ctx", 8192)) or 8192
    threads = int(_get(candidate, "threads", 0) or 0)
    w = _get(candidate, "weights_gb", None)
    nl = _get(candidate, "n_layer", None)
    kv = _get(candidate, "kv_gb", None)

    is_gpu = getattr(device, "is_gpu", False)
    cand_vram = estimate_model_vram_gb(model, gl, ctx, weights_gb=w, n_layer=nl, kv_gb=kv) if is_gpu else 0.0
    # ARCH-ENG-220: this candidate's RAM cost must include the KV that will not
    # fit on THIS device, plus its host overhead. `estimate_model_ram_gb` alone
    # returns 0.0 for a fully-offloaded GPU brain, so asking "does adding a
    # second brain exhaust system RAM?" always answered "no" regardless of how
    # much memory the pair actually needed.
    cand_ram = brain_ram_footprint_gb(
        model, gl, ctx,
        device_vram_gb=(getattr(device, "memory_gb", None) if is_gpu else None),
        weights_gb=w, n_layer=nl, kv_gb=kv)

    # Fail closed on an unknown footprint.
    if cand_ram is None or (is_gpu and cand_vram is None):
        return (False, "cannot establish this model's footprint (unknown size) — "
                       "refusing to add rather than risk an OOM")

    headroom = device_headroom(device, placements, devices=devices)

    # 1) VRAM (GPU target only).
    if is_gpu and headroom["vram_free_gb"] is not None:
        free = headroom["vram_free_gb"]
        if cand_vram is not None and (free - cand_vram) < VRAM_SAFETY_MARGIN_GB:
            return (False, f"VRAM: {getattr(device, 'name', 'GPU')} has ~{free:.1f} GB "
                           f"free, needs ~{cand_vram:.1f} GB (+{VRAM_SAFETY_MARGIN_GB:.0f} GB "
                           f"margin) — lower context, offload fewer layers, or use a smaller model")

    # 2) System RAM (all brains share it).
    if headroom["ram_free_gb"] is not None:
        free = headroom["ram_free_gb"]
        if (free - (cand_ram or 0.0)) < RAM_SAFETY_MARGIN_GB:
            return (False, f"system RAM: ~{free:.1f} GB free after current brains, this "
                           f"brain needs ~{(cand_ram or 0.0):.1f} GB (+{RAM_SAFETY_MARGIN_GB:.0f} GB "
                           f"margin) — stop a brain or pick a smaller model")

    # 3) CPU cores (sum of --threads across ALL brains).
    if headroom["cores_free"] is not None:
        free = headroom["cores_free"]
        if (free - threads) < 0:
            return (False, f"CPU cores: {free} core(s) free, this brain requests "
                           f"{threads} thread(s) — reduce --threads or remove a brain")

    return (True, f"fits: ~{(cand_vram or 0.0):.1f} GB VRAM, "
                  f"~{(cand_ram or 0.0):.1f} GB RAM, {threads} thread(s)")


__all__ = [
    "estimate_model_vram_gb",
    "estimate_model_ram_gb",
    "device_headroom",
    "can_add_brain",
    "VRAM_SAFETY_MARGIN_GB",
    "RAM_SAFETY_MARGIN_GB",
]
