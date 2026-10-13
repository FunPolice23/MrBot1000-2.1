"""tests/test_dual_brain_runtime.py — Canonical dual-brain runtime (v2.1).

Offline/mock-first: no real llama-server or network is required. Health probes
use a tiny local HTTP server or are exercised purely in the offline path.
"""

import http.server
import json
import os
import threading
import unittest

from agents.runtime.dual_brain import (
    BrainRole,
    BrainConfig,
    DualBrainRuntime,
    build_config,
    default_contract,
    PROVIDER_LLAMACPP,
    PROVIDER_OLLAMA,
    PROVIDER_KOBOLDCPP,
    PROVIDER_VLLM,
    choose_cpu_decision_model,
    apply_hardware_fallback,
    estimate_model_size_b,
    is_cpu_decision_model,
)
from agents.providers.provider_manager import supported_tensor_types


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
    def test_tensor_types_are_conservative_for_old_cuda(self):
        self.assertNotIn("bf16", supported_tensor_types("7.5"))
        self.assertIn("q4_0", supported_tensor_types("7.5"))

    def test_tensor_types_include_bf16_for_ampere_and_newer(self):
        self.assertIn("bf16", supported_tensor_types("8.6"))

    def test_cpu_tensor_types_do_not_require_cuda(self):
        self.assertEqual(supported_tensor_types(cpu=True), ["f32", "f16", "q8_0", "q4_0"])

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

    def test_perf_flag_prints_token_timings_by_default(self):
        # v2.1.37 (ARCH-ENG-044): --perf is passed by default so a visible
        # console shows live prompt-eval + token-generation timings, not just
        # the load banner.
        cfg = build_config(BrainRole.BIG, {})
        command = cfg.build_llama_command(model_path="big.gguf")
        self.assertIn("--perf", command)

    def test_perf_flag_is_configurable_off(self):
        cfg = build_config(BrainRole.BIG, {"BIG_BRAIN_SHOW_PERF": "false"})
        command = cfg.build_llama_command(model_path="big.gguf")
        self.assertNotIn("--perf", command)

    def test_context_shift_enabled_emits_flag(self):
        # v2.1.64 (ARCH-ENG-075): --context-shift lets llama.cpp roll the
        # context window forward when a conversation exceeds --ctx-size instead
        # of erroring "context length exceeded" mid-dialogue. Without it a long
        # Chat/Dialogue thread dies on the question that overflows the window.
        cfg = build_config(BrainRole.BIG, {"BIG_BRAIN_CONTEXT_SHIFT": "true"})
        command = cfg.build_llama_command(model_path="big.gguf")
        self.assertIn("--context-shift", command)
        self.assertNotIn("--no-context-shift", command)

    def test_context_shift_disabled_emits_negative_flag(self):
        cfg = build_config(BrainRole.BIG, {"BIG_BRAIN_CONTEXT_SHIFT": "false"})
        command = cfg.build_llama_command(model_path="big.gguf")
        self.assertIn("--no-context-shift", command)
        self.assertNotIn("--context-shift", command)

    def test_context_shift_unset_omits_flag(self):
        # Off-by-default: an untouched config is byte-identical to before, so
        # llama.cpp keeps its own default (disabled) and nothing changes.
        cfg = build_config(BrainRole.BIG, {})
        command = cfg.build_llama_command(model_path="big.gguf")
        self.assertNotIn("--context-shift", command)
        self.assertNotIn("--no-context-shift", command)

    def test_context_shift_applies_to_small_brain(self):
        cfg = build_config(BrainRole.SMALL, {"SMALL_BRAIN_CONTEXT_SHIFT": "true"})
        command = cfg.build_llama_command(model_path="small.gguf")
        self.assertIn("--context-shift", command)

    def test_cpu_decision_model_policy_prefers_configured_small_model(self):
        self.assertEqual(estimate_model_size_b("LFM2.5-1.2B-Q4.gguf"), 1.2)
        self.assertTrue(is_cpu_decision_model("qwen2.5-1.5b-instruct.gguf"))
        self.assertFalse(is_cpu_decision_model("qwen3-4b-instruct.gguf"))
        self.assertEqual(
            choose_cpu_decision_model(
                "qwen2.5-1.5b-instruct.gguf",
                ["qwen3-4b-instruct.gguf", "tinyllama-1.1b-chat.gguf"],
            ),
            "qwen2.5-1.5b-instruct.gguf",
        )

    def test_cpu_decision_model_policy_selects_smallest_discovered_model(self):
        self.assertEqual(
            choose_cpu_decision_model(
                "qwen3-8b-instruct.gguf",
                ["qwen3-4b-instruct.gguf", "tinyllama-1.1b-chat.gguf"],
            ),
            "tinyllama-1.1b-chat.gguf",
        )

    def test_decision_support_flag_is_configurable(self):
        cfg = build_config(BrainRole.SMALL, {"SMALL_BRAIN_DECISION_SUPPORT": "true"})
        self.assertTrue(cfg.decision_support_only)

    def test_small_brain_falls_back_to_cpu_without_second_gpu(self):
        cfg = build_config(BrainRole.SMALL, {"SMALL_BRAIN_GPU_LAYERS": "-1"})
        apply_hardware_fallback(cfg, {0})
        self.assertEqual(cfg.gpu_layers, 0)
        self.assertEqual(cfg.gpu_label, "CPU / System RAM")
        self.assertTrue(cfg.decision_support_only)

    def test_missing_gpu_overrides_stale_positive_gpu_layers(self):
        cfg = build_config(BrainRole.SMALL, {"SMALL_BRAIN_GPU_LAYERS": "20"})
        apply_hardware_fallback(cfg, {0})
        self.assertEqual(cfg.gpu_layers, 0)

    def test_small_brain_keeps_auto_gpu_when_second_gpu_exists(self):
        cfg = build_config(BrainRole.SMALL, {"SMALL_BRAIN_GPU_LAYERS": "-1"})
        apply_hardware_fallback(cfg, {0, 1})
        self.assertEqual(cfg.gpu_layers, -1)
        self.assertFalse(cfg.decision_support_only)

    def test_small_brain_recovers_gpu_after_cpu_fallback(self):
        # A brain forced to CPU (gpu_layers=0) while its GPU was unplugged must
        # recover to auto-offload once that GPU is detected again — otherwise the
        # stale SMALL_BRAIN_GPU_LAYERS=0 in .env keeps it on CPU forever.
        cfg = build_config(BrainRole.SMALL, {"SMALL_BRAIN_GPU_LAYERS": "0"})
        self.assertEqual(cfg.gpu_layers, 0)
        apply_hardware_fallback(cfg, {0, 1})
        self.assertEqual(cfg.gpu_layers, -1)
        self.assertFalse(cfg.decision_support_only)

    def test_small_brain_stays_cpu_when_gpu_still_missing(self):
        # Recovery must NOT fire when the target GPU is genuinely absent.
        cfg = build_config(BrainRole.SMALL, {"SMALL_BRAIN_GPU_LAYERS": "0"})
        apply_hardware_fallback(cfg, {0})
        self.assertEqual(cfg.gpu_layers, 0)
        self.assertEqual(cfg.gpu_label, "CPU / System RAM")

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
    def test_kv_cache_and_batch_are_independent_per_brain(self):
        rt = DualBrainRuntime.from_env({
            "BIG_BRAIN_KV_CACHE": "q4_0",
            "BIG_BRAIN_BATCH": "4096",
            "SMALL_BRAIN_KV_CACHE": "f16",
            "SMALL_BRAIN_BATCH": "512",
        })
        self.assertEqual(rt.config(BrainRole.BIG).kv_cache, "q4_0")
        self.assertEqual(rt.config(BrainRole.BIG).batch, 4096)
        self.assertEqual(rt.config(BrainRole.SMALL).kv_cache, "f16")
        self.assertEqual(rt.config(BrainRole.SMALL).batch, 512)

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
        self.assertIsNone(health["selected_model_available"])
        self.assertEqual(health["model_status"], "unselected")

    def test_health_marks_selected_model_available_without_changing_selection(self):
        rt = DualBrainRuntime.from_env({
            "BIG_BRAIN_URL": f"http://127.0.0.1:{self._server.port}/v1",
            "BIG_BRAIN_MODEL": "qwen3-27b",
        })
        health = rt.health(BrainRole.BIG)
        self.assertTrue(health["selected_model_available"])
        self.assertEqual(health["model_status"], "available")
        self.assertEqual(rt.model(BrainRole.BIG), "qwen3-27b")

    def test_health_marks_stale_selected_model_without_silent_fallback(self):
        rt = DualBrainRuntime.from_env({
            "BIG_BRAIN_URL": f"http://127.0.0.1:{self._server.port}/v1",
            "BIG_BRAIN_MODEL": "stale-model",
        })
        health = rt.health(BrainRole.BIG)
        self.assertFalse(health["selected_model_available"])
        self.assertEqual(health["model_status"], "stale")
        self.assertEqual(health["model"], "stale-model")
        self.assertEqual(rt.model(BrainRole.BIG), "stale-model")

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


