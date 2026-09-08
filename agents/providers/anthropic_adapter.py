"""Anthropic provider adapter (v2.0.25).

Self-contained complete() mirroring the former WorkerAgent._call_anthropic.
context_for resolves via the static table (Claude 200k).
"""
import os
from .context_table import lookup_context


class AnthropicAdapter:
    def __init__(self, name: str = "anthropic",
                 *, api_key_env: str = "ANTHROPIC_API_KEY",
                 default_model: str = "claude-3-5-sonnet-20241022",
                 disabled_env: str = "DISABLE_ANTHROPIC", order: int = 50,
                 chat_model: str = ""):
        self.name = name
        self.api_key_env = api_key_env
        self.default_model = default_model
        self.disabled_env = disabled_env
        self.order = order
        self.chat_model = chat_model

    def available(self) -> bool:
        try:
            import anthropic  # noqa: F401
        except Exception:
            return False
        if os.getenv(self.disabled_env or "DISABLE_ANTHROPIC", "false").lower() == "true":
            return False
        return bool(os.getenv(self.api_key_env))

    def complete(self, model: str, system: str, user: str, max_tokens: int,
                 chat: bool = False, **kwargs) -> str:
        import anthropic
        key = os.getenv(self.api_key_env)
        if not key:
            raise RuntimeError(f"anthropic: {self.api_key_env} not set")
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=model or self.default_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
            system=system,
        )
        return resp.content[0].text

    def context_for(self, model: str) -> int:
        return lookup_context("anthropic", model or self.default_model, default=200000)
