import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manager import ManagerThread


class TestManagerQueueLimits(unittest.TestCase):
    def setUp(self):
        self._old_max = os.environ.get("MANAGER_QUEUE_MAXSIZE")
        os.environ["MANAGER_QUEUE_MAXSIZE"] = "10"

    def tearDown(self):
        if self._old_max is None:
            os.environ.pop("MANAGER_QUEUE_MAXSIZE", None)
        else:
            os.environ["MANAGER_QUEUE_MAXSIZE"] = self._old_max

    def test_human_queue_drops_oldest_when_full(self):
        manager = ManagerThread(api_key="", worker=None, db=None)
        for i in range(11):
            manager.send_human_message(f"msg{i}")

        self.assertEqual(manager.human_queue.qsize(), 10)
        self.assertEqual(manager.human_queue.get_nowait(), "msg1")

    def test_task_queue_drops_oldest_when_full(self):
        manager = ManagerThread(api_key="", worker=None, db=None)
        for i in range(11):
            manager.queue_task(f"t{i}")

        self.assertEqual(manager.task_queue.qsize(), 10)
        self.assertEqual(manager.task_queue.get_nowait(), "t1")


if __name__ == "__main__":
    unittest.main()
