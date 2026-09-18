"""Shared pytest configuration for the MrBot1000 test suite.

PySide6 aborts the whole process (a hard crash with no Python traceback) when a
QWidget is constructed and no QApplication exists yet. Test modules that build
GUI widgets used to create their own QApplication; any module that forgot to
would take the entire pytest run down with it.

This module guarantees exactly one offscreen QApplication for the whole session,
so every GUI-constructing test is safe and the suite can run as a whole.

Must set QT_QPA_PLATFORM before PySide6 is imported, hence the top-of-file env
setup.
"""

import os

# Offscreen platform: no display required (CI / headless / SSH sessions).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _qt_app_session():
    """Create a single session-wide QApplication for Qt widget tests."""
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        # PySide6 unavailable: let non-GUI tests run unimpeded.
        yield None
        return

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(scope="session", autouse=True)
def _operator_env_is_untouched():
    """Fail the session if any test rewrites the operator's `.env`.

    A test run must be structurally incapable of altering operator config, but a
    guard test alone cannot bracket the suite (pytest gives no ordering
    guarantee). This snapshots both candidate paths at session start and asserts
    they are byte-identical at session end:

      * `Path(".env")`                 — CWD-relative, what set_env_values uses
      * `<repo>/.env`                  — absolute, what the old non-atomic
                                          `_persist_settings` fallback wrote

    Regression: tests/test_provider_selection.py called `_persist_role_model`
    without `persist=False`, and the default of True rewrote the live `.env`
    (resetting BIG_BRAIN_MODEL to a non-existent path).
    """
    from pathlib import Path

    repo_env = Path(__file__).resolve().parent.parent / ".env"
    candidates = [Path(".env"), repo_env]

    def _snapshot(p: Path):
        try:
            return p.read_bytes() if p.exists() else None
        except Exception as exc:  # unreadable: record the reason, don't crash
            return f"<unreadable: {exc}>".encode()

    before = {p: _snapshot(p) for p in candidates}
    yield
    for p, original in before.items():
        after = _snapshot(p)
        assert after == original, (
            f"the test suite modified {p} — a test wrote operator config. "
            f"Route persistence through MRBOT_ENV_PATH instead."
        )
