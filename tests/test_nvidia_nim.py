"""Tests for NVIDIA NIM support + OpenAI-compatible streaming/reasoning (v2.0.36).

Covers:
- NVIDIA is registered as a fetchable provider with the correct base_url.
- Live model fetch (preferred) returns the NVIDIA catalog when reachable;
  the curated FREE list is used as the offline/blocked fallback.
- OpenAICompatibleAdapter.complete() streams, captures reasoning_content
  (Nemotron enable_thinking), forwards temperature/top_p/extra_body, and
  returns ONLY the answer text.
- Non-streaming fallback path when the SDK rejects stream/extra_body (TypeError).
- Ollama / Anthropic adapters are NOT broken by the new `think` kwarg
  forwarded from base_worker.llm().
"""

import os
import sys
import unittest
from unittest import mock

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestNvidiaProviderRegistration(unittest.TestCase):
    def test_nvidia_registered(self):
        import provider_models as pm
        self.assertIn("NVIDIA", pm._PROVIDERS)
        kind, base, vendor = pm._PROVIDERS["NVIDIA"]
        self.assertEqual(kind, "nvidia")
        self.assertEqual(base, "https://integrate.api.nvidia.com/v1")
        self.assertEqual(vendor, "NVIDIA")

    def test_nvidia_is_fetchable(self):
        import provider_models as pm
        self.assertTrue(pm.is_fetchable("NVIDIA"))


class TestNvidiaFreeFallback(unittest.TestCase):
    def test_currated_free_list_all_free_and_contains_lightning(self):
        import provider_models as pm
        models = pm._nvidia_free_models()
        self.assertTrue(len(models) >= 1)
        ids = {m.id for m in models}
        self.assertIn("nvidia/nemotron-3.5-lightning-30b-a3b", ids)
        for m in models:
            self.assertTrue(m.free, f"{m.id} should be FREE")
            self.assertEqual(m.price_out_per_1m, 0.0)
            self.assertEqual(m.vendor, "NVIDIA")

    def test_fetch_fallback_used_when_live_empty(self):
        """When NVIDIA live fetch returns nothing, the curated FREE list is returned."""
        import provider_models as pm
        with mock.patch.object(pm, "_from_openai_compatible", return_value=[]), \
             mock.patch.object(pm, "_load_cache", return_value={}), \
             mock.patch.object(pm, "_save_cache"), \
             mock.patch.dict(pm._MEM_CACHE, clear=True):
            os.environ.pop("NVIDIA_API_KEY", None)
            models = pm.fetch_models("NVIDIA", "", use_cache=False)
            self.assertTrue(models)
            self.assertTrue(all(m.free for m in models))
            ids = {m.id for m in models}
            self.assertIn("nvidia/nemotron-3.5-lightning-30b-a3b", ids)


class TestNvidiaLiveFetchReachable(unittest.TestCase):
    def test_live_fetch_returns_models(self):
        """Network-dependent: NVIDIA /v1/models is public. Skips if offline/blocked."""
        import provider_models as pm
        os.environ.pop("NVIDIA_API_KEY", None)
        try:
            models = pm.fetch_models("NVIDIA", "", use_cache=False)
        except Exception:
            self.skipTest("NVIDIA /v1/models unreachable in this environment")
        self.assertGreater(len(models), 0,
                           "NVIDIA live catalog should return models")
        # Live catalog is the FULL NIM catalog (mostly paid); we must NOT label
        # unknown-price models as FREE (display "n/a"). The curated fallback is
        # what flags models free.
        for m in models:
            self.assertFalse(m.free, f"live NVIDIA model {m.id} must not be FREE")
            self.assertNotEqual(m.price_out_display, "FREE")


