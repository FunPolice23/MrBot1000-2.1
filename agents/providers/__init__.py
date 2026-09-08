"""Provider adapters for MrBot1000 (v2.0.25).

A provider adapter is a small uniform object exposing:
  - name / available()      : identity + readiness (key/endpoint present, SSRF-safe base_url)
  - complete(...)           : call the model, return answer text
  - context_for(model)      : real context window (tokens), never raises

Most cloud/local servers are OpenAI-compatible (/v1/chat/completions), so a
single OpenAICompatibleAdapter covers OpenAI, OpenRouter, Groq, DeepSeek,
Mistral, Together, vLLM, LM Studio, KoboldCpp, and Gemini (via its OpenAI-
compatible base_url). Ollama and Anthropic get dedicated adapters.

Security: credentials come from env (api_key_env name only, never stored);
any user-supplied base_url is validated through InstructionGate._is_safe_fetch_url
(SSRF guard) before the adapter is considered available.
"""
from .context_table import MODEL_CONTEXT_TABLE, lookup_context
from .openai_compatible import OpenAICompatibleAdapter, LlamaCppAdapter
from .ollama_adapter import OllamaAdapter
from .anthropic_adapter import AnthropicAdapter

__all__ = [
    "MODEL_CONTEXT_TABLE",
    "lookup_context",
    "OpenAICompatibleAdapter",
    "LlamaCppAdapter",
    "OllamaAdapter",
    "AnthropicAdapter",
]
