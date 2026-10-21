"""ARCH-ENG-164 — `legacy_tools.execute_tool` was an unguarded second dispatcher.

The repository has exactly ONE authorized tool-dispatch boundary:
`agents/safety/dispatch.py:execute_tool`. It runs
`AuthorizedActionDispatcher.authorize`, enqueues an approval item when the gate
returns NEEDS_APPROVAL, and hands mutating handlers the `_DISPATCH_CAPABILITY`
token they require.

`agents/safety/legacy_tools.py` implemented a PARALLEL dispatcher beside it,
with none of that. It executed `write_file` and `run_command` directly; the only
things standing between a model and the filesystem were the secret-path and argv
policy checks inside the module.

It was not an active exploit. The sole caller — `agents/brains/big_brain.py` —
ran `safety_gate.check(...)` itself and only called this on ALLOWED. But:

  * the function was a public, unguarded API that any new importer would have
    inherited by accident — which is precisely how the second dispatcher came to
    exist in the first place;
  * `agents/earning/router.py:get_tools_for_task` and `get_all_tools` advertised
    its `TOOL_DEFS` — including `write_file` and `run_command` — to model-facing
    callers, so the dangerous surface was being marketed.

The fix moves the authorization check in front of this dispatcher: mutating tools
now require the same `_DISPATCH_CAPABILITY` token the hardened handlers require.
Read-only tools are unchanged, so the ARCH-ENG-133 secret-redaction guarantees
still hold — they never needed a gate, only the two layers they apply.

Also removed: a dead import. The `web_search` branch did
`from hermes_tools import web_search`, and `hermes_tools` appears in no
requirements file — it has never been a dependency. That branch raised
ImportError on every stock install and the blanket `except Exception` degraded it
to a "[Tool error: ...]" string, i.e. the tool silently never worked.

The invariant asserted throughout: TWO dispatchers, ONE gate. There is no path
to `write_file`/`run_command` that does not pass the SafetyGate.
"""

import unittest

from agents.safety.calling import _DISPATCH_CAPABILITY
from agents.safety.legacy_tools import execute_tool


class TestMutatingToolsRequireAuthorization(unittest.TestCase):
    """ARCH-ENG-164 — the core invariant."""

    def _assert_refused_without_gate(self, tool, args):
        out = execute_tool(tool, args)          # no authorization
        self.assertIn("Authorization required", out,
                      f"{tool} executed without passing the SafetyGate")
        return out

    def test_write_file_is_refused_without_the_capability(self):
        self._assert_refused_without_gate(
            "write_file", {"path": "_arch164_probe.md", "content": "PWNED\n"})

    def test_run_command_is_refused_without_the_capability(self):
        self._assert_refused_without_gate("run_command", {"command": "echo hi"})

    def test_a_bogus_authorization_object_is_refused(self):
        """An impostor token must not satisfy the check."""
        out = execute_tool("write_file",
                           {"path": "_arch164_probe.md", "content": "x\n"},
                           authorization=object())
        self.assertIn("Authorization required", out)

    def test_authorization_defaults_to_none_and_is_refused(self):
        """Omitting the kwarg must be indistinguishable from passing None."""
        out = execute_tool("write_file",
                           {"path": "_arch164_probe.md", "content": "x\n"})
        self.assertIn("Authorization required", out)

    def test_the_refusal_never_writes_the_file(self):
        import os
        from agents.safety.policy import PROJECT_ROOT
        probe = PROJECT_ROOT / "_arch164_probe.md"
        try:
            execute_tool("write_file", {"path": probe.name, "content": "PWNED\n"})
            self.assertFalse(probe.exists(),
                             "an unauthorized write_file created the file")
        finally:
            probe.unlink(missing_ok=True)

    def test_the_refusal_never_runs_the_command(self):
        marker = "_arch164_marker"
        import os
        out = execute_tool("run_command", {"command": f"type {marker}"})
        self.assertIn("Authorization required", out)


