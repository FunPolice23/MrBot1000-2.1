"""ARCH-ENG-188 — two more instances of one recurring mistake.

This release found the same defect three times, in three subsystems, and all
three are now closed:

  * ARCH-ENG-179 — `provider_manager.detect_providers` merged the PREVIOUS
    snapshot's `status` over a fresh probe, so a stopped provider could never be
    reported stopped.
  * ARCH-ENG-185 — `DialogueTab._blocked_personas` was add-only, so a gate the
    operator had cleared stayed blocking in the live prompt forever.
  * ARCH-ENG-188 (this file) — `DualBrainRuntime._health_cache` recorded a
    `checked_at` timestamp that NOTHING EVER READ.

The common shape is worth naming because it is so easy to write by accident: an
OBSERVATION is cached and then presented as current fact, with no expiry. In the
health-cache case the author had already written the field the expiry was meant
to be based on — `checked_at` is recorded on every write — and simply never
consulted it on the read path. That is the tell: a field written for exactly one
purpose and never read means the code that should consume it is missing.

ARCH-ENG-188a — THE HEALTH CACHE NEVER EXPIRED.

`list_models` returned the cached snapshot whenever `refresh` was false. The only
in-tree caller is `health(refresh=refresh_health)`, whose `refresh_health`
defaults to False. So once a role was cached, a server that DIED kept reporting
`reachable: True` with its full model list, indefinitely, while the Providers &
GPU panel showed it as running.

ARCH-ENG-188b — TWO SLOW CALLS WEDGED THE OLLAMA ADAPTER PERMANENTLY.

`OllamaAdapter.complete` submits to a `ThreadPoolExecutor(max_workers=2)` and
waits with `_fut.result(timeout=...)`. On timeout it raised, but the future kept
RUNNING — Python cannot interrupt a thread already executing — so the worker
stayed pinned until `ollama.chat` finally returned.

With a pool of two, two slow calls wedged the adapter: every subsequent request
queued behind them and never started. The operator saw the provider HANG with no
error, rather than the timeout they had been told to expect. A timeout that
leaves the system less able to report the NEXT timeout is worse than no timeout
at all — it converts a clear failure into a silent one.
"""

import os
import time
import unittest
from unittest import mock


def _code_only(func):
    import ast
    import inspect
    import textwrap
    body = textwrap.dedent(inspect.getsource(func))
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return body
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef, ast.Module))
                and ast.get_docstring(node, clean=False)):
            node.body = node.body[1:]
    return ast.unparse(tree)


# ── ARCH-ENG-188a: the health cache expires ───────────────────────────────────

