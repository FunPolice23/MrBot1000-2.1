"""Hugging Face GGUF discovery and safe download helpers."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from provider_models import classify_model_band, infer_model_parameters

HF_API = "https://huggingface.co/api"
HF_SITE = "https://huggingface.co"


@dataclass(frozen=True)
class ProviderInstallTarget:
    """A provider-specific destination and the action needed after download."""

    key: str
    label: str
    directory: Path
    mode: str
    note: str


def provider_install_targets() -> list[ProviderInstallTarget]:
    """Return provider-aware destinations using environment overrides first."""
    home = Path.home()
    llama_dir = Path(os.getenv("GGUF_MODELS_DIR", "").strip() or r"D:\llama.cpp")
    lmstudio_dir = Path(os.getenv("LM_STUDIO_MODELS_DIR", "").strip() or r"D:\LMStudio\models")
    ollama_dir = Path(os.getenv("OLLAMA_IMPORT_DIR", "").strip() or (home / "MrBot1000" / "ollama-import"))
    kobold_dir = Path(os.getenv("KOBOLDCPP_MODELS_DIR", "").strip() or (home / "KoboldCpp" / "models"))
    vllm_dir = Path(os.getenv("VLLM_IMPORT_DIR", "").strip() or (home / "MrBot1000" / "vllm-import"))
    return [
        ProviderInstallTarget("llamacpp", "llama.cpp / MrBot1000", llama_dir, "direct", "The downloaded GGUF can be launched directly by llama-server."),
        ProviderInstallTarget("lmstudio", "LM Studio", lmstudio_dir, "direct", "Use LM Studio's configured model directory or import this folder there."),
        ProviderInstallTarget("koboldcpp", "KoboldCpp", kobold_dir, "direct", "KoboldCpp can open the downloaded GGUF path directly."),
        ProviderInstallTarget("ollama", "Ollama", ollama_dir, "ollama-import", "Downloaded to a dedicated import folder; do not place raw GGUF files directly into Ollama's managed blob store. An Ollama Modelfile/import step is still required."),
        ProviderInstallTarget("vllm", "vLLM", vllm_dir, "unsupported-gguf", "Downloaded to a dedicated import folder; vLLM normally uses Transformers/Safetensors and does not automatically consume this GGUF."),
        ProviderInstallTarget("custom", "Custom folder", home / "MrBot1000" / "models", "custom", "The file is downloaded only and is not registered with a provider."),
    ]


@dataclass
class GGUFArtifact:
    name: str
    size: int = 0
    quantization: str = "unknown"
    sha256: str = ""
    download_url: str = ""

    @property
    def size_label(self) -> str:
        if not self.size:
            return "size unknown"
        value = float(self.size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return "size unknown"


@dataclass
class HuggingFaceGGUFModel:
    repo_id: str
    title: str
    description: str = ""
    downloads: int = 0
    likes: int = 0
    last_modified: str = ""
    license: str = "unknown"
    architecture: str = "unknown"
    params_billion: Optional[float] = None
    active_params_billion: Optional[float] = None
    moe: Optional[bool] = None
    context: Optional[int] = None
    capabilities: list[str] = field(default_factory=list)
    base_model: str = ""
    model_card: str = ""
    metadata_source: str = "repository"
    task: str = "unknown"
    category: str = "other"
    artifacts: list[GGUFArtifact] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def type_label(self) -> str:
        if self.moe is True:
            return "MoE"
        if self.moe is False:
            return "Dense"
        return "Unknown type"

    @property
    def params_label(self) -> str:
        return f"{self.params_billion:g}B" if self.params_billion is not None else "unknown params"

    @property
    def size_band(self) -> str:
        return classify_model_band(
            self.params_billion,
            moe=self.moe is True,
            active_params_billion=self.active_params_billion,
        )

    @property
    def size_label(self) -> str:
        if self.params_billion is None:
            return "unknown size"
        if self.moe and self.active_params_billion is not None and self.active_params_billion < self.params_billion:
            return f"{self.params_label} total / {self.active_params_billion:g}B active"
        return self.params_label

    @property
    def site_url(self) -> str:
        return f"{HF_SITE}/{self.repo_id}"


def _https_url(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    trusted = host == "huggingface.co" or host.endswith(".huggingface.co") or host.endswith(".hf.co")
    if parsed.scheme != "https" or not trusted:
        raise ValueError("Hugging Face requests must use a trusted HTTPS host")
    return url


def _validate_response_url(url: str) -> str:
    """Reject redirects outside Hugging Face and its signed download hosts."""
    return _https_url(url)


def _parse_params(text: str) -> Optional[float]:
    authoritative = re.findall(r"(?:number of parameters|parameter count|parameters)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*[bB]", text, re.I)
    if authoritative:
        return max(float(item) for item in authoritative)
    matches = re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*[bB](?!\w)", text)
    if not matches:
        return None
    return max(float(item) for item in matches)


def _parse_context(text: str) -> Optional[int]:
    matches = re.findall(r"(?:context(?:\s+length)?|max_position_embeddings)[^\d]{0,40}(\d[\d,]*)", text, re.I)
    values = [int(item.replace(",", "")) for item in matches]
    return max(values) if values else None


def _parse_quantization(name: str) -> str:
    upper = name.upper()
    for pattern in (r"Q[2-8](?:_[Kk](?:_[SML]|_XL)?|_0)?", r"IQ[1-4]_[A-Z]+", r"BF16", r"F16", r"F32"):
        match = re.search(pattern, upper)
        if match:
            return match.group(0)
    return "unknown"


def _architecture(text: str) -> str:
    lowered = text.lower()
    for family in ("llama", "qwen", "gemma", "mistral", "mixtral", "deepseek", "phi", "command-r", "yi", "falcon"):
        if family in lowered:
            return family
    return "unknown"


def _is_moe(text: str) -> Optional[bool]:
    lowered = text.lower()
    if re.search(r"\b(?:mixture[- ]of[- ]experts|moe|mixtral|experts?)\b", lowered) or re.search(r"(?:\d+x\d+b|\d+b[-_]?a\d+b|a\d+b|a3b|a4b)", lowered):
        return True
    if re.search(r"\b(?:dense|causal language model|decoder[- ]only)\b", lowered):
        return False
    # Common model-family names are useful provisional evidence in the list
    # endpoint, which does not include each repository's config.json.
    if re.search(r"\b(?:llama|qwen|gemma|mistral|phi|yi|falcon|minicpm|command[- ]r)\b", lowered):
        return False
    return None


def _artifact_from_sibling(repo_id: str, sibling: dict[str, Any]) -> Optional[GGUFArtifact]:
    name = str(sibling.get("rfilename") or sibling.get("path") or "")
    lowered = name.lower()
    excluded = ("mmproj", "imatrix", "embedding", "adapter", "projector", "tokenizer", "clip")
    if not lowered.endswith(".gguf") or any(token in lowered for token in excluded):
        return None
    if "/mtp/" in f"/{lowered}" or lowered.startswith("mtp/"):
        return None
    return GGUFArtifact(
        name=name,
        size=int(sibling.get("size") or (sibling.get("lfs") or {}).get("size") or 0),
        sha256=str((sibling.get("lfs") or {}).get("sha256") or ""),
        quantization=_parse_quantization(name),
        download_url=_https_url(f"{HF_SITE}/{repo_id}/resolve/main/{name}"),
    )


class HuggingFaceModelService:
    """Small API client kept independent from Qt for easy testing."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "MrBot1000-Model-Library/1.0")

    def search(self, query: str = "", page: int = 0, limit: int = 100, task: str = "", library: str = "") -> list[HuggingFaceGGUFModel]:
        params = {
            "search": query,
            "sort": "downloads",
            "direction": "-1",
            "limit": min(limit, 1000),
            "offset": page * limit,
            "full": "true",
        }
        if task:
            params["pipeline_tag"] = task
        params["filter"] = "gguf"
        if library:
            params["library"] = library
        response = self.session.get(
            _https_url(f"{HF_API}/models"),
            params=params,
            timeout=(10, 30),
        )
        _validate_response_url(response.url)
        response.raise_for_status()
        results = []
        for item in response.json():
            repo_id = str(item.get("id") or "")
            if repo_id:
                results.append(self._summary_model(item))
        return results

    def _summary_model(self, item: dict[str, Any]) -> HuggingFaceGGUFModel:
        """Build a result from the list endpoint without N+1 network calls."""
        repo_id = str(item.get("id") or "")
        siblings = item.get("siblings") or []
        artifacts = [artifact for sibling in siblings if (artifact := _artifact_from_sibling(repo_id, sibling))]
        tags = [str(tag) for tag in item.get("tags") or []]
        task = str(item.get("pipeline_tag") or "unknown")
        capabilities = self._capabilities(item, tags, "")
        category = self._category(task, tags, capabilities)
        text = " ".join((repo_id, task, " ".join(tags)))
        params, active_params = infer_model_parameters(repo_id)
        return HuggingFaceGGUFModel(
            repo_id=repo_id,
            title=repo_id.rsplit("/", 1)[-1],
            downloads=int(item.get("downloads") or 0),
            likes=int(item.get("likes") or 0),
            last_modified=str(item.get("lastModified") or ""),
            architecture=_architecture(text),
            params_billion=_parse_params(text) or params,
            active_params_billion=active_params,
            moe=_is_moe(text),
            capabilities=capabilities,
            task=task,
            category=category,
            artifacts=artifacts,
            raw={"summary": item},
        )

    def inspect(self, repo_id: str, summary: Optional[dict[str, Any]] = None) -> HuggingFaceGGUFModel:
        response = self.session.get(_https_url(f"{HF_API}/models/{repo_id}"), timeout=(10, 30))
        _validate_response_url(response.url)
        response.raise_for_status()
        data = response.json()
        siblings = data.get("siblings") or []
        try:
            tree = self._get_tree(repo_id)
        except requests.RequestException:
            tree = []
        sizes = {str(item.get("path")): item for item in tree if isinstance(item, dict)}
        for sibling in siblings:
            path = str(sibling.get("rfilename") or sibling.get("path") or "")
            if path in sizes:
                sibling.update(sizes[path])
        artifacts = [artifact for sibling in siblings if (artifact := _artifact_from_sibling(repo_id, sibling))]
        card = data.get("cardData") or {}
        tags = [str(tag) for tag in (data.get("tags") or [])]
        base_model = self._base_model(data, card, tags)
        base_data, base_readme = ({}, "")
        if base_model and base_model != repo_id:
            try:
                base_data = self._get_model(base_model)
                base_readme = self._get_raw(base_model, "README.md")
            except (requests.RequestException, ValueError):
                pass
        try:
            readme = self._get_raw(repo_id, "README.md")
            config = self._get_json(repo_id, "config.json")
        except requests.RequestException:
            readme, config = "", {}
        if not config and base_model:
            config = self._get_json(base_model, "config.json")
        card_text = base_readme or readme
        text = " ".join((repo_id, str(data.get("pipeline_tag") or ""), " ".join(tags), str(card), str(config), card_text, *(a.name for a in artifacts)))
        params = _parse_params(text)
        inferred_params, active_params = infer_model_parameters(repo_id)
        params = params or inferred_params
        architecture = self._config_architecture(config) or _architecture(text)
        moe = self._config_moe(config)
        if moe is None:
            moe = _is_moe(text)
        context = self._config_context(config) or card.get("context_length") or _parse_context(text)
        description = self._description(card_text, data, base_data)
        capabilities = self._capabilities(data, tags, card_text)
        task = str(base_data.get("pipeline_tag") or data.get("pipeline_tag") or "unknown")
        category = self._category(task, tags, capabilities)
        license_name = str(card.get("license") or data.get("license") or "unknown")
        return HuggingFaceGGUFModel(
            repo_id=repo_id,
            title=repo_id.rsplit("/", 1)[-1],
            description=description,
            downloads=int((summary or data).get("downloads") or 0),
            likes=int((summary or data).get("likes") or 0),
            last_modified=str(data.get("lastModified") or ""),
            license=license_name,
            architecture=architecture,
            params_billion=params,
            active_params_billion=active_params,
            moe=moe,
            context=context if isinstance(context, int) else None,
            capabilities=capabilities,
            base_model=base_model,
            model_card=card_text,
            metadata_source="base model + GGUF repository" if base_model else "GGUF repository",
            task=task,
            category=category,
            artifacts=artifacts,
            raw=data,
        )

    def _get_model(self, repo_id: str) -> dict[str, Any]:
        response = self.session.get(_https_url(f"{HF_API}/models/{repo_id}"), timeout=(10, 30))
        _validate_response_url(response.url)
        response.raise_for_status()
        return response.json()

    def _get_raw(self, repo_id: str, filename: str) -> str:
        response = self.session.get(_https_url(f"{HF_SITE}/{repo_id}/raw/main/{filename}"), timeout=(10, 30))
        _validate_response_url(response.url)
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        return response.text if isinstance(response.text, str) else ""

    def _get_json(self, repo_id: str, filename: str) -> dict[str, Any]:
        raw = self._get_raw(repo_id, filename)
        if not raw:
            return {}
        try:
            import json
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _get_tree(self, repo_id: str) -> list[dict[str, Any]]:
        response = self.session.get(_https_url(f"{HF_API}/models/{repo_id}/tree/main"), params={"recursive": "true"}, timeout=(10, 30))
        _validate_response_url(response.url)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        value = response.json()
        return value if isinstance(value, list) else []

    @staticmethod
    def _base_model(data: dict[str, Any], card: dict[str, Any], tags: list[str]) -> str:
        value = card.get("base_model") or data.get("base_model")
        if isinstance(value, list):
            value = value[0] if value else ""
        if value:
            return str(value)
        for tag in tags:
            if tag.startswith("base_model:") and not tag.startswith("base_model:quantized:"):
                return tag.split(":", 1)[1]
        return ""

    @staticmethod
    def _config_architecture(config: dict[str, Any]) -> str:
        values = []
        for key in ("model_type", "architectures"):
            value = config.get(key)
            values.extend(value if isinstance(value, list) else [value] if value else [])
        return str(values[0]) if values else ""

    @staticmethod
    def _config_moe(config: dict[str, Any]) -> Optional[bool]:
        flattened = str(config).lower()
        if any(key in flattened for key in ("num_local_experts", "num_experts_per_tok", "num_experts")):
            return True
        if config:
            return False
        return None

    @staticmethod
    def _config_context(config: dict[str, Any]) -> Optional[int]:
        values = []
        for key in ("max_position_embeddings", "max_sequence_length", "seq_length"):
            value = config.get(key)
            if isinstance(value, int):
                values.append(value)
        for value in config.values():
            if isinstance(value, dict):
                nested = HuggingFaceModelService._config_context(value)
                if nested:
                    values.append(nested)
        return max(values) if values else None

    @staticmethod
    def _description(readme: str, data: dict[str, Any], base_data: dict[str, Any]) -> str:
        if readme:
            clean = re.sub(r"```.*?```", "", readme, flags=re.S)
            clean = re.sub(r"!\[[^]]*\]\([^)]*\)", "", clean)
            clean = re.sub(r"<[^>]+>", " ", clean)
            clean = re.sub(r"\s+", " ", clean).strip()
            return clean[:4000]
        return str(data.get("description") or base_data.get("description") or "")

    @staticmethod
    def _capabilities(data: dict[str, Any], tags: list[str], readme: str) -> list[str]:
        text = " ".join(tags + [str(data.get("pipeline_tag") or ""), readme]).lower()
        capabilities = []
        for label, terms in (("text", ("causal language", "text generation")), ("vision", ("vision", "image-text", "visual")), ("video", ("video",)), ("tool calling", ("tool calling", "function calling")), ("reasoning", ("reasoning", "thinking")), ("coding", ("coding", "code"))):
            if any(term in text for term in terms):
                capabilities.append(label)
        return capabilities

    @staticmethod
    def _category(task: str, tags: list[str], capabilities: list[str]) -> str:
        lowered = " ".join([task, *tags]).lower()
        if any(term in lowered for term in ("embedding", "feature-extraction", "sentence-similarity", "text-embeddings")):
            return "embedding"
        if "vision" in capabilities or "image-text" in lowered:
            return "vision"
        if any(term in lowered for term in ("text-generation", "text2text", "conversational", "causal-lm")) or "text" in capabilities:
            return "chat/generative"
        return "other"


