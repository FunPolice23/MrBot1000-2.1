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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.program_knowledge import (
    get_database, get_personality_engine, get_knowledge_context,
    ProgramKnowledge
)
from agents.prompt_assembly import assemble_role_prompt
from agents.personas import DRIVER, NAVIGATOR


class SmallBrainAdapter:
    """Interface to the fast chat model through the active provider."""
    
    def __init__(self, model=None, base_url=None):
        # Canonical runtime owns the role→endpoint/model/device contract.
        from agents.dual_brain_runtime import BrainRole, DualBrainRuntime
        _cfg = DualBrainRuntime.from_env().config(BrainRole.SMALL)
        legacy_url = os.getenv("SMALL_BRAIN_URL") if _cfg.provider == "llamacpp" else ""
        self.base_url = base_url or legacy_url or _cfg.endpoint
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
        # Full mode is opt-in for models with enough context to benefit from it.
        if tier == "full":
            extra += f"\n\n# ABOUT {ProgramKnowledge.PROGRAM_NAME}"
            extra += ProgramKnowledge.CORE_IDENTITY
            extra += ProgramKnowledge.CORE_CAPABILITIES
            extra += ProgramKnowledge.SAFETY_RULES

        limit = 1200 if tier == "compact" else 4000
        return assemble_role_prompt(
            self.base_system_prompt, "small_brain", query,
            self.personality, self.knowledge, extra, limit)
    
    def chat(self, user_message: str, history: list = None,
             system_prompt: str = None, max_tokens: int = None,
             dialogue_mode: bool = False) -> str:
        """Handle conversation with tool calling support."""
        # GUI is the source of truth for model selection
        if self.model == "unknown" or not self.model:
            return f"[{NAVIGATOR.current_name}: No model selected. Please choose a model in the Providers & GPU tab.]"

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
                f"\n\nDIALOGUE-ONLY MODE: Reply as {NAVIGATOR.current_name} in natural language. "
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
            
            # Small Brain uses text-based tool parsing to remain compatible
            # with compact local models and provider templates.
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
                max_iterations=1 if dialogue_mode else 2,
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
            return f"[{NAVIGATOR.current_name} Error: {str(e)[:200]}]"
    
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
