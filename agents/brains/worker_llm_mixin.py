"""LLM retry/fallback orchestration for the legacy worker fa?ade."""

from __future__ import annotations

import os
import time

from agents.brains.base_worker import (
    MAX_TOKENS, _OUTPUT_FRACTION, context_tokens, estimate_tokens,
    fit_prompt_to_ctx, read_think_level, think_budget,
)


class WorkerLLMMixin:
    def llm(self, system: str, user: str, *, chat: bool = False, **kwargs) -> str:
        """Call LLM with retries, multiple providers, and max_tokens."""
        # v2.0.21 P3#6: read MAX_TOKENS live from env (or instance override) so the
        # Settings "Max Tokens" knob applies immediately after Save (no restart).
        # The module-level MAX_TOKENS is only the import-time default.
        if "max_tokens" in kwargs:
            max_tokens = kwargs["max_tokens"]
        elif getattr(self, "_max_tokens", None) is not None:
            max_tokens = self._max_tokens
        else:
            max_tokens = int(os.getenv("MAX_TOKENS", MAX_TOKENS))
        # v2.0.24h: thinking+answer budget is DERIVED from the model's real
        # context window (context_tokens), so it fits whether the model is a tiny
        # 8k local SLM or a 1M-token cloud frontier model. thinking = a level
        # fraction of the output budget; answer = the rest. Everything is capped
        # to the context so we never request more output tokens than the model
        # can hold. An explicit max_tokens kwarg (e.g. planner calls) still wins
        # (and is itself capped to context-100 below); for short direct outputs
        # callers pass think=False so the model spends its whole budget on the
        # answer, not a thinking block.
        think_on = os.getenv("THINKING_ENABLED", "true").strip().lower()
        think_on = think_on not in ("0", "false", "no", "off")
        # Caller may explicitly suppress thinking for a direct short output.
        suppress_think = kwargs.pop("think", None) is False
        ctx = context_tokens(chat)
        # v2.0.25: never overflow the window. Subtract the ACTUAL input size
        # (system+user) and defensively truncate if it cannot fit, so we never
        # hand any provider a prompt longer than its context. headroom is the
        # absolute max output for THIS call.
        provider_hint = self._provider_hint(chat)
        est_input = estimate_tokens(system, provider_hint) + estimate_tokens(user, provider_hint)
        if est_input + 100 > ctx:
            system, user = fit_prompt_to_ctx(system, user, ctx - 100, provider_hint)
            est_input = estimate_tokens(system, provider_hint) + estimate_tokens(user, provider_hint)
            self.log_signal.emit(f"[LLM] prompt truncated to fit ctx={ctx} (est_input={est_input})")
        headroom = max(64, ctx - est_input - 100)
        if think_on and not suppress_think and "max_tokens" not in kwargs:
            level = read_think_level(chat)
            output_budget = max(2048, int(ctx * _OUTPUT_FRACTION))
            think_reserve = think_budget(level, chat)
            answer_reserve = max(512, output_budget - think_reserve)
            max_tokens = min(think_reserve + answer_reserve, headroom)
            self.log_signal.emit(
                f"[Think] level={level} mode={'chat' if chat else 'main'} "
                f"ctx={ctx} num_predict={max_tokens} "
                f"(think~{think_reserve}+answer~{answer_reserve}, {int(_OUTPUT_FRACTION*100)}% of ctx)"
            )
        elif suppress_think:
            # Direct output: make sure the model doesn't waste budget on thinking.
            if "max_tokens" not in kwargs:
                max_tokens = min(int(os.getenv("MAX_TOKENS", MAX_TOKENS)), headroom)
        else:
            # Explicit max_tokens path: still cap it to the model context so we
            # never request more output than the window can hold.
            max_tokens = min(max_tokens, headroom)
            self.log_signal.emit(
                f"[Think] explicit max_tokens={max_tokens} (ctx={ctx})"
            )
        # v2.0.25: build the provider list from the user-configured, available
        # adapter registry (user-driven order; Ollama default-enabled). Each
        # entry is (name, func, model_key, default_model) matching the legacy shape.
        providers = self._build_providers(chat)
        self.log_signal.emit(f"[LLM] providers={[p[0] for p in providers]}")

        # v2.1.47 (ARCH-ENG-046): fail fast when NO provider is enabled/available.
        # Previously, with every local brain disabled and no cloud provider on,
        # the loop still tried a stale adapter and emitted 3× "big-brain failed
        # (Connection error.)" retry spam before returning "LLM unavailable".
        # An empty provider list means the operator has not enabled anything —
        # say so once, clearly, and stop. This is the single gate that prevents
        # "something attempting to run with no provider enabled/running".
        if not providers:
            self.log_signal.emit(
                "[LLM] no provider enabled — enable a brain in Providers & GPU "
                "(or a cloud provider) before running. Skipping this call."
            )
            self.last_provider = "none"
            return "ERROR: no provider enabled"

        # A4: build a daily LLM cost guard (disabled when budget == 0).
        try:
            from agents.safety.cost import CostGuard
            _guard = CostGuard.from_env()
        except Exception:
            _guard = None

        for attempt in range(3):
            for name, func, model_key, default_model in providers:
                # D4 (v2.0.34y): skip a provider whose circuit is open (dead/flaky)
                # so we fail fast to the next provider instead of retrying 500s.
                try:
                    from agents.safety.circuit import get_breaker
                    if get_breaker().is_open(name):
                        self.log_signal.emit(
                            f"[LLM] circuit OPEN for '{name}' — skipping (fail-fast)")
                        continue
                except Exception:
                    pass
                # A4: once the daily cap is exceeded, skip BILLABLE providers so the
                # loop falls through to the free/local one (prevents net-negative
                # earning). Local providers are never skipped. Guarded: a db error
                # must not block calls.
                if _guard is not None and _guard.should_skip(self.db, name):
                    self.log_signal.emit(
                        f"[Budget] daily cap reached — skipping paid provider '{name}', "
                        f"falling back to local")
                    continue
                # Phase F (ARCH-ENG-091): per-provider rate limit + daily call
                # cap. Fail closed for billable providers (a clear skip so we
                # fall through to the next provider); local providers are never
                # $-capped. Guarded: a limiter error must never block calls.
                try:
                    from agents.safety.provider_rate_limiter import (
                        get_provider_rate_limiter)
                    _rl = get_provider_rate_limiter().acquire(
                        name, block=False, timeout=0.0)
                    if not _rl.get("allow"):
                        self.log_signal.emit(
                            f"[RateLimit] skipping '{name}': {_rl.get('reason','')}")
                        continue
                except Exception:
                    pass
                try:
                    model = default_model
                    self.last_model = model
                    mode_label = "chat" if chat else "main"
                    self.log_signal.emit(f"[LLM] trying {name} mode={mode_label} model={model}")
                    t0 = time.time()
                    # v2.0.36: forward the thinking flag so reasoning-capable
                    # providers (NVIDIA Nemotron w/ enable_thinking) emit their
                    # thinking stream. Adapters that don't support it ignore it.
                    resp = func(model, system, user, max_tokens, chat=chat,
                                think=think_on,
                                temperature=self._temperature, top_p=self._top_p)
                    dt_ms = int((time.time() - t0) * 1000)
                    from agents.runtime.performance import telemetry
                    telemetry.record_model_call(
                        dt_ms, ok=bool(resp and str(resp).strip()))
                    # v2.0.21 P1#2: an empty response (chars=0) is a failure, not
                    # a success. The logs showed the chat model returning empty
                    # bodies, which forced the "heuristic fallback (planner
                    # failed)" path. Treat empty as retryable so a later attempt
                    # (or fallback provider) can produce real output.
                    if not resp or not str(resp).strip():
                        telemetry.record_retry()
                        self.log_signal.emit(f"[LLM] {name} returned empty — retrying")
                        try:
                            if self.db is not None:
                                self.db.log_llm_call(
                                    model=model, provider=name,
                                    trigger=getattr(self, "last_trigger", "llm"),
                                    prompt_chars=len(system) + len(user),
                                    response_chars=0, latency_ms=dt_ms,
                                    error="empty response")
                        except Exception:
                            pass
                        # fall through to retry (next provider / attempt)
                        continue
                    # Persist the call so the DB Stats tab can show it (2.0.20e).
                    # v2.1.80 (ARCH-ENG-099): record real token + tps estimates
                    # (chars//4, tokens/elapsed) like the big/small brain paths,
                    # so DB Stats shows token usage instead of all-zero columns.
                    # Guarded: logging must never break the LLM result.
                    try:
                        if self.db is not None:
                            _p_chars = len(system) + len(user)
                            _r_chars = len(resp or "")
                            _p_tok = max(1, _p_chars // 4)
                            _c_tok = max(1, _r_chars // 4)
                            _elapsed_s = dt_ms / 1000.0
                            _tps = ((_p_tok + _c_tok) / _elapsed_s
                                    if _elapsed_s > 0 else 0.0)
                            self.db.log_llm_call(
                                model=model, provider=name,
                                trigger=getattr(self, "last_trigger", "llm"),
                                prompt_chars=_p_chars,
                                response_chars=_r_chars,
                                latency_ms=dt_ms, error=None,
                                prompt_tokens=_p_tok,
                                completion_tokens=_c_tok,
                                tokens_per_second=round(_tps, 2))
                            # ARCH-ENG-243 (BD-01): the typed spend event the
                            # Insights spend KPI reads -- estimated with the
                            # same pricer as the brain adapters, so a
                            # cloud-backed worker bills honestly costed
                            # events (local paths estimate 0.0 and stay
                            # out of the event log; llm_calls keeps them).
                            from agents.safety.cost import estimate_call_cost
                            _call_cost = estimate_call_cost(
                                name, model, _p_tok, _c_tok)
                            if _call_cost > 0:
                                from agents.core.event_logger import (
                                    StructuredEventLogger)
                                StructuredEventLogger.instance().llm_spend_event(
                                    model=model, provider=name,
                                    tokens=_p_tok + _c_tok,
                                    est_usd=_call_cost)
                    except Exception as _log_err:
                        self.log_signal.emit(f"[LLM] stats log skipped: {_log_err}")
                    self.last_provider = name
                    # D4: a successful call closes the circuit for this provider.
                    try:
                        from agents.safety.circuit import get_breaker
                        get_breaker().record_success(name)
                    except Exception:
                        pass
                    return resp
                except Exception as e:
                    from agents.runtime.performance import telemetry
                    telemetry.record_model_call(
                        (time.time() - t0) * 1000, ok=False)
                    telemetry.record_retry()
                    self.log_signal.emit(f"[LLM] {name} failed ({e}), trying next...")
                    # D4: record the failure so a persistently-dead provider opens
                    # its circuit and is skipped instead of retried repeatedly.
                    try:
                        from agents.safety.circuit import get_breaker
                        get_breaker().record_failure(name)
                    except Exception:
                        pass
                    # Log the failed attempt too (error populated).
                    try:
                        if self.db is not None:
                            self.db.log_llm_call(
                                model=default_model, provider=name,
                                trigger=getattr(self, "last_trigger", "llm"),
                                prompt_chars=len(system) + len(user),
                                response_chars=0, latency_ms=0, error=str(e)[:200])
                    except Exception:
                        pass
                    continue

            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            break

        self.last_provider = "error"
        return "ERROR: LLM unavailable"



__all__=["WorkerLLMMixin"]
