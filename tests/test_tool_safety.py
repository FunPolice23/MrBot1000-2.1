import unittest
from pathlib import Path

from agents.tool_safety import command_argv, resolve_command_cwd, resolve_project_path


class TestToolSafety(unittest.TestCase):
    def test_relative_paths_stay_inside_project(self):
        resolved = resolve_project_path("agents/tools.py")
        self.assertTrue(resolved.is_file())
        self.assertEqual(resolved, resolve_project_path(str(resolved)))

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_project_path("../../outside.txt", allow_missing=True)

    def test_command_is_parsed_without_shell_operators(self):
        self.assertEqual(command_argv("python -m pytest"), ["python", "-m", "pytest"])
        for command in ("python -m pytest | more", "echo ok > output.txt",
                        "python -c $(whoami)", "echo one & echo two"):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    command_argv(command)

    def test_command_cwd_is_project_bound(self):
        self.assertEqual(resolve_command_cwd(None), resolve_project_path("."))
        with self.assertRaises(ValueError):
            resolve_command_cwd(str(Path.home()))


if __name__ == "__main__":
    unittest.main()