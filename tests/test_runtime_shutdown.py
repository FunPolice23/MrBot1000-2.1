import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from main import MainWindow


class TestMainWindowShutdown(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_shutdown_stops_threads_and_closes_db(self):
        window = MainWindow.__new__(MainWindow)
        window._shutting_down = False
        window._shutdown_ollama = MagicMock()

        manager = MagicMock()
        manager.isRunning.return_value = True
        summarizer = MagicMock()
        summarizer.isRunning.return_value = True
        db = MagicMock()

        window.manager = manager
        window.summarizer = summarizer
        window.db = db

        window.shutdown()

        manager.stop.assert_called_once_with()
        summarizer.stop.assert_called_once_with()
        manager.wait.assert_called_once_with(5000)
        summarizer.wait.assert_called_once_with(5000)
        manager.terminate.assert_called_once_with()
        summarizer.terminate.assert_called_once_with()
        db.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
