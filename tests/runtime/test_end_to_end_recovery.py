import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agents.safety.approval import HumanApprovalQueue
from agents.services.autonomous_run_store import AutonomousRunStore
from agents.services.autonomous_loop import AutonomousLoop
from agents.safety.calling import execute_tool


class TestEndToEndRecovery(unittest.TestCase):
    def tearDown(self):
        HumanApprovalQueue.reset_singleton()

    def test_mutation_stops_at_approval_boundary(self):
        result = execute_tool("run_command", {"command": "echo must-not-run"})
        self.assertIn("PENDING APPROVAL", result)
        self.assertEqual(HumanApprovalQueue.instance().pending_count(), 1)

    def test_interrupted_run_is_recovered_as_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "runs.db")
            store = AutonomousRunStore(path)
            run_id = store.save_run(
                {
                    "run_id": "recovery-1",
                    "opportunity_id": "opp-recovery",
                    "status": "RUNNING",
                    "success": False,
                    "paid": False,
                    "payment_amount": 0,
                    "decision": "",
                    "decision_reason": "",
                    "explanation": "",
                    "stages": [],
                    "errors": [],
                },
                "opp-recovery",
            )
            store.recover_incomplete()
            recovered = store.get_run(run_id)
            self.assertEqual(recovered["status"], "FAILED")
            self.assertIn("restart", recovered["decision_reason"])

    def test_concurrency_limit_is_bounded_and_cancellation_is_observed(self):
        with patch.dict(os.environ, {"MRBOT_AUTONOMY_MAX_CONCURRENT": "1"}):
            loop = AutonomousLoop(SimpleNamespace())
        loop.cancel("opp-cancel")
        result = loop.run(SimpleNamespace(id="opp-cancel"))
        self.assertEqual(result.decision, "failed")
        self.assertIn("cancelled", result.decision_reason.lower())


if __name__ == "__main__":
    unittest.main()
