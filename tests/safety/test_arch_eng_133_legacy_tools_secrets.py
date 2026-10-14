"""ARCH-ENG-133: the legacy Big Brain tool set must not leak credential stores.

Reproduced pre-fix by EXECUTION (not inference), via the real dispatch path the
Big Brain tool loop uses (SafetyGate classifies the alias `read_file` ->
canonical `file_read` = READONLY => ALLOWED, then hands the call to
legacy_tools.execute_tool -- NOT to the hardened handlers._tool_file_read):

    execute_tool('read_file', {'path': '.env'})        -> 13418 chars, 264 keys
    execute_tool('read_file', {'path': 'wallet.key'})  -> the raw Fernet key

Both went straight into the model's `role: "tool"` message.

Fix: legacy_tools re-applies the same two layers as handlers._tool_file_read,
using the SAME authority (`_is_secret_file` imported from agents.safety.handlers)
so there is one blocklist instead of two that can drift. Plus defence in depth
on write_file / run_command / analyze_document, which return refusal strings
rather than raising.

The final tests are a behaviour-targeted negative control: with the authority
monkeypatched to always-False, the live .env read must LEAK -- proving the guard
is what stops the leak, not an accident of the file being absent.
"""
import unittest
from pathlib import Path
from unittest import mock

from agents.safety.legacy_tools import (
    _is_secret_path,
    _read_file,
    execute_tool,
)
from agents.safety.handlers import _is_secret_file
from agents.safety.policy import PROJECT_ROOT
from agents.safety.gate import SafetyDecision, SafetyGate
from agents.integrations.wallet_crypto import redact_secrets

# Names that mark a credential/key store but need not exist in every checkout
# (they are gitignored), so the tests create them inside PROJECT_ROOT.
_SYNTHETIC_SECRET_NAMES = [
    ".env.production",
    "config/.env",
    "arch133_probe.pem",
    "arch133_probe.key",
]


class SecretReadRefused(unittest.TestCase):
    """Layer 1: a file whose value IS the credential is never returned."""

    def test_each_secret_path_is_refused(self):
        """Every secret store -- real or synthetic -- must be refused."""
        for rel in (".env", "wallet.key", "data/platform_vault.json"):
            p = PROJECT_ROOT / rel
            if not p.exists():
                self.skipTest(f"{rel} not present in this checkout")
            out = execute_tool("read_file", {"path": rel})
            self.assertIn("Read refused", out, f"{rel} leaked: {out[:80]!r}")
            self.assertIn(".env.example", out)  # actionable guidance, not a dead end
            self.assertIn("ask the operator", out)

    def test_synthetic_secret_names_are_refused(self):
        """Secret NAMES are refused even when the file does not exist yet."""
        created = []
        try:
            for rel in _SYNTHETIC_SECRET_NAMES:
                p = PROJECT_ROOT / rel
                if not p.exists():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("PLACEHOLDER_SECRET=do-not-return\n", encoding="utf-8")
                    created.append(p)
                out = execute_tool("read_file", {"path": rel})
                self.assertIn("Read refused", out, f"{rel} leaked: {out[:80]!r}")
                self.assertNotIn("PLACEHOLDER_SECRET", out)
        finally:
            for p in created:
                p.unlink(missing_ok=True)

    def test_env_example_is_still_readable(self):
        """.env.example holds placeholders and must stay readable."""
        p = PROJECT_ROOT / ".env.example"
        if not p.exists():
            self.skipTest(".env.example not present in this checkout")
        out = execute_tool("read_file", {"path": ".env.example"})
        self.assertNotIn("Read refused", out)
        self.assertGreater(len(out), 50, ".env.example returned nothing useful")

    def test_missing_file_message_unchanged(self):
        """A nonexistent path still reports not-found (behaviour unchanged)."""
        out = execute_tool("read_file", {"path": "does_not_exist_arch133.md"})
        self.assertIn("not found", out.lower())


