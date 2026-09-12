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

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.program_knowledge import (
    get_database, get_personality_engine, get_knowledge_context,
    ProgramKnowledge
)
from agents.prompt_assembly import assemble_role_prompt
from agents.task_router import classify_task, get_tools_for_task, get_specialization_prompt
from agents.safety_gate import SafetyGate, SafetyDecision
from agents.personas import DRIVER


class BigBrainAdapter:
    """Interface to the main reasoning model via llama-server on 5060 Ti."""
    
    def __init__(self, model=None, base_url=None, safety_gate: SafetyGate | None = None):
        # Canonical runtime owns the role→endpoint/model/device contract. The
        # adapter inherits its defaults from the runtime; an explicit arg or env
        # still wins, but there is one source of truth.
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        _cfg = DualBrainRuntime.from_env().config(BrainRole.BIG)
        legacy_url = os.getenv("BIG_BRAIN_URL") if _cfg.provider == "llamacpp" else ""
        self.base_url = base_url or legacy_url or _cfg.endpoint
        self.device = _cfg.device
        self.context_length = _cfg.context
        
        # Knowledge and memory
        self.db = get_database()
        self.personality = get_personality_engine()
        self.knowledge = get_knowledge_context()
        
        # Safety gate
        self.safety_gate = safety_gate or SafetyGate()
        
        # Auto-detect model: use provided, env var, or "unknown" (populated later
        # by _refresh_big_brain_models / UI when llama-server is reachable).
        # We intentionally avoid a blocking HTTP call in __init__ so tab
        # construction stays fast even when llama-server is not yet running.
        self.model = model or os.getenv("BIG_BRAIN_MODEL") or _cfg.model or "unknown"
        
        # Load system prompt
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "big_brain.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                self.base_system_prompt = f.read()
        else:
            self.base_system_prompt = "You are the BIG BRAIN of MrBot1000."
    
    def _get_client(self):
        """Get OpenAI client for llama-server."""
        import openai
        timeout = float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "60"))
        return openai.OpenAI(api_key="local", base_url=self.base_url,
                             timeout=max(5.0, timeout))

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
    
    def _build_system_prompt(self, query: str = "", task_type: str = "general") -> str:
        """Build system prompt with knowledge, personality, and specialization."""
        extra = f"\n\n# ABOUT {ProgramKnowledge.PROGRAM_NAME}"
        extra += ProgramKnowledge.CORE_IDENTITY
        extra += ProgramKnowledge.CORE_CAPABILITIES
        extra += ProgramKnowledge.SAFETY_RULES
        
        # Add task-specific specialization
        specialization = get_specialization_prompt(task_type)
        if specialization:
            extra += f"\n{specialization}"

        return assemble_role_prompt(
            self.base_system_prompt, "big_brain", query,
            self.personality, self.knowledge, extra)
    
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
                from agents.approval_queue import ApprovalKind, ApprovalItem, HumanApprovalQueue
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
                from agents.tools import execute_tool
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
            
            self.db.log_conversation("big_brain", "user", prompt)
            self.db.log_conversation("big_brain", "assistant", answer)
            self.personality.evolve_from_interaction("big_brain", prompt, answer)
            
            return answer
            
        except Exception as e:
            error_msg = str(e)
            if "not found" in error_msg.lower() or "404" in error_msg:
                available = self.get_available_models()
                if available:
                    self.model = available[0]
                    return f"[Switched to model: {self.model}]"
                return f"[No models found. Please check llama-server is running.]"
            return f"[Big Brain Error: {error_msg[:200]}]"
    
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
             dialogue_mode: bool = False) -> str:
        """Handle direct chat with tool calling support."""
        # GUI is the source of truth for model selection
        if self.model == "unknown" or not self.model:
            return f"[{DRIVER.current_name}: No model selected. Please choose a model in the Providers & GPU tab.]"

        # Build system prompt
        if system_prompt:
            full_system = system_prompt
        else:
            full_system = self._build_system_prompt(user_message)
        
        # Add anti-hallucination rules
        from agents.tool_calling import add_anti_hallucination_rules
        full_system = add_anti_hallucination_rules(full_system)
        if dialogue_mode:
            full_system += (
                f"\n\nDIALOGUE-ONLY MODE: Reply as {DRIVER.current_name} in natural language. "
                "Do not call tools, write SQL, emit function names, or describe a "
                "tool call. Use the evidence already present in the conversation. "
                "If evidence is missing, say BLOCKED in one or two sentences."
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

        try:
            client = self._get_client()
            
            # Use tool calling
            from agents.tool_calling import chat_with_tools
            protocol = self._dialogue_protocol()
            answer = chat_with_tools(
                client=client,
                model=self.model,
                system_prompt=full_system,
                user_message=user_message,
                history=history,
                max_tokens=request_max_tokens,
                temperature=0.5,
                # One tool round lets Dialogue execute bounded read-only
                # research instead of endlessly announcing that it will search.
                max_iterations=1 if dialogue_mode else 2,
                use_function_calling=protocol["use_function_calling"],
                flatten_system_prompt=protocol["flatten_system_prompt"],
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )

            # Log and evolve
            self.db.log_conversation("big_brain", "user", user_message)
            self.db.log_conversation("big_brain", "assistant", answer)
            self.personality.evolve_from_interaction("big_brain", user_message, answer)

            return answer
        except Exception as e:
            return f"[Marcus Rivera Error: {str(e)[:200]}]"


_big_brain = None

def get_big_brain():
    """Get or create the Big Brain singleton."""
    global _big_brain
    if _big_brain is None:
        _big_brain = BigBrainAdapter()
    return _big_brain
