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


# Value types whose size is fixed regardless of content — safe to seek past.
_FIXED_SIZES = {0: 1, 1: 1, 7: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4,
                10: 8, 11: 8, 12: 8}


def _skip_fast(f, vtype: int) -> None:
    """Advance past one value using seeks for fixed-size scalars and string
    blobs; only recurse for arrays. Avoids reading/decoding array *elements*
    we do not need (the vocab arrays are ~128k–293k entries each)."""
    size = _FIXED_SIZES.get(vtype)
    if size is not None:
        f.seek(size, 1)
        return
    if vtype == 8:  # string
        (sl,) = struct.unpack("<Q", f.read(8))
        f.seek(sl, 1)
        return
    if vtype == 9:  # array
        (atype,) = struct.unpack("<I", f.read(4))
        (alen,) = struct.unpack("<Q", f.read(8))
        elem = _FIXED_SIZES.get(atype)
        if elem is not None:
            f.seek(elem * alen, 1)  # whole fixed-size array in one seek
        else:
            for _ in range(alen):
                _skip_fast(f, atype)
        return
    # Unknown type: fall back to the conservative skipper.
    _skip_val(f, vtype)


# (path, mtime_ns, size) -> (frozenset(wanted), {key: value})
_SCALAR_CACHE: Dict[Any, Any] = {}
# (path, mtime_ns, size) -> header metadata dict (arrays > max_array_len skipped)
_HEADER_CACHE: Dict[Any, Any] = {}


def read_scalar_metadata(path: str, wanted_keys) -> Dict[str, Any]:
    """Read only ``wanted_keys`` from the GGUF header, skipping everything else.

    Unlike :func:`read_metadata`, large array values (the tokenizer vocab /
    merge tables — 128k+ entries) are seeked past rather than materialised, so
    this returns in a few ms instead of hundreds. Only the requested keys are
    decoded; everything else is skipped. Returns a dict with just those keys
    (missing keys are simply absent). Empty on failure — callers must treat a
    missing key as "unknown", never as a hard value.

    Results are cached per (path, mtime, size) so repeated reads of the same
    file (e.g. build_llama_command reading the chat template for both brains,
    or a restart) are effectively free.
    """
    wanted = frozenset(wanted_keys)
    cache_key = None
    try:
        st = os.stat(path)
        cache_key = (path, st.st_mtime_ns, st.st_size)
        cached = _SCALAR_CACHE.get(cache_key)
        if cached is not None and wanted <= cached[0]:
            return {k: v for k, v in cached[1].items() if k in wanted}
    except Exception:
        cache_key = None
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
                if key in wanted:
                    out[key] = _read_val(f, vtype)
                else:
                    _skip_fast(f, vtype)
    except Exception:
        return out
    if cache_key is not None:
        prev = _SCALAR_CACHE.get(cache_key)
        merged_keys = wanted | (prev[0] if prev else frozenset())
        merged = dict(prev[1]) if prev else {}
        merged.update(out)
        _SCALAR_CACHE[cache_key] = (merged_keys, merged)
        # Bound the cache: a handful of models is all the GUI ever cycles.
        if len(_SCALAR_CACHE) > 32:
            _SCALAR_CACHE.pop(next(iter(_SCALAR_CACHE)))
    return out


def read_header_metadata(path: str, max_array_len: int = 4096) -> Dict[str, Any]:
    """Read every SCALAR/STRING K/V pair, and small arrays, skipping big arrays.

    A drop-in for :func:`read_metadata` when the caller only inspects scalar
    fields (architecture, layer/head/embedding counts). The tokenizer vocab and
    merge tables are arrays of 128k–293k entries; skipping them turns a ~300ms
    full read (which decodes every vocab string on the GUI thread) into a few
    ms. Small arrays (per-layer head counts, language lists — a handful of
    entries) are still materialised so ``_first()``-style callers keep working.
    Arrays larger than ``max_array_len`` are skipped (absent from the result) —
    callers that genuinely need a huge array must use read_metadata explicitly.

    Cached per (path, mtime, size) so repeated reads are free.
    """
    try:
        st = os.stat(path)
        ck = (path, st.st_mtime_ns, st.st_size)
        cached = _HEADER_CACHE.get(ck)
        if cached is not None:
            return dict(cached)
    except Exception:
        ck = None
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
                if vtype == 9:  # array — peek length, materialise only if small
                    (atype,) = struct.unpack("<I", f.read(4))
                    (alen,) = struct.unpack("<Q", f.read(8))
                    if alen <= max_array_len:
                        out[key] = [_read_val(f, atype) for _ in range(alen)]
                    else:
                        _skip_array_body(f, atype, alen)
                else:
                    out[key] = _read_val(f, vtype)
    except Exception:
        return out
    if ck is not None:
        _HEADER_CACHE[ck] = dict(out)
        if len(_HEADER_CACHE) > 32:
            _HEADER_CACHE.pop(next(iter(_HEADER_CACHE)))
    return out


def _skip_array_body(f, atype: int, alen: int) -> None:
    """Skip ``alen`` elements of type ``atype`` (header already consumed)."""
    elem = _FIXED_SIZES.get(atype)
    if elem is not None:
        f.seek(elem * alen, 1)
        return
    if atype == 8:
        # Array of strings (the tokenizer vocab/merge tables — 128k–293k
        # entries). Each is u64 length + bytes; lengths are variable so we
        # cannot bulk-seek, but we inline the loop to avoid ~1.3M Python
        # function calls that otherwise dominate the read.
        unpack = struct.unpack
        read = f.read
        seek = f.seek
        for _ in range(alen):
            (sl,) = unpack("<Q", read(8))
            if sl:
                seek(sl, 1)
        return
    for _ in range(alen):
        _skip_fast(f, atype)


def read_tensor_names(path: str) -> set[str]:
    """Read GGUF tensor names without touching tensor data."""
    names: set[str] = set()
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return names
            f.read(4)
            (tensor_count,) = struct.unpack("<Q", f.read(8))
            (n_kv,) = struct.unpack("<Q", f.read(8))
            for _ in range(n_kv):
                (key_length,) = struct.unpack("<Q", f.read(8))
                f.seek(key_length, 1)
                (value_type,) = struct.unpack("<I", f.read(4))
                _skip_val(f, value_type)
            for _ in range(tensor_count):
                (name_length,) = struct.unpack("<Q", f.read(8))
                names.add(f.read(name_length).decode("utf-8", "replace"))
                (dimensions,) = struct.unpack("<I", f.read(4))
                f.seek(8 * dimensions + 4 + 8, 1)
    except (OSError, struct.error, UnicodeError, ValueError):
        return set()
    return names


def validate_model(path: str) -> list[str]:
    """Return deterministic GGUF compatibility errors before server startup."""
    metadata = read_header_metadata(path)
    if not metadata:
        return ["file is not a readable GGUF"]
    if metadata.get("general.architecture") == "qwen35":
        tensor_names = read_tensor_names(path)
        required = "blk.16.attn_norm.weight"
        if tensor_names and required not in tensor_names:
            return [f"qwen35 GGUF is missing required tensor {required!r}"]
    return []


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
    meta = read_header_metadata(path)
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
