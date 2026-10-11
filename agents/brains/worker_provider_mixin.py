"""Provider registry and selection mixin for the legacy worker fa?ade."""

from __future__ import annotations

import os


class WorkerProviderMixin:
    def _chat_model_effective(self) -> str | None:
        chat_model = self._chat_ollama_model_override or os.getenv("OLLAMA_CHAT_MODEL", "").strip() or None
        if not chat_model or not OLLAMA_AVAILABLE:
            return chat_model
        try:
            available = self._ollama_model_names()
        except Exception:
            available = []
        if available and chat_model not in available:
            self.log_signal.emit(f"[LLM] chat model not found: {chat_model}; available={available[:5]}")
            return None
        return chat_model

    def _ollama_model_names(self) -> list[str]:
        if not _REQUESTS_AVAILABLE or not _requests:
            return []
        try:
            r = _requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
            r.raise_for_status()
            data = r.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    # ── LLM Methods ────────────────────────────────────────────────────────────

    # ── v2.0.25 provider registry ─────────────────────────────────────────────
    # v2.0.33: per-provider main/chat role control. Each registry adapter carries
    # a `_role_prefix` (env prefix) + `chat_model`. Role filtering happens in
    # `_build_providers`/`_provider_hint` via `_role_allows`.
    _ROLE_PREFIX = {
        "ollama": "OLLAMA", "anthropic": "ANTHROPIC", "openai": "OPENAI",
        "openrouter": "OPENROUTER", "gemini": "GEMINI", "groq": "GROQ",
        "deepseek": "DEEPSEEK", "mistral": "MISTRAL", "together": "TOGETHER",
        "vllm": "VLLM", "lm-studio": "LM_STUDIO", "koboldcpp": "KOBOLDCPP",
    }

    def _role_allows(self, ad: object, chat: bool) -> bool:
        """Whether this provider may serve the given role (main/chat).

        Legacy `DISABLE_<PREFIX>=true` disables both roles. Otherwise each role is
        independently gated by `<PREFIX>_MAIN_ENABLED` / `<PREFIX>_CHAT_ENABLED`
        (default enabled). If NEITHER is explicitly set, the provider is available
        for both (backward-compatible).
        """
        prefix = self._ROLE_PREFIX.get(ad.name, ad.name.upper())
        from agents.core.configuration import provider_settings
        config_name = "lmstudio" if ad.name == "lm-studio" else ad.name
        if config_name in {
            "ollama", "openai", "openrouter", "anthropic", "gemini",
            "groq", "deepseek", "mistral", "together", "nous", "nvidia",
            "vllm", "lmstudio", "koboldcpp",
        } and not provider_settings(config_name).enabled:
            return False
        main_on = os.getenv(f"{prefix}_MAIN_ENABLED", "").lower()
        chat_on = os.getenv(f"{prefix}_CHAT_ENABLED", "").lower()
        if main_on == "" and chat_on == "":
            # v2.1 dual-brain llama.cpp default: big-brain serves MAIN,
            # small-brain serves CHAT (hardware: 5060 Ti main / 1660S chat).
            if ad.name == "big-brain":
                return not chat
            if ad.name == "small-brain":
                return chat
            return True  # legacy default: enabled for both
        if chat:
            return chat_on != "false"
        return main_on != "false"

    def _build_provider_registry(self) -> list:
        """Return the ordered list of configured provider adapters.

        Built lazily (first call) from adapters/providers + the user's settings/
        env. Order is user-driven (settings.json if present, else a sensible
        default: Ollama first, then cloud). Ollama is default-enabled but never
        forced — it is simply absent if unavailable/disabled. No provider assumes
        another exists.
        """
        if getattr(self, "_provider_registry", None) is not None:
            return self._provider_registry
        try:
            from agents.providers import (
                OllamaAdapter, AnthropicAdapter, OpenAICompatibleAdapter,
            )
        except Exception:
            self._provider_registry = []
            return self._provider_registry
        from agents.core.configuration import all_provider_settings
        configured = all_provider_settings()

        def provider_value(name: str, field: str, default: str = "") -> str:
            value = getattr(configured[name], field, "")
            return value or default

        regs = []
        # Ollama (default-enabled, order 0)
        regs.append(OllamaAdapter(
            name="ollama", order=0,
            chat_model=provider_value("ollama", "chat_model")))
        # Anthropic
        regs.append(AnthropicAdapter(
            name="anthropic", order=50,
            chat_model=provider_value("anthropic", "chat_model")))
        # OpenAI
        regs.append(OpenAICompatibleAdapter(
            name="openai", api_key_env="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1", default_model="gpt-4o-mini",
            disabled_env="DISABLE_OPENAI", order=40,
            chat_model=provider_value("openai", "chat_model")))
        # OpenRouter (OpenAI-compatible)
        regs.append(OpenAICompatibleAdapter(
            name="openrouter", api_key_env="OPENROUTER_API_KEY",
            base_url=provider_value("openrouter", "base_url", "https://openrouter.ai/api/v1"),
            default_model=provider_value("openrouter", "model"),
            disabled_env="DISABLE_OPENROUTER", order=60,
            chat_model=provider_value("openrouter", "chat_model")))
        # Gemini (OpenAI-compatible base_url)
        regs.append(OpenAICompatibleAdapter(
            name="gemini", api_key_env="GEMINI_API_KEY",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            default_model=provider_value("gemini", "model", "gemini-1.5-pro"),
            disabled_env="DISABLE_GEMINI", order=55,
            chat_model=provider_value("gemini", "chat_model")))
        # Groq / DeepSeek / Mistral / Together (OpenAI-compatible)
        regs.append(OpenAICompatibleAdapter(
            name="groq", api_key_env="GROQ_API_KEY",
            base_url=provider_value("groq", "base_url", "https://api.groq.com/openai/v1"),
            default_model=provider_value("groq", "model"), disabled_env="DISABLE_GROQ", order=70,
            chat_model=provider_value("groq", "chat_model")))
        regs.append(OpenAICompatibleAdapter(
            name="deepseek", api_key_env="DEEPSEEK_API_KEY",
            base_url=provider_value("deepseek", "base_url", "https://api.deepseek.com/v1"),
            default_model=provider_value("deepseek", "model", "deepseek-chat"),
            disabled_env="DISABLE_DEEPSEEK", order=70,
            chat_model=provider_value("deepseek", "chat_model")))
        regs.append(OpenAICompatibleAdapter(
            name="mistral", api_key_env="MISTRAL_API_KEY",
            base_url=provider_value("mistral", "base_url", "https://api.mistral.ai/v1"),
            default_model=provider_value("mistral", "model"), disabled_env="DISABLE_MISTRAL", order=70,
            chat_model=provider_value("mistral", "chat_model")))
        regs.append(OpenAICompatibleAdapter(
            name="together", api_key_env="TOGETHER_API_KEY",
            base_url=provider_value("together", "base_url", "https://api.together.xyz/v1"),
            default_model=provider_value("together", "model"), disabled_env="DISABLE_TOGETHER", order=70,
            chat_model=provider_value("together", "chat_model")))
        # Nous Research (OpenAI-compatible). NOTE: the portal no longer serves
        # `hermes-*` ids (they 404); it proxies a third-party catalog instead.
        regs.append(OpenAICompatibleAdapter(
            name="nous", api_key_env="NOUS_API_KEY",
            base_url=provider_value("nous", "base_url", "https://inference-api.nousresearch.com/v1"),
            default_model=provider_value("nous", "model", ""),
            disabled_env="DISABLE_NOUS", order=65,
            chat_model=provider_value("nous", "chat_model")))
        # NVIDIA NIM (OpenAI-compatible hosted API) — v2.0.34ap (H70)
        regs.append(OpenAICompatibleAdapter(
            name="nvidia", api_key_env="NVIDIA_API_KEY",
            base_url=provider_value("nvidia", "base_url", "https://integrate.api.nvidia.com/v1"),
            default_model=provider_value("nvidia", "model"), disabled_env="DISABLE_NVIDIA", order=72,
            chat_model=provider_value("nvidia", "chat_model")))
        # Local OpenAI-compatible servers (vLLM / LM Studio / KoboldCpp)
        if provider_value("vllm", "base_url"):
            regs.append(OpenAICompatibleAdapter(
                name="vllm", api_key_env="VLLM_API_KEY",
                base_url=provider_value("vllm", "base_url"),
                default_model=provider_value("vllm", "model"),
                disabled_env="DISABLE_VLLM", order=30,
                chat_model=provider_value("vllm", "chat_model"), require_api_key=False))
        if provider_value("lmstudio", "base_url"):
            regs.append(OpenAICompatibleAdapter(
                name="lm-studio", api_key_env="LM_STUDIO_API_KEY",
                base_url=provider_value("lmstudio", "base_url"),
                default_model=provider_value("lmstudio", "model"),
                disabled_env="DISABLE_LM_STUDIO", order=30,
                chat_model=provider_value("lmstudio", "chat_model"), require_api_key=False))
        if provider_value("koboldcpp", "base_url"):
            regs.append(OpenAICompatibleAdapter(
                name="koboldcpp", api_key_env="KOBOLDCPP_API_KEY",
                base_url=provider_value("koboldcpp", "base_url"),
                default_model=provider_value("koboldcpp", "model"),
                disabled_env="DISABLE_KOBOLDCPP", order=30,
                chat_model=provider_value("koboldcpp", "chat_model"), require_api_key=False))
        # v2.1: dual-brain llama.cpp (llama-server). Register a role only when
        # the user has explicitly saved a model; a live server's first model is
        # not an implicit selection.
        try:
            from agents.runtime.dual_brain import (BrainRole, DualBrainRuntime,
                                                   PROVIDER_LLAMACPP)
            from agents.providers import LlamaCppAdapter as _LCA
            _rt = DualBrainRuntime.from_env()
            _big = _rt.config(BrainRole.BIG)
            _small = _rt.config(BrainRole.SMALL)
            for _role, _cfg, _env_model, _is_chat in (
                (BrainRole.BIG, _big, "BIG_BRAIN_MODEL", False),
                (BrainRole.SMALL, _small, "SMALL_BRAIN_MODEL", True),
            ):
                if not (_cfg.provider == PROVIDER_LLAMACPP and _cfg.enabled and _cfg.endpoint):
                    continue
                _model = _cfg.model or os.getenv(_env_model, "").strip()
                if not _model:
                    continue
                _name = "big-brain" if _role is BrainRole.BIG else "small-brain"
                regs.append(_LCA(name=_name, base_url=_cfg.endpoint,
                                 default_model=_model, chat_model=_model if _is_chat else "",
                                 disabled_env="DISABLE_BIG_BRAIN" if _role is BrainRole.BIG else "DISABLE_SMALL_BRAIN",
                                 order=-10))
        except Exception:
            pass
        self._provider_registry = regs
        return regs

    def invalidate_provider_registry(self):
        """v2.0.34ak: drop the cached adapter registry so the NEXT llm() call rebuilds
        it from current env. Needed for live model switching (local or cloud) without
        an app restart — adapters bake their model names from env at build time, so a
        changed <PROVIDER>_MODEL / _CHAT_MODEL in .env only takes effect once the
        cache is invalidated.
        """
        self._provider_registry = None

    def _build_providers(self, chat: bool) -> list:
        """Return (name, func, model_key, default_model) tuples for available adapters.

        User-driven order (by adapter.order; Ollama first by default). The chosen
        model per provider: Ollama resolves main/chat from env/override; cloud
        resolves from its default_model (main) / chat_model (chat). func delegates
        to adapter.complete. Providers whose role doesn't match `chat` are skipped
        (v2.0.33 per-provider main/chat control).

        D3 (v2.0.34x): when LLM_COST_AWARE is enabled (default on), billable
        cloud providers are re-ordered cheapest-first by `_price_for(model)
        .price_out_per_1m` so the first *successful* call is the cheapest adequate
        one. Ollama/local is always first (free). Unknown prices sort last (we
        never starve a configured provider — we only reorder, never drop).
        """
        regs = self._build_provider_registry()
        out = []
        # The Settings provider selector is an explicit local-backend choice.
        # Keep cloud providers available for fallback, but do not let an
        # unrelated local adapter (especially Ollama) win by registry order.
        selected_local = os.getenv("ACTIVE_LOCAL_PROVIDER", "").strip().lower()
        selected_local = {
            "auto": "",
            "llama.cpp": "llamacpp",
            "llama-cpp": "llamacpp",
            "lm studio": "lmstudio",
            "lm_studio": "lmstudio",
            "kobold cpp": "koboldcpp",
        }.get(selected_local, selected_local)
        local_adapter_names = {
            "ollama", "vllm", "lm-studio", "koboldcpp",
            "big-brain", "small-brain",
        }
        selected_adapter_names = {
            "ollama": {"ollama"},
            "vllm": {"vllm"},
            "lmstudio": {"lm-studio"},
            "koboldcpp": {"koboldcpp"},
            "llamacpp": {"big-brain", "small-brain"},
        }.get(selected_local)
        if selected_adapter_names and not any(
                ad.name in selected_adapter_names for ad in regs):
            # Keep injected/offline registries usable when the selected backend
            # is not registered; the normal registry will contain it when live.
            selected_adapter_names = None
        for ad in sorted(regs, key=lambda a: a.order):
            if not ad.available():
                continue
            if selected_adapter_names and ad.name in local_adapter_names \
                    and ad.name not in selected_adapter_names:
                continue
            if not self._role_allows(ad, chat):
                continue
            # v2.1.37 (ARCH-ENG-044): the "Auto-failover to cloud" toggle is a
            # real gate. When CLOUD_FAILOVER_ENABLED is off, cloud providers are
            # NOT contacted as a backup — only local providers serve requests.
            # (A provider whose Role is "Disabled" is already excluded above by
            # _role_allows; this is the stricter, toggle-driven backup gate.)
            if ad.name not in local_adapter_names \
                    and not self._cloud_failover_enabled():
                continue
            if ad.name == "ollama":
                model = (self._chat_ollama_model_override if chat else None)                         or (self._chat_model_effective() if chat else None)                         or self._ollama_model_override                         or os.getenv("OLLAMA_MAIN_MODEL", "").strip()                         or os.getenv("OLLAMA_MODEL", "llama3.2")
                fn = lambda m, sys_, u, mt, chat=chat, a=ad, **kw: a.complete(m, sys_, u, mt, chat=chat, **kw)
                # Local/free always stays first; price key None = "free, sort first".
                out.append((0.0, "ollama", fn, "", model))
            elif ad.name in ("big-brain", "small-brain"):
                # v2.1 dual-brain llama.cpp is local/free: price 0.0, sorts first
                # (big-brain before Ollama for main; small-brain for chat).
                model = (ad.chat_model if chat else None) or ad.default_model or ""
                fn = lambda m, sys_, u, mt, chat=chat, a=ad, **kw: a.complete(m, sys_, u, mt, chat=chat, **kw)
                out.append((0.0, ad.name, fn, "", model))
            else:
                model = (ad.chat_model if chat else None) or ad.default_model or ""
                fn = lambda m, sys_, u, mt, chat=chat, a=ad, **kw: a.complete(m, sys_, u, mt, chat=chat, **kw)
                # D3: tag with the out-price (cheapest first). Ollama is 0.0 (free,
                # always first); unknown-price cloud providers sort LAST (inf), so a
                # misconfigured/unknown model never jumps ahead of a priced one.
                price = self._provider_out_price(model)
                sort_key = 0.0 if price == 0.0 else (price if price is not None else float("inf"))
                out.append((sort_key, ad.name, fn, "", model))
        # D3: stable sort by price key (ollama=0.0 first, then cheapest cloud).
        if self._cost_aware_enabled():
            out.sort(key=lambda t: t[0])
        else:
            # Preserve adapter.order grouping (re-extract order not available here,
            # so keep insertion order which already follows adapter.order for non-local).
            pass
        # Return the (name, func, model_key, default_model) shape the rest expects.
        return [(name, fn, mk, dm) for (_price, name, fn, mk, dm) in out]

    def _cost_aware_enabled(self) -> bool:
        return os.getenv("LLM_COST_AWARE", "1").strip().lower() not in ("0", "false", "no", "off")

    def _cloud_failover_enabled(self) -> bool:
        """v2.1.37 (ARCH-ENG-044): whether cloud providers may be used as a
        backup when the local brain fails. Mirrors the GUI toggle
        (gui/widgets/provider_config_widget._cloud_failover_enabled) and reads
        the same CLOUD_FAILOVER_ENABLED key (default on). When off, only local
        providers are contacted."""
        return os.getenv("CLOUD_FAILOVER_ENABLED", "1").strip().lower() not in (
            "0", "false", "no", "off")

    def _provider_out_price(self, model: str):
        """D3: out-token price (USD/1M) for `model`, or None if unknown/free."""
        if not model:
            return None
        try:
            from app.provider_models import _price_for
            inn, outp = _price_for(model)
            return outp
        except Exception:
            return None

    def _provider_hint(self, chat: bool) -> str | None:
        """Primary provider name for this mode (used to pick tokenizer/context hint)."""
        regs = self._build_provider_registry()
        for ad in sorted(regs, key=lambda a: a.order):
            if ad.available() and self._role_allows(ad, chat):
                if ad.name == "ollama":
                    return "ollama"
                return ad.name
        return None



__all__ = ["WorkerProviderMixin"]
