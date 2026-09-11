import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agents.sql_safety import execute_readonly_query, validate_readonly_sql


class TestSqlToolSafety(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "agent.db"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO facts(value) VALUES ('ok')")
            conn.commit()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_select_returns_rows(self):
        result = json.loads(execute_readonly_query(
            "SELECT id, value FROM facts", self.db_path))
        self.assertEqual(result[0]["value"], "ok")

    def test_malformed_and_mutating_sql_are_rejected(self):
        for sql in (
            "SELEC value FROM facts",
            "UPDATE facts SET value='changed'",
            "DELETE FROM facts",
            "SELECT value FROM facts; DELETE FROM facts",
            "PRAGMA journal_mode=WAL",
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(ValueError):
                    validate_readonly_sql(sql, self.db_path)

    def test_connection_is_closed_after_success_and_failure(self):
        execute_readonly_query("SELECT value FROM facts", self.db_path)
        with self.assertRaises(ValueError):
            execute_readonly_query("SELEC value FROM facts", self.db_path)
        renamed = self.db_path.with_suffix(".renamed")
        self.db_path.rename(renamed)
        self.assertTrue(renamed.exists())

    def test_safety_gate_blocks_invalid_query_before_allowing_it(self):
        from agents.safety_gate import SafetyDecision, SafetyGate
        with patch("agents.tool_safety.resolve_project_path", return_value=self.db_path):
            allowed, reason, decision = SafetyGate().check(
                "query_database", {"sql": "UPDATE facts SET value='bad'"})
        self.assertFalse(allowed)
        self.assertEqual(decision, SafetyDecision.BLOCKED)
        self.assertIn("Unsafe SQL", reason)


if __name__ == "__main__":
    unittest.main()
