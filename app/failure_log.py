"""Shared ARCH-ENG-109 failure-capture helper.

Writes brain/Live chat-failure diagnostics to a single absolute log file so the
root cause of an intermittent "could not reach its model" is recoverable from
disk regardless of the process cwd (a GUI launch's cwd is unpredictable — the
app may be started from a desktop shortcut whose "Start in" dir is not the repo).

The log path is anchored to the repository root (derived from this file's
location: <repo>/app/ or <repo>/agents/... -> <repo>/brain_failures.log), NOT to
os.getcwd().
"""
import os
import time

_LOG_FILENAME = "brain_failures.log"


def failure_log_path() -> str:
    """Absolute path to brain_failures.log at the repo root."""
    # This file lives at <repo>/app/failure_log.py (or <repo>/agents/...). Walk
    # up to the directory that contains main.py / app/ — the repo root.
    here = os.path.dirname(os.path.abspath(__file__))
    # app/ -> repo root is one level up; agents/x/ is deeper, so climb until we
    # find a marker (main.py or the 'app' package dir).
    cur = here
    for _ in range(5):
        if os.path.isfile(os.path.join(cur, "main.py")) or \
           os.path.isdir(os.path.join(cur, "app")):
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.join(cur, _LOG_FILENAME)


def log_failure(message: str) -> None:
    """Append a timestamped diagnostic line to the failure log. Never raises."""
    try:
        path = failure_log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass
