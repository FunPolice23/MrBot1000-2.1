"""Read-only SQLite execution for model-facing database tools."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


_READONLY_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}


def _readonly_authorizer(action: int, _arg1: Any, _arg2: Any,
                         _database: Any, _source: Any) -> int:
    """Allow only query planning/read operations."""
    return (sqlite3.SQLITE_OK if action in _READONLY_ACTIONS
            else sqlite3.SQLITE_DENY)


def _prepare_readonly(conn: sqlite3.Connection, sql: str) -> None:
    """Compile one statement with writes and side effects denied."""
    conn.set_authorizer(_readonly_authorizer)
    # EXPLAIN compiles the statement without executing its data operations.
    conn.execute("EXPLAIN " + sql).fetchone()


def validate_readonly_sql(sql: str, db_path: str | Path) -> None:
    """Raise ValueError unless *sql* is one valid, read-only SQLite statement."""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL must be a non-empty SELECT statement")
    statement = sql.strip()
    with closing(sqlite3.connect(str(db_path))) as conn:
        try:
            _prepare_readonly(conn, statement)
        except sqlite3.Error as exc:
            raise ValueError(f"SQL is not a valid read-only query: {exc}") from exc


def execute_readonly_query(sql: str, db_path: str | Path,
                           limit: int = 50) -> str:
    """Validate and execute a bounded read-only query with guaranteed cleanup."""
    validate_readonly_sql(sql, db_path)
    row_limit = max(0, min(int(limit), 500))
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        conn.set_authorizer(_readonly_authorizer)
        rows = conn.execute(sql).fetchmany(row_limit)
        return json.dumps([dict(row) for row in rows], indent=2, default=str)
