import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from earning_pipeline import Opportunity
from agents.workflow_planner import WorkflowPlanner


class TestWorkflowPlanner(unittest.TestCase):
    def test_upwork_plan_includes_application_delivery_and_submission_steps(self):
        planner = WorkflowPlanner()
        opportunity = Opportunity(
            id="upwork_1",
            source="upwork",
            platform="Upwork",
            title="Build Python automation",
            description="Need a Python developer to automate a workflow",
            url="https://www.upwork.com/jobs/123",
        )

        plan = planner.build_plan(opportunity)

        actions = [step.action for step in plan.steps]
        self.assertIn("apply", actions)
        self.assertIn("deliver", actions)
        self.assertIn("submit", actions)
        self.assertEqual(plan.platform, "upwork")

    def test_unknown_platform_falls_back_to_manual_research_plan(self):
        planner = WorkflowPlanner()
        opportunity = Opportunity(
            id="custom_1",
            source="dynamic",
            platform="Custom Market",
            title="Independent task",
            description="A custom lead that requires manual follow-up",
            url="https://example.com/task",
        )

        plan = planner.build_plan(opportunity)

        actions = [step.action for step in plan.steps]
        self.assertIn("research", actions)
        self.assertIn("manual_followup", actions)
        self.assertTrue(any("manual" in step.notes.lower() for step in plan.steps))


if __name__ == "__main__":
    unittest.main()
