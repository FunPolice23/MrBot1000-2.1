import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_worker import ROOT_FOLDER


class TestRootScope(unittest.TestCase):
    def test_base_worker_root_points_to_repo_root(self):
        expected = Path(__file__).resolve().parent.parent
        self.assertEqual(Path(ROOT_FOLDER).resolve(), expected)


if __name__ == "__main__":
    unittest.main()