class TestNvidiaLiveNotFalselyFree(unittest.TestCase):
    def test_live_models_not_flagged_free(self):
        """Live NVIDIA models with unknown pricing show n/a, never FREE."""
        import provider_models as pm
        os.environ.pop("NVIDIA_API_KEY", None)
        try:
            models = pm.fetch_models("NVIDIA", "", use_cache=False)
        except Exception:
            self.skipTest("NVIDIA /v1/models unreachable in this environment")
        self.assertTrue(models)
        for m in models:
            self.assertFalse(m.free)
            self.assertNotEqual(m.price_out_display, "FREE")


class TestOpenAICompatibleStreaming(unittest.TestCase):
    def _install_fake_openai(self, stream_chunks):
        """Install a fake `openai` module that yields `stream_chunks` and records
        the last create() kwargs. Returns the fake module (also reachable at
        sys.modules['openai'])."""
        class _Delta:
            def __init__(self, reasoning=None, content=None):
                self.reasoning_content = reasoning
                self.content = content

        class _Choice:
            def __init__(self, d):
                self.delta = d

        class _Chunk:
            def __init__(self, c):
                # c is a dict like {"reasoning": ...} or {"content": ...}
                self.choices = [_Choice(_Delta(**c))]

        class _Stream:
            def __iter__(self):
                return iter([_Chunk(c) for c in stream_chunks])

        class _Completions:
            last = {}

            def create(self, **kw):
                _Completions.last = kw
                return _Stream()

        class _Chat:
            completions = _Completions()

        class _Client:
            chat = _Chat()

        class _FakeOpenAI:
            last_init = {}

            def OpenAI(self, **kw):
                _FakeOpenAI.last_init = kw
                return _Client()

            # expose inner classes for assertions
            chat = _Chat()

        return _FakeOpenAI()

    def test_streams_and_captures_reasoning_and_enable_thinking(self):
        import agents.providers.openai_compatible as oc
        fake = self._install_fake_openai([
            {"reasoning": "Let me think..."},
            {"reasoning": " step by step."},
            {"content": "The answer is 42."},
        ])
        with mock.patch.dict(sys.modules, {"openai": fake}):
            os.environ["NVIDIA_API_KEY"] = "nvapi-test"
            try:
                ad = oc.OpenAICompatibleAdapter(
                    name="nvidia", api_key_env="NVIDIA_API_KEY",
                    base_url="https://integrate.api.nvidia.com/v1",
                    default_model="nvidia/nemotron-3.5-lightning-30b-a3b")
                reasoning = []
                out = ad.complete("nvidia/nemotron-3.5-lightning-30b-a3b", "sys",
                                  "hi", 100, think=True,
                                  on_reasoning=reasoning.append)
            finally:
                os.environ.pop("NVIDIA_API_KEY", None)
        self.assertEqual(out, "The answer is 42.")
        self.assertEqual("".join(reasoning), "Let me think... step by step.")
        kw = fake.chat.completions.last
        self.assertTrue(kw.get("stream"))
        self.assertEqual(
            kw.get("extra_body", {})
            .get("chat_template_kwargs", {})
            .get("enable_thinking"), True)
        self.assertEqual(
            fake.last_init.get("base_url"),
            "https://integrate.api.nvidia.com/v1")
        self.assertEqual(fake.last_init.get("api_key"), "nvapi-test")

    def test_temperature_and_top_p_forwarded(self):
        import agents.providers.openai_compatible as oc
        fake = self._install_fake_openai([{"content": "hi"}])
        with mock.patch.dict(sys.modules, {"openai": fake}):
            os.environ["NVIDIA_API_KEY"] = "nvapi-test"
            try:
                ad = oc.OpenAICompatibleAdapter(
                    name="nvidia", api_key_env="NVIDIA_API_KEY",
                    base_url="https://integrate.api.nvidia.com/v1")
                ad.complete("m", "s", "u", 50, temperature=0.7, top_p=0.95)
            finally:
                os.environ.pop("NVIDIA_API_KEY", None)
        kw = fake.chat.completions.last
        self.assertEqual(kw.get("temperature"), 0.7)
        self.assertEqual(kw.get("top_p"), 0.95)

    def test_non_streaming_fallback_on_typeerror(self):
        """If create(**kwargs) raises TypeError (stream/extra_body unsupported),
        the adapter retries non-streaming and still returns content."""
        import agents.providers.openai_compatible as oc

        class _Resp:
            choices = [type("C", (), {"message": type("M", (), {"content": "fallback"})()})()]

        class _Completions:
            calls = []

            def create(self, **kw):
                _Completions.calls.append(kw)
                if kw.get("stream"):
                    raise TypeError("stream not supported")
                return _Resp()

        class _Chat:
            completions = _Completions()

        class _Client:
            chat = _Chat()

        class _Fake:
            def OpenAI(self, **kw):
                return _Client()

        with mock.patch.dict(sys.modules, {"openai": _Fake()}):
            os.environ["NVIDIA_API_KEY"] = "nvapi-test"
            try:
                ad = oc.OpenAICompatibleAdapter(
                    name="nvidia", api_key_env="NVIDIA_API_KEY",
                    base_url="https://integrate.api.nvidia.com/v1")
                out = ad.complete("m", "s", "u", 50, think=True)
            finally:
                os.environ.pop("NVIDIA_API_KEY", None)
            self.assertEqual(out, "fallback")
            # first call attempted stream=True, second did not (fallback).
            self.assertTrue(_Completions.calls[0].get("stream"))
            self.assertNotIn("stream", _Completions.calls[-1])


