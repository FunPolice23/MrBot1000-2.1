import os
import tempfile
import unittest

from earning_memory import EarningMemory


class TestEarningMemory(unittest.TestCase):
    def setUp(self):
        self.tmp_db = tempfile.mktemp(suffix=".db", prefix="memory-")
        self.mem = EarningMemory(db_path=self.tmp_db)

    def tearDown(self):
        if os.path.exists(self.tmp_db):
            os.unlink(self.tmp_db)

    def test_remember_success_tracks_unique_platforms(self):
        self.mem.remember_success("python", "Upwork", 50.0)
        self.mem.remember_success("python", "Upwork", 20.0)
        self.mem.remember_success("python", "Fiverr", 10.0)

        rows = self.mem.get_successful_skills(min_success=1, limit=10)
        self.assertEqual(len(rows), 1)
        row = rows[0]

        self.assertEqual(row["skill"], "python")
        self.assertEqual(row["success"], 3)
        self.assertAlmostEqual(row["revenue"], 80.0)
        self.assertIn("Upwork", row["platforms"])
        self.assertIn("Fiverr", row["platforms"])
        self.assertEqual(row["platforms"].count("Upwork"), 1)


if __name__ == "__main__":
    unittest.main()