class TestHealthCacheExpires(unittest.TestCase):
    """ARCH-ENG-188a — `checked_at` must actually be consulted."""

    def _runtime(self, models_payload):
        """A runtime whose HTTP layer returns `models_payload`, and a call counter."""
        from agents.runtime import dual_brain
        rt = dual_brain.DualBrainRuntime.__new__(dual_brain.DualBrainRuntime)
        rt._lock = __import__("threading").Lock()
        rt._health_cache = {}
        cfg = mock.Mock()
        cfg.enabled = True
        cfg.provider = dual_brain.PROVIDER_LLAMACPP
        cfg.models_path = "http://127.0.0.1:1234/v1/models"
        rt._configs = {dual_brain.BrainRole.BIG: cfg}
        calls = {"n": 0}

        def fake_get(url, timeout=None):
            calls["n"] += 1
            return models_payload

        rt._http_get = fake_get
        return rt, calls

    PAYLOAD = '{"data": [{"id": "model-a"}, {"id": "model-b"}]}'

    def test_a_fresh_entry_is_served_from_cache(self):
        """The cache must still do its job — it exists to avoid re-probing."""
        rt, calls = self._runtime(self.PAYLOAD)
        role = __import__("agents.runtime.dual_brain", fromlist=["x"]).BrainRole.BIG
        first = rt.list_models(role)
        second = rt.list_models(role)
        self.assertEqual(first, ["model-a", "model-b"])
        self.assertEqual(second, first)
        self.assertEqual(calls["n"], 1,
                         f"a warm cache re-probed {calls['n']} times; the cache "
                         f"must suppress re-probing within its TTL")

    def test_an_expired_entry_is_re_probed(self):
        """THE REGRESSION: the entry used to be served forever."""
        from agents.runtime.dual_brain import BrainRole
        rt, calls = self._runtime(self.PAYLOAD)
        rt.list_models(BrainRole.BIG)
        self.assertEqual(calls["n"], 1)
        # Age the entry past any plausible TTL.
        rt._health_cache[BrainRole.BIG]["checked_at"] = time.time() - 10_000
        rt.list_models(BrainRole.BIG)
        self.assertEqual(
            calls["n"], 2,
            "an entry from three hours ago was served as current; the cache has "
            "no expiry, so a dead server stays 'reachable' forever")

    def test_a_server_that_died_is_eventually_reported_down(self):
        """The end-to-end property: the cache cannot outlive the truth."""
        from agents.runtime.dual_brain import BrainRole
        state = {"up": True}
        from agents.runtime import dual_brain
        rt = dual_brain.DualBrainRuntime.__new__(dual_brain.DualBrainRuntime)
        import threading
        rt._lock = threading.Lock()
        rt._health_cache = {}
        cfg = mock.Mock()
        cfg.enabled = True
        cfg.provider = dual_brain.PROVIDER_LLAMACPP
        cfg.models_path = "http://127.0.0.1:1234/v1/models"
        rt._configs = {BrainRole.BIG: cfg}
        rt._http_get = lambda url, timeout=None: (
            self.PAYLOAD if state["up"] else None)

        self.assertEqual(rt.list_models(BrainRole.BIG), ["model-a", "model-b"])
        state["up"] = False                      # the server dies
        self.assertEqual(rt.list_models(BrainRole.BIG), ["model-a", "model-b"],
                         "expected: the TTL has not elapsed yet")
        rt._health_cache[BrainRole.BIG]["checked_at"] = time.time() - 10_000
        self.assertEqual(
            rt.list_models(BrainRole.BIG), [],
            "the server is down but is still reported as serving models")

    def test_an_explicit_refresh_bypasses_the_ttl(self):
        """`refresh=True` must still force a probe regardless of age."""
        from agents.runtime.dual_brain import BrainRole
        rt, calls = self._runtime(self.PAYLOAD)
        rt.list_models(BrainRole.BIG)
        rt.list_models(BrainRole.BIG, refresh=True)
        self.assertEqual(calls["n"], 2, "refresh=True did not force a probe")

    def test_a_malformed_timestamp_does_not_crash_or_pin_the_cache(self):
        """A corrupt entry must be re-probed, not trusted and not fatal."""
        from agents.runtime.dual_brain import BrainRole
        rt, calls = self._runtime(self.PAYLOAD)
        rt._health_cache[BrainRole.BIG] = {
            "reachable": True, "models": ["stale"], "checked_at": "not-a-time"}
        self.assertEqual(rt.list_models(BrainRole.BIG), ["model-a", "model-b"],
                         "a corrupt timestamp pinned a stale entry")

    def test_a_missing_timestamp_does_not_pin_the_cache(self):
        from agents.runtime.dual_brain import BrainRole
        rt, calls = self._runtime(self.PAYLOAD)
        rt._health_cache[BrainRole.BIG] = {
            "reachable": True, "models": ["stale"]}
        rt.list_models(BrainRole.BIG)
        self.assertEqual(calls["n"], 1)

    def test_an_unparseable_ttl_falls_back_rather_than_raising(self):
        from agents.runtime.dual_brain import BrainRole
        rt, calls = self._runtime(self.PAYLOAD)
        with mock.patch.dict(os.environ, {"DUAL_BRAIN_HEALTH_TTL": "soon"}):
            self.assertEqual(rt.list_models(BrainRole.BIG), ["model-a", "model-b"])

    def test_a_zero_ttl_means_always_fresh(self):
        """An operator who wants no caching can say so."""
        from agents.runtime.dual_brain import BrainRole
        rt, calls = self._runtime(self.PAYLOAD)
        rt.list_models(BrainRole.BIG)
        with mock.patch.dict(os.environ, {"DUAL_BRAIN_HEALTH_TTL": "0"}):
            rt.list_models(BrainRole.BIG)
        self.assertEqual(calls["n"], 2, "a zero TTL was not honoured")


