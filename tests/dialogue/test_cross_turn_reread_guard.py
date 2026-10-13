"""Cross-turn tool re-read guard (Phase A, chat_completion._seed_executed_calls_from_history).

Within one chat_with_tools run, `executed_text_calls` stops a model re-issuing
the identical web_read/web_search. But each new dialogue turn builds fresh sets,
so a persona that already read a URL in a PRIOR turn would read it again, every
turn, forever (the "agents keep re-reading the same page" loop). The seed scans
the conversation history for tool calls already shown and pre-seeds the set, so
an already-visible result is treated as already delivered.

Uses real history, not a page cache: it only suppresses a call whose exact
invocation is already in the transcript, and the last-10-message window means a
stale entry ages out (a genuinely changed page is re-readable later).
"""
import json
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

# Import order matters: agents.safety.calling imports chat_completion at module
# load, so importing chat_completion FIRST hits a pre-existing circular import.
# The app always loads calling first (small_brain -> calling -> chat_completion);
# mirror that here.
import agents.safety.calling  # noqa: F401  (breaks the import cycle)
from agents.dialogue.chat_completion import _seed_executed_calls_from_history


class TestSeedExecutedCalls(unittest.TestCase):
    def test_seeds_web_read_url_from_history(self):
        seen = set()
        history = [
            {"role": "assistant", "content": 'Let me check it. web_read("https://example.com/jobs/1")'},
        ]
        _seed_executed_calls_from_history(history, seen)
        self.assertIn(
            ("web_read", json.dumps({"url": "https://example.com/jobs/1"}, sort_keys=True)),
            seen,
        )

    def test_seeds_web_search_query(self):
        seen = set()
        history = [{"role": "assistant", "content": 'web_search("remote python gigs")'}]
        _seed_executed_calls_from_history(history, seen)
        self.assertIn(
            ("web_search", json.dumps({"query": "remote python gigs"}, sort_keys=True)),
            seen,
        )

    def test_key_matches_live_parser(self):
        """The seeded key MUST equal the key the within-turn guard builds, or the
        guard won't recognize the duplicate. Compare against the real parser."""
        from agents.safety.response import _parse_tool_call_from_text
        seen = set()
        text = 'I will read web_read("https://example.com/a") now'
        _seed_executed_calls_from_history(
            [{"role": "assistant", "content": text}], seen)
        parsed = _parse_tool_call_from_text(text)
        live_key = (parsed[0], json.dumps(parsed[1], sort_keys=True))
        self.assertIn(live_key, seen)

    def test_no_calls_no_seed(self):
        seen = set()
        _seed_executed_calls_from_history(
            [{"role": "user", "content": "just a normal message with no tools"}], seen)
        self.assertEqual(seen, set())

    def test_empty_and_malformed_history_safe(self):
        seen = set()
        _seed_executed_calls_from_history(None, seen)
        _seed_executed_calls_from_history([], seen)
        _seed_executed_calls_from_history(
            [None, "not a dict", {"role": "x"}, {"content": None},
             {"content": 123}], seen)
        self.assertEqual(seen, set())

    def test_multiple_calls_in_one_message(self):
        seen = set()
        _seed_executed_calls_from_history(
            [{"role": "assistant", "content":
              'web_read("https://a.com") then web_search("q")'}], seen)
        self.assertEqual(len(seen), 2)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
