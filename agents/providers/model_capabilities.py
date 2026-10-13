"""Model capability detection — Multi-Token Prediction (Phase G, ARCH-ENG-092).

MTP (multi-token prediction) is a speculative-decoding mode in llama.cpp
(``--spec-type draft-mtp``) that predicts several tokens per forward pass using
the model's NATIVE multi-token head. It only works on models that were trained
with — and shipped a GGUF carrying — that head.

Detection is by tensor names (the reliable signal, since the architecture string
alone is not sufficient):
- DeepSeek-V3 / Qwen3.6-35B style: a ``blk.<N>.nextn.*`` block
  (``eh_proj``, ``enorm``, ``hnorm``, ``shared_head_norm``).
- Other trainers (e.g. Xing4.0) expose ``mtp`` / ``shared_head`` tensors.

We fail SAFE: if we cannot confirm an MTP head, ``supported`` is False so the GUI
greys the option out rather than enabling a flag that would no-op or error. This
function never raises and never fabricates a capability.
"""

from __future__ import annotations

import os
from typing import Any, Dict

# Substrings that mark an MTP / next-token-prediction head in the tensor names.
_MTP_MARKERS = ("nextn", "mtp", "shared_head", "eh_proj")

# ARCH-ENG-098: detect_mtp parses the GGUF header (hundreds of thousands of
# tensor/KV skips on a 9B+ model). The GUI status tick used to call it every
# ~4s on the GUI thread, freezing the whole app for seconds. Cache by
# (abspath, mtime_ns, size) so a given file is parsed at most once until it
# actually changes on disk. Callers get a copy so they can't mutate the cache.
_MTP_CACHE: Dict[tuple, Dict[str, Any]] = {}


def _cache_key(model_path: str):
    try:
        st = os.stat(model_path)
        return (os.path.abspath(model_path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (os.path.abspath(model_path), None, None)


def detect_mtp(model_path: str) -> Dict[str, Any]:
    """Return {"supported": bool, "reason": str, "head_tensors": int}.

    ``supported`` is True only when the GGUF carries MTP-head tensors. Any read
    failure or missing head yields supported=False with a plain-language reason.
    """
    result: Dict[str, Any] = {
        "supported": False,
        "reason": "",
        "head_tensors": 0,
    }
    if not model_path:
        result["reason"] = "no model selected"
        return result
    key = _cache_key(model_path)
    cached = _MTP_CACHE.get(key)
    if cached is not None:
        return dict(cached)
    try:
        from agents.providers.gguf_meta import read_tensor_names
        names = read_tensor_names(model_path)
    except Exception as exc:
        result["reason"] = f"could not read model: {exc}"
        return result
    if not names:
        result["reason"] = "not a readable GGUF"
        return result
    head = [n for n in names if any(m in n.lower() for m in _MTP_MARKERS)]
    result["head_tensors"] = len(head)
    if head:
        result["supported"] = True
        result["reason"] = "model carries an MTP (multi-token) head"
    else:
        result["reason"] = "model has no MTP head — MTP unavailable"
    _MTP_CACHE[key] = dict(result)
    return result


def mtp_tooltip(model_path: str) -> str:
    """A short, human sentence for the GUI tooltip / status."""
    info = detect_mtp(model_path)
    if info["supported"]:
        return ("MTP available — predicts multiple tokens per pass for faster "
                "generation on this model. Enable to try it.")
    return info["reason"] or "MTP unavailable for this model."


__all__ = ["detect_mtp", "mtp_tooltip"]
