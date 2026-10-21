"""Cloud-provider lifecycle: auth headers on the probe + truthful load/unload.

ARCH-ENG-138. Two observed defects, both reproduced by execution before the fix:

1. ``check_endpoint`` built a bare ``urllib.request.Request(url)`` with NO
   ``Authorization`` header, so a cloud ``/v1/models`` probe got a 401 and the
   Providers & GPU row showed "Stopped" forever even with a valid key.
2. ``load_provider_model`` / ``unload_provider_model`` returned
   ``(False, "<provider> does not expose a model-load API")`` for every cloud
   provider, and ``provider_lifecycle_backend._start_external_brain`` routes all
   non-llamacpp roles through that path — so "Start" on a cloud brain always
   logged a failure and could never reach Running.

Both tests target BEHAVIOUR and fail if either defect is reintroduced. No test
here performs a real network call: the HTTP layer is stubbed.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.providers import provider_lifecycle as pl  # noqa: E402
from agents.providers.provider_lifecycle import ProviderStatusChecker  # noqa: E402

_CLOUD = ("openai", "groq", "openrouter", "together", "nvidia_nim")
_LOCAL = ("llamacpp", "ollama", "lmstudio", "vllm", "koboldcpp")


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class TestAuthHeaders(unittest.TestCase):
    """The cloud probe must carry a Bearer token; a local one must not."""

    def setUp(self):
        self._env = dict(os.environ)
        for k in list(os.environ):
            if k.endswith("_API_KEY"):
                os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_cloud_probe_carries_bearer_header(self):
        os.environ["OPENAI_API_KEY"] = "sk-test-abc123"
        headers = ProviderStatusChecker._auth_headers("openai")
        self.assertEqual(headers.get("Authorization"), "Bearer sk-test-abc123")

    def test_local_probe_carries_no_auth_header(self):
        """An on-machine server has no auth; sending a token would be wrong."""
        os.environ["OPENAI_API_KEY"] = "sk-test-abc123"
        for provider in _LOCAL:
            with self.subTest(provider=provider):
                self.assertEqual(
                    ProviderStatusChecker._auth_headers(provider), {})

    def test_no_headers_without_a_key(self):
        self.assertEqual(ProviderStatusChecker._auth_headers("openai"), {})
        self.assertEqual(ProviderStatusChecker._auth_headers(""), {})

    def test_check_endpoint_sends_the_header(self):
        """The header must reach urllib, not just be computable."""
        os.environ["OPENAI_API_KEY"] = "sk-test-abc123"
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["auth"] = (req.headers or {}).get("Authorization")
            return _FakeResponse(b'{"data": [{"id": "gpt-4o-mini"}]}')

        with mock.patch.object(pl.urllib.request, "urlopen", fake_urlopen):
            ProviderStatusChecker.clear_cache()
            ok, models = ProviderStatusChecker.check_endpoint(
                "https://api.openai.com/v1/models", provider="openai")
        self.assertTrue(ok)
        self.assertEqual(seen.get("auth"), "Bearer sk-test-abc123")
        self.assertIn("gpt-4o-mini", models)

    def test_check_endpoint_without_auth_still_probes_locally(self):
        """Local callers (no provider kwarg) keep the old unauthenticated shape."""
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["auth"] = (req.headers or {}).get("Authorization")
            return _FakeResponse(b'{"data": []}')

        with mock.patch.object(pl.urllib.request, "urlopen", fake_urlopen):
            ok, _ = ProviderStatusChecker.check_endpoint("http://127.0.0.1:1234/v1/models")
        self.assertTrue(ok)
        self.assertIsNone(seen.get("auth"))

    def test_key_is_never_printed_by_the_header_builder(self):
        secret = "sk-LEAK-ME-999"
        os.environ["GROQ_API_KEY"] = secret
        buf = io.StringIO()
        with redirect_stdout(buf):
            ProviderStatusChecker._auth_headers("groq")
        self.assertNotIn(secret, buf.getvalue())


class TestCloudLoadUnload(unittest.TestCase):
    """A cloud model IS available remotely — load/unload must not report failure."""

    def test_cloud_load_is_a_truthful_noop_success(self):
        for provider in _CLOUD:
            with self.subTest(provider=provider):
                ok, msg = ProviderStatusChecker.load_provider_model(
                    provider, "https://example.invalid/v1", "some-model")
                self.assertTrue(
                    ok,
                    f"Start on a cloud brain must not fail — {msg}")
                self.assertIn("remotely", msg)

    def test_cloud_unload_is_a_truthful_noop_success(self):
        for provider in _CLOUD:
            with self.subTest(provider=provider):
                ok, msg = ProviderStatusChecker.unload_provider_model(
                    provider, "https://example.invalid/v1", "some-model")
                self.assertTrue(ok, f"Stop on a cloud brain must not fail — {msg}")

    def test_no_network_call_is_made_for_cloud_load(self):
        """The no-op must actually be a no-op — no HTTP at all."""
        with mock.patch.object(
                pl.urllib.request, "urlopen",
                side_effect=AssertionError("cloud load must not hit the network")):
            ok, _ = ProviderStatusChecker.load_provider_model(
                "openai", "https://example.invalid/v1", "gpt-4o-mini")
        self.assertTrue(ok)

    def test_unknown_provider_still_fails_explicitly(self):
        """The no-op is scoped to KNOWN cloud vendors only.

        An unrecognised provider must keep its explicit failure rather than
        silently becoming a fake success — that would be fabrication.
        """
        ok, msg = ProviderStatusChecker.load_provider_model(
            "totally-made-up-vendor", "https://example.invalid/v1", "m")
        self.assertFalse(ok)
        self.assertIn("does not expose a model-load API", msg)

    def test_local_provider_load_still_attempts_http(self):
        """lmstudio/ollama must keep their real load calls (regression guard)."""
        with mock.patch.object(
                ProviderStatusChecker, "_post_json",
                return_value=(True, "ok")) as post:
            ok, _ = ProviderStatusChecker.load_provider_model(
                "lmstudio", "http://127.0.0.1:1234/v1", "my-model")
        self.assertTrue(ok)
        self.assertTrue(post.called, "lmstudio load must still POST")
        self.assertIn("/api/v1/models/load", post.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
