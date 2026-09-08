"""OpenAI-compatible provider adapter (v2.0.25).

One adapter, many providers: OpenAI, OpenRouter, Groq, DeepSeek, Mistral,
Together, vLLM, LM Studio, KoboldCpp, NVIDIA NIM, and Gemini (via its
OpenAI-compatible base_url) all speak /v1/chat/completions. They differ only
in `base_url` and the API key env var.

Security:
- api_key_env holds the ENV VAR NAME, never the secret. The key is read from
  os.getenv(api_key_env) at call time.
- base_url is validated through InstructionGate._is_safe_fetch_url (SSRF guard)
  before the adapter is considered available; a poisoned/loopback base_url makes
  available() return False.

Streaming + reasoning (v2.0.36):
- complete() now STREAMS (stream=True) so reasoning/thinking models (e.g.
  NVIDIA Nemotron with enable_thinking) yield their thinking tokens as they
  arrive, instead of blocking for the whole response. Reasoning content is
  captured from `chunk.choices[0].delta.reasoning_content` and delivered via the
  `on_reasoning` callback (if provided). This mirrors NVIDIA's own Build example
  (`reasoning_content` + `extra_body["chat_template_kwargs"]["enable_thinking"]`).
- `temperature`, `top_p`, and an arbitrary `extra_body` are forwarded so callers
  (and the model-exploration / thinking paths) can pass provider-specific knobs.
  extra_body is merged on top of whatever the caller supplies (never trusted
  input, only our own env-driven dict).
"""

from .context_table import lookup_context


