"""agents/provider_manager.py — Provider detection and management for MrBot1000.

Supports:
- Local providers: llama.cpp, Ollama, vLLM, LM Studio, KoboldCpp
- Cloud providers: OpenAI, Anthropic, OpenRouter, Groq, DeepSeek, Mistral, Together
- GPU management: single GPU, multi-GPU, cloud-only, mixed setups
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ProviderType(str, Enum):
    LLAMACPP = "llamacpp"
    OLLAMA = "ollama"
    VLLM = "vllm"
    LM_STUDIO = "lm_studio"
    KOBOLDCPP = "koboldcpp"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    GROQ = "groq"
    DEEPSEEK = "deepseek"
    MISTRAL = "mistral"
    TOGETHER = "together"


class ProviderStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass
class GPUInfo:
    """Information about a GPU."""
    index: int
    name: str
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    temperature: float = 0.0
    utilization: float = 0.0
    assigned_provider: str = ""
    assigned_brain: str = ""


@dataclass
class ProviderInfo:
    """Information about a provider."""
    name: str
    provider_type: str
    status: str = ProviderStatus.UNAVAILABLE
    base_url: str = ""
    api_key_env: str = ""
    models: List[str] = field(default_factory=list)
    selected_model: str = ""
    context_size: int = 32768
    gpu_index: int = -1  # -1 for cloud
    is_local: bool = True
    is_cloud: bool = False
    cost_per_1m_tokens: float = 0.0
    latency_ms: float = 0.0
    tokens_per_second: float = 0.0
    last_error: str = ""


class ProviderManager:
    """Detects and manages providers."""
    
    _instance: Optional["ProviderManager"] = None
    
    def __init__(self):
        self._providers: Dict[str, ProviderInfo] = {}
        self._gpus: List[GPUInfo] = []
        self._detected = False
    
    @classmethod
    def instance(cls) -> "ProviderManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def detect_providers(self) -> Dict[str, ProviderInfo]:
        """Detect all available providers.

        Preserve any user-selected state (enabled/disabled status, selected model,
        and GPU assignment) from the prior snapshot so a re-detect does not
        silently reset a provider that the operator already toggled or configured.
        """
        previous = dict(self._providers)
        self._providers = {}
        self._detect_gpus()
        self._detect_local_providers()
        self._detect_cloud_providers()

        for name, provider in dict(previous).items():
            if name not in self._providers:
                self._providers[name] = provider
                continue
            current = self._providers[name]
            current.status = provider.status if provider.status else current.status
            if provider.selected_model:
                current.selected_model = provider.selected_model
            if getattr(provider, "gpu_index", -1) != -1:
                current.gpu_index = provider.gpu_index
            if getattr(provider, "base_url", ""):
                current.base_url = provider.base_url
            if getattr(provider, "api_key_env", ""):
                current.api_key_env = provider.api_key_env
            if provider.models:
                current.models = provider.models
            if getattr(provider, "last_error", ""):
                current.last_error = provider.last_error

        self._detected = True
        return self._providers
    
    def _detect_gpus(self):
        """Detect GPUs using nvidia-smi."""
        self._gpus = []
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 7:
                        self._gpus.append(GPUInfo(
                            index=int(parts[0]),
                            name=parts[1],
                            memory_total_mb=int(float(parts[2])),
                            memory_used_mb=int(float(parts[3])),
                            memory_free_mb=int(float(parts[4])),
                            temperature=float(parts[5]) if parts[5] != "N/A" else 0.0,
                            utilization=float(parts[6]) if parts[6] != "N/A" else 0.0,
                        ))
        except Exception:
            pass
    
    def _detect_local_providers(self):
        """Detect local providers."""
        # Detect Ollama
        self._detect_ollama()
        # Detect vLLM
        self._detect_vllm()
        # Detect LM Studio
        self._detect_lm_studio()
        # Detect KoboldCpp
        self._detect_koboldcpp()
        # Detect llama.cpp
        self._detect_llamacpp()

    def refresh_provider_models(self, provider_name: str) -> List[str]:
        """Refresh models for one local provider without rebuilding all state."""
        provider = self.get_provider(provider_name)
        if not provider or not provider.is_local:
            return []

        env_prefix = {
            ProviderType.OLLAMA.value: "OLLAMA",
            ProviderType.VLLM.value: "VLLM",
            ProviderType.LM_STUDIO.value: "LM_STUDIO",
            ProviderType.KOBOLDCPP.value: "KOBOLDCPP",
        }.get(provider.provider_type, "")
        base_url = (
            os.getenv(f"{env_prefix}_BASE_URL", "").strip()
            if env_prefix else ""
        ) or provider.base_url
        provider.base_url = base_url
        base_url = base_url.rstrip("/")
        try:
            if provider.provider_type == ProviderType.OLLAMA.value:
                url = f"{base_url}/api/tags"
                with urllib.request.urlopen(urllib.request.Request(url), timeout=5) as resp:
                    models = [item.get("name", "") for item in json.loads(resp.read().decode()).get("models", [])]
            elif provider.provider_type in (ProviderType.LM_STUDIO.value, ProviderType.VLLM.value):
                url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
                with urllib.request.urlopen(urllib.request.Request(url), timeout=5) as resp:
                    models = [item.get("id", "") for item in json.loads(resp.read().decode()).get("data", [])]
            elif provider.provider_type == ProviderType.KOBOLDCPP.value:
                with urllib.request.urlopen(urllib.request.Request(f"{base_url}/api/v1/model"), timeout=5) as resp:
                    model = json.loads(resp.read().decode()).get("result", "")
                    models = [model] if model else []
            else:
                return list(provider.models)
        except Exception as exc:
            provider.last_error = str(exc)
            return []

        provider.models = list(dict.fromkeys(model for model in models if model))
        provider.status = ProviderStatus.RUNNING if provider.models else provider.status
        provider.last_error = ""
        return list(provider.models)
    
    def _detect_ollama(self):
        """Detect Ollama."""
        try:
            base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
            req = urllib.request.Request(f"{base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                self._providers["ollama"] = ProviderInfo(
                    name="Ollama",
                    provider_type=ProviderType.OLLAMA.value,
                    status=ProviderStatus.RUNNING,
                    base_url=base_url,
                    models=models,
                    is_local=True,
                    is_cloud=False,
                )
        except Exception as e:
            self._providers["ollama"] = ProviderInfo(
                name="Ollama",
                provider_type=ProviderType.OLLAMA.value,
                status=ProviderStatus.STOPPED,
                base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
                last_error=str(e),
                is_local=True,
                is_cloud=False,
            )
    
    def _detect_vllm(self):
        """Detect vLLM."""
        base_url = os.getenv("VLLM_BASE_URL", "").rstrip("/")
        if not base_url:
            return
        try:
            models_url = (f"{base_url}/models" if base_url.endswith("/v1")
                          else f"{base_url}/v1/models")
            req = urllib.request.Request(models_url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("id", "") for m in data.get("data", [])]
                self._providers["vllm"] = ProviderInfo(
                    name="vLLM",
                    provider_type=ProviderType.VLLM.value,
                    status=ProviderStatus.RUNNING,
                    base_url=base_url,
                    models=models,
                    is_local=True,
                    is_cloud=False,
                )
        except Exception as e:
            self._providers["vllm"] = ProviderInfo(
                name="vLLM",
                provider_type=ProviderType.VLLM.value,
                status=ProviderStatus.STOPPED,
                base_url=base_url,
                last_error=str(e),
                is_local=True,
                is_cloud=False,
            )
    
    def _detect_lm_studio(self):
        """Detect LM Studio."""
        base_url = os.getenv(
            "LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
        try:
            models_url = (
                f"{base_url.rstrip('/')}/models"
                if base_url.rstrip('/').endswith('/v1')
                else f"{base_url.rstrip('/')}/v1/models"
            )
            req = urllib.request.Request(models_url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("id", "") for m in data.get("data", [])]
                self._providers["lm_studio"] = ProviderInfo(
                    name="LM Studio",
                    provider_type=ProviderType.LM_STUDIO.value,
                    status=ProviderStatus.RUNNING,
                    base_url=base_url,
                    models=models,
                    is_local=True,
                    is_cloud=False,
                )
        except Exception as e:
            self._providers["lm_studio"] = ProviderInfo(
                name="LM Studio",
                provider_type=ProviderType.LM_STUDIO.value,
                status=ProviderStatus.STOPPED,
                base_url=base_url,
                last_error=str(e),
                is_local=True,
                is_cloud=False,
            )
    
    def _detect_koboldcpp(self):
        """Detect KoboldCpp."""
        base_url = os.getenv("KOBOLDCPP_BASE_URL", "")
        if not base_url:
            return
        try:
            req = urllib.request.Request(f"{base_url}/api/v1/model")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                model = data.get("result", "")
                self._providers["koboldcpp"] = ProviderInfo(
                    name="KoboldCpp",
                    provider_type=ProviderType.KOBOLDCPP.value,
                    status=ProviderStatus.RUNNING,
                    base_url=base_url,
                    models=[model] if model else [],
                    is_local=True,
                    is_cloud=False,
                )
        except Exception as e:
            self._providers["koboldcpp"] = ProviderInfo(
                name="KoboldCpp",
                provider_type=ProviderType.KOBOLDCPP.value,
                status=ProviderStatus.STOPPED,
                base_url=base_url,
                last_error=str(e),
                is_local=True,
                is_cloud=False,
            )
    
    def _detect_llamacpp(self):
        """Detect llama.cpp."""
        # Check for llama-server binary
        bin_path = os.getenv("LLAMA_SERVER_BIN", "")
        if not bin_path:
            # Try default paths
            default_paths = [
                r"D:\llama.cpp\llama-server.exe",
                r"D:\llama.cpp\build\bin\llama-server.exe",
                r"D:\llama.cpp\build\bin\Release\llama-server.exe",
            ]
            for p in default_paths:
                if os.path.exists(p):
                    bin_path = p
                    break
        
        if bin_path and os.path.exists(bin_path):
            self._providers["llamacpp"] = ProviderInfo(
                name="llama.cpp",
                provider_type=ProviderType.LLAMACPP.value,
                status=ProviderStatus.STOPPED,  # Not running yet
                base_url="http://127.0.0.1:1234",
                is_local=True,
                is_cloud=False,
            )
        else:
            self._providers["llamacpp"] = ProviderInfo(
                name="llama.cpp",
                provider_type=ProviderType.LLAMACPP.value,
                status=ProviderStatus.UNAVAILABLE,
                last_error="llama-server binary not found",
                is_local=True,
                is_cloud=False,
            )
    
    def _detect_cloud_providers(self):
        """Detect cloud providers."""
        cloud_providers = [
            ("openai", "OpenAI", "OPENAI_API_KEY", ProviderType.OPENAI,
             ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]),
            ("anthropic", "Anthropic", "ANTHROPIC_API_KEY", ProviderType.ANTHROPIC,
             ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"]),
            ("openrouter", "OpenRouter", "OPENROUTER_API_KEY", ProviderType.OPENROUTER,
             ["openai/gpt-4o-mini", "openai/gpt-4o", "anthropic/claude-3.5-sonnet", "google/gemini-2.0-pro"]),
            ("groq", "Groq", "GROQ_API_KEY", ProviderType.GROQ,
             ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-3276k", "gemma-2-9b-it"]),
            ("deepseek", "DeepSeek", "DEEPSEEK_API_KEY", ProviderType.DEEPSEEK,
             ["deepseek-chat", "deepseek-reasoner"]),
            ("mistral", "Mistral", "MISTRAL_API_KEY", ProviderType.MISTRAL,
             ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest", "open-mixtral-8x22b"]),
            ("together", "Together", "TOGETHER_API_KEY", ProviderType.TOGETHER,
             ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "deepseek-ai/DeepSeek-V3", "mistralai/Mistral-7B-Instruct-v0.3"]),
        ]
        
        for name, display_name, key_env, ptype, default_models in cloud_providers:
            api_key = os.getenv(key_env, "")
            if api_key:
                self._providers[name] = ProviderInfo(
                    name=display_name,
                    provider_type=ptype.value,
                    status=ProviderStatus.RUNNING,
                    api_key_env=key_env,
                    models=default_models,  # Populate with common model names
                    is_local=False,
                    is_cloud=True,
                )
            else:
                self._providers[name] = ProviderInfo(
                    name=display_name,
                    provider_type=ptype.value,
                    status=ProviderStatus.UNAVAILABLE,
                    api_key_env=key_env,
                    models=default_models,  # Still show models even without key
                    last_error=f"No API key (set {key_env})",
                    is_local=False,
                    is_cloud=True,
                )
    
    def get_providers(self) -> Dict[str, ProviderInfo]:
        """Get all detected providers."""
        if not self._detected:
            self.detect_providers()
        return self._providers
    
    def get_gpus(self) -> List[GPUInfo]:
        """Get all detected GPUs."""
        if not self._detected:
            self.detect_providers()
        return self._gpus
    
    def get_running_providers(self) -> Dict[str, ProviderInfo]:
        """Get only running providers."""
        return {k: v for k, v in self.get_providers().items() if v.status == ProviderStatus.RUNNING}

    @staticmethod
    def normalize_provider_name(name: str) -> str:
        """Return the runtime/provider-config spelling for a provider name."""
        return {
            "lm_studio": "lmstudio",
            "lm studio": "lmstudio",
            "llama.cpp": "llamacpp",
            "koboldcpp": "koboldcpp",
        }.get((name or "").strip().lower(), (name or "").strip().lower())

    def resolve_enabled_provider(self, local: bool = True) -> Optional[str]:
        """Resolve the explicitly enabled provider, or ``None``.

        Environment role settings are authoritative because they are shared by
        the GUI, adapters, and workers. Provider detection alone is not enough:
        a stopped or merely installed backend must not become the active route.
        """
        role_keys = ("BIG_BRAIN_PROVIDER", "SMALL_BRAIN_PROVIDER")
        candidates = []
        for key in role_keys:
            provider = self.normalize_provider_name(os.getenv(key, ""))
            enabled = os.getenv(key.replace("_PROVIDER", "_ENABLED"), "true")
            if provider and enabled.strip().lower() not in ("0", "false", "no", "off"):
                candidates.append(provider)
        if candidates and all(provider == candidates[0] for provider in candidates):
            return candidates[0]
        if candidates:
            return candidates[0]
        return None
    
    def get_local_providers(self) -> Dict[str, ProviderInfo]:
        """Get local providers."""
        return {k: v for k, v in self.get_providers().items() if v.is_local}
    
    def get_cloud_providers(self) -> Dict[str, ProviderInfo]:
        """Get cloud providers."""
        return {k: v for k, v in self.get_providers().items() if v.is_cloud}
    
    def set_provider_status(self, name: str, status: str | ProviderStatus) -> bool:
        """Set the runtime status for a provider without losing it on re-detect."""
        provider = self.get_provider(name)
        if provider is None:
            return False
        provider.status = status.value if isinstance(status, ProviderStatus) else str(status)
        return True

    def get_provider(self, name: str) -> Optional[ProviderInfo]:
        """Get a specific provider."""
        return self.get_providers().get(name)
    
    def get_gpu(self, index: int) -> Optional[GPUInfo]:
        """Get a specific GPU."""
        for gpu in self.get_gpus():
            if gpu.index == index:
                return gpu
        return None
    
    def assign_provider_to_gpu(self, provider_name: str, gpu_index: int):
        """Assign a provider to a GPU."""
        if provider_name in self._providers:
            self._providers[provider_name].gpu_index = gpu_index
        for gpu in self._gpus:
            if gpu.index == gpu_index:
                gpu.assigned_provider = provider_name
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all providers and GPUs."""
        return {
            "providers": {k: {
                "name": v.name,
                "type": v.provider_type,
                "status": v.status,
                "models": len(v.models),
                "gpu_index": v.gpu_index,
                "is_local": v.is_local,
                "is_cloud": v.is_cloud,
            } for k, v in self.get_providers().items()},
            "gpus": [{
                "index": g.index,
                "name": g.name,
                "memory_total_mb": g.memory_total_mb,
                "memory_used_mb": g.memory_used_mb,
                "memory_free_mb": g.memory_free_mb,
                "temperature": g.temperature,
                "utilization": g.utilization,
                "assigned_provider": g.assigned_provider,
            } for g in self.get_gpus()],
        }


__all__ = [
    "ProviderManager",
    "ProviderInfo",
    "GPUInfo",
    "ProviderType",
    "ProviderStatus",
]
