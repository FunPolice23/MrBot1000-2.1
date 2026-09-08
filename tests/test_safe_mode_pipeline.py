import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_pipeline import ActionPipeline, ProposedAction


class TestSafeModePipeline(unittest.TestCase):
    def test_safe_mode_skips_writing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = ActionPipeline(root_folder=tmpdir, log_fn=lambda _: None, safe_mode=True)
            action = ProposedAction(
                action_type="create_file",
                proposer="Tester",
                description="Create a dry-run file",
                target_path="example.txt",
                code="print('safe mode')",
            )

            result = pipeline.process(action)

            self.assertTrue(result.success)
            self.assertIn("safe mode", result.message.lower())
            self.assertFalse(Path(tmpdir, "example.txt").exists())

    def test_safe_path_blocks_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = ActionPipeline(root_folder=tmpdir, log_fn=lambda _: None, safe_mode=False)
            action = ProposedAction(
                action_type="create_file",
                proposer="Tester",
                description="escape attempt",
                target_path="..\\outside.txt",
                code="blocked",
            )

            result = pipeline.process(action)
            self.assertFalse(result.success)
            self.assertIn("Path escapes root folder", result.message)

    def test_safe_path_blocks_prefix_collision_sibling(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "proj"
            root.mkdir()
            sibling = Path(parent) / "proj-sibling"
            sibling.mkdir()

            pipeline = ActionPipeline(root_folder=str(root), log_fn=lambda _: None, safe_mode=False)
            escape_target = sibling / "evil.txt"
            rel = os.path.relpath(str(escape_target), str(root))

            action = ProposedAction(
                action_type="create_file",
                proposer="Tester",
                description="prefix collision escape",
                target_path=rel,
                code="blocked",
            )

            result = pipeline.process(action)
            self.assertFalse(result.success)
            self.assertIn("Path escapes root folder", result.message)
            self.assertFalse(escape_target.exists())

    def test_safe_path_allows_in_root_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = ActionPipeline(root_folder=tmpdir, log_fn=lambda _: None, safe_mode=False)
            action = ProposedAction(
                action_type="create_file",
                proposer="Tester",
                description="valid path",
                target_path="nested/ok.txt",
                code="ok",
            )

            result = pipeline.process(action)
            self.assertTrue(result.success)
            self.assertTrue(Path(tmpdir, "nested", "ok.txt").exists())


if __name__ == "__main__":
    unittest.main()
