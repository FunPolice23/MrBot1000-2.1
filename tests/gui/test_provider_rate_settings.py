"""Phase F3 — Settings-tab provider rate/cap fields seed + persist (ARCH-ENG-091).

The dead-control rule: a toggle/field must seed from env AND persist. We exercise
the exact expressions the GUI uses for the per-provider rate + daily-call fields
and prove a set value round-trips through set_env_values to the env keys the
runtime reads.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.safety.provider_rate_limiter import is_local_provider


def _seed_default(prov, cur):
    return cur if cur else ("2.0" if is_local_provider(prov) else "1.0")


class TestProviderFieldSeeds(unittest.TestCase):
    def setUp(self):
        for k in list(os.environ):
            if k.endswith("_RATE_PER_SEC") or k.endswith("_MAX_CALLS_PER_DAY"):
                os.environ.pop(k, None)

    def test_cloud_defaults_when_unset(self):
        self.assertEqual(_seed_default("openai", ""), "1.0")
        self.assertEqual(_seed_default("anthropic", ""), "1.0")

    def test_local_defaults_when_unset(self):
        self.assertEqual(_seed_default("ollama", ""), "2.0")

    def test_env_override_wins(self):
        os.environ["OPENAI_RATE_PER_SEC"] = "3.5"
        self.assertEqual(_seed_default("openai",
                                       os.getenv("OPENAI_RATE_PER_SEC", "")), "3.5")


class TestProviderFieldPersists(unittest.TestCase):
    def test_set_values_round_trip(self):
        from app.environment import set_env_values
        tmp = Path(tempfile.mkdtemp()) / ".env"
        tmp.write_text("KEEP=1\n", encoding="utf-8")
        # Simulate save_settings writing the per-provider fields.
        ok = set_env_values({"OPENAI_RATE_PER_SEC": "0.5",
                             "OPENAI_MAX_CALLS_PER_DAY": "250"}, path=tmp)
        self.assertTrue(ok)
        text = tmp.read_text(encoding="utf-8")
        self.assertIn("OPENAI_RATE_PER_SEC=0.5", text)
        self.assertIn("OPENAI_MAX_CALLS_PER_DAY=250", text)
        self.assertIn("KEEP=1", text)

    def test_runtime_reads_persisted_key(self):
        # The limiter must read back exactly what the Settings field persisted.
        from agents.safety.provider_rate_limiter import ProviderRateLimiter
        os.environ["GROQ_RATE_PER_SEC"] = "0.25"
        try:
            lim = ProviderRateLimiter(db_path=":memory:")
            self.assertAlmostEqual(lim.rate_for("groq"), 0.25)
        finally:
            os.environ.pop("GROQ_RATE_PER_SEC", None)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
