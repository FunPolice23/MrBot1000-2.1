"""gui/workers/db_query_worker.py — run a read-only SQLite query off the GUI thread.

Several tabs (Self-Improvement, Autonomous Learning, …) poll a SQLite table on
a QTimer via the RefreshCoordinator. Doing ``sqlite3.connect`` + ``execute`` on
the GUI thread freezes the UI for the duration of the query (and every poll
tick). This worker moves the query to a background QThread and delivers the
rows back through a signal so the GUI thread only touches widgets.

Read-only by design: it opens the DB, runs one SELECT, and closes. No writes,
no migrations — safe to run concurrently with the app's own writers.
"""

from __future__ import annotations

import sqlite3
from typing import Callable, List, Tuple

from PySide6.QtCore import QThread, Signal


class DbQueryWorker(QThread):
    """Run ``query`` against ``db_path`` off-thread; emit rows (or an error)."""

    # rows: list of tuples; error: "" on success, else a message.
    finished_rows = Signal(list, str)

    def __init__(self, db_path: str, query: str, params: Tuple = (),
                 parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.query = query
        self.params = params

    def run(self) -> None:
        rows: List[Tuple] = []
        error = ""
        try:
            # isolation_level=None -> autocommit read; timeout avoids a hard
            # block if a writer holds the lock briefly.
            conn = sqlite3.connect(self.db_path, timeout=2.0)
            try:
                rows = conn.execute(self.query, self.params).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            error = str(exc)
        except Exception as exc:  # never let a worker crash the app
            error = f"{type(exc).__name__}: {exc}"
        self.finished_rows.emit(rows, error)


def run_db_query(db_path: str, query: str,
                 on_done: Callable[[List[Tuple], str], None],
                 params: Tuple = (), parent=None) -> DbQueryWorker:
    """Convenience: start a DbQueryWorker and wire ``on_done(rows, error)``.

    ``on_done`` runs on the GUI thread (it is connected to a Qt signal), so it
    may safely touch widgets. The worker is kept alive by its parent; callers
    that need to cancel should hold the returned reference.
    """
    worker = DbQueryWorker(db_path, query, params, parent=parent)
    worker.finished_rows.connect(on_done)
    worker.finished.connect(worker.deleteLater)
    worker.start()
    return worker


__all__ = ["DbQueryWorker", "run_db_query"]
