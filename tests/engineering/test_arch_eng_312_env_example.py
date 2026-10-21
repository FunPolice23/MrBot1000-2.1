"""ARCH-ENG-312 — `.env.example` must not ship values that break the runtime.

The example carried placeholder prose on keys the runtime parses with plain
``int(os.getenv(...))`` — including ``MAX_TOKENS``, which
``agents/brains/base_worker.py`` reads at MODULE IMPORT time. A new operator
who copied `.env.example` to `.env` got ``ValueError: invalid literal for
int() ... 'your-max-tokens-here'`` and a dead app before any window existed.

These tests pin the numeric keys to real integers so the example stays a
working baseline, and pin the ARCH-ENG-311 chat-template toggle to the
advanced-flags documentation.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Keys the runtime parses as raw integers somewhere in the codebase (verified
# against agents/brains/base_worker.py, worker_budget.py, brains/big_small
# temperature presets, and the dual-brain config).
INT_KEYS = (
    "MAX_TOKENS",
    "BIG_BRAIN_MAX_TOKENS",
    "SMALL_BRAIN_MAX_TOKENS",
    "MAIN_CONTEXT_TOKENS",
    "CHAT_CONTEXT_TOKENS",
    "BIG_BRAIN_BATCH",
    "SMALL_BRAIN_BATCH",
    "BIG_BRAIN_THREADS",
    "SMALL_BRAIN_THREADS",
    "BIG_BRAIN_PORT",
    "SMALL_BRAIN_PORT",
    "BIG_BRAIN_DEVICE",
    "SMALL_BRAIN_DEVICE",
    "BIG_BRAIN_CONTEXT",
    "SMALL_BRAIN_CONTEXT",
    "DIALOGUE_MAX_TOKENS_BIG",
    "DIALOGUE_MAX_TOKENS_SMALL",
    "DIALOGUE_THINK_TOKENS_SMALL",
    "DIALOGUE_THINK_TOKENS_BIG",
)

# Prose placeholders are fine on STRING keys (model names, addresses, API
# keys) — this is only about numeric-parsed keys.


def _env_example() -> dict:
    """KEY -> VALUE for the non-comment KEY=VALUE lines of .env.example."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([A-Za-z0-9_]+)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).split(" #")[0].strip()
    return out


class TestNumericKeysAreRealIntegers(unittest.TestCase):
    def test_the_file_is_valid_utf8(self):
        (ROOT / ".env.example").read_text(encoding="utf-8")  # raises on mojibake

    def test_int_parsed_keys_parse_as_int(self):
        env = _env_example()
        missing = [k for k in INT_KEYS if k not in env]
        self.assertEqual(missing, [],
                         ".env.example no longer carries a numeric key the "
                         "runtime reads")
        bad = []
        for key in INT_KEYS:
            value = env.get(key, "")
            try:
                int(value)
            except ValueError:
                bad.append(f"{key}={value!r}")
        self.assertEqual(
            bad, [],
            ".env.example carries prose placeholders on int-parsed keys — "
            "copying the file becomes a ValueError at import time: "
            + "; ".join(bad))


class TestTheChatTemplateToggleIsDocumented(unittest.TestCase):
    def test_the_legacy_template_escapehatch_is_documented(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK", text,
                      "the ARCH-ENG-311 legacy chat-template fallback toggle "
                      "is no longer documented in .env.example")
        # It must be a commented-out opt-in example, not an active setting.
        active = [ln for ln in text.splitlines()
                  if re.match(r"^MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK=", ln.strip())]
        self.assertEqual(
            active, [],
            ".env.example actively sets MRBOT_LEGACY_CHAT_TEMPLATE_FALLBACK; "
            "it is a rescue knob and must stay commented out")


if __name__ == "__main__":
    unittest.main()
