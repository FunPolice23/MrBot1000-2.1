import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager import ManagerThread


class TestRuntimeWarnings(unittest.TestCase):
    def test_manager_emits_warning_for_logging_failure(self):
        class DummyDB:
            def log_thought(self, *_args, **_kwargs):
                raise RuntimeError("db unavailable")

        messages = []
        manager = ManagerThread(api_key="", worker=None, db=DummyDB())
        manager.log = manager.log if hasattr(manager, "log") else None
        manager.log = type("Sig", (), {"emit": lambda self, msg: messages.append(msg)})()

        manager._m_think("hello")

        self.assertTrue(any("RuntimeWarning" in msg for msg in messages))


if __name__ == "__main__":
    unittest.main()
