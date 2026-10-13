"""Short help text for the advanced llama.cpp settings (Phase G, ARCH-ENG-094).

One place for the mouse-hover descriptions of every advanced launch control, so
the Provider Control / per-device settings stay self-documenting without
duplicating strings across widgets. Defaults are unchanged — these are only
tooltips. Keys match the BrainSettingsRow control names.
"""

LLAMA_SETTING_HELP = {
    "ctx": (
        "Context window (tokens). How much conversation/history the model keeps. "
        "Larger = more memory (KV cache grows) and slower; too small = the model "
        "forgets earlier turns. 8k–32k is typical; raise only if you hit "
        "'context length exceeded'."),
    "gpu_layers": (
        "-1 = Auto (offload all layers to the GPU), 0 = CPU/system-RAM only, "
        "N = offload exactly N layers. More GPU layers = faster but more VRAM. "
        "Lower it if the model won't fit your GPU."),
    "threads": (
        "CPU threads for tokenization, sampling, and any non-offloaded layers. "
        "More helps CPU-heavy work but steals cores from the other brain; 2–3 is "
        "plenty when the GPU does the math."),
    "batch": (
        "Prompt-eval batch size (tokens processed per forward pass). Larger = "
        "faster prompt ingestion, more peak memory. 512–2048 is a safe range."),
    "kv_cache": (
        "KV-cache data type. f16 = full precision (most memory, best quality); "
        "q8_0/q4_0 = quantized (much less memory, slightly lower quality). Pick "
        "q8_0 to fit longer contexts in limited VRAM."),
    "split_mode": (
        "How to split the model across multiple GPUs: none (single device), "
        "layer, or row. Leave 'none' unless you are spreading one model over "
        "more than one GPU."),
    "temperature": (
        "Sampling randomness. 0 = deterministic/greedy, higher = more varied. "
        "~0.7 for chat, lower for factual/code tasks."),
    "flash_attn": (
        "FlashAttention. 'on' reduces memory and can speed up long contexts on "
        "supported GPUs. 'auto' lets llama.cpp decide. Off is safest if unsure."),
    "cache_reuse": (
        "Reuse a shared KV prefix across turns (KV shifting). Big win for the "
        "Dialogue tab where every turn re-sends a long shared prompt. 0/off = "
        "recompute each turn."),
    "context_shift": (
        "Roll the context window forward when a conversation exceeds the context "
        "size, instead of erroring mid-thread. On by default now; off to keep "
        "strict windowing."),
    "ctx_checkpoints": (
        "Context checkpoints — snapshot KV state so you can rewind to an earlier "
        "point. Advanced; leave 0 unless you need rewind."),
    "mtp": (
        "Multi-Token Prediction: predicts several tokens per forward pass using "
        "the model's native MTP head, for faster generation. Only available on "
        "models that carry an MTP head (greyed out otherwise). Costs a little "
        "extra VRAM."),
    "spec_draft_n_max": (
        "How many tokens MTP/speculative decoding drafts per pass (default 3). "
        "Higher can be faster but wastes work when drafts are often rejected."),
    "mmproj": (
        "Vision projector (mmproj) file for multimodal models. Leave empty to use "
        "the model's built-in projector, or Auto-detect to pick the matching one."),
}


def tooltip(key: str, default: str = "") -> str:
    """Return the help text for a setting key, or ``default`` if unknown."""
    return LLAMA_SETTING_HELP.get(key, default)


__all__ = ["LLAMA_SETTING_HELP", "tooltip"]
