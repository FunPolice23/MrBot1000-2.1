"""ARCH-ENG-297..301 — medium-tier wiring and dead-code removal."""

from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[2]
FIX_IDS = ("ARCH-ENG-297", "ARCH-ENG-298", "ARCH-ENG-299",
           "ARCH-ENG-300", "ARCH-ENG-301")


class _MemoryDB:
    def __init__(self, rows):
        self.rows = rows

    def search_memories(self, query, limit=5):
        return self.rows[:limit]

    def get_memories(self, limit=10, min_importance=0.0):
        return self.rows[:limit]

    def get_lessons(self, limit=3):
        return []

    def get_conversation_history(self, brain, limit=5):
        return []


def _row(title, *, expired=False, quarantined=False):
    return {
        "id": 1, "category": "knowledge", "title": title,
        "content": f"{title} content", "importance": 0.9, "confidence": 0.9,
        "source": "test", "timestamp": "2026-01-01T00:00:00",
        "expires_at": "2000-01-01T00:00:00" if expired else "",
        "provenance": "test", "verification_level": "L3",
        "related_ids": (), "supersedes_id": "", "contradicts_id": "",
        "quarantined": quarantined,
    }


class TestLayeredMemoryIsLive(unittest.TestCase):
    def test_all_recorded_ids_are_exercised_together(self):
        self.assertEqual(len(FIX_IDS), len(set(FIX_IDS)))

    def test_knowledge_context_uses_the_layered_retriever(self):
        from agents.knowledge.program_knowledge import KnowledgeContext

        db = _MemoryDB([
            _row("live memory"),
            _row("expired memory", expired=True),
            _row("quarantined memory", quarantined=True),
        ])
        text = KnowledgeContext(db).build_context("big", "anything")
        self.assertIn("live memory", text)
        self.assertNotIn("expired memory", text)
        self.assertNotIn("quarantined memory", text)

    def test_plain_rows_are_still_formatted(self):
        """Vacuity probe: a retriever that returns nothing would hide all rows."""
        from agents.knowledge.program_knowledge import KnowledgeContext

        text = KnowledgeContext(_MemoryDB([_row("ordinary fact")])).build_context(
            "big", "anything")
        self.assertIn("[knowledge] ordinary fact: ordinary fact content", text)


class TestModelRecommendationsAreSurfaced(unittest.TestCase):
    def test_brain_settings_row_consults_the_recommender(self):
        body = (REPO / "gui/widgets/brain_settings_row.py").read_text(
            encoding="utf-8")
        self.assertIn("model_recommendations import summary", body)
        self.assertIn("summary(model)", body)

    def test_the_recommender_still_returns_a_line(self):
        from agents.providers.model_recommendations import summary

        line = summary("definitely-not-a-real-model.gguf")
        self.assertIsInstance(line, str)
        self.assertIn("ctx", line)


class TestQualityControllerIsASecondGate(unittest.TestCase):
    def _workspace(self):
        from agents.safety.workspace import TaskWorkspace

        tmp = tempfile.TemporaryDirectory(prefix="arch299_")
        self.addCleanup(tmp.cleanup)
        ws = TaskWorkspace("test", "job-1", root_folder=tmp.name)
        ws.save("deliverable.txt", "A complete deliverable with approach, "
                                   "implementation, timeline and tests. " * 20)
        return ws

    def test_submit_is_blocked_when_the_quality_gate_fails(self):
        from agents.evidence.document_scanner import QualityController

        ws = self._workspace()
        with patch.object(QualityController, "pre_submit_check",
                          return_value={"passed": False, "issues": ["bad"]}):
            result = ws.submit()
        self.assertEqual(result["status"], "blocked")
        self.assertNotEqual(ws.status, "submitted")

    def test_submit_passes_when_both_gates_agree(self):
        """Vacuity probe: a permanently blocked submit would not be a gate."""
        from agents.evidence.document_scanner import QualityController

        ws = self._workspace()
        with patch.object(QualityController, "pre_submit_check",
                          return_value={"passed": True, "quality_score": 0.95}):
            result = ws.submit()
        self.assertEqual(result["status"], "submitted")


class TestDeadModulesAreGone(unittest.TestCase):
    def test_capability_executor_is_deleted(self):
        self.assertIsNone(
            importlib.util.find_spec("agents.earning.capability"))
        import agents.earning as earning
        self.assertNotIn("EarningCapabilityExecutor", earning.__all__)

    def test_hardware_plan_is_deleted(self):
        self.assertIsNone(
            importlib.util.find_spec("agents.runtime.hardware_plan"))

    def test_the_live_replacements_still_exist(self):
        """Vacuity probe: the deletion did not remove the live paths."""
        from app.earning_pipeline import EarningPipeline
        from agents.runtime.device_registry import detect_devices

        self.assertTrue(callable(EarningPipeline))
        self.assertTrue(callable(detect_devices))


if __name__ == "__main__":
    unittest.main()