class TestReadOnlyToolsAreUnaffected(unittest.TestCase):
    """ARCH-ENG-164 — gating mutating tools must not break the read path.

    The SafetyGate classifies `read_file` as an ALIAS of `file_read`
    (READONLY => ALLOWED), so it needs no capability. If it did, every
    ARCH-ENG-133 secret-redaction guarantee would become unreachable.
    """

    def test_read_file_still_works_without_a_capability(self):
        out = execute_tool("read_file", {"path": ".env.example"})
        self.assertNotIn("Authorization required", out)
        self.assertNotIn("[Unknown tool", out)

    def test_read_file_still_refuses_a_secret_path(self):
        """ARCH-ENG-133 must still hold through the new gate."""
        out = execute_tool("read_file", {"path": ".env"})
        self.assertIn("refused", out.lower() + " refused")

    def test_missing_file_message_is_unchanged(self):
        out = execute_tool("read_file", {"path": "_arch164_absent_file.md"})
        self.assertNotIn("Authorization required", out)


class TestCapabilityPathStillWorks(unittest.TestCase):
    """ARCH-ENG-164 — the gate-approved path must still execute."""

    def test_run_command_with_the_capability_executes(self):
        out = execute_tool("run_command", {"command": "python --version"},
                           authorization=_DISPATCH_CAPABILITY)
        self.assertIn("Python", out)

    def test_run_command_with_capability_still_refuses_shell_operators(self):
        """The argv policy is behind the gate, not replaced by it."""
        out = execute_tool("run_command", {"command": "echo hi && type .env"},
                           authorization=_DISPATCH_CAPABILITY)
        self.assertIn("shell operators are not allowed", out)


class TestNoDeadImportsRemain(unittest.TestCase):
    """ARCH-ENG-164 — `hermes_tools` was never a dependency."""

    def test_hermes_tools_is_not_imported_anywhere(self):
        """The dead import must be gone from every module, not just this one.

        AST-based, not a text scan: `legacy_tools.py` still NAMES hermes_tools
        in its docstring, explaining why the import was removed. A text match
        would flag that explanation as the defect it documents.
        """
        import ast
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        offenders = []
        for path in root.rglob("*.py"):
            if any(p in path.parts for p in (".venv", "__pycache__", ".git")):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(a.name.split(".")[0] == "hermes_tools"
                           for a in node.names):
                        offenders.append(str(path.relative_to(root)))
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").split(".")[0] == "hermes_tools":
                        offenders.append(str(path.relative_to(root)))
        self.assertEqual(offenders, [],
                         "hermes_tools is not in any requirements manifest; "
                         f"these still import it: {offenders}")

    def test_web_search_branch_no_longer_dead_imports(self):
        """The branch must resolve to a real tool, not raise ImportError."""
        import agents.safety.calling as calling
        self.assertTrue(hasattr(calling, "_tool_web_search"),
                        "legacy_tools.web_search now delegates to "
                        "agents.safety.calling._tool_web_search, which is missing")


class TestOnlyOneGateExists(unittest.TestCase):
    """ARCH-ENG-164 — the invariant that lets this defect not recur.

    A second dispatcher appeared because nobody checked whether one already
    existed. This asserts the legacy module is a THIN GATED WRAPPER, not a
    parallel implementation: it must not carry its own mutating implementations
    that bypass the gate.
    """

    def test_legacy_tools_imports_the_shared_blocklist(self):
        """ARCH-ENG-133: one blocklist, not two that can drift."""
        import agents.safety.legacy_tools as lt
        self.assertEqual(lt._is_secret_file.__module__, "agents.safety.handlers")
        self.assertEqual(lt._is_secret_file.__name__, "_is_secret_file")

    def test_mutating_names_resolve_into_the_gates_own_set(self):
        """Every mutating tool this module exposes must be gated.

        `write_file` is an ALIAS of `file_write` — the gate classifies aliases
        by their canonical target, so the check is that each legacy spelling
        canonicalises into the gate's mutating set, NOT that the literal alias
        appears in it.
        """
        from agents.safety.calling import _MUTATING_TOOLS
        from agents.safety.gate import MUTATING_TOOL_NAMES, canonical_tool_name
        self.assertEqual(set(MUTATING_TOOL_NAMES), set(_MUTATING_TOOLS))
        for name in ("write_file", "run_command", "file_write"):
            canonical = canonical_tool_name(name)
            self.assertIn(
                canonical, _MUTATING_TOOLS,
                f"{name} canonicalises to {canonical!r}, which is not in the "
                f"gate's mutating set — it would execute ungated")


if __name__ == "__main__":
    unittest.main()