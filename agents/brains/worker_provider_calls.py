"""Legacy provider-call compatibility mixin."""

from __future__ import annotations

import os
import time

from agents.brains.base_worker import (
    ANTHROPIC_AVAILABLE, Anthropic, OLLAMA_AVAILABLE, ollama,
    OPENAI_AVAILABLE, openai, num_gpu_for, split_thinking,
    _normalize_keep_alive,
)


class WorkerProviderCallsMixin:
    def _call_openai(self, model: str, system: str, user: str, max_tokens: int, chat: bool = False) -> str:
        if not OPENAI_AVAILABLE or not openai or not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OpenAI not available")
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
        ).choices[0].message.content

    def _call_anthropic(self, model: str, system: str, user: str, max_tokens: int, chat: bool = False) -> str:
        if not ANTHROPIC_AVAILABLE or not Anthropic or not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("Anthropic not available")
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        return client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": user}
            ],
            system=system,
        ).content[0].text

    def _call_ollama(self, model: str, system: str, user: str, max_tokens: int, chat: bool = False,
                     temperature: float = 0.7, top_p: float = 0.9, **kwargs) -> str:
        if not OLLAMA_AVAILABLE or not ollama:
            raise RuntimeError("Ollama not available or pydantic_core issue")
        try:
            options = {"num_predict": max_tokens, "temperature": temperature, "top_p": top_p}
            # v2.0.34ab (Section E F5) + v2.0.36: resolve GPU layers per role.
            # `num_gpu_for` returns None for AUTO (env unset/"auto"/-1) so we OMIT
            # num_gpu and let Ollama's VRAM-aware scheduler offload what fits —
            # the correct, hardware-agnostic choice (6GB GTX 1660S up to big RTX).
            # A non-None value (explicit int; 0 = CPU-only) is passed through.
            ng = num_gpu_for(model, chat)
            if ng is not None:
                options["num_gpu"] = ng
            else:
                # AUTO: surface the discovered VRAM so the operator can see the
                # program is adapting to their real hardware.
                try:
                    from agents.runtime.llm import vram_gb
                    _vram = vram_gb()
                    self.log_signal.emit(
                        f"[LLM] GPU AUTO: detected ~{_vram}GB VRAM — letting Ollama "
                        f"manage offload (num_gpu omitted)")
                except Exception:
                    pass
            self.log_signal.emit(
                f"[LLM] ollama request model={model} mode={'chat' if chat else 'main'} "
                f"options={options}"
            )
            t0 = time.time()
            # v2.0.24e: hard timeout on the Ollama call. The ollama Python client's
            # chat() does NOT accept a per-call timeout kwarg in this version, so a
            # stalled Ollama (common on a 6GB GPU under concurrent chunked calls)
            # would block the calling thread FOREVER — the heartbeat appears to
            # "stop" with no error. We run the call in a worker thread and wait on
            # it with a timeout; on expiry we raise so the retry/fallback path (or
            # the heartbeat try/except) can recover. This is version-agnostic.
            ollama_timeout = float(os.getenv("OLLAMA_TIMEOUT", 180))
            from concurrent.futures import TimeoutError as _TE
            _fut = self._ollama_executor.submit(
                lambda: ollama.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    options=options,
                    # TTL (not permanent pin): let Ollama evict under VRAM pressure.
                    # Fixed in 2.0.16 (Bug B) — keep_alive=-1 pinned the model in
                    # VRAM and caused RuntimeError on a 6GB GPU. Ollama 0.6.x requires
                    # a unit-suffixed duration ("300s", "5m"); a bare number ("300")
                    # is rejected (status 400 "missing unit in duration"). Normalize:
                    # -1 => forever (int), bare digits => append "s", else as-given.
                    keep_alive=_normalize_keep_alive(os.getenv("OLLAMA_KEEP_ALIVE", "300s")),
                )
            )
            try:
                _raw = _fut.result(timeout=ollama_timeout)
            except _TE:
                _fut.cancel()
                raise RuntimeError(
                    f"Ollama model '{model}' timed out after {ollama_timeout:.0f}s")
            content = _raw['message']['content']
            dt = time.time() - t0
            # v2.0.24: Thinking models emit <think>…</think> blocks. Split the
            # reasoning from the final answer so the answer is never starved and
            # the reasoning can be shown separately in the chat UI / logs.
            thinking, answer = split_thinking(content)
            self.log_signal.emit(
                f"[LLM] ollama response model={model} latency={dt:.2f}s "
                f"chars={len(content)} think_chars={len(thinking)} answer_chars={len(answer)}"
            )
            # Keep the structured parts so callers can access reasoning without
            # re-parsing (e.g. summarizer stores thinking in its DB chat turn).
            self.last_response = {
                "thinking": thinking,
                "answer": answer,
                "raw": content,
                "provider": "ollama",
                "model": model,
                "mode": "chat" if chat else "main",
            }
            # v2.0.24g: RETURN THE ANSWER, not the raw text. Callers (CEO decision
            # parse, chat/summary display) expect the final answer. If the model
            # emitted only thinking (answer empty), fall back to the thinking so
            # callers still receive coherent text instead of an empty string —
            # but the budget fix above makes answer-empty rare. Emitting raw
            # thinking as "the answer" is exactly what produced the
            # "ACTION[JobSearch]: ? No wait per instruction…" garbage decisions.
            if answer:
                return answer
            if thinking:
                # Model thought but produced no answer (e.g. hit num_predict cap).
                # Return the thinking as a last resort so the caller isn't empty.
                return thinking
            return content
        except Exception as e:
            raise RuntimeError(f"Ollama model '{model}' failed: {e}")

    

__all__=["WorkerProviderCallsMixin"]
