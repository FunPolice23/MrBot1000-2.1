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
