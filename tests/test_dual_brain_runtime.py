"""tests/test_dual_brain_runtime.py — Canonical dual-brain runtime (v2.1).

Offline/mock-first: no real llama-server or network is required. Health probes
use a tiny local HTTP server or are exercised purely in the offline path.
"""

import http.server
import json
import os
import threading
import unittest

from agents.dual_brain_runtime import (
    BrainRole,
    BrainConfig,
    DualBrainRuntime,
    build_config,
    default_contract,
    PROVIDER_LLAMACPP,
    PROVIDER_OLLAMA,
    PROVIDER_KOBOLDCPP,
    PROVIDER_VLLM,
)


class _FakeModelsHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps({"data": [{"id": "qwen3-27b"}, {"id": "gemma-4b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        pass


class _Server:
    def __init__(self):
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _FakeModelsHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class TestRoleDefaults(unittest.TestCase):
    def test_custom_display_names_are_role_specific(self):
        big = build_config(BrainRole.BIG, {"BIG_BRAIN_NAME": "Orion"})
        small = build_config(BrainRole.SMALL, {"SMALL_BRAIN_NAME": "Lumen"})

        self.assertEqual(big.display_name, "Orion")
        self.assertEqual(small.display_name, "Lumen")

    def test_big_brain_defaults_device0_port1234(self):
        cfg = build_config(BrainRole.BIG, {})
        self.assertEqual(cfg.device, 0)
        self.assertEqual(cfg.port, 1234)
        self.assertEqual(cfg.provider, PROVIDER_LLAMACPP)

    def test_small_brain_defaults_device1_port1235(self):
        cfg = build_config(BrainRole.SMALL, {})
        self.assertEqual(cfg.device, 1)
        self.assertEqual(cfg.port, 1235)

    def test_small_brain_cpu_only_command_avoids_missing_cuda_device(self):
        cfg = build_config(BrainRole.SMALL, {
            "SMALL_BRAIN_GPU_LAYERS": "0",
        })
        command = cfg.build_llama_command(model_path="small.gguf")
        self.assertNotIn("--device", command)
        self.assertIn("--n-gpu-layers", command)
        self.assertEqual(command[command.index("--n-gpu-layers") + 1], "0")

    def test_default_contract_has_both_roles(self):
        contract = default_contract()
        self.assertIn("big", contract)
        self.assertIn("small", contract)
        self.assertEqual(contract["big"]["device"], 0)
        self.assertEqual(contract["small"]["device"], 1)


class TestIsolation(unittest.TestCase):
    def test_default_isolation_is_isolated(self):
        rt = DualBrainRuntime.from_env({})
        report = rt.validate_isolation()
        self.assertTrue(report["isolated"])
        self.assertTrue(report["big_device_ok"])
        self.assertTrue(report["small_device_ok"])
        self.assertTrue(report["distinct_ports"])

    def test_broken_isolation_detected_when_small_uses_device0(self):
        big = build_config(BrainRole.BIG, {})
        small = build_config(BrainRole.SMALL, {"SMALL_BRAIN_DEVICE": "0"})
        rt = DualBrainRuntime(big=big, small=small)
        report = rt.validate_isolation()
        self.assertFalse(report["isolated"])
        self.assertFalse(report["small_device_ok"])

    def test_cpu_only_small_brain_is_valid_without_gpu1(self):
        big = build_config(BrainRole.BIG, {})
        small = build_config(BrainRole.SMALL, {"SMALL_BRAIN_GPU_LAYERS": "0"})
        report = DualBrainRuntime(big=big, small=small).validate_isolation()
        self.assertTrue(report["small_cpu_only"])
        self.assertTrue(report["small_device_ok"])

    def test_shared_port_breaks_isolation(self):
        big = build_config(BrainRole.BIG, {"BIG_BRAIN_PORT": "1234"})
        small = build_config(BrainRole.SMALL, {"SMALL_BRAIN_PORT": "1234"})
        rt = DualBrainRuntime(big=big, small=small)
        self.assertFalse(rt.validate_isolation()["distinct_ports"])


class TestConfigFromEnv(unittest.TestCase):
    def test_env_overrides_endpoint_and_model(self):
        env = {
            "BIG_BRAIN_URL": "http://127.0.0.1:9000/v1",
            "BIG_BRAIN_MODEL": "my-model",
            "BIG_BRAIN_CONTEXT": "8192",
        }
        rt = DualBrainRuntime.from_env(env)
        self.assertEqual(rt.endpoint(BrainRole.BIG), "http://127.0.0.1:9000/v1")
        self.assertEqual(rt.model(BrainRole.BIG), "my-model")
        self.assertEqual(rt.config(BrainRole.BIG).context, 8192)

    def test_unknown_provider_falls_back_to_llamacpp(self):
        cfg = build_config(BrainRole.BIG, {"BIG_BRAIN_PROVIDER": "nonsense"})
        self.assertEqual(cfg.provider, PROVIDER_LLAMACPP)

    def test_ollama_provider_uses_api_tags_path(self):
        cfg = build_config(BrainRole.SMALL, {
            "SMALL_BRAIN_PROVIDER": "ollama",
            "SMALL_BRAIN_URL": "http://127.0.0.1:11434",
        })
        self.assertEqual(cfg.provider, PROVIDER_OLLAMA)
        self.assertEqual(cfg.models_path, "http://127.0.0.1:11434/api/tags")

    def test_vllm_provider_normalizes_shared_base_url(self):
        cfg = build_config(BrainRole.BIG, {
            "BIG_BRAIN_PROVIDER": "vllm",
            "VLLM_BASE_URL": "http://127.0.0.1:8000/v1",
        })
        self.assertEqual(cfg.provider, PROVIDER_VLLM)
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:8000/v1")
        self.assertEqual(cfg.models_path, "http://127.0.0.1:8000/v1/models")

    def test_koboldcpp_provider_uses_native_model_path(self):
        cfg = build_config(BrainRole.BIG, {
            "BIG_BRAIN_PROVIDER": "koboldcpp",
            "KOBOLDCPP_BASE_URL": "http://127.0.0.1:5001",
        })
        self.assertEqual(cfg.provider, PROVIDER_KOBOLDCPP)
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:5001")
        self.assertEqual(cfg.models_path, "http://127.0.0.1:5001/api/v1/model")


class TestOfflineHealth(unittest.TestCase):
    def test_offline_is_reachable_false_no_raise(self):
        env = {"BIG_BRAIN_URL": "http://127.0.0.1:1/v1", "BIG_BRAIN_ENABLED": "true"}
        rt = DualBrainRuntime.from_env(env)
        # Port 1 is closed; probe must degrade, not raise.
        health = rt.health(BrainRole.BIG)
        self.assertFalse(health["reachable"])
        self.assertEqual(health["model_count"], 0)
        self.assertIn("latency_ms", health)

    def test_disabled_role_returns_no_models(self):
        env = {"SMALL_BRAIN_ENABLED": "false"}
        rt = DualBrainRuntime.from_env(env)
        self.assertEqual(rt.list_models(BrainRole.SMALL), [])


class TestLiveHealth(unittest.TestCase):
    """Uses a real localhost HTTP server (no external network)."""

    @classmethod
    def setUpClass(cls):
        cls._server = _Server()

    @classmethod
    def tearDownClass(cls):
        cls._server.close()

    def test_health_lists_models_from_server(self):
        rt = DualBrainRuntime.from_env(
            {"BIG_BRAIN_URL": f"http://127.0.0.1:{self._server.port}/v1"})
        models = rt.list_models(BrainRole.BIG)
        self.assertEqual(set(models), {"qwen3-27b", "gemma-4b"})
        health = rt.health(BrainRole.BIG)
        self.assertTrue(health["reachable"])
        self.assertEqual(health["model_count"], 2)

    def test_snapshot_contains_isolation_and_both_roles(self):
        rt = DualBrainRuntime.from_env(
            {"BIG_BRAIN_URL": f"http://127.0.0.1:{self._server.port}/v1"})
        snap = rt.snapshot(refresh_health=True)
        self.assertIn("isolation", snap)
        self.assertIn("big", snap)
        self.assertIn("small", snap)


class TestModelSwitching(unittest.TestCase):
    def test_set_model_persists_per_role(self):
        rt = DualBrainRuntime.from_env({})
        rt.set_model(BrainRole.BIG, "qwen3-27b")
        rt.set_model(BrainRole.SMALL, "gemma-4b")
        self.assertEqual(rt.model(BrainRole.BIG), "qwen3-27b")
        self.assertEqual(rt.model(BrainRole.SMALL), "gemma-4b")
        # Switching one role must not affect the other.
        rt.set_model(BrainRole.BIG, "other")
        self.assertEqual(rt.model(BrainRole.SMALL), "gemma-4b")

    def test_set_model_invalidates_health_cache(self):
        rt = DualBrainRuntime.from_env({})
        rt.set_model(BrainRole.BIG, "x")
        health = rt.health(BrainRole.BIG)
        self.assertEqual(health["model"], "x")


if __name__ == "__main__":
    unittest.main()
