"""Alignment tests between SafetyGate and the real tool registry.

Guards the regression where ``SafetyGate._RULES`` named tools that do not exist
(``read_file``, ``list_directory``, ``query_database``, ``write_file``). Because
``check()`` fails closed on unknown names, that mismatch silently blocked every
legitimate read tool and left the SQL validation branch unreachable.

Add a new tool to ``execute_tool`` (or to the schema) without classifying it in
``agents/safety_gate.py`` and these tests fail.
"""
import re
import unittest
from pathlib import Path

from agents import tool_calling
from agents.safety_gate import (
    MUTATING_TOOL_NAMES,
    READONLY_TOOL_NAMES,
    SafetyDecision,
    SafetyGate,
    canonical_tool_name,
    is_known_tool,
)

_SOURCE = Path(tool_calling.__file__).read_text(encoding="utf-8", errors="replace")


class TestSafetyGateRegistryAlignment(unittest.TestCase):
    def _dispatched_names(self) -> set:
        return set(re.findall(r'name == "([^"]+)"', _SOURCE))

    def test_every_dispatched_tool_is_classified(self):
        missing = sorted(n for n in self._dispatched_names() if not is_known_tool(n))
        self.assertEqual(
            missing, [], f"tools dispatchable but not classified in SafetyGate: {missing}")

    def test_every_schema_tool_is_classified(self):
        names = {t["function"]["name"] for t in tool_calling.get_all_tools()}
        missing = sorted(n for n in names if not is_known_tool(n))
        self.assertEqual(
            missing, [], f"tools exposed to models but not classified: {missing}")

    def test_mutating_denylist_matches_safety_gate(self):
        self.assertEqual(tool_calling._MUTATING_TOOLS, set(MUTATING_TOOL_NAMES))

    def test_readonly_and_mutating_sets_are_disjoint(self):
        self.assertEqual(READONLY_TOOL_NAMES & MUTATING_TOOL_NAMES, frozenset())

    def test_gate_allows_readonly_and_gates_state_changing_tools(self):
        gate = SafetyGate()
        for name in sorted(READONLY_TOOL_NAMES - {"query_db"}):
            with self.subTest(tool=name):
                allowed, _reason, decision = gate.check(name, {})
                self.assertTrue(allowed, name)
                self.assertEqual(decision, SafetyDecision.ALLOWED, name)
        for name in sorted(MUTATING_TOOL_NAMES):
            with self.subTest(tool=name):
                allowed, _reason, decision = gate.check(name, {})
                self.assertFalse(allowed, name)
                self.assertEqual(decision, SafetyDecision.NEEDS_APPROVAL, name)

    def test_unknown_tool_is_blocked(self):
        allowed, _reason, decision = SafetyGate().check("totally_made_up_tool", {})
        self.assertFalse(allowed)
        self.assertEqual(decision, SafetyDecision.BLOCKED)

    def test_legacy_aliases_still_resolve_to_real_tools(self):
        classified = READONLY_TOOL_NAMES | MUTATING_TOOL_NAMES
        for alias in ("read_file", "list_directory", "write_file", "query_database"):
            with self.subTest(alias=alias):
                self.assertIn(canonical_tool_name(alias), classified)

    def test_execute_tool_does_not_run_an_unknown_tool(self):
        result = tool_calling.execute_tool("totally_made_up_tool", {})
        self.assertIn("Unknown tool", result)


class TestAutoApproveReadonlyFlag(unittest.TestCase):
    """``auto_approve_readonly`` must actually change behaviour, not just sit
    on the instance. It was previously stored and never read, so the flag
    advertised a policy the gate never enforced."""

    def test_default_still_auto_approves_readonly(self):
        gate = SafetyGate()  # default True
        self.assertTrue(gate.auto_approve_readonly)
        name = sorted(READONLY_TOOL_NAMES - {"query_db"})[0]
        allowed, _reason, decision = gate.check(name, {})
        self.assertTrue(allowed)
        self.assertEqual(decision, SafetyDecision.ALLOWED)

    def test_disabling_forces_readonly_through_approval(self):
        gate = SafetyGate(auto_approve_readonly=False)
        for name in sorted(READONLY_TOOL_NAMES - {"query_db"}):
            with self.subTest(tool=name):
                allowed, reason, decision = gate.check(name, {})
                self.assertFalse(allowed, name)
                self.assertEqual(decision, SafetyDecision.NEEDS_APPROVAL, name)
                self.assertIn("requires approval", reason)

    def test_disabling_does_not_weaken_mutating_gate(self):
        gate = SafetyGate(auto_approve_readonly=False)
        for name in sorted(MUTATING_TOOL_NAMES):
            with self.subTest(tool=name):
                allowed, _reason, decision = gate.check(name, {})
                self.assertFalse(allowed, name)
                self.assertEqual(decision, SafetyDecision.NEEDS_APPROVAL, name)


if __name__ == "__main__":
    unittest.main()
