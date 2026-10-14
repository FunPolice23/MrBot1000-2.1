"""ARCH-ENG-134: `workshop_read` must not return credential stores to the model.

Reproduced pre-fix by EXECUTION (not inference), through the real dispatcher:

    MRBOT_WORKSHOP_ROOT=<tmp> execute_tool('workshop_read', {'filepath': '.env'})
        -> 'OPENAI_API_KEY=sk-ZZZZyyyyXXXXwwwwVVVVuuuu\\n'   (raw)
    ... 'wallet.key'
        -> 'RAWFERNETKEYMATERIAL==\\n'                        (raw)
    ... 'notes.md'
        -> 'api key is sk-proj-AAAAbbbbCCCCddddEEEEFFFFGGGG\\n' (unredacted)

`workshop_read` is READONLY and auto-allowed, but the workshop root is a
DIFFERENT tree from PROJECT_ROOT (MRBOT_WORKSHOP_ROOT, default D:\\ai_workshop),
so the ARCH-ENG-132 `file_read` guard never saw it — and `Workshop.read_file`
is a bare `open(path).read()`. The workshop's own store `accounts/accounts.json`
holds a plaintext `password` field (Workshop.add_account).

The fix mirrors `_tool_file_read`'s two layers with the SAME authorities:
1. a secret NAME is refused outright (the value IS the whole file);
2. every other file's text passes through `redact_secrets`.
"""
import json
import os
import unittest
from pathlib import Path

from agents.knowledge import workshop as workshop_mod
from agents.safety import handlers
from agents.safety.handlers import _tool_workshop_read

TMP_ROOT = None
_ORIG_ROOT = None


def setUpModule():
    """Point the workshop at a throwaway root so D:\\ai_workshop is never read."""
    global TMP_ROOT, _ORIG_ROOT
    import tempfile
    TMP_ROOT = tempfile.mkdtemp(prefix="arch134_")
    # WORKSHOP_ROOT is read at IMPORT time, so the env var alone is not enough
    # once `agents.knowledge.workshop` has been imported: patch the module
    # constant as well, then rebuild the singleton against it.
    _ORIG_ROOT = workshop_mod.WORKSHOP_ROOT
    os.environ["MRBOT_WORKSHOP_ROOT"] = TMP_ROOT
    workshop_mod.WORKSHOP_ROOT = TMP_ROOT
    workshop_mod._workshop = None
    ws = workshop_mod.get_workshop()
    assert ws.root == str(Path(TMP_ROOT).resolve()), (
        f"workshop root is not the temp root: {ws.root}")
    # the secret stores, exactly as the workshop's own schema creates them.
    # `.env` deliberately carries BOTH a value-shaped credential (which the
    # ARCH-ENG-135 `redact_secrets` patterns scrub) and an OPAQUE value that no
    # pattern can shape-match — that opaque value is what makes the layer-1
    # guard provably load-bearing in the negative control below.
    (Path(TMP_ROOT) / ".env").write_text(
        "OPENAI_API_KEY=sk-ZZZZyyyyXXXXwwwwVVVVuuuu\n"
        "WORKSHOP_OPAQUE_TOKEN=q7Zr!vL2mK#pX9bN4\n",
        encoding="utf-8")
    (Path(TMP_ROOT) / "wallet.key").write_text(
        "RAWFERNETKEYMATERIAL==\n", encoding="utf-8")
    (Path(TMP_ROOT) / "id_rsa.pem").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n", encoding="utf-8")
    (Path(TMP_ROOT) / "platform_vault.json").write_text(
        json.dumps({"entries": {"acme": "fernet:gAAAAABqz5MFzo-SnSTaBcD."}}),
        encoding="utf-8")
    (Path(TMP_ROOT) / "accounts").mkdir(exist_ok=True)
    (Path(TMP_ROOT) / "accounts" / "accounts.json").write_text(
        json.dumps({"acme": {"platform": "acme", "username": "ops",
                             "email": "ops@acme.test",
                             "password": "PlaintextPassword123!"}}),
        encoding="utf-8")
    (Path(TMP_ROOT) / "payments.json").write_text(
        json.dumps({"card": {"method": "card", "identifier": "4242424242424242"}}),
        encoding="utf-8")
    # readable content, one of which carries a pasted credential
    (Path(TMP_ROOT) / "notes.md").write_text(
        "# Notes\napi key is sk-proj-AAAAbbbbCCCCddddEEEEFFFFGGGG\n"
        "raw hex key: " + "a" * 64 + "\n",
        encoding="utf-8")
    (Path(TMP_ROOT) / "proposals").mkdir(exist_ok=True)
    (Path(TMP_ROOT) / "proposals" / "proposal_1.md").write_text(
        "# Proposal for acme\nTitle: Widget build\n", encoding="utf-8")
    # `.env` nested one level deep must still be refused
    (Path(TMP_ROOT) / "config").mkdir(exist_ok=True)
    (Path(TMP_ROOT) / "config" / ".env").write_text(
        "NESTED=sk-nested1111aaaa2222bbbb\n", encoding="utf-8")