class OpenAICompatibleAdapter:
    def __init__(self, name: str, *, api_key_env: str, base_url: str,
                 default_model: str = "", context_override: int | None = None,
                 disabled_env: str | None = None, order: int = 100,
                 chat_model: str = ""):
        self.name = name
        self.api_key_env = api_key_env
        self.base_url = base_url
        self.default_model = default_model
        self.context_override = context_override
        self.disabled_env = disabled_env
        self.order = order
        self.chat_model = chat_model

    # ── availability / safety ──────────────────────────────────────────────
    def available(self) -> bool:
        # SDK present?
        try:
            import openai  # noqa: F401
        except Exception:
            return False
        # Explicitly disabled?
        if self.disabled_env and os_getenv(self.disabled_env, "false").lower() == "true":
            return False
        # Key present?
        if not os_getenv(self.api_key_env):
            return False
        # SSRF: refuse loopback / metadata / private base_url.
        if not _is_safe_base_url(self.base_url):
            return False
        return True

    # ── completion ─────────────────────────────────────────────────────────
    def complete(self, model: str, system: str, user: str, max_tokens: int,
                 chat: bool = False, *, think: bool = False,
                 temperature: float | None = None, top_p: float | None = None,
                 extra_body: dict | None = None,
                 on_reasoning=None) -> str:
        """Call the model and return the answer text.

        Streams when the openai SDK supports it, so reasoning/thinking models
        emit their thinking tokens as they arrive (delivered via `on_reasoning`).
        Provider-specific knobs (`temperature`, `top_p`, `extra_body`) are
        forwarded; unknown fields are ignored by the SDK.

        Args:
            think: when True, enable the provider's thinking/reasoning mode
                (e.g. NVIDIA Nemotron `enable_thinking`). Only applied for
                providers/adapters that support it (merged into extra_body).
            temperature / top_p: sampling knobs; None => SDK default.
            extra_body: dict merged into the request body (e.g.
                {"chat_template_kwargs": {"enable_thinking": True},
                 "reasoning_budget": 16384}). Our own `think` flag is merged on
                top (and never overrides an explicit caller value).
            on_reasoning: optional callable(str) invoked for each reasoning
                chunk. Used to surface thinking in the Thought panel.
        """
        import openai
        key = os_getenv(self.api_key_env)
        if not key:
            raise RuntimeError(f"{self.name}: {self.api_key_env} not set")
        if not _is_safe_base_url(self.base_url):
            raise RuntimeError(f"{self.name}: unsafe base_url refused: {self.base_url}")

        # Build extra_body, folding in thinking if requested. We never trust
        # caller dict identity (defensive copy).
        body = dict(extra_body or {})
        if think:
            ct = body.setdefault("chat_template_kwargs", {})
            if isinstance(ct, dict) and "enable_thinking" not in ct:
                ct["enable_thinking"] = True

        kwargs: dict = dict(
            model=model or self.default_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            stream=True,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if body:
            kwargs["extra_body"] = body

        client = openai.OpenAI(api_key=key, base_url=self.base_url)
        # Stream: capture reasoning_content (Nemotron/DeepSeek thinking) and
        # accumulate the final answer. Streaming also avoids blocking the caller
        # thread for the full generation on slow reasoning models.
        answer_parts: list[str] = []
        try:
            stream = client.chat.completions.create(**kwargs)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    if on_reasoning is not None:
                        try:
                            on_reasoning(reasoning)
                        except Exception:
                            pass
                    continue
                content = getattr(delta, "content", None)
                if content is not None:
                    answer_parts.append(content)
        except TypeError:
            # Some SDK/server combos reject extra_body/stream at call time; fall
            # back to a plain non-streaming call (no reasoning capture). This
            # keeps the adapter resilient across OpenAI-compatible variants.
            kwargs.pop("stream", None)
            kwargs.pop("extra_body", None)
            resp = client.chat.completions.create(
                model=model or self.default_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""

        return "".join(answer_parts)

    # ── context resolution ─────────────────────────────────────────────────
    def context_for(self, model: str) -> int:
        if self.context_override:
            return max(1024, int(self.context_override))
        return lookup_context(self.name, model or self.default_model, default=128000)


# ── helpers (local, avoid top-level cross-module import at load) ──────────────
def os_getenv(key: str, default: str = "") -> str:
    import os
    return os.getenv(key, default)


def _is_safe_base_url(url: str) -> bool:
    """SSRF guard for provider base_url (v2.1: relaxed for local providers).

    Operator-configured LOCAL/LAN endpoints legitimately run on loopback/private
    addresses (llama.cpp :1234/:1235, LM Studio, vLLM, KoboldCpp on 127.0.0.1).
    This check now ALLOWS loopback + private RFC1918 but still rejects link-local
    metadata (169.254.169.254), multicast, reserved, and non-http schemes.
    """
    from urllib.parse import urlparse
    import ipaddress
    import socket
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        host = (p.hostname or "").strip().lower()
        if not host:
            return False
        if host in ("169.254.169.254", "metadata.google.internal"):
            return False
        try:
            infos = socket.getaddrinfo(host, None)
        except Exception:
            return True  # offline/unresolvable - timeout/error path covers it
        for info in infos:
            ip_str = info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return False
        return True
    except Exception:
        return False


class LlamaCppAdapter(OpenAICompatibleAdapter):
    """Local llama.cpp (llama-server) provider - no API key required.

    Uses the OpenAI-compatible /v1 chat interface. Availability only requires
    the endpoint be set and the role ENABLED; the SDK key is a placeholder.
    Honors <PREFIX>_ENABLED (default true) and DISABLE_<PREFIX>=true.
    """
    def __init__(self, name, *, api_key_env=None, base_url, default_model="",
                 context_override=None, disabled_env=None, order=100, chat_model=""):
        # llama.cpp needs no auth; api_key_env is optional (defaults to a
        # per-provider placeholder that complete() fills with "local").
        super().__init__(
            name=name,
            api_key_env=api_key_env or f"{name.upper().replace('-', '_')}_API_KEY",
            base_url=base_url,
            default_model=default_model,
            context_override=context_override,
            disabled_env=disabled_env,
            order=order,
            chat_model=chat_model,
        )

    def available(self) -> bool:
        try:
            import openai  # noqa: F401
        except Exception:
            return False
        if self.disabled_env and os_getenv(self.disabled_env, "false").lower() == "true":
            return False
        prefix = self.name.upper().replace("-", "_")
        if os_getenv(f"{prefix}_ENABLED", "true").lower() != "true":
            return False
        if not _is_safe_base_url(self.base_url):
            return False
        return bool(self.base_url)

    def complete(self, model, system, user, max_tokens, chat=False, **kwargs):
        # llama.cpp needs no auth; base complete() requires an API key, so set a
        # placeholder for the OpenAI SDK when none is configured.
        if not os_getenv(self.api_key_env):
            import os as _os
            _os.environ[self.api_key_env] = "local"
        return super().complete(model, system, user, max_tokens, chat=chat, **kwargs)
