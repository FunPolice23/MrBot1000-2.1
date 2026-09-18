"""Tests for the `.env` write guard (test isolation + protected keys).

Regression these lock in: tests/test_provider_selection.py called
`_persist_role_model(..., )` without `persist=False`; because the default was
True it wrote the operator's live `.env` and reset BIG_BRAIN_MODEL to a
non-existent path on every test run.

The rule: a test run must be *structurally* incapable of writing operator
config. `set_env_values` refuses under pytest unless `MRBOT_ENV_PATH` points at
an explicit temp file.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest


def test_set_env_values_refuses_to_write_under_pytest(monkeypatch):
    """Without an explicit override, a test must not be able to write .env."""
    monkeypatch.delenv("MRBOT_ENV_PATH", raising=False)
    from main import EnvWriteRefused, set_env_values

    with pytest.raises(EnvWriteRefused):
        set_env_values({"BIG_BRAIN_MODEL": "D:/whatever/model.gguf"})


def test_mrbot_env_path_redirects_the_write(monkeypatch, tmp_path):
    """With MRBOT_ENV_PATH set, the write lands in the temp file, atomically."""
    target = tmp_path / "redirected.env"
    target.write_text("EXISTING=1\n", encoding="utf-8")
    monkeypatch.setenv("MRBOT_ENV_PATH", str(target))

    from main import env_file_path, set_env_values

    assert env_file_path() == target
    assert set_env_values({"BIG_BRAIN_MODEL": "D:/models/ok.gguf"}) is True

    text = target.read_text(encoding="utf-8")
    assert "BIG_BRAIN_MODEL=D:/models/ok.gguf" in text
    assert "EXISTING=1" in text, "unknown keys must be preserved"


def test_empty_model_value_never_blanks_a_saved_selection(monkeypatch, tmp_path):
    """A settings save with an unselected dropdown must not erase the key.

    `_current_model_path` returns "" when nothing is selected, and Save writes
    that value — which used to blank BIG_BRAIN_MODEL.
    """
    target = tmp_path / "protected.env"
    target.write_text("BIG_BRAIN_MODEL=D:/models/kept.gguf\n", encoding="utf-8")
    monkeypatch.setenv("MRBOT_ENV_PATH", str(target))

    from main import set_env_values

    # Only an empty protected value: nothing to write at all.
    assert set_env_values({"BIG_BRAIN_MODEL": ""}) is False
    assert "BIG_BRAIN_MODEL=D:/models/kept.gguf" in target.read_text(encoding="utf-8")

    # Mixed dict: the protected key is dropped, the real setting still lands.
    assert set_env_values({"BIG_BRAIN_MODEL": "   ", "BIG_BRAIN_THREADS": "8"}) is True
    text = target.read_text(encoding="utf-8")
    assert "BIG_BRAIN_MODEL=D:/models/kept.gguf" in text, "protected key was blanked"
    assert "BIG_BRAIN_THREADS=8" in text


def test_persist_role_model_defaults_to_not_writing():
    """The default must be opt-in; production callers pass it explicitly.

    The implementation lives on ``BrainLaunchWorker`` — ``DualBrainControl``'s
    methods are rebound at module level (``dual_brain_control.py:3637-3652``)
    behind a generic ``*args, **kwargs`` wrapper, so introspecting the attribute
    on DualBrainControl yields no named parameters.
    """
    from gui.dual_brain_control import BrainLaunchWorker

    fn = getattr(BrainLaunchWorker, "_persist_role_model")
    sig = inspect.signature(fn)
    assert "persist" in sig.parameters, (
        "could not introspect the real _persist_role_model implementation")
    assert sig.parameters["persist"].default is False, (
        "persist must default to False, or a test run rewrites the operator's .env"
    )


def test_persist_role_model_without_persist_does_not_write(monkeypatch, tmp_path):
    """Calling with the default must leave the filesystem alone."""
    monkeypatch.delenv("MRBOT_ENV_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    from gui.dual_brain_control import DualBrainControl
    from agents.dual_brain_runtime import BrainRole, DualBrainRuntime

    control = DualBrainControl.__new__(DualBrainControl)
    runtime = DualBrainRuntime.from_env()
    cfg = runtime.config(BrainRole.BIG)

    # Exactly the call shape used by tests/test_provider_selection.py:106.
    control._persist_role_model(False, r"D:\models\qwen3.gguf", runtime, cfg)

    assert not (tmp_path / ".env").exists(), "default call wrote .env"
    assert cfg.model == r"D:\models\qwen3.gguf"
    assert os.environ["BIG_BRAIN_MODEL"] == r"D:\models\qwen3.gguf"
