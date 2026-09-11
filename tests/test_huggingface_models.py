import hashlib
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from agents.huggingface_models import (
    GGUFArtifact,
    HuggingFaceModelService,
    download_artifact,
    _response_total_bytes,
)


def test_list_name_classification_handles_dense_and_moe_variants():
    service = HuggingFaceModelService(Mock())
    dense = service._summary_model({
        "id": "Qwen/Qwen3.8-27B-GGUF",
        "pipeline_tag": "image-text-to-text",
        "tags": ["gguf", "qwen3_5"],
        "siblings": [{"rfilename": "Qwen3.8-27B-Q4_K_M.gguf", "size": 1}],
    })
    moe = service._summary_model({
        "id": "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF",
        "pipeline_tag": "text-generation",
        "tags": ["gguf", "qwen3"],
        "siblings": [{"rfilename": "Qwen3-Coder-30B-A3B-Q4_K_M.gguf", "size": 1}],
    })
    assert dense.type_label == "Dense"
    assert moe.type_label == "MoE"


def test_inspect_keeps_chat_gguf_and_excludes_mmproj():
    response = Mock()
    response.url = "https://huggingface.co/api/models/acme/demo"
    response.json.return_value = {
        "id": "acme/demo-7B",
        "downloads": 42,
        "siblings": [
            {"rfilename": "demo-7B-Q4_K_M.gguf", "size": 100},
            {"rfilename": "mmproj-model-f16.gguf", "size": 20},
        ],
        "cardData": {"license": "apache-2.0"},
    }
    response.raise_for_status = Mock()
    session = Mock()
    session.get.return_value = response

    model = HuggingFaceModelService(session).inspect("acme/demo-7B")

    assert [item.name for item in model.artifacts] == ["demo-7B-Q4_K_M.gguf"]
    assert model.params_billion == 7
    assert model.artifacts[0].quantization == "Q4_K_M"
    assert model.license == "apache-2.0"


def test_api_redirect_to_http_is_rejected():
    response = Mock()
    response.url = "http://example.invalid/api/models"
    session = Mock()
    session.get.return_value = response

    try:
        HuggingFaceModelService(session).search("qwen", limit=1)
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("non-HTTPS API redirect was accepted")


def test_api_redirect_to_untrusted_https_host_is_rejected():
    response = Mock()
    response.url = "https://evil.example/api/models"
    session = Mock()
    session.get.return_value = response

    try:
        HuggingFaceModelService(session).search("qwen", limit=1)
    except ValueError as exc:
        assert "trusted HTTPS" in str(exc)
    else:
        raise AssertionError("untrusted HTTPS API redirect was accepted")


def test_search_uses_full_paginated_list_without_n_plus_one_inspection():
    response = Mock()
    response.url = "https://huggingface.co/api/models?filter=gguf&full=true"
    response.raise_for_status = Mock()
    response.json.return_value = [
        {
            "id": "acme/one-7B-GGUF",
            "downloads": 10,
            "pipeline_tag": "text-generation",
            "tags": ["gguf"],
            "siblings": [{"rfilename": "one-Q4_K_M.gguf", "size": 123}],
        },
        {
            "id": "acme/two-3B-GGUF",
            "downloads": 9,
            "pipeline_tag": "text-generation",
            "tags": ["gguf"],
            "siblings": [{"rfilename": "two-Q8_0.gguf", "size": 456}],
        },
    ]
    session = Mock()
    session.get.return_value = response

    models = HuggingFaceModelService(session).search(limit=100, page=3)

    assert len(models) == 2
    assert models[0].artifacts[0].name == "one-Q4_K_M.gguf"
    params = session.get.call_args.kwargs["params"]
    assert params["full"] == "true"
    assert params["limit"] == 100
    assert params["offset"] == 300
    assert session.get.call_count == 1


def test_download_verifies_checksum_and_renames_atomically(tmp_path: Path):
    payload = b"verified model bytes"
    response = Mock()
    response.url = "https://huggingface.co/acme/demo/resolve/main/demo.gguf"
    response.status_code = 200
    response.headers = {"Content-Length": str(len(payload))}
    response.iter_content.return_value = [payload]
    response.raise_for_status = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    artifact = GGUFArtifact(
        name="demo.gguf",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        download_url=response.url,
    )

    with patch("agents.huggingface_models.requests.get", return_value=response):
        path = download_artifact(artifact, tmp_path, threading.Event(), threading.Event())

    assert path.read_bytes() == payload
    assert not (tmp_path / "demo.gguf.part").exists()


def test_download_removes_partial_file_when_response_is_oversized(tmp_path: Path):
    response = Mock()
    response.url = "https://huggingface.co/acme/demo/resolve/main/demo.gguf"
    response.status_code = 200
    response.headers = {"Content-Length": "20"}
    response.raise_for_status = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [b"too much data"]
    artifact = GGUFArtifact(
        name="demo.gguf", size=4, download_url=response.url)

    with patch("agents.huggingface_models.requests.get", return_value=response):
        try:
            download_artifact(artifact, tmp_path, threading.Event(), threading.Event())
        except ValueError as exc:
            assert "exceeds" in str(exc) or "exceeded" in str(exc)
        else:
            raise AssertionError("oversized model response was accepted")
    assert not (tmp_path / "demo.gguf.part").exists()


def test_response_total_uses_absolute_content_range_for_resume():
    response = Mock()
    response.headers = {"Content-Range": "bytes 100-199/1000", "Content-Length": "100"}
    assert _response_total_bytes(response, 100, 1000, True) == 1000


def test_response_total_does_not_add_existing_to_full_content_length():
    response = Mock()
    response.headers = {"Content-Length": "1000"}
    assert _response_total_bytes(response, 100, 1000, False) == 1000