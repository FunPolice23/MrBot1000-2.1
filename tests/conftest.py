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

# Redirect every `set_env_values` write to a throwaway file for the whole
# session. Production code correctly persists to the real `.env`, but a test
# run must be structurally incapable of altering operator config — and without
# this, GUI paths that legitimately save (e.g. the per-device enable toggle
# writing <ROLE>_ENABLED) rewrote the live `.env` and tripped the guard below
# (ARCH-ENG-049). `app.environment.env_file_path()` honours this override.
import atexit  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_MRBOT_TEST_ENV = _Path(tempfile.gettempdir()) / "mrbot_test_env_do_not_edit"
try:
    _MRBOT_TEST_ENV.write_text("", encoding="utf-8")
    os.environ["MRBOT_ENV_PATH"] = str(_MRBOT_TEST_ENV)
    atexit.register(lambda: _MRBOT_TEST_ENV.unlink(missing_ok=True))
except OSError:
    pass

# Same isolation for the device policy (`settings.json`). GUI tests construct a
# real `DualBrainControl`, whose widget seeding fires `valueChanged` ->
# `_on_brain_settings_changed` -> `save_policy()` with no root, so without this a
# test run rewrites the operator's LIVE settings.json (ARCH-ENG-057). A canary
# run proved it: the operator's saved per-device model and every llama.cpp
# setting were wiped by merely building the widget.
_MRBOT_TEST_SETTINGS = _Path(tempfile.gettempdir()) / "mrbot_test_settings_do_not_edit.json"
try:
    _MRBOT_TEST_SETTINGS.write_text("{}", encoding="utf-8")
    os.environ["MRBOT_DEVICE_SETTINGS_PATH"] = str(_MRBOT_TEST_SETTINGS)
    atexit.register(lambda: _MRBOT_TEST_SETTINGS.unlink(missing_ok=True))
except OSError:
    pass

# Park the autonomous manager loop for the whole test session. `MainWindow`
# starts ManagerThread, whose first cycle makes a real provider call; with no
# llama-server listening that call blocks in TCP connect / retry-sleep and the
# thread is still inside httpx when the test tears the window down — an access
# violation that kills the pytest process (exit 139) and loses the whole run.
# Tests exercise manager *units* directly, never the live loop, so parking it is
# the right isolation and costs nothing.
#
# Set (not setdefault): main.py calls load_dotenv(override=True), and the
# operator's .env sets STARTUP_DELAY_SECS=0, which would clobber a default.
os.environ["STARTUP_DELAY_SECS"] = "3600"
# Also disable provider retries so any stray call fails fast instead of
# sleeping through its retry budget while a test tears down.
os.environ.setdefault("OPENAI_MAX_RETRIES", "0")

import pytest  # noqa: E402


# ── QThread registry ────────────────────────────────────────────────────────
# Installed at import time (before any test can construct a thread) so the
# per-test cleanup sweep can see every QThread the suite creates.
import weakref  # noqa: E402

_LIVE_QT_THREADS = weakref.WeakSet()
try:
    from PySide6.QtCore import QThread as _QThread  # noqa: E402

    _orig_qthread_init = _QThread.__init__

    def _tracked_qthread_init(self, *a, **kw):
        _orig_qthread_init(self, *a, **kw)
        _LIVE_QT_THREADS.add(self)

    _QThread.__init__ = _tracked_qthread_init
except Exception:  # PySide6 unavailable: non-GUI tests still run
    pass


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
def _track_mainwindow_instances():
    """Register every MainWindow instance so leaks can be closed cheaply.

    Patching `__init__` once per session avoids scanning the whole heap after
    each of 1000+ tests.
    """
    import weakref
    try:
        import main
    except Exception:
        yield
        return

    live = weakref.WeakSet()
    original_init = main.MainWindow.__init__

    def tracked_init(self, *a, **kw):
        # main.py runs load_dotenv(override=True) at import, which restores the
        # operator's STARTUP_DELAY_SECS=0. Re-assert the parked value so the
        # live manager loop cannot start mid-suite.
        os.environ["STARTUP_DELAY_SECS"] = "3600"
        original_init(self, *a, **kw)
        live.add(self)

    main.MainWindow.__init__ = tracked_init
    try:
        yield live
    finally:
        main.MainWindow.__init__ = original_init


