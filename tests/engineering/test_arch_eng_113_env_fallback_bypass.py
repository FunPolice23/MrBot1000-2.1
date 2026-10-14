"""ARCH-ENG-113 — an explicit `path=` may not escape MRBOT_ENV_PATH isolation.

`set_env_values(values, path=...)` lets a caller name the .env target directly.
Two GUI persistence paths used that to RETRY a failed write against a hardcoded
`<repo>/.env`:

    gui/widgets/dual_brain_control.py:1796   (_persist_settings)
    gui/workers/provider_lifecycle_backend.py:599  (_write_env_values)

The old guard (`_env_write_refusal`) only refused when MRBOT_ENV_PATH was unset.
With the override SET — exactly the state the suite runs in — the retry was
permitted, and the explicit path pointed at the operator's LIVE .env. One
transient failure on the isolated write therefore rewrote operator config:
CRLF→LF normalisation across the whole file plus a provider toggle, caught by
the session guard in tests/conftest.py as "the test suite modified .env".

The rule now: under pytest the resolved target may never be the repo's own
`.env`, however it was spelled. An explicit *isolated* path still works, so the
legitimate production fallback (CWD != repo root) is untouched outside pytest.
"""
import os
import tempfile
from pathlib import Path

import pytest

REPO = Path(r"D:\MrBot1000_2.0")
LIVE = REPO / ".env"

# Importing pytest is what activates the guard; conftest already sets the
# session override, but be explicit so this module is self-contained.
os.environ.setdefault(
    "MRBOT_ENV_PATH", str(Path(tempfile.gettempdir()) / "mrbot_test_env_do_not_edit"))

from app.environment import EnvWriteRefused, set_env_values  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_live_env():
    """Restore the operator's .env after every test in this module.

    These tests deliberately attempt to write the LIVE .env to prove the guard
    refuses. On the unfixed code the attempt SUCCEEDS, so without this the very
    act of detecting the regression would corrupt operator config — the same
    failure mode as the bug itself.
    """
    before = LIVE.read_bytes()
    yield
    try:
        if LIVE.read_bytes() != before:
            LIVE.write_bytes(before)
    except OSError:
        pass


def test_hardcoded_repo_env_fallback_is_refused_under_pytest():
    """The exact call shape the two GUI fallbacks make must be refused."""
    before = LIVE.read_bytes()
    with pytest.raises(EnvWriteRefused) as excinfo:
        set_env_values({"DISABLE_GROQ": "True"}, path=REPO / ".env")
    assert "live .env" in str(excinfo.value)
    assert LIVE.read_bytes() == before, "the live .env was rewritten anyway"


def test_repo_env_is_refused_even_when_spelled_relatively():
    """Same file, different spelling — the guard resolves the path."""
    before = LIVE.read_bytes()
    cwd = os.getcwd()
    os.chdir(REPO)
    try:
        with pytest.raises(EnvWriteRefused):
            set_env_values({"DISABLE_GROQ": "True"}, path=Path(".env"))
        with pytest.raises(EnvWriteRefused):
            set_env_values({"DISABLE_GROQ": "True"},
                           path=REPO / "sub" / ".." / ".env")
    finally:
        os.chdir(cwd)
    assert LIVE.read_bytes() == before


def test_an_explicit_isolated_path_still_writes(tmp_path):
    """The guard must not break the legitimate use: a caller-supplied temp file."""
    target = tmp_path / "isolated.env"
    target.write_text("KEEP=1\n", encoding="utf-8")
    assert set_env_values({"OPENAI_RATE_PER_SEC": "0.5"}, path=target) is True
    text = target.read_text(encoding="utf-8")
    assert "OPENAI_RATE_PER_SEC=0.5" in text
    assert "KEEP=1" in text


def test_no_override_at_all_is_still_refused(monkeypatch):
    """Rule 1 must survive rule 2 (the original ARCH-ENG-049 invariant)."""
    monkeypatch.delenv("MRBOT_ENV_PATH", raising=False)
    with pytest.raises(EnvWriteRefused) as excinfo:
        set_env_values({"BIG_BRAIN_MODEL": "D:/whatever/model.gguf"})
    assert "MRBOT_ENV_PATH" in str(excinfo.value)


def test_production_outside_pytest_is_unaffected(monkeypatch, tmp_path):
    """The guard is a test-only control: with pytest not in sys.modules, a
    production caller naming the repo .env directly must still succeed."""
    import app.environment as ae

    monkeypatch.setattr(ae.sys, "modules", {k: v for k, v in ae.sys.modules.items()
                                            if k != "pytest"})
    monkeypatch.setenv("MRBOT_ENV_PATH", str(tmp_path / "ignored.env"))
    target = tmp_path / "prod.env"
    target.write_text("A=1\n", encoding="utf-8")
    assert ae._env_write_refusal(target) == ""
    assert set_env_values({"B": "2"}, path=target) is True
    assert "B=2" in target.read_text(encoding="utf-8")


def test_both_gui_fallbacks_still_name_the_repo_env():
    """Document the call sites, so a future edit that 'simplifies' the fallback
    away cannot silently reintroduce the hole."""
    import inspect

    from gui.widgets import dual_brain_control as dbc
    from gui.workers import provider_lifecycle_backend as plb

    for fn in (dbc.DualBrainControl._persist_settings,
               plb.ProviderLifecycleBackend._write_env_values):
        src = inspect.getsource(fn)
        assert "set_env_values(values, path=repo_env)" in src, (
            f"{fn.__qualname__} no longer routes its fallback through the "
            f"guarded writer — verify it cannot reach the live .env")
