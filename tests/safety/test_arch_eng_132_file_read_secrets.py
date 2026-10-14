"""ARCH-ENG-132: `file_read` must not return credential stores to the model.

Reproduced pre-fix by EXECUTION (not inference):
    execute_tool('file_read', {'path': '.env'})          -> 13,418 chars, 264 credential lines
    execute_tool('file_read', {'path': 'wallet.key'})    -> the raw Fernet wallet key
    execute_tool('file_read', {'path': 'data/platform_vault.json'}) -> vault blobs

`file_read` is READONLY and auto-allowed, but PROJECT_ROOT CONTAINS the secret
stores, so the credential vault's "the model never sees a password" contract was
defeated by a tool that never touches the vault.
"""
import os
from pathlib import Path

import pytest

from agents.safety.handlers import _is_secret_file, _tool_file_read
from agents.safety.policy import PROJECT_ROOT, resolve_project_path


# ── the secret stores are refused outright ─────────────────────────────────

@pytest.mark.parametrize("path", [
    ".env",
    "wallet.key",
    "data/platform_vault.json",
    "data/platform_vault.key",
])
def test_secret_store_is_refused(path):
    """A file whose value IS the credential must never reach the model."""
    try:
        p = resolve_project_path(path)
    except FileNotFoundError:
        pytest.skip(f"{path} not present in this checkout (gitignored)")
    if not p.exists():
        pytest.skip(f"{path} not present in this checkout (gitignored)")
    out = _tool_file_read({"path": path})
    assert "Read refused" in out, f"{path} leaked to the model: {out[:80]!r}"


@pytest.mark.parametrize("name", [
    ".env", ".env.local", ".env.production", "id_rsa.pem", "server.key",
    "wallet.key", "platform_vault.key", "platform_vault.json", "wallets.json",
    "credentials.json", "secrets.json", ".netrc", ".npmrc", "store.p12",
])
def test_is_secret_file_classifies_by_name(name):
    assert _is_secret_file(Path("/repo") / name) is True


@pytest.mark.parametrize("name", [
    "README.md", "CHANGELOG.md", "main.py", "app/version.py",
    ".env.example", ".env.example.txt", "keyboard.py", "monkey.txt",
])
def test_is_secret_file_allows_normal_files(name):
    """The blocklist must not swallow ordinary project files."""
    assert _is_secret_file(Path("/repo") / name) is False


# ── a secret pasted into a readable file is redacted ───────────────────────

def test_pasted_secret_in_readable_file_is_redacted(tmp_path):
    """Layer 2: a credential in a non-secret file is scrubbed by redact_secrets."""
    f = tmp_path / "notes.md"
    # 64-hex raw key shape + fernet token shape, both matched by redact_secrets
    f.write_text(
        "key: " + "a" * 64 + "\n"
        "fernet:gAAAAABqz5MFzo-SnSTaBcD.\n",
        encoding="utf-8",
    )
    # place it inside PROJECT_ROOT so resolve_project_path accepts it
    rel = f.relative_to(PROJECT_ROOT) if str(f).startswith(str(PROJECT_ROOT)) else None
    if rel is None:
        target = PROJECT_ROOT / "_arch132_probe.md"
        target.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            out = _tool_file_read({"path": target.name})
        finally:
            target.unlink(missing_ok=True)
    else:
        out = _tool_file_read({"path": str(rel)})
    assert "a" * 64 not in out, "raw 64-hex key reached the model"
    assert "REDACTED" in out


def test_clean_readable_file_is_not_redacted(tmp_path):
    """Ordinary prose must survive untouched (no over-blocking)."""
    target = PROJECT_ROOT / "_arch132_probe_clean.md"
    target.write_text("# Notes\nnormal text with a short hash 3f8a2b1c\n", encoding="utf-8")
    try:
        out = _tool_file_read({"path": target.name})
    finally:
        target.unlink(missing_ok=True)
    assert out.startswith("# Notes")
    assert "3f8a2b1c" in out  # short hashes are not secret-shaped


def test_missing_file_message_unchanged():
    """A nonexistent path still reports not-found (behavior unchanged)."""
    out = _tool_file_read({"path": "does_not_exist_xyz.md"})
    assert "not found" in out.lower() or "read error" in out.lower()


# ── discrimination: the fix actually changes behavior ──────────────────────

def test_discrimination_removing_the_guard_leaks(monkeypatch):
    """Negative control against BEHAVIOR (not imports): with the secret-file
    guard disabled, a live `.env` must leak — proving the guard is what stops it."""
    target = PROJECT_ROOT / ".env"
    created = False
    if not target.exists():
        target.write_text("NOUS_API_KEY=placeholder-for-discrimination-test\n", encoding="utf-8")
        created = True
    try:
        original = _is_secret_file
        monkeypatch.setattr(
            "agents.safety.handlers._is_secret_file", lambda p: False
        )
        out = _tool_file_read({"path": ".env"})
        assert "Read refused" not in out, "guard disabled but still refused?"
        assert "NOUS_API_KEY" in out, "expected the real .env content when guard is off"
        monkeypatch.setattr("agents.safety.handlers._is_secret_file", original)
        # and with the guard restored it is refused again
        assert "Read refused" in _tool_file_read({"path": ".env"})
    finally:
        if created:
            target.unlink(missing_ok=True)
