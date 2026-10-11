import unittest

from agents.safety.authorization import AuthorizedActionDispatcher
from agents.safety.gate import SafetyDecision


class TestAuthorizedActionDispatcher(unittest.TestCase):
    def test_read_only_dispatch_runs_handler(self):
        dispatcher = AuthorizedActionDispatcher()
        result = dispatcher.dispatch(
            "file_read", {"path": "README.md"}, lambda _authorization: "ok")
        self.assertEqual(result, "ok")

    def test_mutation_requires_explicit_approval(self):
        dispatcher = AuthorizedActionDispatcher()
        called = []
        result = dispatcher.dispatch(
            "file_write", {"path": "x"}, lambda _authorization: called.append(True),
        )
        self.assertIn("[PENDING APPROVAL]", result)
        self.assertEqual(called, [])

    def test_approved_mutation_runs_handler(self):
        dispatcher = AuthorizedActionDispatcher()
        result = dispatcher.dispatch(
            "file_write", {"path": "x"}, lambda _authorization: "approved",
            approved=True,
        )
        self.assertEqual(result, "approved")

    def test_unknown_action_is_blocked(self):
        result = AuthorizedActionDispatcher().authorize("not-a-tool", {})
        self.assertFalse(result.allowed)
        self.assertEqual(result.decision, SafetyDecision.BLOCKED)


if __name__ == "__main__":
    unittest.main()
