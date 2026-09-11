"""
Small Brain — Provider adapter for the fast chat model.
Uses llama-server (llama.cpp) via the OpenAI SDK.
Auto-detects downloaded models — no hardcoded model names.
GPU: 1660 Super (device 1) with RAM overflow.
Port: 1235.
Includes program knowledge, memory, and personality.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.program_knowledge import (
    get_database, get_personality_engine, get_knowledge_context,
    ProgramKnowledge
)


class SmallBrainAdapter:
    """Interface to the fast chat model via llama-server on 1660 Super."""
    
    def __init__(self, model=None, base_url=None):
        # Canonical runtime owns the role→endpoint/model/device contract.
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        _cfg = DualBrainRuntime.from_env().config(BrainRole.SMALL)
        self.base_url = base_url or os.getenv("SMALL_BRAIN_URL") or _cfg.endpoint
        self.device = _cfg.device
        self.context_length = _cfg.context
        
        # Knowledge and memory
        self.db = get_database()
        self.personality = get_personality_engine()
        self.knowledge = get_knowledge_context()
        
        # Auto-detect model: use provided, env var, or "unknown" (populated later
        # by _refresh_small_brain_models / UI when llama-server is reachable).
        # We intentionally avoid a blocking HTTP call in __init__ so tab
        # construction stays fast even when llama-server is not yet running.
        self.model = model or os.getenv("SMALL_BRAIN_MODEL") or _cfg.model or "unknown"
        
        # Load system prompt
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "small_brain.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r") as f:
                self.base_system_prompt = f.read()
        else:
            self.base_system_prompt = "You are the SMALL BRAIN of MrBot1000."
    
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
    
    def _build_system_prompt(self, query: str = "") -> str:
        """Build system prompt with knowledge and personality."""
        prompt = self.base_system_prompt
        
        # Add program knowledge
        prompt += f"\n\n# ABOUT {ProgramKnowledge.PROGRAM_NAME}"
        prompt += ProgramKnowledge.CORE_IDENTITY
        prompt += ProgramKnowledge.CORE_CAPABILITIES
        prompt += ProgramKnowledge.SAFETY_RULES
        
        # Add personality
        prompt += self.personality.get_system_prompt_addon("small_brain")
        
        # Add relevant memories and context
        context = self.knowledge.build_context("small_brain", query)
        if context:
            prompt += f"\n\n# CURRENT CONTEXT\n{context}"
        
        return prompt
    
    def chat(self, user_message: str, history: list = None,
             system_prompt: str = None, max_tokens: int = None) -> str:
        """Handle conversation with tool calling support."""
        # GUI is the source of truth for model selection
        if self.model == "unknown" or not self.model:
            return "[Alex Vega: No model selected. Please choose a model in the Providers & GPU tab.]"

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
            
            # v2.1: Small Brain (1660S) uses text-based tool parsing
            # to avoid 400 errors from llama.cpp template parser
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
                # Text-form tool calls need a second round to execute and
                # return evidence to the persona.
                max_iterations=2,
                use_function_calling=False,
                flatten_system_prompt=protocol["flatten_system_prompt"],
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )

            # Log and evolve
            self.db.log_conversation("small_brain", "user", user_message)
            self.db.log_conversation("small_brain", "assistant", answer)
            self.personality.evolve_from_interaction("small_brain", user_message, answer)

            return answer
        except Exception as e:
            return f"[Alex Vega Error: {str(e)[:200]}]"
    
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
