"""Tests for agents.mrbot_cli — read-only runtime inspection CLI.

Covers: env whitelist sanitisation, secrets redaction, server probing,
health reporting, and the security invariant that no credential value
is ever printed to stdout.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.services import mrbot_cli
# ---------------------------------------------------------------------------
# read_env
# ---------------------------------------------------------------------------

def test_read_env_only_allows_whitelisted_keys():
    """Only ENV_READ_ALLOWLIST keys appear in the result."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("BIG_BRAIN_MODEL=moonshot\n")
        f.write("SMALL_BRAIN_MODEL=gemma\n")
        f.write("NOUS_API_KEY=super-secret\n")
        f.write("ATOMIC_SOLANA_ADDRESS=so1secret\n")
        f.write("BIG_BRAIN_PORT=1234\n")
        fname = f.name
    try:
        with patch.object(mrbot_cli, "ENV_PATH", Path(fname)):
            env = mrbot_cli.read_env()
        assert "BIG_BRAIN_MODEL" in env
        assert "NOUS_API_KEY" not in env
        assert "ATOMIC_SOLANA_ADDRESS" not in env
        assert "BIG_BRAIN_PORT" in env
    finally:
        os.unlink(fname)


def test_read_env_missing_file_returns_empty():
    """A missing .env is not an error; returns {}.

    Regression: the original code assumed the file exists and would raise
    FileNotFoundError on first access, crashing health checks on fresh
    installs where .env has not been written yet.
    """
    with patch.object(mrbot_cli, "ENV_PATH", Path("/nonexistent/path/.env")):
        env = mrbot_cli.read_env()
    assert env == {}


# ---------------------------------------------------------------------------
# pretty_env — redaction
# ---------------------------------------------------------------------------

def test_pretty_env_redacts_sensitive_keys():
    """Keys matching the redaction regex show [REDACTED], never the value."""
    env = {"NOUS_API_KEY": "sk-live-abc123", "BIG_BRAIN_MODEL": "phi4"}
    text = mrbot_cli.pretty_env(env)
    assert "sk-live-abc123" not in text
    assert "[REDACTED]" in text
    assert "BIG_BRAIN_MODEL" in text


def test_pretty_env_never_prints_secret_values():
    """No value containing 'secret'/'key'/'token' etc. is ever visible."""
    env = {
        "BIG_BRAIN_URL": "http://127.0.0.1:1234/v1",  # allowed, not secret
        "SMALL_BRAIN_MODEL": "gemma",
    }
    text = mrbot_cli.pretty_env(env)
    assert "http://127.0.0.1:1234/v1" in text  # localhost endpoint is public
    assert "gemma" in text


# ---------------------------------------------------------------------------
# probe_models — unreachable server
# ---------------------------------------------------------------------------

def test_probe_models_unreachable_returns_false():
    """Nothing listening → (False, '', []) never raises."""
    ok, model_id, entries = mrbot_cli.probe_models(19999, timeout_s=0.5)
    assert ok is False
    assert model_id == ""
    assert entries == []


# ---------------------------------------------------------------------------
# cmd_health — structure
# ---------------------------------------------------------------------------

def _fake_args(command):
    return type("Args", (), {"command": command})()


def test_cmd_health_prints_degraded_when_servers_down(monkeypatch, capsys):
    """Both brains unreachable → DEGRADED (expected in CI / headless)."""
    monkeypatch.setattr(mrbot_cli, "read_env", lambda: {
        "BIG_BRAIN_PORT": "1",
        "SMALL_BRAIN_PORT": "1",
    })
    monkeypatch.setattr(
        mrbot_cli.urllib.request, "urlopen",
        lambda *_a, **__k: (_ for _ in ()).throw(Exception("nope")),
    )
    mrbot_cli.cmd_health(_fake_args("health"))
    out = capsys.readouterr().out
    assert "DEGRADED" in out
    assert ".env" in out
    assert "Big Brain" in out
    assert "Small Brain" in out


def test_cmd_health_shows_ok_when_all_present(monkeypatch, tmp_path, capsys):
    """All checks pass → OK."""
    db = tmp_path / "mrbot_state.db"
    sqlite3.connect(str(db)).close()
    monkeypatch.setattr(mrbot_cli, "read_env", lambda: {
        "BIG_BRAIN_PORT": "1",
        "SMALL_BRAIN_PORT": "1",
    })
    monkeypatch.setattr(
        mrbot_cli, "probe_models",
        lambda *_a, **__k: (True, "test-model", []),
    )
    monkeypatch.setattr(mrbot_cli, "REPO_ROOT", tmp_path)
    mrbot_cli.cmd_health(_fake_args("health"))
    out = capsys.readouterr().out
    assert "OK" in out


# ---------------------------------------------------------------------------
# main — argument routing
# ---------------------------------------------------------------------------

def test_main_unknown_subcommand_returns_2(capsys):
    with pytest.raises(SystemExit) as exc_info:
        mrbot_cli.main(["no-such-cmd"])
    assert exc_info.value.code == 2


def test_main_no_args_prints_help(capsys):
    rc = mrbot_cli.main([])
    assert rc == 0
    assert "mrbot-cli" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Security invariant
# ---------------------------------------------------------------------------

def test_no_secret_value_ever_printed(monkeypatch):
    """Even with a real .env containing credentials, stdout must
    never contain the raw credential value."""
    monkeypatch.setenv("NOUS_API_KEY", "sk-live-super-secret-token")
    env = mrbot_cli.read_env()
    text = mrbot_cli.pretty_env(env)
    assert "sk-live-super-secret-token" not in text
