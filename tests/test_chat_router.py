import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chat_router import ChatRouter


class TestChatRouter(unittest.TestCase):
    def test_general_chat_stays_on_chat_model(self):
        router = ChatRouter()
        decision = router.classify("Can you explain how the agent works?")
        self.assertEqual(decision.route_to, "summarizer")
        self.assertFalse(decision.use_main_model)

    def test_analysis_queries_use_main_model_context(self):
        router = ChatRouter()
        decision = router.classify("Analyze the latest job search results and tell me the best opportunity")
        self.assertEqual(decision.route_to, "summarizer")
        self.assertTrue(decision.use_main_model)

    def test_task_requests_route_to_manager(self):
        router = ChatRouter()
        decision = router.classify("Please fix the bug in main.py and update the changelog")
        self.assertEqual(decision.route_to, "manager")
        self.assertTrue(decision.use_main_model)

    def test_context_builder_includes_json_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "job_search_leads_report.json"), "w", encoding="utf-8") as fh:
                fh.write('{"best": "upwork", "score": 0.95}')
            with open(os.path.join(tmpdir, "notes.txt"), "w", encoding="utf-8") as fh:
                fh.write("plain text")

            router = ChatRouter()
            context = router.build_runtime_context(tmpdir, user_message="Tell me about the current job search")
            self.assertIn("job_search_leads_report.json", context)
            self.assertIn("upwork", context)
            self.assertNotIn("plain text", context)


if __name__ == "__main__":
    unittest.main()