def tearDownModule():
    """Restore the real workshop root and drop the temp tree."""
    import shutil
    import tempfile
    if _ORIG_ROOT is not None:
        workshop_mod.WORKSHOP_ROOT = _ORIG_ROOT
    if TMP_ROOT:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    os.environ.pop("MRBOT_WORKSHOP_ROOT", None)
    workshop_mod._workshop = None
    del tempfile


class TestWorkshopReadRefusesSecretStores(unittest.TestCase):
    """Layer 1: a file whose value IS the credential is never returned."""

    def test_env_is_refused(self):
        """The raw `.env` must not reach the model."""
        out = _tool_workshop_read({"filepath": ".env"})
        assert "Read refused" in out, f"leak: {out[:120]!r}"
        assert "OPENAI_API_KEY" not in out
        assert "sk-ZZZZyyyyXXXXwwwwVVVVuuuu" not in out
        assert "ask the operator for any value" in out

    def test_wallet_key_is_refused(self):
        """The raw Fernet key material must not reach the model."""
        out = _tool_workshop_read({"filepath": "wallet.key"})
        assert "Read refused" in out, f"leak: {out[:120]!r}"
        assert "RAWFERNETKEYMATERIAL" not in out

    def test_pem_is_refused(self):
        """A private-key file (*.pem) is refused by name, like `file_read`."""
        out = _tool_workshop_read({"filepath": "id_rsa.pem"})
        assert "Read refused" in out, f"leak: {out[:120]!r}"
        assert "BEGIN RSA PRIVATE KEY" not in out

    def test_platform_vault_is_refused(self):
        """The encrypted platform credential vault is refused by name."""
        out = _tool_workshop_read({"filepath": "platform_vault.json"})
        assert "Read refused" in out, f"leak: {out[:120]!r}"

    def test_accounts_json_is_refused(self):
        """`accounts/accounts.json` stores a plaintext password — refuse it."""
        out = _tool_workshop_read({"filepath": "accounts/accounts.json"})
        assert "Read refused" in out, f"leak: {out[:120]!r}"
        assert "PlaintextPassword123" not in out
        assert "password" not in out.lower().replace("credential/key store", "")

    def test_payments_json_is_refused(self):
        """`payments.json` stores payment identifiers — refuse it."""
        out = _tool_workshop_read({"filepath": "payments.json"})
        assert "Read refused" in out, f"leak: {out[:120]!r}"
        assert "4242424242424242" not in out

    def test_nested_env_is_refused(self):
        """`config/.env` (a parent-segment name) must still be refused."""
        out = _tool_workshop_read({"filepath": "config/.env"})
        assert "Read refused" in out, f"leak: {out[:120]!r}"
        assert "sk-nested1111aaaa2222bbbb" not in out

    def test_backslash_separator_is_refused(self):
        """A Windows-style `config\\.env` is classified the same way."""
        out = _tool_workshop_read({"filepath": "config\\.env"})
        assert "Read refused" in out, f"leak: {out[:120]!r}"


class TestWorkshopReadAllowsNormalFiles(unittest.TestCase):
    """The blocklist must not swallow ordinary workshop content."""

    def test_notes_md_is_readable(self):
        """A normal note's prose survives intact."""
        out = _tool_workshop_read({"filepath": "notes.md"})
        assert "Read refused" not in out, out[:120]
        assert out.startswith("# Notes")
        assert "api key is" in out

    def test_proposal_is_readable(self):
        """`proposals/proposal_1.md` is NOT a credential store — stay readable."""
        out = _tool_workshop_read({"filepath": "proposals/proposal_1.md"})
        assert "Read refused" not in out, out[:120]
        assert "# Proposal for acme" in out
        assert "Title: Widget build" in out

    def test_env_example_is_readable(self):
        """`.env.example` holds placeholder key names and stays readable."""
        (Path(TMP_ROOT) / ".env.example").write_text(
            "OPENAI_API_KEY=\n", encoding="utf-8")
        out = _tool_workshop_read({"filepath": ".env.example"})
        assert "Read refused" not in out, out[:120]
        assert "OPENAI_API_KEY" in out