def free_space(path: Path) -> int:
    return shutil.disk_usage(path).free


def download_artifact(
    artifact: GGUFArtifact,
    destination: Path,
    pause_event: Any,
    cancel_event: Any,
    progress: Optional[Callable[..., None]] = None,
) -> Path:
    """Download atomically, resuming a partial file and verifying known hashes."""
    _https_url(artifact.download_url)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / Path(artifact.name).name
    partial = target.with_name(target.name + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    if artifact.size and free_space(destination) < max(artifact.size - existing, 0):
        raise OSError("Not enough free storage for this model")
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    with requests.get(artifact.download_url, headers=headers, stream=True, timeout=(15, 60)) as response:
        _validate_response_url(response.url)
        resumed = existing > 0 and response.status_code == 206
        if existing and not resumed:
            existing = 0
            partial.unlink(missing_ok=True)
        response.raise_for_status()
        total = _response_total_bytes(response, existing, artifact.size, resumed)
        if artifact.size and total > artifact.size:
            partial.unlink(missing_ok=True)
            raise ValueError("Model response exceeds the declared artifact size")
        mode = "ab" if existing else "wb"
        completed = existing
        checked_space_at = existing
        started_at = time.monotonic()
        last_report_at = started_at
        last_report_bytes = completed
        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if cancel_event.is_set():
                    raise InterruptedError("Download canceled")
                while pause_event.is_set() and not cancel_event.is_set():
                    time.sleep(0.25)
                if cancel_event.is_set():
                    raise InterruptedError("Download canceled")
                if chunk:
                    handle.write(chunk)
                    completed += len(chunk)
                    if artifact.size and completed > artifact.size:
                        handle.close()
                        partial.unlink(missing_ok=True)
                        raise ValueError("Model download exceeded the declared artifact size")
                    completed = max(completed, 0)
                    if completed - checked_space_at >= 16 * 1024 * 1024:
                        if total and free_space(destination) < max(total - completed, 0):
                            raise OSError("Free storage became insufficient during download")
                        checked_space_at = completed
                    if progress:
                        now = time.monotonic()
                        elapsed = max(now - started_at, 0.001)
                        instantaneous = (completed - existing) / elapsed
                        if now - last_report_at >= 0.1 or completed == total:
                            recent_elapsed = max(now - last_report_at, 0.001)
                            recent_rate = (completed - last_report_bytes) / recent_elapsed
                            speed = recent_rate if last_report_bytes != completed else instantaneous
                            try:
                                progress(completed, total, max(speed, 0.0))
                            except TypeError:
                                progress(completed, total)
                            last_report_at = now
                            last_report_bytes = completed
    if artifact.sha256:
        digest = hashlib.sha256()
        with partial.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != artifact.sha256.lower():
            partial.unlink(missing_ok=True)
            raise ValueError("SHA-256 checksum verification failed")
    os.replace(partial, target)
    return target


def _response_total_bytes(response: requests.Response, existing: int, artifact_size: int, resumed: bool) -> int:
    """Normalize full and ranged HTTP lengths into one absolute file size."""
    content_range = response.headers.get("Content-Range", "")
    match = re.search(r"bytes\s+\d+-\d+/(\d+)", content_range)
    if match:
        return max(int(match.group(1)), existing)
    content_length = int(response.headers.get("Content-Length") or 0)
    if resumed:
        return max(artifact_size, existing + content_length)
    return max(artifact_size, content_length, existing)