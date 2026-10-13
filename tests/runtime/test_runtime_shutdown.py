import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication
from main import MainWindow


class TestMainWindowShutdown(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_shutdown_closes_db_and_ollama(self):
        # v2.1.77: legacy ManagerThread/SummarizerThread removed. shutdown() now
        # tears down the DB + Ollama executors + tab background threads; there
        # are no manager/summarizer worker threads to stop.
        window = MainWindow.__new__(MainWindow)
        window._shutting_down = False
        window._shutdown_ollama = MagicMock()
        window._stop_tab_background_threads = MagicMock()
        db = MagicMock()
        window.db = db

        window.shutdown()

        window._shutdown_ollama.assert_called_once_with()
        window._stop_tab_background_threads.assert_called_once_with()
        db.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
