"""Model-profile detection for MrBot1000.

Auto-detects the model family from GGUF metadata, filename, and server
``/props`` endpoint. Provides the correct configuration for:

- Tool-calling format (OpenAI function calls vs. text-mode parsing)
- Thinking/reasoning mode (``enable_thinking``, ``reasoning_content``)
- System-role handling (``<|im_start|>``, ``<|turn>``, flat prefix)
- Streaming support and chat-template fallback
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

# ---------------------------------------------------------------------------
# Model-family registry
# ---------------------------------------------------------------------------
# Each entry describes how a model family expects to receive messages,
# tools, and thinking/reasoning instructions.

FAMILY_PROFILES: dict[str, dict[str, Any]] = {
    # Qwen 3.8 — thinking delivered in separate reasoning_content field
    "qwen3_8": {
        "id": "qwen3_8",
        "system_format": "im_start",
        "tool_format": "tool_call_xml",
        "thinking": "enable_thinking_param",
        "thinking_tag": "<think>",
        "reasoning_field": "reasoning_content",
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "notes": "Qwen3.8 — reasoning_content field in API, not inline.",
    },
    # Qwen 3.6 / 3 — thinking inline in content as <think>...</think>
    "qwen3": {
        "id": "qwen3",
        "system_format": "im_start",
        "tool_format": "tool_call_xml",
        "thinking": "enable_thinking_param",
        "thinking_tag": "<think>",
        "reasoning_field": None,
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "notes": "Qwen3.6/3 — enable_thinking, thinking inline in content.",
    },
    # Qwen 3.6 — same inline-thinking behavior as qwen3
    "qwen3_6": {
        "id": "qwen3_6",
        "system_format": "im_start",
        "tool_format": "tool_call_xml",
        "thinking": "enable_thinking_param",
        "thinking_tag": "<think>",
        "reasoning_field": None,
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "notes": "Qwen3.6 — enable_thinking, thinking inline in content.",
    },
    "qwen2": {
        "id": "qwen2",
        "system_format": "im_start",
        "tool_format": "tool_call_json",      # <tool_call>{"name":"fn","arguments":{}}</tool_call>
        "thinking": "none",
        "thinking_tag": None,
        "reasoning_field": None,
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "notes": "Qwen2.5 — no thinking mode, JSON tool calls in content.",
    },
    "gemma4": {
        "id": "gemma4",
        "system_format": "gemma_turn",        # <|turn>system\n...\n<turn|>
        "tool_format": "gemma_tool_response",  # <|tool_response>...<tool_response|>
        "thinking": "channel_thought",         # <|channel>thought\n...\n<channel|>
        "thinking_tag": "<|channel>thought",
        "reasoning_field": None,               # inline in content
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "preserve_thinking": True,
        "notes": "Gemma 4 — channel-thought format, turn-based.",
    },
    "gemma": {
        "id": "gemma",
        "system_format": "im_start",
        "tool_format": "none",
        "thinking": "none",
        "thinking_tag": None,
        "reasoning_field": None,
        "supports_function_calling": False,
        "supports_system_role": True,
        "streaming": True,
        "notes": "Gemma 2/3 — no tool calling, system in im_start.",
    },
    "deepseek": {
        "id": "deepseek",
        "system_format": "flat",              # System: ... (prefix-based)
        "tool_format": "deepseek_v3",          # <｜tool▁call▁begin｜>function<｜tool▁sep｜>name\n```json\n{args}\n```<｜tool▁call▁end｜>
        "thinking": "enable_thinking_param",   # extra_body.chat_template_kwargs.enable_thinking
        "thinking_tag": "<think>",
        "reasoning_field": "reasoning_content",
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "notes": "DeepSeek V3 — reasoning_content + enable_thinking.",
    },
    "deepseek_coder": {
        "id": "deepseek_coder",
        "system_format": "flat",
        "tool_format": "hash_instruction",     # ### Instruction:\n...\n### Response:\n...
        "thinking": "none",
        "thinking_tag": None,
        "reasoning_field": None,
        "supports_function_calling": False,
        "supports_system_role": False,
        "streaming": True,
        "notes": "DeepSeek Coder — hash-based instruction/response.",
    },
    "llama": {
        "id": "llama",
        "system_format": "im_start",
        "tool_format": "tool_call_xml",        # same as qwen3 (chatml lineage)
        "thinking": "none",
        "thinking_tag": None,
        "reasoning_field": None,
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "notes": "Llama 3/4 — chatml, no thinking by default.",
    },
    "nemotron": {
        "id": "nemotron",
        "system_format": "im_start",
        "tool_format": "tool_call_xml",
        "thinking": "enable_thinking_param",
        "thinking_tag": "<think>",
        "reasoning_field": "reasoning_content",
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "notes": "NVIDIA Nemotron — reasoning_content + enable_thinking.",
    },
    "nemotron_nano": {
        "id": "nemotron_nano",
        "system_format": "special_10_11",      # <SPECIAL_10>System\n...\n<SPECIAL_11>User\n...
        "tool_format": "nano_toolcall",        # <TOOLCALL>[{"name":"fn","arguments":"..."}]</TOOLCALL>
        "thinking": "slash_think",             # /think or /no_think in user message
        "thinking_tag": "<think>",
        "reasoning_field": None,
        "supports_function_calling": True,
        "supports_system_role": False,
        "streaming": True,
        "notes": "NVIDIA Nemotron Nano — special tokens + slash-think.",
    },
    "mistral": {
        "id": "mistral",
        "system_format": "flat",              # system message folded into first user
        "tool_format": "tool_calls_json",      # [TOOL_CALLS] [{"name":"fn","arguments":{}}]
        "thinking": "none",
        "thinking_tag": None,
        "reasoning_field": None,
        "supports_function_calling": True,
        "supports_system_role": False,         # must flatten system prompt
        "streaming": True,
        "notes": "Mistral — system prompt must be flattened into user.",
    },
    "phi": {
        "id": "phi",
        "system_format": "im_start",
        "tool_format": "tool_call_xml",
        "thinking": "none",
        "thinking_tag": None,
        "reasoning_field": None,
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "notes": "Phi 3/4 — chatml-style.",
    },
    "falcon": {
        "id": "falcon",
        "system_format": "flat",
        "tool_format": "none",
        "thinking": "none",
        "thinking_tag": None,
        "reasoning_field": None,
        "supports_function_calling": False,
        "supports_system_role": False,
        "streaming": True,
        "notes": "Falcon — no tool calling.",
    },
    "starcoder": {
        "id": "starcoder",
        "system_format": "im_start",
        "tool_format": "tool_call_xml",
        "thinking": "none",
        "thinking_tag": None,
        "reasoning_field": None,
        "supports_function_calling": True,
        "supports_system_role": True,
        "streaming": True,
        "notes": "StarCoder — chatml.",
    },
}

# Architecture → family mapping (from GGUF metadata general.architecture)
ARCH_TO_FAMILY: dict[str, str] = {
    "llama": "llama",
    "qwen2": "qwen2",
    "qwen3": "qwen3",
    "qwen3_8": "qwen3_8",
    "qwen3_6": "qwen3_6",
    "gemma": "gemma",
    "gemma2": "gemma",
    "gemma3": "gemma",
    "gemma4": "gemma4",
    "phi3": "phi",
    "phi4": "phi",
    "mistral": "mistral",
    "mixtral": "mistral",
    "falcon": "falcon",
    "starcoder": "starcoder",
    "starcoder2": "starcoder",
    "deepseek": "deepseek",
    "deepseek2": "deepseek",
    "deepseek_v2": "deepseek",
    "deepseek_v3": "deepseek",
    "nemotron": "nemotron",
}

# Filename patterns → family (fallback when metadata is missing)
FILENAME_PATTERNS: list[tuple[str, str]] = [
    ("qwen3.8", "qwen3_8"),
    ("qwen3.6", "qwen3_6"),
    ("qwen3", "qwen3"),
    ("qwen2.5", "qwen2"),
    ("qwen2", "qwen2"),
    ("qwen", "qwen2"),
    ("gemma-4", "gemma4"),
    ("gemma4", "gemma4"),
    ("gemma-3", "gemma"),
    ("gemma-2", "gemma"),
    ("gemma", "gemma"),
    ("deepseek-v3", "deepseek"),
    ("deepseek-v2", "deepseek"),
    ("deepseek-coder", "deepseek_coder"),
    ("deepseek", "deepseek"),
    ("nemotron-nano", "nemotron_nano"),
    ("nemotron", "nemotron"),
    ("ministral", "mistral"),
    ("mistral", "mistral"),
    ("llama-4", "llama"),
    ("llama-3", "llama"),
    ("llama", "llama"),
    ("phi-4", "phi"),
    ("phi-3", "phi"),
    ("phi4", "phi"),
    ("phi3", "phi"),
    ("falcon", "falcon"),
    ("starcoder", "starcoder"),
]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _read_gguf_metadata(model_path: str) -> dict[str, Any]:
    """Read GGUF metadata from a model file (best-effort)."""
    try:
        from agents.gguf_meta import read_metadata
        return read_metadata(model_path) or {}
    except Exception:
        return {}


def detect_family_from_metadata(model_path: str) -> Optional[str]:
    """Detect model family from GGUF tokenizer metadata."""
    meta = _read_gguf_metadata(model_path)
    if not meta:
        return None
    # Check architecture first
    arch = meta.get("general.architecture", "")
    if arch in ARCH_TO_FAMILY:
        return ARCH_TO_FAMILY[arch]
    # Check tokenizer chat template name
    template = meta.get("tokenizer.chat_template", "")
    template_lower = template.lower()
    if "qwen3" in template_lower or "qwen 3" in template_lower:
        # Qwen3.8 uses a distinct template with reasoning_content field
        if "3.8" in template_lower or "3_8" in template_lower:
            return "qwen3_8"
        if "3.6" in template_lower or "3_6" in template_lower:
            return "qwen3_6"
        return "qwen3"
    if "qwen2" in template_lower or "qwen 2" in template_lower:
        return "qwen2"
    if "gemma" in template_lower:
        if "4" in template_lower or "gemma4" in template_lower.replace(" ", ""):
            return "gemma4"
        return "gemma"
    if "deepseek" in template_lower:
        return "deepseek"
    if "nemotron" in template_lower:
        if "nano" in template_lower:
            return "nemotron_nano"
        return "nemotron"
    return None


def detect_family_from_filename(model_path: str) -> Optional[str]:
    """Detect model family from filename patterns."""
    name = os.path.basename(model_path).lower()
    for pattern, family in FILENAME_PATTERNS:
        if pattern in name:
            return family
    return None


def detect_family_from_server_props(base_url: str) -> Optional[str]:
    """Detect model family from llama-server /props endpoint."""
    try:
        base = str(base_url or "").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        host = (urlparse(base).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return None
        with urlopen(f"{base}/props", timeout=1.5) as reply:
            props = json.loads(reply.read().decode("utf-8"))
        model_name = props.get("model_filename", "") or props.get("model", "") or ""
        if not model_name:
            # Try to infer from chat_template string
            tpl = props.get("chat_template", "") or ""
            tpl_lower = tpl.lower()
            if "qwen3" in tpl_lower:
                if "3.8" in tpl_lower or "3_8" in tpl_lower:
                    return "qwen3_8"
                if "3.6" in tpl_lower or "3_6" in tpl_lower:
                    return "qwen3_6"
                return "qwen3"
            if "gemma" in tpl.lower():
                return "gemma4" if "4" in tpl else "gemma"
            return None
        return detect_family_from_filename(model_name) or detect_family_from_metadata(model_name)
    except Exception:
        return None


def detect_model_family(
    model_path: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """Detect model family using all available sources.

    Order of precedence:
    1. Server /props endpoint (if local)
    2. GGUF metadata
    3. Filename patterns
    4. Safe default: "chatml"
    """
    # 1. Server props
    if base_url:
        family = detect_family_from_server_props(base_url)
        if family:
            return family
    # 2. GGUF metadata
    if model_path:
        family = detect_family_from_metadata(model_path)
        if family:
            return family
    # 3. Filename
    if model_path:
        family = detect_family_from_filename(model_path)
        if family:
            return family
    # 4. Default
    return "llama"  # chatml — safest generic default


# ---------------------------------------------------------------------------
# Profile access
# ---------------------------------------------------------------------------

def get_profile(family: str) -> dict[str, Any]:
    """Get a model-family profile by ID, falling back to generic chatml."""
    profile = FAMILY_PROFILES.get(family, FAMILY_PROFILES["llama"]).copy()
    profile["family"] = family
    return profile


def get_model_profile(
    model_path: Optional[str] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None,
) -> dict[str, Any]:
    """Detect family and return its profile."""
    # If model_name is given, also try to detect from it
    family = None
    if model_name:
        family = detect_family_from_filename(model_name)
    if not family:
        family = detect_family_from_metadata(model_path) if model_path else None
    if not family:
        family = detect_family_from_server_props(base_url) if base_url else None
    if not family:
        family = detect_family_from_filename(model_path) if model_path else None
    if not family:
        family = "llama"
    profile = get_profile(family)
    profile["family"] = family
    profile["model_path"] = model_path or ""
    return profile


# ---------------------------------------------------------------------------
# Convenience helpers for the rest of the codebase
# ---------------------------------------------------------------------------

def supports_tool_calling(profile: dict[str, Any]) -> bool:
    """Whether the model supports OpenAI-style function calling."""
    return bool(profile.get("supports_function_calling"))


def supports_thinking(profile: dict[str, Any]) -> bool:
    """Whether the model supports a thinking/reasoning mode."""
    return profile.get("thinking", "none") not in ("none", "")


def wants_enable_thinking(profile: dict[str, Any]) -> bool:
    """Whether to send extra_body={"chat_template_kwargs":{"enable_thinking":True}}."""
    return profile.get("thinking") == "enable_thinking_param"


def needs_flat_system(profile: dict[str, Any]) -> bool:
    """Whether the system prompt must be folded into the first user message."""
    return profile.get("system_format") == "flat"


def extract_thinking_from_content(content: str, profile: dict[str, Any]) -> tuple[str, str]:
    """Extract thinking blocks from content based on family format.

    Returns (thinking_text, visible_text).
    """
    if not content:
        return "", ""
    thinking_kind = profile.get("thinking", "none")
    if thinking_kind == "channel_thought":
        # Gemma 4: <|channel>thought\n...\n<channel|>
        import re
        thinking_parts = re.findall(r"<\|channel>thought\s*(.*?)\s*<\|channel\|>", content, re.DOTALL)
        thinking = "\n".join(thinking_parts)
        visible = re.sub(r"<\|channel>thought\s*.*?\s*<\|channel\|>", "", content, flags=re.DOTALL).strip()
        return thinking.strip(), visible
    # Standard <think>...</think>
    thinking_tag = profile.get("thinking_tag", "<think>")
    end_tag = thinking_tag.replace("<", "</")
    import re
    thinking_parts = re.findall(re.escape(thinking_tag) + r"\s*(.*?)\s*" + re.escape(end_tag), content, re.DOTALL)
    thinking = "\n".join(thinking_parts)
    visible = re.sub(
        re.escape(thinking_tag) + r"\s*.*?\s*" + re.escape(end_tag),
        "", content, flags=re.DOTALL
    ).strip()
    return thinking, visible


def build_extra_body(profile: dict[str, Any], enable_thinking: bool = True) -> dict[str, Any]:
    """Build the extra_body dict for a model-family-compatible request."""
    body: dict[str, Any] = {}
    if wants_enable_thinking(profile) and enable_thinking:
        body["chat_template_kwargs"] = {"enable_thinking": True}
    if profile.get("preserve_thinking"):
        body["preserve_thinking"] = True
    return body


def describe_profile(profile: dict[str, Any]) -> str:
    """Human-readable summary for logging."""
    family = profile.get("family", "unknown")
    tools = "fc" if profile.get("supports_function_calling") else "text"
    thinking = profile.get("thinking", "none")
    system = profile.get("system_format", "?")
    return f"{family}(tools={tools},thinking={thinking},system={system})"
