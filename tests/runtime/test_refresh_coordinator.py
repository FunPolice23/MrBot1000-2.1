import unittest

from PySide6.QtCore import QCoreApplication

from gui.builders.refresh_coordinator import RefreshCoordinator


class TestRefreshCoordinator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_hidden_entries_do_not_refresh(self):
        coordinator = RefreshCoordinator()
        calls = []
        coordinator.register("view", lambda: calls.append("refresh"), 1)
        coordinator._refresh_due()
        self.assertEqual(calls, [])
        coordinator.set_visible("view", True)
        self.assertEqual(calls, ["refresh"])
        coordinator.set_visible("view", False)
        coordinator._refresh_due()
        self.assertEqual(calls, ["refresh"])

    def test_invalid_interval_is_rejected(self):
        coordinator = RefreshCoordinator()
        with self.assertRaises(ValueError):
            coordinator.register("view", lambda: None, 0)


if __name__ == "__main__":
    unittest.main()
