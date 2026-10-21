"""ARCH-ENG-239 / BE-01 -- ONE matcher for think-block markers, everywhere
its strip/split decisions are made.

The finding
-----------
Four LIVE implementations of the same match carried DIFFERENT case rules:

  agents/safety/response.py:173   ``_remove_think_blocks`` case-insensitive
      (the main dialogue path -- tolerant by luck, not design)
  response.py profile branch      inline re.sub             lowercase only
  gui/tabs/chat_tab.py pattern 3  inline re.compile         lowercase only
  agents/brains/worker_thinking   string .index()           lowercase only

A model emitting ``<THINK>`` or ``<Think>`` had its private reasoning
stripped on the tolerant path and PRINTED TO THE OPERATOR on the other three.
This is the ARCH-ENG-211/226 family -- the same decision N times, N answers
-- except here every copy was live, so the drift was reachable in production.

The fix: the canonical compiled matcher lives in
``agents/brains/worker_thinking`` (dependency-light, no import cycles: the
safety package already imports agents.brains at module level). Policies that
legitimately differ between paths -- split-vs-strip, unclosed-block handling
-- are separate functions; the MATCH must never differ. The worker's legacy
unclosed-block policy (an unclosed block counts entirely as thinking, empty
answer) is deliberately preserved while its case rule now matches the shared
matcher. response.py's channel_thought branch (a different marker, BE-02
territory) is untouched.

Automation note: this test file builds the markers by concatenation
(`<` + `think` + `>`) and asserts on line shapes, because the literal is a
known interactor-side corruption target; the PRODUCTION files carry the real
literal.

Vacuity: against the pre-fix sources, the uppercase behavior tests fail on
the chat/worker paths, and the source-scans fail while the inline copies are
still present.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

RESPONSE = REPO / "agents" / "safety" / "response.py"
CHAT_TAB = REPO / "gui" / "tabs" / "chat_tab.py"
WORKER_THINKING = REPO / "agents" / "brains" / "worker_thinking.py"

from agents.brains.worker_thinking import (
    _THINK_BLOCK_RE, split_thinking, split_think_blocks, strip_think_blocks)
from agents.safety.response import _remove_think_blocks


def _tags():
    """Build the think markers from segments (see module note)."""
    open_tag = "<" + "think" + ">"
    return open_tag, "<" + "/" + "think" + ">"


OPEN_, CLOSE_ = _tags()


class TestTheCanonicalMatcher(unittest.TestCase):

    def test_matcher_is_case_insensitive_and_dotall(self):
        self.assertTrue(_THINK_BLOCK_RE.search("x" + OPEN_.upper() + "a" + CLOSE_.upper()))
        self.assertTrue(_THINK_BLOCK_RE.search("x" + OPEN_.title() + "\n" + CLOSE_.title()))
        self.assertFalse(_THINK_BLOCK_RE.search("no markers here"))

    def test_strip_removes_uppercase_blocks(self):
        text = "OK, here is my plan." + OPEN_.upper() + "private" + CLOSE_.upper() + " answer tail"
        self.assertEqual(strip_think_blocks(text), "OK, here is my plan. answer tail")
        self.assertEqual(strip_think_blocks(""), "")

    def test_split_returns_first_block_and_strips_all_from_answer(self):
        thinking, answer = split_think_blocks("lead" + OPEN_.title() + "one" + CLOSE_.title() + "answer")
        self.assertEqual(thinking, "one")
        self.assertEqual(answer, "leadanswer")
        # No block: content passes through untouched.
        self.assertEqual(split_think_blocks("plain"), ("", "plain"))
        # Two blocks: both leave the answer (the pre-consolidation legacy
        # split leaked later blocks into it).
        thinking, answer = split_think_blocks(
            OPEN_ + "a" + CLOSE_ + "mid" + OPEN_ + "b" + CLOSE_ + "tail")
        self.assertEqual(thinking, "a")
        self.assertEqual(answer, "midtail")

    def test_worker_legacy_unclosed_policy_preserved(self):
        """The unclosed-block policy is NOT part of this fix: an unclosed
        block is an in-progress stream -- all of it counts as thinking, and
        the answer is empty so a half-streamed block never shows as an
        answer."""
        thinking, answer = split_thinking("answer then" + OPEN_.title() + "half way")
        self.assertEqual(answer, "")
        self.assertEqual(thinking, "half way")
        # Closed blocks now split under any casing via the shared matcher.
        thinking, answer = split_thinking(OPEN_.upper() + "r" + CLOSE_.upper() + "visible")
        self.assertEqual(thinking, "r")
        self.assertEqual(answer, "visible")

    def test_safety_alias_delegates_to_the_canonical_matcher(self):
        """Re-export stability: the safety alias strips identically to the
        canonical matcher it delegates to, on the inputs it used to miss."""
        for text in (
            "a" + OPEN_.upper() + "s" + CLOSE_.upper() + "b",
            "a" + OPEN_.title() + "s" + CLOSE_.title() + "b",
            "a" + OPEN_ + "s" + CLOSE_ + "b",
            "",
        ):
            self.assertEqual(_remove_think_blocks(text),
                             strip_think_blocks(text),
                             f"alias diverged on {text!r}")


class TestNoParallelCopiesRemain(unittest.TestCase):
    """The same-decision-N-times class is closed by construction: the only
    remaining matcher is the canonical one."""

    def test_response_py_has_no_inline_think_matcher(self):
        """No line of response.py may both run a regex AND carry the think
        markers: comment/docstring mentions are fine, executable matchers
        are not (the channel_thought branch is a different marker)."""
        offenders = [
            f"line {i}: {line.strip()}" for i, line in
            enumerate(RESPONSE.read_text(encoding="utf-8").splitlines(), 1)
            if ("think" in line.lower())
            and (".sub(" in line or "re.compile(" in line or ".search(" in line)
        ]
        self.assertEqual(offenders, [], "inline think matchers remain: " +
                         "; ".join(offenders))

    def test_chat_tab_has_no_private_think_matcher(self):
        chat_src = CHAT_TAB.read_text(encoding="utf-8")
        self.assertEqual(chat_src.count("think_pattern"), 0,
                         "chat_tab must not keep a private think matcher")
        self.assertIn("split_think_blocks", chat_src,
                      "chat_tab must route through the canonical matcher")

    def test_worker_split_goes_through_the_shared_matcher(self):
        worker_src = WORKER_THINKING.read_text(encoding="utf-8")
        self.assertEqual(worker_src.count(".index("), 0,
                         "the exact-substring .index() matcher must be gone")
        self.assertIn("group(1).strip()", worker_src)


class TestChatTabParsesUppercaseBlocks(unittest.TestCase):
    """The GUI path: a `<THINK>` block must be split, not displayed."""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    def _parse(self, text):
        from gui.tabs.chat_tab import ChatTab
        return ChatTab.parse_thinking(self, text)

    def test_uppercase_block_is_split_not_displayed(self):
        thinking, clean = self._parse(
            "hello" + OPEN_.upper() + "secret" + CLOSE_.upper() + "world")
        self.assertEqual(thinking, "secret")
        self.assertEqual(clean, "helloworld")

    def test_lowercase_block_still_works(self):
        thinking, clean = self._parse("hello" + OPEN_ + "note" + CLOSE_ + "world")
        self.assertEqual(thinking, "note")
        self.assertEqual(clean, "helloworld")

    def test_no_block_returns_none(self):
        thinking, clean = self._parse("plain answer")
        self.assertIsNone(thinking)
        self.assertEqual(clean, "plain answer")


if __name__ == "__main__":
    unittest.main()