def _placement(role, device_id, index, name, mem_gb, port, is_cpu=False, label=""):
    return {
        "role": role, "device_id": device_id, "kind": "cpu" if is_cpu else "gpu",
        "index": index, "name": name, "memory_gb": mem_gb, "is_cpu": is_cpu,
        "port": port, "label": label or name,
    }


class TestNBrainSlots(unittest.TestCase):
    """N-brain slot store (Phase 1). Slots 0/1 are the BIG/SMALL role configs;
    slots 2+ are built from extra detected-device placements."""

    def test_default_slots_are_the_two_role_configs(self):
        rt = DualBrainRuntime.from_env({})
        self.assertEqual(len(rt.slots()), 2)
        self.assertIs(rt.slot_config(0), rt.config(BrainRole.BIG))
        self.assertIs(rt.slot_config(1), rt.config(BrainRole.SMALL))

    def test_slot_config_out_of_range_returns_none(self):
        rt = DualBrainRuntime.from_env({})
        self.assertIsNone(rt.slot_config(5))
        self.assertIsNone(rt.slot_config(-1))

    def test_sync_slots_grows_to_four_placements(self):
        rt = DualBrainRuntime.from_env({})
        placements = [
            _placement("big", "gpu:AAA", 0, "RTX 5060 Ti", 16, 1234),
            _placement("big", "gpu:BBB", 2, "RTX 4090", 24, 1235),
            _placement("small", "gpu:CCC", 1, "GTX 1660", 6, 1236),
            _placement("big", "cpu", -1, "CPU", 48, 1237, is_cpu=True,
                       label="CPU / System RAM (48 GB)"),
        ]
        slots = rt.sync_slots(placements)
        self.assertEqual(len(slots), 4)
        # Slots 0/1 keep object identity with the role configs.
        self.assertIs(slots[0], rt.config(BrainRole.BIG))
        self.assertIs(slots[1], rt.config(BrainRole.SMALL))
        # Slot 0/1 device + port follow the placement.
        self.assertEqual(slots[0].device_id, "gpu:AAA")
        self.assertEqual(slots[0].port, 1234)
        self.assertEqual(slots[1].device_id, "gpu:BBB")
        self.assertEqual(slots[1].port, 1235)
        # Slot 2+ are freshly built with the right device/port/role.
        self.assertEqual(slots[2].device_id, "gpu:CCC")
        self.assertEqual(slots[2].port, 1236)
        self.assertEqual(slots[2].role, BrainRole.SMALL)
        self.assertIsNone(slots[2].gpu_layers)  # GPU => auto offload
        self.assertEqual(slots[3].device_id, "cpu")
        self.assertEqual(slots[3].port, 1237)
        self.assertEqual(slots[3].gpu_layers, 0)  # CPU pool => system RAM only
        self.assertTrue(slots[3].decision_support_only)

    def test_sync_slots_preserves_gui_fields_on_slots_0_1(self):
        rt = DualBrainRuntime.from_env({})
        # Simulate an operator having picked a model + context on the Big Brain.
        rt.set_model(BrainRole.BIG, "my-big-model")
        rt.config(BrainRole.BIG).context = 40000
        placements = [
            _placement("big", "gpu:AAA", 0, "RTX 5060 Ti", 16, 1234),
            _placement("small", "gpu:CCC", 1, "GTX 1660", 6, 1235),
        ]
        rt.sync_slots(placements)
        big = rt.config(BrainRole.BIG)
        self.assertEqual(big.model, "my-big-model")   # operator choice kept
        self.assertEqual(big.context, 40000)          # operator choice kept
        self.assertEqual(big.device_id, "gpu:AAA")    # device re-seeded
        self.assertEqual(big.gpu_label, "RTX 5060 Ti")  # label re-seeded

    def test_sync_slots_never_drops_below_two(self):
        rt = DualBrainRuntime.from_env({})
        # One device enabled => still keep both role configs as slots 0/1.
        slots = rt.sync_slots([_placement("big", "gpu:AAA", 0, "Card", 16, 1234)])
        self.assertEqual(len(slots), 2)
        self.assertIs(slots[0], rt.config(BrainRole.BIG))
        self.assertIs(slots[1], rt.config(BrainRole.SMALL))

    def test_sync_slots_shrinks_when_devices_disabled(self):
        rt = DualBrainRuntime.from_env({})
        four = [
            _placement("big", "gpu:A", 0, "A", 16, 1234),
            _placement("big", "gpu:B", 1, "B", 16, 1235),
            _placement("small", "gpu:C", 2, "C", 6, 1236),
            _placement("big", "cpu", -1, "CPU", 48, 1237, is_cpu=True),
        ]
        self.assertEqual(len(rt.sync_slots(four)), 4)
        # Operator disables two devices -> only two placements.
        two = four[:2]
        self.assertEqual(len(rt.sync_slots(two)), 2)

    def test_slot_for_device_lookup(self):
        rt = DualBrainRuntime.from_env({})
        placements = [
            _placement("big", "gpu:AAA", 0, "A", 16, 1234),
            _placement("small", "gpu:CCC", 1, "C", 6, 1235),
            _placement("small", "gpu:DDD", 2, "D", 6, 1236),
        ]
        rt.sync_slots(placements)
        self.assertIs(rt.slot_for_device("gpu:AAA"), rt.slots()[0])
        self.assertIs(rt.slot_for_device("gpu:DDD"), rt.slots()[2])
        self.assertIsNone(rt.slot_for_device("gpu:NOPE"))
        self.assertIsNone(rt.slot_for_device(""))

    def test_sync_slots_is_resilient_to_bad_placements(self):
        rt = DualBrainRuntime.from_env({})
        # A malformed placement must not raise or corrupt the store.
        slots = rt.sync_slots([{"garbage": True}, _placement("big", "gpu:A", 0, "A", 16, 1234)])
        self.assertGreaterEqual(len(slots), 2)


class TestBuildSlotConfig(unittest.TestCase):
    def test_gpu_placement_uses_auto_offload_and_big_context(self):
        from agents.runtime.dual_brain import build_slot_config
        cfg = build_slot_config(
            _placement("big", "gpu:AAA", 3, "Big Card", 24, 1240), 2, BrainRole.BIG)
        self.assertEqual(cfg.slot, 2)
        self.assertEqual(cfg.device_id, "gpu:AAA")
        self.assertEqual(cfg.device, 3)
        self.assertEqual(cfg.port, 1240)
        self.assertIsNone(cfg.gpu_layers)
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:1240/v1")
        self.assertFalse(cfg.decision_support_only)

    def test_cpu_placement_forces_system_ram(self):
        from agents.runtime.dual_brain import build_slot_config
        cfg = build_slot_config(
            _placement("small", "cpu", -1, "CPU", 48, 1241, is_cpu=True), 3,
            BrainRole.SMALL)
        self.assertEqual(cfg.gpu_layers, 0)
        self.assertTrue(cfg.decision_support_only)
        self.assertEqual(cfg.device, 0)  # no CUDA device referenced


if __name__ == "__main__":
    unittest.main()
