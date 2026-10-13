"""
Big Brain — Provider adapter for the main reasoning model.
Uses llama-server (llama.cpp) via the OpenAI SDK.
Auto-detects downloaded models — no hardcoded model names.
GPU: 5060 Ti (device 0) with RAM overflow.
Port: 1234.

Features:
- Tool calling with safety gate
- Task-specific specialization prompts
- Dynamic communication with Small Brain
- Memory + personality + program knowledge
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.knowledge.program_knowledge import (
    get_database, get_personality_engine, get_knowledge_context,
    ProgramKnowledge
)
from agents.knowledge.prompt_assembly import assemble_role_prompt
from agents.earning.router import classify_task, get_tools_for_task, get_specialization_prompt
from agents.safety.gate import SafetyGate, SafetyDecision
from agents.cognition.personas import DRIVER


class BigBrainAdapter:
    """Interface to the main reasoning model via llama-server on 5060 Ti."""
    
    def __init__(self, model=None, base_url=None, safety_gate: SafetyGate | None = None):
        # Canonical runtime owns the role→endpoint/model/device contract. The
        # adapter inherits its defaults from the runtime; an explicit arg or env
        # still wins, but there is one source of truth.
        from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
        _cfg = DualBrainRuntime.from_env().config(BrainRole.BIG)
        legacy_url = os.getenv("BIG_BRAIN_URL") if _cfg.provider == "llamacpp" else ""
        self.base_url = base_url or legacy_url or _cfg.endpoint
        self.device = _cfg.device
        self.context_length = _cfg.context
        
        # Knowledge and memory
        self.db = get_database()
        self.personality = get_personality_engine()
        self.knowledge = get_knowledge_context()
        
        # Prompting engine — remembers what works per task type
        from agents.knowledge.prompting_engine import record_successful_pattern, get_brain_recommendation
        self._prompting_engine = {
            "record": record_successful_pattern,
            "recommend": get_brain_recommendation,
        }
        
        # Safety gate
        self.safety_gate = safety_gate or SafetyGate()
        
        # A model is never selected implicitly. The user must choose or save one;
        # the dialogue UI may later replace this with the live server model.
        # We intentionally avoid a blocking HTTP call in __init__ so tab
        # construction stays fast even when llama-server is not yet running.
        self.model = model or os.getenv("BIG_BRAIN_MODEL", "").strip() or ""
        self.temperature = float(os.getenv("BIG_BRAIN_TEMPERATURE", "0.5") or 0.5)
        self.last_tool_trace = []
        self.last_thought_graph = None
        
        # Load system prompt
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "prompts", "big_brain.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                self.base_system_prompt = f.read()
        else:
            self.base_system_prompt = "You are the BIG BRAIN of MrBot1000."
    
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
        # v2.1.86 (ARCH-ENG-107): raised the default connect window to 30s (was
        # 8s) and pass it through — a busy brain mid-generation cannot accept a
        # new TCP connection inside 8s, so the next turn falsely logged "could
        # not reach its model". A stopped server still fails fast (refused
        # instantly); only a BUSY server is slow to accept.
        read_timeout = max(5.0, float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "600")))
        connect_timeout = max(2.0, float(
            os.getenv("LOCAL_LLM_CONNECT_TIMEOUT_SECONDS", "30")))
        from agents.providers.openai_compatible import _build_provider_timeout
        return openai.OpenAI(
            api_key="local", base_url=self.base_url,
            timeout=_build_provider_timeout(openai, read=read_timeout,
                                            connect=connect_timeout),
        )

    def _dialogue_protocol(self) -> dict:
        from agents.providers.openai_compatible import (
            get_llama_server_capabilities, resolve_chat_protocol)
        capabilities = get_llama_server_capabilities(self.base_url)
        return resolve_chat_protocol(self.model, capabilities, default_tools=True)
    
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

    def _start_got_turn(self, prompt: str):
        from agents.brains.brain_got import start_brain_turn
        return start_brain_turn("big_brain", prompt)

    def _finish_got_turn(self, turn, response: str, status: str = "completed",
                         branch_candidates=None, evidence_by_id=None) -> str:
        turn.record_tool_trace(self.last_tool_trace)
        # Branching (Tree/Graph-of-Thoughts): when the caller supplies multiple
        # candidate thoughts AND the selected pattern allows branching, expand,
        # score by evidence-backed support, and record the selection. No-op for
        # direct (max_branches=1) patterns — existing behaviour is preserved.
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

        Prefers the live device registry (source of truth for detected hardware)
        so the prompt reflects the ACTUAL card, never a hardcoded name; falls
        back to the runtime config's gpu_label. Empty string when unknown.
        """
        try:
            from agents.runtime.dual_brain import BrainRole, DualBrainRuntime
            from agents.runtime import device_registry as dr
            cfg = DualBrainRuntime.from_env().config(BrainRole.BIG)
            label = (cfg.gpu_label or "").strip()
            try:
                devices = dr.detect_devices(include_cpu=True)
                if cfg.device_id:
                    dev = next((d for d in devices if d.id == cfg.device_id), None)
                    if dev is not None:
                        label = dev.label()
                elif cfg.gpu_layers == 0:
                    cpu = next((d for d in devices if d.is_cpu), None)
                    if cpu is not None:
                        label = cpu.label()
                elif 0 <= cfg.device < 64:
                    gpu = next((d for d in devices
                                if d.is_gpu and d.index == cfg.device), None)
                    if gpu is not None:
                        label = gpu.label()
            except Exception:
                pass
            if not label:
                return ""
            return (f"You run on {label}. You are the larger-capacity brain; "
                    "handle deep reasoning, planning, and verification, and keep "
                    "responses grounded in evidence.")
        except Exception:
            return ""

    def _build_system_prompt(self, query: str = "", task_type: str = "general") -> str:
        """Build system prompt with knowledge, personality, and specialization.
        
        Uses the prompting engine to select the best technique for the task type
        and injects memory of what worked before.
        """
        extra = f"\n\n# ABOUT {ProgramKnowledge.PROGRAM_NAME}"
        extra += ProgramKnowledge.CORE_IDENTITY
        extra += ProgramKnowledge.CORE_CAPABILITIES
        extra += ProgramKnowledge.SAFETY_RULES

        # Hardware awareness (N-brain): tell the model which device it runs on so
        # it can reason about its own capacity. Reflects the ACTUAL detected
        # hardware, never a hardcoded card.
        hw = self._hardware_line()
        if hw:
            extra += f"\n\n# YOUR HARDWARE\n{hw}\n"

        # Add task-specific specialization
        specialization = get_specialization_prompt(task_type)
        if specialization:
            extra += f"\n{specialization}"
        
        base = assemble_role_prompt(
            self.base_system_prompt, "big_brain", query,
            self.personality, self.knowledge, extra)
        
        # Apply prompting engine: select technique + inject memory
        from agents.knowledge.prompting_engine import adaptive_prompt
        recommendation = self._prompting_engine["recommend"]("big_brain", task_type, model_path=self.model, model_name=os.path.basename(self.model))
        return adaptive_prompt(task_type, base, recommendation)
    
    def _execute_tool_calls(self, tool_calls: list) -> list:
        """Execute tool calls from the model, with safety gate."""
        results = []
        for tc in tool_calls:
            fn_name = tc.function.name
            fn_args = tc.function.arguments or "{}"
            try:
                arguments = json.loads(fn_args)
            except json.JSONDecodeError:
                arguments = {}
            
            # Safety gate check
            allowed, reason, decision = self.safety_gate.check(fn_name, arguments)
            
            if decision == SafetyDecision.BLOCKED:
                results.append({
                    "tool_call_id": tc.id,
                    "role": "tool",
                    "content": f"[BLOCKED] {reason}"
                })
                continue
            
            if decision == SafetyDecision.NEEDS_APPROVAL:
                from agents.safety.approval import ApprovalKind, ApprovalItem, HumanApprovalQueue
                approval = HumanApprovalQueue.instance().enqueue(ApprovalItem(
                    kind=ApprovalKind.ACTION,
                    title=f"Big Brain tool request: {fn_name}",
                    description=f"{reason}. Human approval is required before this tool can run.",
                    requested_by="big_brain",
                    details={"tool": fn_name, "arguments": arguments, "reason": reason},
                    payload={"tool_call_id": tc.id, "tool": fn_name, "arguments": arguments},
                ))
                results.append({
                    "tool_call_id": tc.id,
                    "role": "tool",
                    "content": (
                        f"[PENDING APPROVAL] request_id={approval.id}; {reason}. "
                        "The tool was not executed. Wait for explicit human approval "
                        "and retry the request."
                    )
                })
                continue
            
            # Execute the tool
            try:
                from agents.safety.legacy_tools import execute_tool
                result = execute_tool(fn_name, arguments)
            except Exception as e:
                result = f"[Tool execution error: {e}]"
            
            results.append({
                "tool_call_id": tc.id,
                "role": "tool",
                "content": result
            })
        
        return results
    
    def analyze_with_tools(self, prompt: str, context: str = "") -> str:
        """Deep reasoning and analysis with tool calling."""
        got_turn = self._start_got_turn(prompt)
        self.last_tool_trace = []
        # Classify the task
        task_type = classify_task(prompt)
        
        # Build messages
        user_msg = prompt
        if context:
            user_msg = f"Context:\n{context}\n\nQuestion:\n{prompt}"
        
        messages = [
            {"role": "system", "content": self._build_system_prompt(prompt, task_type)},
            {"role": "user", "content": user_msg}
        ]
        
        # Get tools for this task type
        tools = get_tools_for_task(task_type)
        
        try:
            client = self._get_client()
            
            # Tool calling loop (max 5 iterations)
            for _ in range(5):
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 4096,
                    "temperature": 0.3,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                
                response = client.chat.completions.create(**kwargs)
                msg = response.choices[0].message
                
                # If no tool calls, we're done
                if not msg.tool_calls:
                    answer = msg.content or ""
                    self._finish_got_turn(got_turn, answer)
                    self.db.log_conversation("big_brain", "user", prompt)
                    self.db.log_conversation("big_brain", "assistant", answer)
                    self.personality.evolve_from_interaction("big_brain", prompt, answer)
                    return answer
                
                # Add assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "tc.function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in msg.tool_calls
                    ]
                })
                
                # Execute tool calls
                tool_results = self._execute_tool_calls(msg.tool_calls)
                messages.extend(tool_results)
            
            # If we exhausted iterations, ask for final answer
            messages.append({
                "role": "user",
                "content": "Based on the tool results above, provide your final answer."
            })
            final_response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=4096,
                temperature=0.3
            )
            answer = final_response.choices[0].message.content or ""
            self._finish_got_turn(got_turn, answer)
            
            self.db.log_conversation("big_brain", "user", prompt)
            self.db.log_conversation("big_brain", "assistant", answer)
            self.personality.evolve_from_interaction("big_brain", prompt, answer)
            
            return answer
            
        except Exception as e:
            # ARCH-ENG-109: log the REAL exception type + message (see small_brain).
            try:
                import logging, sys
                _diag = ("big_brain chat failed: %s: %s "
                         "(base_url=%s model=%s)") % (
                             type(e).__name__, str(e)[:300],
                             self.base_url, self.model)
                print(_diag, file=sys.stderr, flush=True)
                logging.getLogger(__name__).warning(_diag)
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
                        f"[{DRIVER.current_name}: Selected model '{self.model}' "
                        f"is unavailable. Available models: {', '.join(available)}. "
                        "Choose one explicitly in Providers & GPU.]"
                    )
                return (
                    f"[{DRIVER.current_name}: Selected model '{self.model}' is unavailable "
                    "and no models were reported by the configured server.]"
                )
            error_response = f"[Big Brain Error: {error_msg[:200]}]"
            self._finish_got_turn(got_turn, error_response, "error")
            return error_response
    
    def analyze(self, prompt: str, context: str = "") -> str:
        """Deep reasoning and analysis (legacy method, now uses tool calling)."""
        return self.analyze_with_tools(prompt, context)
    
    def verify(self, claim: str) -> str:
        """Fact-check a claim from Small Brain."""
        return self.analyze_with_tools(f"Verify the accuracy of this claim:\n{claim}")
    
    def plan(self, goal: str) -> str:
        """Create a multi-step plan."""
        return self.analyze_with_tools(f"Create a detailed plan to achieve this goal:\n{goal}")
    
    def revise(self, original_plan: str, feedback: str) -> str:
        """Revise a plan based on feedback."""
        return self.analyze_with_tools(
            f"Original plan:\n{original_plan}\n\n"
            f"Feedback:\n{feedback}\n\n"
            f"Revise the plan incorporating the feedback."
        )
    
    def chat(self, user_message: str, history: list = None,
             system_prompt: str = None, max_tokens: int = None,
             dialogue_mode: bool = False, stream_progress=None,
             tool_trace_cb=None, images=None, branch_candidates=None,
             evidence_by_id=None) -> str:
        """Handle direct chat with tool calling support.
        
        stream_progress: optional callback(str_chunk) invoked for each streamed
        token so the caller can show live generation progress.
        tool_trace_cb: optional callback(tool_event_dict) invoked the moment a
        tool executes (real activity, rendered separately from narration).
        images: optional vision payload (URLs/data-URLs/paths) for multimodal models.
        branch_candidates: optional list of candidate thoughts (dicts or
            BranchCandidate) for a branching (Tree/Graph-of-Thoughts) turn. When
            supplied and the reasoning pattern allows branching, the thought graph
            expands, scores each candidate by evidence-backed support, and records
            the selection. Ignored for direct (max_branches=1) patterns.
        evidence_by_id: optional {evidence_id: Evidence} used to score branches.
        """
        # GUI is the source of truth for model selection
        if self.model == "unknown" or not self.model:
            return f"[{DRIVER.current_name}: No model selected. Please choose a model in the Providers & GPU tab.]"
        
        # Detect model family for proper template/tool/thinking handling.
        from agents.providers.model_profile import get_model_profile, build_extra_body, needs_flat_system
        profile = get_model_profile(model_path=self.model, base_url=self.base_url)

        # Build system prompt
        if system_prompt:
            full_system = system_prompt
        else:
            full_system = self._build_system_prompt(user_message)
        
        # Add anti-hallucination rules
        from agents.safety.calling import add_anti_hallucination_rules
        full_system = add_anti_hallucination_rules(full_system)
        if dialogue_mode:
            full_system += (
                f"\n\nDIALOGUE MODE: Reply as {DRIVER.current_name} in natural language. "
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
        # Budget the BASE prompt first, then the dialogue tool-format block stays
        # intact at the tail (same ordering fix as the small brain).
        from agents.knowledge.prompting_engine import enforce_prompt_budget
        full_system = enforce_prompt_budget(full_system)
        
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

        got_turn = self._start_got_turn(user_message)
        try:
            client = self._get_client()
            
            # Use tool calling
            from agents.safety.calling import chat_with_tools
            protocol = self._dialogue_protocol()
            self.last_tool_trace = []
            
            # Use detected profile for thinking/extra_body configuration.
            # Natural dialogue needs a visible answer within its bounded
            # generation budget. Qwen/DeepSeek-style reasoning can otherwise
            # consume all tokens in `reasoning_content` and leave no persona
            # text for the conversation.
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
            # Only send extra_body if non-empty (avoids issues with servers that
            # reject unknown fields).
            final_extra_body = extra_body if extra_body else None
            
            # Track timing for stats.
            import time as _time
            _t0 = _time.time()
            
            answer = chat_with_tools(
                client=client,
                model=self.model,
                system_prompt=full_system,
                user_message=user_message,
                history=history,
                max_tokens=request_max_tokens,
                temperature=self.temperature,
                # One tool round lets Dialogue execute bounded read-only
                # research instead of endlessly announcing that it will search.
                max_iterations=2 if dialogue_mode else 2,
                # Dialogue is a visible persona exchange, not a tool round.
                # Small Brain already disables function calling here; keeping
                # Big Brain on the live tool protocol can yield tool-only or
                # empty responses from local templates.
                use_function_calling=(
                    False if dialogue_mode else protocol["use_function_calling"]
                ),
                flatten_system_prompt=protocol["flatten_system_prompt"],
                extra_body=final_extra_body,
                tool_trace=self.last_tool_trace,
                stream_progress=stream_progress,
                on_tool_trace=tool_trace_cb,
                images=images,
            )
            elapsed = _time.time() - _t0
            
            # Log to DB with real tokens/tps.
            try:
                prompt_chars = len(full_system) + len(user_message)
                resp_chars = len(answer or "")
                prompt_tokens = max(1, prompt_chars // 4)
                completion_tokens = max(1, resp_chars // 4)
                tps = (prompt_tokens + completion_tokens) / elapsed if elapsed > 0 else 0.0
                self.db.log_llm_call(
                    model=self.model,
                    provider=getattr(self, "last_provider", "big-brain"),
                    trigger="dialogue" if dialogue_mode else "chat",
                    prompt_chars=prompt_chars,
                    response_chars=resp_chars,
                    latency_ms=int(elapsed * 1000),
                    error=None,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    tokens_per_second=tps,
                    cost_usd=0.0,
                )
            except Exception:
                pass  # Stats logging must never break the response
            if not str(answer or "").strip():
                empty_response = (
                    f"[{DRIVER.current_name} Error: model returned an empty response "
                    f"for '{self.model}' at {self.base_url}. Check the loaded model "
                    "and chat template.]"
                )
                self._finish_got_turn(got_turn, empty_response, "empty")
                return empty_response

            # Log and evolve
            self.db.log_conversation("big_brain", "user", user_message)
            self.db.log_conversation("big_brain", "assistant", answer)
            self.personality.evolve_from_interaction("big_brain", user_message, answer)

            self._finish_got_turn(got_turn, answer,
                                  branch_candidates=branch_candidates,
                                  evidence_by_id=evidence_by_id)
            return answer
        except Exception as e:
            error_response = f"[Edward Hurst Error: {str(e)[:200]}]"
            self._finish_got_turn(got_turn, error_response, "error")
            return error_response


_big_brain = None

def get_big_brain():
    """Get or create the Big Brain singleton."""
    global _big_brain
    if _big_brain is None:
        _big_brain = BigBrainAdapter()
    return _big_brain
