import tempfile
import unittest
from pathlib import Path

from agents.core.persistence_contract import (
    authority_for,
    validate_store_paths,
)


class TestPersistenceContract(unittest.TestCase):
    def test_rejects_unknown_store(self):
        with self.assertRaisesRegex(ValueError, "Unknown persistence store"):
            validate_store_paths({"unknown": "unknown.db"})

    def test_rejects_shared_store_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            shared = Path(tmpdir) / "shared.db"
            with self.assertRaisesRegex(ValueError, "share path"):
                validate_store_paths({
                    "earning": shared,
                    "memory": shared,
                })

    def test_accepts_distinct_store_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            validate_store_paths({
                "earning": Path(tmpdir) / "earning.db",
                "memory": Path(tmpdir) / "memory.db",
                "portfolio": Path(tmpdir) / "portfolio.db",
                "autonomous_runs": Path(tmpdir) / "runs.db",
            })

    def test_authority_metadata_is_available(self):
        store = authority_for("autonomous_runs")
        self.assertEqual(store.filename, "autonomous_runs.db")
        self.assertIn("idempotency", store.authority)


if __name__ == "__main__":
    unittest.main()
