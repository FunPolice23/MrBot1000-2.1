import unittest
from unittest import mock

from agents.moltbook_agent import (
    MOLTBOOK_REGISTER_URL,
    MOLTBOOK_SKILL_URL,
    MoltbookAgentCapability,
)


class _InstructionGate:
    def __init__(self, status="allowed"):
        self.status = status

    def fetch_instruction(self, url, **kwargs):
        self.url = url
        return mock.Mock(status=self.status, trusted=self.status == "allowed")


class TestMoltbookAgentCapability(unittest.TestCase):
    def test_reads_official_skill_before_planning(self):
        gate = _InstructionGate()
        capability = MoltbookAgentCapability(gate)
        instruction = capability.read_skill()
        self.assertTrue(instruction.trusted)
        self.assertEqual(gate.url, MOLTBOOK_SKILL_URL)

    def test_registration_waits_for_capability_approval(self):
        client = mock.Mock()
        capability = MoltbookAgentCapability(_InstructionGate(), client)
        plan = capability.plan_registration("MrBot", "An AI earning agent", "allowed")
        result = capability.register(plan)
        self.assertEqual(result["status"], "awaiting_approval")
        client.post.assert_not_called()

    def test_registration_returns_claim_details_without_api_key(self):
        client = mock.Mock()
        response = mock.Mock()
        response.json.return_value = {
            "agent": {
                "api_key": "must-not-leak",
                "claim_url": "https://www.moltbook.com/claim/test",
                "verification_code": "reef-test",
            }
        }
        response.raise_for_status.return_value = None
        client.post.return_value = response
        capability = MoltbookAgentCapability(_InstructionGate(), client)
        plan = capability.plan_registration("MrBot", "An AI earning agent", "allowed")
        result = capability.register(plan, capability_approved=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["claim_url"], "https://www.moltbook.com/claim/test")
        self.assertNotIn("api_key", result)
        client.post.assert_called_once_with(
            MOLTBOOK_REGISTER_URL,
            json={"name": "MrBot", "description": "An AI earning agent"},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )

    def test_incomplete_plan_is_blocked(self):
        capability = MoltbookAgentCapability(_InstructionGate())
        plan = capability.plan_registration("", "", "allowed")
        result = capability.register(plan, capability_approved=True)
        self.assertEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
