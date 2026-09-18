""""
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.program_knowledge import (
    get_database, get_personality_engine, get_knowledge_context,
    ProgramKnowledge
)
from agents.prompt_assembly import assemble_role_prompt

from agents.personas import DRIVER, NAVIGATOR


class SmallBrainAdapter:
    """Interface to the fast chat model through the active provider.
    
    Model auto-detection: when SMALL_BRAIN_MODEL is unset or the configured
    model is not found on the server, auto-detect the first available model
    from llama-server's /v1/models endpoint. This lets users swap models
    without manually syncing env vars.
    """
    
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
        
        # Model: prefer explicit arg, then env var, then auto-detect.
        # We intentionally avoid a blocking HTTP call in __init__ so tab
        # construction stays fast even when llama-server is not yet running.
        self.model = model or os.getenv("SMALL_BRAIN_MODEL", "").strip() or ""
        self._explicit_model = self.model  # track whether user set it explicitly
        self.temperature = float(os.getenv("SMALL_BRAIN_TEMPERATURE", "0.5") or 0.5)
        self.last_tool_trace = []
        
        # Load system prompt
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "small_brain.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r") as f:
                self.base_system_prompt = f.read()
        else:
            self.base_system_prompt = "You are the SMALL BRAIN of MrBot1000."
    
    def _ensure_model(self):
        """Ensure self.model is set to a model the server actually has.
        
        Auto-detection runs once, lazy, on first use — not in __init__ so
        tab construction stays fast when llama-server is offline.
        """
        if self.model:
            # If user set an explicit model, verify it exists on the server.
            # If it doesn't, fall through to auto-detection.
            if self._model_exists_on_server(self.model):
                return
            # Explicit model not found — switch to auto-detected model and
            # clear the explicit flag so we don't re-verify on every call.
            self._explicit_model = ""
        
        if not self.model:
            detected = self._get_first_available_model()
            if detected and detected != "unknown":
                self.model = detected
                self._explicit_model = ""
    
    def _model_exists_on_server(self, model_name: str) -> bool:
        """Check whether the server reports `model_name` as available."""
        try:
            models = self.get_available_models()
            return model_name in models
        except Exception:
            return False
    
    def _get_client(self):
        """Get OpenAI client for llama-server."""
        import openai
        # Use a longer default timeout for local inference — when VRAM is
        # contended, a 60s default fires before the model can even finish a
        # single generation, leaving the Dialogue tab stuck on "Generating..."
        # with no error shown to the operator.
        timeout = float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "600"))
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
        self._explicit_model = model_name
    
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
        base = assemble_role_prompt(
            self.base_system_prompt, "small_brain", query,
            self.personality, self.knowledge, extra, limit)
        
        # Apply prompting engine: select technique + inject memory
        from agents.prompting_engine import adaptive_prompt, select_technique
        # Pass actual model to recommendation engine (not just role)
        recommendation = {
            "recommended_technique": select_technique("dialogue", {"complexity": "low", "urgency": "urgent"}),
            "complexity": "low",
        }
        # Override if model is actually large (e.g. 27B in Small Brain slot)
        from agents.prompting_engine import get_brain_recommendation
        recommendation = get_brain_recommendation("small_brain", "dialogue", model_path=self.model, model_name=os.path.basename(self.model))