class Layer2Redaction(unittest.TestCase):
    """Layer 2: a secret pasted into a READABLE file is scrubbed."""

    PROBE = PROJECT_ROOT / "_arch133_probe.md"

    def tearDown(self):
        self.PROBE.unlink(missing_ok=True)

    def test_pasted_credential_is_redacted(self):
        """A 64-hex key / fernet token in README.md never reaches the model."""
        secret_hex = "a" * 64
        # A realistic full-length fernet token (ARCH-ENG-132's truncated stub is
        # not matched: the pattern needs a `.` separator and no trailing pad `=`,
        # which would break its word boundary).
        fernet = "fernet:gAAAAABqz5MFzo-SnSTaBcD.xYzAbCdEfGhIjKlMnOpQrStUvWxYz0123456789ABCD"
        self.PROBE.write_text(
            f"key: {secret_hex}\n{fernet}\nmnemonic: abandon abandon art\n",
            encoding="utf-8",
        )
        out = execute_tool("read_file", {"path": self.PROBE.name})
        self.assertNotIn(secret_hex, out, "raw 64-hex key reached the model")
        self.assertNotIn("gAAAAABqz5MFzo-SnSTaBcDxyz", out,
                         "raw fernet token reached the model")
        self.assertIn("REDACTED", out)

    def test_normal_content_survives_apart_from_redaction(self):
        """Ordinary prose is returned intact (no over-blocking)."""
        body = "# Notes\nnormal text with a short hash 3f8a2b1c\n"
        self.PROBE.write_text(body, encoding="utf-8")
        out = execute_tool("read_file", {"path": self.PROBE.name})
        self.assertEqual(out, redact_secrets(body))
        self.assertTrue(out.startswith("# Notes"))
        self.assertIn("3f8a2b1c", out, "short hashes are not secret-shaped")


class MutatingToolDefenceInDepth(unittest.TestCase):
    """write_file / run_command are already NEEDS_APPROVAL -- these add layer 2."""

    def test_analyze_document_refuses_secret_path(self):
        """analyze_document reads through the same reader; it must refuse too."""
        out = execute_tool("analyze_document", {"path": ".env"})
        self.assertIn("Analysis refused", out)
        self.assertIn(".env.example", out)

    def test_analyze_document_refuses_synthetic_secret(self):
        p = PROJECT_ROOT / "_arch133_probe.key"
        p.write_text("PLACEHOLDER_SECRET\n", encoding="utf-8")
        try:
            out = execute_tool("analyze_document", {"path": p.name})
            self.assertIn("Analysis refused", out)
            self.assertNotIn("PLACEHOLDER_SECRET", out)
        finally:
            p.unlink(missing_ok=True)

    ENV = PROJECT_ROOT / ".env"
    # The real .env is gitignored, so a fresh clone has none. These tests must
    # not depend on that (the fresh-clone gate caught exactly this) and must
    # never risk the operator's real file: setUp writes its OWN .env when one is
    # absent, and tearDown removes only what the test itself created.
    _ENV_MARKER = "ARCH_ENG_133_PROBE_OWNED_BY_TEST=1\n"

    def setUp(self):
        self._env_created = False
        if not self.ENV.exists():
            self.ENV.write_text(self._ENV_MARKER, encoding="utf-8")
            self._env_created = True

    def tearDown(self):
        # Remove only what this test created; never touch a real .env.
        if self._env_created:
            self.ENV.unlink(missing_ok=True)

    def test_write_file_refuses_secret_destination(self):
        """write_file must not clobber .env / *.key even behind an approval."""
        env_before = self.ENV.read_bytes()
        for rel in (".env", "wallet.key", "_arch133_probe.pem"):
            out = execute_tool("write_file", {"path": rel, "content": "PWNED=1\n"})
            self.assertIn("Write refused", out, f"{rel} was written to!")
            self.assertNotIn("PWNED=1", out)
        self.assertEqual(
            self.ENV.read_bytes(), env_before,
            "the .env was modified by the test",
        )
        self.assertFalse((PROJECT_ROOT / "_arch133_probe.pem").exists())

    def test_run_command_refuses_command_naming_a_secret_file(self):
        """A command that names a secret store never executes."""
        for cmd in ("type .env", "type wallet.key", "type data/platform_vault.json"):
            out = execute_tool("run_command", {"command": cmd})
            self.assertIn("Command refused", out, f"{cmd!r} executed!")
            self.assertIn(".env.example", out)

    def test_run_command_still_executes_normal_commands(self):
        """The guard must not break ordinary read-only commands."""
        out = execute_tool("run_command", {"command": "python --version"})
        self.assertIn("Python", out)

    def test_run_command_rejects_shell_operators_as_before(self):
        """Pre-existing command_argv validation is unchanged."""
        out = execute_tool("run_command", {"command": "echo hi && type .env"})
        self.assertIn("shell operators are not allowed", out)


