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
from agents.task_router import classify_task, get_tools_for_task, get_specialization_prompt
from agents.safety_gate import SafetyGate, SafetyDecision


class BigBrainAdapter:
    """Interface to the main reasoning model via llama-server on 5060 Ti."""
    
    def __init__(self, model=None, base_url=None, safety_gate: SafetyGate | None = None):
        # Canonical runtime owns the role→endpoint/model/device contract. The
        # adapter inherits its defaults from the runtime; an explicit arg or env
        # still wins, but there is one source of truth.
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        _cfg = DualBrainRuntime.from_env().config(BrainRole.BIG)
        self.base_url = base_url or os.getenv("BIG_BRAIN_URL") or _cfg.endpoint
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
        return openai.OpenAI(api_key="local", base_url=self.base_url)
    
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
        prompt = self.base_system_prompt
        
        # Add program knowledge
        prompt += f"\n\n# ABOUT {ProgramKnowledge.PROGRAM_NAME}"
        prompt += ProgramKnowledge.CORE_IDENTITY
        prompt += ProgramKnowledge.CORE_CAPABILITIES
        prompt += ProgramKnowledge.SAFETY_RULES
        
        # Add task-specific specialization
        specialization = get_specialization_prompt(task_type)
        if specialization:
            prompt += f"\n{specialization}"
        
        # Add personality
        prompt += self.personality.get_system_prompt_addon("big_brain")
        
        # Add relevant memories and context
        context = self.knowledge.build_context("big_brain", query)
        if context:
            prompt += f"\n\n# CURRENT CONTEXT\n{context}"
        
        return prompt
    
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
                # For now, block approval-required tools and notify UI
                # TODO: emit signal for UI approval dialog
                results.append({
                    "tool_call_id": tc.id,
                    "role": "tool",
                    "content": f"[PENDING APPROVAL] {reason}. Use approved tools only."
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
             system_prompt: str = None) -> str:
        """Handle direct chat with tool calling support."""
        # GUI is the source of truth for model selection
        if self.model == "unknown" or not self.model:
            return "[Marcus Rivera: No model selected. Please choose a model in the Providers & GPU tab.]"

        # Build system prompt
        if system_prompt:
            full_system = system_prompt
        else:
            full_system = self._build_system_prompt(user_message)
        
        # Add anti-hallucination rules
        from agents.tool_calling import add_anti_hallucination_rules
        full_system = add_anti_hallucination_rules(full_system)
        
        # v2.1: Use the context length from Providers_GPU settings
        # Reserve ~20% for input, rest for output
        max_tokens = int(self.context_length * 0.8)
        
        # Cap at reasonable limits to avoid OOM
        max_tokens = min(max_tokens, 32768)
        max_tokens = max(max_tokens, 2048)

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
            answer = chat_with_tools(
                client=client,
                model=self.model,
                system_prompt=full_system,
                user_message=user_message,
                history=history,
                max_tokens=max_tokens,
                temperature=0.5,
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
