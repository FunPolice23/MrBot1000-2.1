import os
import sys
import tempfile
import unittest
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chat_router import ChatRouter
from agents.shared_context import SharedContext


class TestSharedResearchContext(unittest.TestCase):
    def test_chat_router_includes_shared_research_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path = str(Path(tmpdir) / "shared_context.json")
            os.environ["SHARED_CONTEXT_PATH"] = context_path
            try:
                shared_context = SharedContext(context_path)
                shared_context.update_research_snapshot({
                    "research_path": tmpdir,
                    "research_file_count": 3,
                    "research": "Key finding: use this context for better replies.",
                    "root": "root context",
                })

                router = ChatRouter()
                runtime_context = router.build_runtime_context(tmpdir, "What do you know?")

                self.assertIn("SHARED RESEARCH SNAPSHOT", runtime_context)
                self.assertIn("use this context", runtime_context)
            finally:
                os.environ.pop("SHARED_CONTEXT_PATH", None)

    def test_shared_context_concurrent_writes_preserve_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            context_path = str(Path(tmpdir) / "shared_context.json")
            shared_context = SharedContext(context_path)

            def writer(idx: int):
                for step in range(25):
                    shared_context.update_model_context(
                        f"model_{idx}",
                        current_task=f"task_{idx}_{step}",
                        reasoning_chain=[f"reason_{idx}_{step}"],
                    )
                    shared_context.add_event(
                        event_type="concurrency_test",
                        source=f"writer_{idx}",
                        data={"step": step},
                    )

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            state = shared_context._read_state()
            self.assertGreaterEqual(len(state.models), 6)
            self.assertGreater(len(state.recent_events), 0)
            self.assertLessEqual(len(state.recent_events), 100)


if __name__ == "__main__":
    unittest.main()