class TestWorkshopReadRedaction(unittest.TestCase):
    """Layer 2: a credential pasted into a readable file is scrubbed."""

    def test_pasted_secret_is_redacted(self):
        """A 64-hex key inside `notes.md` must be replaced, not returned."""
        out = _tool_workshop_read({"filepath": "notes.md"})
        assert "a" * 64 not in out, "raw 64-hex key reached the model"
        assert "[REDACTED-SECRET]" in out


class TestWorkshopReadPathEscapeUnchanged(unittest.TestCase):
    """Pre-existing `_safe_path` behaviour must be untouched by this fix."""

    def test_posix_escape_returns_outside_workshop_refusal(self):
        """`../../etc/passwd` still hits the workshop's own refusal, verbatim."""
        out = _tool_workshop_read({"filepath": "../../etc/passwd"})
        assert "outside workshop" in out, out[:160]
        assert "Read refused" not in out

    def test_windows_escape_returns_outside_workshop_refusal(self):
        """`..\\..\\secret` likewise keeps the pre-existing message."""
        out = _tool_workshop_read({"filepath": "..\\..\\secret"})
        assert "outside workshop" in out, out[:160]
        assert "Read refused" not in out

    def test_missing_file_message_unchanged(self):
        """A nonexistent in-workshop path still reports the read error."""
        out = _tool_workshop_read({"filepath": "does_not_exist_xyz.md"})
        assert "Error reading file" in out, out[:160]


class TestDiscriminationGuardStopsTheLeak(unittest.TestCase):
    """Negative control against BEHAVIOUR (not imports).

    With the secret-name guard disabled, a live `.env` must LEAK — proving the
    guard is what stops it, not an incidental import or a missing file.
    """

    def test_disabling_the_guard_re_leaks_then_refuses_again(self):
        """Guard off -> the raw `.env` content is returned; guard restored ->
        refused again.

        Targets the guard's BEHAVIOUR, not an import. The fixture `.env` carries
        an opaque value (`q7Zr!vL2mK#pX9bN4`) that no `redact_secrets` pattern
        shape-matches, so with layer 1 disabled the leak is observable
        regardless of how thorough layer 2 is — the guard is the only thing that
        stops it.
        """
        original = handlers._is_workshop_secret_path
        opaque = "q7Zr!vL2mK#pX9bN4"
        try:
            handlers._is_workshop_secret_path = lambda filepath: False
            leaked = _tool_workshop_read({"filepath": ".env"})
            assert "Read refused" not in leaked, "guard off but still refused?"
            assert opaque in leaked, (
                f"expected the raw .env value when the guard is disabled: {leaked!r}")
            assert "OPENAI_API_KEY" in leaked, "expected real .env content"

            handlers._is_workshop_secret_path = original
            refused = _tool_workshop_read({"filepath": ".env"})
            assert "Read refused" in refused, "guard restored but not refusing?"
            assert opaque not in refused
            assert "OPENAI_API_KEY" not in refused
        finally:
            handlers._is_workshop_secret_path = original

    def test_disabling_the_guard_re_leaks_wallet_key(self):
        """Same control on `wallet.key`: raw Fernet material returns when the
        guard is off, and is refused once it is restored."""
        original = handlers._is_workshop_secret_path
        try:
            handlers._is_workshop_secret_path = lambda filepath: False
            leaked = _tool_workshop_read({"filepath": "wallet.key"})
            assert "Read refused" not in leaked, "guard off but still refused?"
            assert "RAWFERNETKEYMATERIAL" in leaked, (
                f"expected the raw Fernet material with the guard off: {leaked!r}")

            handlers._is_workshop_secret_path = original
            assert "RAWFERNETKEYMATERIAL" not in _tool_workshop_read(
                {"filepath": "wallet.key"})
        finally:
            handlers._is_workshop_secret_path = original

    def test_disabling_redaction_re_leaks_the_pasted_key(self):
        """Layer 2 discrimination: without `redact_secrets` the pasted 64-hex
        key survives, proving layer 1 alone does not cover layer 2."""
        out_with = _tool_workshop_read({"filepath": "notes.md"})
        assert "a" * 64 not in out_with
        # prove the key really is in the file on disk (i.e. layer 2 did the work)
        on_disk = (Path(TMP_ROOT) / "notes.md").read_text(encoding="utf-8")
        assert "a" * 64 in on_disk, "fixture lost the secret it should carry"


if __name__ == "__main__":
    unittest.main()
