"""
agents/gguf_meta.py — dependency-light GGUF metadata reader (stdlib only).

Used to ESTIMATE a .gguf model's total VRAM footprint (weights + KV cache at a
given context) so the Providers & GPU panel can warn when a model is unlikely to
fit its target GPU and would spill to system RAM (v2.0.37c).

Design rules
------------
- Pure stdlib (struct). Importable anywhere without pulling in Qt/openai.
- Read-only; never mutates the file.
- Best-effort: if the layout is unexpected, returns fields it could read and
  ``complete=False`` rather than raising. The caller must treat the estimate as
  a heuristic (a warning threshold), never a hard gate.

KV-cache estimate
-----------------
llama.cpp stores K and V per attention layer. For kv cache type f16, bytes per
token ~= 2 * n_layer * n_kv_head * head_dim * 2. Multiplied by context length.
We derive n_layer / n_kv_head / head_dim from GGUF metadata where present.
"""

from __future__ import annotations

import os
import struct
from typing import Any, Dict, Optional


def _read_val(f, vtype: int):
    if vtype in (0, 1, 7):      # uint8 / int8 / bool
        return struct.unpack("<B", f.read(1))[0]
    if vtype in (2, 3):         # uint16 / int16
        return struct.unpack("<h", f.read(2))[0]
    if vtype in (4, 5):         # uint32 / int32
        return struct.unpack("<i", f.read(4))[0]
    if vtype == 6:              # float32
        return struct.unpack("<f", f.read(4))[0]
    if vtype == 10:             # uint64
        return struct.unpack("<Q", f.read(8))[0]
    if vtype == 11:             # int64
        return struct.unpack("<q", f.read(8))[0]
    if vtype == 12:             # float64
        return struct.unpack("<d", f.read(8))[0]
    if vtype == 8:              # string
        (sl,) = struct.unpack("<Q", f.read(8))
        return f.read(sl).decode("utf-8", "replace")
    if vtype == 9:              # array
        (atype,) = struct.unpack("<I", f.read(4))
        (alen,) = struct.unpack("<Q", f.read(8))
        return [_read_val(f, atype) for _ in range(alen)]
    return None


def _skip_val(f, vtype: int) -> None:
    """Advance the file pointer past one metadata value (used when we only need
    a few keys but must walk all preceding K/V pairs)."""
    if vtype in (0, 1, 7):
        f.read(1)
    elif vtype in (2, 3):
        f.read(2)
    elif vtype in (4, 5, 6):
        f.read(4)
    elif vtype in (10, 11, 12):
        f.read(8)
    elif vtype == 8:
        (sl,) = struct.unpack("<Q", f.read(8))
        f.read(sl)
    elif vtype == 9:
        (atype,) = struct.unpack("<I", f.read(4))
        (alen,) = struct.unpack("<Q", f.read(8))
        for _ in range(alen):
            _skip_val(f, atype)
    # unknown types are ignored (best-effort)


def _first(x):
    """Scalar, or list -> max (MoE stores per-layer kv heads as arrays; the KV
    cache must cover the widest attention layer)."""
    if isinstance(x, (list, tuple)):
        return max(x) if x else 0
    return x or 0


def read_metadata(path: str) -> Dict[str, Any]:
    """Return the model's GGUF metadata K/V as a dict. Empty on failure."""
    out: Dict[str, Any] = {}
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return {}
            f.read(4)  # version u32
            f.read(8)  # tensor_count u64
            (n_kv,) = struct.unpack("<Q", f.read(8))
            for _ in range(n_kv):
                (kl,) = struct.unpack("<Q", f.read(8))
                key = f.read(kl).decode("utf-8", "replace")
                (vtype,) = struct.unpack("<I", f.read(4))
                out[key] = _read_val(f, vtype)
    except Exception:
        return {}
    return out


def estimate_vram_gb(path: str, context: int = 8192,
                     kv_type_bytes: int = 2) -> Dict[str, Any]:
    """Estimate a model's VRAM footprint.

    Returns dict: weights_gb, kv_gb, total_gb, complete (bool). ``complete`` is
    False when metadata was insufficient (n_layer/kv_head/head_dim missing) — the
    caller should then fall back to weights-only + a warning buffer.
    """
    result: Dict[str, Any] = {
        "path": path,
        "weights_gb": round(os.path.getsize(path) / 1e9, 2),
        "kv_gb": 0.0,
        "total_gb": None,
        "complete": False,
        "arch": None,
        "n_layer": None,
        "kv_head": None,
        "head_dim": None,
        "embedding": None,
    }
    meta = read_metadata(path)
    if not meta:
        return result

    result["arch"] = meta.get("general.architecture")

    # Find n_layer / kv_head / head_dim / embedding across arch-specific keys.
    n_layer = None; kv_head = None; head_dim = None; embedding = None
    for k, v in meta.items():
        if k.endswith(".block_count") and n_layer is None:
            n_layer = _first(v)
        elif k.endswith(".attention.head_count_kv") and kv_head is None:
            kv_head = _first(v)
        elif k.endswith(".attention.head_count") and head_dim is None:
            # stored here only if no separate head_dim key; we derive head_dim below
            pass
        elif k.endswith(".attention.key_length") and head_dim is None:
            head_dim = _first(v)
        elif k.endswith(".embedding_length") and embedding is None:
            embedding = _first(v)
        elif k == "llama.attention.head_count" and "head_count_kv" not in meta:
            if kv_head is None:
                kv_head = _first(v)
        elif k.endswith(".attention.head_count"):
            # capture head_count as a fallback for kv_head and head_dim
            hc = _first(v)
            if kv_head is None and hc:
                kv_head = hc

    # Separate pass: head_dim derivation from head_count + embedding.
    for k, v in meta.items():
        if k.endswith(".attention.head_count") and head_dim is None:
            hc = _first(v)
            if embedding and hc:
                head_dim = embedding // hc

    if n_layer is None:
        # No layer count found -> cannot estimate KV.
        result["total_gb"] = round(result["weights_gb"] * 1.05 + 0.3, 2)
        return result
    if not kv_head or not head_dim:
        result["total_gb"] = round(result["weights_gb"] * 1.05 + 0.3, 2)
        return result

    kv_bytes = 2 * n_layer * kv_head * head_dim * kv_type_bytes * context
    result["n_layer"] = n_layer
    result["kv_head"] = kv_head
    result["head_dim"] = head_dim
    result["embedding"] = embedding
    result["kv_gb"] = round(kv_bytes / 1e9, 2)
    result["total_gb"] = round(result["weights_gb"] + result["kv_gb"], 2)
    result["complete"] = True
    return result


if __name__ == "__main__":
    import glob
    for f in sorted(glob.glob(r"D:/LMStudio/models/**/*.gguf", recursive=True)):
        b = os.path.basename(f)
        if b.lower().startswith("mmproj"):
            continue
        e = estimate_vram_gb(f, context=8192)
        print(f"W={e['weights_gb']:6.2f} KV@8k={e['kv_gb']:6.2f} "
              f"total={e['total_gb']:6.2f} complete={e['complete']} "
              f"arch={e['arch']} L={e['n_layer']} kvh={e['kv_head']} hd={e['head_dim']}  {b}")