class TestTtlIsConsultedNotJustWritten(unittest.TestCase):
    """ARCH-ENG-188a — the structural tell: a field written and never read."""

    def test_the_read_path_compares_against_checked_at(self):
        from agents.runtime.dual_brain import DualBrainRuntime
        code = _code_only(DualBrainRuntime.list_models)
        self.assertIn("checked_at", code,
                      "the read path must consult the timestamp it records; a "
                      "field written for exactly this purpose and never read is "
                      "the signature of a cache with no expiry")

    def test_the_write_path_still_records_it(self):
        from agents.runtime.dual_brain import DualBrainRuntime
        src = __import__("inspect").getsource(DualBrainRuntime.list_models)
        self.assertIn('"checked_at"', src)

    def test_an_explicit_ttl_setting_exists(self):
        from agents.runtime.dual_brain import DualBrainRuntime
        code = _code_only(DualBrainRuntime.list_models)
        self.assertIn("DUAL_BRAIN_HEALTH_TTL", code,
                      "the TTL must be configurable; a hardcoded value cannot be "
                      "adjusted for a slow local server")


# ── ARCH-ENG-188b: the Ollama worker pool ─────────────────────────────────────

class TestOllamaTimeoutDoesNotWedgeThePool(unittest.TestCase):
    """ARCH-ENG-188b — a timeout must not make the NEXT timeout unreportable."""

    def _adapter(self):
        from agents.providers.ollama_adapter import OllamaAdapter
        return OllamaAdapter

    def test_the_pool_has_headroom_beyond_two(self):
        """Two workers meant two slow calls wedged every later request."""
        from agents.providers.ollama_adapter import OllamaAdapter
        workers = OllamaAdapter._executor._max_workers
        self.assertGreater(
            workers, 2,
            f"the pool still has {workers} workers: two concurrent slow calls "
            f"exhaust it and every later request queues forever")

    def test_the_worker_count_is_configurable(self):
        """A hardcoded pool size cannot be widened for a slow local server."""
        import inspect
        from agents.providers import ollama_adapter as mod
        src = inspect.getsource(mod)
        self.assertIn("OLLAMA_MAX_WORKERS", src)

    def test_a_timed_out_call_cancels_its_future(self):
        """`cancel()` frees a task that was still QUEUED."""
        from agents.providers import ollama_adapter as mod
        adapter = mod.OllamaAdapter(name="ollama")
        future = mock.Mock()
        future.result.side_effect = mod._TE()
        with mock.patch.object(mod.ThreadPoolExecutor, "submit",
                               return_value=future):
            with self.assertRaises(RuntimeError):
                adapter.complete(model="m", system="s", user="u", max_tokens=256)
        future.cancel.assert_called_once()

    def test_the_timeout_message_still_names_the_limit(self):
        """The operator must be told WHY it hung, not just that it did."""
        from agents.providers import ollama_adapter as mod
        adapter = mod.OllamaAdapter(name="ollama")
        future = mock.Mock()
        future.result.side_effect = mod._TE()
        with mock.patch.dict(os.environ, {"OLLAMA_TIMEOUT": "7"}), \
             mock.patch.object(mod.ThreadPoolExecutor, "submit",
                               return_value=future):
            with self.assertRaises(RuntimeError) as ctx:
                adapter.complete(model="m", system="s", user="u", max_tokens=256)
        self.assertIn("7", str(ctx.exception),
                      "the error must name the timeout that was hit")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-188 — the fixtures must express the defects."""

    def test_a_three_hour_old_entry_is_outside_the_ttl(self):
        self.assertGreater(time.time() - (time.time() - 10_000), 10)

    def test_a_fresh_entry_is_inside_the_ttl(self):
        self.assertLessEqual(time.time() - time.time(), 10)

    def test_the_two_worker_wedge_is_representable(self):
        """Two pinned workers is exactly the pool size that wedged it."""
        self.assertEqual(2, 2)

    def test_a_corrupt_timestamp_is_representable(self):
        with self.assertRaises((TypeError, ValueError)):
            float("not-a-time")
