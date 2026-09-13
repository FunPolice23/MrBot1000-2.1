import tempfile
import unittest
from pathlib import Path

from agents.workshop import Workshop


class TestWorkshop(unittest.TestCase):
    def test_custom_root_creates_shared_structure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "ai_workshop"
            workshop = Workshop(str(root), max_bytes=1024)
            self.assertTrue(root.is_dir())
            self.assertTrue((root / "proposals").is_dir())
            self.assertTrue(workshop.create_folder("projects/demo"))
            self.assertTrue(workshop.write_file("projects/demo/notes.md", "hello"))
            self.assertEqual(workshop.read_file("projects/demo/notes.md"), "hello")

    def test_paths_cannot_escape_workshop(self):
        with tempfile.TemporaryDirectory() as temp:
            workshop = Workshop(temp, max_bytes=1024)
            self.assertFalse(workshop.write_file("../outside.txt", "blocked"))
            self.assertFalse(workshop.create_folder("../../outside"))
            self.assertIn("outside workshop", workshop.read_file("../outside.txt"))

    def test_quota_rejects_new_bytes_but_allows_same_size_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            workshop = Workshop(temp, max_bytes=5)
            self.assertTrue(workshop.write_file("notes/a.txt", "12345"))
            self.assertFalse(workshop.write_file("notes/b.txt", "x"))
            self.assertTrue(workshop.write_file("notes/a.txt", "abcde"))
            stats = workshop.storage_stats()
            self.assertEqual(stats["used_bytes"], 5)
            self.assertEqual(stats["remaining_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
