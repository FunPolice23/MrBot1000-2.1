"""Static per-provider/model context-window table (v2.0.25).

Keys are provider names; values are dicts of glob/regex pattern -> context tokens.
Patterns are matched against the model name with fnmatch (case-insensitive). A
literal "*" matches everything for that provider. This is the FIRST layer of
context resolution (fast, offline); live probes (ollama show / /v1/models) and
env overrides refine it. See blueprint .hermes/plans/2026-08-08_*.md §2.
"""
import fnmatch

MODEL_CONTEXT_TABLE = {
    "openai": {
        "gpt-4o*": 128000,
        "gpt-4.1*": 1047576,
        "gpt-5*": 400000,
        "o1*": 200000,
        "o3*": 200000,
        "o4*": 200000,
        "*": 128000,
    },
    "anthropic": {
        "claude*": 200000,
        "claude-3*": 200000,
        "claude-2*": 100000,
        "*": 200000,
    },
    "gemini": {
        "gemini-1.5*": 2000000,
        "gemini-2*": 2000000,
        "gemini-*": 1000000,
        "*": 1000000,
    },
    "openrouter": {"*": 200000},
    "groq": {"*": 131072},
    "deepseek": {"deepseek*": 64000, "*": 64000},
    "mistral": {"*": 128000},
    "together": {"*": 32768},
    "vllm": {"*": 32768},
    "lm-studio": {"*": 32768},
    "koboldcpp": {"*": 8192},
    # Ollama resolves live via `ollama show`; table is only a last-resort floor.
    "ollama": {"*": 128000},
}


def lookup_context(provider: str, model: str, default: int = 128000) -> int:
    """Return the static context window for provider+model, or default.

    Never raises. fnmatch against the provider's pattern table; first match wins
    (most-specific patterns should be listed before "*").
    """
    try:
        table = MODEL_CONTEXT_TABLE.get(provider)
        if not table:
            return default
        m = (model or "").lower()
        for pattern, ctx in table.items():
            if fnmatch.fnmatch(m, pattern.lower()):
                return int(ctx)
    except Exception:
        pass
    return default
