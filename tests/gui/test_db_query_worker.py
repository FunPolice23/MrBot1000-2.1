"""Tests for the off-thread DbQueryWorker (GUI responsiveness fix)."""

import os
import sqlite3
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from gui.workers.db_query_worker import DbQueryWorker, run_db_query  # noqa: E402


class TestDbQueryWorker(unittest.TestCase):
    def _make_db(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t (a TEXT, b INT)")
        conn.executemany("INSERT INTO t VALUES (?, ?)",
                         [("x", 1), ("y", 2), ("z", 3)])
        conn.commit()
        conn.close()
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_returns_rows(self):
        path = self._make_db()
        worker = DbQueryWorker(path, "SELECT a, b FROM t ORDER BY b")
        result = {}
        worker.finished_rows.connect(lambda rows, err: result.update(
            rows=rows, err=err))
        worker.run()  # run synchronously for the test
        self.assertEqual(result["err"], "")
        self.assertEqual(result["rows"], [("x", 1), ("y", 2), ("z", 3)])

    def test_missing_db_reports_error_not_crash(self):
        worker = DbQueryWorker("/nonexistent/path/nope.db", "SELECT 1")
        result = {}
        worker.finished_rows.connect(lambda rows, err: result.update(
            rows=rows, err=err))
        worker.run()
        self.assertNotEqual(result["err"], "")
        self.assertEqual(result["rows"], [])

    def test_bad_sql_reports_error(self):
        path = self._make_db()
        worker = DbQueryWorker(path, "SELECT * FROM no_such_table")
        result = {}
        worker.finished_rows.connect(lambda rows, err: result.update(
            rows=rows, err=err))
        worker.run()
        self.assertNotEqual(result["err"], "")

    def test_params_are_bound(self):
        path = self._make_db()
        worker = DbQueryWorker(path, "SELECT b FROM t WHERE a = ?", ("y",))
        result = {}
        worker.finished_rows.connect(lambda rows, err: result.update(rows=rows))
        worker.run()
        self.assertEqual(result["rows"], [(2,)])

    def test_run_db_query_async_delivers_on_gui_thread(self):
        path = self._make_db()
        done = {}
        worker = run_db_query(
            path, "SELECT count(*) FROM t",
            lambda rows, err: done.update(rows=rows, err=err))
        # Pump the event loop until the worker finishes.
        deadline = time.time() + 5
        while "rows" not in done and time.time() < deadline:
            _app.processEvents()
            time.sleep(0.02)
        self.assertIn("rows", done)
        self.assertEqual(done["rows"], [(3,)])
        self.assertEqual(done["err"], "")
        worker.wait(1000)


if __name__ == "__main__":
    unittest.main()
