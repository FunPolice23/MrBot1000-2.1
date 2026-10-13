"""Phase F3 — per-provider rate limit + daily budget (ARCH-ENG-091).

Provider-aware defaults (local = hardware-bound/no $ cap; cloud = real $ default
cap), operator-configurable via env, daily counter persisted so a restart does
not reset usage. Fails closed on the cap; local never $-capped.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, r"D:\MrBot1000_2.0")


class TestProviderClassification(unittest.TestCase):
    def test_local_providers(self):
        from agents.safety.provider_rate_limiter import is_local_provider
        for n in ("ollama", "Ollama", "llama.cpp", "local", "vllm", "lmstudio"):
            self.assertTrue(is_local_provider(n), n)

    def test_cloud_providers(self):
        from agents.safety.provider_rate_limiter import is_local_provider
        for n in ("openai", "anthropic", "groq", "openrouter", "nous"):
            self.assertFalse(is_local_provider(n), n)


class TestProviderRateLimiter(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp()) / "agent.db"
        # Fresh limiter bound to a temp DB + table.
        from agents.safety import provider_rate_limiter as prl
        self._prl = prl
        prl.ensure_table(str(self._tmp))
        self.limiter = prl.ProviderRateLimiter(db_path=str(self._tmp))
        # Clear any env overrides leaking in.
        for k in list(os.environ):
            if k.endswith("_RATE_PER_SEC") or k.endswith("_MAX_CALLS_PER_DAY"):
                os.environ.pop(k, None)

    def _set_db(self, limiter):
        limiter._db_path = str(self._tmp)

    def test_provider_aware_defaults(self):
        # Local: generous rate, no daily cap.
        self.assertEqual(self.limiter.max_calls_for("ollama"), 0)
        self.assertGreaterEqual(self.limiter.rate_for("ollama"), 1.0)
        # Cloud: conservative daily cap.
        self.assertGreater(self.limiter.max_calls_for("openai"), 0)

    def test_rate_limit_blocks_burst(self):
        os.environ["OPENAI_RATE_PER_SEC"] = "0.5"  # 1 per 2s
        os.environ["OPENAI_MAX_CALLS_PER_DAY"] = "0"  # no daily cap
        limiter = self.limiter
        self._set_db(limiter)
        # First call allowed (bucket starts with capacity 1).
        self.assertTrue(limiter.acquire("openai", block=False, timeout=0.0)["allow"])
        # Immediate second call is over rate -> refused (non-blocking).
        self.assertFalse(limiter.acquire("openai", block=False, timeout=0.0)["allow"])

    def test_daily_cap_refuses_after_n(self):
        os.environ["GROQ_MAX_CALLS_PER_DAY"] = "2"
        os.environ["GROQ_RATE_PER_SEC"] = "100"  # rate won't interfere
        limiter = self.limiter
        self._set_db(limiter)
        self.assertTrue(limiter.acquire("groq", block=False)["allow"])
        self.assertTrue(limiter.acquire("groq", block=False)["allow"])
        third = limiter.acquire("groq", block=False)
        self.assertFalse(third["allow"])
        self.assertIn("daily call cap", third["reason"])

    def test_local_never_dollar_capped(self):
        os.environ["OLLAMA_MAX_CALLS_PER_DAY"] = "1"
        os.environ["OLLAMA_RATE_PER_SEC"] = "100"
        limiter = self.limiter
        self._set_db(limiter)
        # Even with a cap env, local providers default to 0 (unlimited) unless
        # explicitly set; here it IS set to 1, so verify the env override is
        # honored (operator opt-in) rather than the default.
        self.assertEqual(limiter.max_calls_for("ollama"), 1)
        # But with no override, local is unlimited:
        os.environ.pop("OLLAMA_MAX_CALLS_PER_DAY")
        self.assertEqual(limiter.max_calls_for("ollama"), 0)

    def test_counter_survives_reinit(self):
        os.environ["ANTHROPIC_MAX_CALLS_PER_DAY"] = "5"
        os.environ["ANTHROPIC_RATE_PER_SEC"] = "100"
        l1 = self.limiter
        self._set_db(l1)
        self.assertTrue(l1.acquire("anthropic", block=False)["allow"])
        # Simulate an app restart: brand-new limiter, same DB.
        l2 = self._prl.ProviderRateLimiter(db_path=str(self._tmp))
        self.assertEqual(l2._calls_today("anthropic"), 1)

    def test_check_does_not_consume(self):
        os.environ["MISTRAL_MAX_CALLS_PER_DAY"] = "1"
        os.environ["MISTRAL_RATE_PER_SEC"] = "100"
        limiter = self.limiter
        self._set_db(limiter)
        self.assertTrue(limiter.check("mistral")["allow"])
        self.assertTrue(limiter.check("mistral")["allow"])  # check never consumes
        self.assertTrue(limiter.acquire("mistral", block=False)["allow"])
        self.assertFalse(limiter.check("mistral")["allow"])  # now at cap


class TestTokenBucketTryAcquire(unittest.TestCase):
    def test_nonblocking(self):
        from app.library import TokenBucket
        b = TokenBucket(rate=0.5, capacity=1)
        self.assertTrue(b.try_acquire(1.0, timeout=0.0))
        self.assertFalse(b.try_acquire(1.0, timeout=0.0))

    def test_blocking_with_timeout_waits(self):
        from app.library import TokenBucket
        b = TokenBucket(rate=10.0, capacity=1)
        self.assertTrue(b.try_acquire(1.0, timeout=0.0))
        # Next token arrives in ~0.1s; a 1s timeout should get it.
        self.assertTrue(b.try_acquire(1.0, timeout=1.0))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
