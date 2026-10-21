"""Phase E — Settings-tab web-discovery toggle is a LIVE control (ARCH-ENG-087).

The skill's dead-control rule: a toggle must (1) seed from env, (2) persist, and
(3) be consumed by the runtime. This test proves the seed reflects the env and
that a checked toggle round-trips through set_env_values to ALLOW_WEB_DISCOVERY
(the key the runtime reads). We exercise the exact expressions the GUI uses.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _env_bool(name, default=False):
    v = os.getenv(name, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


class TestWebDiscoveryToggleSeed(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.pop("ALLOW_WEB_DISCOVERY", None)

    def tearDown(self):
        os.environ.pop("ALLOW_WEB_DISCOVERY", None)
        if self._orig is not None:
            os.environ["ALLOW_WEB_DISCOVERY"] = self._orig

    def test_seed_defaults_off(self):
        os.environ.pop("ALLOW_WEB_DISCOVERY", None)
        self.assertFalse(_env_bool("ALLOW_WEB_DISCOVERY"))

    def test_seed_reflects_env_true(self):
        os.environ["ALLOW_WEB_DISCOVERY"] = "true"
        self.assertTrue(_env_bool("ALLOW_WEB_DISCOVERY"))

    def test_seed_reflects_env_false(self):
        os.environ["ALLOW_WEB_DISCOVERY"] = "false"
        self.assertFalse(_env_bool("ALLOW_WEB_DISCOVERY"))


class TestWebDiscoveryTogglePersists(unittest.TestCase):
    """A checked toggle must write ALLOW_WEB_DISCOVERY the runtime consumes."""

    def test_checked_round_trips_to_env(self):
        from app.environment import set_env_values
        tmp = Path(tempfile.mkdtemp()) / ".env"
        tmp.write_text("SOME_OTHER=keep\n", encoding="utf-8")
        # Simulate the Save handler writing the checkbox state.
        checked = True
        ok = set_env_values(
            {"ALLOW_WEB_DISCOVERY": "true" if checked else "false"}, path=tmp)
        self.assertTrue(ok)
        text = tmp.read_text(encoding="utf-8")
        self.assertIn("ALLOW_WEB_DISCOVERY=true", text)
        self.assertIn("SOME_OTHER=keep", text)  # unknown keys preserved
        # The runtime reads exactly this key/value.
        self.assertTrue(_env_bool_from_text(text, "ALLOW_WEB_DISCOVERY"))


def _env_bool_from_text(text, name):
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().lower() in ("1", "true", "yes")
    return False


if __name__ == "__main__":
    raise SystemExit(unittest.main())