class TestOtherAdaptersUnaffected(unittest.TestCase):
    def test_ollama_ignores_think_kwarg(self):
        import agents.providers.ollama_adapter as oa
        # ollama may be unavailable; we only assert the signature accepts think.
        import inspect
        params = inspect.signature(oa.OllamaAdapter.complete).parameters
        self.assertIn("kwargs", params)

    def test_anthropic_ignores_think_kwarg(self):
        import agents.providers.anthropic_adapter as aa
        import inspect
        params = inspect.signature(aa.AnthropicAdapter.complete).parameters
        self.assertIn("kwargs", params)


class TestBaseWorkerForwardsThink(unittest.TestCase):
    def test_llm_passes_think_flag(self):
        """base_worker.llm() forwards `think` to the provider function."""
        import agents.base_worker as bw
        captured = {}

        class _FakeWorker(bw.WorkerAgent):
            def __init__(self):
                # minimal: avoid real __init__ (needs Qt/signals)
                self.log_signal = mock.Mock()
                self.db = None
                self._provider_registry = None

        # Build a fake provider function that records its kwargs + returns text.
        def fake_complete(model, system, user, max_tokens, chat=False, **kw):
            captured.update(kw)
            captured["model"] = model
            return "ok"

        w = _FakeWorker.__new__(_FakeWorker)
        w.log_signal = mock.Mock()
        w.db = None
        w._provider_registry = None
        w._max_tokens = None
        # Patch the env-driven flags used inside llm()
        with mock.patch.dict(os.environ, {
                "THINKING_ENABLED": "true", "MAX_TOKENS": "256"}), \
             mock.patch.object(bw, "context_tokens", return_value=8192), \
             mock.patch.object(bw, "estimate_tokens", return_value=10), \
             mock.patch.object(bw, "fit_prompt_to_ctx", side_effect=lambda *a, **k: a[:2]), \
             mock.patch.object(bw, "read_think_level", return_value="normal"), \
             mock.patch.object(bw, "think_budget", return_value=1024), \
             mock.patch.object(bw, "MAX_TOKENS", 256), \
             mock.patch.object(bw.WorkerAgent, "_build_providers",
                               return_value=[("nvidia", fake_complete, "", "nvidia/m")]):
            w._cost_aware_enabled = lambda: False
            w._provider_hint = lambda chat: "nvidia"
            w.last_trigger = "llm"
            out = w.llm("sys", "user", chat=False)
        self.assertEqual(out, "ok")
        self.assertIn("think", captured)
        self.assertTrue(captured["think"])


if __name__ == "__main__":
    unittest.main()