@pytest.fixture(autouse=True)
def _no_leaked_mainwindow_threads(request, _track_mainwindow_instances):
    """Stop any MainWindow-owned QThreads a test forgot to shut down.

    `MainWindow.__init__` starts ManagerThread + SummarizerThread, which do real
    socket I/O, and tab widgets start parentless QThreads (e.g. the GPU poller).
    A test that builds a window and does not call `shutdown()` leaves those
    threads running; when the Qt event loop is later torn down mid-`socket.read`
    or mid-`nvidia-smi` the process dies with an access violation (exit 139) and
    the whole run is lost. Test *order* therefore decided whether the suite
    passed, which is not acceptable.

    Runs before AND after every test. Each window is validity-checked first: one
    whose C++ side is already destroyed would crash (not raise) on close().
    Cleaning up at test *start* as well means a test that pumps the event loop
    in its own tearDown cannot be handed a stale window from an earlier test.
    """
    _cleanup_leaked_windows(_track_mainwindow_instances)
    yield
    _cleanup_leaked_windows(_track_mainwindow_instances)
    _stop_running_qt_threads() if os.environ.get("MRBOT_TEST_THREAD_SWEEP") == "1" else None


def _cleanup_leaked_windows(live):
    """Shut down and close every still-live MainWindow (never raises)."""
    try:
        import shiboken6
    except Exception:
        shiboken6 = None
    for win in list(live):
        if shiboken6 is not None and not shiboken6.isValid(win):
            continue
        try:
            win.shutdown()
        except Exception:
            pass
        try:
            win.close()
        except Exception:
            pass


def _stop_running_qt_threads(limit: int = 40):
    """Best-effort stop of every live QThread (bounded, never raises).

    Off by default: terminating a QThread that is mid-`socket.read` is what
    causes the access violation, so this must not run on every test. Enable with
    MRBOT_TEST_THREAD_SWEEP=1 when diagnosing leaked threads.
    """
    threads = _live_qt_threads()
    for th in list(threads)[:limit]:
        try:
            import shiboken6
            if not shiboken6.isValid(th):
                continue
        except Exception:
            pass
        try:
            if th.isRunning():
                if hasattr(th, "stop"):
                    th.stop()
                elif hasattr(th, "requestInterruption"):
                    th.requestInterruption()
                th.wait(3000)
        except Exception:
            pass


def _live_qt_threads():
    """WeakSet of every QThread instance created this session."""
    return _LIVE_QT_THREADS


@pytest.fixture(scope="session", autouse=True)
def _operator_env_is_untouched():
    """Fail the session if any test rewrites the operator's `.env` or
    `settings.json`.

    A test run must be structurally incapable of altering operator config, but a
    guard test alone cannot bracket the suite (pytest gives no ordering
    guarantee). This snapshots both candidate paths at session start and asserts
    they are byte-identical at session end:

      * `Path(".env")`                 — CWD-relative, what set_env_values uses
      * `<repo>/.env`                  — absolute, what the old non-atomic
                                          `_persist_settings` fallback wrote
      * `<repo>/settings.json`         — the device policy (models + per-device
                                          llama.cpp settings). `MRBOT_ENV_PATH`
                                          only covered `.env`; GUI tests that
                                          build a `DualBrainControl` still wrote
                                          this file until ARCH-ENG-057.

    Regression: tests/test_provider_selection.py called `_persist_role_model`
    without `persist=False`, and the default of True rewrote the live `.env`
    (resetting BIG_BRAIN_MODEL to a non-existent path).
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    repo_env = repo_root / ".env"
    candidates = [Path(".env"), repo_env, repo_root / "settings.json"]

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
            f"Route persistence through MRBOT_ENV_PATH / "
            f"MRBOT_DEVICE_SETTINGS_PATH instead."
        )
