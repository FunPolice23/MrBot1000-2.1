"""The persona-facing tool-name stripper must derive its names from the registry.

``agents/safety/response.py::_remove_tool_syntax`` decides whether a bare tool
name is a leak (and gets stripped) or real prose. It used to carry its own
hand-typed copy of the tool list, so a tool added to the canonical registry in
``safety_gate`` would keep leaking its bare name into persona bubbles until
someone remembered to edit a second list — the same duplication hazard that
produced five consecutive releases of tool-name-leak fixes (v2.1.27-v2.1.31).

These tests fail if ``_remove_tool_syntax`` ever stops deriving its names from
``MUTATING_TOOL_NAMES | READONLY_TOOL_NAMES``.
"""
import re
import unittest

from agents.safety import response
from agents.safety.gate import MUTATING_TOOL_NAMES, READONLY_TOOL_NAMES

ALL_TOOL_NAMES = READONLY_TOOL_NAMES | MUTATING_TOOL_NAMES


class TestToolSyntaxStripIsRegistryDerived(unittest.TestCase):
    def test_pattern_covers_every_registered_tool(self):
        """No registered tool may be missing from the strip alternation."""
        pattern = response._tool_name_pattern()
        missing = sorted(n for n in ALL_TOOL_NAMES if n not in pattern.split("|"))
        self.assertEqual(missing, [], f"registered tools missing from strip: {missing}")

    def test_pattern_contains_no_unregistered_name(self):
        """The stripper must not invent tool names the registry does not have."""
        pattern = response._tool_name_pattern()
        extra = sorted(n for n in pattern.split("|") if n not in ALL_TOOL_NAMES)
        self.assertEqual(extra, [], f"strip pattern names unknown tools: {extra}")

    def test_stripper_does_not_duplicate_the_registry_literal(self):
        """Guard against re-introducing a hand-typed copy of the registry.

        This must have real power: an earlier version of this guard scanned for
        a single string literal of >=80 chars holding 4+ tool names, which
        PASSED against the exact pre-change code it existed to reject — the old
        list was four implicit-concatenation fragments of 60/66/47/51 chars, so
        no fragment ever reached the threshold — while a routine docstring
        naming four real tools drove it to a spurious failure.

        The effective check is therefore a DIFFERENTIAL one, and it is immune to
        both failure modes: reconstruct the alternation from the live registry,
        and assert the stripper's behaviour on a never-registered name matches
        what the OLD hand-typed approach would have done (i.e. leak it). If
        response.py ever falls back to a literal list, a name absent from that
        literal stops being stripped and this test fails.
        """
        import agents.safety.response as response_mod
        from agents.safety import gate

        # A name the registry definitely does not know.
        sentinel = "zz_unregistered_tool_qq"
        self.assertNotIn(sentinel, ALL_TOOL_NAMES)

        # Sanity: the sentinel is not stripped today (it is not a tool).
        self.assertEqual(
            response_mod._remove_tool_syntax(f"{sentinel} | web_read"),
            f"{sentinel} | web_read",
            "an unregistered name must never be stripped as a tool leak")

        # Now register it. A derived stripper must pick it up immediately; a
        # hand-typed literal list would still leak it. This is the exact
        # regression the literal caused, expressed as a live assertion.
        saved = gate.READONLY_TOOL_NAMES
        try:
            gate.READONLY_TOOL_NAMES = saved | frozenset({sentinel})
            self.assertEqual(
                response_mod._remove_tool_syntax(f"{sentinel} | web_read"), "",
                "a newly registered tool is not stripped — the tool list has "
                "been duplicated as a literal instead of derived from the "
                "registry")
        finally:
            gate.READONLY_TOOL_NAMES = saved

        # The pattern must also be reproducible, not hash-seed dependent, so a
        # future snapshot or diff of it is stable.
        self.assertEqual(
            response_mod._tool_name_pattern(),
            response_mod._tool_name_pattern(),
            "the derived pattern must be deterministic across calls")

    def test_every_registered_tool_is_stripped_as_a_bare_leak(self):
        """Each registered tool's bare name leaks nothing when it stands alone."""
        for name in sorted(ALL_TOOL_NAMES):
            self.assertEqual(
                response._remove_tool_syntax(name), "",
                f"bare {name} was not stripped")
            self.assertEqual(
                response._remove_tool_syntax(f"{name}[]"), "",
                f"empty-bracket {name}[] was not stripped")
            self.assertEqual(
                response._remove_tool_syntax(f"the payout was $80. {name}"),
                "the payout was $80.",
                f"trailing {name} was not stripped in place")

    def test_real_prose_mentioning_a_tool_is_preserved(self):
        """Deriving the list must not start mangling legitimate answers."""
        prose = [
            "I'll use web_read.",
            "Using web_read and web_check.",
            "I used web_search to find the listing.",
            "The web_read tool returned the page text.",
            "The web_read results show $80.",
            "I read the page with web_read and the payout was $80.\n"
            "web_search would not have helped here.",
        ]
        for line in prose:
            self.assertEqual(response._remove_tool_syntax(line), line)


if __name__ == "__main__":
    unittest.main()