class GateClassificationUnchanged(unittest.TestCase):
    """The fix must not silently change any authorization decision."""

    def test_read_file_still_allowed(self):
        gate = SafetyGate()
        allowed, _reason, decision = gate.check("read_file", {"path": "README.md"})
        self.assertTrue(allowed)
        self.assertEqual(decision, SafetyDecision.ALLOWED)

    def test_write_file_still_needs_approval(self):
        gate = SafetyGate()
        allowed, _reason, decision = gate.check(
            "write_file", {"path": "notes.md", "content": "x"})
        self.assertFalse(allowed)
        self.assertEqual(decision, SafetyDecision.NEEDS_APPROVAL)

    def test_run_command_still_needs_approval(self):
        gate = SafetyGate()
        allowed, _reason, decision = gate.check(
            "run_command", {"command": "python --version"})
        self.assertFalse(allowed)
        self.assertEqual(decision, SafetyDecision.NEEDS_APPROVAL)

    def test_analyze_document_still_blocked(self):
        """The gate keeps blocking analyze_document; that is unchanged."""
        gate = SafetyGate()
        _allowed, _reason, decision = gate.check(
            "analyze_document", {"path": "README.md"})
        self.assertEqual(decision, SafetyDecision.BLOCKED)

    def test_single_authority_is_shared_not_duplicated(self):
        """legacy_tools must import handlers' blocklist, not carry its own."""
        import agents.safety.legacy_tools as lt
        self.assertIs(lt._is_secret_file, _is_secret_file)


class BehaviourNegativeControl(unittest.TestCase):
    """Prove the guard is what stops the leak -- not an accident."""

    ENV = PROJECT_ROOT / ".env"
    # The real .env is gitignored and may be absent in a fresh clone (the
    # fresh-clone gate caught exactly this). Own the fixture: create a .env with
    # a known marker when none exists, and remove only what we created. This
    # keeps the control meaningful without touching the operator's real file.
    _OWN_MARKER = "NOUS_API_KEY=arch-eng-133-discrimination-probe\n"

    def setUp(self):
        self._env_created = False
        if not self.ENV.exists():
            self.ENV.write_text(self._OWN_MARKER, encoding="utf-8")
            self._env_created = True

    def tearDown(self):
        if self._env_created:
            self.ENV.unlink(missing_ok=True)

    def test_disabling_the_guard_re_leaks_then_refuses_again(self):
        """With `_is_secret_file` forced to False the .env read LEAKS.

        This is a control against BEHAVIOR (not imports): if the leak only
        stopped because the file happened to be absent, this test would fail
        even with the guard disabled.

        setUp has already ensured a .env exists (ours if none was present).
        tearDown removes the fixture only if this test created it.
        """
        with mock.patch(
            "agents.safety.legacy_tools._is_secret_file", lambda p: False
        ):
            out = execute_tool("read_file", {"path": ".env"})
            self.assertNotIn("Read refused", out, "guard off but still refused?")
            self.assertIn(
                "NOUS_API_KEY", out,
                "expected the .env content when the guard is off",
            )
        # Guard restored -> refused again.
        again = execute_tool("read_file", {"path": ".env"})
        self.assertIn("Read refused", again)
        self.assertNotIn("NOUS_API_KEY", again)

    def test_secret_path_helper_follows_the_authority(self):
        """`_is_secret_path` is the authority applied to a string path."""
        self.assertTrue(_is_secret_path(".env"))
        self.assertTrue(_is_secret_path("wallet.key"))
        self.assertFalse(_is_secret_path(".env.example"))
        self.assertFalse(_is_secret_path("README.md"))
        # And the direct reader agrees.
        self.assertIn("Read refused", _read_file(".env"))


if __name__ == "__main__":
    unittest.main()
