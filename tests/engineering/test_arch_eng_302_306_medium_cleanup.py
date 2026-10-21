"""ARCH-ENG-302..306 — medium-tier cleanup, wiring and error visibility."""

from __future__ import annotations

import importlib.util
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[2]
FIX_IDS = ("ARCH-ENG-302", "ARCH-ENG-303", "ARCH-ENG-304",
           "ARCH-ENG-305", "ARCH-ENG-306")


class TestD02DeadCoreModules(unittest.TestCase):
    def test_recovery_and_account_profile_are_gone(self):
        self.assertIsNone(importlib.util.find_spec("agents.core.recovery"))
        self.assertIsNone(importlib.util.find_spec("agents.core.account_profile"))

    def test_architecture_boundary_checker_moved_to_test_support(self):
        from tests.support.architecture_boundaries import check_import_boundaries

        with tempfile.TemporaryDirectory() as tmp:
            bad = pathlib.Path(tmp) / "bad.py"
            bad.write_text("import PySide6\n", encoding="utf-8")
            violations = check_import_boundaries(
                tmp, ["bad.py"], {"bad.py": ("PySide6",)})
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].imported, "PySide6")

    def test_the_old_production_module_is_gone(self):
        self.assertIsNone(
            importlib.util.find_spec("agents.core.architecture_boundaries"))


class TestE01ChatRouterRemoved(unittest.TestCase):
    def test_chat_router_is_gone(self):
        self.assertIsNone(importlib.util.find_spec("agents.dialogue.chat_router"))

    def test_bounded_discussion_remains_executable(self):
        from agents.dialogue.discussion import (
            BoundedDiscussion, DiscussionPurpose, DiscussionTurn,
        )

        d = BoundedDiscussion("choose a platform", max_turns=2)
        self.assertTrue(d.add_turn(DiscussionTurn(
            speaker="analyst", summary="Upwork has the better fit",
            purpose=DiscussionPurpose.PROPOSE)))
        self.assertTrue(d.add_turn(DiscussionTurn(
            speaker="operator", summary="Use Upwork",
            purpose=DiscussionPurpose.CONCLUDE)))
        self.assertEqual(d.status.value, "resolved")


class TestO01CoderWorkerIsLive(unittest.TestCase):
    def test_tool_schema_allows_coder_to_draft_content(self):
        from agents.safety.tools import get_all_tools

        schema = next(t for t in get_all_tools()
                      if t["function"]["name"] == "propose_code_patch")
        self.assertNotIn("new_content", schema["function"]["parameters"]["required"])
        self.assertIn("issue", schema["function"]["parameters"]["properties"])

    def test_handler_uses_coder_worker_when_content_is_missing(self):
        from agents.safety import handlers

        class _Service:
            root_dir = str(REPO)

        keys = ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                "OPENROUTER_API_KEY", "GROQ_API_KEY")
        with patch("agents.services.code_patch_service.get_code_patch_service",
                   return_value=_Service()), \
             patch.dict(os.environ, {k: "" for k in keys}):
            out = handlers._tool_propose_code_patch({
                "target": "agents/example.py",
                "motivation": "fix a concrete defect",
            })
        self.assertIn("CoderWorker", out)
        self.assertIn("no model API key", out)


class TestR02SettingsErrorsAreVisible(unittest.TestCase):
    def test_collector_records_and_resets(self):
        from gui.error_collector import (
            gui_error_snapshot, record_gui_error, reset_gui_errors,
        )

        reset_gui_errors()
        record_gui_error("settings:test-section", ValueError("boom"))
        snap = gui_error_snapshot()
        self.assertEqual(snap["settings:test-section"]["count"], 1)
        self.assertIn("boom", snap["settings:test-section"]["last"])
        reset_gui_errors()
        self.assertEqual(gui_error_snapshot(), {})

    def test_save_settings_routes_its_ten_silent_handlers(self):
        source = (REPO / "main.py").read_text(encoding="utf-8")
        start = source.index("    def save_settings(self):")
        end = source.find("\n    def ", start + 10)
        body = source[start:end if end > 0 else None]
        self.assertGreaterEqual(body.count("record_gui_error("), 10)
        self.assertNotIn("        except Exception:\n            pass", body)


class TestP02LearningDashboard(unittest.TestCase):
    def test_every_readout_is_called(self):
        from app.earning_memory import EarningMemory

        path = tempfile.mktemp(suffix=".db")
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        memory = EarningMemory(db_path=path)
        dashboard = memory.learning_dashboard()
        self.assertGreaterEqual(len(dashboard), 15)
        for key in ("top_search_strategies", "best_performing_task_types",
                    "recurring_failure_causes", "get_memory_summary"):
            self.assertIn(key, dashboard)
            if isinstance(dashboard[key], dict):
                self.assertNotIn("error", dashboard[key], key)

    def test_dashboard_is_not_a_constant(self):
        from app.earning_memory import EarningMemory

        path = tempfile.mktemp(suffix=".db")
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        memory = EarningMemory(db_path=path)
        memory.remember_success("python", "Upwork", 100.0)
        dashboard = memory.learning_dashboard()
        self.assertIsInstance(dashboard["get_memory_summary"], dict)


if __name__ == "__main__":
    unittest.main()
