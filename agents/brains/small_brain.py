"""
Small Brain — Provider adapter for the fast chat model.
Uses llama-server (llama.cpp) via the OpenAI SDK.
Auto-detects downloaded models — no hardcoded model names.
 GPU: optional secondary device, or CPU/system RAM when no secondary GPU exists.
Port: 1235.
Includes program knowledge, memory, and personality.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.knowledge.program_knowledge import (
    get_database, get_personality_engine, get_knowledge_context,
    ProgramKnowledge
)
from agents.knowledge.prompt_assembly import assemble_role_prompt
from agents.cognition.personas import DRIVER, NAVIGATOR


class SmallBrainAdapter:
    """Interface to the fast chat model through the active provider."""
    
    def __init__(self, model=None, base_url=None, config=None):
        # Canonical runtime owns the role→endpoint/model/device contract.
        # Phase 2: a per-slot ``config`` (roster-driven) seeds the adapter; no
        # config -> the legacy env path, byte-identical.
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
        if config is not None:
            _cfg = config
            legacy_url = ""
        else:
            _cfg = DualBrainRuntime.from_env().config(BrainRole.SMALL)
            legacy_url = os.getenv("SMALL_BRAIN_URL") if _cfg.provider == "llamacpp" else ""
        self.base_url = base_url or legacy_url or _cfg.endpoint
        self.provider = _cfg.provider
        self.device = _cfg.device
        self.context_length = _cfg.context
        self.decision_support_only = _cfg.decision_support_only
        self.config = config
        
        # Knowledge and memory
        self.db = get_database()
        self.personality = get_personality_engine()
        self.knowledge = get_knowledge_context()
        
        # A model is never selected implicitly. The user must choose or save one;
        # the dialogue UI may later replace this with the live server model.
        # We intentionally avoid a blocking HTTP call in __init__ so tab
        # construction stays fast even when llama-server is not yet running.
        self.model = model or (config.model if config is not None
                               else os.getenv("SMALL_BRAIN_MODEL", "").strip()) or ""
        self.temperature = float(os.getenv("SMALL_BRAIN_TEMPERATURE", "0.5") or 0.5)
        self.last_tool_trace = []
        self.last_thought_graph = None
        
        # Load system prompt
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "prompts", "small_brain.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r") as f:
                self.base_system_prompt = f.read()
        else:
            self.base_system_prompt = "You are the SMALL BRAIN of MrBot1000."
    
    def _get_client(self):
        """Get OpenAI client for llama-server."""
        import openai
        # Use a longer READ timeout for local inference — when VRAM is
        # contended, a 60s default fires before the model can even finish a
        # single generation, leaving the Dialogue tab stuck on "Generating..."
        # with no error shown to the operator. CONNECT stays short so a stopped
        # llama-server (or a wrong port) fails fast instead of pinning the
        # caller — and the manager thread — for the whole generation budget.
        #
        # v2.1.86 (ARCH-ENG-107): the CONNECT timeout was 8s, but a CPU-hosted
        # brain mid-prompt-eval (a 3-4k-token Dialogue context takes 30s+ at
        # ~125 tok/s on CPU, single request slot) cannot accept a new TCP
        # connection inside 8s — so the NEXT turn's connect timed out and the
        # Dialogue logged "could not reach its model" even though the server was
        # alive and generating. A stopped server still fails fast on connect
        # (refused instantly); only a BUSY server is slow to accept. 30s covers
        # a CPU model's prompt-eval window without meaningfully delaying a truly
        # dead-endpoint failure. Tunable via LOCAL_LLM_CONNECT_TIMEOUT_SECONDS.
        read_timeout = max(5.0, float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "600")))
        connect_timeout = max(2.0, float(
            os.getenv("LOCAL_LLM_CONNECT_TIMEOUT_SECONDS", "30")))
        from agents.providers.openai_compatible import _build_provider_timeout
        from agents.runtime.provider_keys import resolve_provider_api_key
        # Phase 1: local providers keep the "local" sentinel (unchanged); cloud
        # providers resolve a real key from the encrypted vault /
        # PROVIDER_API_KEY_* / SMALL_API_KEY, or "" (fail-closed) so a paid
        # endpoint is never sent the "local" sentinel.
        api_key = resolve_provider_api_key(getattr(self, "provider", "llamacpp"), "SMALL")
        return openai.OpenAI(
            api_key=api_key, base_url=self.base_url,
            timeout=_build_provider_timeout(openai, read=read_timeout,
                                            connect=connect_timeout),
        )

    def _dialogue_protocol(self) -> dict:
        from agents.providers.openai_compatible import (
            get_llama_server_capabilities, resolve_chat_protocol)
        capabilities = get_llama_server_capabilities(self.base_url)
        return resolve_chat_protocol(self.model, capabilities, default_tools=False)
    
    def _get_first_available_model(self) -> str:
        """Auto-detect first available model in llama-server."""
        try:
            client = self._get_client()
            models = client.models.list()
            if models and models.data:
                return models.data[0].id
        except Exception:
            pass
        return "unknown"
    
    def get_available_models(self) -> list:
        """Get list of all downloaded models."""
        try:
            client = self._get_client()
            models = client.models.list()
            if models and models.data:
                return [m.id for m in models.data]
        except Exception:
            pass
        return []
    
    def set_model(self, model_name: str):
        """Switch to a different model."""
        self.model = model_name

    def _start_got_turn(self, prompt: str, pattern=None):
        from agents.brains.brain_got import start_brain_turn
        return start_brain_turn("small_brain", prompt, pattern=pattern)

    def _finish_got_turn(self, turn, response: str, status: str = "completed",
                         branch_candidates=None, evidence_by_id=None) -> str:
        turn.record_tool_trace(self.last_tool_trace)
        # Branching (Tree/Graph-of-Thoughts): see BigBrainAdapter._finish_got_turn.
        if branch_candidates:
            try:
                turn.expand_branches(branch_candidates)
                if turn.is_branching:
                    turn.score_branches(evidence_by_id)
                    turn.select_branch()
            except Exception:
                pass  # branching is advisory; never break the turn
        self.last_thought_graph = turn.finish(response, status)
        return response

    def _hardware_line(self) -> str:
        """One line describing the device this brain runs on (N-brain).

        The device registry is the source of truth, and a label is asserted to
        the model only when detection CONFIRMED a device. Same rule as
        ``BigBrainAdapter._hardware_line`` (ARCH-ENG-115): the config's
        ``gpu_label`` default is a placeholder (``"CPU / System RAM"`` for this
        role), so falling back to it when detection came back empty told the
        brain it runs on hardware that was never verified.
        """
        try:
            from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
            from agents.runtime import device_registry as dr
            cfg = DualBrainRuntime.from_env().config(BrainRole.SMALL)
            # Resolve the live device label from the registry when possible.
            try:
                devices = dr.detect_devices(include_cpu=True)
                dev = None
                if cfg.device_id:
                    dev = next((d for d in devices if d.id == cfg.device_id), None)
                elif cfg.gpu_layers == 0:
                    dev = next((d for d in devices if d.is_cpu), None)
                elif 0 <= cfg.device < 64:
                    dev = next((d for d in devices
                                if d.is_gpu and d.index == cfg.device), None)
                if dev is None:
                    return ""
                label = dev.label()
            except Exception:
                return ""
            if not label:
                return ""
            return (f"You run on {label}. You are the fast, lower-capacity brain; "
                    "keep answers concise and escalate heavy reasoning to the Big Brain.")
        except Exception:
            return ""

    def _build_system_prompt(self, query: str = "") -> str:
        """Build a tiered system prompt for the configured chat model.

        Compact is the default because small models lose instruction adherence
        when identity, capability documentation, memory, and tool rules compete
        in one oversized prompt. Set SMALL_BRAIN_PROMPT_TIER=full for a larger
        model, or =tiny for the smallest available model.
        """
        tier = os.getenv("SMALL_BRAIN_PROMPT_TIER", "compact").strip().lower()
        if tier not in {"tiny", "compact", "full"}:
            tier = "compact"

        if tier == "tiny":
            return self.base_system_prompt + (
                "\n\n# OPERATING CONTRACT\n"
                f"You are {NAVIGATOR.current_name}, the concise chat and triage assistant for MrBot1000.\n"
                "Answer the user's current question directly in 1-3 short paragraphs.\n"
                "Do not invent facts. Say UNKNOWN when evidence is missing.\n"
                "Never spend, submit, sign, share secrets, or claim payment without human approval.\n"
            )

        # Compact retains the parts that shape behavior, not the full program manual.
        extra = (
            "\n\n# ABOUT MRBOT1000\n"
            f"MrBot1000 is a local-first earning assistant. {NAVIGATOR.current_name} handles chat, triage,\n"
            f"status, and lightweight risk checks; {DRIVER.current_name} handles complex planning and review.\n"
            "The human operator approves spending, contracts, credentials, submissions,\n"
            "and irreversible actions. Never invent results or payment.\n"
        )
        if self.decision_support_only:
            extra += (
                "\n\n# CPU DECISION-SUPPORT MODE\n"
                "You are a fast triage and decision-support model assisting Edward Hurst. "
                "Do not act as the primary planner, claim completion, or invent missing evidence. "
                "Return concise options, risks, and a recommended next check for the larger brain.\n"
            )
        # Hardware awareness (N-brain): tell the model which device it runs on so
        # it can reason about its own latency/capacity and not over-promise.
        hw = self._hardware_line()
        if hw:
            extra += f"\n\n# YOUR HARDWARE\n{hw}\n"
        # Full mode is opt-in for models with enough context to benefit from it.
        if tier == "full":
            extra += f"\n\n# ABOUT {ProgramKnowledge.PROGRAM_NAME}"
            extra += ProgramKnowledge.CORE_IDENTITY
            extra += ProgramKnowledge.CORE_CAPABILITIES
            extra += ProgramKnowledge.SAFETY_RULES

        limit = 1200 if tier == "compact" else 4000
        base = assemble_role_prompt(
            self.base_system_prompt, "small_brain", query,
            self.personality, self.knowledge, extra, limit)
        
        # Apply prompting engine: select technique + inject memory
        from agents.knowledge.prompting_engine import adaptive_prompt, select_technique
        # Pass actual model to recommendation engine (not just role)
        recommendation = {
            "recommended_technique": select_technique("dialogue", {"complexity": "low", "urgency": "urgent"}),
            "complexity": "low",
        }
        # Override if model is actually large (e.g. 27B in Small Brain slot)
        from agents.knowledge.prompting_engine import get_brain_recommendation
        recommendation = get_brain_recommendation("small_brain", "dialogue", model_path=self.model, model_name=os.path.basename(self.model))
        return adaptive_prompt("dialogue", base, recommendation)
    
    def chat(self, user_message: str, history: list = None,
             system_prompt: str = None, max_tokens: int = None,
             dialogue_mode: bool = False, stream_progress=None,
             tool_trace_cb=None, images=None, branch_candidates=None,
             evidence_by_id=None) -> str:
        """Handle conversation with tool calling support.
        
        stream_progress: optional callback(str_chunk) invoked for each streamed
        token so the caller can show live generation progress.
        tool_trace_cb: optional callback(tool_event_dict) invoked the moment a
        tool executes (real activity, rendered separately from narration).
        images: optional vision payload (URLs/data-URLs/paths) for multimodal models.
        branch_candidates: optional candidate thoughts for a branching
            (Tree/Graph-of-Thoughts) turn; ignored for direct patterns.
        evidence_by_id: optional {evidence_id: Evidence} used to score branches.
        """
        # Enforcement (Security's design): a cloud-backed brain is $-capped by the
        # daily budget AND call-count-limited, keyed on the RESOLVED provider
        # (self.provider), not the role label — one point covers all four GUI
        # doors (chat_tab:414/450, dialogue_tab:3015/3055) plus any future direct
        # caller, so enforcement can't drift. Local brains are never gated (the
        # 2-brain local path is unchanged). Fails open on infra error, matching
        # worker_llm_mixin. Billable-by-name, never gated on recorded cost.
        try:
            from agents.safety.cost import enforcement_skip_decision, is_local_provider
            from agents.safety.provider_rate_limiter import get_provider_rate_limiter
            _skip, _reason = enforcement_skip_decision(self.provider, self.db)
            if _skip:
                return (f"[{NAVIGATOR.current_name}: {_reason}. Skipping the call "
                        f"to stay within budget.]")
            # Call-count backstop only for BILLABLE providers (local is free and
            # uncapped — no need to count it, and it avoids a per-call DB bump).
            if not is_local_provider(self.provider):
                _rl = get_provider_rate_limiter().acquire(self.provider)
                if not _rl.get("allow", True):
                    return (f"[{NAVIGATOR.current_name}: {_rl.get('reason') or 'rate limited'}. "
                            f"Skipping the call.]")
        except Exception:
            pass
        # GUI is the source of truth for model selection
        if self.model == "unknown" or not self.model:
            return f"[{NAVIGATOR.current_name}: No model selected. Please choose a model in the Providers & GPU tab.]"

        # Detect model family for proper template/tool/thinking handling.
        from agents.providers.model_profile import get_model_profile, build_extra_body
        profile = get_model_profile(model_path=self.model, base_url=self.base_url)
        
        # Build system prompt
        if system_prompt:
            full_system = system_prompt
        else:
            full_system = self._build_system_prompt(user_message)
        
        # Add anti-hallucination rules
        from agents.safety.calling import add_anti_hallucination_rules
        full_system = add_anti_hallucination_rules(full_system)
        # Bound the BASE prompt (identity + memory) to the fast budget FIRST,
        # then append the dialogue-mode tool instructions AFTER budgeting so the
        # exact tool-call format is never truncated away. The small brain was
        # emitting bare `web_read` / `web_read[]` because the tool-format example
        # sat past the 4000-char fast budget and got head-truncated.
        from agents.knowledge.prompting_engine import enforce_prompt_budget
        full_system = enforce_prompt_budget(full_system, {"prompt_mode": "fast"})
        if dialogue_mode:
            full_system += (
                f"\n\nDIALOGUE MODE: Reply as {NAVIGATOR.current_name} in natural language. "
                "You MAY call READ-ONLY tools to gather real evidence — web_search, "
                "web_read, web_check, query_db (read-only SQL), file_read, workshop_* — "
                "and you SHOULD call one when you need current facts instead of guessing. "
                "Calling a tool is how you get evidence; never invent results. "
                "TOOL CALL FORMAT (exact — the call only runs if you write it this way, "
                "with the URL/query inside the quotes): web_read(\"https://example.com/page\") "
                "or web_search(\"your search query\"). Put the real URL or query inside the "
                "quotes. A bare tool name with no quotes does nothing. "
                "Actions that create/register/sign/pay/submit are NOT available here and "
                "must go to the human for approval. If evidence is genuinely missing after "
                "a tool call, say BLOCKED in one or two sentences. "
            )
        
        # v2.1: Use the context length from Providers_GPU settings
        # Reserve ~20% for input, rest for output
        context_max_tokens = int(self.context_length * 0.8)
        
        # Cap at reasonable limits to avoid OOM
        # Scale Dialogue output with the model's configured context. A fixed
        # 2k cap discards useful model-to-model reasoning on larger contexts;
        # an explicit environment value remains available for tighter setups.
        dialogue_cap = int(os.getenv(
            "DIALOGUE_MAX_TOKENS", max(4096, min(32768, self.context_length // 2))))
        if max_tokens is not None:
            dialogue_cap = min(dialogue_cap, max(128, int(max_tokens)))
        request_max_tokens = min(context_max_tokens, dialogue_cap)
        if max_tokens is None:
            request_max_tokens = max(
                request_max_tokens, min(4096, self.context_length // 2))

        if history:
            messages = [{"role": "system", "content": full_system}]
            for msg in history[-10:]:
                messages.append(msg)
            messages.append({"role": "user", "content": user_message})
        else:
            messages = [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_message}
            ]

        # ARCH-ENG-317: a plain dialogue turn is back-and-forth talk, not an
        # orchestration problem. The resolver keyword-matches the whole turn
        # context (the board text contains "options"/"compare"/"evidence"),
        # which labelled casual chat tree/graph/react even though no branching
        # happened — see the big brain's chat() for the full rationale.
        got_pattern = None
        if dialogue_mode and not branch_candidates:
            from agents.cognition.reasoning_modes import (
                PatternSelection, ReasoningPattern)
            got_pattern = PatternSelection(
                ReasoningPattern.DIRECT_DIALOGUE,
                "plain dialogue turn: back-and-forth conversation needs "
                "no branching")
        got_turn = self._start_got_turn(user_message, pattern=got_pattern)
        try:
            client = self._get_client()
            
            # Small Brain uses text-based tool parsing to remain compatible
            # with compact local models and provider templates.
            from agents.safety.calling import chat_with_tools
            protocol = self._dialogue_protocol()
            self.last_tool_trace = []
            # Keep dialogue turns focused on visible conversational output;
            # otherwise reasoning-only generation can exhaust the turn budget.
            model_lower = str(self.model).lower()
            thinking_requested = dialogue_mode and os.getenv(
                "DIALOGUE_ENABLE_THINKING", ""
            ).lower() in {"1", "true", "yes"}
            thinking_model = "thinking" in model_lower
            extra_body = build_extra_body(
                profile,
                enable_thinking=thinking_model or thinking_requested,
            )
            if dialogue_mode and (
                not thinking_requested
                and (
                    profile.get("thinking") in ("enable_thinking_param", "channel_thought")
                    or any(name in model_lower for name in ("qwen", "deepseek", "gemma"))
                )
            ):
                # Disable thinking for dialogue turns so the model spends its
                # budget on a visible persona reply instead of a reasoning
                # channel. Covers Qwen/DeepSeek (enable_thinking_param) AND
                # Gemma 4 (channel_thought), which otherwise rambles its
                # deliberation as the visible answer.
                extra_body = build_extra_body(profile, enable_thinking=False)
                if not extra_body:
                    extra_body = {"chat_template_kwargs": {"enable_thinking": False}}
                else:
                    extra_body.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
            final_extra_body = extra_body if extra_body else None
            
            # Track timing for stats.
            import time as _time
            _t0 = _time.time()
            # ARCH-ENG-109: retry wrapper. Two confirmed Live failure modes for
            # the CPU small brain (LFM2.5): (1) a mid-stream ReadError
            # (WinError 10054 "connection forcibly closed") from llama.cpp
            # resetting the SSE stream — httpx shows the POST returns 200 but
            # the stream dies mid-read; (2) an empty visible answer because the
            # template forces thinking mode and the model emits thinking only.
            # Retry up to 3x: connection errors get a FRESH client (stale
            # socket), empty answers get a plain-text nudge. Read-only dialogue
            # tools are safe to re-run.
            _NUDGE = ("\n\n[SYSTEM: Answer in plain text, 1-3 sentences. State "
                      "your actual decision or finding. Do not think silently.]")
            answer = None
            _last_exc = None
            for _attempt in range(3):
                try:
                    _u = user_message if _attempt == 0 else (user_message + _NUDGE)
                    answer = chat_with_tools(
                        client=client,
                        model=self.model,
                        system_prompt=full_system,
                        user_message=_u,
                        history=history,
                        max_tokens=request_max_tokens,
                        temperature=self.temperature,
                        max_iterations=2 if dialogue_mode else 2,
                        use_function_calling=False,
                        flatten_system_prompt=protocol["flatten_system_prompt"],
                        extra_body=final_extra_body,
                        tool_trace=self.last_tool_trace,
                        stream_progress=stream_progress,
                        on_tool_trace=tool_trace_cb,
                        images=images,
                    )
                    if str(answer or "").strip():
                        break  # real answer
                    # empty -> log + retry with nudge
                    try:
                        from app.failure_log import log_failure
                        log_failure(
                            "small_brain empty answer (attempt %d, model=%s)"
                            % (_attempt, self.model))
                    except Exception:
                        pass
                    answer = None
                except Exception as _ce:
                    _last_exc = _ce
                    try:
                        from app.failure_log import log_failure
                        log_failure(
                            "small_brain attempt %d raised %s: %s"
                            % (_attempt, type(_ce).__name__, str(_ce)[:200]))
                    except Exception:
                        pass
                    answer = None
                    # Fresh client for the next attempt (drop the stale socket).
                    try:
                        client = self._get_client()
                    except Exception:
                        pass
                    continue
            if _last_exc is not None and not str(answer or "").strip():
                raise _last_exc  # let the outer handler format the error
            elapsed = _time.time() - _t0
            
            # Log to DB with real tokens/tps.
            try:
                prompt_chars = len(full_system) + len(user_message)
                resp_chars = len(answer or "")
                prompt_tokens = max(1, prompt_chars // 4)
                completion_tokens = max(1, resp_chars // 4)
                tps = (prompt_tokens + completion_tokens) / elapsed if elapsed > 0 else 0.0
                # ARCH-ENG: a roster can back this brain with a cloud provider
                # (self.provider != llamacpp). Record the REAL cost so a
                # cloud-backed brain counts against the daily budget and
                # CostGuard can skip it — the old hardcoded 0.0 let it bill
                # freely. Local brains stay 0.0 (free).
                try:
                    from agents.safety.cost import estimate_call_cost
                    _call_cost = estimate_call_cost(
                        self.provider, self.model, prompt_tokens, completion_tokens)
                except Exception:
                    _call_cost = 0.0
                self.db.log_llm_call(
                    model=self.model,
                    provider=getattr(self, "last_provider", "small-brain"),
                    trigger="dialogue" if dialogue_mode else "chat",
                    prompt_chars=prompt_chars,
                    response_chars=resp_chars,
                    latency_ms=int(elapsed * 1000),
                    error=None,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    tokens_per_second=tps,
                    cost_usd=_call_cost,
                )
                # ARCH-ENG-243 (BD-01): the typed spend event the Insights
                # spend KPI reads; same cost-basis discipline as big_brain.
                if _call_cost > 0:
                    from agents.core.event_logger import StructuredEventLogger
                    StructuredEventLogger.instance().llm_spend_event(
                        model=self.model,
                        provider=getattr(self, "last_provider", "small-brain"),
                        tokens=prompt_tokens + completion_tokens,
                        est_usd=_call_cost)
            except Exception:
                pass  # Stats logging must never break the response
            if not str(answer or "").strip():
                empty_response = (
                    f"[{NAVIGATOR.current_name} Error: model returned an empty response "
                    f"for '{self.model}' at {self.base_url}. Check the loaded model "
                    "and chat template.]"
                )
                self._finish_got_turn(got_turn, empty_response, "empty")
                return empty_response

            # Log and evolve
            self.db.log_conversation("small_brain", "user", user_message)
            self.db.log_conversation("small_brain", "assistant", answer)
            self.personality.evolve_from_interaction("small_brain", user_message, answer)

            self._finish_got_turn(got_turn, answer,
                                  branch_candidates=branch_candidates,
                                  evidence_by_id=evidence_by_id)
            return answer
        except Exception as e:
            # ARCH-ENG-109: log the REAL exception type + message so an
            # intermittent "could not reach its model" in Live mode is
            # diagnosable. Previously this was swallowed into a user-facing
            # string and never surfaced, so the true cause (connection reset?
            # read timeout? stale pool?) was invisible. Goes to the console /
            # Live Logs.
            try:
                import logging, sys
                _diag = ("small_brain chat failed: %s: %s "
                         "(base_url=%s model=%s)") % (
                             type(e).__name__, str(e)[:300],
                             self.base_url, self.model)
                # print() to stderr: guaranteed visible in the launch console.
                # logging alone goes nowhere in this GUI app (no handler wired),
                # which is why ARCH-ENG-109's log line was invisible.
                print(_diag, file=sys.stderr, flush=True)
                logging.getLogger(__name__).warning(_diag)
                # Shared repo-anchored failure log (survives an invisible console
                # and an unpredictable GUI-launch cwd).
                try:
                    from app.failure_log import log_failure
                    log_failure(_diag)
                except Exception:
                    pass
            except Exception:
                pass
            error_msg = str(e)
            if "not found" in error_msg.lower() or "404" in error_msg:
                available = self.get_available_models()
                if available:
                    return (
                        f"[{NAVIGATOR.current_name}: Selected model '{self.model}' "
                        f"is unavailable. Available models: {', '.join(available)}. "
                        "Choose one explicitly in Providers & GPU.]"
                    )
                return (
                    f"[{NAVIGATOR.current_name}: Selected model '{self.model}' is unavailable "
                    "and no models were reported by the configured server.]"
                )
            error_response = f"[{NAVIGATOR.current_name} Error: {error_msg[:200]}]"
            self._finish_got_turn(got_turn, error_response, "error")
            return error_response
    
    def review(self, plan: str) -> str:
        """Review Big Brain's plan for red flags."""
        return self.chat(
            f"Review this plan for red flags, accuracy, and feasibility:\n\n{plan}\n\n"
            f"Reply with: APPROVED, or list specific concerns."
        )
    
    def should_escalate(self, user_message: str) -> bool:
        """Determine if a message needs Big Brain.

        Keyword-only heuristic. The old version also did a blocking Small Brain
        round-trip ("Does this need deep reasoning?") to decide — that ran on the
        GUI thread in the Chat tab and froze the UI for seconds on every message.
        The keyword list is deliberately broad and covers the complex/analytical
        intents that warrant the Big Brain (v2.0.36y)."""
        complex_keywords = ["analyze", "plan", "strategy", "complex", "deep", "reasoning",
                            "code", "programming", "research", "compare", "evaluate",
                            "explain", "review", "design", "architecture", "debug"]
        return any(kw in user_message.lower() for kw in complex_keywords)
    
    def classify(self, text: str) -> str:
        """Quick classification of an opportunity."""
        return self.chat(
            f"Classify this opportunity (microtask/freelance/airdrop/staking/scam/other):\n\n{text}"
        )
    
    def search_opportunities(self, query: str) -> str:
        """Search for opportunities (placeholder for Discovery Engine integration)."""
        return self.chat(
            f"Search for opportunities matching this query: {query}\n\n"
            f"Return a list of potential opportunities with platform, pay, and time estimate."
        )


_small_brain = None

def get_small_brain():
    """Get or create the Small Brain singleton."""
    global _small_brain
    if _small_brain is None:
        _small_brain = SmallBrainAdapter()
    return _small_brain
